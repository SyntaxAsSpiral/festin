"""Resolve the model API key. Never stored in the shared SQLite DB."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

KEY_NAME = "model.key"
_MAX_KEY = 4096


def model_key_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / KEY_NAME


def model_key_is_set(data_dir: str | Path) -> bool:
    """True when the 0600 file holds a key. Env keys do not flip this."""
    path = model_key_path(data_dir)
    try:
        return path.is_file() and bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def model_key_source(data_dir: str | Path, base_url: str) -> str:
    """Where the effective key comes from: 'env', 'file', or 'none'. Never the key."""
    if _host_key(base_url):
        return "env"
    if model_key_is_set(data_dir):
        return "file"
    return "none"


def write_model_key(data_dir: str | Path, key: str) -> None:
    """Store one line in model.key at mode 0600, or delete the file when empty.

    The write is a temp file in the same directory, mode 0600, then replace.
    """
    if not isinstance(key, str):
        raise ValueError("API key must be a string.")
    text = key.strip()
    if "\n" in text or "\r" in text or "\x00" in text:
        raise ValueError("The API key must be a single line.")
    if len(text) > _MAX_KEY:
        raise ValueError("That API key is too long.")
    directory = Path(data_dir)
    path = directory / KEY_NAME
    if not text:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise ValueError("Could not store the API key.") from exc
        return
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".model.key.", dir=directory)
    tmp = Path(tmp_name)
    owned = False
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            owned = True
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except OSError as exc:
        raise ValueError("Could not store the API key.") from exc
    finally:
        if not owned:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _key_from_env_file() -> str:
    """FESTIN_MODEL_KEY_FILE: a host secret holding only the key (e.g. /run/secrets/...)."""
    name = os.environ.get("FESTIN_MODEL_KEY_FILE", "").strip()
    if not name:
        return ""
    try:
        return Path(name).read_text(encoding="utf-8").strip()[:_MAX_KEY]
    except OSError:
        return ""


def _host_key(base_url: str) -> str:
    """A key the host set for Festin. Festin's own settings come first, so a
    generic OPENROUTER_API_KEY inherited from a login shell (another tool's key)
    never overrides the kitchen's: FESTIN_MODEL_KEY, then FESTIN_MODEL_KEY_FILE,
    then OPENROUTER_API_KEY for an openrouter.ai endpoint."""
    value = os.environ.get("FESTIN_MODEL_KEY", "").strip()
    if value:
        return value
    value = _key_from_env_file()
    if value:
        return value
    if urlparse(base_url).hostname == "openrouter.ai":
        return os.environ.get("OPENROUTER_API_KEY", "").strip()
    return ""


def resolve_model_key(data_dir: str | Path, base_url: str) -> str:
    """The host's key (see _host_key), else a 0600 model.key next to the DB."""
    value = _host_key(base_url)
    if value:
        return value
    key_file = model_key_path(data_dir)
    if key_file.is_file():
        return key_file.read_text(encoding="utf-8").strip()
    return ""
