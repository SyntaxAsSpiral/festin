"""Load Babette's system_prompt from a YAML literal block. No YAML runtime."""

from __future__ import annotations

from pathlib import Path

PERSONA_KEYS = ("system_prompt",)
DEFAULT_PERSONA = Path(__file__).resolve().parent.parent / "data" / "persona.yaml"


def load_persona(path: str | Path | None = None) -> dict[str, str]:
    source = Path(path) if path is not None else DEFAULT_PERSONA
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
                    raise ValueError("Duplicate persona key: " + key)
                continue
            raise ValueError("Persona must be YAML literal blocks (key: |).")
        if line.startswith("  "):
            body.append(line[2:])
        elif not line:
            body.append("")
        elif line.endswith(": |") and " " not in line[:-3]:
            blocks[key] = "\n".join(body).rstrip("\n")
            key = line[:-3]
            if key in blocks:
                raise ValueError("Duplicate persona key: " + key)
            body = []
        else:
            raise ValueError("Persona blocks must be indented by two spaces.")
    if key is not None:
        blocks[key] = "\n".join(body).rstrip("\n")
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
