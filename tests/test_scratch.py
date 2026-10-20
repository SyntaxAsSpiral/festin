"""Babette's private scratch: one string, this kitchen week, never the household's."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from festin.chat.core_tools import build_core_registry
from festin.chat.messages import actions_record, append_message, build_chat_messages, ensure_chat
from festin.chat.persona import load_persona
from festin.chat.schemas import tool_specs
from festin.chat.trace import public_args, public_result
from festin.schema import connect
from festin.settings import get_settings, today as household_today, week_bounds
from tests.conftest import start_kitchen, stop_kitchen
from tests.test_api import Client

MARKER = "ZQISP-follow-up-pointer"
PERSONA_LINE = "* A private scratch is yours alone (set_scratch); the household never sees it."


class Ctx:
    def __init__(self, conn, today=None):
        self.conn = conn
        self.data_dir = Path("/tmp")
        self.chat_id = "chat-scratch"
        self.today = today


def _row(conn):
    return conn.execute(
        "SELECT text, week_start, updated_at FROM babette_scratch WHERE id = 1"
    ).fetchone()


def _opening(conn, tmp_path, chat_id="chat-scratch"):
    messages, _stored = build_chat_messages(
        conn,
        chat_id=chat_id,
        settings=get_settings(conn),
        week="2026-10-17",
        editor_plan=None,
        image_support=False,
        data_dir=tmp_path,
    )
    opening = next(
        (
            message["content"]
            for message in messages
            if str(message["content"]).startswith("New-chat context:")
        ),
        None,
    )
    if opening is None:
        return None, messages
    return json.loads(opening.split("\n", 1)[1]), messages


def test_write_overwrite_and_clear(blank_db):
    conn = connect(blank_db)
    registry = build_core_registry()
    ctx = Ctx(conn)
    before = conn.execute("SELECT count(*) FROM kitchen_log_events").fetchone()[0]

    saved = registry.dispatch(
        "set_scratch",
        {"text": "  ask   how\nthe   Ispahan\tturned out  "},
        ctx,
    )
    assert saved == {"status": "saved"}
    assert MARKER not in json.dumps(saved)
    row = _row(conn)
    assert row["text"] == "ask how the Ispahan turned out"
    assert row["week_start"] == week_bounds(conn, on=household_today(conn))[0].isoformat()
    assert row["updated_at"]

    replaced = registry.dispatch(
        "set_scratch",
        {"text": f"  {MARKER}   CBK-0001 note-9 chat-1  "},
        ctx,
    )
    assert replaced == {"status": "saved"}
    assert _row(conn)["text"] == f"{MARKER} CBK-0001 note-9 chat-1"
    assert conn.execute("SELECT count(*) FROM babette_scratch").fetchone()[0] == 1

    cleared = registry.dispatch("set_scratch", {"text": ""}, ctx)
    assert cleared == {"status": "cleared"}
    assert _row(conn) is None
    blanked = registry.dispatch("set_scratch", {"text": " \n\t "}, ctx)
    assert blanked == {"status": "cleared"}
    assert _row(conn) is None

    with pytest.raises(ValueError, match="string"):
        registry.dispatch("set_scratch", {"text": 800}, ctx)
    with pytest.raises(ValueError, match="text"):
        registry.dispatch("set_scratch", {}, ctx)
    assert conn.execute("SELECT count(*) FROM kitchen_log_events").fetchone()[0] == before
    conn.close()


def test_eight_hundred_character_limit_does_not_clobber(blank_db):
    conn = connect(blank_db)
    registry = build_core_registry()
    ctx = Ctx(conn)
    kept = "x" * 800
    assert registry.dispatch("set_scratch", {"text": kept}, ctx)["status"] == "saved"
    assert _row(conn)["text"] == kept

    with pytest.raises(ValueError, match="800"):
        registry.dispatch("set_scratch", {"text": "y" * 801}, ctx)
    assert _row(conn)["text"] == kept

    # Collapse runs before the limit, as live notesToSelf did.
    padded = ("z" * 12) + (" " * 900)
    assert len(padded) > 800
    assert registry.dispatch("set_scratch", {"text": padded}, ctx)["status"] == "saved"
    assert _row(conn)["text"] == "z" * 12
    conn.close()


def test_injected_at_chat_start_only(blank_db, tmp_path):
    conn = connect(blank_db)
    registry = build_core_registry()
    registry.dispatch("set_scratch", {"text": MARKER}, Ctx(conn))

    payload, _messages = _opening(conn, tmp_path, "chat-empty")
    assert payload["your_scratch"] == MARKER

    ensure_chat(conn, "chat-first")
    append_message(conn, "chat-first", {"role": "user", "content": "hello"})
    payload, messages = _opening(conn, tmp_path, "chat-first")
    assert payload["your_scratch"] == MARKER
    assert _row(conn)["text"] == MARKER

    append_message(conn, "chat-first", {"role": "assistant", "content": "Bonjour."})
    payload, messages = _opening(conn, tmp_path, "chat-first")
    assert payload is None
    assert all(MARKER not in str(message["content"]) for message in messages)
    assert _row(conn)["text"] == MARKER
    conn.close()


def test_earlier_kitchen_week_clears_on_new_chat_read(blank_db, tmp_path):
    conn = connect(blank_db)
    start, _end = week_bounds(conn, on=household_today(conn))
    previous = (start - timedelta(days=7)).isoformat()
    later = (start + timedelta(days=7)).isoformat()
    conn.execute(
        "INSERT INTO babette_scratch (id, text, week_start, updated_at) VALUES (1, ?, ?, ?)",
        (MARKER, previous, "2026-10-01T00:00:00.000000Z"),
    )
    conn.commit()

    # A chat already underway does not read the scratch, so it does not clear it.
    ensure_chat(conn, "chat-old")
    append_message(conn, "chat-old", {"role": "user", "content": "still talking"})
    append_message(conn, "chat-old", {"role": "assistant", "content": "oui"})
    payload, messages = _opening(conn, tmp_path, "chat-old")
    assert payload is None
    assert all(MARKER not in str(message["content"]) for message in messages)
    assert _row(conn)["text"] == MARKER

    payload, _messages = _opening(conn, tmp_path, "chat-new")
    assert payload is None or "your_scratch" not in payload
    assert _row(conn) is None

    conn.execute(
        "INSERT INTO babette_scratch (id, text, week_start, updated_at) VALUES (1, ?, ?, ?)",
        (MARKER, later, "2026-10-01T00:00:00.000000Z"),
    )
    conn.commit()
    payload, _messages = _opening(conn, tmp_path, "chat-later")
    # A later week is not an earlier one; the read keeps it.
    assert payload["your_scratch"] == MARKER
    assert _row(conn)["week_start"] == later
    conn.close()


def test_trace_and_replay_omit_the_text(blank_db):
    args = public_args({"text": MARKER, "query": "soup"})
    assert args == {"query": "soup"}
    assert MARKER not in json.dumps(public_result("set_scratch", {"status": "saved"}))
    record = actions_record(
        [
            {
                "kind": "tool",
                "name": "set_scratch",
                "args": {"text": MARKER},
                "result": {"status": "saved"},
            }
        ]
    )
    assert "set_scratch" in record
    assert MARKER not in record


def test_persona_names_the_scratch_once():
    prompt = load_persona()["system_prompt"]
    lines = [line for line in prompt.splitlines() if "set_scratch" in line]
    assert lines == [PERSONA_LINE]
    description = next(desc for name, desc, _schema in tool_specs() if name == "set_scratch")
    assert "Private scratch, not shown to the household." in description
    assert "References and only the most immediate priorities." in description
    assert "Overwrite rather than accumulate." in description
    assert "At most 800 characters." in description
    assert "Empty string when nothing is immediate." in description
    assert "update_household_context" in description
    assert "ask how the Ispahan turned out" in description
    assert "card ids, note ids, chat ids" in description
    assert "Not a diary, not a summary of the chat" in description


def test_absent_from_api_log_search_and_settings(blank_db, tmp_path):
    conn = connect(blank_db)
    registry = build_core_registry()
    registry.dispatch(
        "set_scratch",
        {"text": f"{MARKER} CBK-0001 note-9 chat-1"},
        Ctx(conn),
    )
    found = registry.dispatch("search_history", {"query": "ZQISP"}, Ctx(conn))
    assert found["matches"] == []
    assert found["log"] == []
    conn.close()

    server = start_kitchen(blank_db, origins=("http://kitchen.example",))
    client = Client(server.server_address[1], origin="http://kitchen.example")
    try:
        paths = [
            "/api/session",
            "/api/settings",
            "/api/weather",
            "/api/recipes",
            "/api/notes",
            "/api/chats",
            "/api/log",
            "/api/plugins",
            "/api/plugins/printer",
            "/api/plugins/printer/feed",
            "/api/plugins/tattva",
            "/api/plugins/outbound",
            "/api/plugins/voice",
            "/api/household-context/household",
            "/api/household-context/preferences",
            "/api/household-context/restrictions",
            "/api/plans/2026-10-17",
        ]
        bodies = []
        log_before = None
        for path in paths:
            _status, body = client.request("GET", path)
            bodies.append(body)
            if path == "/api/log":
                log_before = body
        assert log_before["entries"] == []
        writes = [
            ("POST", "/api/notes", {"text": "cream", "type": "shopping"}),
            ("POST", "/api/settings", {"tableName": "Babette's Table"}),
            ("POST", "/api/chats", {}),
            ("POST", "/api/recipes", {"title": "Soup"}),
            ("PUT", "/api/household-context/household", {"text": "Three at the table."}),
        ]
        for method, path, payload in writes:
            _status, body = client.request(method, path, payload)
            bodies.append(body)
        note_id = next(body.get("id") for body in bodies if body.get("text") == "cream")
        _status, note = client.request("GET", f"/api/notes/{note_id}")
        bodies.append(note)
        _status, listed = client.request("GET", "/api/log")
        bodies.append(listed)
        assert listed["entries"]
        assert MARKER not in json.dumps(listed)

        banned = (MARKER, "your_scratch", "notesToSelf", "babette_scratch", "set_scratch")
        for body in bodies:
            blob = json.dumps(body)
            for word in banned:
                assert word not in blob, word

        settings = next(body for body in bodies if "tableName" in body or "weekStart" in body)
        assert "scratch" not in json.dumps(settings).casefold()
    finally:
        stop_kitchen(server)

    fresh = connect(blank_db)
    try:
        leaks = [
            line
            for line in fresh.iterdump()
            if MARKER in line and "babette_scratch" not in line
        ]
        assert leaks == []
        assert fresh.execute(
            "SELECT text FROM babette_scratch WHERE id = 1"
        ).fetchone()["text"].startswith(MARKER)
    finally:
        fresh.close()

    root = Path(__file__).resolve().parents[1]
    for name in ("web/src/settings/form.js", "web/src/settings/Sidebar.jsx"):
        source = (root / name).read_text(encoding="utf-8").casefold()
        assert "scratch" not in source
        assert "notestoself" not in source
        assert "your_scratch" not in source
