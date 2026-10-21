# Festin

**A family cookbook that remembers what you cooked, and can talk about it if you want it to.**

When my grandmother died she left over a thousand recipes: handwritten cards, clipped index cards, notes in the margins. Nobody could find anything in the box, so it sat there collecting dust. My own recipes were no better, scattered across notes apps, old emails and chats with a handful of walled-garden AI assistants.

Festin is where they all live now, in a form the family can use. It is a recipe box and a weekly dinner plan first, in my grandmother's midcentury style, with scans of the original cards kept beside each recipe. The AI is a layer on top. My family are not big fans of AI or computers, so everything a cookbook needs works without it, and the AI never gets in the way of the parts that don't.

## What's in it

**Meals.** One slip for the week: a dinner for each night, marked cooked as you go, under a painted banner. Below it, the Kitchen Log keeps what happened: dinners cooked, recipes added, notes opened and closed, conversations had. Down the side, a frieze of recipes drifts past, a different meal's worth each visit, with whatever you flagged *to cook* at the front.

**Recipes.** The recipe box, searchable and sortable. Each card carries its ingredients, method, notes, photos from your own kitchen and a scan of the original card, and says where it came from. Favourite a dish, queue it for later, record that you cooked it.

**Notes.** Short notes about the kitchen, mostly for Babette to keep: what's running low, what to try next, what someone said about Tuesday's soup.

**Babette.** A chat that knows the kitchen. Point her at any OpenAI-compatible endpoint (OpenRouter by default) and she can read and edit the recipe box, plan the week, keep notes, and search the Log and past conversations. She writes her replies out in dip-pen ink. Don't want her? Leave the key unset and the rest of the app doesn't notice.

**Incoming recipes.** An optional second listener, off until you switch it on, where outside agents can post recipes for review. They can add; they can never edit. See [docs/incoming-recipes.md](docs/incoming-recipes.md).

### Plugins

All off until you turn them on in Settings.

- **Printer.** Prints the week's slip and recipe cards on a receipt printer, through a small HTTP receiver or a command on the host. See [docs/print-receiver.md](docs/print-receiver.md).
- **Dinner tattva.** Names each night's element at the dinner hour, from local sunrise.
- **Cloud agents.** Babette hands a list (a shopping list, say) to an outside agent when you ask. See [docs/cloud-agents.md](docs/cloud-agents.md).

## The look

Festin is meant to feel like paper, not a dashboard. Engraved plates stand in for photos of dishes, the page is ivory with linen cards laid on it, tabs are folders and buttons are keycaps, and everything casts the same soft sepia shadow. It works on a phone, a tablet and a wide desktop, and installs as an app that can run full screen.

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
