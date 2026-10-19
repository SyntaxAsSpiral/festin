"""Slip jobs. Live kept them on babette.json under 'slips'. They live in the slips table.

prepare_slip draws a preview and does not print. print_slip sends one copy.
A slip that is no longer 'ready' is not sent again. 'uncertain' is reported
and left as it is.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shlex
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

from festin import plans as plans_mod
from festin import recipes as recipes_mod
from festin.errors import NotFound, StaleState
from festin.plugins.printer import printing
from festin.settings import get_settings

SLIP_SENTENCE = "Slips are ephemeral. Print only when asked."
PRINT_SOURCE = "festin"


def stamp(now: datetime | None = None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def clean_note_band(value):
    """A known band id, or None. The tool enum rejects an unknown band; the server ignores it."""
    band = str(value or "").strip().casefold()
    if band not in printing.band_ids():
        return None
    return band


def slips_dir(data_dir: Path) -> Path:
    folder = Path(data_dir) / "slips"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _day_title(slot: dict, by_id: dict) -> str:
    rid = slot.get("recipe")
    if rid:
        recipe = by_id.get(rid)
        if not recipe:
            raise ValueError(f"unknown recipe {rid}")
        return recipe["title"]
    return (slot.get("title") or "").strip()


def _day_ingredients(slot: dict, by_id: dict) -> list[str]:
    items: list[str] = []
    rid = slot.get("recipe")
    if rid:
        recipe = by_id.get(rid)
        if not recipe:
            raise ValueError(f"unknown recipe {rid}")
        items.extend(recipe.get("ingredients") or [])
    items.extend(slot.get("ingredients") or [])
    return items


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        item = " ".join(str(raw).split())
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _recipes_by_id(conn, plan) -> dict:
    found = {}
    for slot in plan.get("days") or []:
        rid = slot.get("recipe")
        if isinstance(rid, str) and rid and rid not in found:
            try:
                found[rid] = recipes_mod.get_recipe(conn, rid)
            except NotFound as exc:
                raise ValueError(f"unknown recipe {rid}") from exc
    return found


def _saved_week(conn, week: str) -> dict | None:
    row = conn.execute("SELECT start_date FROM weeks WHERE start_date = ?", (week,)).fetchone()
    if row is None:
        return None
    return plans_mod.get_plan(conn, week)


def _as_print_plan(conn, saved: dict) -> dict:
    week = saved["weekStart"]
    plan = {
        "weekStart": week,
        "days": saved["days"],
        "slipTitle": saved.get("slipTitle") or "",
        "slipQuote": printing.stored_week_quote(conn, week),
    }
    if saved.get("plates"):
        plan["slipPlates"] = saved["plates"]
    return plan


def preview(conn, data_dir: Path, week=None, draft=None):
    if draft is not None:
        if not isinstance(draft, dict) or not draft.get("weekStart"):
            raise ValueError("Use exactly seven dinners in Saturday–Friday order.")
        week = str(draft["weekStart"])
        plan = {
            "weekStart": week,
            "days": draft.get("days") or [],
            "notes": draft.get("notes") or "",
        }
        if len(plan["days"]) != 7:
            raise ValueError("Use exactly seven dinners.")
        saved = _saved_week(conn, week)
        if saved is not None:
            plan["slipTitle"] = saved.get("slipTitle") or ""
        elif draft.get("slipTitle"):
            plan["slipTitle"] = draft.get("slipTitle") or ""
        plan["slipQuote"] = printing.stored_week_quote(conn, week)
        if not plan["slipQuote"] and isinstance(draft.get("slipQuote"), str):
            plan["slipQuote"] = draft["slipQuote"]
        if saved and isinstance(saved.get("plates"), dict):
            plan["slipPlates"] = printing.resolve_print_plates(saved["plates"], week)
        elif isinstance(draft.get("slipPlates"), dict):
            plan["slipPlates"] = draft["slipPlates"]
        elif isinstance(draft.get("plates"), dict):
            plan["slipPlates"] = draft["plates"]
    else:
        if not isinstance(week, str) or not week.strip():
            raise ValueError("weekStart must be an ISO date.")
        week = week.strip()
        saved = _saved_week(conn, week)
        if saved is None:
            raise ValueError("No saved plan for this week. Open it in the editor to preview a draft.")
        plan = _as_print_plan(conn, saved)
    by_id = _recipes_by_id(conn, plan)
    directory = slips_dir(data_dir)
    output = directory / (str(uuid.uuid4()) + ".png")
    printing.dinner(plan, by_id, output)
    items = _dedupe([item for slot in plan["days"] for item in _day_ingredients(slot, by_id)])
    heading = " ".join(str(plan.get("slipTitle") or "").split()) or printing.DEFAULT_SLIP_TITLE
    rendered = heading + "\n" + "\n".join(
        slot["day"] + ": " + (slot.get("title") or _day_title(slot, by_id)) for slot in plan["days"]
    )
    rendered += "\n\n" + (plan.get("slipQuote") or printing.DEFAULT_SLIP_QUOTE)
    return {
        "image": "/slips/" + output.name,
        "ingredients": items,
        "draft": draft is not None,
        "title": heading + " · " + plan["weekStart"],
        "rendered_text": rendered,
    }


def note_slip_band(conn, args, settings):
    """Fixed setting wins; else chosen band, else the saved note's band, else this week's pantry plate."""
    locked = printing.fixed_band(settings)
    if locked:
        return locked
    raw = args.get("band")
    if raw not in (None, ""):
        return clean_note_band(raw) or printing.week_note_band(conn, settings)
    note_id = args.get("note_id")
    if isinstance(note_id, str) and note_id:
        entry = conn.execute("SELECT band FROM notes WHERE id = ?", (note_id,)).fetchone()
        saved = clean_note_band(entry["band"]) if entry is not None else None
        if saved:
            return saved
    return printing.week_note_band(conn, settings)


def _request_key(conn, chat_id, args) -> str:
    if chat_id:
        count = conn.execute(
            "SELECT count(*) AS n FROM chat_messages WHERE chat_id = ?", (chat_id,)
        ).fetchone()["n"]
        return f"{chat_id}:{count}"
    token = args.get("print_request_id")
    if not isinstance(token, str) or not token.strip():
        token = str(uuid.uuid4())
    return "api:" + token.strip()


def _load_match(conn, request_key, signature):
    return conn.execute(
        "SELECT * FROM slips WHERE request_key = ? AND signature = ? ORDER BY created_at",
        (request_key, signature),
    ).fetchall()


def _public_from_row(row) -> dict:
    payload = json.loads(row["payload_json"] or "{}")
    record = {
        "slip_id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "image": row["image"],
        "title": row["title"],
        "rendered_text": row["rendered_text"],
        "request_key": row["request_key"],
        "signature": row["signature"],
        "sha256": row["sha256"],
    }
    for key in ("ingredients", "draft", "message"):
        if key in payload:
            record[key] = payload[key]
    return record


def _insert(conn, record: dict, now=None) -> None:
    payload = {
        key: record[key]
        for key in ("ingredients", "draft", "message")
        if key in record
    }
    when = stamp(now)
    conn.execute(
        """
        INSERT INTO slips (
            id, kind, status, title, image, rendered_text, request_key, signature,
            sha256, payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["slip_id"],
            record["kind"],
            record["status"],
            record.get("title") or "",
            record["image"],
            record.get("rendered_text") or "",
            record.get("request_key") or "",
            record.get("signature") or "",
            record.get("sha256") or "",
            json.dumps(payload, ensure_ascii=False),
            when,
            when,
        ),
    )


def _set_status(conn, slip_id: str, status: str, message: str | None = None) -> None:
    row = conn.execute("SELECT payload_json FROM slips WHERE id = ?", (slip_id,)).fetchone()
    payload = json.loads(row["payload_json"] or "{}") if row else {}
    if message is None:
        payload.pop("message", None)
    else:
        payload["message"] = message
    conn.execute(
        "UPDATE slips SET status = ?, payload_json = ?, updated_at = ? WHERE id = ?",
        (status, json.dumps(payload, ensure_ascii=False), stamp(), slip_id),
    )


def prepare_slip(conn: sqlite3.Connection, args: dict, *, data_dir: Path, chat_id: str | None = None) -> dict:
    if not isinstance(args, dict):
        raise ValueError("Choose plan, recipe, or note.")
    kind = args.get("kind") or ("recipe" if args.get("recipe_id") else None)
    if kind is None:
        raise ValueError("Choose plan, recipe, or note.")
    args = {**args, "kind": kind}
    settings = get_settings(conn)
    request_key = _request_key(conn, chat_id, args)
    signature = hashlib.sha256(
        json.dumps(args, sort_keys=True, default=str).encode()
    ).hexdigest()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for existing in _load_match(conn, request_key, signature):
            if existing["status"] == "superseded":
                continue
            if existing["status"] == "ready" and not existing["rendered_text"]:
                _set_status(conn, existing["id"], "superseded")
                continue
            conn.commit()
            return _public_from_row(existing)
        if kind == "plan":
            week = str(args.get("week_start") or "").strip()
            if not week:
                raise ValueError("weekStart must be an ISO date.")
            raw_plates = args.get("plates")
            if isinstance(raw_plates, dict):
                chosen = printing.accept_plates(
                    raw_plates, week, printing.last_week_plates(conn, week)
                )
                printing.store_week_plates(conn, week, chosen)
            raw_quote = args.get("quote")
            if isinstance(raw_quote, str) and raw_quote.strip():
                printing.store_week_quote(conn, week, raw_quote)
            draft = args.get("_plan")
            result = preview(
                conn,
                data_dir,
                week,
                draft if isinstance(draft, dict) and draft.get("weekStart") == week else None,
            )
        elif kind == "recipe":
            recipe_id = args.get("recipe_id")
            try:
                recipe = recipes_mod.get_recipe(conn, recipe_id)
            except NotFound as exc:
                raise ValueError("Unknown recipe ID.") from exc
            title = recipe["title"]
            # Whitelist: id, voice, provenance, source, stub, ingredients, method, notes.
            # Context and searchDescription are never printed.
            shown, text = printing.recipe_slip_text(recipe)
            band_name = printing.band_for_category(recipe.get("category"), _plugin_settings(conn))
            result = _text_result(conn, data_dir, title, text, shown, band_name, settings)
        elif kind == "note":
            raw_title, raw_text = args.get("title"), args.get("text")
            if (
                not isinstance(raw_title, str)
                or not isinstance(raw_text, str)
                or not raw_title.strip()
                or not raw_text.strip()
            ):
                raise ValueError("A note slip needs the title and the text to print.")
            title, text = raw_title.strip(), raw_text.strip()
            band_name = note_slip_band(conn, args, _plugin_settings(conn))
            result = _text_result(conn, data_dir, title, text, text, band_name, settings)
        else:
            raise ValueError("Choose plan, recipe, or note.")
        slip_id = Path(result["image"]).stem
        image_path = _slip_path(data_dir, result["image"])
        result.update(
            {
                "slip_id": slip_id,
                "kind": kind,
                "status": "ready",
                "request_key": request_key,
                "signature": signature,
                "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            }
        )
        _insert(conn, result)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def _plugin_settings(conn) -> dict:
    row = conn.execute(
        "SELECT settings_json FROM plugin_settings WHERE plugin_id = 'printer'"
    ).fetchone()
    if row is None or not row["settings_json"]:
        return {}
    parsed = json.loads(row["settings_json"])
    return parsed if isinstance(parsed, dict) else {}


def _text_result(conn, data_dir, title, text, shown, band_name, settings) -> dict:
    if not title or len(title) > 200 or not shown or len(shown) > 16000:
        raise ValueError("Use a title under 200 characters and non-empty text under 16,000 characters.")
    output = slips_dir(data_dir) / (str(uuid.uuid4()) + ".png")
    footer = settings.get("table_name") or "Babette's Table"
    printing.text_slip(title, text, output, footer, band_name)
    return {
        "image": "/slips/" + output.name,
        "title": title,
        "rendered_text": title + "\n\n" + shown,
    }


def _slip_path(data_dir: Path, image: str) -> Path:
    name = Path(str(image)).name
    path = (slips_dir(data_dir) / name).resolve()
    root = slips_dir(data_dir).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Invalid slip path.")
    return path


def print_message(status: str) -> str:
    if status == "printed":
        return "Printed."
    return (
        "The printer did not confirm. Check it before asking for another copy; "
        "some paper may have printed."
    )


def print_slip(conn: sqlite3.Connection, slip_id: str, *, data_dir: Path) -> dict:
    if not isinstance(slip_id, str) or not slip_id.strip():
        raise ValueError("Prepare a slip first.")
    slip_id = slip_id.strip()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT * FROM slips WHERE id = ?", (slip_id,)).fetchone()
        if row is None:
            raise ValueError("Prepare a slip first.")
        if row["status"] != "ready":
            conn.rollback()
            return {
                "slip_id": slip_id,
                "status": row["status"],
                "message": "No additional print sent.",
            }
        path = _slip_path(data_dir, row["image"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("The prepared preview changed. Prepare it again before printing.")
        with Image.open(path) as im:
            if im.width != 576:
                raise ValueError("Unexpected slip width.")
            im.verify()
        _set_status(conn, slip_id, "printing")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    try:
        status = deliver_print(path, slip_id, row["sha256"], _plugin_settings(conn))
        message = print_message(status)
    except ValueError:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _set_status(conn, slip_id, "ready")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        raise
    conn.execute("BEGIN IMMEDIATE")
    try:
        _set_status(conn, slip_id, status, message)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"slip_id": slip_id, "status": status, "message": message}


def print_dinner(conn, body: dict, *, data_dir: Path) -> dict:
    """Print one Le Festin for the week on Meals. One copy; repeats are idempotent."""
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    plan = body.get("plan")
    week = body.get("weekStart", body.get("week_start"))
    if isinstance(plan, dict):
        week = week or plan.get("weekStart")
    if not isinstance(week, str) or not week.strip():
        raise ValueError("weekStart must be an ISO date.")
    week = week.strip()
    args = {
        "kind": "plan",
        "week_start": week,
        "print_request_id": "dinner:" + week,
    }
    if isinstance(plan, dict) and plan.get("weekStart"):
        args["_plan"] = plan
    slip = prepare_slip(conn, args, data_dir=data_dir)
    return print_slip(conn, slip["slip_id"], data_dir=data_dir)


def print_test_slip(conn, body: dict | None = None, *, data_dir: Path, now=None) -> dict:
    """Render and send a small slip with the table name and the time."""
    settings = get_settings(conn)
    table = settings.get("table_name") or "Babette's Table"
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    when = instant.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    slip = prepare_slip(
        conn,
        {
            "kind": "note",
            "title": "Printer test",
            "text": table + "\n" + when,
            "print_request_id": "test-slip:" + str(uuid.uuid4()),
        },
        data_dir=data_dir,
    )
    return print_slip(conn, slip["slip_id"], data_dir=data_dir)


def print_recipe(conn, body: dict, *, data_dir: Path) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    try:
        recipe = recipes_mod.get_recipe(conn, body.get("recipe_id"))
    except NotFound as exc:
        raise ValueError("Unknown recipe ID.") from exc
    # The Print button prints the card as saved; a caller that read it first may pin the version.
    expected = body.get("expected_updated_at", body.get("expectedUpdatedAt"))
    if expected is not None and expected != recipe.get("updatedAt"):
        raise StaleState("Recipe changed. Refresh before printing.")
    slip = prepare_slip(
        conn,
        {
            "kind": "recipe",
            "recipe_id": recipe["id"],
            "expected_updated_at": recipe.get("updatedAt"),
            "print_request_id": str(uuid.uuid4()),
        },
        data_dir=data_dir,
    )
    return print_slip(conn, slip["slip_id"], data_dir=data_dir)


PRINT_COMMAND_ENV = "FESTIN_PRINT_COMMAND"

DELIVERY_OFF_MESSAGE = (
    "Print delivery is not configured. Choose Print receiver in Settings → Plugins "
    "(or Print command when the host sets FESTIN_PRINT_COMMAND)."
)


def print_command_configured() -> bool:
    return bool(os.environ.get(PRINT_COMMAND_ENV, "").strip())


def resolve_delivery_mode(settings: dict | None) -> str:
    """Effective delivery mode. Empty + receiverUrl keeps pre-deliveryMode kitchens printing."""
    raw = settings or {}
    mode = str(raw.get("deliveryMode") or "").strip()
    if mode:
        return mode
    if str(raw.get("receiverUrl") or "").strip():
        return "receiver"
    return ""


def deliver_print(path: Path, slip_id: str, digest: str, settings: dict) -> str:
    """Send one PNG slip. Mode comes from settings (with receiverUrl back-compat)."""
    mode = resolve_delivery_mode(settings)
    if mode == "receiver":
        return _receiver_print(path, slip_id, digest, settings or {})
    if mode == "command":
        return _command_print(path)
    raise ValueError(DELIVERY_OFF_MESSAGE)


def _receiver_print(path: Path, slip_id: str, digest: str, settings: dict) -> str:
    url = str(settings.get("receiverUrl") or "").rstrip("/")
    if not url:
        raise ValueError("Print receiver URL is not set.")
    token = str(settings.get("token") or "")
    if not token:
        raise ValueError("Print receiver token is not set.")
    body = json.dumps(
        {
            "job_id": slip_id,
            "slip_id": slip_id,
            "source": PRINT_SOURCE,
            "sha256": digest,
            "image": base64.b64encode(path.read_bytes()).decode(),
        }
    ).encode()
    request = Request(
        url + "/print",
        body,
        {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
            "Content-Length": str(len(body)),
        },
    )
    try:
        with urlopen(request, timeout=120) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise ValueError("Print receiver rejected the job.") from exc
    except (OSError, URLError, TimeoutError):
        return "uncertain"
    return (
        result.get("status")
        if isinstance(result, dict) and result.get("status") in ("printed", "uncertain")
        else "uncertain"
    )


def _command_print(path: Path) -> str:
    template = os.environ.get(PRINT_COMMAND_ENV, "").strip()
    if not template:
        raise ValueError(
            "Print command is not configured on the host (set FESTIN_PRINT_COMMAND)."
        )
    if "{file}" not in template:
        raise ValueError("FESTIN_PRINT_COMMAND must include {file}.")
    try:
        parts = shlex.split(template)
    except ValueError as exc:
        raise ValueError("FESTIN_PRINT_COMMAND could not be parsed.") from exc
    if not parts or not any("{file}" in part for part in parts):
        raise ValueError("FESTIN_PRINT_COMMAND must include {file}.")
    argv = [part.replace("{file}", str(path)) for part in parts]
    try:
        process = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return "printed" if process.returncode == 0 else "uncertain"
    except (OSError, subprocess.TimeoutExpired):
        return "uncertain"


def action_prepare(conn, body, *, data_dir, now=None):
    return prepare_slip(conn, body, data_dir=data_dir)


def action_print(conn, body, *, data_dir, now=None):
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    return print_slip(conn, body.get("slip_id"), data_dir=data_dir)


def action_print_dinner(conn, body, *, data_dir, now=None):
    return print_dinner(conn, body, data_dir=data_dir)


def action_print_recipe(conn, body, *, data_dir, now=None):
    return print_recipe(conn, body, data_dir=data_dir)


def action_test_slip(conn, body, *, data_dir, now=None):
    return print_test_slip(conn, body, data_dir=data_dir, now=now)
