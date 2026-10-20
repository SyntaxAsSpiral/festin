"""Load YAML literal-block documents. No YAML runtime.

Persona and tool text share the same on-disk form: `key: |` with two-space
body indent. Placeholders `{name}` are filled by the caller; unknown or
unfilled names raise.
"""

from __future__ import annotations

import re
from pathlib import Path

PERSONA_KEYS = ("system_prompt",)
DEFAULT_PERSONA = Path(__file__).resolve().parent.parent / "data" / "persona.yaml"

_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def load_blocks(path: str | Path) -> dict[str, str]:
    """Parse a file of YAML literal blocks into {key: body}."""
    source = Path(path)
    lines = source.read_text(encoding="utf-8").splitlines()
    blocks: dict[str, str] = {}
    key = None
    body: list[str] = []
    for line in lines:
        if key is None:
            if not line.strip():
                continue
            if line.endswith(": |") and " " not in line[:-3]:
                key = line[:-3]
                if key in blocks:
                    raise ValueError("Duplicate key: " + key)
                continue
            raise ValueError("Document must be YAML literal blocks (key: |).")
        if line.startswith("  "):
            body.append(line[2:])
        elif not line:
            body.append("")
        elif line.endswith(": |") and " " not in line[:-3]:
            blocks[key] = "\n".join(body).rstrip("\n")
            key = line[:-3]
            if key in blocks:
                raise ValueError("Duplicate key: " + key)
            body = []
        else:
            raise ValueError("Blocks must be indented by two spaces.")
    if key is not None:
        blocks[key] = "\n".join(body).rstrip("\n")
    return blocks


def fill_placeholders(text: str, values: dict[str, object]) -> str:
    """Replace `{name}` with str(values[name]). Unknown or missing names raise."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise ValueError("Unknown or unfilled placeholder: {" + name + "}")
        return str(values[name])

    return _PLACEHOLDER.sub(replace, text)


def load_persona(path: str | Path | None = None) -> dict[str, str]:
    source = Path(path) if path is not None else DEFAULT_PERSONA
    blocks = load_blocks(source)
    unknown = [name for name in blocks if name not in PERSONA_KEYS]
    if unknown:
        raise ValueError(
            "Unknown persona keys: " + ", ".join(unknown) + ". Use system_prompt only."
        )
    if "system_prompt" not in blocks:
        raise ValueError("Persona must define a system_prompt literal block.")
    return blocks


def persona(path: str | Path | None = None) -> str:
    return load_persona(path)["system_prompt"]
