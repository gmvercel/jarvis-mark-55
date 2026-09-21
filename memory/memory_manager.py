import json
import os
from datetime import datetime
from threading import Lock
from pathlib import Path
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
BACKUP_MEMORY_PATH = BASE_DIR / "memory" / "long_term.json.bak"
_lock            = Lock()
MAX_VALUE_LENGTH = 380
MEMORY_MAX_CHARS = 2200
RESUME_PATH       = BASE_DIR / "memory" / "restart_context.json"


def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
    }


def _normalize_memory(data: dict | None) -> dict:
    if not isinstance(data, dict):
        return _empty_memory()
    base = _empty_memory()
    for key in base:
        if key not in data:
            data[key] = {}
    return data


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _load_json(path: Path) -> dict:
    if not path.exists():
        return _empty_memory()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Invalid memory json: {exc}") from exc
    if not isinstance(data, dict):
        return _empty_memory()
    return _normalize_memory(data)


def _write_memory_and_backup(memory: dict) -> None:
    memory = _normalize_memory(memory)
    memory = _trim_to_limit(memory)
    _atomic_write_json(MEMORY_PATH, memory)
    _atomic_write_json(BACKUP_MEMORY_PATH, memory)

def load_memory() -> dict:
    """Load persisted memory safely, falling back to the last backup if the main file is corrupt."""
    if not MEMORY_PATH.exists():
        if BACKUP_MEMORY_PATH.exists():
            try:
                return _load_json(BACKUP_MEMORY_PATH)
            except Exception as e:
                print(f"[Memory] ⚠️ Backup memory recovery failed: {e}")
        return _empty_memory()

    with _lock:
        try:
            data = _load_json(MEMORY_PATH)
            return data
        except Exception as e:
            print(f"[Memory] ⚠️ Load error: {e}")
            if BACKUP_MEMORY_PATH.exists():
                try:
                    data = _load_json(BACKUP_MEMORY_PATH)
                    print("[Memory] 🔁 Recovered memory from backup.")
                    return data
                except Exception as backup_error:
                    print(f"[Memory] ⚠️ Backup load error: {backup_error}")
            return _empty_memory()

def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


def _trim_to_limit(memory: dict) -> dict:
    if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
        return memory
    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))
    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        print(f"[Memory] 🗑️  Trimmed {cat}/{key}")
    return memory

def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    memory = _stamp_activity(memory)
    with _lock:
        _write_memory_and_backup(memory)


def _stamp_activity(memory: dict) -> dict:
    """Attach a light time-awareness marker and a generic activity record into memory."""
    if not isinstance(memory, dict):
        return memory
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta = memory.get("meta", {}) if isinstance(memory.get("meta"), dict) else {}
    meta["last_memory_update"] = now
    meta["last_memory_day"] = datetime.now().strftime("%Y-%m-%d")
    memory["meta"] = meta
    return memory


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            new_val  = _truncate_value(str(value["value"] if isinstance(value, dict) else value))
            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True
    return changed


def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()
    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory)
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
    return memory

def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

    meta = memory.get("meta", {}) if isinstance(memory.get("meta"), dict) else {}
    last_update = str(meta.get("last_memory_update") or "")
    if last_update:
        lines.append("Last Memory Update:")
        lines.append(f"  - {last_update}")
        lines.append("")

    # Time-aware prompt signal: if the user has been away, the memory context has a
    # clear temporal anchor and the assistant can naturally reason about elapsed time.
    today = datetime.now().strftime("%Y-%m-%d")
    lines.append("Time Context:")
    lines.append(f"  - Current local day: {today}")
    lines.append("")

    sessions = memory.get("sessions", [])
    if isinstance(sessions, list) and sessions:
        recent = []
        for item in sessions[-5:]:
            if isinstance(item, dict):
                summary = item.get("summary") or item.get("note") or ""
                date = item.get("date") or ""
                if summary:
                    part = f"{date}: {summary}" if date else summary
                    recent.append(part)
        if recent:
            lines.append("Recent Session Context:")
            for entry in recent:
                lines.append(f"  - {entry}")
            lines.append("")

    work_sessions = memory.get("work_sessions", [])
    if isinstance(work_sessions, list) and work_sessions:
        lines.append("Active Work Sessions:")
        for item in work_sessions[-8:]:
            if isinstance(item, dict):
                title = str(item.get("title") or "Untitled Session").strip()
                topic = str(item.get("topic") or "general").strip()
                scope = str(item.get("scope") or "project").strip()
                summary = str(item.get("summary") or "").strip()
                summary_part = f" — {summary}" if summary else ""
                lines.append(f"  - {title} [{scope}] / topic: {topic}{summary_part}")
        lines.append("")

    identity  = memory.get("identity", {})
    id_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in id_fields:
        entry = identity.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in id_fields:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    prefs = memory.get("preferences", {})
    if prefs:
        lines.append("")
        lines.append("Preferences:")
        for key, entry in list(prefs.items())[:15]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    projects = memory.get("projects", {})
    if projects:
        lines.append("")
        lines.append("Active Projects / Goals:")
        for key, entry in list(projects.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    rels = memory.get("relationships", {})
    if rels:
        lines.append("")
        lines.append("People in their life:")
        for key, entry in list(rels.items())[:10]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    wishes = memory.get("wishes", {})
    if wishes:
        lines.append("")
        lines.append("Wishes / Plans / Wants:")
        for key, entry in list(wishes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    notes = memory.get("notes", {})
    if notes:
        lines.append("")
        lines.append("Other notes:")
        for key, entry in list(notes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key}: {val}")

    if not lines:
        return ""

    header = "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > 2000:
        result = result[:1997] + "…"

    return result + "\n"

def create_work_session(title: str, topic: str, summary: str, scope: str = "project") -> dict:
    """Create a named thematic work session stored in long-term memory.

    The payload is intentionally lightweight and human-readable so the LLM can
    later retrieve the active session context naturally in future turns.
    """
    safe_title = str(title or "Untitled Session").strip()
    safe_topic = str(topic or "general").strip()
    safe_summary = str(summary or "").strip()
    safe_scope = str(scope or "project").strip().lower()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    memory = load_memory()
    sessions = memory.get("work_sessions", [])
    if not isinstance(sessions, list):
        sessions = []

    entry = {
        "id": f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(sessions)}",
        "title": safe_title,
        "topic": safe_topic,
        "summary": safe_summary,
        "scope": safe_scope,
        "created_at": now,
        "updated_at": now,
        "notes": [],
    }
    sessions.append(entry)
    memory["work_sessions"] = sessions[-50:]
    save_memory(memory)
    return entry


def list_work_sessions() -> list[dict]:
    memory = load_memory()
    sessions = memory.get("work_sessions", [])
    if not isinstance(sessions, list):
        return []
    return sessions[-20:]


def delete_work_session(session_id: str) -> bool:
    """Delete one work session by id and persist the change."""
    if not session_id:
        return False
    memory = load_memory()
    sessions = memory.get("work_sessions", [])
    if not isinstance(sessions, list):
        return False
    kept = [item for item in sessions if not isinstance(item, dict) or item.get("id") != session_id]
    if len(kept) == len(sessions):
        return False
    memory["work_sessions"] = kept
    save_memory(memory)
    return True


def get_work_session(topic: str | None = None, title: str | None = None) -> dict | None:
    sessions = list_work_sessions()
    if not sessions:
        return None
    if topic:
        topic = str(topic).strip().lower()
        for item in reversed(sessions):
            if str(item.get("topic", "")).lower() == topic:
                return item
    if title:
        title = str(title).strip().lower()
        for item in reversed(sessions):
            if str(item.get("title", "")).lower() == title:
                return item
    return sessions[-1]


def save_generic_conversation_context(summary: str, key: str = "conversation_context") -> str:
    """Persist a generic, non-session conversation note in the notes section.

    The purpose is to remember useful facts from an ordinary conversation without
    forcing every turn into a work-session list structure.
    """
    if not isinstance(summary, str):
        summary = str(summary or "")
    summary = summary.strip()
    if not summary:
        return "No generic context saved."
    safe_key = str(key or "conversation_context").strip() or "conversation_context"
    note = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — {summary}"
    update_memory({"notes": {safe_key: {"value": note}}})
    return f"Saved generic conversation context: {safe_key}"


def append_work_session_note(session_id: str, note: str) -> dict | None:
    """Add or append a note to a previously created work session."""
    if not session_id or not isinstance(note, str):
        return None
    memory = load_memory()
    sessions = memory.get("work_sessions", [])
    if not isinstance(sessions, list):
        sessions = []
    sess = None
    for item in sessions:
        if isinstance(item, dict) and item.get("id") == session_id:
            sess = item
            break
    if not sess:
        return None
    session_notes = sess.get("notes", [])
    if not isinstance(session_notes, list):
        session_notes = []
    session_notes.append({
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "text": note.strip()[:900],
    })
    sess["notes"] = session_notes[-20:]
    sess["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    memory["work_sessions"] = sessions
    save_memory(memory)
    return sess


def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat    = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget


# ── Session memory ─────────────────────────────────────────────────────────────

_SESSION_MAX = 3   # safety cap — in practice 0-1 entries after pop


def save_session_summary(summary: str, language: str = "") -> None:
    """Append a 1-2 sentence session summary to long_term.json['sessions']."""
    summary = (summary or "").strip()
    if not summary:
        return
    memory = load_memory()
    sessions = memory.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
    entry: dict = {
        "date":    datetime.now().strftime("%Y-%m-%d"),
        "summary": summary[:280],
    }
    if language:
        entry["language"] = language
    sessions.append(entry)
    memory["sessions"] = sessions[-_SESSION_MAX:]
    with _lock:
        _write_memory_and_backup(memory)
    print(f"[Memory] 📝 Session saved ({entry['date']}): {summary[:60]}…")


def pop_last_session() -> dict | None:
    """
    Return AND remove the most recent session entry.
    Calling this consumes the entry so it is never repeated in future briefings.
    """
    with _lock:
        if not MEMORY_PATH.exists():
            return None
        try:
            memory = _load_json(MEMORY_PATH)
            sessions = memory.get("sessions", [])
            if not isinstance(sessions, list) or not sessions:
                return None
            entry = sessions.pop()          # remove the last entry
            memory["sessions"] = sessions
            _write_memory_and_backup(memory)
            return entry
        except Exception as e:
            print(f"[Memory] ⚠️ pop_last_session error: {e}")
            if BACKUP_MEMORY_PATH.exists():
                try:
                    memory = _load_json(BACKUP_MEMORY_PATH)
                    sessions = memory.get("sessions", [])
                    if isinstance(sessions, list) and sessions:
                        entry = sessions.pop()
                        memory["sessions"] = sessions
                        _write_memory_and_backup(memory)
                        return entry
                except Exception as backup_error:
                    print(f"[Memory] ⚠️ pop_last_session backup error: {backup_error}")
            return None


def save_restart_context(turns: list[str]) -> None:
    """Persist conversation turns for the intentional in-app restart only."""
    clean = [str(turn).strip() for turn in (turns or []) if str(turn).strip()]
    if not clean:
        return
    payload = {"turns": clean[-40:], "saved_at": datetime.now().isoformat()}
    with _lock:
        RESUME_PATH.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(RESUME_PATH, payload)


def load_restart_context() -> list[str]:
    """Read, without consuming, the context left by an intentional restart."""
    with _lock:
        try:
            data = json.loads(RESUME_PATH.read_text(encoding="utf-8"))
            turns = data.get("turns", [])
            return [str(turn) for turn in turns if str(turn).strip()][-40:]
        except (OSError, ValueError, TypeError):
            return []


def clear_restart_context() -> None:
    with _lock:
        try:
            RESUME_PATH.unlink(missing_ok=True)
        except OSError:
            pass