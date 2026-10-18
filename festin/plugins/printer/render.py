"""Le Festin compositor (design approved 2026-09-05; spacing approved 2026-09-06).

One cartouche, serif in the raster, vegetable plates, Celtic head/foot
at ~168 dots. Gray L for hatch; type fill=0. Do not crush then bleach
the gilding. Do not lace every day.

Fonts resolve when a slip is drawn. Importing this module does not need them,
so a kitchen with the printer off still starts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
PLATES = ROOT / "plates"
W = 576
HEADER_H = 168
TITLE_WEEK_GAP = 28  # Extra air below the title; original spacing was 4 dots.
WRITE_IN_H = 80  # ~10 mm; blank nights stay empty for a pen

_FONT_PATHS: dict[str, str] = {}


def locate_font(filename: str) -> str:
    cached = _FONT_PATHS.get(filename)
    if cached:
        return cached
    candidates = []
    for key in ("FESTIN_FONT_DIR", "HOLIDAY_FONT_DIR"):
        extra = os.environ.get(key)
        if extra:
            candidates.append(Path(extra) / filename)
    candidates.append(Path("/usr/share/fonts/truetype/liberation") / filename)
    candidates.append(Path("/usr/share/fonts/truetype/liberation2") / filename)
    for path in candidates:
        if path.is_file():
            _FONT_PATHS[filename] = str(path)
            return _FONT_PATHS[filename]
    found = _from_fontconfig(filename)
    if found:
        _FONT_PATHS[filename] = found
        return found
    raise FileNotFoundError("Missing Liberation Serif font: " + filename)


def _from_fontconfig(filename: str) -> str | None:
    if shutil.which("fc-list") is None:
        return None
    try:
        out = subprocess.run(
            ["fc-list", "-f", "%{file}\n", "Liberation Serif"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.stdout.splitlines():
        if Path(line).name == filename and Path(line).is_file():
            return line
    return None


def serif() -> str:
    return locate_font("LiberationSerif-Regular.ttf")


def serif_bold() -> str:
    return locate_font("LiberationSerif-Bold.ttf")


def serif_italic() -> str:
    return locate_font("LiberationSerif-Italic.ttf")


def flatten(im):
    if im.mode == "RGBA":
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    return im.convert("L")


def paper_white(g, paper=240, ink=0.72):
    g = ImageOps.autocontrast(g, cutoff=1)
    g = ImageEnhance.Contrast(g).enhance(1.25)
    return g.point(lambda p: 255 if p >= paper else 255 - int((255 - p) * ink))


def dense_crop(g, frac=0.08, pad=6):
    hist = [
        sum(255 - g.getpixel((x, y)) for x in range(0, g.width, 3))
        for y in range(g.height)
    ]
    peak = max(hist) if hist else 1
    rows = [i for i, v in enumerate(hist) if v > peak * frac]
    if not rows:
        box = g.point(lambda p: 255 if p < 250 else 0).getbbox() or (0, 0, g.width, g.height)
        return g.crop(box)
    y0, y1 = max(0, rows[0] - pad), min(g.height, rows[-1] + 1 + pad)
    cols = [
        sum(255 - g.getpixel((x, y)) for y in range(y0, y1, 2))
        for x in range(g.width)
    ]
    peakc = max(cols) if cols else 1
    xs = [i for i, v in enumerate(cols) if v > peakc * frac]
    x0, x1 = (max(0, xs[0] - pad), min(g.width, xs[-1] + 1 + pad)) if xs else (0, g.width)
    return g.crop((x0, y0, x1, y1))


def fit_w(im, width):
    h = max(1, round(im.height * width / im.width))
    return im.resize((width, h), Image.Resampling.LANCZOS)


def plate_veg(path):
    with Image.open(path) as opened:
        return dense_crop(paper_white(flatten(opened), paper=242, ink=0.9), 0.04, 8)


def plate_ornament(path, frac=0.10):
    with Image.open(path) as opened:
        g = paper_white(flatten(opened), paper=238, ink=0.58)
    g = ImageEnhance.Brightness(g).enhance(1.08)
    return dense_crop(g, frac, 6)


def band_header(path):
    """Full-width head band: ornament, fit to the dinner inner width, then HEADER_H tall."""
    header = plate_ornament(path, 0.08)
    header = fit_w(header, W - 28 * 2 + 16)
    if header.height != HEADER_H:
        header = header.resize((header.width, HEADER_H), Image.Resampling.LANCZOS)
    return header


def band_copies(path):
    """Top and foot copies of one band. The flat edge faces the outer edge of the slip.

    flat_edge bottom flips the top copy and leaves the foot as drawn.
    top or none keeps today's drawing on top and flips the foot.
    """
    name = Path(path).name
    found = None
    rows = list(json.loads((PLATES / "catalog.json").read_text()))
    rows.extend(json.loads((PLATES / "bands.json").read_text()).get("bands") or [])
    for row in rows:
        if row.get("file") != name or "flat_edge" not in row:
            continue
        edge = row["flat_edge"]
        if edge not in ("bottom", "top", "none"):
            raise ValueError("Bad flat_edge for " + name)
        if found is not None and found != edge:
            raise ValueError("flat_edge disagrees for " + name)
        found = edge
    band = band_header(path)
    flipped = band.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    if found == "bottom":
        return flipped, band
    return band, flipped


def multiply(dst, src, xy):
    x, y = xy
    w, h = src.size
    if x < 0 or y < 0:
        return
    if x + w > dst.width:
        src = src.crop((0, 0, dst.width - x, h))
        w = src.width
    if y + h > dst.height:
        src = src.crop((0, 0, w, dst.height - y))
        h = src.height
    region = dst.crop((x, y, x + w, y + h))
    dst.paste(ImageChops.multiply(region, src), (x, y))


def text_size(text, font):
    d = ImageDraw.Draw(Image.new("L", (W, 240), 255))
    left, top, right, bottom = d.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def wrap(text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if text_size(trial, font)[0] <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def render(days, week_text, output, closing_quote="Pour les dames de la maison.", plates=None):
    chosen = plates or {}
    top = plate_veg(PLATES / chosen.get("top", "3.jpg"))
    bot = plate_veg(PLATES / chosen.get("bottom", "1.jpg"))
    corner = plate_ornament(PLATES / "corner.jpg", 0.06)
    header, foot = band_copies(PLATES / chosen.get("header", "header.jpg"))

    inset = 28
    inner_w = W - inset * 2
    top_i = fit_w(top, inner_w)
    bot_i = fit_w(bot, inner_w)
    corner = fit_w(corner, 112)

    font_title = ImageFont.truetype(serif_bold(), 84)
    font_week = ImageFont.truetype(serif_italic(), 42)
    font_day = ImageFont.truetype(serif_bold(), 48)
    font_dish = ImageFont.truetype(serif(), 45)
    font_close = ImageFont.truetype(serif_italic(), 39)
    max_text = inner_w - 8
    title_lines = wrap("LE FESTIN", font_title, max_text)
    week_lines = wrap(week_text, font_week, max_text)
    close_lines = wrap(closing_quote, font_close, max_text)

    edge = 14
    height = edge + header.height + 8 + top_i.height + 14
    height += sum(text_size(t, font_title)[1] + 4 for t in title_lines) + TITLE_WEEK_GAP + 4
    height += sum(text_size(t, font_week)[1] + 4 for t in week_lines) + 16
    for day, dish in days:
        height += text_size(day, font_day)[1] + 8
        if dish.strip():
            dish_lines = wrap(dish, font_dish, max_text)
            height += sum(text_size(t, font_dish)[1] + 6 for t in dish_lines) + 18
        else:
            height += WRITE_IN_H + 18
    height += 8 + bot_i.height + 12
    height += sum(text_size(t, font_close)[1] + 4 for t in close_lines) + edge + header.height

    canvas = Image.new("L", (W, height), 255)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([6, 6, W - 7, height - 7], outline=0, width=3)
    draw.rectangle([12, 12, W - 13, height - 13], outline=90, width=1)

    hx = (W - header.width) // 2
    multiply(canvas, header, (hx, 8))
    multiply(canvas, foot, (hx, height - foot.height - 8))
    multiply(canvas, corner.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (4, 4))
    multiply(canvas, corner, (W - corner.width - 4, 4))
    multiply(canvas, corner.transpose(Image.Transpose.ROTATE_180), (4, height - corner.height - 4))
    multiply(
        canvas,
        corner.transpose(Image.Transpose.FLIP_TOP_BOTTOM),
        (W - corner.width - 4, height - corner.height - 4),
    )

    x0 = inset
    y = edge + header.height + 2
    canvas.paste(top_i, (x0 + (inner_w - top_i.width) // 2, y))
    y += top_i.height + 12
    for line in title_lines:
        tw, th = text_size(line, font_title)
        draw.text((x0 + (inner_w - tw) / 2, y), line, font=font_title, fill=0)
        y += th + 4
    y += TITLE_WEEK_GAP
    for line in week_lines:
        tw, th = text_size(line, font_week)
        draw.text((x0 + (inner_w - tw) / 2, y), line, font=font_week, fill=0)
        y += th + 4
    y += 16
    for day, dish in days:
        draw.text((x0 + 4, y), day, font=font_day, fill=0)
        y += text_size(day, font_day)[1] + 6
        if dish.strip():
            for line in wrap(dish, font_dish, max_text):
                draw.text((x0 + 4, y), line, font=font_dish, fill=0)
                y += text_size(line, font_dish)[1] + 6
            y += 16
        else:
            rule_y = y + WRITE_IN_H - 14
            draw.line([(x0 + 4, rule_y), (x0 + inner_w - 8, rule_y)], fill=150, width=2)
            y += WRITE_IN_H + 16
    canvas.paste(bot_i, (x0 + (inner_w - bot_i.width) // 2, y))
    y += bot_i.height + 12
    for line in close_lines:
        tw, th = text_size(line, font_close)
        draw.text((x0 + (inner_w - tw) / 2, y), line, font=font_close, fill=0)
        y += th + 4

    output = Path(output)
    canvas.save(output)
    output.with_suffix(".md").write_text(f"![le festin]({output.name})\n")
