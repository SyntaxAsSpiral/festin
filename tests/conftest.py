"""Shared fixtures: one migrated blank DB per session, copied per test.

Schema apply from v0 costs ~2s; a file copy of a current blank is sub-ms.
KitchenServer.shutdown is ~0.5s — prefer one module-scoped server and reset the
DB file between tests. Printer PNG rasterization is stubbed where tests only
need slip contracts.
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest
from PIL import Image

from festin.schema import apply, connect
from festin.server import KitchenServer


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory):
    path = tmp_path_factory.mktemp("schema") / "blank.sqlite"
    conn = connect(path)
    apply(conn)
    conn.close()
    return path


@pytest.fixture
def blank_db(tmp_path, migrated_template):
    """Path to a fresh copy of the current schema (empty kitchen)."""
    dest = tmp_path / "store.sqlite"
    shutil.copy2(migrated_template, dest)
    return dest


def reset_db_file(db_path: Path, template: Path) -> None:
    """Replace the live DB with a fresh migrated blank (same path)."""
    fresh = db_path.with_suffix(".fresh")
    shutil.copy2(template, fresh)
    fresh.replace(db_path)


def start_kitchen(db_path: Path, **kwargs) -> KitchenServer:
    server = KitchenServer(("127.0.0.1", 0), db_path, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def stop_kitchen(server: KitchenServer) -> None:
    server.shutdown()
    server.server_close()


@pytest.fixture
def stub_slip_art(monkeypatch):
    """Skip real plate/font rasterization; write a valid 576-wide L PNG."""
    from festin.plugins.printer import printing

    def fake_text_slip(title, text, output, footer, band_name):
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("L", (576, 120), 200).save(path)
        path.with_suffix(".md").write_text(f"![slip]({path.name})\n", encoding="utf-8")

    def fake_render(
        days, week_text, output, closing_quote, plates=None, slip_title="Le Festin"
    ):
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("L", (576, 200), 200).save(path)

    monkeypatch.setattr(printing, "text_slip", fake_text_slip)
    monkeypatch.setattr(printing.feast, "render", fake_render)
