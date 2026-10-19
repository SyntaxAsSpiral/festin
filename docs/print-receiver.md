# Print receiver protocol

Festin renders every slip as a 576-dot (80 mm) 1-bit PNG, then hands that file
to your printer. One delivery mode is a small HTTP **print receiver**: Festin
POSTs the image; your receiver talks to the driver.

This document is enough for anyone (or their coding agent) to write a receiver
for their own printer. Festin never assumes a particular brand or host name.

## When to use it

Choose **Print receiver** in Settings → Plugins → Thermal printer when the
kitchen app and the printer live on different machines, or when you want a
single service that several apps can share. For a printer on the same box as
Festin, **Print command** (a local `{file}` template) is often simpler.

## Request

```
POST <receiverUrl>/print
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "job_id": "slip-uuid",
  "slip_id": "slip-uuid",
  "source": "festin",
  "sha256": "<hex digest of the PNG bytes>",
  "image": "<base64-encoded PNG>"
}
```

| Field | Meaning |
| --- | --- |
| `job_id` | Idempotency key. Festin uses the slip id. |
| `slip_id` | Same value as `job_id` today; kept for clarity. |
| `source` | Always `festin` from this app. |
| `sha256` | Hex digest of the decoded PNG. Reject the job if it does not match. |
| `image` | Base64 PNG, 576 pixels wide, 1-bit (mode `1`) or grayscale (`L`). |

`receiverUrl` in settings is the base only. Festin appends `/print`.

## Response

HTTP 200 with JSON:

```json
{ "status": "printed" }
```

or

```json
{ "status": "uncertain" }
```

| Status | Meaning |
| --- | --- |
| `printed` | The job reached the printer (or was already completed for this `job_id`). |
| `uncertain` | The outcome is unclear — paper may have moved. Festin will not mint a replacement automatically. |

Any other HTTP status is treated as a hard rejection (Festin surfaces an error
and leaves the slip ready to retry). Network failures become `uncertain`.

## Idempotency

A duplicate `job_id` must **not** print again. Return the prior status
(`printed` or `uncertain`) for that id. Festin already refuses to send a slip
that is no longer `ready`; the receiver is the second line of defence when two
clients share one printer.

## What `uncertain` means

The job may have partially printed, the driver timed out after accepting the
bytes, or the link dropped before the ACK. Tell the cook to look at the tape
before asking for another copy. Do not invent a new `job_id` to "fix" it.

## Minimal reference receiver

A sketch that accepts the POST, checks the digest, writes the PNG, and hands it
to a local command. Replace the command with whatever your printer needs
(`lp`, `tm20-set print png`, …).

```python
#!/usr/bin/env python3
"""Tiny print receiver. Not production-hardened — a starting point."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("PRINT_TOKEN", "change-me")
PRINT_CMD = os.environ.get("PRINT_CMD", "lp -d thermal {file}")
# job_id -> last status
SEEN: dict[str, str] = {}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.rstrip("/") != "/print":
            self.send_error(404)
            return
        auth = self.headers.get("Authorization") or ""
        if auth != "Bearer " + TOKEN:
            self.send_error(401)
            return
        length = int(self.headers.get("Content-Length") or "0")
        body = json.loads(self.rfile.read(length).decode())
        job_id = str(body.get("job_id") or "")
        if not job_id:
            self.send_error(400, "job_id required")
            return
        if job_id in SEEN:
            return self._reply(SEEN[job_id])
        raw = base64.b64decode(body["image"])
        if hashlib.sha256(raw).hexdigest() != body.get("sha256"):
            self.send_error(400, "sha256 mismatch")
            return
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(raw)
                path = tmp.name
            argv = [part.replace("{file}", path) for part in PRINT_CMD.split()]
            code = subprocess.run(argv, timeout=120).returncode
            status = "printed" if code == 0 else "uncertain"
        except OSError:
            status = "uncertain"
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        SEEN[job_id] = status
        self._reply(status)

    def _reply(self, status: str):
        raw = json.dumps({"status": status}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8766), Handler).serve_forever()
```

Run it with a throwaway token, point Festin’s Print receiver URL at
`http://127.0.0.1:8766`, and print a test slip from Settings.

## Out of scope (for now)

- Raw ESC/POS to TCP port 9100 from Festin itself
- 58 mm (384-dot) tape width
