"""Dinner week validation and propose_dinners over weeks/nights."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from festin.chat.messages import parse_week_start
from festin.chat.tools_recipes import (
    dinner_title_key,
    entry_kind,
    load_recipes,
    present_week,
    stamp_now,
    unique_dinner_id,
    ctx_get,
)
from festin.schema import WEEKDAYS


def canonical_recipe_id(value) -> str:
    text = value.strip() if isinstance(value, str) else ""
    match = re.fullmatch(r"(?:cbk[-\s]?)?(\d{1,4})", text, re.IGNORECASE)
    if not match:
        return text
    return f"CBK-{int(match.group(1)):04d}"


def dinner_title(title, row) -> str:
    text = title if isinstance(title, str) else ""
    card = row.get("title") if isinstance(row, dict) else ""
    if text.strip() and card and dinner_title_key(text) == dinner_title_key(card):
        text = card
    return " ".join(text.split())


def validate_plan(plan: dict, rows: list[dict] | None = None, conn=None) -> dict:
    if rows is None:
        if conn is None:
            raise ValueError("Catalog required to validate a plan.")
        rows = load_recipes(conn)
    week = parse_week_start(plan["weekStart"]).isoformat()
    days = plan["days"]
    if len(days) != 7 or [slot["day"] for slot in days] != list(WEEKDAYS):
        raise ValueError("Use exactly seven dinners in Saturday–Friday order.")
    by_id = {row["id"]: row for row in rows}
    clean = []
    for slot in days:
        rid = canonical_recipe_id(slot.get("recipe")) or None
        if not rid:
            rid = unique_dinner_id(slot.get("title", ""), by_id.values())
        row = by_id.get(rid) if rid else None
        if rid:
            if row is None:
                raise ValueError("Unknown recipe: " + str(rid))
            if entry_kind(row) == "praxis":
                raise ValueError("Praxis cards are techniques, not dinners: " + rid)
        if (
            not isinstance(slot.get("title", ""), str)
            or not isinstance(slot.get("ingredients", []), list)
            or any(not isinstance(item, str) for item in slot.get("ingredients", []))
        ):
            raise ValueError("Dinner titles and ingredients must be text.")
        clean.append(
            {
                "day": slot["day"],
                "recipe": rid,
                "title": dinner_title(slot.get("title", ""), row),
                "ingredients": slot.get("ingredients", []),
            }
        )
    result = {"weekStart": week, "days": clean, "notes": str(plan.get("notes", ""))}
    if plan.get("slipTitle"):
        result["slipTitle"] = str(plan["slipTitle"])
    return result


def propose_dinners(args: dict, ctx: Any) -> dict:
    conn = ctx_get(ctx, "conn")
    plan = validate_plan(args, conn=conn)
    start = plan["weekStart"]
    existing = conn.execute("SELECT * FROM weeks WHERE start_date = ?", (start,)).fetchone()
    if existing and existing["updated_at"] != args.get("expected_updated_at"):
        shown = present_week(conn, existing)
        stamp = json.dumps(existing["updated_at"], ensure_ascii=False)
        raise ValueError(
            "That week already has saved dinners. Retry once with expected_updated_at="
            + stamp
            + ", keeping the nights you are not changing. Saved plan: "
            + json.dumps(shown, ensure_ascii=False)
            + " Tell zk this save did not happen."
        )
    slip_title = ""
    slip_quote = ""
    plates_json = None
    if existing:
        slip_title = existing["slip_title"] or ""
        slip_quote = existing["slip_quote"] or ""
        plates_json = existing["plates_json"]
    if "slipTitle" in plan:
        slip_title = plan["slipTitle"]
    notes = str(args.get("notes") or plan.get("notes") or "")
    stamp = stamp_now(ctx)
    week_date = date.fromisoformat(start)
    iso_dates = [(week_date + timedelta(days=i)).isoformat() for i in range(7)]
    conn.executemany("DELETE FROM night_ingredients WHERE date = ?", [(d,) for d in iso_dates])
    conn.executemany("DELETE FROM nights WHERE date = ?", [(d,) for d in iso_dates])
    conn.execute("DELETE FROM weeks WHERE start_date = ?", (start,))
    conn.execute(
        """
        INSERT INTO weeks (start_date, slip_title, slip_quote, notes, plates_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (start, slip_title, slip_quote, notes, plates_json, stamp),
    )
    for index, slot in enumerate(plan["days"]):
        when = iso_dates[index]
        conn.execute(
            """
            INSERT INTO nights (date, week_start, recipe_id, title, cooked, updated_at)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (when, start, slot["recipe"], slot["title"], stamp),
        )
        for position, item in enumerate(slot["ingredients"]):
            conn.execute(
                "INSERT INTO night_ingredients (date, position, text) VALUES (?, ?, ?)",
                (when, position, item),
            )
    conn.commit()
    week = conn.execute("SELECT * FROM weeks WHERE start_date = ?", (start,)).fetchone()
    proposed = present_week(conn, week)
    return {"proposed": proposed, "saved": True, "instruction": "Saved that week."}
