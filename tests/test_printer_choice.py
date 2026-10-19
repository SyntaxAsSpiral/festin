"""Babette's pick band setting and weekly slip plate picks (festin-3d6.25)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from festin import plans, recipes
from festin.chat.messages import ensure_chat
from festin.plugins import host
from festin.plugins.printer import printing
from festin.plugins.printer.slips import note_slip_band, prepare_slip
from festin.schema import WEEKDAYS, connect
from festin.server import KitchenServer

SAT = "2026-10-17"
PREV = "2026-10-10"


class Ctx:
    def __init__(self, conn, data_dir, chat_id="chat-1"):
        self.conn = conn
        self.data_dir = Path(data_dir)
        self.chat_id = chat_id


def _kitchen(tmp_path):
    server = KitchenServer(
        ("127.0.0.1", 0),
        tmp_path / "store.sqlite",
        origins=("http://kitchen.example",),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _enable(conn, band="babette"):
    host.update_plugin(
        conn,
        "printer",
        {
            "enabled": True,
            "settings": {
                "receiverUrl": "http://127.0.0.1:9",
                "token": "test-token",
                "band": band,
            },
        },
    )


def _days():
    return [
        {
            "day": day,
            "recipe": None,
            "title": "Soup" if day == "sat" else "",
            "ingredients": ["lentils"] if day == "sat" else [],
        }
        for day in WEEKDAYS
    ]


def test_band_default_is_babette_and_fixed_overrides_recipe_and_note(tmp_path):
    server = _kitchen(tmp_path)
    try:
        conn = connect(server.db_path)
        _enable(conn, band="babette")
        ensure_chat(conn, "chat-1")
        recipe = recipes.create_recipe(
            conn,
            {
                "title": "Honey bread",
                "category": "breads",
                "ingredients": ["flour"],
                "method": "Bake.",
                "voice": "house",
                "stub": False,
            },
        )
        plugin_settings = {"band": "babette"}
        assert printing.band_for_category("breads", plugin_settings) == "wheat"
        assert printing.fixed_band(plugin_settings) is None

        _enable(conn, band="rose")
        locked = {"band": "rose"}
        assert printing.band_for_category("breads", locked) == "rose"
        assert printing.band_for_category("chicken", locked) == "rose"
        assert note_slip_band(conn, {"kind": "note"}, locked) == "rose"

        registry = host.build_registry(conn)
        ctx = Ctx(conn, server.data_dir)
        recipe_slip = registry.dispatch(
            "prepare_slip", {"kind": "recipe", "recipe_id": recipe["id"]}, ctx
        )
        note_slip = registry.dispatch(
            "prepare_slip",
            {"kind": "note", "title": "List", "text": "Leeks."},
            ctx,
        )
        assert recipe_slip["status"] == "ready"
        assert note_slip["status"] == "ready"
        # Fixed rose: both text slips render (band file resolves; no crash on override).
        assert printing.band_for_category(recipe["category"], locked) == "rose"
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_prepare_slip_stores_plates_rejects_repeat_and_rotates_when_empty(tmp_path):
    server = _kitchen(tmp_path)
    try:
        conn = connect(server.db_path)
        _enable(conn, band="babette")
        ensure_chat(conn, "chat-1")
        plans.save_plan(conn, PREV, {"weekStart": PREV, "days": _days()})
        last = {
            "top": "top-salad",
            "bottom": "bottom-cake",
            "header": "header-rose",
            "pantry": "pantry-rose",
        }
        printing.store_week_plates(conn, PREV, last)
        plans.save_plan(conn, SAT, {"weekStart": SAT, "days": _days()})
        assert printing.stored_week_plates(conn, SAT) is None

        rotation = printing.fallback_plates(SAT)
        ctx = Ctx(conn, server.data_dir)
        empty = prepare_slip(
            conn, {"kind": "plan", "week_start": SAT}, data_dir=server.data_dir, chat_id="chat-1"
        )
        assert empty["status"] == "ready"
        assert printing.stored_week_plates(conn, SAT) is None
        assert printing.week_slip_plates(conn, SAT) == rotation

        picks = {
            "top": "top-pasta",
            "bottom": "bottom-pie",
            "header": "header-wheat",
            "pantry": "pantry-wheat",
        }
        stored_slip = prepare_slip(
            conn,
            {"kind": "plan", "week_start": SAT, "plates": picks, "print_request_id": "plates-1"},
            data_dir=server.data_dir,
            chat_id="chat-1",
        )
        assert stored_slip["status"] == "ready"
        assert printing.stored_week_plates(conn, SAT) == picks

        # Repeat of last week → accept_plates falls back to rotation (and stores that).
        repeat = prepare_slip(
            conn,
            {
                "kind": "plan",
                "week_start": SAT,
                "plates": dict(last),
                "print_request_id": "plates-2",
            },
            data_dir=server.data_dir,
            chat_id="chat-1",
        )
        assert repeat["status"] == "ready"
        accepted = printing.stored_week_plates(conn, SAT)
        assert accepted == printing.accept_plates(last, SAT, last)
        assert accepted != last

        # Meals Print path with no plates arg keeps stored plates.
        kept = prepare_slip(
            conn,
            {"kind": "plan", "week_start": SAT, "print_request_id": "plates-3"},
            data_dir=server.data_dir,
            chat_id="chat-1",
        )
        assert kept["status"] == "ready"
        assert printing.stored_week_plates(conn, SAT) == accepted

        registry = host.build_registry(conn)
        tools = {item["function"]["name"]: item["function"] for item in registry.openai_tools()}
        plates_prop = tools["prepare_slip"]["parameters"]["properties"]["plates"]
        assert "top-harvest" in plates_prop["description"]
        assert "when the week has none stored" in plates_prop["description"].casefold()
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_accept_plates_unit_and_existing_named_band_stays_valid():
    week = SAT
    last = printing.fallback_plates(PREV)
    raw = {
        "top": "top-harvest",
        "bottom": "bottom-bread",
        "header": "header-scroll",
        "pantry": "pantry-bay",
    }
    assert printing.accept_plates(raw, week, None) == raw
    assert printing.accept_plates(last, week, last) != last
    assert printing.fixed_band({"band": "scroll"}) == "scroll"
    assert printing.fixed_band({"band": "babette"}) is None
    assert printing.configured_default({"band": "babette"}) == "scroll"


def test_dinner_passes_week_slip_title_into_render(tmp_path, monkeypatch):
    """render.py must not hard-code LE FESTIN; the week's slip_title is the heading."""
    seen = {}

    def fake_render(days, week_text, output, closing_quote, plates=None, slip_title="Le Festin"):
        seen["slip_title"] = slip_title
        seen["closing_quote"] = closing_quote
        Path(output).write_bytes(b"PNG")

    monkeypatch.setattr(printing.feast, "render", fake_render)
    plan = {
        "weekStart": SAT,
        "days": [
            {"day": day, "title": "Soup" if day == "sat" else "", "recipe": None}
            for day in ("sat", "sun", "mon", "tue", "wed", "thu", "fri")
        ],
        "slipTitle": "Autumn table",
        "slipQuote": "Que la table rassemble.",
    }
    printing.dinner(plan, {}, tmp_path / "out.png")
    assert seen["slip_title"] == "Autumn table"
    assert seen["closing_quote"] == "Que la table rassemble."

    seen.clear()
    plan["slipTitle"] = ""
    plan["slipQuote"] = ""
    printing.dinner(plan, {}, tmp_path / "out2.png")
    assert seen["slip_title"] == printing.DEFAULT_SLIP_TITLE
    assert seen["closing_quote"] == printing.DEFAULT_SLIP_QUOTE


def test_prepare_slip_quote_stored_and_default_when_absent(tmp_path):
    server = _kitchen(tmp_path)
    try:
        conn = connect(server.db_path)
        _enable(conn, band="babette")
        ensure_chat(conn, "chat-1")
        plans.save_plan(
            conn,
            SAT,
            {"weekStart": SAT, "days": _days(), "slipTitle": "Autumn table"},
        )
        public = plans.get_plan(conn, SAT)
        assert public["slipTitle"] == "Autumn table"
        assert "slipQuote" not in public

        empty = prepare_slip(
            conn,
            {"kind": "plan", "week_start": SAT, "print_request_id": "quote-0"},
            data_dir=server.data_dir,
            chat_id="chat-1",
        )
        assert printing.DEFAULT_SLIP_QUOTE in empty["rendered_text"]
        assert "Autumn table" in empty["rendered_text"]
        assert printing.stored_week_quote(conn, SAT) == ""

        motto = "Que la table rassemble."
        with_quote = prepare_slip(
            conn,
            {
                "kind": "plan",
                "week_start": SAT,
                "quote": motto,
                "print_request_id": "quote-1",
            },
            data_dir=server.data_dir,
            chat_id="chat-1",
        )
        assert motto in with_quote["rendered_text"]
        assert printing.stored_week_quote(conn, SAT) == motto
        assert "slipQuote" not in plans.get_plan(conn, SAT)

        # Plans save keeps the quote; title stays on-screen only.
        plans.save_plan(
            conn,
            SAT,
            {
                "weekStart": SAT,
                "days": _days(),
                "slipTitle": "Winter hearth",
                "expected_updated_at": plans.get_plan(conn, SAT)["updatedAt"],
            },
        )
        assert plans.get_plan(conn, SAT)["slipTitle"] == "Winter hearth"
        assert printing.stored_week_quote(conn, SAT) == motto

        again = prepare_slip(
            conn,
            {"kind": "plan", "week_start": SAT, "print_request_id": "quote-2"},
            data_dir=server.data_dir,
            chat_id="chat-1",
        )
        assert motto in again["rendered_text"]
        assert "Winter hearth" in again["rendered_text"]
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_recipe_slip_skips_placeholder_voice_and_source():
    from festin.plugins.printer.printing import recipe_slip_text

    plain, _ = recipe_slip_text(
        {"id": "CBK-1414", "voice": "unknown", "source": "unknown", "provenance": "Claude", "ingredients": ["eggs"]}
    )
    assert plain.splitlines()[0] == "CBK-1414"
    assert "unknown" not in plain and "Claude" not in plain
    named, _ = recipe_slip_text(
        {"id": "CBK-0001", "voice": "grandma", "source": "Quita's Recipe box", "provenance": "ocr-draft", "ingredients": ["eggs"]}
    )
    assert named.startswith("CBK-0001 · from grandma\nSource: Quita's Recipe box")
