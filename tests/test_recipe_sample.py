"""The frieze's random sample of recipes."""

from __future__ import annotations

from festin import recipes as recipes_mod
from festin.schema import connect


def test_sample_page_is_distinct_random_and_category_filtered(blank_db):
    conn = connect(blank_db)
    for i in range(40):
        recipes_mod.create_recipe(conn, {"title": f"Dish {i:03d}", "category": "casseroles"})
    page = recipes_mod.list_recipes(conn, limit=10, sample=True)
    ids = [r["id"] for r in page["recipes"]]
    assert len(ids) == 10 and len(set(ids)) == 10
    assert page["nextCursor"] is None

    for i in range(40, 60):
        recipes_mod.create_recipe(conn, {"title": f"Dish {i:03d}", "category": "casseroles"})
    first = [r["id"] for r in recipes_mod.list_recipes(conn, limit=10)["recipes"]]
    draws = [
        [r["id"] for r in recipes_mod.list_recipes(conn, limit=10, sample=True)["recipes"]]
        for _ in range(20)
    ]
    assert any(d != first for d in draws)

    recipes_mod.create_recipe(conn, {"title": "Leek soup", "category": "soups-stews"})
    filtered = recipes_mod.list_recipes(
        conn, limit=5, sample=True, categories=["soups-stews"]
    )
    assert [r["title"] for r in filtered["recipes"]] == ["Leek soup"]
    conn.close()
