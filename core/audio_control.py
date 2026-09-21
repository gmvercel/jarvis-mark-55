from __future__ import annotations

import array
import asyncio
import json
import os
import platform
import re
import subprocess
import threading
import time
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _ROOT / "config" / "api_keys.json"
_MEDIA_VOLUME_STACK: list[list[tuple[object, float]]] = []

DEFAULT_AUDIO_SETTINGS = {
    "adaptive_audio_enabled": True,
    "adaptive_audio_mode": "duck",
    "adaptive_audio_duck_percent": 40,
    "voice_activation_enabled": False,
    "voice_activation_media_mode": "duck",
    "voice_activation_duck_percent": 40,
    "push_to_talk_enabled": False,
    "push_to_talk_chord": "ctrl+space",
}


def load_audio_settings() -> dict:
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    settings = dict(DEFAULT_AUDIO_SETTINGS)
    for key in settings:
        if key in data:
            settings[key] = data[key]
    settings["voice_activation_media_mode"] = (
        "stop" if settings["voice_activation_media_mode"] == "stop" else "duck"
    )
    settings["adaptive_audio_mode"] = (
        "stop" if settings["adaptive_audio_mode"] == "stop" else "duck"
    )
    settings["adaptive_audio_duck_percent"] = max(
        5, min(90, int(settings["adaptive_audio_duck_percent"]))
    )
    return settings


def apply_voice_volume(pcm: bytes, adjustment: int, enabled: bool = True) -> bytes:
    """Scale signed 16-bit mono PCM while preserving its original byte length."""
    if not enabled or not adjustment or len(pcm) < 2:
        return pcm
    gain = max(0.0, 1.0 + max(-100, min(100, int(adjustment))) / 100.0)
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    for index, sample in enumerate(samples):
        samples[index] = max(-32768, min(32767, int(sample * gain)))
    return samples.tobytes() + pcm[len(samples) * 2:]


def _media_key(key: str) -> None:
    try:
        import pyautogui
        pyautogui.press(key)
    except Exception as exc:
        print(f"[Audio] Media key failed: {exc}")


def _media_controls() -> list[object]:
    """Return active per-application volume controls, excluding JARVIS itself."""
    if platform.system() != "Windows":
        return []
    try:
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        controls = []
        for session in AudioUtilities.GetAllSessions():
            try:
                if getattr(session, "State", 1) != 1:
                    continue
                process = session.Process
                if process is None:
                    continue
                if getattr(process, "pid", None) == os.getpid():
                    continue
                control = session._ctl.QueryInterface(ISimpleAudioVolume)
                if control.GetMasterVolume() >= 0:
                    controls.append(control)
            except Exception as exc:
                print(f"[Audio] Skipping unavailable media session: {exc}")
        return controls
    except Exception as exc:
        print(f"[Audio] Per-app media volume unavailable: {exc}")
        return []


def media_output_available() -> bool:
    """Return whether Windows exposes an active media audio session."""
    return bool(_media_controls())


def adjust_media_volume(adjustment: int) -> int:
    """Apply a temporary per-app media-volume adjustment."""
    adjustment = max(-100, min(100, int(adjustment)))
    if not adjustment:
        return 0
    controls = _media_controls()
    if controls:
        snapshot = [(control, float(control.GetMasterVolume())) for control in controls]
        _MEDIA_VOLUME_STACK.append(snapshot)
        delta = adjustment / 100.0
        for control, volume in snapshot:
            control.SetMasterVolume(max(0.0, min(1.0, volume + delta)), None)
        return len(snapshot)
    steps = min(10, max(1, round(abs(adjustment) / 5)))
    key = "volumeup" if adjustment > 0 else "volumedown"
    for _ in range(steps):
        _media_key(key)
    return steps


async def _toggle_media_playback_async() -> bool:
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        session = manager.get_current_session()
        if session is None:
            sessions = manager.get_sessions()
            session = sessions[0] if sessions else None
        if session is None:
            return False
        status = str(session.get_playback_info().playback_status).lower()
        operation = session.try_pause_async if "playing" in status else session.try_play_async
        return bool(await operation())
    except Exception as exc:
        print(f"[Audio] Media transport control failed: {exc}")
        return False


def toggle_media_playback(loop=None) -> None:
    """Pause or resume the active media session, falling back to media keys."""
    # The media key is synchronous and works for browser tabs as well as
    # Spotify/VLC, while the WinRT request can be delayed by the audio loop.
    _media_key("playpause")


def activate_media(mode: str, duck_percent: int = 40, loop=None) -> int:
    """Pause media or duck its per-app volume; return a restore token."""
    if mode == "stop":
        toggle_media_playback(loop)
        return 0
    return adjust_media_volume(-abs(int(duck_percent)))


def restore_ducked_media(steps: int) -> None:
    if _MEDIA_VOLUME_STACK:
        snapshot = _MEDIA_VOLUME_STACK.pop()
        for control, volume in snapshot:
            try:
                control.SetMasterVolume(volume, None)
            except Exception:
                pass
        return
    for _ in range(max(0, int(steps))):
        _media_key("volumeup")


class WakeWordDetector:
    """Local detector for the pre-trained 'hey jarvis' wake phrase."""

    _CHUNK_SAMPLES = 1280  # openWakeWord's recommended 80 ms at 16 kHz
    _THRESHOLD = 0.35
    _REQUIRED_POSITIVE_WINDOWS = 2
    _COOLDOWN_SECONDS = 1.5

    def __init__(self):
        try:
            import openwakeword
            import numpy as np
            from openwakeword.model import Model
        except ImportError as exc:
            raise RuntimeError("Install voice activation with: pip install openwakeword") from exc

        model_dir = Path(openwakeword.__file__).resolve().parent / "resources" / "models"
        model_path = model_dir / "hey_jarvis_v0.1.onnx"
        if not model_path.exists():
            try:
                from openwakeword.utils import download_models
                download_models(model_names=["hey_jarvis"], target_directory=str(model_dir))
            except Exception as exc:
                raise RuntimeError(
                    "The hey_jarvis model is missing and could not be downloaded. "
                    "Check the internet connection and try again."
                ) from exc

        self._np = np
        self._model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        self._pending = bytearray()
        self._positive_windows = 0
        self._cooldown_until = 0.0

    def reset(self) -> None:
        """Discard partial audio so a previous phrase cannot retrigger later."""
        self._pending.clear()
        self._positive_windows = 0
        self._cooldown_until = 0.0

    def detected(self, pcm: bytes) -> bool:
        if not pcm:
            return False
        if time.monotonic() < getattr(self, "_cooldown_until", 0.0):
            return False
        self._pending.extend(pcm)
        chunk_bytes = self._CHUNK_SAMPLES * 2
        detected = False
        while len(self._pending) >= chunk_bytes:
            chunk = bytes(self._pending[:chunk_bytes])
            del self._pending[:chunk_bytes]
            samples = self._np.frombuffer(chunk, dtype=self._np.int16)
            scores = self._model.predict(samples)
            positive = max((float(score) for score in scores.values()), default=0.0) >= self._THRESHOLD
            self._positive_windows = self._positive_windows + 1 if positive else 0
            if self._positive_windows >= self._REQUIRED_POSITIVE_WINDOWS:
                detected = True
                self._positive_windows = 0
                self._cooldown_until = time.monotonic() + self._COOLDOWN_SECONDS
        return detected


async def windows_phrase_contains_jarvis() -> bool:
    """Recognize one Windows speech phrase and match the standalone word Jarvis."""
    try:
        from winrt.windows.media.speechrecognition import SpeechRecognizer
    except ImportError:
        return False
    recognizer = SpeechRecognizer()
    try:
        result = await recognizer.recognize_async()
        text = str(getattr(result, "text", "") or "").casefold()
        return bool(re.search(r"\bjarvis\b", text))
    except Exception:
        return False
    finally:
        try:
            recognizer.close()
        except Exception:
            pass