# Festin

**A family cookbook that remembers what you cooked, and can talk about it if you want it to.**

When my grandmother died she left over a thousand recipes: handwritten cards, clipped index cards, notes in the margins. Nobody could find anything in the box, so it sat there collecting dust. My own recipes were no better, scattered across notes apps, old emails and chats with a handful of walled-garden AI assistants.

Festin is where they all live now, in her midcentury style, in a form the family can use. The AI is a layer on top. My family are not big fans of AI or computers, so everything a cookbook needs works without it.

## What's in it

- **Her box, intact.** Every recipe keeps a scan of the original card and a line saying whose it was.
- **The week on one slip.** Seven dinners, ticked off as you cook them. Tap a dish and its card opens. Print it for the fridge on a receipt printer.
- **A log that remembers.** Every dinner cooked, recipe added, note opened and conversation held lands in the Kitchen Log, dated, so "when did we last make that?" has an answer.
- **A to-cook queue.** Flag a dish and it leads the frieze that drifts down the side of the page, ahead of the random draw.
- **Babette, if you want her.** A chat that can read and edit the recipe box, plan the week, keep notes and search the Log and old conversations. Bring any OpenAI-compatible endpoint (OpenRouter by default). Leave the key unset and nothing else notices she's gone.
- **A door that stays shut.** An optional second listener where outside agents can post recipes for review. They can add, never edit. Off until you switch it on. See [docs/incoming-recipes.md](docs/incoming-recipes.md).

### Plugins

All off until you turn them on in Settings.

- **Printer.** Prints the week's slip and recipe cards on a receipt printer, through a small HTTP receiver or a command on the host. See [docs/print-receiver.md](docs/print-receiver.md).
- **Dinner tattva.** Names each night's element at the dinner hour, from local sunrise.
- **Cloud agents.** Babette hands a list (a shopping list, say) to an outside agent when you ask. See [docs/cloud-agents.md](docs/cloud-agents.md).

## The look

Paper, not a dashboard. Engraved plates stand in for dish photos, linen cards lie on an ivory page, tabs are folders, buttons are keycaps, and every shadow is the same soft sepia. It runs on a phone, a tablet and a wide desktop, and installs as an app that can go full screen.

## Under the hood

- **Front end:** Vite, React and Motion, in `web/`.
- **Back end:** the Python standard library over SQLite, in `festin/`. No framework, no ORM, one database file.
- **Environment:** a Nix flake. `nix develop` gives you node, Python with pytest, and sqlite.

## Running it

```sh
nix develop
(cd web && npm install)

# The kitchen. An empty database is created on first run.
python -m festin.server data/kitchen.db --host 127.0.0.1 --port 8879

# The app, in another shell. Vite sends /api to the kitchen.
npm run dev
```

To serve the built app from the kitchen as one process, run `npm run build`, then `python -m festin.server data/kitchen.db --web web/dist` (`FESTIN_WEB` is the same switch). In development leave `--web` off: Vite serves the front end and proxies `/api`.

Chat needs a model key. Set `OPENROUTER_API_KEY` or `FESTIN_MODEL_KEY` in the kitchen's environment, or put it in a `model.key` file (mode 0600) next to the database. Choose the model in Settings.

Everything else lives in Settings: the table's name, the week's first day, the weather location, the plugins and the incoming-recipes switch.

## Tests

```sh
pytest                      # back end
(cd web && npx vitest run)  # front end
npm run build               # must pass
```

## Licence

[MIT](LICENSE).
