# Festin

A kitchen app for one household: the family recipe box, the week's dinners, and Babette, a cook who lives in the margin and helps plan, remember and write things down.

Festin is a rebuild of a kitchen app that has been cooking every night for a while now. It is a work in progress, built in public, and not yet released.

## What it does

- **Meals.** One slip for the week: a dinner per night, marked cooked as you go, with a painted banner over it. The Kitchen Log underneath keeps what happened: dinners, recipes added and first cooked, notes opened and closed, conversations.
- **Recipes.** The recipe box, searchable, with each card's ingredients, method, notes, photos from the kitchen and scans of the original card. Every card says where it came from.
- **Notes.** Short notes on the kitchen, mostly for Babette to keep: what's running low, what to try, what someone said about Tuesday's soup.
- **Babette.** A chat with a model of your choosing (any OpenAI-compatible endpoint, OpenRouter by default). She can read and edit the recipe box, plan the week, keep notes, and search the Log and past conversations.
- **Incoming recipes.** An optional second listener, off until you switch it on, where outside agents may post recipes for review. They can add, never edit. See [docs/incoming-recipes.md](docs/incoming-recipes.md).

### Plugins

Off until you turn them on in Settings.

- **Printer.** Prints the week's slip and recipe cards on a receipt printer, through a small HTTP receiver or a command set on the host. See [docs/print-receiver.md](docs/print-receiver.md).
- **Dinner tattva.** Names each night's element at the dinner hour, from local sunrise.
- **Cloud agents.** Babette can hand a list to an outside agent when you ask, for example a shopping list. See [docs/cloud-agents.md](docs/cloud-agents.md).

## Stack

- **Front end:** Vite, React and Motion, in `web/`.
- **Back end:** Python standard library over SQLite, in `festin/`. No framework.
- **Environment:** a Nix flake. `nix develop` gives node, Python with pytest, and sqlite.

## Running it

```sh
nix develop
(cd web && npm install)

# The kitchen: an empty database is created on first run.
python -m festin.server data/kitchen.db --host 127.0.0.1 --port 8879

# The app, in another shell. Vite sends /api to the kitchen.
npm run dev
```

To serve the built app from the kitchen (one process): `npm run build`, then `python -m festin.server data/kitchen.db --web web/dist` (`FESTIN_WEB` is the same switch). Leave `--web` off in development; Vite still serves the front end and proxies `/api`.

Chat needs a model key: set `OPENROUTER_API_KEY` or `FESTIN_MODEL_KEY` in the kitchen's environment, or put it in a `model.key` file (mode 0600) next to the database. Choose the model in Settings.

Everything else lives in Settings: the table's name, the week's first day, the weather location, plugins and the incoming-recipes switch.

## Tests

```sh
pytest                      # back end
(cd web && npx vitest run)  # front end
npm run build               # must pass
```

## Licence

[MIT](LICENSE).
