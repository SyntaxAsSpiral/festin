"""The frieze's random sample of recipes."""

from __future__ import annotations

from festin import recipes as recipes_mod
from festin.schema import apply, connect


def _kitchen(tmp_path, n):
    conn = connect(tmp_path / "store.sqlite")
    apply(conn)
    for i in range(n):
        recipes_mod.create_recipe(conn, {"title": f"Dish {i:03d}", "category": "casseroles"})
    return conn


def test_a_sample_is_one_page_of_distinct_recipes(tmp_path):
    conn = _kitchen(tmp_path, 40)
    page = recipes_mod.list_recipes(conn, limit=10, sample=True)
    ids = [r["id"] for r in page["recipes"]]
    assert len(ids) == 10 and len(set(ids)) == 10
    assert page["nextCursor"] is None


def test_a_sample_is_not_the_alphabetical_first_page(tmp_path):
    conn = _kitchen(tmp_path, 60)
    first = [r["id"] for r in recipes_mod.list_recipes(conn, limit=10)["recipes"]]
    # Twenty random draws of 10 from 60 all matching the first page is effectively impossible.
    draws = [[r["id"] for r in recipes_mod.list_recipes(conn, limit=10, sample=True)["recipes"]] for _ in range(20)]
    assert any(d != first for d in draws)
