# Festin

Babette's kitchen app, rebuilt: Vite + React + Motion front end, Python backend over SQLite. Public repo.

## Layout

- `web/` — Vite + React app.
- `festin/` — Python backend package. `tests/` — backend tests (pytest).
- `ref/` — local reference, gitignored, never committed. `ref/state-machine.md` is the map of every state; beads cite it by section (§). `ref/mock2.html` is the visual mock.
- The live app at `/mnt/echo/family-cookbook` is reference only. Never write its files, and never write `data/babette.json`.

## Environment

`nix develop` gives node, python with pytest, and sqlite. Add tools to `flake.nix`; no global installs.

## Rules for workers

- Work only in your own git worktree and branch. The foreman merges.
- Read the bead you were given (`bd show <id>`) and the `ref/state-machine.md` sections it cites before writing code.
- Do not close, create or edit beads. Report back to the foreman instead.
- Every image is a normal file. No base64 in HTML, CSS or JS.
- Tests ship with the code. Backend: `pytest`. Front end: `npm run build` must pass.
- No personal config in code: no adeck addresses, webhook URLs or tailnet names. Defaults are neutral ("Babette's Table").
