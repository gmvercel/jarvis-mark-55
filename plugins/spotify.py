"""Spotify playback control through the Spotify Web API."""
from __future__ import annotations

import json
import os
import re
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus, unquote

PLUGIN = {
    "name": "spotify",
    "description": (
        "Control Spotify playback directly. Use this for playing a song or playlist, "
        "pausing, resuming, skipping to the next or previous track, and checking the "
        "current track. Use the Spotify Web API when configured and desktop media controls "
        "as a fallback. Do not use youtube_video for Spotify requests."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "play | pause | resume | next | previous | status"},
            "query": {"type": "STRING", "description": "Song, artist, playlist name, Spotify URL, or Spotify URI"},
            "content_type": {"type": "STRING", "description": "track or playlist; omit to detect automatically"},
            "device": {"type": "STRING", "description": "Optional Spotify device name to control"},
        },
        "required": ["action"],
    },
}

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _ROOT / "config" / "api_keys.json"
_CACHE_PATH = (Path(os.environ["SPOTIFY_CACHE_PATH"]).expanduser()
               if os.environ.get("SPOTIFY_CACHE_PATH")
               else Path.home() / ".cache" / "mark-jarvis" / "spotify-token-cache")
_SCOPES = "user-modify-playback-state user-read-playback-state user-read-currently-playing"
_CLIENT = None


def _config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _credentials() -> tuple[str, str, str]:
    config = _config()
    client_id = os.environ.get("SPOTIFY_CLIENT_ID") or config.get("spotify_client_id", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET") or config.get("spotify_client_secret", "")
    redirect_uri = os.environ.get("SPOTIFY_REDIRECT_URI") or config.get(
        "spotify_redirect_uri", "http://127.0.0.1:8888/callback"
    )
    return str(client_id).strip(), str(client_secret).strip(), str(redirect_uri).strip()


def _spotify():
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ModuleNotFoundError as exc:
        missing = exc.name or "a Spotify dependency"
        raise RuntimeError(
            f"Spotify dependency '{missing}' is not available in {sys.executable}. "
            f"Install it with: {sys.executable} -m pip install spotipy"
        ) from exc
    except ImportError as exc:
        raise RuntimeError(
            f"Spotify dependencies could not be imported by {sys.executable}: {exc}"
        ) from exc

    client_id, client_secret, redirect_uri = _credentials()
    if not client_id or not client_secret:
        raise RuntimeError(
            "Spotify is not configured. Add spotify_client_id and spotify_client_secret "
            "to config/api_keys.json or set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET."
        )
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    auth = SpotifyOAuth(
        client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri,
        scope=_SCOPES, cache_path=str(_CACHE_PATH), open_browser=True,
    )
    _CLIENT = spotipy.Spotify(auth_manager=auth)
    return _CLIENT


def _spotify_ref(value: str) -> tuple[str, str] | None:
    value = unquote((value or "").strip())
    match = re.search(r"spotify:(track|playlist):([A-Za-z0-9]+)", value)
    if match:
        return match.group(1), match.group(2)
    match = re.search(r"open\.spotify\.com/(track|playlist)/([A-Za-z0-9]+)", value)
    return (match.group(1), match.group(2)) if match else None


def _device_id(spotify, requested: str = "") -> str | None:
    devices = spotify.devices().get("devices", [])
    if not devices:
        raise RuntimeError("No Spotify device is active. Open Spotify on a phone or computer first.")
    requested = requested.strip().lower()
    if requested:
        for device in devices:
            if device.get("name", "").lower() == requested:
                return device.get("id")
        raise RuntimeError(f"Spotify device '{requested}' was not found.")
    for device in devices:
        if device.get("is_active"):
            return device.get("id")
    return devices[0].get("id")


def _track_label(item: dict) -> str:
    artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
    return f"{item.get('name', 'Unknown track')} - {artists or 'Unknown artist'}"


def _play(spotify, params: dict) -> str:
    query = str(params.get("query") or "").strip()
    if not query:
        spotify.start_playback(device_id=_device_id(spotify, str(params.get("device") or "")))
        return "Spotify playback resumed."
    ref = _spotify_ref(query)
    content_type = str(params.get("content_type") or "").lower().strip()
    if ref:
        content_type, item_id = ref
        uri = f"spotify:{content_type}:{item_id}"
        label = query
    elif content_type == "playlist":
        items = spotify.search(q=query, type="playlist", limit=1).get("playlists", {}).get("items", [])
        if not items:
            return f"No Spotify playlist found for '{query}'."
        uri = items[0]["uri"]
    else:
        items = spotify.search(q=query, type="track", limit=1).get("tracks", {}).get("items", [])
        if not items:
            return f"No Spotify track found for '{query}'."
        track = items[0]
        uri = track["uri"]
        label = _track_label(track)
    device_id = _device_id(spotify, str(params.get("device") or ""))
    if content_type == "playlist":
        spotify.start_playback(device_id=device_id, context_uri=uri)
        return f"Playing Spotify playlist '{query}'."
    spotify.start_playback(device_id=device_id, uris=[uri])
    return f"Playing {label}."


def _status(spotify) -> str:
    current = spotify.current_playback()
    item = (current or {}).get("item") or {}
    if not item:
        return "Spotify is not currently playing anything."
    state = "playing" if current.get("is_playing") else "paused"
    return f"Spotify is {state}: {_track_label(item)}."


def _desktop_fallback(action: str) -> bool:
    """Use Windows media keys for transport commands when the Web API is unavailable."""
    keys = {"pause": "playpause", "resume": "playpause", "next": "nexttrack", "previous": "prevtrack"}
    key = keys.get(action)
    if not key:
        return False


def _open_spotify_search(query: str) -> bool:
    """Open a Spotify search page when API playback is unavailable."""
    try:
        return bool(webbrowser.open(
            f"https://open.spotify.com/search/{quote_plus(query.strip())}"
        ))
    except Exception:
        return False
    try:
        import pyautogui
        pyautogui.press(key)
        return True
    except Exception:
        return False


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action") or "status").lower().strip()
    aliases = {"play_pause": "resume", "playpause": "resume", "prev": "previous", "back": "previous", "skip": "next"}
    action = aliases.get(action, action)
    try:
        spotify = _spotify()
        device_id = _device_id(spotify, str(params.get("device") or "")) if action in {"pause", "resume", "next", "previous"} else None
        if action == "play":
            result = _play(spotify, params)
        elif action == "pause":
            spotify.pause_playback(device_id=device_id)
            result = "Spotify playback paused."
        elif action == "resume":
            spotify.start_playback(device_id=device_id)
            result = "Spotify playback resumed."
        elif action == "next":
            spotify.next_track(device_id=device_id)
            result = "Skipped to the next Spotify track."
        elif action == "previous":
            spotify.previous_track(device_id=device_id)
            result = "Returned to the previous Spotify track."
        elif action == "status":
            result = _status(spotify)
        else:
            return "Unknown Spotify action. Use play, pause, resume, next, previous, or status."
    except Exception as exc:
        if action == "play" and str(params.get("query") or "").strip():
            if _open_spotify_search(str(params["query"])):
                result = "Opened the Spotify search page for the requested item."
            else:
                result = f"Spotify control failed: {exc}"
        elif _desktop_fallback(action):
            labels = {
                "pause": "paused",
                "resume": "resumed",
                "next": "skipped to the next track",
                "previous": "returned to the previous track",
            }
            result = f"Spotify playback {labels[action]} using the desktop media control."
        else:
            result = f"Spotify control failed: {exc}"
    if player:
        try:
            player.write_log(f"[Spotify] {result}")
        except Exception:
            pass
    return result