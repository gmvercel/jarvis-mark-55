"""Personal task lists, notes, and countdown timers."""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

PLUGIN = {
    "name": "productivity",
    "description": (
        "Manage personal productivity: create and list to-do tasks in multiple lists, "
        "complete or remove tasks, create and read notes, and start or stop countdown timers. "
        "Use this instead of reminders for tasks, notes, or timers."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "One of: add_task, list_tasks, complete_task, remove_task, "
                    "create_list, list_lists, add_note, list_notes, start_timer, "
                    "stop_timer, timer_status, list_notifications"
                ),
            },
            "title": {"type": "STRING", "description": "Task title"},
            "task_id": {"type": "STRING", "description": "Task id"},
            "list_name": {"type": "STRING", "description": "Task list name"},
            "note": {"type": "STRING", "description": "Note text"},
            "minutes": {"type": "INTEGER", "description": "Duration in minutes"},
            "seconds": {"type": "INTEGER", "description": "Duration in seconds"},
        },
        "required": ["action"],
    },
}

_ROOT = Path(__file__).resolve().parent.parent
_DATA_PATH = _ROOT / "memory" / "productivity.json"
_LOCK = threading.RLock()
_TIMER_THREAD: threading.Thread | None = None
_TIMER_STOP = threading.Event()


def _default_data() -> dict:
    return {"lists": {"Inbox": []}, "notes": [], "timer": None}


def _load() -> dict:
    try:
        data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        base = _default_data()
        base.update(data if isinstance(data, dict) else {})
        base["lists"] = base["lists"] if isinstance(base["lists"], dict) else {"Inbox": []}
        base["notes"] = base["notes"] if isinstance(base["notes"], list) else []
        return base
    except Exception:
        return _default_data()


def _save(data: dict) -> None:
    _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = _DATA_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(_DATA_PATH)


def _show(player, title: str, text: str) -> None:
    if player:
        try:
            player.show_content(title, text)
        except Exception:
            pass
        try:
            player.write_log(f"[Productivity] {title}")
        except Exception:
            pass


def _notify(player, message: str) -> None:
    if player:
        try:
            request_say = getattr(player, "request_say", None)
            if request_say:
                request_say(message)
        except Exception:
            pass
        try:
            player.show_system_alert(message)
        except Exception:
            pass
        try:
            player.write_log(f"[Productivity] {message}")
        except Exception:
            pass


def _timer_worker(player) -> None:
    while not _TIMER_STOP.wait(1):
        with _LOCK:
            data = _load()
            timer = data.get("timer")
            now = time.time()
            if timer and now >= timer["ends_at"]:
                label = timer.get("label", "Timer")
                data["timer"] = None
                _save(data)
                _notify(player, f"Timer terminato: {label}")


def _ensure_worker(player) -> None:
    global _TIMER_THREAD
    if _TIMER_THREAD and _TIMER_THREAD.is_alive():
        return
    _TIMER_STOP.clear()
    _TIMER_THREAD = threading.Thread(target=_timer_worker, args=(player,), daemon=True)
    _TIMER_THREAD.start()


def _remaining(item: dict) -> str:
    seconds = max(0, int(item["ends_at"] - time.time()))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _list_tasks(data: dict, list_name: str) -> str:
    names = [list_name] if list_name else list(data["lists"])
    chunks = []
    for name in names:
        tasks = data["lists"].get(name, [])
        chunks.append(f"{name}:" + ("\n" + "\n".join(
            f"[{'x' if task.get('done') else ' '}] {task['id']}: {task['title']}" for task in tasks
        ) if tasks else " empty"))
    return "\n\n".join(chunks)


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    try:
        with _LOCK:
            data = _load()
            if action == "add_task":
                list_name = str(parameters.get("list_name") or "Inbox").strip()
                title = str(parameters.get("title") or "").strip()
                if not title:
                    return "I need a task title."
                data["lists"].setdefault(list_name, []).append({
                    "id": uuid.uuid4().hex[:8], "title": title, "done": False,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                })
                _save(data)
                result = f"Added '{title}' to {list_name}."
            elif action == "list_tasks":
                result = _list_tasks(data, str(parameters.get("list_name") or "").strip())
                _show(player, "TASKS", result)
            elif action in {"complete_task", "remove_task"}:
                task_id = str(parameters.get("task_id") or "").strip()
                found = None
                for tasks in data["lists"].values():
                    for task in tasks:
                        if task["id"] == task_id or task["title"].lower() == task_id.lower():
                            found = task
                            if action == "complete_task":
                                task["done"] = True
                            else:
                                tasks.remove(task)
                            break
                    if found:
                        break
                if not found:
                    return f"Task '{task_id}' was not found."
                _save(data)
                result = f"Task '{found['title']}' {'completed' if action == 'complete_task' else 'removed'}."
            elif action == "create_list":
                name = str(parameters.get("list_name") or "").strip()
                if not name:
                    return "I need a list name."
                data["lists"].setdefault(name, [])
                _save(data)
                result = f"List '{name}' is ready."
            elif action == "list_lists":
                result = "Lists: " + ", ".join(data["lists"])
                _show(player, "LISTS", result)
            elif action == "add_note":
                note = str(parameters.get("note") or parameters.get("title") or "").strip()
                if not note:
                    return "I need the note text."
                data["notes"].append({"id": uuid.uuid4().hex[:8], "text": note,
                                      "created_at": datetime.now().isoformat(timespec="seconds")})
                _save(data)
                result = "Note saved."
            elif action == "list_notes":
                result = "\n".join(f"{item['id']}: {item['text']}" for item in data["notes"]) or "No notes saved."
                _show(player, "NOTES", result)
            elif action == "list_notifications":
                history_path = Path.home() / ".jarvis" / "reminders" / "events" / "history.json"
                try:
                    history = json.loads(history_path.read_text(encoding="utf-8"))
                except Exception:
                    history = []
                result = "\n".join(
                    f"{item.get('created_at', '--')}: {item.get('message', '')}"
                    for item in history[-30:]
                ) or "No notifications saved."
                _show(player, "NOTIFICATIONS", result)
            elif action == "start_timer":
                duration = int(parameters.get("seconds") or int(parameters.get("minutes") or 0) * 60)
                if duration <= 0:
                    return "Tell me how many minutes or seconds."
                label = str(parameters.get("title") or "Timer").strip()
                data["timer"] = {"label": label, "duration": duration, "ends_at": time.time() + duration}
                _save(data)
                _ensure_worker(player)
                try:
                    player.show_productivity_timer("timer")
                except Exception:
                    pass
                result = f"Timer started for {duration // 60} minutes."
            elif action == "stop_timer":
                data["timer"] = None
                _save(data)
                result = "Timer stopped."
            elif action == "timer_status":
                timer = data.get("timer")
                result = f"{timer['label']}: {_remaining(timer)} remaining." if timer else "No timer is running."
                _show(player, "TIMER", result)
            else:
                return "Unknown productivity action."
        if player and action not in {"list_tasks", "list_lists", "list_notes", "list_notifications", "timer_status"}:
            player.write_log(f"[Productivity] {result}")
        return result
    except Exception as exc:
        return f"Productivity action failed: {exc}"
