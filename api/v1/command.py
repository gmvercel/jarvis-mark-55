"""Vercel entrypoint for the Jarvis Cloud command API."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from api._common import ask_gemini, handle_options, is_authorized, read_json, send_json


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        handle_options(self)

    def do_POST(self) -> None:
        if not is_authorized(self):
            send_json(self, 401, {"error": "Unauthorized"})
            return
        try:
            body = read_json(self)
            message = str(body.get("message", "")).strip()
            if not message:
                send_json(self, 400, {"error": "message is required"})
                return
            if len(message) > 8000:
                send_json(self, 413, {"error": "message is too long"})
                return
            reply = ask_gemini(message)
        except ValueError as exc:
            send_json(self, 400, {"error": str(exc)})
            return
        except RuntimeError as exc:
            send_json(self, 502, {"error": str(exc)})
            return
        send_json(self, 200, {"ok": True, "reply": reply})

    def log_message(self, format: str, *args: object) -> None:
        return
