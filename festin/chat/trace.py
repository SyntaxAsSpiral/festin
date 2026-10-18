"""Public args/results for NDJSON trace events (live shapes)."""

from __future__ import annotations


def public_args(arguments):
    out = {}
    if not isinstance(arguments, dict):
        return out
    for key in (
        "query",
        "kind",
        "recipe_id",
        "week_start",
        "title",
        "slip_id",
        "chat_id",
        "start",
        "limit",
        "offset",
        "category",
        "voice",
        "source",
        "tattva",
        "status",
        "full",
        "list",
    ):
        if key not in arguments:
            continue
        value = arguments[key]
        if isinstance(value, str) and len(value) > 160:
            value = value[:157] + "..."
        if isinstance(value, (str, int, bool)) or value is None:
            out[key] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            out[key] = [
                item if len(item) <= 80 else item[:77] + "..." for item in value[:8]
            ]
    return out


def public_result(name, result):
    if isinstance(result, list):
        titles = []
        for row in result:
            if not isinstance(row, dict) or not row.get("title"):
                continue
            title = str(row["title"])
            ident = row.get("id")
            titles.append(f"{ident} {title}" if ident else title)
            if len(titles) >= 8:
                break
        return {"count": len(result), "titles": titles}
    if not isinstance(result, dict):
        return {"ok": True}
    if result.get("error"):
        return {"error": str(result["error"])[:240]}
    out = {}
    for key in (
        "status",
        "message",
        "id",
        "title",
        "total",
        "limit",
        "offset",
        "limit_reached",
        "saved",
        "proposed",
        "matches",
        "ok",
        "recipe_id",
    ):
        if key in result:
            value = result[key]
            if key == "matches" and isinstance(value, list):
                out[key] = len(value)
            elif key == "proposed" and isinstance(value, dict):
                out[key] = value.get("weekStart")
            elif isinstance(value, (str, int, bool)) or value is None:
                out[key] = value
    if "results" in result and isinstance(result["results"], list):
        out["results"] = len(result["results"])
    return out or {"ok": True}
