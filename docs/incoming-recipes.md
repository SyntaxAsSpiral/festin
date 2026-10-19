# Incoming recipes

Outside agents that can search the web find recipes and hand them to Festin.
Babette does not search. The kitchen exposes a second listener just for this
intake. The only Festin setting is an on/off toggle; the sending agent needs the
address and a bearer key.

## Contract

| | |
| --- | --- |
| Listener | Own port (default `8889`), same bind host as the kitchen |
| Routes | `GET /` (this contract) and `POST /recipes` only |
| Auth | `Authorization: Bearer <key>` and `X-Agent-Name` (≤ 80 characters) |
| Body | JSON, ≤ 64 KB, text fields only |

### Fields

| Field | Rule |
| --- | --- |
| `title` | Required, ≤ 200 characters |
| `ingredients` | Required, 1–80 lines, each ≤ 240. JSON array of strings, or one string with newlines |
| `method` | Optional, ≤ 4000 characters (steps) |
| `notes` | Optional, ≤ 4000 characters |
| `source` | Optional, ≤ 300 characters. A site name or URL kept as text — never fetched |
| `voice` | Optional, ≤ 80 characters |

About 30 posts per hour per key; beyond that the listener answers `429`.

A good recipe here has one ingredient per line, a method in steps, and a
`source` that says where it came from.

### Example

```bash
curl -sS -D - -X POST http://127.0.0.1:8889/recipes \
  -H "Authorization: Bearer $FESTIN_INBOX_KEY" \
  -H "X-Agent-Name: my-agent" \
  -H "Content-Type: application/json" \
  -d '{"title":"Agent broth","ingredients":["water","salt"],"method":"1. Simmer.\n2. Season.","source":"https://example.com/broth"}'
```

`GET /` returns the same contract as plain text, or as JSON when `Accept`
includes `application/json`.

### What Festin stores

The row is a normal recipe: `provenance` is the agent name,
`needsPracticeReview` is true, `category` is empty for Babette or the cook.
The Kitchen Log gets a `recipe_added` line with detail `from <agent>`.

## Key

Festin generates a key on first start and stores only its sha256. Settings →
Model → Incoming recipes shows the listener address and a **New key** button.
That button shows the new key once, inside a copyable block (URL, key, example
curl). Auth compares the bearer with a constant-time digest of that hash.

## Toggle

Incoming recipes starts off. Turning it on binds the listener; off closes it again.
The listener always uses the kitchen's bind host; nothing is public until the
host exposes the port.

## Putting the port online

Festin never publishes the inbox. That is a host step:

- **Tailscale Funnel** — serve the inbox port on the mesh/public Funnel URL.
- **Cloudflare tunnel** — point a tunnel hostname at `127.0.0.1:<inbox-port>`.
- **Router** — forward one TCP port to the kitchen host's inbox port on the LAN.

Give agents only the public URL and the current bearer key. Rotate the key
from Settings when a sender should lose access.

## Run locally

```bash
python -m festin.server data/kitchen.db --host 127.0.0.1 --port 8886 --inbox-port 8896
```

Kitchen API on `8886`, incoming recipes on `8896`.

## Telling Festin its public address

Once the inbox port is reachable from outside, start the kitchen with that address so Settings and the agent instructions show it instead of the local port:

```
python -m festin.server <db> --inbox-url https://kitchen.example.net:8443
```

or set `FESTIN_INBOX_URL`. Festin never discovers or opens the public address itself.
