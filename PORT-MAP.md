# Chat engine port map — `festin-3d6.12.5`

Live source: `/mnt/echo/family-cookbook/babette/server.py` (`chat()` ~3112 and callees).  
Persona: `/mnt/echo/family-cookbook/babette/persona.yaml`.  
Events: `/mnt/echo/festin/ref/live-routes.md` § NDJSON chat stream.  
Store: `festin/schema.py` (v1 kitchen + v2 `sessions` + v3 weather).

**Engine boundary for this bead:** plain modules (e.g. `festin/chat/` or `festin/engine.py` + `festin/tools.py`) that take an `emit(event)` callback. No routes in `festin/server.py`; the API worker / foreman wires `/api/chat` and `/api/stop`. zk: follow live exactly; leave InkStream behind.

---

## 1. Live call graph (chat path)

### 1.1 HTTP framing (API bead / foreman — not this engine)

| Live | Role |
|---|---|
| `wants_chat_stream` | `stream:true` or `Accept: application/x-ndjson` |
| `stream_chat` | Non-blocking `CHAT_LOCK`; 409 `"Babette is still answering."`; NDJSON via `write_ndjson`; calls `chat(..., emit=...)` |
| Non-stream POST `/api/chat` | Same `chat(...)` without emit; JSON `{ok}` / `{ok, stopped}` |
| `stop_request` | Sets flight cancel; closes upstream sock; waits for settle |

Festin difference (already in schema v2 / sessions): lock is **per chat** via `sessions.turn_json`, not a process-wide `CHAT_LOCK`. Two devices on different chats chat at once; same chat → 409. Engine assumes the caller already holds that lock (or the API layer does).

### 1.2 `chat(text, week, photos, retry, editor_plan, chat_id, expected_messages, submission_id, emit)`

Ordered steps and every live helper they touch:

1. **Validate week / draft** — `make_slips.parse_week_start`, `validate_plan`
2. **Under LOCK, load state** — `state()`, settings copy
3. **Stale checks** — `StaleState` if `chat_id ≠ activeChatId` or `expected_messages ≠ len(messages)`
4. **submission_id dedupe** — scan `messages` for same id; settled → `{ok:true}`; trailing user → force `retry`
5. **Retry vs append** — retry reuses last user (and its `plan`); else `store_photos` + append user message + `write(STATE)`
6. **Model gate** — need `settings.model`; resolve key from `KEYS` / `OPENROUTER_API_KEY`
7. **Flight** — `begin_flight` → `supports_images` (under `_OPENING.flight`) → `event('chat_started')` → `set_working` → **`emit({type:'start', request_id})`**
8. **Publish helpers** — `publish_delta` / `publish_reset` / `publish_trace` → `set_working` + emit
9. **Vision gate** — if model is text-only and history window has photos → `ValueError` (live message kept)
10. **Prompt build** — `chat_messages` (persona, calendar, editor, optional new-chat context, history window, prior tool_results)
11. **Tool loop** (max 30 turns) — `note_turn`, cancel check, `complete` (SSE + fallback), `reasoning_text`, tool_calls → `tool` / `apply_dinner_proposal`, `remember_tool_result`, `public_args` / `public_result` / `tool_trace_label`, emit `trace`; slip preview images re-injected as user content
12. **Final assistant** — append message with `content`, `slips`, `trace`; `event('chat_completed')`; `{ok:true}` → emit `done` at HTTP layer
13. **ChatCancelled** — optional partial assistant (`stopped:true`); `{ok:true, stopped:true}` → emit `stopped`
14. **finally** — `end_flight`, `clear_working`

### 1.3 Prompt / history / provider (every function)

| Function | What it does |
|---|---|
| `HISTORY_WINDOW` (=40) | Last N stored messages fed to the model |
| `load_persona` / `persona` | Read `persona.yaml` `system_prompt` only (`PERSONA_KEYS`) |
| `inject_household` | True when `len(messages) ≤ 1` (opening turn) |
| `calendar_context` | today / weekday / this+next week starts (live: Saturday week) |
| `editor_context` / `plan_stamp` / `current_week_dinners` | Open editor week + kitchen week stamps |
| `weather_context` / `dinner_tattva_context` / `dinner_place` | Opening-context weather (core) and tattva (plugin) |
| `chat_messages` | system + optional new-chat context + `model_message` history + interrupted tool_results system note |
| `model_message` | Text; if photos, multimodal parts from `data/cooking-photos/` (resize for inference) |
| `store_photos` | Decode data-URLs → `data/cooking-photos/<uuid>.{jpg,png,webp}`; return `/photos/...` |
| `supports_images` | Probe `/models` (OpenRouter or local); 5 min cache |
| `completion_payload` / `completion_request` | OpenAI-compatible tools + optional OpenRouter reasoning/provider |
| `open_provider` | urlopen tied to flight sock for stop |
| `parse_sse` / `sse_line` / `absorb_reasoning_details` / `merge_detail` | Stream deltas + tool_call assembly; cancel mid-read |
| `complete` / `complete_plain` / `completed_message` / `log_model_response` | Stream first; on `StreamBroken` emit `reset` and one plain completion |
| `keep_for_model` | Strip non-API fields before appending assistant turn |
| `reasoning_text` | thinking for `trace` (`kind:thinking`) |
| `begin_flight` / `end_flight` / `note_turn` / `flight_turn` / `provider_cancelled` / `stop_request` / `_flight_settled` | In-memory flight table + cancel |
| `set_working` / `clear_working` / `remember_tool_result` | Progress / WORKING snapshot |
| `event` | Append `data/babette-events.jsonl` (metadata only) |
| `tool` | Dispatch table (below) |
| `public_args` / `public_result` / `tool_trace_label` / `TOOL_LABELS` / `TOOL_FAILURE_LABELS` | Safe trace payloads |
| `StaleState` / `ChatCancelled` / `StreamBroken` | Control exceptions |

### 1.4 NDJSON events (unchanged shapes)

Order: `start` → (`delta`\* \| `reset` \| `trace`)\* → `done` \| `stopped` \| `error`.

| type | fields |
|---|---|
| `start` | `request_id` |
| `delta` | `text` |
| `reset` | (type only) |
| `trace` | `trace[]` of `{kind:thinking,text}` or `{kind:tool,name,label,args,result}` |
| `done` | `ok: true` |
| `stopped` | (type only) |
| `error` | `error`, `status` (409 or 400) |

---

## 2. Model tools (20)

Live dispatch: `tool(name, args)` plus special-case `propose_dinners` → `apply_dinner_proposal` inside `chat`.

Legend for **SQLite**: table(s) that replace the live file. **Gap** = no home in current `schema.py` (see §4).

| Tool | Reads (live) | Writes (live) | SQLite / Festin equivalent |
|---|---|---|---|
| `search_cookbook` | `data/recipes.json` | — | `recipes` (+ filters on columns / JSON fields) |
| `analyze_cookbook` | `recipes.json`, `data/plans/*.json` (dinner history) | — | `recipes`, `nights`, `weeks` |
| `add_recipe` | `recipes.json` (search first, by convention) | `recipes.json` (+ `meta.nextNumericId`) | `recipes`, `catalog_meta.next_numeric_id` |
| `edit_recipe` | `recipes.json` | `recipes.json` (`expected_updated_at` / `updatedAt`) | `recipes.updated_at` |
| `append_recipe_context` | `recipes.json` | `recipes.json` `.context` | `recipes.context` |
| `delete_recipe` | `recipes.json` | `recipes.json` (id never reused) | `recipes` delete; counter unchanged |
| `attach_recipe_photos` | chat photo paths; `recipes.json` | `recipes.json` `.photos`; files under `data/cooking-photos/` | `recipes.photos_json`; **files still on disk** (no blob table) |
| `propose_dinners` | `data/plans/<week>.json` | that plan file; may clear `babette.json` `proposal` | `weeks`, `nights`, `night_ingredients` (`updated_at` stamp) |
| `update_kitchen_status` | `statusPane`; kitchen-week plan | `babette.json` `statusPane`; optional plan file | plan half → `weeks`/`nights`; **statusPane → Gap A** |
| `search_notes` | `babette.json` `journal` + `data/memory.json` | — | `notes` (kinds include journal types, `preference`, context lanes) |
| `analyze_notes` | journal + memory | — | `notes` |
| `read_notes` | journal + memory | — | `notes` |
| `keep_note` | journal / memory | journal note **or** memory context lane / standing | `notes` insert/update (`context-*` ids, preference rows) |
| `edit_note` | journal / memory | journal or memory (`original` stale guard) | `notes` |
| `delete_note` | journal | journal delete | `notes` delete |
| `search_chat_history` | `babette.json` chats + active `messages` | — | `chats`, `chat_messages` |
| `read_chat_history` | same | — | `chats`, `chat_messages` (+ `extra_json.photos`) |
| `prepare_slip` | plan / recipe / note; band catalog; prior `slips` | `babette.json` `slips[id]`; PNG under `babette/slips/generated/` | PNG on disk; **slip registry → Gap B**; recipe/note/week reads map as above |
| `print_slip` | `slips[id]` + PNG | slip status; Epson via tm20 wrapper | **Gap B** + printer plugin (3d6.6) |
| `send_list` | named open notes; `data/agent-webhooks.json` | HTTP POST to agent | notes read OK; **webhooks → Gap C** (list-send plugin) |

### 2.1 Message / flight side effects (not tools, but chat writes)

| Live field | Where | SQLite |
|---|---|---|
| Active thread `messages[]` | `babette.json` | `chat_messages` for the session’s `chat_id` (`extra_json`: photos, plan, slips, trace, tool_results, submission_id, stopped) |
| Filed chats | `babette.json` `chats[]` | `chats` + `chat_messages` |
| `activeChatId` | `babette.json` | per-device `sessions.chat_id` (not a global active id) |
| Photo files | `data/cooking-photos/` | same idea: filesystem next to the DB (path convention TBD by API bead) |
| Events | `data/babette-events.jsonl` | optional log file; not in schema (keep as sidecar or drop) |

---

## 3. Persona print rules (cut → printer plugin later)

From `babette/persona.yaml` **L'Écriture**:

> Slips are ephemeral. Print only when asked.

That is the only persona sentence that is a print rule. It leaves the persona with the engine; **3d6.6** moves it (and any printer-specific guidance) into the printer plugin.

Related live behavior that is **tool** policy, not persona text (still ported with the tools; plugin owns delivery):

- `prepare_slip` — preview only; inspect `rendered_text` / image before print; note slips need title+text the model writes
- `print_slip` — one copy; only after user asked; idempotent once status ≠ `ready`; uncertain → report, do not auto-replace
- Slip preview images may be re-injected into the model as `user` multimodal content after `prepare_slip` when the model accepts images

---

## 4. Does not map onto the current schema

| Gap | Live | Why it matters for chat | Likely home |
|---|---|---|---|
| **A. Kitchen status pane** | `babette.json` `statusPane` (`intro`, `actions`, `notesToSelf`, `updatedAt`, `reportDate`) | `update_kitchen_status`; opening `kitchen_status_memory` / `notesToSelf` when `inject_household` | New shared table or settings JSON; importer today **drops** statusPane on purpose |
| **B. Slip job registry** | `babette.json` `slips` map (ready/printing/printed/uncertain, sha256, signature, request_key) | `prepare_slip` / `print_slip` dedupe and status | Printer plugin store, or a `slips` table |
| **C. Agent webhooks** | `data/agent-webhooks.json` | `send_list` | List-send / plugins settings (3d6.6) |
| **D. BYOK connection** | `settings.base_url`, `settings.model`, in-memory `KEYS` / env | Every `complete` call | Minimal columns or secrets file here; widened by 3d6.6 |
| **E. Tattva in opening context** | `dinner_tattva_context` | New-chat system blob | Tattva plugin; omit or stub when plugin off |
| **F. Proposal scratch** | `babette.json` `proposal` | Cleared when `propose_dinners` saves that week | Unused if editor draft is client-only; confirm with API bead |
| **G. Saturday report worker** | `generate_weekly_report` / `_weekly_report_worker` | Uses `chat_messages` + structured status; not `/api/chat` | Out of this bead unless foreman says otherwise |
| **H. Global `CHAT_LOCK` / `WORKING` / `FLIGHTS`** | process memory | Live single-flight | Replaced by `sessions.turn_json` + per-request cancel; engine still needs an in-process cancel handle for the provider socket |
| **I. Events jsonl** | `babette-events.jsonl` | Ops metadata | Sidecar file OK; no table required |
| **J. Band / plate art files** | `babette/slips` bands, `printing.*` | Note/recipe slip rendering | Printer plugin assets |

**Already mapped well:** recipes, notes (incl. imported context lanes + preferences), weeks/nights/ingredients, chats/messages, sessions, core weather + dinner hour + table name + week start.

**Active chat identity:** live compares `chat_id` to global `activeChatId`. Festin compares to **this device’s** `sessions.chat_id` (and message count on that chat). Same `StaleState` strings as live.

---

## 5. Explicitly left behind

- **InkStream** (`static/inkstream*.js` and any server coupling): front end’s steady reveal replaces it. Engine still emits `delta` / `reset` as live.
- HTTP Host / same-origin / mount-prefix checks: API layer.
- Routes on `festin/server.py`: other worker + foreman.

---

## 6. Proposed engine module split (for after review)

Not implemented yet — sketch only:

- `festin/chat/persona.py` — load `system_prompt` from data
- `festin/chat/engine.py` — `chat(..., emit=)`; flight cancel; history; complete/SSE
- `festin/chat/tools.py` — tool schemas + dispatch over SQLite
- `festin/chat/photos.py` — store / attach cooking photos
- Gaps A–D either stub with clear errors or minimal schema the foreman approves before code

Tests: fake model covering event sequence, tools, stop, retry (bead done-check).
