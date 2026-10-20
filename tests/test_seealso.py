"""See also: praxis applies-to nouns against a formule's ingredient lines."""

from __future__ import annotations

import json
from http.client import HTTPConnection

from festin.recipes import create_recipe, get_recipe, see_also
from festin.schema import connect
from tests.conftest import start_kitchen, stop_kitchen


def _formule(conn, title, ingredients, **extra):
    body = {"title": title, "kind": "formule", "ingredients": ingredients}
    body.update(extra)
    return create_recipe(conn, body)


def _praxis(conn, title, applies_to, **extra):
    body = {"title": title, "kind": "praxis", "method": "Do the thing.", "appliesTo": applies_to}
    body.update(extra)
    return create_recipe(conn, body)


def test_whole_word_plural_and_accent(blank_db):
    conn = connect(blank_db)
    formule = _formule(conn, "Custard", ["2 eggs, beaten", "200g pâté", "3 egg whites"])
    egg = _praxis(conn, "Fats", ["egg"])
    pate = _praxis(conn, "Pâté service", ["pate"])
    white = _praxis(conn, "Meringue", ["egg white"])
    plant = _praxis(conn, "Aubergine", ["eggplant"])
    berry = _praxis(conn, "Berrying", ["berry"])
    tart = _formule(conn, "Berry tart", ["mixed berries"])
    missed = _praxis(conn, "Steel", ["stainless steel"])

    again = get_recipe(conn, formule["id"])
    assert [item["id"] for item in again["seeAlso"]] == [egg["id"], white["id"], pate["id"]]
    assert plant["id"] not in [item["id"] for item in again["seeAlso"]]
    assert missed["id"] not in [item["id"] for item in again["seeAlso"]]
    assert [item["id"] for item in get_recipe(conn, tart["id"])["seeAlso"]] == [berry["id"]]

    # eggplant is its own word. egg does not swallow it.
    aubergine = _formule(conn, "Aubergine gratin", ["1 eggplant"])
    assert [item["id"] for item in get_recipe(conn, aubergine["id"])["seeAlso"]] == [plant["id"]]
    conn.close()


def test_cap_title_order_and_empty(blank_db):
    conn = connect(blank_db)
    formule = _formule(conn, "Omelette", ["2 eggs, beaten"])
    for title in ("Delta", "Alpha", "Gamma", "Beta"):
        _praxis(conn, title, ["eggs"])
    _praxis(conn, "Quiet", [])
    _praxis(conn, "Other", ["rice"])

    seen = get_recipe(conn, formule["id"])
    assert [item["title"] for item in seen["seeAlso"]] == ["Alpha", "Beta", "Delta"]
    assert all(set(item) == {"id", "title"} for item in seen["seeAlso"])

    bare = _formule(conn, "Untitled stew", [])
    assert get_recipe(conn, bare["id"])["seeAlso"] == []
    method_only = _formule(conn, "Method only", [], method="Fold in the eggs.")
    assert get_recipe(conn, method_only["id"])["seeAlso"] == []
    conn.close()


def test_praxis_never_lists_itself_and_api_omits_see_also(blank_db):
    conn = connect(blank_db)
    self_praxis = _praxis(conn, "Eggs themselves", ["egg"], ingredients=["2 eggs, beaten"])
    other = _praxis(conn, "Fats", ["eggs"])
    assert "seeAlso" not in self_praxis
    listed = see_also(conn, self_praxis)
    assert [item["id"] for item in listed] == [other["id"]]
    assert get_recipe(conn, self_praxis["id"]).get("seeAlso") is None
    conn.close()


def test_recipe_api_see_also_shape(blank_db):
    server = start_kitchen(blank_db)
    try:
        port = server.server_address[1]

        def request(method, path, body=None):
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            raw = None
            headers = {}
            if body is not None:
                raw = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(raw))
            conn.request(method, path, body=raw, headers=headers)
            response = conn.getresponse()
            payload = json.loads(response.read().decode())
            status = response.status
            conn.close()
            return status, payload

        status, formule = request(
            "POST",
            "/api/recipes",
            {"title": "Custard", "ingredients": ["2 eggs, beaten"], "method": "Temper."},
        )
        assert status == 201
        assert formule["seeAlso"] == []

        status, praxis = request(
            "POST",
            "/api/recipes",
            {"title": "Fats", "kind": "praxis", "method": "Render.", "appliesTo": ["egg"]},
        )
        assert status == 201
        assert "seeAlso" not in praxis

        status, again = request("GET", f"/api/recipes/{formule['id']}")
        assert status == 200
        assert again["seeAlso"] == [{"id": praxis["id"], "title": "Fats"}]

        status, listed = request("GET", "/api/recipes")
        assert status == 200
        row = next(item for item in listed["recipes"] if item["id"] == formule["id"])
        assert "seeAlso" not in row
    finally:
        stop_kitchen(server)
