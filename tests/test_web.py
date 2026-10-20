"""Built front end served by the kitchen (--web / FESTIN_WEB)."""

from __future__ import annotations

import json
import shutil
import socket
from http.client import HTTPConnection

import pytest

from festin.server import WEB_CACHE_LONG, WEB_CACHE_SHORT, KitchenServer, main
from tests.conftest import start_kitchen, stop_kitchen

INDEX = "<!doctype html><title>FESTIN_INDEX</title>\n"


@pytest.fixture(scope="module")
def web_kitchen(migrated_template, tmp_path_factory):
    root = tmp_path_factory.mktemp("web")
    db = root / "store.sqlite"
    shutil.copy2(migrated_template, db)
    dist = root / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (assets / "app-Ab12Cd34.js").write_text("console.log(1)\n", encoding="utf-8")
    (assets / "app-Ab12Cd34.css").write_text("body{color:black}\n", encoding="utf-8")
    (assets / "plain.js").write_text("plain\n", encoding="utf-8")
    (dist / "icon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (dist / "mark.woff2").write_bytes(b"woff2")
    (dist / "photo.jpg").write_bytes(b"\xff\xd8\xff")
    (dist / "photo.png").write_bytes(b"\x89PNG")
    (dist / "photo.webp").write_bytes(b"RIFF")
    (dist / "manifest.webmanifest").write_text('{"name":"Babette"}', encoding="utf-8")
    (dist / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")
    kept = dist / "keep"
    kept.mkdir()
    (kept / "LISTING_SHOULD_NOT_APPEAR.txt").write_text("hidden", encoding="utf-8")
    photos = root / "photos"
    files = root / "files"
    cards = root / "cards"
    photos.mkdir()
    files.mkdir()
    cards.mkdir()
    (photos / "shot.jpg").write_bytes(b"PHOTO")
    (files / "note.txt").write_bytes(b"FILE")
    (cards / "card.png").write_bytes(b"CARD")
    (dist / "shot.jpg").write_bytes(b"WEBSHOT")
    server = start_kitchen(db, web_dir=dist, photos_dir=photos)
    try:
        yield server
    finally:
        stop_kitchen(server)


def _exchange(port: int, method: str, path: str):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path)
    response = conn.getresponse()
    body = response.read()
    status = response.status
    headers = {key.lower(): value for key, value in response.getheaders()}
    conn.close()
    return status, headers, body


def _raw(port: int, method: str, target: str) -> tuple[int, bytes]:
    """Send the request target unchanged. HTTP clients may collapse dot segments."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(
            f"{method} {target} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode()
        )
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    return status, body


def test_shell_asset_and_spa(web_kitchen):
    port = web_kitchen.server_address[1]
    index = INDEX.encode()

    status, headers, body = _exchange(port, "GET", "/")
    assert status == 200
    assert body == index
    assert headers["content-type"].startswith("text/html")
    assert headers["cache-control"] == WEB_CACHE_SHORT

    status, headers, body = _exchange(port, "HEAD", "/")
    assert status == 200
    assert body == b""
    assert headers["content-type"].startswith("text/html")
    assert int(headers["content-length"]) == len(index)

    status, headers, body = _exchange(port, "GET", "/assets/app-Ab12Cd34.js")
    assert status == 200
    assert body == b"console.log(1)\n"
    assert headers["content-type"].startswith("text/javascript")
    assert headers["cache-control"] == WEB_CACHE_LONG

    status, headers, body = _exchange(port, "HEAD", "/assets/app-Ab12Cd34.css")
    assert status == 200
    assert body == b""
    assert headers["content-type"].startswith("text/css")
    assert headers["cache-control"] == WEB_CACHE_LONG

    status, headers, body = _exchange(port, "GET", "/assets/plain.js")
    assert status == 200
    assert body == b"plain\n"
    assert headers["cache-control"] == WEB_CACHE_SHORT

    for path in ("/meals", "/recipes/CBK-0001", "/chats/x", "/recipes/CBK-0001?cooked=1"):
        status, headers, body = _exchange(port, "GET", path)
        assert status == 200, path
        assert body == index, path
        assert headers["cache-control"] == WEB_CACHE_SHORT

    status, headers, body = _exchange(port, "GET", "/keep/")
    assert status == 200
    assert body == index
    assert b"LISTING_SHOULD_NOT_APPEAR" not in body
    status, _, body = _exchange(port, "GET", "/keep/LISTING_SHOULD_NOT_APPEAR.txt")
    assert status == 200
    assert body == b"hidden"


def test_content_types(web_kitchen):
    port = web_kitchen.server_address[1]
    expected = {
        "/icon.svg": "image/svg+xml",
        "/mark.woff2": "font/woff2",
        "/photo.jpg": "image/jpeg",
        "/photo.png": "image/png",
        "/photo.webp": "image/webp",
        "/manifest.webmanifest": "application/manifest+json",
        "/favicon.ico": "image/x-icon",
    }
    for path, content_type in expected.items():
        status, headers, body = _exchange(port, "GET", path)
        assert status == 200, path
        assert headers["content-type"] == content_type, path
        assert headers["cache-control"] == WEB_CACHE_SHORT
        assert body


def test_missing_asset_is_not_the_shell(web_kitchen):
    port = web_kitchen.server_address[1]
    status, headers, body = _exchange(port, "GET", "/assets/missing-Ab12Cd34.js")
    assert status == 404
    assert headers["content-type"].startswith("application/json")
    assert json.loads(body)["error"] == "Not found"
    assert b"FESTIN_INDEX" not in body

    status, _, body = _exchange(port, "GET", "/assets/")
    assert status == 404
    assert b"FESTIN_INDEX" not in body
    assert b"app-Ab12Cd34" not in body


def test_traversal_is_refused(web_kitchen):
    port = web_kitchen.server_address[1]
    for target in (
        "/../etc/passwd",
        "/assets/../../etc/passwd",
        "/%2e%2e/%2e%2e/etc/passwd",
        "/assets/%2e%2e/%2e%2e/index.html",
        "/foo/%2e%2e/index.html",
        "/assets/..%2f..%2fetc/passwd",
        "/%2e%2e%2f%2e%2e%2fetc/passwd",
        "/assets/%2e%2e%5c%2e%2e%5csecret",
    ):
        status, body = _raw(port, "GET", target)
        assert status == 403, target
        assert b"FESTIN_INDEX" not in body
        assert b"root:" not in body


def test_api_and_kitchen_files_stay_put(web_kitchen):
    port = web_kitchen.server_address[1]
    status, headers, body = _exchange(port, "GET", "/api/settings")
    assert status == 200
    assert headers["content-type"].startswith("application/json")
    assert json.loads(body)["tableName"] == "Babette's Table"
    assert b"FESTIN_INDEX" not in body

    status, headers, body = _exchange(port, "HEAD", "/api/settings")
    assert status == 200
    assert body == b""
    assert headers["content-type"].startswith("application/json")
    assert int(headers["content-length"]) > 0

    status, headers, body = _exchange(port, "GET", "/api/no-such")
    assert status == 404
    assert headers["content-type"].startswith("application/json")
    assert b"FESTIN_INDEX" not in body

    status, _, body = _exchange(port, "GET", "/photos/shot.jpg")
    assert status == 200
    assert body == b"PHOTO"
    status, _, body = _exchange(port, "GET", "/shot.jpg")
    assert status == 200
    assert body == b"WEBSHOT"
    status, _, body = _exchange(port, "GET", "/files/note.txt")
    assert status == 200
    assert body == b"FILE"
    status, _, body = _exchange(port, "GET", "/cards/card.png")
    assert status == 200
    assert body == b"CARD"

    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", "/meals", body=b"{}", headers={"Content-Type": "application/json"})
    response = conn.getresponse()
    posted = response.read()
    assert response.status == 404
    assert response.getheader("Content-Type").startswith("application/json")
    assert b"FESTIN_INDEX" not in posted
    conn.close()


def test_without_web_root_stays_json(blank_db):
    server = start_kitchen(blank_db)
    try:
        status, headers, body = _exchange(server.server_address[1], "GET", "/")
    finally:
        stop_kitchen(server)
    assert status == 404
    assert headers["content-type"].startswith("application/json")
    assert json.loads(body)["error"] == "Not found"


def test_cli_web_dir(monkeypatch, blank_db, tmp_path):
    web = tmp_path / "dist"
    other = tmp_path / "other"
    web.mkdir()
    other.mkdir()
    seen = {}

    def stop(self):
        seen["web"] = self.web_dir
        raise RuntimeError("stop")

    monkeypatch.setattr(KitchenServer, "serve_forever", stop)

    def run(argv):
        seen.clear()
        with pytest.raises(RuntimeError, match="stop"):
            main(argv)
        return seen["web"]

    base = [str(blank_db), "--host", "127.0.0.1", "--port", "0", "--inbox-port", "0"]
    assert run(base) is None
    assert run(base + ["--web", str(web)]) == web.resolve()
    monkeypatch.setenv("FESTIN_WEB", str(other))
    assert run(base) == other.resolve()
    assert run(base + ["--web", str(web)]) == web.resolve()
    monkeypatch.setenv("FESTIN_WEB", "  ")
    assert run(base) is None


def test_help_mentions_web(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "--web" in out
    assert "FESTIN_WEB" in out
