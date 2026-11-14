"""Serve an explicitly synthetic roster locally; record requests without credential values."""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pandas as pd

_ITEMS = [
    {"id": 1, "name": "Ada", "category": "confirmed", "price": 20.0},
    {"id": 2, "name": "Ben", "category": "confirmed", "price": 20.0},
    {"id": 3, "name": "Cy", "category": "waitlist", "price": 0.0},
    {"id": 4, "name": None, "category": "confirmed", "price": 20.0},
    {"id": 5, "name": "Eli", "category": "confirmed", "price": 20.0},
    {"id": 7, "name": "Gia", "category": "waitlist", "price": 0.0},
    {"id": 8, "name": "Hale", "category": "confirmed", "price": 20.0},
    {"id": 9, "name": "Ivo", "category": "confirmed", "price": 20.0},
]


def validate_page_size(value):
    """Keep the experiment within the small fixture's bounded page sizes."""
    if type(value) is not int or not 1 <= value <= 8:
        raise ValueError("PAGE_SIZE must be an integer from one through eight")


class RosterFixture:
    """Run an ephemeral loopback API with a complete audit and no replay fallback."""

    def __init__(self):
        """Start a local service and remove inherited worker API authentication."""
        self._previous_token = os.environ.pop("TRAJECTORY_API_TOKEN", None)
        self._rows = []
        self._lock = threading.Lock()
        self._closed = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            """Implement only the bounded synthetic items endpoint."""

            def log_message(self, _format, *args):
                """Keep request logs in the explicit structured audit only."""

            def do_GET(self):  # noqa: N802 - stdlib callback name
                """Serve an exact page and retain only non-secret audit fields."""
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                page, size, status, records, next_page = 0, 0, 400, [], None
                has_authorization = "Authorization" in self.headers
                try:
                    page = int(query["page"][0])
                    size = int(query["page_size"][0])
                    valid = (
                        parsed.path == "/v1/items"
                        and set(query) == {"page", "page_size"}
                        and page >= 1
                        and 1 <= size <= 8
                        and not has_authorization
                    )
                    if valid:
                        start = (page - 1) * size
                        records = _ITEMS[start : start + size]
                        next_page = page + 1 if start + size < len(_ITEMS) else None
                        status = 200
                except (KeyError, ValueError):
                    pass
                body = {"items": records, "next_page": next_page} if status == 200 else {"error": "fixture contract"}
                with owner._lock:
                    owner._rows.append(
                        {
                            "request_index": len(owner._rows) + 1,
                            "page": page,
                            "page_size": size,
                            "returned_rows": len(records),
                            "next_page": next_page,
                            "status": status,
                            "authorization_present": has_authorization,
                        }
                    )
                payload = json.dumps(body, allow_nan=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
        except BaseException:
            if self._previous_token is not None:
                os.environ["TRAJECTORY_API_TOKEN"] = self._previous_token
            raise
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def audit_frame(self):
        """Return the observed request rows without computing analytical summaries."""
        with self._lock:
            return pd.DataFrame([dict(row) for row in self._rows])

    def close(self):
        """Stop the server and restore the inherited token variable without displaying it."""
        if self._closed:
            return
        self._closed = True
        try:
            self._server.shutdown()
            self._thread.join(timeout=2)
            self._server.server_close()
        finally:
            if self._previous_token is not None and "TRAJECTORY_API_TOKEN" not in os.environ:
                os.environ["TRAJECTORY_API_TOKEN"] = self._previous_token
            self._previous_token = None
