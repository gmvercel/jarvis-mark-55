"""
ProactiveEngine 2.0 — context-aware, time-aware, non-repetitive background prompting.
Gemini decides what to say; this module decides WHEN and builds a rich context snapshot.
"""
import time
from datetime import datetime
import io
import threading
from pathlib import Path

from memory.memory_manager import format_memory_for_prompt

# OpenCV for camera frame processing
try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False


GENERIC_WINDOW_NAMES = {
    "", "desktop", "win32window", "foreground window", "window", "unknown", "untitled"
}


def _get_camera_index() -> int:
    """Get the configured camera index or default to 0."""
    try:
        import json
        from pathlib import Path
        config_path = Path(__file__).parent.parent / "config" / "api_keys.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            return int(cfg.get("camera_index", 0))
    except Exception:
        pass
    return 0


def _check_camera_available() -> bool:
    """Quick check if camera is accessible (called once at init time)."""
    if not _CV2_AVAILABLE:
        return False
    
    try:
        index = _get_camera_index()
        cap = cv2.VideoCapture(index)
        ret = cap.isOpened()
        cap.release()
        return ret
    except Exception:
        return False


class ProactiveEngine:
    """Generic proactive prompt engine.

    The runtime only needs three capabilities from this class: a cooldown-aware
    trigger gate, a trigger timestamp update, and a prompt composer that can
    fold recent memory and background monitors into a single natural sentence.
    """

    def __init__(self, min_idle_seconds: float = 60.0, cooldown_seconds: float = 1800.0):
        self.min_idle_seconds = min_idle_seconds
        self.cooldown_seconds = cooldown_seconds
        self._last_trigger = 0.0

    def should_trigger(self, last_user_speech: float | None = None) -> bool:
        """Return True when the user has been idle long enough and cooldown expired."""
        if last_user_speech is None:
            last_user_speech = time.monotonic()
        idle_seconds = time.monotonic() - float(last_user_speech)
        if idle_seconds < self.min_idle_seconds:
            return False
        if (time.monotonic() - self._last_trigger) < self.cooldown_seconds:
            return False
        return True

    def mark_triggered(self) -> None:
        self._last_trigger = time.monotonic()

    def build_prompt(self, memory: dict | None = None, monitors: list | None = None,
                     recent_turns: list[str] | None = None) -> str:
        """Compose a lightweight, generic proactive check-in prompt.

        The response stays intentionally generic and avoids any desktop camera or
        foreground-window observation path, matching the user request to remove
        the desktop-aware proactive check-in procedure.
        """
        lines = []
        memory_text = format_memory_for_prompt(memory)
        if memory_text:
            lines.append(memory_text)

        if monitors:
            topics = []
            for item in monitors[:5]:
                topic = item.get("topic") if isinstance(item, dict) else str(item)
                if topic:
                    topics.append(str(topic))
            if topics:
                lines.append("Background monitors: " + ", ".join(topics) + ".")

        if recent_turns:
            recent = " ".join(str(turn).strip() for turn in recent_turns[-4:] if str(turn).strip())
            if recent:
                lines.append("Recent conversation: " + recent[:240] + ".")

        user_context = "\n".join(part for part in lines if part).strip()
        if not user_context:
            return "I’m here if you want a hand with your work."

        return (
            "I noticed a little time has passed while you were working. "
            "Here is a concise context snapshot: " + user_context[:800] +
            "\nWould you like a quick next step or a fresh plan?"
        )
