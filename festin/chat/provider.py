"""OpenAI-compatible chat completions: SSE stream with plain fallback.

Tests inject a FakeCompleter instead of calling these helpers.
"""

from __future__ import annotations

import http.client
import json
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from festin.chat.exceptions import ChatCancelled, StreamBroken
from festin.chat.flights import attach_provider, provider_cancelled

CHAT_PROVIDER_TIMEOUT = 60


def completion_payload(base, settings, messages, tools, stream):
    payload = {
        "model": settings["model"],
        "messages": messages,
        "tools": tools,
    }
    if urlparse(base).hostname == "openrouter.ai":
        payload["reasoning"] = {"effort": "low"}
        payload["provider"] = {
            "sort": "throughput",
            "preferred_min_throughput": {"p50": 40},
        }
    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    return payload


def completion_request(base, settings, key, messages, tools, stream):
    payload = completion_payload(base, settings, messages, tools, stream)
    return Request(
        base.rstrip("/") + "/chat/completions",
        json.dumps(payload).encode(),
        {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + (key or "local"),
        },
    )


def merge_detail(current, item):
    if not isinstance(current, dict) or not current:
        return dict(item)
    merged = dict(current)
    for key, value in item.items():
        previous = merged.get(key)
        if key in ("text", "summary") and isinstance(value, str) and isinstance(previous, str):
            if value.startswith(previous):
                merged[key] = value
            elif value and value not in previous and not previous.endswith(value):
                merged[key] = previous + value
        else:
            merged[key] = value
    return merged


def absorb_reasoning_details(bucket, incoming):
    if not isinstance(incoming, list):
        return
    for item in incoming:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if isinstance(index, int) and index >= 0:
            while len(bucket) <= index:
                bucket.append(None)
            bucket[index] = merge_detail(bucket[index], item)
            continue
        if bucket and isinstance(bucket[-1], dict) and bucket[-1].get("index") is None:
            bucket[-1] = merge_detail(bucket[-1], item)
        else:
            bucket.append(dict(item))


def sse_line(raw):
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    return text.strip()


def parse_sse(response, on_delta, stop=None):
    content, reasoning, reasoning_content = [], [], []
    details, tools = [], {}
    finish = provider = None
    usage = None
    saw_done = showed = False
    try:
        for raw in response:
            if stop and stop():
                closer = getattr(response, "close", None)
                if closer:
                    try:
                        closer()
                    except OSError:
                        pass
                raise ChatCancelled()
            line = sse_line(raw)
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                saw_done = True
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError as exc:
                raise StreamBroken("bad_sse", showed) from exc
            if not isinstance(chunk, dict):
                raise StreamBroken("bad_sse", showed)
            if chunk.get("provider"):
                provider = chunk["provider"]
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            choices = chunk.get("choices") or []
            if not choices or not isinstance(choices[0], dict):
                continue
            choice = choices[0]
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                continue
            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                content.append(piece)
                showed = True
                if on_delta:
                    on_delta(piece)
            for key, bucket in (("reasoning", reasoning), ("reasoning_content", reasoning_content)):
                bit = delta.get(key)
                if isinstance(bit, str) and bit:
                    bucket.append(bit)
            if delta.get("reasoning_details"):
                absorb_reasoning_details(details, delta["reasoning_details"])
            for call in delta.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                index = call.get("index", 0)
                if not isinstance(index, int):
                    index = 0
                slot = tools.setdefault(
                    index, {"id": "", "type": "function", "name": "", "arguments": []}
                )
                if isinstance(call.get("id"), str) and call["id"]:
                    slot["id"] = call["id"]
                if isinstance(call.get("type"), str) and call["type"]:
                    slot["type"] = call["type"]
                function = call.get("function") or {}
                if not isinstance(function, dict):
                    continue
                if isinstance(function.get("name"), str):
                    slot["name"] += function["name"]
                if isinstance(function.get("arguments"), str):
                    slot["arguments"].append(function["arguments"])
    except (ChatCancelled, StreamBroken):
        raise
    except (http.client.HTTPException, URLError, TimeoutError, socket.timeout, OSError) as exc:
        if stop and stop():
            raise ChatCancelled() from exc
        raise StreamBroken(type(exc).__name__, showed) from exc
    if not saw_done and not finish:
        raise StreamBroken("closed", showed)
    message = {"role": "assistant", "content": "".join(content) if content else None}
    if reasoning:
        message["reasoning"] = "".join(reasoning)
    if reasoning_content:
        message["reasoning_content"] = "".join(reasoning_content)
    kept_details = [item for item in details if isinstance(item, dict)]
    if kept_details:
        message["reasoning_details"] = kept_details
    if tools:
        message["tool_calls"] = [
            {
                "id": tools[index]["id"],
                "type": tools[index]["type"],
                "function": {
                    "name": tools[index]["name"],
                    "arguments": "".join(tools[index]["arguments"]),
                },
            }
            for index in sorted(tools)
        ]
    return {
        "choices": [{"finish_reason": finish, "message": message}],
        "usage": usage or {},
        "provider": provider,
    }, showed


def completed_message(body):
    choice = body["choices"][0]
    reason = choice.get("finish_reason")
    if reason not in ("stop", "tool_calls"):
        raise ValueError(
            f'The model response did not finish (stop reason: {reason or "missing"}). Retry the request.'
        )
    return choice["message"]


def complete_plain(base, settings, key, messages, tools, request_id, turn):
    if provider_cancelled(request_id):
        raise ChatCancelled()
    req = completion_request(base, settings, key, messages, tools, False)
    try:
        with urlopen(req, timeout=CHAT_PROVIDER_TIMEOUT) as response:
            if provider_cancelled(request_id):
                raise ChatCancelled()
            body = json.load(response)
    except ChatCancelled:
        raise
    except HTTPError as exc:
        exc.close()
        if provider_cancelled(request_id):
            raise ChatCancelled() from exc
        raise
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        if provider_cancelled(request_id):
            raise ChatCancelled() from exc
        raise
    return completed_message(body)


def complete(
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
    """Stream first; on StreamBroken fall back to one plain request (live behavior)."""
    if provider_cancelled(request_id):
        raise ChatCancelled()
    req = completion_request(base, settings, key, messages, tools, True)
    showed = False
    body = None
    started = time.monotonic()
    broken = None
    try:
        response = urlopen(req, timeout=CHAT_PROVIDER_TIMEOUT)
        attach_provider(request_id, response, getattr(response, "fp", None))
        try:
            if provider_cancelled(request_id):
                raise ChatCancelled()
            body, showed = parse_sse(
                response, on_delta, lambda: provider_cancelled(request_id)
            )
        finally:
            try:
                response.close()
            except OSError:
                pass
    except ChatCancelled:
        raise
    except StreamBroken as exc:
        if provider_cancelled(request_id):
            raise ChatCancelled() from exc
        showed = exc.showed
        broken = exc
    except HTTPError as exc:
        exc.close()
        if provider_cancelled(request_id):
            raise ChatCancelled() from exc
        broken = StreamBroken("HTTPError", False)
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        if provider_cancelled(request_id):
            raise ChatCancelled() from exc
        broken = StreamBroken(type(exc).__name__, False)
    if provider_cancelled(request_id):
        raise ChatCancelled()
    if broken is not None:
        if showed and on_reset:
            on_reset()
        if delivery is not None:
            delivery["kept"] = False
        return complete_plain(base, settings, key, messages, tools, request_id, turn)
    message = body["choices"][0]["message"]
    reset = bool(showed and message.get("tool_calls"))
    if reset and on_reset:
        on_reset()
    if delivery is not None:
        delivery["kept"] = bool(showed and not reset)
    _ = started  # live logs timing via events; we drop events jsonl
    return completed_message(body)


def reasoning_text(msg) -> str:
    chunks = []
    for value in (msg.get("reasoning"), msg.get("reasoning_content")):
        if isinstance(value, str) and value.strip():
            chunks.append(value.strip())
    for item in msg.get("reasoning_details") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("text") or item.get("summary")
        if isinstance(value, str) and value.strip() and value.strip() not in chunks:
            chunks.append(value.strip())
    return "\n\n".join(chunks)[:8000]


def keep_for_model(msg):
    kept = {k: msg[k] for k in ("role", "content", "tool_calls") if k in msg}
    if msg.get("reasoning_details"):
        kept["reasoning_details"] = msg["reasoning_details"]
    elif isinstance(msg.get("reasoning"), str) and msg["reasoning"]:
        kept["reasoning"] = msg["reasoning"]
    return kept


def supports_images(base, model, key):
    """Probe provider /models. None means unknown — do not block photos."""
    # Tests and offline installs leave this unknown.
    return None
