# Festin

A recipe manager and family cookbook, with an optional AI assistant.

My grandmother left over a thousand recipes when she died, mostly handwritten and clipped index cards. They were hard to search, so they mostly sat in the box. My own recipes were scattered across notes apps, email and chats with various AI assistants. Festin keeps all of them in one place, in her style, so the family can use them. My family aren't big on AI or computers, so the cookbook works fully without the AI.

## Features

- **Recipes.** Searchable, with ingredients, method, notes, your own photos and a scan of the original card. Each recipe records where it came from.
- **Meals.** A plan for the week, one dinner per night, marked cooked as you go. It can be printed on a receipt printer.
- **Kitchen Log.** A dated record of what was cooked, added, noted and discussed.
- **To-cook queue.** Flag a recipe and it shows first in the frieze beside the page.
- **Notes.** Short notes about the kitchen, mostly kept by Babette.
- **Babette.** A chat assistant that can read and edit the recipes, plan the week, keep notes and search the Log and past conversations. It works with any OpenAI-compatible endpoint (OpenRouter by default) and is off until you give it a key.
- **Incoming recipes.** An optional second listener that lets outside agents post recipes for review. They can add but not edit. Off by default. See [docs/incoming-recipes.md](docs/incoming-recipes.md).

### Plugins

Off by default; enable them in Settings.

- **Printer.** Prints the week's plan and recipe cards on a receipt printer, through an HTTP receiver or a command on the host. See [docs/print-receiver.md](docs/print-receiver.md).
- **Dinner tattva.** Names each night's element at the dinner hour, from local sunrise.
- **Cloud agents.** Babette can send a list, such as a shopping list, to an outside agent. See [docs/cloud-agents.md](docs/cloud-agents.md).

## Stack

- Front end: Vite, React and Motion, in `web/`.
- Back end: Python standard library over SQLite, in `festin/`. No framework.
- Environment: a Nix flake. `nix develop` provides node, Python with pytest, and sqlite.

The app works on phones, tablets and desktops, and can be installed as an app.

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

Everything else is in Settings: the table's name, the week's first day, the weather location, the plugins and the incoming-recipes switch.

## Tests

```sh
pytest                      # back end
(cd web && npx vitest run)  # front end
npm run build               # must pass
```

## Licence

[MIT](LICENSE).
