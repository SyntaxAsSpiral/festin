"""Ask the configured endpoint whether the key, model, and tools work.

The result is {ok, message}. The key is sent only as a Bearer header and is
never copied into the message.
"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROBE_TIMEOUT = 4
MAX_BODY = 8 * 1024 * 1024

OK = "Connected. This model can call tools."
BAD_KEY = "The API key was rejected."
UNREACHABLE = "The model endpoint is unreachable."
NOT_FOUND = "That model was not found."
NO_TOOLS = "This model cannot call tools."
NO_KEY = "No API key is set."
NO_NAME = "Choose a model name."
REJECTED = "The model endpoint rejected the test."

_PING_TOOL = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Confirm the channel.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(_NoRedirect)


def probe_model(base_url: str, model_name: str, key: str, *, timeout: float = PROBE_TIMEOUT) -> dict:
    """List models, then a 1-token completion when the list does not say."""
    name = " ".join(str(model_name or "").split())
    token = str(key or "").strip()
    if not token:
        return {"ok": False, "message": NO_KEY}
    if not name:
        return {"ok": False, "message": NO_NAME}
    base = str(base_url or "").rstrip("/")
    status, payload, text = _call("GET", base + "/models", token, None, timeout)
    if status == "unreachable":
        return {"ok": False, "message": UNREACHABLE}
    if status in (401, 403):
        return {"ok": False, "message": BAD_KEY}
    if status == 200:
        found = _find_model(payload, name)
        if found is not None:
            flag = _tools_flag(found[0]) if found[1] else None
            if found[1] and flag is True:
                return {"ok": True, "message": OK}
            if found[1] and flag is False:
                return {"ok": False, "message": NO_TOOLS}
            if not found[1]:
                return {"ok": False, "message": NOT_FOUND}
    return _completion(base, name, token, timeout)


def _find_model(payload, name: str):
    """(entry, listed) or None when the body is not a model list."""
    entries = _entries(payload)
    if entries is None:
        return None
    for entry in entries:
        if _entry_id(entry) == name:
            return entry, True
    return None, False


def _completion(base: str, name: str, key: str, timeout: float) -> dict:
    status, _payload, text = _call(
        "POST",
        base + "/chat/completions",
        key,
        {
            "model": name,
            "messages": [{"role": "user", "content": "Reply with ok."}],
            "max_tokens": 1,
            "tools": [_PING_TOOL],
        },
        timeout,
    )
    if status == "unreachable":
        return {"ok": False, "message": UNREACHABLE}
    if status in (401, 403):
        return {"ok": False, "message": BAD_KEY}
    if status == 404 or _missing_model(text):
        return {"ok": False, "message": NOT_FOUND}
    if status == 200:
        return {"ok": True, "message": OK}
    if status in (400, 422) and "tool" in text.lower():
        return {"ok": False, "message": NO_TOOLS}
    return {"ok": False, "message": REJECTED}


def _entries(payload):
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, list):
        return data
    models = payload.get("models")
    if isinstance(models, list):
        return models
    return None


def _entry_id(entry) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str(entry.get("id") or entry.get("name") or "")
    return ""


def _tools_flag(entry):
    """True, False, or None when the catalog does not say."""
    if not isinstance(entry, dict):
        return None
    params = entry.get("supported_parameters")
    if isinstance(params, list):
        return "tools" in params or "tool_choice" in params
    caps = entry.get("capabilities")
    if isinstance(caps, dict) and "tools" in caps:
        return bool(caps["tools"])
    if "supports_tools" in entry:
        return bool(entry["supports_tools"])
    return None


def _missing_model(text: str) -> bool:
    lowered = text.lower()
    return "not found" in lowered or "does not exist" in lowered or "unknown model" in lowered


def _call(method: str, url: str, key: str, payload, timeout: float):
    headers = {"Accept": "application/json", "Authorization": "Bearer " + key}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read(MAX_BODY)
            code = getattr(response, "status", 200)
    except HTTPError as exc:
        raw = exc.read(MAX_BODY) if exc.fp else b""
        code = exc.code
    except (URLError, TimeoutError, OSError):
        return "unreachable", None, ""
    text = raw.decode("utf-8", "replace")[:4000]
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = None
    return code, parsed, text
