"""Cooking photos on disk under <data_dir>/photos/."""

from __future__ import annotations

import base64
import io
import uuid
from pathlib import Path


def photos_dir(data_dir: str | Path) -> Path:
    path = Path(data_dir) / "photos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_photos(images, data_dir: str | Path) -> list[str]:
    """Decode data-URLs into data_dir/photos/. Return /photos/<file> paths."""
    from PIL import Image

    if not isinstance(images, list) or len(images) > 4:
        raise ValueError("Attach up to four photos.")
    prepared = []
    for raw in images:
        if not isinstance(raw, str) or len(raw) > 15000000:
            raise ValueError("Each photo must be under 10 MB.")
        try:
            header, encoded = raw.split(",", 1)
            blob = base64.b64decode(encoded, validate=True)
            if len(blob) > 10 * 1024 * 1024:
                raise ValueError("Photo too large")
            with Image.open(io.BytesIO(blob)) as im:
                if im.width * im.height > 40000000:
                    raise ValueError("Photo dimensions too large")
                fmt = im.format
                im.verify()
            ext = {"JPEG": ".jpg", "MPO": ".jpg", "PNG": ".png", "WEBP": ".webp"}[fmt]
        except Exception as exc:
            raise ValueError(
                "Use a valid JPEG, PNG or WebP cooking photo under 10 MB."
            ) from exc
        prepared.append((blob, ext))
    root = photos_dir(data_dir)
    paths = []
    for blob, ext in prepared:
        name = str(uuid.uuid4()) + ext
        (root / name).write_bytes(blob)
        paths.append("/photos/" + name)
    return paths


def photo_file(data_dir: str | Path, ref: str) -> Path:
    """Resolve a /photos/… or bare name to a file under data_dir/photos/."""
    name = Path(ref).name
    path = (photos_dir(data_dir) / name).resolve()
    root = photos_dir(data_dir).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Choose a photo already shared in chat.")
    return path


def model_image_parts(content: str, photo_refs: list[str], data_dir: str | Path) -> list[dict]:
    """Build multimodal content parts; shrink large originals for the provider."""
    from PIL import Image, ImageOps

    parts: list[dict] = [
        {
            "type": "text",
            "text": content
            + "\n\nPhoto references (in image order): "
            + ", ".join(photo_refs),
        }
    ]
    for name in photo_refs:
        path = photo_file(data_dir, name)
        mime = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[path.suffix]
        blob = path.read_bytes()
        with Image.open(io.BytesIO(blob)) as im:
            if max(im.size) > 2048 or len(blob) > 1024 * 1024:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((2048, 2048))
                output = io.BytesIO()
                im.save(output, format="JPEG", quality=85)
                blob, mime = output.getvalue(), "image/jpeg"
        parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:" + mime + ";base64," + base64.b64encode(blob).decode()
                },
            }
        )
    return parts
