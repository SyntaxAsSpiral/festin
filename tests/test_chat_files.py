"""Chat text attachments: store, serve, model message, history replay."""

from __future__ import annotations

import hashlib
import threading
from http.client import HTTPConnection
from pathlib import Path

from festin.chat.engine import chat as run_chat
from festin.chat.files import store_files
from festin.chat.messages import append_message, load_messages, model_message
from festin.schema import connect
from festin.server import KitchenServer


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_store_and_serve_round_trip(tmp_path, blank_db):
    data_dir = Path(blank_db).parent
    body = "# Cake density\n\nA short taxonomy.\n"
    refs = store_files([{"name": "cake-density.md", "text": body}], data_dir)
    assert len(refs) == 1
    assert refs[0]["name"] == "cake-density.md"
    assert refs[0]["path"] == "/files/" + _sha(body) + ".md"
    stored = data_dir / "files" / (_sha(body) + ".md")
    assert stored.read_text(encoding="utf-8") == body

    server = KitchenServer(("127.0.0.1", 0), blank_db, origins=("http://kitchen.example",))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        conn.request("GET", refs[0]["path"], headers={"Origin": "http://kitchen.example"})
        response = conn.getresponse()
        payload = response.read()
        assert response.status == 200
        assert payload.decode("utf-8") == body
        conn.close()

        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        conn.request("GET", "/files/../secret.txt", headers={"Origin": "http://kitchen.example"})
        assert conn.getresponse().status == 404
        conn.close()
    finally:
        server.shutdown()


def test_binary_rejected(tmp_path, blank_db):
    data_dir = Path(blank_db).parent
    try:
        store_files([{"name": "blob.bin", "text": "ok\x00nope"}], data_dir)
        assert False, "expected ValueError"
    except ValueError as err:
        assert "UTF-8" in str(err)

    try:
        store_files([{"name": "x.md", "text": b"\xff\xfe binary"}], data_dir)
        assert False, "expected ValueError"
    except ValueError as err:
        assert "UTF-8" in str(err)


def test_model_message_carries_document_text(tmp_path, blank_db):
    data_dir = Path(blank_db).parent
    text = "Tejas nights want one fire, not three."
    refs = store_files([{"name": "notes.txt", "text": text}], data_dir)
    message = {
        "role": "user",
        "content": "Distil this into praxis cards.",
        "files": refs,
        "photos": [],
    }
    built = model_message(message, data_dir, image_support=False)
    assert isinstance(built["content"], str)
    assert built["content"].startswith("Distil this into praxis cards.")
    assert "Attached file: notes.txt" in built["content"]
    assert text in built["content"]


def test_history_replay_includes_file_text(blank_db, tmp_path):
    data_dir = Path(blank_db).parent
    conn = connect(blank_db)
    from festin.chat.messages import ensure_chat

    ensure_chat(conn, "chat-files")
    body = "Apas loves soup and cabbage."
    refs = store_files([{"name": "apas.md", "text": body}], data_dir)
    append_message(
        conn,
        "chat-files",
        {"role": "user", "content": "Please read this.", "files": refs},
    )
    stored = load_messages(conn, "chat-files")
    assert stored[-1]["files"][0]["name"] == "apas.md"
    replayed = model_message(stored[-1], data_dir, image_support=False)
    assert "Attached file: apas.md" in replayed["content"]
    assert body in replayed["content"]


def test_engine_stores_files_on_send(blank_db):
    from festin.chat.flights import clear_flights
    from festin.chat.messages import ensure_chat
    from festin.settings import update_settings

    clear_flights()
    data_dir = Path(blank_db).parent
    conn = connect(blank_db)
    update_settings(conn, model_name="test-model")
    ensure_chat(conn, "c1")
    events = []
    seen = {}

    def completer(base, settings, key, messages, tools, request_id, turn, on_delta=None, on_reset=None, delivery=None):
        user = [m for m in messages if m["role"] == "user"][-1]
        seen["content"] = user["content"]
        text = "Noted."
        if on_delta:
            on_delta(text)
        if delivery is not None:
            delivery["kept"] = True
        return {"role": "assistant", "content": text}

    run_chat(
        conn,
        text="Distil this.",
        week="2026-10-17",
        chat_id="c1",
        session_chat_id="c1",
        data_dir=data_dir,
        files=[{"name": "cake.md", "text": "density table"}],
        emit=events.append,
        completer=completer,
        image_support=False,
        model_key="test-key",
    )
    assert "Attached file: cake.md" in seen["content"]
    assert "density table" in seen["content"]
    stored = load_messages(conn, "c1")
    user = next(m for m in stored if m["role"] == "user")
    assert user["files"][0]["name"] == "cake.md"
    assert user["files"][0]["path"].startswith("/files/")
    assert (data_dir / "files" / Path(user["files"][0]["path"]).name).is_file()
    clear_flights()
    conn.close()
