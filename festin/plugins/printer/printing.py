"""Raster slips: approved dinner layout, and matching recipe/note stationery.

Plate ids stay the live catalog ids. Image files are the artist originals
(seasonal names) plus the four compositor pieces that folder does not hold:
corner.jpg, header.jpg, 1.jpg, 3.jpg.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from festin.plugins.printer import render as feast

DEFAULT_SLIP_QUOTE = "Pour les dames de la maison."
DEFAULT_SLIP_TITLE = "Le Festin"
SLOTS = ("top", "bottom", "header", "pantry")
PLATES = feast.PLATES
# Stride and offset differ so a new week does not slide every slot together.
TURN = {"top": (1, 0), "bottom": (3, 1), "header": (3, 2), "pantry": (1, 3)}
DAY_LABELS = {
    "sat": "Saturday",
    "sun": "Sunday",
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
}

# A sub-heading is a short capital clause and its colon, at the start of a line or
# just after a sentence. "For filling:" in a one-paragraph method qualifies; a
# mid-phrase colon, a 6:1 ratio, and a 6:30 do not, because the colon is not
# followed by a space or the clause fails the checks below.
HEADING_RE = re.compile(r"(?:^|(?<=[.!?]\s))([A-Z](?:[^:!.?\n]{0,28}[^\s:!.?])?):(?=\s|$)")
TEMP_RE = re.compile(
    r"(?<!\d)(\d{3}(?:\s*°(?:\s*F)?|\s+degrees|\s+F))(?!\w)",
    re.IGNORECASE,
)
DURATION_RE = re.compile(
    r"(?<![\d./])(\d+(?:\.\d+)?(?:\s*(?:to|–|-)\s*\d+(?:\.\d+)?)?\s+(?:minutes|minute|mins|min|hours|hour|hrs|hr))\b",
    re.IGNORECASE,
)
_CLOCK_RE = re.compile(r"\d\s*:\s*\d|\b\d{1,2}:\d{2}\b|\b(?:a\.?m\.?|p\.?m\.?)\b", re.IGNORECASE)


def plate_catalog():
    path = PLATES / "catalog.json"
    rows = json.loads(path.read_text())
    seen = set()
    for row in rows:
        key = (row["slot"], row["id"])
        if row["slot"] not in SLOTS or key in seen or not (path.parent / row["file"]).is_file():
            raise ValueError("Bad slip plate catalog row: " + str(row.get("id")))
        if row["slot"] in ("header", "pantry") and row.get("flat_edge") not in ("bottom", "top", "none"):
            raise ValueError("Bad slip plate catalog row: " + str(row.get("id")))
        seen.add(key)
    return rows


def plate_ids(slot):
    return [row["id"] for row in plate_catalog() if row["slot"] == slot]


def plate_file(slot, ident):
    for row in plate_catalog():
        if row["slot"] == slot and row["id"] == ident:
            return row["file"]
    raise KeyError(ident)


def band_catalog():
    path = PLATES / "bands.json"
    body = json.loads(path.read_text())
    bands = body.get("bands")
    mapped = body.get("categories")
    default = body.get("default")
    if not isinstance(bands, list) or not isinstance(mapped, dict) or not isinstance(default, str):
        raise ValueError("Bad slip band catalog")
    seen = set()
    for row in bands:
        ident, file = row.get("id"), row.get("file")
        if (
            not isinstance(ident, str)
            or not ident
            or ident in seen
            or not isinstance(file, str)
            or not (path.parent / file).is_file()
            or not isinstance(row.get("description"), str)
            or not row["description"].strip()
            or row.get("flat_edge") not in ("bottom", "top", "none")
        ):
            raise ValueError("Bad slip band row: " + str(ident))
        seen.add(ident)
    if default not in seen:
        raise ValueError("Bad slip band default")
    return body


def band_ids():
    return [row["id"] for row in band_catalog()["bands"]]


def band_file(ident):
    for row in band_catalog()["bands"]:
        if row["id"] == ident:
            return row["file"]
    raise KeyError(ident)


BABETTE_BAND = "babette"


def fixed_band(settings=None):
    """Named band for every recipe and note slip, or None for Babette's pick (dynamic)."""
    chosen = (settings or {}).get("band")
    if chosen in (None, "", BABETTE_BAND):
        return None
    if chosen in band_ids():
        return chosen
    return None


def configured_default(settings=None):
    """Fallback band when dynamic rules miss. Never returns babette."""
    locked = fixed_band(settings)
    if locked:
        return locked
    return band_catalog()["default"]


def band_for_category(category, settings=None):
    """Recipe and praxis slips. A fixed setting overrides; else the category map, else the catalog default."""
    locked = fixed_band(settings)
    if locked:
        return locked
    body = band_catalog()
    ident = body["categories"].get(category) if isinstance(category, str) else None
    if ident not in band_ids():
        ident = body["default"]
    return ident


def _week_index(week_start):
    day = date.fromisoformat(week_start) if isinstance(week_start, str) else week_start
    iso = day.isocalendar()
    return iso.year * 53 + iso.week


def fallback_plates(week_start):
    index = _week_index(week_start)
    picks = {}
    for slot in SLOTS:
        ids = plate_ids(slot)
        stride, offset = TURN[slot]
        picks[slot] = ids[(index * stride + offset) % len(ids)]
    return picks


def _combo(value):
    return tuple(value.get(slot) for slot in SLOTS) if isinstance(value, dict) else None


def accept_plates(raw, week_start, last=None):
    """Keep known ids. An unknown id falls back for that slot. A repeat of last week falls back entirely."""
    fallback = fallback_plates(week_start)
    raw = raw if isinstance(raw, dict) else {}
    chosen = {}
    for slot in SLOTS:
        ident = raw.get(slot)
        chosen[slot] = ident if ident in plate_ids(slot) else fallback[slot]
    if last is not None and _combo(chosen) == _combo(last):
        chosen = dict(fallback)
        if _combo(chosen) == _combo(last):
            ids = plate_ids("top")
            chosen["top"] = ids[(ids.index(chosen["top"]) + 1) % len(ids)]
    return chosen


def resolve_print_plates(stored, week_start):
    return accept_plates(stored, week_start, None)


def kitchen_week(today=None):
    today = today or date.today()
    return (today - timedelta(days=(today.weekday() - 5) % 7)).isoformat()


def stored_week_plates(conn: sqlite3.Connection, week: str) -> dict | None:
    """Raw plates_json for a week, or None when unset."""
    row = conn.execute("SELECT plates_json FROM weeks WHERE start_date = ?", (week,)).fetchone()
    if row is None or not row["plates_json"]:
        return None
    parsed = json.loads(row["plates_json"])
    return parsed if isinstance(parsed, dict) else None


def week_slip_plates(conn: sqlite3.Connection, week: str):
    return resolve_print_plates(stored_week_plates(conn, week), week)


def last_week_plates(conn: sqlite3.Connection, week: str) -> dict:
    """Resolved plates for the Saturday before week (rotation when that week had none)."""
    previous = (date.fromisoformat(week) - timedelta(days=7)).isoformat()
    return resolve_print_plates(stored_week_plates(conn, previous), previous)


def store_week_plates(conn: sqlite3.Connection, week: str, plates: dict, *, now=None) -> dict:
    """Persist accepted plates on the week row (insert a blank week when missing)."""
    payload = json.dumps(plates, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ") if now is None else now
    row = conn.execute("SELECT start_date FROM weeks WHERE start_date = ?", (week,)).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO weeks (start_date, slip_title, slip_quote, notes, plates_json, updated_at)
            VALUES (?, '', '', '', ?, ?)
            """,
            (week, payload, stamp),
        )
    else:
        conn.execute(
            "UPDATE weeks SET plates_json = ?, updated_at = ? WHERE start_date = ?",
            (payload, stamp, week),
        )
    return plates


def stored_week_quote(conn: sqlite3.Connection, week: str) -> str:
    row = conn.execute("SELECT slip_quote FROM weeks WHERE start_date = ?", (week,)).fetchone()
    if row is None or not row["slip_quote"]:
        return ""
    return str(row["slip_quote"])


def store_week_quote(conn: sqlite3.Connection, week: str, quote: str, *, now=None) -> str:
    """Persist the printed closing quote on the week (insert a blank week when missing)."""
    cleaned = " ".join(str(quote or "").split())
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ") if now is None else now
    row = conn.execute("SELECT start_date FROM weeks WHERE start_date = ?", (week,)).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO weeks (start_date, slip_title, slip_quote, notes, plates_json, updated_at)
            VALUES (?, '', ?, '', NULL, ?)
            """,
            (week, cleaned, stamp),
        )
    else:
        conn.execute(
            "UPDATE weeks SET slip_quote = ?, updated_at = ? WHERE start_date = ?",
            (cleaned, stamp, week),
        )
    return cleaned


def plate_tool_listing() -> str:
    """Compact id (phrase) lines for prepare_slip — short labels, not full catalog prose."""
    chunks = []
    for slot in SLOTS:
        bits = []
        for ident in plate_ids(slot):
            phrase = ident.removeprefix(slot + "-").replace("-", " ")
            bits.append(ident + " (" + phrase + ")")
        chunks.append(slot + ": " + ", ".join(bits))
    return "; ".join(chunks)


def week_note_band(conn: sqlite3.Connection, settings=None, today=None):
    """pantry-X on this kitchen week's plates is band X. Anything else uses the default."""
    locked = fixed_band(settings)
    if locked:
        return locked
    pantry = week_slip_plates(conn, kitchen_week(today)).get("pantry") or ""
    ident = pantry.removeprefix("pantry-")
    if ident not in band_ids():
        return band_catalog()["default"]
    return ident


def band_listing() -> str:
    rows = band_catalog()["bands"]
    return " ".join(row["id"] + ": " + row["description"] for row in rows)


def band_property(description: str) -> dict:
    rows = band_catalog()["bands"]
    return {
        "type": "string",
        "enum": [row["id"] for row in rows],
        "description": description,
    }


def plates_property(description: str) -> dict:
    return {
        "type": "object",
        "description": description,
        "properties": {slot: {"type": "string"} for slot in SLOTS},
    }


def valid_heading(clause):
    words = clause.split()
    if not 1 <= len(words) <= 4 or len(clause) > 30 or not clause[0].isupper():
        return False
    return _CLOCK_RE.search(clause) is None


def mark_light_bold(text):
    """Render-time ** markers for sub-headings, oven temperatures, and durations."""
    return "\n".join(_mark_line(line) for line in text.splitlines())


def _mark_line(line):
    spans = []
    for match in HEADING_RE.finditer(line):
        if valid_heading(match.group(1)):
            spans.append(match.span())
    for pattern in (TEMP_RE, DURATION_RE):
        spans.extend(match.span() for match in pattern.finditer(line))
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    parts, cursor = [], 0
    for start, end in merged:
        parts.append(line[cursor:start])
        parts.append("**" + line[start:end] + "**")
        cursor = end
    parts.append(line[cursor:])
    return "".join(parts)


PLACEHOLDERS = {"", "unknown", "zk-chat"}


def _known(value) -> str:
    text = " ".join(str(value or "").split())
    return "" if text.casefold() in PLACEHOLDERS else text


def recipe_slip_text(recipe):
    """Plain slip body, and the same body with light **bold** for the raster."""
    # Placeholders ("unknown", the chat stamp) never print; provenance is bookkeeping.
    head = recipe["id"]
    voice, source = _known(recipe.get("voice")), _known(recipe.get("source"))
    if voice:
        head += " · from " + voice
    if source and source != voice:
        head += "\nSource: " + source
    if recipe.get("stub"):
        head += "\nUnfinished recipe"
    plain, marked = [head], [head]
    sections = []
    praxis = recipe.get("kind") == "praxis"
    if praxis:
        if recipe.get("method"):
            sections.append(("Method", recipe["method"]))
        applies = recipe.get("appliesTo") or []
        if applies:
            sections.append(("Applies to", "\n".join(applies)))
        if recipe.get("ingredients"):
            sections.append(("Ingredients", "\n".join(recipe["ingredients"])))
    else:
        if recipe.get("ingredients"):
            sections.append(("Ingredients", "\n".join(recipe["ingredients"])))
        if recipe.get("method"):
            sections.append(("Method", recipe["method"]))
    if recipe.get("notes"):
        sections.append(("Notes", recipe["notes"]))
    for label, body in sections:
        plain.append(label + "\n" + body)
        marked.append("**" + label + "**\n" + mark_light_bold(body))
    return "\n\n".join(plain), "\n\n".join(marked)


def parse_bold(text):
    """Split matched **bold** into runs. An unmatched ** stays as characters."""
    parts, buf, bold, index = [], [], False, 0

    def flush():
        if buf:
            parts.append(("".join(buf), bold))
            buf.clear()

    while index < len(text):
        if text.startswith("**", index):
            if bold or text.find("**", index + 2) != -1:
                flush()
                bold = not bold
                index += 2
            else:
                buf.append("**")
                index += 2
        else:
            buf.append(text[index])
            index += 1
    flush()
    return parts


def layout_marked(text, measure, max_width, regular, bold):
    """One paragraph wrapped into lines of (segment, is_bold). Long words break."""
    runs = parse_bold(text)
    chars = []
    for segment, is_bold in runs:
        font = bold if is_bold else regular
        chars.extend((ch, font, is_bold) for ch in segment)
    if not chars:
        return [[("", False)]]

    def width(items):
        total, index = 0, 0
        while index < len(items):
            font = items[index][1]
            end = index + 1
            while end < len(items) and items[end][1] is font:
                end += 1
            total += measure.textlength("".join(ch for ch, _, _ in items[index:end]), font=font)
            index = end
        return total

    lines, current = [], []
    for item in chars:
        trial = current + [item]
        if width(trial) > max_width:
            split = max((i for i, (ch, _, _) in enumerate(current) if ch == " "), default=-1)
            if split > 0:
                lines.append(current[:split])
                current = current[split + 1 :] + [item]
            else:
                lines.append(current[:])
                current = [item]
        else:
            current = trial
    lines.append(current)
    laid = []
    for line in lines:
        segments, text, flag = [], "", None
        for ch, _, is_bold in line:
            if flag is is_bold:
                text += ch
            else:
                if text:
                    segments.append((text, flag))
                text, flag = ch, is_bold
        if text:
            segments.append((text, flag))
        laid.append(segments or [("", False)])
    return laid


def dinner(plan, recipes, output):
    labels = DAY_LABELS
    days = []
    for slot in plan["days"]:
        title = slot.get("title") or ""
        if not title and slot.get("recipe"):
            title = recipes[slot["recipe"]]["title"]
        days.append((labels[slot["day"]], title))
    week_text = "the week of " + date.fromisoformat(plan["weekStart"]).strftime("%-d %B")
    plates = resolve_print_plates(plan.get("slipPlates"), plan["weekStart"])
    files = {slot: plate_file(slot, plates[slot]) for slot in SLOTS}
    slip_title = " ".join(str(plan.get("slipTitle") or "").split()) or DEFAULT_SLIP_TITLE
    feast.render(
        days,
        week_text,
        output,
        plan.get("slipQuote") or DEFAULT_SLIP_QUOTE,
        files,
        slip_title=slip_title,
    )


def text_slip(title, text, output, footer, band_name):
    width, inset = 576, 36
    heading = ImageFont.truetype(feast.serif_bold(), 46)
    body = ImageFont.truetype(feast.serif(), 32)
    body_bold = ImageFont.truetype(feast.serif_bold(), 32)
    caption = ImageFont.truetype(feast.serif_italic(), 26)
    # 'lt' hangs each run from its own glyph box, so a bold run misses the
    # regular baseline. Share the regular face's ascender-to-baseline distance.
    # getmetrics() includes internal leading and would drop the whole line.
    body_ascent = -body.getbbox("h", anchor="ls")[1]
    measure = ImageDraw.Draw(Image.new("L", (width, 1)))
    max_w = width - 2 * inset

    def wrap(line, font):
        # Break long words as well; URLs and IDs must not run off the tape.
        lines, current = [], ""
        for char in line:
            if measure.textlength(current + char, font=font) > max_w:
                split = current.rfind(" ")
                if split > 0:
                    lines.append(current[:split])
                    current = current[split + 1 :] + char
                else:
                    lines.append(current)
                    current = char
            else:
                current += char
        return lines + [current]

    rows = []
    for line in wrap(title, heading):
        rows.append(([(line, heading)], 58))
    rows.append(([], 18))
    for paragraph in text.splitlines():
        for segments in layout_marked(paragraph, measure, max_w, body, body_bold):
            rows.append(([(seg, body_bold if is_bold else body) for seg, is_bold in segments if seg], 42))
    footer_lines = wrap(footer, caption)
    header, foot = feast.band_copies(feast.PLATES / band_file(band_name))
    text_top = 8 + feast.HEADER_H + 12
    body_end = text_top + sum(advance for _, advance in rows)
    caption_box = measure.textbbox((0, 0), "Agyp", font=caption)
    caption_h = caption_box[3] - caption_box[1]
    caption_y = body_end + 30 + 34 * (len(footer_lines) - 1)
    height = caption_y + caption_h + 16 + header.height + 8
    canvas = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((6, 6, width - 7, height - 7), outline=0, width=2)
    hx = (width - header.width) // 2
    feast.multiply(canvas, header, (hx, 8))
    feast.multiply(canvas, foot, (hx, height - foot.height - 8))
    y = text_top
    for segments, advance in rows:
        x = inset
        for line, font in segments:
            if font is body or font is body_bold:
                draw.text((x, y + body_ascent), line, font=font, fill=0, anchor="ls")
            else:
                draw.text((x, y), line, font=font, fill=0, anchor="lt")
            x += measure.textlength(line, font=font)
        y += advance
    draw.line((inset, y + 16, width - inset, y + 16), fill=140, width=1)
    for line in footer_lines:
        draw.text((inset, y + 30), line, font=caption, fill=0, anchor="lt")
        y += 34
    output = Path(output)
    canvas.save(output)
    output.with_suffix(".md").write_text(f"![slip]({output.name})\n")
