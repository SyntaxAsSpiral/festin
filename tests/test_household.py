"""Household context table, tool, API, and separation from notes."""

from __future__ import annotations

import pytest

from festin.chat.core_tools import build_core_registry
from festin.chat.messages import _context_lanes
from festin.chat.schemas import CONTEXT_LIMITS, TOOL_SPECS
from festin.household import put_section, update_household_context
from festin.log import list_log
from festin.notes import create_note, list_notes
from festin.schema import connect
from tests.conftest import reset_db_file, start_kitchen, stop_kitchen
from tests.test_chat_tools import Ctx


@pytest.fixture
def conn(blank_db):
    connection = connect(blank_db)
    try:
        yield connection
    finally:
        connection.close()


def test_tool_appends_by_default_and_replace_needs_version(conn, tmp_path):
    ctx = Ctx(conn, tmp_path)
    first = update_household_context(
        {"section": "restrictions", "text": "No shellfish"},
        ctx,
    )
    assert first["saved"]["text"] == "No shellfish"
    second = update_household_context(
        {"section": "restrictions", "text": "No peanuts"},
        ctx,
    )
    assert second["saved"]["text"] == "No shellfish\nNo peanuts"

    stamp = second["saved"]["updatedAt"]
    with pytest.raises(ValueError, match="expected_updated_at"):
        update_household_context(
            {"section": "restrictions", "text": "rewritten", "mode": "replace"},
            ctx,
        )
    with pytest.raises(ValueError, match="changed"):
        update_household_context(
            {
                "section": "restrictions",
                "text": "rewritten",
                "mode": "replace",
                "expected_updated_at": "stale",
            },
            ctx,
        )
    replaced = update_household_context(
        {
            "section": "restrictions",
            "text": "rewritten",
            "mode": "replace",
            "expected_updated_at": stamp,
        },
        ctx,
    )
    assert replaced["saved"]["text"] == "rewritten"


def test_tool_enforces_section_limits(conn, tmp_path):
    ctx = Ctx(conn, tmp_path)
    too_long = "x" * (CONTEXT_LIMITS["household"] + 1)
    with pytest.raises(ValueError, match="at most"):
        update_household_context({"section": "household", "text": too_long}, ctx)


def test_keep_note_project_stays_a_note(conn, tmp_path):
    registry = build_core_registry()
    ctx = Ctx(conn, tmp_path)
    kept = registry.dispatch(
        "keep_note",
        {"type": "project", "text": "UI refactor for the notes pane"},
        ctx,
    )
    assert kept["saved"]["type"] == "project"
    assert conn.execute("SELECT count(*) FROM household_context").fetchone()[0] == 0
    keep_schema = next(schema for name, _desc, schema in TOOL_SPECS if name == "keep_note")
    assert "context" not in keep_schema["properties"]
    assert any(name == "update_household_context" for name, _d, _s in TOOL_SPECS)


def test_notes_list_and_log_omit_context(conn):
    put_section(conn, "household", {"text": "Three at the table.", "expectedUpdatedAt": None})
    create_note(conn, {"type": "shopping", "text": "cream", "open": True})
    listed = list_notes(conn)
    assert all(note["id"] != "context-household" for note in listed["notes"])
    assert all(
        note["type"] not in ("household", "preferences", "restrictions")
        for note in listed["notes"]
    )
    assert any(note["text"] == "cream" for note in listed["notes"])

    entries = list_log(conn, limit=50)["entries"]
    assert not any(
        entry.get("kind") == "note_created"
        and (
            str(entry.get("id") or "").startswith("context-")
            or entry.get("detail") == "household"
        )
        for entry in entries
    )


def test_opening_context_reads_household_table(conn):
    put_section(conn, "preferences", {"text": "Likes soup.", "expectedUpdatedAt": None})
    lanes = _context_lanes(conn)
    assert lanes["preferences"] == "Likes soup."
    assert lanes["household"] == ""
    assert lanes["restrictions"] == ""


def test_http_get_put_household_context(blank_db, migrated_template):
    import json
    import urllib.error
    import urllib.request

    server = start_kitchen(blank_db)
    try:
        host, port = server.server_address

        def call(method, path, body=None):
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(
                f"http://{host}:{port}{path}",
                data=data,
                method=method,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Origin": f"http://{host}:{port}",
                },
            )
            try:
                with urllib.request.urlopen(req) as res:
                    return res.status, json.loads(res.read().decode())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode())

        status, body = call("GET", "/api/household-context/household")
        assert status == 200
        assert body == {"section": "household", "text": "", "updatedAt": None}

        status, body = call(
            "PUT",
            "/api/household-context/household",
            {"text": "Three at the table.", "expectedUpdatedAt": None},
        )
        assert status == 200
        assert body["text"] == "Three at the table."
        stamp = body["updatedAt"]

        status, conflict = call(
            "PUT",
            "/api/household-context/household",
            {"text": "stale write", "expectedUpdatedAt": None},
        )
        assert status == 409

        status, again = call(
            "PUT",
            "/api/household-context/household",
            {"text": "Four at the table.", "expectedUpdatedAt": stamp},
        )
        assert status == 200
        assert again["text"] == "Four at the table."
    finally:
        stop_kitchen(server)
        reset_db_file(blank_db, migrated_template)
