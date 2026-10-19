"""Plain speech from a chat reply. Markup goes; paragraph breaks stay."""

from __future__ import annotations

import re

SPEECH_LIMIT = 4000


def speech_text(value) -> str:
    """Strip code, links, images, and emphasis. Keep paragraph breaks. Cap length."""
    text = str(value or "").replace("\r\n", "\n")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_#]+", "", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if not text:
        raise ValueError("Nothing to read.")
    if len(text) > SPEECH_LIMIT:
        raise ValueError("That reply is too long to read in one pass.")
    return text
