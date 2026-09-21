"""Public deployment health check."""
from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler

from api._common import handle_options, send_json


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        handle_options(self)

    def do_GET(self) -> None:
        send_json(self, 200, {
            "ok": True,
            "service": "jarvis-cloud",
            "gemini_configured": bool(os.environ.get("GEMINI_API_KEY")),
            "auth_configured": bool(os.environ.get("JARVIS_CLOUD_TOKEN")),
        })

    def log_message(self, format: str, *args: object) -> None:
        return
