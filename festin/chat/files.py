"""Attached text documents under <data_dir>/files/ (sha256-named)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

# On-disk names: hex digest plus a short extension. Matches server FILE_NAME.
_STORED_NAME = re.compile(r"^[0-9a-f]{64}\.(md|txt)$")
_EXT = {".md": ".md", ".markdown": ".md", ".txt": ".txt", ".text": ".txt"}


def files_dir(data_dir: str | Path) -> Path:
    path = Path(data_dir) / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_files(items, data_dir: str | Path) -> list[dict]:
    """Persist UTF-8 documents. Return [{path, name}] for message refs."""
    if not isinstance(items, list):
        raise ValueError("Attached files must be a list.")
    if len(items) > 20:
        raise ValueError("Attach fewer documents in one message.")
    prepared = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each attached file needs a name and text.")
        name = _clean_name(item.get("name"))
        text = _clean_text(item.get("text"))
        blob = text.encode("utf-8")
        digest = hashlib.sha256(blob).hexdigest()
        ext = _extension(name)
        stored = digest + ext
        prepared.append((stored, name, blob))
    root = files_dir(data_dir)
    out = []
    for stored, name, blob in prepared:
        path = root / stored
        if not path.is_file():
            path.write_bytes(blob)
        out.append({"path": "/files/" + stored, "name": name})
    return out


def file_path(data_dir: str | Path, ref: str) -> Path:
    """Resolve /files/… or bare stored name under data_dir/files/."""
    name = Path(ref).name
    if not _STORED_NAME.match(name):
        raise ValueError("Choose a file already attached in chat.")
    path = (files_dir(data_dir) / name).resolve()
    root = files_dir(data_dir).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Choose a file already attached in chat.")
    return path


def read_file_text(data_dir: str | Path, ref: str) -> str:
    path = file_path(data_dir, ref)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("That file is not valid UTF-8 text.") from exc


def model_file_block(ref: dict, data_dir: str | Path) -> str:
    """Framed document text for the model turn."""
    name = ref.get("name") if isinstance(ref, dict) else None
    path = ref.get("path") if isinstance(ref, dict) else None
    if not isinstance(name, str) or not name.strip():
        name = Path(path).name if isinstance(path, str) else "document"
    if not isinstance(path, str):
        raise ValueError("Attached file is missing its path.")
    body = read_file_text(data_dir, path)
    return "Attached file: " + name.strip() + "\n" + body


def _clean_name(value) -> str:
    text = " ".join(str(value or "").split())
    if not text or len(text) > 200:
        raise ValueError("Give each attached file a name under 200 characters.")
    return text


def _clean_text(value) -> str:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("That file is not valid UTF-8 text.") from exc
    if not isinstance(value, str):
        raise ValueError("That file is not valid UTF-8 text.")
    if "\x00" in value:
        raise ValueError("That file is not valid UTF-8 text.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("That file is not valid UTF-8 text.") from exc
    return value


def _extension(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return _EXT.get(suffix, ".txt")
