"""Notes: pinned / archived wording on the open cap and Babette's tool text."""

from __future__ import annotations

import pytest

from festin.chat.schemas import TOOL_SPECS
from festin.notes import OPEN_NOTE_CAP, create_note, toggle_note
from festin.schema import apply, connect


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "store.sqlite")
    apply(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_pin_cap_message_uses_pinned_archived(conn):
    for index in range(OPEN_NOTE_CAP):
        create_note(conn, {"type": "todo", "text": f"pinned {index}", "open": True})
    with pytest.raises(ValueError, match="already pinned") as raised:
        create_note(conn, {"type": "todo", "text": "one more", "open": True})
    assert "Archive one before pinning another" in str(raised.value)


def test_toggle_archives_and_pins_again(conn):
    note = create_note(conn, {"type": "todo", "text": "cream", "open": True})
    assert note["open"] is True
    archived = toggle_note(conn, note["id"], {"expected_updated_at": note["updatedAt"]})
    assert archived["open"] is False
    pinned = toggle_note(conn, note["id"], {"expected_updated_at": archived["updatedAt"]})
    assert pinned["open"] is True


def test_babette_note_tools_speak_pinned_archived():
    by_name = {name: desc for name, desc, _schema in TOOL_SPECS}
    assert "pinned" in by_name["search_notes"].lower()
    assert "archived" in by_name["search_notes"].lower()
    assert "pinned" in by_name["analyze_notes"].lower()
    keep = by_name["keep_note"].lower()
    assert "pins" in keep or "pinned" in keep
    assert "archive" in keep
