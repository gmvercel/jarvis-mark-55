"""Shared helpers for the Vercel Cloud API."""
from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_MAX_BODY_BYTES = 32 * 1024
_DEFAULT_MODEL = "gemini-2.5-flash"
_DEFAULT_SYSTEM_PROMPT = (
    "Sei JARVIS Cloud, l'assistente personale dell'utente. "
    "Rispondi in italiano se l'utente scrive in italiano. Sii utile, conciso e chiaro. "
    "Non dichiarare di poter controllare il computer locale: questa API non ha accesso al PC."
)


def _cors_origin() -> str:
    return os.environ.get("CORS_ORIGIN", "*").strip() or "*"


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", _cors_origin())
    handler.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "POST, OPTIONS, GET")
    handler.end_headers()
    handler.wfile.write(body)


def handle_options(handler: BaseHTTPRequestHandler) -> None:
    send_json(handler, 204, {})


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    try:
        size = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ValueError("Invalid Content-Length") from exc
    if size <= 0 or size > _MAX_BODY_BYTES:
        raise ValueError("Request body must be between 1 byte and 32 KB")
    raw = handler.rfile.read(size)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Request body must be valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object")
    return data


def is_authorized(handler: BaseHTTPRequestHandler) -> bool:
    expected = os.environ.get("JARVIS_CLOUD_TOKEN", "")
    supplied = handler.headers.get("Authorization", "")
    if not expected or not supplied.startswith("Bearer "):
        return False
    received = supplied.removeprefix("Bearer ").strip()
    return bool(received) and hmac.compare_digest(received, expected)


def ask_gemini(message: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    model = os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)
    payload = {
        "system_instruction": {
            "parts": [{"text": os.environ.get("JARVIS_SYSTEM_PROMPT", _DEFAULT_SYSTEM_PROMPT)}]
        },
        "contents": [{"role": "user", "parts": [{"text": message}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1200},
    }
    request = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=25) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Gemini request failed ({exc.code}): {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Gemini request timed out or was unreachable") from exc

    parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "".join(str(part.get("text", "")) for part in parts).strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response")
    return text
