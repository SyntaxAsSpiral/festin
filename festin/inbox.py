"""Incoming recipes: a second listener for outside agents.

Only GET / (contract) and POST /recipes. Auth is a bearer key whose sha256
lives in settings; the plaintext is shown once when minted. Rate limit is
about 30 posts per hour per key. Text fields only; nothing of the kitchen
API is reachable here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from festin import recipes as recipes_mod
from festin.chat.schemas import PLATE_SLUGS
from festin import settings as core_settings
from festin.schema import connect

BODY_LIMIT = 64 * 1024
RATE_LIMIT = 30
RATE_WINDOW_S = 3600
ALLOWED_FIELDS = frozenset({"title", "category", "description", "ingredients", "notes", "method", "voice", "source"})
# The two whose slugs read oddly to an outside agent.
CATEGORY_HINTS = {"chicken": "chicken (all poultry)", "meats": "meats (meat and game)"}
CATEGORY_TEXT = ", ".join(CATEGORY_HINTS.get(slug, slug) for slug in PLATE_SLUGS)

_INSTRUCTIONS_TEXT = """Festin incoming recipes

POST /recipes — add one recipe (JSON). GET / — this contract (text or JSON).

Auth
  Authorization: Bearer <key>
  X-Agent-Name: <name>   (required, <= 80 characters)

Fields (text only; no images, files, or fetched links)
  title         required, <= 200 characters
  category      required, one of: {categories}
  description   required, <= 300 characters: one or two plain sentences on what
                the dish is and how it is made
  ingredients   required, 1–80 lines, each <= 240 characters
                (JSON array of strings, or one string with newlines)
  method        optional, <= 4000 characters (steps)
  notes         optional, <= 4000 characters
  source        optional, <= 300 characters (site or URL kept as text, never fetched)
  voice         optional, <= 80 characters

Limits
  Request body <= 64 KB
  About 30 recipes per hour per key (HTTP 429 beyond that)

A good recipe here
  One ingredient per line.
  Method written as steps.
  source = where it came from (a site name or URL as plain text).

Example

  curl -sS -D - -X POST {address}/recipes \\
    -H "Authorization: Bearer $FESTIN_INBOX_KEY" \\
    -H "X-Agent-Name: my-agent" \\
    -H "Content-Type: application/json" \\
    -d '{"title":"Agent broth","category":"soups-stews","description":"A plain broth, simmered and seasoned.","ingredients":["water","salt"],"method":"1. Simmer.\\n2. Season.","source":"https://example.com/broth"}'

The kitchen host must expose this port (Tailscale Funnel, Cloudflare tunnel, or
router port-forward). Festin only binds the kitchen's host; it does not put the
port on the public internet.
"""


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def mint_key() -> str:
    return secrets.token_urlsafe(32)


def ensure_inbox_key(conn) -> str | None:
    """Generate a key on first start when none is stored. Returns plaintext once, or None."""
    current = core_settings.get_settings(conn)
    if current.get("inbox_key_hash"):
        return None
    key = mint_key()
    core_settings.update_settings(conn, inbox_key_hash=hash_key(key))
    return key


def rotate_inbox_key(conn) -> str:
    """Mint a new key, store only its sha256, return the plaintext once."""
    key = mint_key()
    core_settings.update_settings(conn, inbox_key_hash=hash_key(key))
    return key


def key_matches(presented: str, stored_hash: str) -> bool:
    if not presented or not stored_hash:
        return False
    digest = hash_key(presented)
    if len(digest) != len(stored_hash):
        return False
    return hmac.compare_digest(digest, stored_hash)


def presented_bearer(header: str | None) -> str:
    if not header:
        return ""
    scheme, _, rest = str(header).strip().partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return rest.strip()


def clean_agent_name(value) -> str:
    name = " ".join(str(value or "").split())
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
        raise ValueError("X-Agent-Name is required.")
    return name


def parse_recipe(body: dict, agent: str) -> dict:
    """Validate agent JSON into create_recipe fields."""
    if not isinstance(body, dict):
        raise ValueError("JSON object required.")
    unknown = set(body) - ALLOWED_FIELDS
    if unknown:
        raise ValueError("Recipe field cannot be set: " + ", ".join(sorted(unknown)))
    title = body.get("title")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
        raise ValueError("Recipes require a title.")
    title = " ".join(title.split())
    category = body.get("category")
    if category not in PLATE_SLUGS:
        raise ValueError("Recipes require a category, one of: " + ", ".join(PLATE_SLUGS))
    description = _optional(body, "description", 300)
    if not description:
        raise ValueError("Recipes require a description: one or two sentences on what the dish is.")
    ingredients = _ingredients(body.get("ingredients"))
    method = _optional(body, "method", 4000)
    notes = _optional(body, "notes", 4000)
    source = _optional(body, "source", 300)
    voice = _optional(body, "voice", 80) or "unknown"
    return {
        "title": title,
        "ingredients": ingredients,
        "method": method,
        "notes": notes,
        # From is always the Web; an author the agent names joins the source credit.
        "voice": "Web",
        "source": ", ".join(part for part in (voice if voice != "unknown" else "", source) if part),
        "provenance": "documented",
        "status": "confirmed",
        "category": category,
        "searchDescription": " ".join(description.split()),
        "stub": False,
    }


def accept_recipe(conn, body: dict, agent: str, *, now: datetime | None = None) -> dict:
    fields = parse_recipe(body, agent)
    return recipes_mod.create_recipe(
        conn,
        fields,
        now=now,
        log_detail=f"from {agent}",
    )


def instructions_payload(address: str) -> dict:
    return {
        "name": "Festin incoming recipes",
        "endpoints": {
            "GET /": "This contract (JSON when Accept includes application/json).",
            "POST /recipes": "Add one recipe.",
        },
        "auth": {
            "Authorization": "Bearer <key>",
            "X-Agent-Name": "required, <= 80 characters",
        },
        "fields": {
            "title": "required, <= 200 characters",
            "category": "required, one of: " + CATEGORY_TEXT,
            "description": "required, <= 300 characters: one or two sentences on what the dish is",
            "ingredients": "required, 1–80 lines, each <= 240 (array or newline string)",
            "method": "optional, <= 4000 characters",
            "notes": "optional, <= 4000 characters",
            "source": "optional, <= 300 characters (text only, never fetched)",
            "voice": "optional, <= 80 characters",
        },
        "limits": {
            "bodyBytes": BODY_LIMIT,
            "perHour": RATE_LIMIT,
        },
        "goodRecipe": {
            "ingredients": "one ingredient per line",
            "method": "steps",
            "source": "where it came from (site or URL as text)",
        },
        "address": address,
        "example": {
            "method": "POST",
            "url": address.rstrip("/") + "/recipes",
            "headers": {
                "Authorization": "Bearer $FESTIN_INBOX_KEY",
                "X-Agent-Name": "my-agent",
                "Content-Type": "application/json",
            },
            "body": {
                "title": "Agent broth",
                "category": "soups-stews",
                "description": "A plain broth of water and salt, simmered and seasoned.",
                "ingredients": ["water", "salt"],
                "method": "1. Simmer.\n2. Season.",
                "source": "https://example.com/broth",
            },
        },
        "hosting": (
            "Expose this one port with Tailscale Funnel, a Cloudflare tunnel, or a "
            "router forward. Festin binds the kitchen host only; it never publishes "
            "the port itself."
        ),
    }


def example_curl(address: str, key: str) -> str:
    base = address.rstrip("/")
    return (
        f"curl -sS -D - -X POST {base}/recipes \\\n"
        f'  -H "Authorization: Bearer {key}" \\\n'
        f'  -H "X-Agent-Name: my-agent" \\\n'
        f'  -H "Content-Type: application/json" \\\n'
        f"""  -d '{{"title":"Agent broth","category":"soups-stews","description":"A plain broth, simmered and seasoned.","ingredients":["water","salt"],"""
        f""""method":"1. Simmer.\\n2. Season.","source":"https://example.com/broth"}}'"""
    )


class RateLimiter:
    """Sliding window: RATE_LIMIT accepts per key hash per RATE_WINDOW_S."""

    def __init__(self):
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def allow(self, key_hash: str, *, now: float | None = None) -> bool:
        instant = now if now is not None else time.monotonic()
        with self._lock:
            cutoff = instant - RATE_WINDOW_S
            window = [t for t in self._hits.get(key_hash, []) if t > cutoff]
            if len(window) >= RATE_LIMIT:
                self._hits[key_hash] = window
                return False
            window.append(instant)
            self._hits[key_hash] = window
            return True


class InboxServer(ThreadingHTTPServer):
    def __init__(self, server_address, db_path, *, public_address: str):
        self.db_path = str(db_path)
        self.public_address = public_address.rstrip("/")
        self.now = lambda: datetime.now(timezone.utc)
        self.rate_limiter = RateLimiter()
        super().__init__(server_address, InboxHandler)


class InboxHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # This port may face the internet: a client that stalls mid-request is dropped.
    timeout = 20

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        path = urlparse(self.path).path
        if path != "/":
            return self._send(404, {"error": "Not found"})
        accept = (self.headers.get("Accept") or "").lower()
        payload = instructions_payload(self.server.public_address)
        if "application/json" in accept:
            return self._send(200, payload)
        body = (
            _INSTRUCTIONS_TEXT.replace("{address}", self.server.public_address)
            .replace("{categories}", CATEGORY_TEXT)
            .encode("utf-8")
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/recipes":
            self._discard_body()
            return self._send(404, {"error": "Not found"})
        try:
            with self._db() as conn:
                settings = core_settings.get_settings(conn)
                if not settings.get("inbox_enabled", False):
                    self._discard_body()
                    return self._send(503, {"error": "Incoming recipes are off."})
                stored_hash = settings.get("inbox_key_hash") or ""
                presented = presented_bearer(self.headers.get("Authorization"))
                if not key_matches(presented, stored_hash):
                    self._discard_body()
                    return self._send(401, {"error": "Unauthorized"})
                content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    self._discard_body()
                    raise ValueError("JSON body required.")
                body = self._read_body()
                agent = clean_agent_name(self.headers.get("X-Agent-Name"))
                if not self.server.rate_limiter.allow(stored_hash):
                    return self._send(429, {"error": "Too many recipes. Try again later."})
                recipe = accept_recipe(conn, body, agent, now=self.server.now())
                return self._send(
                    201,
                    {
                        "id": recipe["id"],
                        "title": recipe["title"],
                        "provenance": recipe["provenance"],
                        "cookCount": recipe.get("cookCount", 0),
                        "status": recipe["status"],
                    },
                )
        except json.JSONDecodeError:
            return self._send(400, {"error": "JSON body required."})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})

    def _db(self):
        conn = connect(self.server.db_path)
        return _closing(conn)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > BODY_LIMIT:
            raise ValueError("Request too large or empty.")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON object required.")
        return data

    def _discard_body(self):
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            return
        if 0 < length <= BODY_LIMIT:
            self.rfile.read(length)

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class _closing:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        self.conn.close()
        return False


def _ingredients(raw) -> list[str]:
    if isinstance(raw, str):
        items = [line.strip() for line in raw.splitlines() if line.strip()]
    elif isinstance(raw, list):
        items = []
        for item in raw:
            if not isinstance(item, str) or not item.strip() or len(item.strip()) > 240:
                raise ValueError("Each ingredient must be text.")
            items.append(" ".join(item.split()))
    else:
        raise ValueError("Recipes require ingredients.")
    if not items or len(items) > 80:
        raise ValueError("Recipes require ingredients.")
    for item in items:
        if len(item) > 240:
            raise ValueError("Each ingredient must be text.")
    return items


def _optional(body: dict, field: str, limit: int) -> str:
    if field not in body:
        return ""
    value = body[field]
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise ValueError("Invalid recipe field: " + field)
    return value.strip()
