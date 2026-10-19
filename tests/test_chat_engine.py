"""Chat turn engine against a fake model. No network."""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

import pytest

from festin.chat.engine import chat
from festin.chat.exceptions import ChatCancelled, StaleState
from festin.chat.flights import begin_flight, clear_flights, provider_cancelled, stop_request
from festin.chat.messages import append_message, ensure_chat, load_messages, message_count
from festin.chat.core_tools import build_core_registry
from festin.schema import WEEKDAYS, connect
from festin.settings import update_settings


SAT = "2026-10-17"  # Saturday


class FakeCompleter:
    """Scripted OpenAI-shaped messages. Mimics complete()'s signature."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(
        self,
        base,
        settings,
        key,
        messages,
        tools,
        request_id,
        turn,
        on_delta=None,
        on_reset=None,
        delivery=None,
    ):
        self.calls += 1
        if not self.script:
            raise AssertionError("fake model exhausted")
        step = self.script.pop(0)
        if step.get("wait_cancel"):
            # Spin until stop_request flips the flight cancel bit.
            for _ in range(200):
                if provider_cancelled(request_id):
                    raise ChatCancelled()
                threading.Event().wait(0.01)
            raise AssertionError("expected cancel")
        if step.get("broken_stream"):
            if on_delta:
                on_delta(step.get("partial", "partial-"))
            if on_reset:
                on_reset()
            if delivery is not None:
                delivery["kept"] = False
            msg = step["message"]
            if on_delta and msg.get("content"):
                on_delta(msg["content"])
            if delivery is not None:
                delivery["kept"] = True
            return msg
        msg = step["message"]
        if msg.get("content") and on_delta and not msg.get("tool_calls"):
            # Stream the answer in two pieces.
            text = msg["content"]
            mid = max(1, len(text) // 2)
            on_delta(text[:mid])
            on_delta(text[mid:])
            if delivery is not None:
                delivery["kept"] = True
        elif msg.get("tool_calls") and on_delta and step.get("stream_then_tools"):
            on_delta("thinking out loud…")
            if on_reset:
                on_reset()
            if delivery is not None:
                delivery["kept"] = False
        return msg


@pytest.fixture
def db(blank_db, tmp_path):
    clear_flights()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    conn = connect(blank_db)
    update_settings(conn, model_name="test-model")
    ensure_chat(conn, "chat-1")
    yield conn, data_dir
    clear_flights()
    conn.close()


def _events():
    bag = []

    def emit(event):
        bag.append(event)

    return bag, emit


def _blank_week(week=SAT):
    return {
        "weekStart": week,
        "notes": "",
        "days": [{"day": d, "recipe": None, "title": "", "ingredients": []} for d in WEEKDAYS],
    }


def test_event_order_start_delta_done(db):
    conn, data_dir = db
    events, emit = _events()
    fake = FakeCompleter(
        [{"message": {"role": "assistant", "content": "Bonsoir. The pot is warm."}}]
    )
    result = chat(
        conn,
        text="Hello",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        emit=emit,
        completer=fake,
        image_support=True,
    )
    assert result == {"ok": True}
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert "delta" in types
    assert types[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Bonsoir. The pot is warm."
    msgs = load_messages(conn, "chat-1")
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["content"] == "Bonsoir. The pot is warm."
    titled = conn.execute("SELECT title FROM chats WHERE id = 'chat-1'").fetchone()
    assert titled["title"] == "Hello"


def test_first_user_message_titles_an_untitled_chat(db):
    conn, data_dir = db
    row = conn.execute("SELECT title FROM chats WHERE id = 'chat-1'").fetchone()
    assert row["title"] == "Current conversation"
    events, emit = _events()
    long = "Need a loaf  " + ("x" * 100) + "\nand more"
    chat(
        conn,
        text=long,
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        emit=emit,
        completer=FakeCompleter([{"message": {"role": "assistant", "content": "Yes."}}]),
        image_support=True,
    )
    titled = conn.execute("SELECT title FROM chats WHERE id = 'chat-1'").fetchone()
    assert titled["title"] == ("Need a loaf " + ("x" * 100) + " and more")[:80]

    # A later turn keeps that title.
    chat(
        conn,
        text="Second thought",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        emit=emit,
        completer=FakeCompleter([{"message": {"role": "assistant", "content": "Ok."}}]),
        image_support=True,
    )
    again = conn.execute("SELECT title FROM chats WHERE id = 'chat-1'").fetchone()
    assert again["title"] == titled["title"]


def test_first_message_files_the_chat(db):
    conn, data_dir = db
    conn.execute("UPDATE chats SET ordinal = NULL WHERE id = 'chat-1'")
    conn.commit()
    events, emit = _events()
    chat(
        conn,
        text="What's for dinner?",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        emit=emit,
        completer=FakeCompleter([{"message": {"role": "assistant", "content": "Soup."}}]),
        image_support=True,
    )
    filed = conn.execute("SELECT ordinal FROM chats WHERE id = 'chat-1'").fetchone()
    assert filed["ordinal"] is not None


def test_first_user_message_keeps_an_explicit_title(db):
    conn, data_dir = db
    conn.execute("UPDATE chats SET title = ? WHERE id = 'chat-1'", ("Market list",))
    conn.commit()
    events, emit = _events()
    chat(
        conn,
        text="Something else entirely",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        emit=emit,
        completer=FakeCompleter([{"message": {"role": "assistant", "content": "Noted."}}]),
        image_support=True,
    )
    titled = conn.execute("SELECT title FROM chats WHERE id = 'chat-1'").fetchone()
    assert titled["title"] == "Market list"


def test_reset_on_broken_stream_then_plain(db):
    conn, data_dir = db
    events, emit = _events()
    fake = FakeCompleter(
        [
            {
                "broken_stream": True,
                "partial": "wrong-",
                "message": {"role": "assistant", "content": "Recovered answer."},
            }
        ]
    )
    chat(
        conn,
        text="Retry path",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        emit=emit,
        completer=fake,
        image_support=True,
    )
    types = [e["type"] for e in events]
    assert "reset" in types
    assert types.index("reset") < types.index("done")
    assert load_messages(conn, "chat-1")[-1]["content"] == "Recovered answer."


def test_stop_mid_stream_keeps_partial(db):
    conn, data_dir = db
    events, emit = _events()
    fake = FakeCompleter([{"wait_cancel": True}])
    request_holder = {}

    def emit_capture(event):
        events.append(event)
        if event["type"] == "start":
            request_holder["id"] = event["request_id"]
            # Stop from another "device" once the flight exists.
            threading.Thread(
                target=lambda: stop_request(request_id=event["request_id"]),
                daemon=True,
            ).start()

    result = chat(
        conn,
        text="Long reply please",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        emit=emit_capture,
        completer=fake,
        image_support=True,
    )
    assert result == {"ok": True, "stopped": True}
    assert events[-1]["type"] == "stopped"


def test_stop_with_partial_text_saved(db):
    conn, data_dir = db
    events, emit = _events()

    def completer(
        base, settings, key, messages, tools, request_id, turn, on_delta=None, on_reset=None, delivery=None
    ):
        if on_delta:
            on_delta("Half a thought")
        raise ChatCancelled()

    result = chat(
        conn,
        text="Stop me",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        emit=emit,
        completer=completer,
        image_support=True,
    )
    assert result["stopped"] is True
    assert events[-1]["type"] == "stopped"
    last = load_messages(conn, "chat-1")[-1]
    assert last["content"] == "Half a thought"
    assert last.get("stopped") is True


def test_submission_id_dedupe_and_retry(db):
    conn, data_dir = db
    fake = FakeCompleter(
        [{"message": {"role": "assistant", "content": "First."}}]
    )
    chat(
        conn,
        text="Ping",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        submission_id="submittx01",
        completer=fake,
        image_support=True,
        emit=lambda e: None,
    )
    # Settled submission returns ok without a new model call.
    fake2 = FakeCompleter(
        [{"message": {"role": "assistant", "content": "Should not run."}}]
    )
    result = chat(
        conn,
        text="Ping again",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        submission_id="submittx01",
        completer=fake2,
        image_support=True,
        emit=lambda e: None,
    )
    assert result == {"ok": True}
    assert fake2.calls == 0
    assert message_count(conn, "chat-1") == 2  # user + assistant

    # Trailing user with same submission_id retries without appending.
    # Drop the assistant so the user is last.
    conn.execute("DELETE FROM chat_messages WHERE role = 'assistant'")
    conn.commit()
    fake3 = FakeCompleter(
        [{"message": {"role": "assistant", "content": "Retried."}}]
    )
    before = message_count(conn, "chat-1")
    chat(
        conn,
        text="ignored on retry",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        submission_id="submittx01",
        completer=fake3,
        image_support=True,
        emit=lambda e: None,
    )
    assert message_count(conn, "chat-1") == before + 1  # only assistant added
    assert load_messages(conn, "chat-1")[-1]["content"] == "Retried."


def test_stale_chat_and_count_emit_409(db):
    conn, data_dir = db
    events, emit = _events()
    with pytest.raises(StaleState, match="shared conversation changed"):
        chat(
            conn,
            text="x",
            week=SAT,
            chat_id="other",
            session_chat_id="chat-1",
            data_dir=data_dir,
            emit=emit,
            completer=FakeCompleter([]),
        )
    assert events[-1] == {
        "type": "error",
        "error": (
            "The shared conversation changed on another device. Your unsent draft was kept; "
            "send it after switching back if you still want it."
        ),
        "status": 409,
    }

    events.clear()
    append_message(conn, "chat-1", {"role": "user", "content": "already here"})
    with pytest.raises(StaleState, match="changed while you were away"):
        chat(
            conn,
            text="x",
            week=SAT,
            chat_id="chat-1",
            session_chat_id="chat-1",
            expected_messages=0,
            data_dir=data_dir,
            emit=emit,
            completer=FakeCompleter([]),
        )
    assert events[-1]["status"] == 409


def test_missing_model_and_no_tools_model(db):
    conn, data_dir = db
    update_settings(conn, model_name="")
    with pytest.raises(ValueError, match="Choose a model"):
        chat(
            conn,
            text="Hi",
            week=SAT,
            chat_id="chat-1",
            session_chat_id="chat-1",
            data_dir=data_dir,
            completer=FakeCompleter([]),
            emit=lambda e: None,
        )
    # Message was kept.
    assert load_messages(conn, "chat-1")[-1]["content"] == "Hi"

    update_settings(conn, model_name="text-only")
    with pytest.raises(ValueError, match="cannot call tools"):
        chat(
            conn,
            text="Cook",
            week=SAT,
            chat_id="chat-1",
            session_chat_id="chat-1",
            data_dir=data_dir,
            tools_supported=False,
            completer=FakeCompleter([]),
            emit=lambda e: None,
        )


def test_vision_gate(db):
    conn, data_dir = db
    # Plant a prior user message with photos.
    append_message(
        conn,
        "chat-1",
        {"role": "user", "content": "see this", "photos": ["/photos/a.jpg"]},
    )
    with pytest.raises(ValueError, match="text only"):
        chat(
            conn,
            text="and this?",
            week=SAT,
            chat_id="chat-1",
            session_chat_id="chat-1",
            data_dir=data_dir,
            image_support=False,
            completer=FakeCompleter(
                [{"message": {"role": "assistant", "content": "nope"}}]
            ),
            emit=lambda e: None,
        )


def test_tool_trace_round_trip(db):
    conn, data_dir = db
    events, emit = _events()
    call = {
        "id": "call-1",
        "type": "function",
        "function": {
            "name": "keep_note",
            "arguments": json.dumps(
                {"type": "shopping", "text": "butter", "color": "green", "open": True}
            ),
        },
    }
    fake = FakeCompleter(
        [
            {"message": {"role": "assistant", "content": None, "tool_calls": [call]}},
            {"message": {"role": "assistant", "content": "Noted the butter."}},
        ]
    )
    chat(
        conn,
        text="Remember butter",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        emit=emit,
        completer=fake,
        image_support=True,
        registry=build_core_registry(),
    )
    types = [e["type"] for e in events]
    assert "trace" in types
    trace_event = next(e for e in events if e["type"] == "trace")
    assert trace_event["trace"][0]["kind"] == "tool"
    assert trace_event["trace"][0]["name"] == "keep_note"
    row = conn.execute(
        "SELECT text, kind, color, open FROM notes WHERE text = 'butter'"
    ).fetchone()
    assert row["kind"] == "shopping"
    assert row["color"] == "green"
    assert row["open"] == 1
    assert events[-1]["type"] == "done"


def test_looking_at_context_resolved_from_sqlite(db):
    conn, data_dir = db
    conn.execute(
        """
        INSERT INTO recipes (
            id, title, kind, voice, source, ingredients_json, method, updated_at
        ) VALUES ('CBK-0042', 'Real Soup', 'recipe', 'zk', 'unknown', '[]', '', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()
    seen = {}

    class Capture(FakeCompleter):
        def __call__(self, base, settings, key, messages, tools, request_id, turn,
                     on_delta=None, on_reset=None, delivery=None):
            seen["messages"] = messages
            return super().__call__(
                base, settings, key, messages, tools, request_id, turn,
                on_delta, on_reset, delivery,
            )

    fake = Capture([{"message": {"role": "assistant", "content": "Oui."}}])
    chat(
        conn,
        text="About this?",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        emit=lambda e: None,
        completer=fake,
        image_support=True,
        context={
            "tab": "recipes",
            "card": {
                "kind": "recipes",
                "id": "CBK-0042",
                "title": "CLIENT LIE — ignore me",
            },
        },
    )
    blocks = [m["content"] for m in seen["messages"] if m["role"] == "system"]
    looking = next(b for b in blocks if b.startswith("The cook is looking at:"))
    assert "- tab: recipes" in looking
    assert "CBK-0042" in looking
    assert "Real Soup" in looking
    assert "CLIENT LIE" not in looking

    # Unknown id: tab only.
    seen.clear()
    fake = Capture([{"message": {"role": "assistant", "content": "Ok."}}])
    chat(
        conn,
        text="Still here",
        week=SAT,
        chat_id="chat-1",
        session_chat_id="chat-1",
        data_dir=data_dir,
        emit=lambda e: None,
        completer=fake,
        image_support=True,
        context={"tab": "notes", "card": {"kind": "notes", "id": "missing-note"}},
    )
    blocks = [m["content"] for m in seen["messages"] if m["role"] == "system"]
    looking = next(b for b in blocks if b.startswith("The cook is looking at:"))
    assert looking == "The cook is looking at:\n- tab: notes"
    assert "missing-note" not in looking
