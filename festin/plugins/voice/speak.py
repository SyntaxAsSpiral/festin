"""Render and cache spoken replies. One job at a time; same text joins."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from festin.chat.keys import resolve_model_key
from festin.plugins.voice.speech import speech_text

TTS_MODEL_ENV = "FESTIN_TTS_MODEL"
TTS_PROJECTOR_ENV = "FESTIN_TTS_PROJECTOR"
VOICE_REFERENCE_ENV = "FESTIN_VOICE_REFERENCE"
ELEVENLABS_KEY_ENV = "ELEVENLABS_API_KEY"

DEFAULT_OPENROUTER_MODEL = "deepgram/flux-tts:free"
DEFAULT_OPENROUTER_VOICE = "flux-gemma-en"
DEFAULT_ELEVEN_MODEL = "eleven_multilingual_v2"

SPEAK_LOCK = threading.Lock()
SPEAK_ACTIVE: str | None = None
SPEAK_JOBS: dict[str, str] = {}

_SHA = re.compile(r"^[0-9a-f]{64}$")


def local_tts_configured() -> bool:
    return all(
        os.environ.get(name, "").strip()
        for name in (TTS_MODEL_ENV, TTS_PROJECTOR_ENV, VOICE_REFERENCE_ENV)
    )


def voice_cache(data_dir: Path) -> Path:
    folder = Path(data_dir) / "voice"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def configured_voice(settings: dict | None) -> dict:
    """Public voice settings used for rendering and the cache key. No secrets."""
    raw = settings or {}
    provider = str(raw.get("provider") or "").strip() or (
        "local" if local_tts_configured() else "openrouter"
    )
    if provider == "elevenlabs":
        return {
            "provider": "elevenlabs",
            "base_url": "https://api.elevenlabs.io/v1",
            "model": str(raw.get("model") or DEFAULT_ELEVEN_MODEL).strip() or DEFAULT_ELEVEN_MODEL,
            "voice": str(raw.get("voice") or "").strip(),
        }
    if provider == "local":
        if not local_tts_configured():
            raise ValueError(
                "Local voice is not configured on the host "
                "(set FESTIN_TTS_MODEL, FESTIN_TTS_PROJECTOR, and FESTIN_VOICE_REFERENCE)."
            )
        return {"provider": "local"}
    # openrouter (and unknown → openrouter)
    return {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": str(raw.get("model") or DEFAULT_OPENROUTER_MODEL).strip()
        or DEFAULT_OPENROUTER_MODEL,
        "voice": str(raw.get("voice") or DEFAULT_OPENROUTER_VOICE).strip()
        or DEFAULT_OPENROUTER_VOICE,
    }


def cache_key(spoken: str, configured: dict) -> str:
    payload = json.dumps(
        {"speech": spoken, "voice": configured},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def voice_command(prompt_file: Path, out_file: Path) -> list[str]:
    """llama-tts argv. Paths come from host env; sampling flags match live."""
    model = os.environ.get(TTS_MODEL_ENV, "").strip()
    projector = os.environ.get(TTS_PROJECTOR_ENV, "").strip()
    reference = os.environ.get(VOICE_REFERENCE_ENV, "").strip()
    if not (model and projector and reference):
        raise ValueError(
            "Local voice is not configured on the host "
            "(set FESTIN_TTS_MODEL, FESTIN_TTS_PROJECTOR, and FESTIN_VOICE_REFERENCE)."
        )
    return [
        "llama-tts",
        "-m",
        model,
        "-mm",
        projector,
        "-f",
        str(prompt_file),
        "--tts-lang",
        "fr",
        "--tts-speaker-file",
        reference,
        "-c",
        "4096",
        "-ngl",
        "99",
        "-n",
        "3072",
        "--temp",
        "0.75",
        "--top-k",
        "50",
        "--top-p",
        "1.0",
        "--min-p",
        "0",
        "--repeat-penalty",
        "1.0",
        "--seed",
        "210921",
        "-o",
        str(out_file),
    ]


def render_local_voice(spoken: str, dest: Path) -> None:
    cache = dest.parent
    prompt = cache / (dest.stem + ".txt")
    partial = cache / (dest.stem + ".part.wav")
    prompt.write_text(spoken + "\n", encoding="utf-8")
    try:
        # No timeout: TTS may take as long as it needs.
        proc = subprocess.run(
            voice_command(prompt, partial),
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise ValueError("The voice could not be rendered.") from exc
    if proc.returncode != 0 or not partial.is_file() or partial.stat().st_size <= 44:
        partial.unlink(missing_ok=True)
        # The cook sees a plain line; the host log keeps llama-tts's own words.
        print(proc.stderr[-2000:], file=sys.stderr)
        raise ValueError("The voice could not be rendered.")
    partial.replace(dest)


def _cloud_request(spoken: str, configured: dict, *, data_dir: Path) -> Request:
    provider = configured["provider"]
    base = configured["base_url"].rstrip("/")
    if provider == "elevenlabs":
        key = os.environ.get(ELEVENLABS_KEY_ENV, "").strip()
        if not key:
            raise ValueError("ElevenLabs is not configured on the host (set ELEVENLABS_API_KEY).")
        voice = configured.get("voice") or ""
        if not voice:
            raise ValueError("Choose an ElevenLabs voice in Settings → Plugins.")
        url = base + "/text-to-speech/" + quote(voice, safe="") + "?output_format=mp3_44100_128"
        payload = {"text": spoken, "model_id": configured["model"]}
        headers = {
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
            "xi-api-key": key,
        }
    else:
        key = resolve_model_key(data_dir, configured["base_url"])
        if not key:
            raise ValueError("Add a model API key for OpenRouter speech.")
        url = base + "/audio/speech"
        payload = {
            "model": configured["model"],
            "input": spoken,
            "voice": configured["voice"],
            "response_format": "mp3",
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
            "Authorization": "Bearer " + key,
        }
    return Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")


def render_cloud_voice(spoken: str, dest: Path, configured: dict, *, data_dir: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial_audio = dest.with_name(dest.stem + ".part.audio")
    partial_wav = dest.with_name(dest.stem + ".part.wav")
    try:
        # No timeout on the TTS HTTP call or on ffmpeg.
        with urlopen(_cloud_request(spoken, configured, data_dir=data_dir)) as response:
            audio = response.read(50 * 1024 * 1024 + 1)
        if not audio or len(audio) > 50 * 1024 * 1024:
            raise ValueError("The cloud voice returned an invalid audio file.")
        partial_audio.write_bytes(audio)
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(partial_audio),
                "-ac",
                "1",
                "-ar",
                "24000",
                "-c:a",
                "pcm_s16le",
                str(partial_wav),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not partial_wav.is_file() or partial_wav.stat().st_size <= 44:
            print(proc.stderr[-2000:], file=sys.stderr)
            raise ValueError("The cloud voice returned audio that could not be played.")
        partial_wav.replace(dest)
    except HTTPError as exc:
        raise ValueError(f"The cloud voice rejected the reading (HTTP {exc.code}).") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("The cloud voice could not be reached.") from None
    finally:
        partial_audio.unlink(missing_ok=True)
        partial_wav.unlink(missing_ok=True)


def render_voice(spoken: str, dest: Path, configured: dict, *, data_dir: Path) -> None:
    if configured["provider"] == "local":
        return render_local_voice(spoken, dest)
    return render_cloud_voice(spoken, dest, configured, data_dir=data_dir)


def _finish_job(key: str, spoken: str, dest: Path, configured: dict, data_dir: Path) -> None:
    global SPEAK_ACTIVE
    try:
        render_voice(spoken, dest, configured, data_dir=data_dir)
        status = "ready"
    except Exception as exc:  # noqa: BLE001 - surface as job error text
        status = str(exc) if isinstance(exc, ValueError) else "The voice could not be rendered."
    with SPEAK_LOCK:
        SPEAK_JOBS[key] = status
        SPEAK_ACTIVE = None


def speak(text, *, data_dir: Path, settings: dict | None) -> dict:
    """Start or join a reading. Cache hit returns ready; else rendering."""
    global SPEAK_ACTIVE
    spoken = speech_text(text)
    configured = configured_voice(settings)
    key = cache_key(spoken, configured)
    dest = voice_cache(data_dir) / (key + ".wav")
    if dest.is_file() and dest.stat().st_size > 44:
        return {"status": "ready", "url": "/api/speak/" + key}
    with SPEAK_LOCK:
        if SPEAK_JOBS.get(key) == "rendering":
            return {"status": "rendering", "url": "/api/speak/" + key}
        if SPEAK_ACTIVE:
            raise ValueError("Babette is already preparing another reading.")
        SPEAK_ACTIVE = key
        SPEAK_JOBS[key] = "rendering"
    try:
        threading.Thread(
            target=_finish_job,
            args=(key, spoken, dest, configured, Path(data_dir)),
            daemon=True,
        ).start()
    except Exception:
        with SPEAK_LOCK:
            SPEAK_ACTIVE = None
            SPEAK_JOBS.pop(key, None)
        raise
    return {"status": "rendering", "url": "/api/speak/" + key}


def speech_result(key: str, *, data_dir: Path) -> tuple[str, bytes | str | None]:
    """Return (status, payload). status is ready|rendering|error|missing."""
    if not _SHA.fullmatch(key or ""):
        return "missing", None
    dest = voice_cache(data_dir) / (key + ".wav")
    if dest.is_file() and dest.stat().st_size > 44:
        return "ready", dest.read_bytes()
    with SPEAK_LOCK:
        status = SPEAK_JOBS.get(key)
    if status == "rendering":
        return "rendering", None
    if status and status != "ready":
        return "error", status
    return "missing", None


def reset_jobs_for_tests() -> None:
    """Clear in-flight state between tests."""
    global SPEAK_ACTIVE
    with SPEAK_LOCK:
        SPEAK_ACTIVE = None
        SPEAK_JOBS.clear()
