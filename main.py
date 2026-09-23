import os as _os
import platform as _platform
import subprocess as _subprocess

# Qt may report a harmless Windows DPI warning on stderr under PowerShell.
_os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────
# This patches Popen itself, so no per-file flag is needed anywhere.
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)   # drop any stale/shared STARTUPINFO
            super().__init__(args, **                       kw)

    _subprocess.Popen = _Popen

# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import math
import re
from array import array
import threading
import time
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

import sounddevice as sd
from google import genai
from google.genai import types
from google.genai.errors import APIError
from websockets.exceptions import ConnectionClosedError as WSConnectionClosedError
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    save_session_summary, pop_last_session, create_work_session,
    save_restart_context, load_restart_context, clear_restart_context,
)

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.open_app          import close_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import _capture_camera, _capture_screen
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.vscode_control    import vscode_control
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.system_monitor    import SystemMonitor, get_system_status
from actions.proactive         import ProactiveEngine
from actions.background_monitor import (
    add_monitor, remove_monitor, list_monitors, check_all as monitor_check_all,
)
from actions.web_search        import _news as _fetch_news_sync
from memory.config_manager     import get_brief_enabled
from core.plugin_loader        import discover_plugins
from core.audio_control        import (
    WakeWordDetector, activate_media, apply_voice_volume,
    load_audio_settings, media_output_available, restore_ducked_media,
    windows_phrase_contains_jarvis,
)
from core.hotkey               import PushToTalk, parse_chord

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _looks_like_live_stream_error(exc) -> bool:
    """Return True for nested Gemini Live / WebSocket receive failures.

    The Google GenAI client can raise APIError 1011 or ConnectionClosedError
    inside an ExceptionGroup / BaseExceptionGroup produced by asyncio.TaskGroup.
    The outer loop should treat those as a recoverable network stream drop
    instead of as a generic fatal error.
    """
    parts = []

    def walk(item):
        if isinstance(item, BaseExceptionGroup):
            for child in item.exceptions:
                walk(child)
        elif isinstance(item, ExceptionGroup):
            for child in item.exceptions:
                walk(child)
        else:
            parts.append(str(item))

    walk(exc)
    text = "\n".join(parts).lower()
    return any(marker in text for marker in (
        "apierror",
        "connectionclosederror",
        "internal error occurred",
        "received 1011",
        "1011",
        "websocket",
        "websockets",
        "cannot connect",
        "connection refused",
        "timed out",
        "timeouterror",
    ))


def _resolve_config_path() -> Path:
    env_path = _os.environ.get("MARK_LII_CONFIG_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.touch(exist_ok=True)
            if _os.access(candidate.parent, _os.W_OK):
                return candidate
        except Exception:
            pass

    primary = get_base_dir() / "config" / "api_keys.json"
    try:
        primary.parent.mkdir(parents=True, exist_ok=True)
        primary.touch(exist_ok=True)
        if _os.access(primary.parent, _os.W_OK):
            return primary
    except Exception:
        pass

    fallback = Path.home() / "AppData" / "Local" / "Mark-LII" / "config" / "api_keys.json"
    try:
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.touch(exist_ok=True)
    except Exception:
        pass
    return fallback


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = _resolve_config_path()
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

_INSTANCE_MUTEX = None
_INSTANCE_LOCK_FILE = None


def _acquire_single_instance() -> bool:
    """Prevent duplicate GUI/audio loops when a shortcut is clicked twice."""
    global _INSTANCE_MUTEX, _INSTANCE_LOCK_FILE
    if _platform.system() != "Windows":
        return True
    import msvcrt

    lock_path = BASE_DIR / "cache" / "jarvis.instance.lock"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        _INSTANCE_LOCK_FILE = lock_path.open("a+b")
        _INSTANCE_LOCK_FILE.seek(0, 2)
        if _INSTANCE_LOCK_FILE.tell() == 0:
            _INSTANCE_LOCK_FILE.write(b"0")
            _INSTANCE_LOCK_FILE.flush()
        _INSTANCE_LOCK_FILE.seek(0)
        msvcrt.locking(_INSTANCE_LOCK_FILE.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except (OSError, IOError):
        if _INSTANCE_LOCK_FILE:
            _INSTANCE_LOCK_FILE.close()
            _INSTANCE_LOCK_FILE = None
        print("[JARVIS] Another instance is already running.")
        return False

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
                " Do not use it for websites or browser requests; use browser_control instead."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "close_app",
        "description": (
            "Closes a running application. Use this whenever the user asks to close, quit, "
            "terminate, or exit an app or program. Always call this tool."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Name of the application to close (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": (
            "Integrated JARVIS research system. Use this for every search or lookup when "
            "the user does not explicitly specify a browser, and for elaborate informational, "
            "multi-part, explanatory, comparison, or research questions even if they do not "
            "say 'search'. Do not use browser_control for these cases: its results open in the "
            "JARVIS on-screen research card. Always prefer this over guessing. "
            "Modes: 'search' (default), 'news' (latest headlines on a topic), "
            "'research' (deep comprehensive answer), 'price' (product cost lookup), "
            "'compare' (side-by-side comparison of items)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query or topic"},
                "mode":   {"type": "STRING", "description": "search | news | research | price | compare"},
                "items":  {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Items to compare (compare mode)"},
                "aspect": {"type": "STRING", "description": "Comparison aspect: price | specs | reviews | features"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "system_status",
        "description": (
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "resource": {
                    "type": "STRING",
                    "description": "Optional single metric: cpu, ram, gpu, temperature, uptime, or processes. Leave empty for full analysis.",
                },
            },
        }
    },
    {
        "name": "presentation_mode",
        "description": (
            "Controls the JARVIS holographic presentation layout. Use action='mini' when the user says "
            "minimize the system/interface or wants a compact corner mode. Use action='restore' to return "
            "to the normal holographic workspace."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "mini | restore"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "music_status",
        "description": (
            "Shows the currently playing music in the JARVIS music widget. Use when the user asks "
            "what is playing, show the current song, or asks for the music player status."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures the screen or webcam image and lets you analyze it. "
            "MUST be called when user asks what is on screen, what you see, "
            "look at camera, analyze my screen, etc. "
            "You have NO visual ability without this tool. "
            "After the image is captured it is sent directly to you — describe what you see and answer the user's question. "
            "When using camera: the live view stays open until user says close it or calls close_camera."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "close_camera",
        "description": (
            "Closes the live camera view shown on screen. "
            "Call when user says: close camera, stop camera, turn off camera, "
            "kamerayı kapat, kapat, creepy, etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls the web. Use for: opening the integrated browser, opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "When browser is omitted, ALWAYS use JARVIS's integrated visible browser; do not open Chrome or any external browser. "
            "Only use an external browser when the user explicitly names one. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "open | go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Optional external browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the integrated browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "open_file",
        "description": (
            "Displays a file or folder directly in JARVIS's holographic preview panel instead of launching the OS default editor. "
            "Use this whenever the user says 'open', 'apri', 'show', 'mostra' a file, document, or folder. "
            "Never open it in Notepad, Preview, or any external app unless the user explicitly asks for the native app."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Absolute path to the file or folder to preview in the holographic interface"},
                "mode": {"type": "STRING", "description": "Optional: preview | open_native. Default is preview."}
            },
            "required": ["path"]
        }
    },
    {
        "name": "create_3d_hologram",
        "description": (
            "Creates and displays an interactive 3D hologram directly in the JARVIS HUD. "
            "Use for requests such as creating a 3D model of a coin, cube, sphere, or any object. "
            "Do not open a file, image, or separate window for this."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "object": {"type": "STRING", "description": "Object description used to find a real asset in assets/3d"},
                "animation": {"type": "STRING", "description": "Optional animation style, e.g. rotate, scan, pulse"},
                "model_path": {"type": "STRING", "description": "Optional path to a real .glb, .gltf or .obj model"},
            },
            "required": ["object"],
        },
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: open, list, create, delete, move, copy, rename, read, write, write_code, create_project, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "open | list | create_file | create_folder | delete | move | copy | rename | read | write | write_code | create_project | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write/write_code"},
                "structure":   {"type": "OBJECT", "description": "Nested project map for create_project, for example {'src': {'main.py': 'print(\"hi\")'}}"},
                "name":        {"type": "STRING", "description": "File name, project folder, or target search term"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "language":    {"type": "STRING", "description": "Language hint for write_code/create_project"},
                "project_name": {"type": "STRING", "description": "Optional project folder name for create_project"},
                "create_readme": {"type": "BOOLEAN", "description": "Whether to create a README.md in the project scaffold"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "vscode_control",
        "description": (
            "Controls the VS Code workspace for coding and debugging: open workspaces or files, "
            "inspect files, run tests, execute terminal commands, check diagnostics, and open files for debugging."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "open_workspace | open_file | list | test | run | diagnostics | debug"},
                "workspace": {"type": "STRING", "description": "Workspace path; defaults to the JARVIS project"},
                "file_path": {"type": "STRING", "description": "File path for open_file or debug"},
                "line": {"type": "INTEGER", "description": "Optional line to open"},
                "column": {"type": "INTEGER", "description": "Optional column to open"},
                "command": {"type": "STRING", "description": "Terminal command for run or diagnostics"},
                "timeout": {"type": "INTEGER", "description": "Timeout in seconds"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use browser_control or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "manage_monitor",
        "description": (
            "Add, remove, or list background monitoring topics. "
            "JARVIS checks these topics once a day and alerts the user when there is a new development. "
            "Use 'add' when the user says 'monitor X', 'track X', 'follow X'. "
            "Use 'remove' when the user says 'stop monitoring X'. "
            "Use 'list' when the user asks what is being monitored. "
            "Do NOT add crypto, financial, or trading topics."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type":        "STRING",
                    "description": "add | remove | list",
                },
                "topic": {
                    "type":        "STRING",
                    "description": "Topic to monitor or stop monitoring (e.g. 'space exploration', 'AI news')",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "restart_jarvis",
        "description": (
            "Restarts the assistant without requiring the user to close and reopen it manually. "
            "Call this when the user asks to restart, reload, or refresh the assistant. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "shutdown_jarvis",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Jarvis. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "create_work_session",
        "description": (
            "Creates a named thematic work session in long-term memory for a project, "
            "briefing, idea, or research thread. Use this whenever the user wants to "
            "start or anchor a focused conversation with title, topic, and context."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING", "description": "Short session title, e.g. 'Sito portfolio'"},
                "topic": {"type": "STRING", "description": "Topic or theme, e.g. 'web project'"},
                "summary": {"type": "STRING", "description": "Brief context or briefing paragraph"},
                "scope": {"type": "STRING", "description": "Scope such as project, idea, research, or planning"},
            },
            "required": ["title", "topic", "summary"]
        }
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
]

class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self._asst_name     = "JARVIS"   # updated each session from config
        self.session              = None
        self.audio_in_queue       = None
        self.out_queue            = None
        self._loop                = None
        self._is_speaking         = False
        self._speaking_lock       = threading.Lock()
        self._phone_active        = False   # True while phone mic is streaming; pauses PC mic
        self._pending_vision       = None    # (img_bytes, mime_type, question, angle) to inject after tool response
        self._vision_cam_active    = False   # True if camera was opened for vision → auto-close after response
        self._vision_close_pending = False   # True after vision injected; next turn_complete closes camera
        self._vision_last_time     = 0.0     # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy          = False   # True while a vision capture/inject cycle is in flight
        self._interrupted          = False   # True while draining audio after user interrupt
        self._audio_settings       = load_audio_settings()
        self._ptt_held             = False
        self._ptt                  = PushToTalk(
            self._on_ptt_change,
            parse_chord(self._audio_settings.get("push_to_talk_chord", "ctrl+space")),
        )
        self._voice_activation_armed = not self._audio_settings["voice_activation_enabled"]
        self._wake_detector        = None
        self._wake_phrase_task     = None
        self._wake_detector_task   = None
        self._wake_audio_queue     = None
        self._media_gate_active    = False
        self._wake_cooldown_until  = 0.0
        self._media_duck_steps     = 0
        self._media_paused_for_wake = False
        self._media_ducked_for_wake = False
        self._speech_media_duck_steps = 0
        self._media_paused_for_speech = False
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self.ui.on_reminder       = self._on_reminder
        self.ui.on_audio_settings_changed = self._apply_audio_settings
        self.ui.on_restart        = self._request_restart
        self.ui.on_reset_context  = self._request_context_reset
        self._turn_done_event: asyncio.Event | None = None
        self._content_send_lock = asyncio.Lock()
        self._dashboard     = None
        self._briefing_sent    = False          # morning briefing fires once per process
        self._sys_monitor      = SystemMonitor()  # persistent cooldown state
        self._proactive        = ProactiveEngine()
        self._last_user_speech = time.monotonic()  # updated on every user utterance
        self._session_log: list[str] = []          # conversation turns for end-of-session summary
        self._restart_context = load_restart_context()

        self._enhanced_live = True  # affective dialog + proactive audio; auto-disabled if the server rejects them
        _core_names = {t["name"] for t in TOOL_DECLARATIONS}
        self._plugin_registry = discover_plugins(
            plugins_dir=Path(__file__).resolve().parent / "plugins",
            core_tool_names=_core_names,
            logger=lambda msg: (print(f"[Plugins] {msg}"), self.ui.write_log(f"SYS: {msg}")),
        )
        self.ui.get_plugins = self._plugin_registry.list_for_ui
        self.ui.request_say = self.plugin_say   # plugins: mid-task speech channel
        self._configure_push_to_talk()

    def _on_ptt_change(self, held: bool) -> None:
        """Receive global key state without touching Qt from the hotkey thread."""
        self._ptt_held = bool(held)
        self.ui.set_ptt_status(
            bool(self._audio_settings.get("push_to_talk_enabled")),
            self._ptt_held,
            self._ptt.label,
        )

    def _configure_push_to_talk(self) -> None:
        self._ptt.stop()
        self._ptt_held = False
        voice_activation = bool(self._audio_settings.get("voice_activation_enabled"))
        # Wake-word and PTT are alternative microphone gates. Voice activation
        # takes precedence so a stale config cannot silence the post-wake turn.
        enabled = bool(self._audio_settings.get("push_to_talk_enabled")) and not voice_activation
        chord = parse_chord(self._audio_settings.get("push_to_talk_chord", "ctrl+space"))
        self.ui.set_ptt_status(enabled, False, "+".join(chord).upper())
        if enabled:
            self._ptt = PushToTalk(
                self._on_ptt_change,
            chord,
            )
            scope = self._ptt.start()
            print(f"[Audio] Push-to-talk enabled ({self._ptt.label}, {scope}).")

    def _apply_audio_settings(self, settings: dict):
        self._audio_settings.update(settings)
        self._configure_push_to_talk()
        enabled = bool(self._audio_settings.get("voice_activation_enabled"))
        self._voice_activation_armed = not enabled
        self._wake_detector = None
        if enabled and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._prepare_wake_detector_and_start_fallback(), self._loop
            )
        elif self._wake_phrase_task and not self._wake_phrase_task.done():
            self._wake_phrase_task.cancel()
            self._wake_phrase_task = None
        self.ui.write_log(
            f"SYS: Voice activation {'enabled' if enabled else 'disabled'}; "
            f"media mode {self._audio_settings.get('voice_activation_media_mode', 'duck')}."
        )

    def _ensure_wake_listener(self):
        if self._audio_settings.get("voice_activation_enabled") and (
                not self._wake_phrase_task or self._wake_phrase_task.done()):
            self._wake_phrase_task = asyncio.create_task(self._listen_for_jarvis())

    async def _prepare_wake_detector(self):
        try:
            self._wake_detector = await asyncio.to_thread(WakeWordDetector)
        except Exception as exc:
            self._wake_detector = None
            self.ui.write_log(f"ERR: Voice activation unavailable — {exc}")

    async def _prepare_wake_detector_and_start_fallback(self):
        # Run both channels: openWakeWord is fast and local for "hey jarvis";
        # Windows recognition catches the shorter natural "Jarvis" phrase.
        if self._audio_settings.get("voice_activation_enabled"):
            await self._prepare_wake_detector()
            self._ensure_wake_listener()

    async def _process_wake_audio(self):
        queue = self._wake_audio_queue
        if queue is None:
            return
        while self._audio_settings.get("voice_activation_enabled"):
            data = await queue.get()
            detector = self._wake_detector
            if detector and not self._voice_activation_armed:
                try:
                    detected = await asyncio.to_thread(detector.detected, data)
                except Exception as exc:
                    self.ui.write_log(f"ERR: Wake word detector — {exc}")
                    continue
                if detected:
                    self._on_wake_word()

    def _queue_wake_audio(self, data: bytes) -> None:
        """Enqueue microphone data on the asyncio thread, never from PortAudio."""
        queue = self._wake_audio_queue
        if queue is None:
            return
        try:
            queue.put_nowait(data)
        except asyncio.QueueFull:
            pass

    async def _listen_for_jarvis(self):
        """Listen for the exact word Jarvis through Windows speech recognition."""
        while self._audio_settings.get("voice_activation_enabled"):
            # Query Windows media sessions off the PortAudio callback. COM
            # enumeration is too slow and unpredictable for realtime capture.
            self._media_gate_active = media_output_available()
            if not self._media_gate_active:
                await asyncio.sleep(0.2)
                continue
            if not self._voice_activation_armed and await windows_phrase_contains_jarvis():
                self._on_wake_word()
            await asyncio.sleep(0.05)
        self._media_gate_active = False

    def _on_wake_word(self):
        if (
            self._voice_activation_armed
            or time.monotonic() < self._wake_cooldown_until
        ):
            return
        self._voice_activation_armed = True
        self._wake_cooldown_until = time.monotonic() + 5.0
        adaptive_audio_enabled = bool(
            self._audio_settings.get("adaptive_audio_enabled", True)
        )
        media_mode = (
            self._audio_settings.get("adaptive_audio_mode", "duck")
            if adaptive_audio_enabled
            else self._audio_settings.get("voice_activation_media_mode", "duck")
        )
        if self._media_gate_active:
            if media_mode == "stop":
                activate_media("stop", loop=self._loop)
                self._media_paused_for_wake = True
            else:
                self._media_duck_steps = activate_media(
                    "duck", self._audio_settings.get("adaptive_audio_duck_percent", 40)
                )
                self._media_ducked_for_wake = self._media_duck_steps > 0
        self.ui.write_log("SYS: Wake word rilevata. Ora ascolto il comando.")

    def plugin_say(self, instruction: str) -> None:
        """
        Thread-safe speech channel for plugins: lets a plugin ask JARVIS to
        say something short WHILE its run() is still executing (plugins block
        their executor thread, so they can't speak through the tool response
        until they finish). The instruction is injected into the Live session
        exactly like a proactive check-in; Gemini phrases it naturally in the
        user's language. Silently a no-op when no session is connected.
        """
        loop = getattr(self, "_loop", None)
        if not loop or not self.session:
            return

        async def _say():
            try:
                await self._send_content(instruction)
            except Exception as e:
                print(f"[PluginSay] {e}")

        try:
            asyncio.run_coroutine_threadsafe(_say(), loop)
        except Exception as e:
            print(f"[PluginSay] {e}")

    def _make_remote_key(self):
        """Called from Qt main thread when user presses Remote Control."""
        if self._dashboard is None:
            self.ui.write_log(
                "SYS: Dashboard unavailable. "
                "Run: pip install fastapi \"uvicorn[standard]\" cryptography"
            )
            return None
        key    = self._dashboard.new_key()
        url    = self._dashboard.get_url()
        manual = self._dashboard.get_manual_url()
        return url, key, f"{url}/auto-login?key={key}", manual

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        self._live_input_text = text.strip()
        asyncio.run_coroutine_threadsafe(self._send_content(text), self._loop)

    def _request_restart(self) -> None:
        """Start the intentional restart without losing the active conversation."""
        if self._loop:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._restart_with_context())
            )

    def _request_context_reset(self) -> None:
        """Restart with no restored conversation, preserving all other data."""
        if self._loop:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._reset_context_and_restart())
            )

    async def _reset_context_and_restart(self) -> None:
        self.ui.write_log("SYS: Conversation context reset requested.")
        self._session_log = []
        self._restart_context = []
        await asyncio.to_thread(clear_restart_context)
        self.ui.show_restart_animation()
        await asyncio.sleep(1.5)
        cmd = [sys.executable, str(Path(__file__).resolve())] + list(sys.argv[1:])
        try:
            _subprocess.Popen(cmd, creationflags=_subprocess.CREATE_NO_WINDOW)
        except Exception:
            try:
                _os.execv(sys.executable, cmd)
            except Exception:
                return
        _os._exit(0)

    async def _restart_with_context(self) -> None:
        self.ui.write_log("SYS: Restart requested; saving conversation context.")
        await asyncio.to_thread(save_restart_context, self._session_log)
        await self._save_session_summary()
        if self.session:
            try:
                await self._send_content("Say a brief natural goodbye to the user.")
            except Exception:
                pass
        self.ui.show_restart_animation()
        await asyncio.sleep(1.5)
        cmd = [sys.executable, str(Path(__file__).resolve())] + list(sys.argv[1:])
        try:
            _subprocess.Popen(cmd, creationflags=_subprocess.CREATE_NO_WINDOW)
        except Exception:
            try:
                _os.execv(sys.executable, cmd)
            except Exception:
                return
        _os._exit(0)

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            was_speaking = self._is_speaking
            self._is_speaking = value

        if value and not was_speaking:
            if (self._audio_settings.get("adaptive_audio_enabled")
                    and media_output_available()
                    and not self._media_paused_for_wake
                    and not self._media_ducked_for_wake):
                if self._audio_settings.get("adaptive_audio_mode") == "stop":
                    activate_media("stop", loop=self._loop)
                    self._media_paused_for_speech = True
                else:
                    self._media_duck_steps = activate_media(
                        "duck", self._audio_settings.get("adaptive_audio_duck_percent", 35)
                    )
                    self._speech_media_duck_steps = self._media_duck_steps
        elif not value and was_speaking:
            if self._speech_media_duck_steps:
                restore_ducked_media(self._speech_media_duck_steps)
                self._speech_media_duck_steps = 0
                self._media_duck_steps = 0
            if self._media_paused_for_speech:
                activate_media("stop", loop=self._loop)
                self._media_paused_for_speech = False
            if self._media_ducked_for_wake:
                restore_ducked_media(self._media_duck_steps)
                self._media_duck_steps = 0
                self._media_ducked_for_wake = False
            if self._media_paused_for_wake:
                activate_media("stop", loop=self._loop)
                self._media_paused_for_wake = False
            if self._audio_settings.get("voice_activation_enabled"):
                self._wake_cooldown_until = time.monotonic() + 5.0
                if self._wake_detector:
                    self._wake_detector.reset()
                self._voice_activation_armed = False

        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def interrupt(self) -> None:
        """Stop JARVIS mid-speech: drain queued audio and open mic immediately."""
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            drained = 0
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except Exception:
                    break
            if drained:
                print(f"[JARVIS] ✋ Interrupted — {drained} audio chunks discarded")
        # This callback runs on Qt's GUI thread. Media-session enumeration in
        # set_speaking() can block on Windows COM, so defer it to the asyncio
        # loop and return immediately to keep the window responsive.
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._finish_interrupt)
        self.ui.write_log("SYS: Interrupted — listening...")

    def _finish_interrupt(self) -> None:
        self.set_speaking(False)
        if self._turn_done_event:
            self._turn_done_event.clear()

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(self._send_content(text), self._loop)

    async def _send_content(self, text: str) -> None:
        """Serialize text turns so only one response can be generated at a time."""
        await self._send_parts([{"text": text}])

    async def _send_parts(self, parts: list[dict]) -> None:
        """Serialize all client-content turns, including multimodal turns."""
        async with self._content_send_lock:
            if self.session:
                await self.session.send_client_content(
                    turns={"parts": parts},
                    turn_complete=True,
                )

    def _on_reminder(self, message: str):
        self.ui.write_log(f"[Reminder] 🔔 {message}")
        self.speak(f"Reminder: {message}")

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        # Load customization from config
        try:
            _cfg = json.loads(open(API_CONFIG_PATH, encoding="utf-8").read())
            self._asst_name = (_cfg.get("assistant_name") or "JARVIS").strip()
            _user_name = (_cfg.get("user_name") or "").strip()
        except Exception:
            self._asst_name = "JARVIS"
            _user_name = ""

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        # Identity injection — overrides any hardcoded name in prompt.txt
        _addr = (f"Rivolgiti sempre all'utente come '{_user_name}' e parla esclusivamente in italiano."
             if _user_name
             else "Rivolgiti all'utente in italiano e parla esclusivamente in italiano.")
        identity_ctx = (
            f"[IDENTITY]\n"
            f"Your name is {self._asst_name}. "
            f"Always refer to yourself as {self._asst_name}.\n"
            f"{_addr}\n\n"
        )

        parts = [time_ctx, identity_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        cfg = dict(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS + self._plugin_registry.get_tool_declarations()}],
            session_resumption=types.SessionResumptionConfig(),
            # Sliding-window compression: session never dies from a full context
            # window — JARVIS can stay in one conversation for hours
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )
        if self._enhanced_live:
            # Affective dialog: JARVIS hears tone/emotion and adapts its voice.            # Proactive audio: JARVIS stays silent when speech isn't addressed
            # to it (background chatter, talking to someone else in the room).
            cfg["enable_affective_dialog"] = True
            cfg["proactivity"] = types.ProactivityConfig(proactive_audio=True)
        return types.LiveConnectConfig(**cfg)

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")

        if name == "create_work_session":
            title = str(args.get("title") or "Untitled Session").strip()
            topic = str(args.get("topic") or "general").strip()
            summary = str(args.get("summary") or "").strip()
            scope = str(args.get("scope") or "project").strip().lower()
            created = create_work_session(title=title, topic=topic, summary=summary, scope=scope)
            print(f"[Memory] 🧭 Session created: {created.get('title')} / {created.get('topic')}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True, "session": created}
            )

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "open_file":
                file_path = str(args.get("path", "")).strip()
                mode = str(args.get("mode", "preview")).lower().strip()
                if not file_path:
                    result = "No file path was provided."
                elif mode == "open_native":
                    if _platform.system() == "Windows":
                        try:
                            _os.startfile(file_path)
                            result = f"Opened the native app for {Path(file_path).name}."
                        except Exception as exc:
                            result = f"Could not open the native app: {exc}"
                    else:
                        result = "Native file open is disabled in preview mode; use the holographic preview instead."
                else:
                    target = Path(file_path).expanduser()
                    if target.is_dir():
                        self.ui.show_file_preview(str(target))
                        result = f"The folder is displayed in the holographic preview panel: {target.name}."
                    else:
                        self.ui.show_file_preview(file_path)
                        result = f"The file is displayed in the holographic preview panel: {target.name}."

            elif name == "create_3d_hologram":
                description = str(args.get("object", "object")).strip() or "object"
                model_path = str(args.get("model_path", "")).strip()
                self.ui.show_3d_hologram(description, model_path)
                result = f"The real 3D hologram asset for {description} is active in the HUD."

            elif name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "close_app":
                r = await loop.run_in_executor(None, lambda: close_app(parameters=args, response=None, player=self.ui))
                result = r or f"Closed {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "screen_process":
                import time as _t_mod
                _now = _t_mod.monotonic()
                _cooldown = 4.0  # seconds — covers echo window after speaking ends
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    _wait = max(0, _cooldown - (_now - self._vision_last_time))
                    print(f"[Vision] ⏳ Cooldown active ({_wait:.1f}s remaining) — ignoring duplicate call")
                    result = "Vision is still processing the previous request. I will not call this again."
                else:
                    self._vision_busy      = True
                    self._vision_last_time = _now
                    angle     = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    if angle == "camera":
                        img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                        self.ui.start_camera_stream()
                        self._vision_cam_active = True
                        print(f"[Vision] 📷 Camera: {len(img_b):,} bytes")
                        _stall = "camera"
                    else:
                        self.ui.enter_mini_mode()
                        img_b, mime_t = await loop.run_in_executor(None, _capture_screen)
                        print(f"[Vision] 🖥️  Screen: {len(img_b):,} bytes")
                        _stall = "screen"
                    self._pending_vision = (img_b, mime_t, user_text, angle)
                    result = (
                        f"[VISION_ACTIVE] {_stall.capitalize()} captured. "
                        f"Immediately say ONE short natural sentence in Italian, "
                        f"telling them you are looking at their {_stall} right now. "
                        f"Do NOT describe or guess content — the actual image arrives in the NEXT message."
                    )

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "vscode_control":
                r = await loop.run_in_executor(None, lambda: vscode_control(parameters=args))
                result = r or "Done."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
                # Mirror results to the on-screen content panel
                _mode = args.get("mode", "search")
                if r:
                    _query = args.get("query") or ", ".join(args.get("items", []))
                    _label = f"{_mode.upper()} — {_query[:38]}" if _query else _mode.upper()
                    self.ui.show_content(_label, r)
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "system_status":
                r = await loop.run_in_executor(None, get_system_status)
                resource = str(args.get("resource", "")).lower().strip()
                self.ui.show_system_scan(r, resource)
                single_values = {
                    "cpu": f"CPU usage is {r.get('cpu_percent')} percent.",
                    "processor": f"CPU usage is {r.get('cpu_percent')} percent.",
                    "ram": f"RAM usage is {r.get('ram_percent')} percent.",
                    "memory": f"RAM usage is {r.get('ram_percent')} percent.",
                    "gpu": f"GPU load is {r.get('gpu_percent') or 'unavailable'} percent.",
                    "temperature": f"CPU temperature is {r.get('cpu_temp_c') or 'unavailable'} C.",
                    "temp": f"CPU temperature is {r.get('cpu_temp_c') or 'unavailable'} C.",
                    "uptime": f"System uptime is {r.get('uptime')}.",
                    "process": f"There are {r.get('process_count')} active processes.",
                    "processes": f"There are {r.get('process_count')} active processes.",
                }
                result = single_values.get(resource, (
                    f"System analysis, read these values one at a time: CPU {r.get('cpu_percent')} percent; "
                    f"RAM {r.get('ram_percent')} percent; GPU {r.get('gpu_percent') or 'unavailable'} percent; "
                    f"temperature {r.get('cpu_temp_c') or 'unavailable'} C; uptime {r.get('uptime')}; "
                    f"processes {r.get('process_count')}."
                ))

            elif name == "music_status":
                self.ui.show_music_widget()
                result = "The music player widget is displayed with the current track information."

            elif name == "presentation_mode":
                action = args.get("action", "mini").lower().strip()
                if action == "restore":
                    self.ui.restore_presentation()
                    result = "Holographic workspace restored."
                else:
                    self.ui.enter_mini_mode()
                    result = "JARVIS presentation minimized."

            elif name == "manage_monitor":
                action = args.get("action", "").lower().strip()
                topic  = args.get("topic", "").strip()
                if action == "add" and topic:
                    result = await asyncio.to_thread(add_monitor, topic)
                elif action == "remove" and topic:
                    result = await asyncio.to_thread(remove_monitor, topic)
                elif action == "list":
                    topics = await asyncio.to_thread(list_monitors)
                    result = ("Monitoring: " + ", ".join(topics)) if topics else "No topics are being monitored."
                else:
                    result = "Specify action (add/remove/list) and a topic."

            elif name == "restart_jarvis":
                self.ui.write_log("SYS: Restart requested.")
                asyncio.create_task(self._restart_with_context())

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                async def _do_shutdown():
                    await self._save_session_summary()
                    if self.session:
                        try:
                            await self._send_content("Say a brief natural goodbye to the user.")
                        except Exception:
                            pass
                    self.ui.show_shutdown_animation()
                    await asyncio.sleep(1.5)
                    import os as _os
                    _os._exit(0)
                asyncio.create_task(_do_shutdown())

            else:
                if self._plugin_registry.has(name):
                    r = await loop.run_in_executor(
                        None,
                        lambda: self._plugin_registry.run(name, args, player=self.ui, session_memory=None)
                    )
                    result = r or "Done."
                else:
                    result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    def _safe_queue_put(self, queue: asyncio.Queue, item):
        """Drop stale audio instead of crashing when the live queue is saturated."""
        try:
            queue.put_nowait(item)
            return
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                pass

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            try:
                await self.session.send_realtime_input(media=msg)
            except Exception as exc:
                # A completed sender leaves the UI online while microphone input is discarded.
                # Raise so the session TaskGroup reaches the reconnect loop.
                raise RuntimeError(f"Realtime sender stopped: {exc}") from exc

    async def _watch_audio_tasks(self, tasks):
        """Reconnect if an audio task exits without raising an exception."""
        while True:
            await asyncio.sleep(1.0)
            for name, task in tasks:
                if task.done() and not task.cancelled():
                    error = task.exception()
                    detail = f": {error}" if error else ""
                    raise RuntimeError(f"Audio task '{name}' stopped{detail}")

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()
        if self._audio_settings.get("voice_activation_enabled"):
            self._wake_audio_queue = asyncio.Queue(maxsize=32)
            await self._prepare_wake_detector()
            self._ensure_wake_listener()
            self._wake_detector_task = asyncio.create_task(self._process_wake_audio())

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if not jarvis_speaking and not self.ui.muted and not self._phone_active:
                data = indata.tobytes()
                if (self._audio_settings.get("voice_activation_enabled")
                    and self._media_gate_active
                    and not self._voice_activation_armed
                    and self._wake_audio_queue is not None):
                    try:
                        loop.call_soon_threadsafe(self._queue_wake_audio, data)
                    except RuntimeError:
                        pass
                    return
                if (self._audio_settings.get("push_to_talk_enabled")
                    and not self._audio_settings.get("voice_activation_enabled")
                        and not self._ptt_held):
                    # Keep sending silence so server-side VAD can close a turn,
                    # without forwarding room audio while PTT is released.
                    data = b"\x00" * len(data)
                if (self._audio_settings.get("voice_activation_enabled")
                    and self._media_gate_active
                    and not self._voice_activation_armed
                    and time.monotonic() >= self._wake_cooldown_until):
                    return
                item = {"data": data, "mime_type": "audio/pcm"}
                loop.call_soon_threadsafe(self._safe_queue_put, self.out_queue, item)

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[JARVIS] 🎤 Mic stream open")
                self.ui.set_microphone_status("connected")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            mic_error = str(e)
            print(f"[JARVIS] ❌ Mic: {mic_error}")
            mic_failed = True
            
            # Determine if mic is disconnected or unavailable
            if any(keyword in mic_error.lower() for keyword in ["no input device", "no device", "not found"]):
                status = "unavailable"
                msg = "⚠️ No microphone detected. You can still use JARVIS with text input via Remote Dashboard."
            elif any(keyword in mic_error.lower() for keyword in ["disconnected", "unplugged"]):
                status = "disconnected"
                msg = "⚠️ Microphone was disconnected. You can still use JARVIS with text input via Remote Dashboard."
            else:
                status = "unavailable"
                msg = f"⚠️ Microphone error: {mic_error[:80]}. Using text-only mode."
            
            self.ui.set_microphone_status(status)
            self.ui.write_log(msg)
            print(f"[JARVIS] {msg}")

            # Keep the Live session available for text and dashboard commands.
            # A missing microphone must not tear down the receiver and reconnect
            # the whole application in a loop.
            while True:
                await asyncio.sleep(5)
        finally:
            if self._wake_detector_task:
                self._wake_detector_task.cancel()
                self._wake_detector_task = None
            self._wake_audio_queue = None
            if self._wake_phrase_task:
                self._wake_phrase_task.cancel()
                self._wake_phrase_task = None

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                try:
                    async for response in self.session.receive():
                        if response.data:
                            if self._interrupted:
                                pass  # discard: interrupted
                            else:
                                if self._turn_done_event and self._turn_done_event.is_set():
                                    self._turn_done_event.clear()
                                # Split into ~50 ms chunks so interrupt() stops audio within 50 ms
                                # (24000 Hz × 2 bytes/sample × 0.05 s = 2400 bytes per slice)
                                _audio_data = apply_voice_volume(
                                    response.data,
                                    0,
                                )
                                _SLICE = 2400
                                for _i in range(0, len(_audio_data), _SLICE):
                                    # Never drop output chunks: losing them makes long
                                    # responses sound clipped, robotic, or out of order.
                                    await self.audio_in_queue.put(
                                        _audio_data[_i : _i + _SLICE]
                                    )

                        if response.server_content:
                            sc = response.server_content

                            if sc.output_transcription and sc.output_transcription.text:
                                txt = _clean_transcript(sc.output_transcription.text)
                                if txt and txt != (out_buf[-1] if out_buf else ""):
                                    out_buf.append(txt)
                                    self.ui.advance_system_scan_with_voice(txt)

                            if sc.input_transcription and sc.input_transcription.text:
                                txt = _clean_transcript(sc.input_transcription.text)
                                if txt:
                                    in_buf.append(txt)
                                    self._last_user_speech = time.monotonic()

                            if sc.turn_complete:
                                if self._turn_done_event:
                                    self._turn_done_event.set()

                                # If this turn_complete ends an interrupted response, clear the
                                # flag and skip all further processing for that turn.
                                if self._interrupted:
                                    self._interrupted = False
                                    in_buf = []
                                    out_buf = []
                                    continue

                                full_in = " ".join(in_buf).strip()
                                if full_in:
                                    self.ui.write_log(f"You: {full_in}")
                                    self._session_log.append(f"User: {full_in}")
                                    self._session_log = self._session_log[-200:]
                                    if self._dashboard:
                                        asyncio.create_task(self._dashboard.broadcast({
                                            "type": "log", "speaker": "user",
                                            "text": full_in,
                                            "ts": datetime.now().isoformat(),
                                        }))
                                in_buf = []

                                full_out = " ".join(out_buf).strip()
                                if full_out:
                                    self.ui.write_log(f"{self._asst_name}: {full_out}")
                                    self._session_log.append(f"{self._asst_name}: {full_out}")
                                    self._session_log = self._session_log[-200:]
                                    if self._dashboard:
                                        asyncio.create_task(self._dashboard.broadcast({
                                            "type": "log", "speaker": "jarvis",
                                            "text": full_out,
                                            "ts": datetime.now().isoformat(),
                                        }))
                                out_buf = []
                                # Vision injection: model finished tool-response turn → now send the image
                                if self._pending_vision and self.session:
                                    import base64 as _b64
                                    img_b, mime_t, question, angle = self._pending_vision
                                    self._pending_vision = None
                                    b64 = _b64.b64encode(img_b).decode("ascii")
                                    print(f"[Vision] 📤 {len(img_b):,} bytes (angle={angle}) → main session")
                                    await self._send_parts([
                                        {"inline_data": {"mime_type": mime_t, "data": b64}},
                                        {"text": question},
                                    ])
                                    # Mark next turn_complete behaviour depending on angle
                                    if self._vision_cam_active:
                                        # Camera: keep busy until JARVIS finishes speaking the answer
                                        self._vision_cam_active = False
                                        self._vision_close_pending = True
                                    else:
                                        # Screen-only: no camera to close; release busy flag now
                                        self._vision_busy = False
                                elif self._vision_close_pending:
                                    # This turn_complete IS the vision answer — close camera + release busy flag
                                    self._vision_close_pending = False
                                    self._vision_busy = False
                                    async def _cam_close():
                                        await asyncio.sleep(2.0)
                                        self.ui.stop_camera_stream()
                                    asyncio.create_task(_cam_close())

                        if response.tool_call:
                            fn_responses = []
                            for fc in response.tool_call.function_calls:
                                print(f"[JARVIS] 📞 {fc.name}")
                                fr = await self._execute_tool(fc)
                                fn_responses.append(fr)
                            await self.session.send_tool_response(
                                function_responses=fn_responses
                            )
                except (APIError, WSConnectionClosedError, ConnectionRefusedError, TimeoutError, OSError) as e:
                    if _looks_like_live_stream_error(e):
                        print(f"[JARVIS] ❌ Recv: {e}")
                        traceback.print_exc()
                        print("[JARVIS] Live receive stream closed; reconnecting session.")
                        raise RuntimeError("Live receive stream closed") from e
                    raise
        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")

        stream = None
        try:
            try:
                stream = sd.RawOutputStream(
                    samplerate=RECEIVE_SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=CHUNK_SIZE,
                )
                stream.start()
            except Exception as exc:
                message = f"Audio output unavailable: {exc}"
                print(f"[JARVIS] ❌ Play: {message}")
                self.ui.write_log(f"⚠️ {message[:160]}")
                while True:
                    await self.audio_in_queue.get()

            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue

                self.set_speaking(True)

                # Batch all immediately-available chunks into one write to reduce
                # thread-pool round-trips (was one asyncio.to_thread per 50ms slice).
                # Cap at ~200 ms so interrupt() still stops audio within ~200 ms.
                batch = bytearray(chunk)
                while len(batch) < 9600:   # 9600 bytes ≈ 200 ms at 24 kHz / 16-bit mono
                    try:
                        batch.extend(self.audio_in_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                try:
                    samples = array("h")
                    samples.frombytes(batch)
                    rms = math.sqrt(sum(sample * sample for sample in samples) / max(1, len(samples)))
                    self.ui.set_audio_level(min(1.0, rms / 7000.0))
                except Exception:
                    pass

                try:
                    await asyncio.to_thread(stream.write, bytes(batch))
                except (RuntimeError, asyncio.CancelledError):
                    raise RuntimeError("Audio output stream stopped")
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            if stream is not None:
                try:
                    stream.stop()
                finally:
                    stream.close()

    # ── Morning briefing ────────────────────────────────────────────────────────

    async def _send_startup_briefing(self) -> None:
        """
        Two-phase briefing optimized for speed:
          Phase 1 — instant greeting (no tools) → speech starts in <1s
          Phase 2 — news pre-fetched in a background thread while Phase 1 plays,
                    delivered as ready text (no Gemini tool-call round-trip) and
                    shown on the UI content panel. Waits for turn_complete event
                    instead of a fixed sleep so there is no unnecessary gap.
        """
        memory   = load_memory()
        identity = memory.get("identity", {})

        def _val(k: str) -> str:
            e = identity.get(k, {})
            return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()

        lang = "Italian"
        name = _val("name")
        time_str = datetime.now().strftime("%H:%M")

        # Start fetching news immediately — runs in parallel while phase 1 plays
        loop = asyncio.get_event_loop()
        news_future = loop.run_in_executor(None, _fetch_news_sync, "top world news today")

        await asyncio.sleep(0.3)
        if not self.session:
            return

        # ── Phase 1: instant greeting ─────────────────────────────────────────
        lang_clause = f" Respond in {lang}." if lang else ""
        name_clause = f" Address the user as {name}." if name else ""

        # Inject last session context if available — pop removes it so it's never repeated
        last = await asyncio.to_thread(pop_last_session)
        session_clause = ""
        if last:
            try:
                _delta = (datetime.now() - datetime.strptime(last["date"], "%Y-%m-%d")).days
                _when  = "earlier today" if _delta == 0 else ("yesterday" if _delta == 1 else f"{_delta} days ago")
            except Exception:
                _when = "last time"
            session_clause = (
                f" Also briefly and naturally mention that {_when}: {last['summary']}"
            )

        p1 = (
            f"Greet the user warmly, mention it is {time_str}, and say you are fetching today's news now.{session_clause} "
            f"Keep it to 2 short sentences max. Do not call any tools.{lang_clause}{name_clause}"
        )

        # Clear the turn-done event so we can wait for Phase 1 to finish
        if self._turn_done_event:
            self._turn_done_event.clear()

        await self._send_content(p1)
        self.ui.write_log("SYS: Briefing phase 1 (greeting) sent.")

        # ── Phase 2: fire as soon as Phase 1 audio is done ───────────────────
        async def _deliver_news():
            try:
                lang_str = f" Respond in {lang}." if lang else ""

                # Wait for news fetch (already running) and Phase 1 turn-complete
                # in parallel — whichever takes longer determines the wait time
                news_done   = asyncio.wrap_future(news_future)
                turn_waited = False
                if self._turn_done_event:
                    try:
                        await asyncio.wait_for(self._turn_done_event.wait(), timeout=6.0)
                        turn_waited = True
                    except asyncio.TimeoutError:
                        pass

                # Extra buffer: turn_complete fires when Gemini finishes *generating*
                # Phase 1, but audio may still be playing.  Waiting a beat here
                # prevents Phase 2 audio from arriving while Phase 1 is mid-sentence
                # (which sounds like a "repeated first response" to the user).
                if turn_waited:
                    await asyncio.sleep(0.8)
                else:
                    await asyncio.sleep(1.0)

                try:
                    news_text = await asyncio.wait_for(news_done, timeout=4.0)
                except Exception:
                    news_text = ""

                if not self.session:
                    return

                if news_text and len(news_text) > 60:
                    # Show on UI content panel immediately
                    self.ui.show_content("NEWS — top world news today", news_text)

                    p2 = (
                        f"[BRIEFING] Here are today's top news headlines:\n{news_text}\n\n"
                        "Pick ONE headline, summarise it in one sentence, then say the full list "
                        f"is displayed on screen. Do not call any tools.{lang_str}"
                    )
                else:
                    self.ui.show_content(
                        "NEWS — unavailable",
                        "Today's news could not be fetched.\n\n"
                        "The integrated search services are temporarily unavailable "
                        "or their request quota has been reached. Try again later.",
                    )
                    p2 = (
                        "News headlines could not be fetched right now. "
                        f"Let the user know briefly.{lang_str}"
                    )

                await self._send_content(p2)
                self.ui.write_log("SYS: Briefing phase 2 (news) sent.")
            except Exception as e:
                print(f"[Briefing] Phase 2 error: {e}")
                self.ui.write_log(f"SYS: Briefing phase 2 failed: {e}")

        asyncio.create_task(_deliver_news())

    # ── Session memory ──────────────────────────────────────────────────────────

    async def _save_session_summary(self) -> None:
        """Summarise the current session in 1-2 sentences and save to long_term.json."""
        log = self._session_log
        if len(log) < 3:          # need at least one exchange to be worth saving
            return
        self._session_log = []    # reset immediately so the next session starts clean

        memory = load_memory()
        lang_entry = memory.get("identity", {}).get("language", {})
        lang = (lang_entry.get("value", "") if isinstance(lang_entry, dict) else str(lang_entry)).strip()
        lang = "Italian"

        convo = "\n".join(log[-40:])   # cap at last 40 turns to stay within token budget
        prompt = (
            f"Summarize this conversation in 1-2 sentences in {lang}. "
            "Focus on what the user accomplished or discussed. "
            "Output ONLY the summary text, nothing else:\n\n" + convo
        )
        try:
            from google import genai as _genai
            client = _genai.Client(api_key=_get_api_key())
            resp   = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-flash-latest",
                contents=prompt,
            )
            summary = (resp.text or "").strip()
            if summary:
                save_session_summary(summary, lang)
        except Exception as e:
            print(f"[Memory] ⚠️ Session summary failed: {e}")

    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: voice alerts when metrics exceed thresholds."""
        while True:
            await asyncio.sleep(30)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if not alert or not self.session:
                continue
            # Don't interrupt an active conversation
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or (time.monotonic() - self._last_user_speech) < 10:
                continue
            self.ui.show_system_alert(alert)
            try:
                await self._send_content(alert)
            except Exception as e:
                print(f"[Monitor] ⚠️ Could not send alert: {e}")

    async def _run_optional_task(self, name: str, task_factory) -> None:
        """Keep optional services from taking down the Live session."""
        while True:
            try:
                await task_factory()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[JARVIS] Optional task '{name}' stopped: {exc}")
                self.ui.write_log(f"WARN: {name} temporarily unavailable.")
                await asyncio.sleep(5)

    # ── Background monitor ──────────────────────────────────────────────────────

    async def _run_background_monitor(self) -> None:
        """Check user-configured topics once per day; speak alerts when new headlines appear."""
        await asyncio.sleep(600)          # wait 10 min after startup before first check
        while True:
            if self.session:
                # Don't interrupt if user spoke recently or JARVIS is mid-sentence
                with self._speaking_lock:
                    speaking = self._is_speaking
                recent_speech = (time.monotonic() - self._last_user_speech) < 30
                if not speaking and not recent_speech:
                    try:
                        alerts = await asyncio.to_thread(monitor_check_all)
                        memory = load_memory()
                        lang_e = memory.get("identity", {}).get("language", {})
                        lang   = "Italian"
                        for alert in alerts:
                            msg = (
                                f"{alert}\n\n"
                                f"Inform the user about this development naturally in {lang}. "
                                "One brief sentence only."
                            )
                            await self._send_content(msg)
                            self.ui.write_log(f"SYS: Monitor alert sent.")
                            await asyncio.sleep(6)   # gap between consecutive alerts
                    except Exception as e:
                        print(f"[Monitor] ⚠️ Background check error: {e}")
            await asyncio.sleep(3600)     # check every hour

    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: blend generic proactive prompts with desktop-aware observations.
        JARVIS stays silent during active speech, and only comments when the user appears
        engaged in a real task or has been idle long enough to justify a check-in.
        """
        while True:
            await asyncio.sleep(45)

            if not self.session:
                continue

            with self._speaking_lock:
                speaking = self._is_speaking

            if speaking:
                continue

            recent_turns = self._session_log[-8:] if self._session_log else []
            memory = await asyncio.to_thread(load_memory)

            if not self._proactive.should_trigger(self._last_user_speech):
                continue

            self._proactive.mark_triggered()

            try:
                monitors = await asyncio.to_thread(list_monitors)
                prompt = self._proactive.build_prompt(
                    memory=memory,
                    monitors=monitors or None,
                    recent_turns=recent_turns,
                )
                await self._send_content(prompt)
                self.ui.write_log("SYS: Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM chunks from dashboard queue into the Gemini Live session."""
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # No audio for 1 s → phone mic inactive, give PC mic back
                self._phone_active = False
                continue
            self._phone_active = True   # phone is streaming — silence PC mic
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and not self.ui.muted:
                self._safe_queue_put(self.out_queue, chunk)

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    await self._send_content(text)
                    self.ui.write_log(f"[Web]: {text}")
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    async def _restore_restart_context(self) -> None:
        """Restore the prior chat into the UI and the new Live session once."""
        turns = list(self._restart_context)
        if not turns or not self.session:
            return
        self._session_log = turns
        for turn in turns:
            self.ui.write_log(turn)
        context = "\n".join(turns)
        await self.session.send_client_content(
            turns={"parts": [{
                "text": (
                    "[RESTORED CONVERSATION CONTEXT]\n"
                    "This is the conversation from immediately before an intentional restart. "
                    "Continue naturally from it. Do not mention this restoration unless asked.\n"
                    f"{context}"
                )
            }]},
            turn_complete=False,
        )
        await asyncio.to_thread(clear_restart_context)
        self._restart_context = []
        self.ui.write_log("SYS: Conversation context restored after restart.")

    # ── main loop ───────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_event_loop()

        # Start dashboard (optional — needs: pip install fastapi "uvicorn[standard]" cryptography)
        try:
            from dashboard.server import DashboardServer
            self._dashboard = DashboardServer()
            self._dashboard.set_connect_callback(self._on_phone_connected)
            asyncio.create_task(self._dashboard.serve())
            self.ui.set_service_status("REMOTE", "ready", "STARTING")
            # Runs for the whole lifetime, not just inside an active session
            asyncio.create_task(self._process_dashboard_commands())
        except Exception as e:
            print(f"[Dashboard] Disabled: {e}")
            self._dashboard = None

        while True:
            try:
                print("[JARVIS] Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                # Fresh client on every reconnect — avoids stale HTTP session state
                # v1alpha carries the enhanced audio features (affective dialog,
                # proactive audio); if they get rejected we fall back to v1beta.
                client = genai.Client(
                    api_key=_get_api_key(),
                    http_options={"api_version": "v1alpha" if self._enhanced_live else "v1beta"}
                )

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session          = session
                    self.audio_in_queue   = asyncio.Queue(maxsize=240)
                    self.out_queue        = asyncio.Queue(maxsize=96)
                    self._turn_done_event = asyncio.Event()

                    # Reset transient state that must not carry over from a previous session
                    self._pending_vision       = None
                    self._vision_cam_active    = False
                    self._vision_close_pending = False
                    self._vision_busy          = False
                    self._vision_last_time     = 0.0
                    self._interrupted          = False

                    await self._restore_restart_context()

                    print("[JARVIS] Connected.")
                    self.ui.set_service_status("GEMINI", "ok", "ONLINE")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS online.")

                    if self._dashboard:
                        await self._dashboard.broadcast({"type": "status", "state": "active"})

                    audio_tasks = [
                        ("sender", tg.create_task(self._send_realtime())),
                        ("microphone", tg.create_task(self._listen_audio())),
                        ("receiver", tg.create_task(self._receive_audio())),
                        ("player", tg.create_task(self._play_audio())),
                    ]
                    tg.create_task(self._watch_audio_tasks(audio_tasks))
                    tg.create_task(self._run_optional_task("system monitor", self._run_system_monitor))
                    tg.create_task(self._run_optional_task("background monitor", self._run_background_monitor))
                    tg.create_task(self._run_optional_task("proactive mode", self._run_proactive_mode))
                    if self._dashboard:
                        tg.create_task(self._run_optional_task("phone relay", self._relay_phone_audio))

                    # Morning briefing — fires once per process launch (if enabled)
                    if not self._briefing_sent and get_brief_enabled():
                        self._briefing_sent = True
                        tg.create_task(self._run_optional_task("startup briefing", self._send_startup_briefing))

            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                # Catches both Exception and BaseExceptionGroup (Python 3.11+
                # TaskGroup raises BaseExceptionGroup when tasks are cancelled
                # externally, which `except Exception` would miss, letting the
                # exception escape the while-loop and causing asyncio.run() to
                # start shutdown — resulting in "executor after shutdown" errors).
                err_str = str(e)
                print(f"[JARVIS] Error ({type(e).__name__}): {e}")
                traceback.print_exc()

                # Normalise nested Gemini Live receive failures so the reconnect
                # loop can behave like a network hiccup instead of bubbling up an
                # opaque ExceptionGroup whose text hides the real failure signal.
                stream_drop = _looks_like_live_stream_error(e)

                # Enhanced audio features rejected by the server (preview API
                # drift) — drop them and reconnect with the plain config.
                if self._enhanced_live and (
                    "INVALID_ARGUMENT" in err_str
                    or "affective" in err_str.lower()
                    or "proactiv" in err_str.lower()
                    or "Unknown name" in err_str
                    or "unexpected keyword" in err_str
                ):
                    self._enhanced_live = False
                    self.ui.write_log(
                        "SYS: Advanced audio features unavailable — reconnecting without them."
                    )
                    continue

                # Invalid API key — stop hammering the API, prompt re-configuration
                if "API key not valid" in err_str or "1007" in err_str:
                    self.ui.write_log("ERR: API key invalid — please re-enter your key.")
                    self.ui.set_state("SLEEPING")
                    self.ui.prompt_reconfig()
                    while not self.ui._win._ready:
                        await asyncio.sleep(1)
                    print("[JARVIS] New API key saved — reconnecting...")
                    _conn_backoff = 3
                    continue

                # Network / timeout errors — log clearly and back off
                is_net_err = stream_drop or any(k in err_str for k in (
                    "TimeoutError", "timed out", "getaddrinfo", "CancelledError",
                    "ConnectionRefusedError", "ConnectionClosedError", "OSError",
                    "Cannot connect", "APIError", "1011", "Internal error occurred",
                ))
                if is_net_err:
                    _conn_backoff = min(getattr(self, "_conn_backoff", 3) * 2, 60)
                    self._conn_backoff = _conn_backoff
                    self.ui.write_log(
                        f"NET: Live stream dropped — {_conn_backoff}s sonra tekrar deneniyor. "
                        "(VPN veya model endpoint hatası olabilir)"
                    )
                else:
                    self._conn_backoff = 3
            finally:
                self.session = None
                # Only save if there was a real conversation (≥3 turns)
                if len(self._session_log) >= 3:
                    asyncio.create_task(self._save_session_summary())

            self.set_speaking(False)
            self.ui.set_state("SLEEPING")

            if self._dashboard:
                await self._dashboard.broadcast({"type": "status", "state": "sleeping"})

            delay = getattr(self, "_conn_backoff", 3)
            print(f"[JARVIS] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)

def main():
    if not _acquire_single_instance():
        return
    _os.chdir(BASE_DIR)
    ui = JarvisUI("face.png")

    def runner():
        try:
            ui.wait_for_api_key()
            jarvis = JarvisLive(ui)
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")
        except BaseException as exc:
            crash_path = BASE_DIR / "jarvis_crash.log"
            details = traceback.format_exc()
            try:
                crash_path.write_text(details, encoding="utf-8")
            except OSError:
                pass
            print(f"[JARVIS] ❌ Fatal error: {exc}")
            traceback.print_exc()
            try:
                ui.write_log(f"ERR: JARVIS si è arrestato. Dettagli salvati in {crash_path.name}")
                ui.set_state("SLEEPING")
            except Exception:
                pass

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()