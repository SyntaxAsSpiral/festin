"""One automated model call per kitchen week for dinner-slip quote and plates.

Off by default (printer setting weeklyPick). Triggered from session/plan load
when the setting is on, a model is configured, and this week still has no
stored quote and plates. One attempt per week per process; failures log to the
server log and leave rotation/default fallbacks in place.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import date, timedelta
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from festin import plans
from festin import settings as core_settings
from festin.chat.keys import resolve_model_key
from festin.chat.persona import persona
from festin.plugins import host
from festin.plugins.printer import printing
from festin.schema import connect

SETTING_KEY = "weeklyPick"

_ATTEMPT_WEEK: str | None = None
_LOCK = threading.Lock()
_WORKING = False

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I | re.M)


def reset_attempts() -> None:
    """Test helper: clear the per-process attempt gate."""
    global _ATTEMPT_WEEK, _WORKING
    with _LOCK:
        _ATTEMPT_WEEK = None
        _WORKING = False


def week_needs_pick(conn, week: str) -> bool:
    """True when the week is missing its quote or its plates. Only the missing part is filled."""
    return (
        not printing.stored_week_quote(conn, week)
        or printing.stored_week_plates(conn, week) is None
    )


def setting_on(conn) -> bool:
    stored = host.get_plugin(conn, "printer")
    return bool(stored["settings"].get(SETTING_KEY))


def trigger_weekly_pick(
    *,
    db_path: str,
    data_dir,
    today: date | None = None,
    completer=None,
    for_week: str | None = None,
) -> bool:
    """Maybe start one background pick for the current household week.

    Returns True when a worker thread was started. Never blocks on the model.
    for_week, when set (plan load), must equal the current week or the call
    is a no-op.
    """
    global _ATTEMPT_WEEK, _WORKING
    conn = connect(db_path)
    try:
        day = today or core_settings.today(conn)
        start, _end = core_settings.week_bounds(conn, on=day)
        week = start.isoformat()
        if for_week is not None and for_week != week:
            return False
        if day < start:
            return False
        if not setting_on(conn):
            return False
        settings = core_settings.get_settings(conn)
        if not settings.get("model"):
            return False
        if not week_needs_pick(conn, week):
            return False
    finally:
        conn.close()

    with _LOCK:
        if _ATTEMPT_WEEK == week or _WORKING:
            return False
        _ATTEMPT_WEEK = week
        _WORKING = True

    thread = threading.Thread(
        target=_worker,
        kwargs={
            "db_path": db_path,
            "data_dir": data_dir,
            "week": week,
            "today": day,
            "completer": completer,
        },
        daemon=True,
    )
    thread.start()
    return True


def run_weekly_pick(
    conn,
    *,
    data_dir,
    week: str,
    today: date | None = None,
    completer=None,
    model_key: str | None = None,
) -> dict:
    """Synchronous pick: call the model and store quote + plates. For tests."""
    if not week_needs_pick(conn, week):
        return {"stored": False, "reason": "already-set"}
    settings = core_settings.get_settings(conn)
    if not settings.get("model"):
        raise ValueError("Choose a model before Babette's weekly pick can run.")
    base = (settings.get("base_url") or "").rstrip("/")
    key = model_key if model_key is not None else resolve_model_key(data_dir, base)
    day = today or date.fromisoformat(week)
    raw = _ask_model(
        conn,
        week=week,
        today=day,
        base=base,
        settings=settings,
        key=key,
        completer=completer,
    )
    quote, plates = _parse_pick(raw)
    if not week_needs_pick(conn, week):
        return {"stored": False, "reason": "already-set"}
    # Never overwrite what the week already has (a choice made in chat, or imported).
    chosen = printing.stored_week_plates(conn, week)
    if chosen is None:
        last = printing.last_week_plates(conn, week)
        chosen = printing.store_week_plates(conn, week, printing.accept_plates(plates, week, last))
    cleaned = printing.stored_week_quote(conn, week) or printing.store_week_quote(conn, week, quote)
    conn.commit()
    return {"stored": True, "quote": cleaned, "plates": chosen}


def _worker(*, db_path, data_dir, week, today, completer):
    global _WORKING
    try:
        conn = connect(db_path)
        try:
            run_weekly_pick(
                conn,
                data_dir=data_dir,
                week=week,
                today=today,
                completer=completer,
            )
        finally:
            conn.close()
    except Exception as exc:
        print(
            f"weekly pick failed week={week} {type(exc).__name__}: {exc}",
            flush=True,
        )
    finally:
        with _LOCK:
            _WORKING = False


def pick_schema() -> dict:
    """Strict JSON schema: quote + plates{top,bottom,header,pantry}."""
    plate_props = {}
    for slot in printing.SLOTS:
        ids = printing.plate_ids(slot)
        listing = " ".join(
            f"{row['id']}: {row['description']}"
            for row in printing.plate_catalog()
            if row["slot"] == slot
        )
        plate_props[slot] = {
            "type": "string",
            "enum": ids,
            "description": f"{slot} plate on this week's dinner slip. {listing}",
        }
    return {
        "type": "object",
        "properties": {
            "quote": {
                "type": "string",
                "minLength": 1,
                "maxLength": 120,
                "description": (
                    "A fresh, short French motto or sign-off for the bottom of "
                    "this week's dinner slip. In the spirit of "
                    "“Pour les dames de la maison.” Warm, memorable, under 20 "
                    "words; no author attribution."
                ),
            },
            "plates": {
                "type": "object",
                "properties": plate_props,
                "required": list(printing.SLOTS),
                "additionalProperties": False,
            },
        },
        "required": ["quote", "plates"],
        "additionalProperties": False,
    }


def _ask_model(conn, *, week, today, base, settings, key, completer):
    messages = _messages(conn, week=week, today=today)
    schema = pick_schema()
    if completer is not None:
        return completer(
            base=base,
            settings=settings,
            key=key,
            messages=messages,
            schema=schema,
        )
    return _http_complete(base, settings, key, messages, schema)


def _http_complete(base, settings, key, messages, schema):
    if not base:
        raise ValueError("Choose a model before Babette's weekly pick can run.")
    payload = {
        "model": settings["model"],
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "weekly_slip_pick",
                "strict": True,
                "schema": schema,
            },
        },
    }
    host_name = urlparse(base).hostname
    if host_name == "openrouter.ai":
        payload["reasoning"] = {"effort": "low"}
        payload["provider"] = {"sort": "throughput", "require_parameters": True}
    else:
        payload["reasoning_effort"] = "low"
    request = Request(
        base.rstrip("/") + "/chat/completions",
        json.dumps(payload).encode(),
        {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + (key or "local"),
        },
    )
    with urlopen(request) as response:
        body = json.load(response)
    message = body["choices"][0]["message"]
    raw = message.get("content") or message.get("reasoning_content") or ""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("The weekly pick returned no structured content.")
    return raw


def _messages(conn, *, week: str, today: date) -> list[dict]:
    plan = plans.get_plan(conn, week)
    dinners = [
        {"day": night["day"], "title": night.get("title") or "", "recipe": night.get("recipe")}
        for night in plan.get("days") or []
    ]
    previous = (date.fromisoformat(week) - timedelta(days=7)).isoformat()
    last_plates = printing.last_week_plates(conn, week)
    last_quote = printing.stored_week_quote(conn, previous) or printing.DEFAULT_SLIP_QUOTE
    season = _season_name(today)
    voice = persona()
    user = (
        f"Choose this week's dinner-slip art and closing quote for the week of {week}. "
        f"Today is {today.isoformat()} ({today.strftime('%A')}); season: {season}. "
        "Return only the JSON object. "
        "Write a new short French motto as quote — warm, under 20 words, no attribution; "
        "vary it from last week's quote. "
        "Choose plates that suit the season and this week's dinners; vary them from last week.\n\n"
        f"This week's dinners:\n{json.dumps(dinners, ensure_ascii=False)}\n\n"
        f"Last week's quote: {last_quote}\n"
        f"Last week's plates: {json.dumps(last_plates, ensure_ascii=False)}\n\n"
        f"Plate catalog: {printing.plate_tool_listing()}"
    )
    return [
        {
            "role": "system",
            "content": (
                "You are Babette choosing the week's dinner-slip closing quote and plate art. "
                "Match this voice for the quote:\n\n"
                + voice
            ),
        },
        {"role": "user", "content": user},
    ]


def _parse_pick(raw) -> tuple[str, dict]:
    if isinstance(raw, dict):
        result = raw
    else:
        text = str(raw).strip()
        if text.startswith("```"):
            text = _FENCE.sub("", text).strip()
        try:
            result = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("The weekly pick returned invalid JSON.") from exc
    if not isinstance(result, dict):
        raise ValueError("The weekly pick returned invalid JSON.")
    quote = result.get("quote")
    plates = result.get("plates")
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError("The weekly pick returned no quote.")
    if not isinstance(plates, dict):
        raise ValueError("The weekly pick returned no plates.")
    cleaned = " ".join(quote.split())
    if len(cleaned) > 120:
        raise ValueError("The weekly pick quote is too long.")
    return cleaned, plates


def _season_name(day: date) -> str:
    month = day.month
    if month in (9, 10, 11):
        return "autumn"
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    return "summer"
