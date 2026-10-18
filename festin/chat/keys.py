"""Resolve the model API key. Never stored in the shared SQLite DB."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


def resolve_model_key(data_dir: str | Path, base_url: str) -> str:
    """Prefer env, then a 0600 model.key file next to the DB data dir."""
    host = urlparse(base_url).hostname
    if host == "openrouter.ai":
        for name in ("OPENROUTER_API_KEY", "FESTIN_MODEL_KEY"):
            value = os.environ.get(name, "").strip()
            if value:
                return value
    else:
        value = os.environ.get("FESTIN_MODEL_KEY", "").strip()
        if value:
            return value
    key_file = Path(data_dir) / "model.key"
    if key_file.is_file():
        return key_file.read_text(encoding="utf-8").strip()
    return ""
