# Festin

Babette's kitchen app, rebuilt: Vite + React + Motion front end, Python backend over SQLite. Public repo.

## Layout

- `web/` — Vite + React app.
- `festin/` — Python backend package. `tests/` — backend tests (pytest).
- `ref/` — local reference, gitignored, never committed. `ref/state-machine.md` is the map of every state; beads cite it by section (§). `ref/mock2.html` is the visual mock.
- The live app at `/mnt/echo/family-cookbook` is reference only. Never write its files, and never write `data/babette.json`.

## Environment

`nix develop` gives node, python with pytest, and sqlite. Add tools to `flake.nix`; no global installs.

Dev kitchen (the whole app, chat included, runs on it):

```
python -m festin.importer <copy of the live data dir> data/kitchen.db
npm run kitchen        # or FESTIN_DB=<path> npm run kitchen
```

`npm run kitchen` serves that database (`data/` is gitignored) at `127.0.0.1:8879`. Vite sends `/api`, `/photos`, `/files` and `/cards` there; start Vite with `FESTIN_PORT=<port>` to use your own dev kitchen. Photos, chat attachments and recipe scans live next to the database (`photos/`, `files/`, `cards/`); a worker's copied database has no scans unless you link the main kitchen's `data/cards` beside it.

Port 8879 is the household's real kitchen (a service, the source of truth since 2026-10-20). Workers never use it, never write `/mnt/echo/festin/data`, and run their own copy on their own port. Chat needs a model key in the environment (`OPENROUTER_API_KEY` or `FESTIN_MODEL_KEY`) or a 0600 `model.key` next to the database.

## Rules for workers

- Work only in your own git worktree and branch. The foreman merges.
- Read the bead you were given (`bd show <id>`) and the `ref/state-machine.md` sections it cites before writing code.
- Do not close, create or edit beads. Report back to the foreman instead.
- A bead you are given is approved. Implement it as written; do not stop to ask for confirmation or offer a design pause. Make reasonable calls yourself and list them in your report. Ask only when the bead contradicts itself or the code makes it impossible.
- Every image is a normal file. No base64 in HTML, CSS or JS.
- Tests ship with the code. Backend: `pytest`. Front end: `npm run build` must pass.
- No personal config in code: no adeck addresses, webhook URLs or tailnet names. Defaults are neutral ("Babette's Table").
