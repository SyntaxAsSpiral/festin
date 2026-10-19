"""Voice plugin: speech_text, speak cache/jobs, route hygiene."""

from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

import pytest

from festin.plugins import host
from festin.plugins.voice import speak, speech
from festin.plugins.voice.plugin import PLUGIN
from festin.schema import connect
from festin.server import KitchenServer


class Client:
    def __init__(self, port: int):
        self.port = port
        self.origin = "http://kitchen.example"

    def request(self, method, path, body=None, *, raw=False):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Origin": self.origin}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(payload))
        elif method in ("POST", "PUT"):
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = "0"
            payload = b"{}"
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        data = response.read()
        status = response.status
        conn.close()
        if raw:
            return status, data
        return status, json.loads(data.decode() or "null")


def _kitchen(blank_db):
    server = KitchenServer(
        ("127.0.0.1", 0),
        blank_db,
        origins=("http://kitchen.example",),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _enable(conn, settings=None):
    body = {"enabled": True}
    if settings is not None:
        body["settings"] = settings
    host.update_plugin(conn, "voice", body)


@pytest.fixture(autouse=True)
def _reset_speak_jobs():
    speak.reset_jobs_for_tests()
    yield
    speak.reset_jobs_for_tests()


def test_speech_text_strips_markup_and_keeps_paragraphs():
    spoken = speech.speech_text(
        "Bonjour. See the [book](https://example.test) and `not this code`.\n\n"
        "Hello **there**.\n\n\nExtra."
    )
    assert spoken == "Bonjour. See the book and not this code.\n\nHello there.\n\nExtra."
    with pytest.raises(ValueError, match="Nothing"):
        speech.speech_text("   ")
    with pytest.raises(ValueError, match="too long"):
        speech.speech_text("x" * (speech.SPEECH_LIMIT + 1))


def test_voice_plugin_off_by_default_and_no_keys_in_public(blank_db):
    conn = connect(blank_db)
    listed = host.list_plugins(conn)
    voice = next(p for p in listed if p["id"] == "voice")
    assert voice["enabled"] is False
    assert voice["name"] == "Voice"
    assert "local" not in next(f for f in voice["schema"] if f["key"] == "provider")["enum"]
    assert voice["settings"]["provider"] == "openrouter"
    settings_blob = json.dumps(voice["settings"]).lower()
    assert "api_key" not in settings_blob
    assert "token" not in settings_blob
    assert "sk-" not in settings_blob
    help_text = next(f for f in voice["schema"] if f["key"] == "provider").get("help") or ""
    assert "ELEVENLABS_API_KEY" in help_text
    conn.close()


def test_local_provider_only_when_host_env_set(blank_db, monkeypatch):
    monkeypatch.setenv("FESTIN_TTS_MODEL", "/tmp/model.gguf")
    monkeypatch.setenv("FESTIN_TTS_PROJECTOR", "/tmp/mmproj.gguf")
    monkeypatch.setenv("FESTIN_VOICE_REFERENCE", "/tmp/ref.wav")
    conn = connect(blank_db)
    voice = host.get_plugin(conn, "voice")
    providers = next(f for f in voice["schema"] if f["key"] == "provider")["enum"]
    assert providers[0] == "local"
    assert voice["settings"]["provider"] == "local"
    command = speak.voice_command(Path("/tmp/line.txt"), Path("/tmp/out.wav"))
    assert command[command.index("--tts-lang") + 1] == "fr"
    assert command[command.index("--temp") + 1] == "0.75"
    assert command[command.index("--tts-speaker-file") + 1] == "/tmp/ref.wav"
    assert "api_key" not in " ".join(command)
    conn.close()


def test_speak_cache_hit_and_job_join(blank_db, tmp_path, monkeypatch):
    calls = []

    def fake_render(spoken, dest, configured, *, data_dir):
        calls.append(spoken)
        time.sleep(0.05)
        dest.write_bytes(b"RIFF" + b"\0" * 80)

    monkeypatch.setattr(speak, "render_voice", fake_render)
    data_dir = tmp_path
    settings = {"provider": "openrouter", "model": "m", "voice": "v"}
    first = speak.speak("Hello **there**.", data_dir=data_dir, settings=settings)
    second = speak.speak("Hello **there**.", data_dir=data_dir, settings=settings)
    assert first["url"] == second["url"]
    assert first["status"] == "rendering"
    assert second["status"] == "rendering"
    key = first["url"].rsplit("/", 1)[-1]
    for _ in range(100):
        status, audio = speak.speech_result(key, data_dir=data_dir)
        if status == "ready":
            break
        time.sleep(0.02)
    assert status == "ready"
    assert audio.startswith(b"RIFF")
    assert calls == ["Hello there."]
    again = speak.speak("Hello **there**.", data_dir=data_dir, settings=settings)
    assert again["status"] == "ready"
    assert again["url"] == first["url"]
    assert calls == ["Hello there."]


def test_speak_busy_when_another_text_is_rendering(blank_db, tmp_path, monkeypatch):
    gate = threading.Event()

    def fake_render(spoken, dest, configured, *, data_dir):
        gate.wait(timeout=2)
        dest.write_bytes(b"RIFF" + b"\0" * 80)

    monkeypatch.setattr(speak, "render_voice", fake_render)
    settings = {"provider": "openrouter"}
    first = speak.speak("One.", data_dir=tmp_path, settings=settings)
    assert first["status"] == "rendering"
    with pytest.raises(ValueError, match="already preparing"):
        speak.speak("Two.", data_dir=tmp_path, settings=settings)
    gate.set()
    key = first["url"].rsplit("/", 1)[-1]
    for _ in range(100):
        status, _ = speak.speech_result(key, data_dir=tmp_path)
        if status == "ready":
            break
        time.sleep(0.02)
    assert status == "ready"


def test_speak_routes_over_http(blank_db, monkeypatch):
    def fake_render(spoken, dest, configured, *, data_dir):
        dest.write_bytes(b"RIFF" + b"\0" * 80)

    monkeypatch.setattr(speak, "render_voice", fake_render)
    server = _kitchen(blank_db)
    client = Client(server.server_address[1])
    try:
        status, off = client.request("POST", "/api/speak", {"text": "Hello."})
        assert status == 404
        assert "off" in off["error"].lower()

        conn = connect(server.db_path)
        _enable(conn, {"provider": "openrouter", "model": "m", "voice": "v"})
        conn.close()

        status, first = client.request("POST", "/api/speak", {"text": "Hello **kitchen**."})
        assert status in (200, 202)
        assert first["url"].startswith("/api/speak/")
        key = first["url"].rsplit("/", 1)[-1]

        for _ in range(50):
            status, body = client.request("GET", first["url"] + "?status=1")
            if status == 200 and body.get("status") == "ready":
                break
            assert status == 202
            time.sleep(0.02)
        assert status == 200

        status, audio = client.request("GET", first["url"], raw=True)
        assert status == 200
        assert audio.startswith(b"RIFF")

        status, again = client.request("POST", "/api/speak", {"text": "Hello **kitchen**."})
        assert status == 200
        assert again["status"] == "ready"
        assert again["url"] == first["url"]

        status, missing = client.request("GET", "/api/speak/" + ("0" * 64) + "?status=1")
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()


def test_put_voice_settings_rejects_unknown_provider(blank_db):
    server = _kitchen(blank_db)
    client = Client(server.server_address[1])
    try:
        status, body = client.request(
            "PUT",
            "/api/plugins/voice",
            {"enabled": True, "settings": {"provider": "acme"}},
        )
        assert status == 400
        assert "provider" in body["error"].lower()
        status, saved = client.request(
            "PUT",
            "/api/plugins/voice",
            {"enabled": True, "settings": {"provider": "openrouter", "model": "x", "voice": "y"}},
        )
        assert status == 200
        assert saved["settings"]["provider"] == "openrouter"
        assert saved["settings"]["model"] == "x"
        assert "token" not in saved["settings"]
        assert "apiKey" not in saved["settings"]
        assert "key" not in saved["settings"]
    finally:
        server.shutdown()
        server.server_close()


def test_plugin_object_shape():
    assert PLUGIN.id == "voice"
    assert PLUGIN.actions() == {}
    assert PLUGIN.feed()["localConfigured"] is False
