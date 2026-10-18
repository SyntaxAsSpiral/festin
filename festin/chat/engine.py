"""One household chat turn. Caller holds the per-chat session lock."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from festin.chat.exceptions import ChatCancelled, StaleState
from festin.chat.flights import (
    begin_flight,
    clear_flights,
    end_flight,
    note_turn,
    provider_cancelled,
)
from festin.chat.keys import resolve_model_key
from festin.chat.messages import (
    HISTORY_WINDOW,
    append_message,
    build_chat_messages,
    ensure_chat,
    load_messages,
    message_count,
    parse_week_start,
    resolve_looking_at,
)
from festin.chat.photos import store_photos
from festin.chat.provider import complete as default_complete
from festin.chat.provider import keep_for_model, reasoning_text, supports_images
from festin.chat.trace import public_args, public_result
from festin.settings import get_settings

# Re-export for tests.
__all__ = ["chat", "StaleState", "ChatCancelled", "clear_flights"]


def chat(
    conn,
    *,
    text,
    week,
    chat_id,
    session_chat_id,
    data_dir,
    photos=None,
    retry=False,
    editor_plan=None,
    expected_messages=None,
    submission_id=None,
    emit=None,
    registry=None,
    completer=None,
    image_support=None,
    persona_path=None,
    model_key=None,
    tools_supported=True,
    context=None,
):
    """Run one turn. Emits live NDJSON event dicts via emit(event).

    Stale checks use this device's session_chat_id and that chat's message count.
    The API layer takes the per-chat lock before calling.

    context is {tab, card: {kind, id}|null} from the client. Card titles and
    note text are loaded from SQLite; client-sent labels are ignored.
    """
    data_dir = Path(data_dir)

    def fail_stale(message: str):
        err = StaleState(message)
        if emit:
            emit({"type": "error", "error": str(err), "status": 409})
        raise err

    parse_week_start(week)
    if editor_plan is not None:
        # Lazy: plans tool validates; engine only needs weekStart alignment later.
        if not isinstance(editor_plan, dict) or "weekStart" not in editor_plan:
            raise ValueError("Use exactly seven dinners in Saturday–Friday order.")

    active_id = session_chat_id if session_chat_id is not None else chat_id
    if active_id is None:
        raise ValueError("chat_id is required.")
    if chat_id is not None and chat_id != active_id:
        fail_stale(
            "The shared conversation changed on another device. Your unsent draft was kept; "
            "send it after switching back if you still want it."
        )
    ensure_chat(conn, active_id)

    count = message_count(conn, active_id)
    if expected_messages is not None and expected_messages != count:
        fail_stale(
            "This conversation changed while you were away. Refresh and try again; "
            "your unsent draft was kept."
        )

    settings = get_settings(conn)
    # Live-shaped aliases already on settings.

    if submission_id:
        if not isinstance(submission_id, str) or not 8 <= len(submission_id) <= 80:
            raise ValueError("Invalid submission.")
        stored = load_messages(conn, active_id)
        for index, message in enumerate(stored):
            if message.get("submission_id") == submission_id:
                if message["role"] == "user" and index == len(stored) - 1:
                    retry = True
                    break
                return {"ok": True}

    if retry:
        stored = load_messages(conn, active_id)
        if not stored or stored[-1]["role"] != "user":
            raise ValueError("There is no unanswered message to retry.")
        editor_plan = stored[-1].get("plan", editor_plan)
    else:
        incoming = {
            "role": "user",
            "content": text,
            "photos": store_photos(photos or [], data_dir) if photos else [],
            "plan": editor_plan,
        }
        if submission_id:
            incoming["submission_id"] = submission_id
        append_message(conn, active_id, incoming)

    if not settings.get("model"):
        raise ValueError("Choose a model in Connection first. Your message has been kept.")

    base = (settings.get("base_url") or "").rstrip("/")
    key = model_key if model_key is not None else resolve_model_key(data_dir, base)
    request_id = str(uuid.uuid4())
    trace = []
    partial = {"text": ""}
    run_complete = completer or default_complete

    if tools_supported is False:
        raise ValueError(
            "This model cannot call tools, and Festin's kitchen turn needs them. "
            "Choose a tool-capable model."
        )

    if registry is None:
        from festin.plugins.host import build_registry

        registry = build_registry(conn)

    tools = registry.openai_tools()

    try:
        begin_flight(request_id, submission_id)
        if image_support is None:
            image_support = supports_images(base, settings["model"], key)
        if provider_cancelled(request_id):
            raise ChatCancelled()
        if emit:
            emit({"type": "start", "request_id": request_id})

        def publish_delta(piece):
            partial["text"] += piece
            if emit:
                emit({"type": "delta", "text": piece})

        def publish_reset():
            partial["text"] = ""
            if emit:
                emit({"type": "reset"})

        def publish_trace():
            if emit:
                emit({"type": "trace", "trace": list(trace)})

        stored = load_messages(conn, active_id)
        if image_support is False and any(
            m.get("photos") for m in stored[-HISTORY_WINDOW:]
        ):
            raise ValueError(
                "This model accepts text only. Choose a vision model for this conversation’s "
                "cooking photos, or start a new text-only chat. Recipe and note printing works "
                "with text-only models."
            )

        opening_extras = {}
        for snippet in registry.opening_snippets(
            _ToolCtx(conn, data_dir, active_id)
        ):
            opening_extras.setdefault("plugin_context", [])
            opening_extras["plugin_context"].append(snippet)

        looking_at = resolve_looking_at(conn, context)
        messages, stored = build_chat_messages(
            conn,
            chat_id=active_id,
            settings=settings,
            week=week,
            editor_plan=editor_plan,
            image_support=image_support,
            data_dir=data_dir,
            persona_path=persona_path,
            opening_extras=opening_extras or None,
            looking_at=looking_at,
        )
        completed = stored[-1].get("tool_results", []) if stored else []
        for item in completed:
            if item.get("name") == "propose_dinners" and item.get("result", {}).get(
                "proposed"
            ):
                editor_plan = item["result"]["proposed"]
        edited_revisions = {}
        ctx = _ToolCtx(conn, data_dir, active_id)

        for turn in range(30):
            note_turn(request_id, turn + 1)
            if provider_cancelled(request_id):
                raise ChatCancelled()
            delivery = {}
            msg = run_complete(
                base,
                settings,
                key,
                messages,
                tools,
                request_id,
                turn + 1,
                publish_delta,
                publish_reset,
                delivery,
            )
            thought = reasoning_text(msg)
            if thought:
                trace.append({"kind": "thinking", "text": thought})
                publish_trace()
            calls = msg.get("tool_calls") or []
            messages.append(keep_for_model(msg))
            if not calls:
                answer = msg.get("content")
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError(
                        "The model returned no answer. Try a tool-capable model."
                    )
                if not delivery.get("kept") and answer != partial["text"]:
                    if partial["text"]:
                        publish_reset()
                    publish_delta(answer)
                append_message(
                    conn,
                    active_id,
                    {"role": "assistant", "content": answer, "trace": trace},
                )
                if emit:
                    emit({"type": "done", "ok": True})
                return {"ok": True}

            for call in calls:
                if provider_cancelled(request_id):
                    raise ChatCancelled()
                tool_name = call.get("function", {}).get("name")
                arguments, result = {}, None
                try:
                    arguments = json.loads(call["function"]["arguments"])
                    if (
                        tool_name == "prepare_slip"
                        and isinstance(arguments, dict)
                        and arguments.get("kind") == "plan"
                        and isinstance(editor_plan, dict)
                        and arguments.get("week_start") == editor_plan.get("weekStart")
                    ):
                        # The open Meals draft wins over the saved week, as live does.
                        arguments["_plan"] = editor_plan
                    if tool_name == "attach_recipe_photos":
                        revisions = edited_revisions.get(arguments.get("recipe_id"))
                        if revisions and arguments.get("expected_updated_at") == revisions[0]:
                            arguments["expected_updated_at"] = revisions[1]
                    if tool_name not in registry.names():
                        # Clear error when the model invents a plugin tool or none exist.
                        raise ValueError(
                            "This model cannot call tools, and Festin's kitchen turn needs them. "
                            "Choose a tool-capable model."
                            if not registry.names()
                            else f"Unknown tool: {tool_name}"
                        )
                    result = registry.dispatch(tool_name, arguments, ctx)
                    if tool_name in ("edit_recipe", "append_recipe_context") and isinstance(
                        result, dict
                    ) and result.get("status") == "saved":
                        recipe = result.get("recipe") or {}
                        edited_revisions[arguments["recipe_id"]] = (
                            arguments.get("expected_updated_at"),
                            recipe.get("updatedAt"),
                        )
                    if tool_name == "propose_dinners" and isinstance(result, dict):
                        editor_plan = result.get("proposed", editor_plan)
                except (ValueError, KeyError, TypeError) as exc:
                    result = {"error": str(exc)}
                trace.append(
                    {
                        "kind": "tool",
                        "name": tool_name,
                        "label": registry.tool_label(tool_name, result),
                        "args": public_args(arguments),
                        "result": public_result(tool_name, result),
                    }
                )
                publish_trace()
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        raise ValueError("Babette reached the tool limit. Please narrow the request.")
    except ChatCancelled:
        text_out = partial["text"]
        had_partial = bool(text_out)
        if had_partial:
            append_message(
                conn,
                active_id,
                {
                    "role": "assistant",
                    "content": text_out,
                    "stopped": True,
                    "trace": trace,
                },
            )
        if emit:
            emit({"type": "stopped"})
        return {"ok": True, "stopped": True}
    except StaleState:
        raise
    except (ValueError, KeyError) as exc:
        if emit:
            emit({"type": "error", "error": str(exc), "status": 400})
        raise
    finally:
        end_flight(request_id)


class _ToolCtx:
    __slots__ = ("conn", "data_dir", "chat_id")

    def __init__(self, conn, data_dir, chat_id):
        self.conn = conn
        self.data_dir = Path(data_dir)
        self.chat_id = chat_id
