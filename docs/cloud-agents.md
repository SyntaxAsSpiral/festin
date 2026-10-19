# Cloud agents (outbound)

Babette can hand a notebook list to one configured cloud agent when the cook
asks. Nothing is scheduled. Recipe intake is the other direction — see
[incoming-recipes.md](incoming-recipes.md).

## Settings

Settings → Plugins → **Cloud agents**. Off by default with the other plugins.

Each destination is:

| Field | Rule |
| --- | --- |
| Name | ≤ 80 characters; not `default` |
| Webhook URL | `http` or `https`, no userinfo in the URL |
| Auth env | Optional environment variable *name* (not the secret) |

Choose one default. `send_list` uses that destination when the cook does not
name an agent. The secret for `auth_env` lives in the kitchen process
environment (for example the service `EnvironmentFile`). Restart the kitchen
after adding a variable so it is loaded.

Destinations are stored in `plugin_settings` for plugin id `outbound`. Auth
env names appear in Settings; secret values never do.

## Tool

`send_list` is registered only while the plugin is on.

| Argument | Rule |
| --- | --- |
| `list_name` | Required. Note type, for example `shopping`. A trailing ` list` is ignored. |
| `agent` | Optional. Destination name; omit to use the Settings default. |

The POST body is JSON:

```json
{"from": "babette", "list": "shopping", "items": ["milk", "eggs"]}
```

Items are the note's non-empty lines (list markers stripped). Exactly one
destination receives the list, once. Sending does not purchase, print, or
change the note.

If `auth_env` is set, the request includes `Authorization: Bearer <env value>`.

## Example

```bash
# Kitchen env
export GROKBOT_WEBHOOK_KEY=scratch-key

# After adding destination "grok-bot" with that auth_env and making it default,
# Babette (or a test) calls send_list with list_name=shopping.
```

## Later

An agent that searches for a recipe can post the result back through the
incoming-recipes inbox. That path is separate from this outbound plugin.
