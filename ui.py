from __future__ import annotations

import asyncio
import json
import math
import os
import platform
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}

from PyQt6.QtCore import (
    QEasingCurve, QEvent, QMimeData, QObject, QPoint, QPointF, QPropertyAnimation, QRect,
    QRectF, QSize, Qt, QTimer, QUrl, pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QDragEnterEvent, QDropEvent, QFont,
    QFontDatabase, QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QPolygonF, QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QAbstractItemView, QFileDialog, QCheckBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton, QRadioButton, QScrollArea,
        QMessageBox, QSizeGrip, QSizePolicy, QSlider, QSplitter, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
    QProgressBar,
)
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget

try:
    from core.avatar import HoloAvatar
except Exception:
    HoloAvatar = None

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()


def _resolve_config_file() -> Path:
    env_path = os.environ.get("MARK_LII_CONFIG_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.touch(exist_ok=True)
            if os.access(candidate.parent, os.W_OK):
                return candidate
        except Exception:
            pass

    primary = BASE_DIR / "config" / "api_keys.json"
    try:
        primary.parent.mkdir(parents=True, exist_ok=True)
        primary.touch(exist_ok=True)
        if os.access(primary.parent, os.W_OK):
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


CONFIG_DIR = _resolve_config_file().parent
API_FILE   = _resolve_config_file()


def _read_full_config() -> dict:
    """Read api_keys.json config dict. Returns {} on any error."""
    try:
        return json.loads(API_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


_DEFAULT_W, _DEFAULT_H = 980, 700
_MIN_W,     _MIN_H     = 820, 580
_LEFT_W  = 148
_RIGHT_W = 340

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    BG        = "#00060a"
    PANEL     = "#010d14"
    PANEL2    = "#010f18"
    BORDER    = "#0d3347"
    BORDER_B  = "#1a5c7a"
    BORDER_A  = "#0f4060"
    PRI       = "#00d4ff"
    PRI_DIM   = "#007a99"
    PRI_GHO   = "#001f2e"
    ACC       = "#ff6b00"
    ACC2      = "#ffcc00"
    GREEN     = "#00ff88"
    GREEN_D   = "#00aa55"
    RED       = "#ff3355"
    MUTED_C   = "#ff3366"
    TEXT      = "#8ffcff"
    TEXT_DIM  = "#3a8a9a"
    TEXT_MED  = "#5ab8cc"
    WHITE     = "#d8f8ff"
    DARK      = "#000d14"
    BAR_BG    = "#011520"


# Ana renge (accent) bağlı anahtarlar — durum renkleri (ACC, GREEN, RED…) sabit kalır
_HUE_LINKED = (
    "BG", "PANEL", "PANEL2", "BORDER", "BORDER_B", "BORDER_A",
    "PRI", "PRI_DIM", "PRI_GHO", "TEXT", "TEXT_DIM", "TEXT_MED",
    "WHITE", "DARK", "BAR_BG",
)
_PALETTE_DEFAULTS: dict[str, str] = {k: getattr(C, k) for k in _HUE_LINKED}

DEFAULT_UI_COLOR = _PALETTE_DEFAULTS["PRI"]


def apply_ui_accent(accent_hex: str) -> bool:
    """
    Seçilen accent rengine göre tüm turkuaz-ailesi paleti yeniden türetir
    (hue kaydırma — parlaklık/doygunluk oranları korunur, tasarım bozulmaz).
    Boyanan öğeler (HUD, dalga formu, metrikler) bir sonraki karede yeni
    rengi alır; stylesheet tabanlı paneller yeniden kurulduklarında alır.
    """
    import colorsys

    accent_hex = (accent_hex or "").strip().lower()
    if not (accent_hex.startswith("#") and len(accent_hex) == 7):
        return False
    try:
        int(accent_hex[1:], 16)
    except ValueError:
        return False

    def _hsv(h: str) -> tuple[float, float, float]:
        r = int(h[1:3], 16) / 255
        g = int(h[3:5], 16) / 255
        b = int(h[5:7], 16) / 255
        return colorsys.rgb_to_hsv(r, g, b)

    base_h            = _hsv(_PALETTE_DEFAULTS["PRI"])[0]
    acc_h, acc_s, _av = _hsv(accent_hex)
    dh   = acc_h - base_h
    grey = acc_s < 0.08   # griye yakın accent → tüm tema desaturize edilir

    for key, hex0 in _PALETTE_DEFAULTS.items():
        h, s, v = _hsv(hex0)
        if grey:
            s *= 0.15
        r, g, b = colorsys.hsv_to_rgb((h + dh) % 1.0, s, v)
        setattr(C, key, "#{:02x}{:02x}{:02x}".format(
            int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5)))
    return True


def current_palette() -> dict[str, str]:
    """C sınıfındaki accent'e bağlı renklerin anlık kopyası."""
    return {k: getattr(C, k) for k in _HUE_LINKED}


def retheme_all_widgets(old: dict[str, str], new: dict[str, str]) -> None:
    """
    CANLI tam tema değişimi. Uygulamadaki HER widget'ın stylesheet'inde eski
    palet renklerini yenileriyle değiştirir ve yeniden çizdirir. Böylece renk
    değişimi yalnızca boyanan öğelerde değil, panel/buton/kenarlık dahil tüm
    arayüzde ANINDA uygulanır — yeniden başlatma gerekmez.
    """
    mapping = {old[k].lower(): new[k].lower()
               for k in old if old[k].lower() != new.get(k, old[k]).lower()}
    if not mapping:
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in app.allWidgets():
        try:
            ss = w.styleSheet()
            if ss:
                s2 = ss
                for o, n in mapping.items():
                    if o in s2:
                        s2 = s2.replace(o, n)
                if s2 != ss:
                    w.setStyleSheet(s2)
            w.update()
        except Exception:
            pass


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c


# ── Windows GPU via NVML DLL (no subprocess, no console window) ──────────────
_nvml_lib: object = None   # cached ctypes DLL
_nvml_ok:  object = None   # None=untested, True=works, False=unavailable


def _nvml_gpu_windows() -> float:
    """Return NVIDIA GPU utilisation % using nvml.dll directly — zero subprocess."""
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False:
        return -1.0
    try:
        import ctypes

        class _Util(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        if _nvml_lib is None:
            for dll_name in ("nvml", r"C:\Windows\System32\nvml.dll"):
                try:
                    lib = ctypes.WinDLL(dll_name)
                    lib.nvmlInit_v2()
                    _nvml_lib = lib
                    break
                except Exception:
                    continue

        if _nvml_lib is None:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            _nvml_ok = True
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)

        dev = ctypes.c_void_p()
        _nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        util = _Util()
        _nvml_lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util))
        _nvml_ok = True
        return float(util.gpu)
    except Exception:
        _nvml_ok = False
        return -1.0


class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # pynvml — subprocess-free, works on all platforms if installed
        try:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
        except Exception:
            pass

        # Windows: nvml.dll via ctypes (already cached in _nvml_gpu_windows)
        if _OS == "Windows":
            return _nvml_gpu_windows()

        # Linux / macOS: libnvidia-ml shared lib via ctypes
        try:
            import ctypes
            _lib = "libnvidia-ml.so.1" if _OS == "Linux" else "libnvidia-ml.dylib"

            class _Util(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            nv = ctypes.CDLL(_lib)
            nv.nvmlInit_v2()
            dev = ctypes.c_void_p()
            nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
            u = _Util()
            nv.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
            return float(u.gpu)
        except Exception:
            pass

        return -1.0   # N/A — zero subprocess on all platforms

    def _get_temp(self) -> float:
        # psutil — works on Linux; occasionally Windows with driver support
        try:
            temps = psutil.sensors_temperatures()
            for name in ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                         "cpu-thermal", "zenpower", "it8688"]:
                if name in temps and temps[name]:
                    return temps[name][0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass

        # Windows: wmi module (pure Python COM, zero subprocess)
        if _OS == "Windows":
            try:
                import wmi  # type: ignore
                w = wmi.WMI(namespace="root/wmi")
                tz = w.MSAcpi_ThermalZoneTemperature()
                if tz:
                    return (tz[0].CurrentTemperature / 10.0) - 273.15
            except Exception:
                pass

        return -1.0   # N/A — zero subprocess on all platforms

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()

class HudCanvas(QWidget):
    def __init__(self, face_path: str, assistant_name: str = "J.A.R.V.I.S", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"
        self._assistant_name = assistant_name
        self._presentation_x = 0
        self._avatar = None
        if HoloAvatar is not None:
            try:
                self._avatar = HoloAvatar()
            except Exception:
                self._avatar = None
        self._audio_level = 0.0
        self._avatar_phase = 0.0
        self._avatar_particles: list[list[float]] = []
        self._ambient_particles = [
            [random.random(), random.random(), random.uniform(0.12, 0.42), random.uniform(0.4, 1.2)]
            for _ in range(42)
        ]
        self._ambient_phase = random.random() * math.pi * 2

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._scan       = 0.0
        self._scan2      = 180.0
        self._rings      = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._load_face(face_path)

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def _get_presentation_x(self):
        return self._presentation_x

    def _set_presentation_x(self, value):
        self._presentation_x = int(value)
        self.update()

    presentation_x = pyqtProperty(int, _get_presentation_x, _set_presentation_x)

    def set_audio_level(self, level: float) -> None:
        self._audio_level = max(0.0, min(1.0, float(level)))

    def push_visemes(self, frames, hop: float, at: float) -> None:
        """Compatibility hook for the higher-fidelity avatar pipeline."""
        if frames:
            self.set_audio_level(max(frame[0] for frame in frames))

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap(); px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _step(self):
        self._tick += 1
        now = time.time()
        if now - self._last_t > (0.12 if self.speaking else 0.5):
            if self.speaking:
                self._tgt_scale = random.uniform(1.06, 1.14)
                self._tgt_halo  = random.uniform(145, 190)
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo  = random.uniform(15, 28)
            else:
                self._tgt_scale = random.uniform(1.001, 1.008)
                self._tgt_halo  = random.uniform(48, 68)
            self._last_t = now

        sp = 0.38 if self.speaking else 0.15
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        speeds = [1.3, -0.9, 2.0] if self.speaking else [0.55, -0.35, 0.9]
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        self._scan  = (self._scan  + (3.0 if self.speaking else 1.3)) % 360
        self._scan2 = (self._scan2 + (-2.0 if self.speaking else -0.75)) % 360

        fw  = min(self.width(), self.height())
        lim = fw * 0.74
        spd = 4.2 if self.speaking else 2.0
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (0.07 if self.speaking else 0.025):
            self._pulses.append(0.0)

        if self.speaking and random.random() < 0.28:
            cx, cy = self.width() / 2, self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.28
            self._particles.append([
                cx + math.cos(ang) * r_s, cy + math.sin(ang) * r_s,
                math.cos(ang) * random.uniform(0.9, 2.4),
                math.sin(ang) * random.uniform(0.9, 2.4) - 0.4, 1.0,
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97, p[4]-0.028]
            for p in self._particles if p[4] > 0
        ]

        if self._avatar is not None:
            dt = max(0.001, min(0.1, now - getattr(self, "_avatar_time", now)))
            self._avatar_time = now
            self._avatar_phase = (self._avatar_phase + dt * (1.8 if self.speaking else 0.65)) % (2 * math.pi)
            if self.speaking and random.random() < 0.18:
                angle = random.uniform(0, 2 * math.pi)
                radius = min(self.width(), self.height()) * random.uniform(0.28, 0.40)
                self._avatar_particles.append([
                    angle, radius, random.uniform(0.25, 0.7), random.uniform(0.35, 0.9)
                ])
            self._avatar_particles = [
                [angle + dt * speed, radius + dt * 10.0, life - dt, speed]
                for angle, radius, life, speed in self._avatar_particles
                if life > dt
            ]
            self._avatar.step(
                dt,
                self._audio_level,
                speaking=self.speaking,
                muted=self.muted,
                state=self.state,
            )
            self._audio_level *= 0.86

        self._ambient_phase = (self._ambient_phase + dt * (0.22 if not self.speaking else 0.55)) % (math.pi * 2)
        for particle in self._ambient_particles:
            particle[1] -= dt * particle[3] * (0.0018 if not self.speaking else 0.0032)
            particle[0] += math.sin(self._ambient_phase + particle[3]) * dt * 0.0008
            if particle[1] < -0.04:
                particle[0] = random.random()
                particle[1] = 1.04

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0
        self.update()

    def _paint_status(self, p, W, H, cx, cy, fw):
        sy = cy + fw * 0.40
        if self.muted:
            txt, col = "⊘  MUTED", qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING", qcol(C.ACC)
        elif self.state == "THINKING":
            txt, col = "◈  THINKING", qcol(C.ACC2)
        elif self.state == "PROCESSING":
            txt, col = "▷  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            txt, col = "●  LISTENING", qcol(C.GREEN)
        else:
            txt, col = f"●  {self.state}", qcol(C.PRI)
        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        p.translate(self._presentation_x, 0)
        fw = min(W, H)

        if self._avatar is not None:
            self._paint_ambient_field(p, W, H, cx, cy, fw)
            self._paint_avatar_effects(p, cx, cy - fw * 0.04, fw * 0.33, fw)
            self._avatar.paint(
                p, cx, cy - fw * 0.04, fw * 0.33,
                qcol(C.PRI), qcol(C.ACC), qcol(C.BG)
            )
            self._paint_status(p, W, H, cx, cy, fw)
            return

    def _paint_ambient_field(self, p, W: float, H: float, cx: float, cy: float, fw: float):
        """Atmospheric HUD field behind the avatar, kept subtle at idle."""
        energy = min(1.0, self._audio_level + (0.22 if self.speaking else 0.0))
        p.save()
        p.setPen(Qt.PenStyle.NoPen)

        aura = QRadialGradient(cx, cy, fw * (0.78 + energy * 0.12))
        aura.setColorAt(0.0, QColor(0, 145, 190, int(22 + energy * 42)))
        aura.setColorAt(0.42, QColor(0, 70, 110, int(14 + energy * 22)))
        aura.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(aura))
        p.drawEllipse(QRectF(cx - fw * 0.82, cy - fw * 0.82, fw * 1.64, fw * 1.64))

        for x, y, alpha, size in self._ambient_particles:
            px, py = x * W, y * H
            pulse = 0.55 + 0.45 * math.sin(self._ambient_phase * size + x * 8)
            color = C.ACC if self.speaking and size > 0.75 else C.PRI
            p.setBrush(qcol(color, int(alpha * pulse * (150 + energy * 80))))
            p.drawEllipse(QPointF(px, py), size, size)

        # HUD corner brackets frame the workspace without reintroducing a grid.
        margin = max(18.0, fw * 0.055)
        arm = max(18.0, fw * 0.07)
        p.setPen(QPen(qcol(C.PRI, int(70 + energy * 80)), 1.2))
        for x, y, dx, dy in (
            (margin, margin, 1, 1), (W - margin, margin, -1, 1),
            (margin, H - margin, 1, -1), (W - margin, H - margin, -1, -1),
        ):
            p.drawLine(QPointF(x, y), QPointF(x + dx * arm, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * arm))
        p.restore()

    def _paint_avatar_effects(self, p, cx: float, cy: float, radius: float, fw: float):
        """Draw restrained reactor effects behind the animated face."""
        active = self.speaking or self._audio_level > 0.03
        primary = qcol(C.ACC if self.speaking else C.PRI)
        secondary = qcol(C.PRI)
        energy = min(1.0, self._audio_level + (0.18 if self.speaking else 0.0))

        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Soft concentric aura.
        for index in range(7, 0, -1):
            ring = radius * (1.35 + index * 0.075)
            alpha = int((8 + energy * 28) * (1.0 - index / 8.0))
            p.setPen(QPen(qcol(primary, alpha), 1.4))
            p.drawEllipse(QRectF(cx - ring, cy - ring, ring * 2, ring * 2))

        # Three rotating orbital arcs give the face a sense of depth.
        for index, (scale, length, width) in enumerate(((1.36, 92, 2.0), (1.52, 58, 1.2), (1.68, 36, 1.0))):
            ring = radius * scale
            angle = math.degrees(self._avatar_phase * (1.0 - index * 0.18) + index * 2.1)
            p.setPen(QPen(qcol(primary if index == 0 else secondary, 150 if active else 80), width))
            rect = QRectF(cx - ring, cy - ring, ring * 2, ring * 2)
            p.drawArc(rect, int(angle * 16), int(length * 16))
            p.drawArc(rect, int((angle + 180) * 16), int(length * 8))

        # A narrow scanning beam sweeps around the head while speaking.
        scan_ring = radius * (1.76 + energy * 0.10)
        p.setPen(QPen(qcol(C.GREEN if active else C.PRI_DIM, 170 if active else 70), 2.0))
        scan = math.degrees(self._avatar_phase * 1.6)
        p.drawArc(QRectF(cx - scan_ring, cy - scan_ring, scan_ring * 2, scan_ring * 2),
                  int(scan * 16), 22 * 16)

        # Cinematic telemetry ring: sparse ticks, labels and a live audio readout.
        telemetry_ring = radius * 1.92
        p.setPen(QPen(qcol(C.PRI, 105 if active else 58), 1.0))
        for degree in range(0, 360, 15):
            angle = math.radians(degree) + self._avatar_phase * 0.12
            inner = telemetry_ring - (10 if degree % 45 == 0 else 5)
            p.drawLine(
                QPointF(cx + math.cos(angle) * inner, cy + math.sin(angle) * inner),
                QPointF(cx + math.cos(angle) * telemetry_ring, cy + math.sin(angle) * telemetry_ring),
            )
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_MED, 170), 1))
        p.drawText(QRectF(cx - telemetry_ring, cy - telemetry_ring - 20, 150, 16),
                   Qt.AlignmentFlag.AlignLeft, "NEURAL CORE  //  ONLINE")
        p.drawText(QRectF(cx + telemetry_ring - 150, cy - telemetry_ring - 20, 150, 16),
                   Qt.AlignmentFlag.AlignRight, f"AUDIO LINK  {int(energy * 100):02d}%")
        p.setPen(QPen(qcol(C.ACC if self.speaking else C.GREEN, 185), 1))
        p.drawText(QRectF(cx - telemetry_ring, cy + telemetry_ring + 7, 150, 16),
                   Qt.AlignmentFlag.AlignLeft, "BIOMETRIC  STABLE")
        p.setPen(QPen(qcol(C.PRI_DIM, 150), 1))
        p.drawText(QRectF(cx + telemetry_ring - 150, cy + telemetry_ring + 7, 150, 16),
                   Qt.AlignmentFlag.AlignRight, "VISUAL MATRIX  3D")

        # Small motes drift outward from the orbital field.
        p.setPen(Qt.PenStyle.NoPen)
        for angle, distance, life, _speed in self._avatar_particles:
            px = cx + math.cos(angle) * distance
            py = cy + math.sin(angle) * distance
            p.setBrush(qcol(C.ACC if self.speaking else C.PRI, int(210 * min(1.0, life))))
            p.drawEllipse(QPointF(px, py), 2.0 + life * 1.5, 2.0 + life * 1.5)
        p.restore()
        return

        # grid dots
        p.setPen(QPen(qcol(C.PRI_GHO), 1))
        for x in range(0, W, 48):
            for y in range(0, H, 48):
                p.drawPoint(x, y)

        r_face = fw * 0.31

        # halo glow
        for i in range(10):
            r   = r_face * (1.8 - i * 0.08)
            frc = 1.0 - i / 10
            a   = max(0, min(255, int(self._halo * 0.085 * frc)))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # pulse rings
        for pr in self._pulses:
            a   = max(0, int(230 * (1.0 - pr / (fw * 0.74))))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # spinning arc rings
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(
            [(0.48, 3, 115, 78), (0.40, 2, 78, 55), (0.32, 1, 56, 40)]
        ):
            ring_r = fw * r_frac
            base   = self._rings[idx]
            a_val  = max(0, min(255, int(self._halo * (1.0 - idx * 0.18))))
            col    = qcol(C.MUTED_C if self.muted else C.PRI, a_val)
            p.setPen(QPen(col, w_r)); p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect  = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        # scanners
        sr = fw * 0.50
        sa = min(255, int(self._halo * 1.5))
        ex = 75 if self.speaking else 44
        p.setPen(QPen(qcol(C.MUTED_C if self.muted else C.PRI, sa), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        srect = QRectF(cx - sr, cy - sr, sr * 2, sr * 2)
        p.drawArc(srect, int(self._scan * 16), int(ex * 16))
        p.setPen(QPen(qcol(C.ACC, sa // 2), 1.5))
        p.drawArc(srect, int(self._scan2 * 16), int(ex * 16))

        # tick marks
        t_out, t_in = fw * 0.497, fw * 0.474
        p.setPen(QPen(qcol(C.PRI, 140), 1))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 6
            p.drawLine(
                QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                QPointF(cx + inn  * math.cos(rad), cy - inn  * math.sin(rad)),
            )

        # crosshair
        ch_r, gap_h = fw * 0.51, fw * 0.16
        p.setPen(QPen(qcol(C.PRI, int(self._halo * 0.5)), 1))
        p.drawLine(QPointF(cx - ch_r, cy), QPointF(cx - gap_h, cy))
        p.drawLine(QPointF(cx + gap_h, cy), QPointF(cx + ch_r, cy))
        p.drawLine(QPointF(cx, cy - ch_r), QPointF(cx, cy - gap_h))
        p.drawLine(QPointF(cx, cy + gap_h), QPointF(cx, cy + ch_r))

        # corner brackets
        bl = 24
        bc = qcol(C.PRI, 210)
        hl, hr = cx - fw // 2, cx + fw // 2
        ht, hb = cy - fw // 2, cy + fw // 2
        p.setPen(QPen(bc, 2))
        for bx, by, dx, dy in [(hl,ht,1,1),(hr,ht,-1,1),(hl,hb,1,-1),(hr,hb,-1,-1)]:
            p.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))

        # face
        if self._face_px:
            fsz    = int(fw * 0.62 * self._scale)
            scaled = self._face_px.scaled(
                fsz, fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
        else:
            orb_r = int(fw * 0.27 * self._scale)
            oc    = (200, 0, 50) if self.muted else (0, 60, 110)
            for i in range(8, 0, -1):
                r2  = int(orb_r * i / 8)
                frc = i / 8
                a   = max(0, min(255, int(self._halo * 1.1 * frc)))
                p.setBrush(QBrush(QColor(int(oc[0]*frc), int(oc[1]*frc), int(oc[2]*frc), a)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2))
            p.setPen(QPen(qcol(C.PRI, min(255, int(self._halo * 2))), 1))
            p.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
            p.drawText(QRectF(cx - 80, cy - 14, 160, 28),
                       Qt.AlignmentFlag.AlignCenter, self._assistant_name)

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PRI, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.5, 2.5)

        # status text
        sy = cy + fw * 0.40
        if self.muted:
            txt, col = "⊘  MUTED",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING",  qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING",   qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING",  qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            elif self.speaking:
                hgt = random.randint(3, 20)
                cl  = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
            else:
                hgt = int(3 + 2 * math.sin(self._tick * 0.09 + i * 0.6))
                cl  = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)


class Hologram3DWidget(QWidget):
    """Textured 3D model viewer with software rendering."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._vertices = []
        self._edges = []
        self._faces = []
        self._model_error = ""
        self._label = "HOLOGRAM"
        self._yaw = -0.35
        self._pitch = 0.25
        self._zoom = 1.0
        self._drag_start = None
        self._rotation_start = (0.0, 0.0)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(50)
        self.hide()

    def show_model(self, description: str, model_path: str = ""):
        text = (description or "object").lower()
        self._model_error = ""

        requested_asset = Path(model_path).expanduser() if model_path else self._find_asset(text)
        if requested_asset and requested_asset.is_file():
            if self._load_asset(requested_asset):
                self._label = requested_asset.stem.upper()[:24]
                self._yaw = -0.35
                self._pitch = 0.25
                self._zoom = 1.0
                self.show()
                self.raise_()
                self.setFocus()
                self.update()
                return
        if model_path:
            self._model_error = "REAL 3D ASSET NOT FOUND OR INVALID"
            self._vertices, self._edges, self._faces = [], [], []
            self._label = Path(model_path).stem.upper()[:24]
            self.show()
            self.raise_()
            self.setFocus()
            self.update()
            return
        models = []
        if not models:
            self._vertices, self._edges, self._faces = [], [], []
            self._label = (description or "OBJECT").upper()[:18]
            asset_dir = Path(__file__).resolve().parent / "assets" / "3d"
            self._model_error = (
                "REAL 3D ASSET NOT FOUND\n"
                f"Put a matching .glb, .gltf or .obj file in:\n{asset_dir}"
            )
            self.show()
            self.raise_()
            self.setFocus()
            self.update()
            return
        self._vertices, self._edges = self._combine_models(models)
        self._faces = []
        self._label = " + ".join(label for label, _ in models)
        self._yaw = -0.35
        self._pitch = 0.25
        self._zoom = 1.0
        self._phase = 0.0
        self.show()
        self.raise_()
        self.setFocus()
        self.update()

    @staticmethod
    def _find_asset(description: str):
        asset_dir = Path(__file__).resolve().parent / "assets" / "3d"
        if not asset_dir.is_dir():
            return None
        words = [word for word in re.findall(r"[a-z0-9]+", description) if len(word) > 2]
        for asset in asset_dir.iterdir():
            if asset.suffix.lower() not in {".glb", ".gltf", ".obj"}:
                continue
            stem = asset.stem.lower()
            if words and any(word in stem for word in words):
                return asset
        return None

    def _load_asset(self, path: Path):
        try:
            import trimesh
            loaded = trimesh.load(str(path), force="scene")
            scene = loaded if isinstance(loaded, trimesh.Scene) else trimesh.Scene(loaded)
            vertices, edges, faces = [], [], []
            edge_set = set()
            max_faces_per_mesh = 700
            # Apply node transforms from GLB scenes before extracting geometry.
            meshes = scene.dump(concatenate=False) if isinstance(loaded, trimesh.Scene) else [loaded]
            for mesh in meshes:
                if not hasattr(mesh, "vertices") or not hasattr(mesh, "faces"):
                    continue
                start = len(vertices)
                vertices.extend(tuple(float(value) for value in vertex) for vertex in mesh.vertices)
                mesh_faces = mesh.faces
                if len(mesh_faces) > max_faces_per_mesh:
                    # Keep the real mesh, but cap wireframe density so a dense
                    # GLB cannot freeze the Qt event thread while opening.
                    import numpy as np
                    sample = np.linspace(
                        0, len(mesh_faces) - 1, max_faces_per_mesh, dtype=int
                    )
                    mesh_faces = mesh_faces[sample]
                for face in mesh_faces:
                    faces.append(tuple(start + int(index) for index in face))
                    for first, second in zip(face, list(face[1:]) + [face[0]]):
                        edge = (start + int(first), start + int(second))
                        canonical = tuple(sorted(edge))
                        if canonical not in edge_set:
                            edge_set.add(canonical)
                            edges.append(edge)
            if not vertices or not edges:
                return False

            # Keep the real silhouette while limiting per-frame projection work.
            if len(edges) > 4000:
                import numpy as np
                selected = np.linspace(0, len(edges) - 1, 4000, dtype=int)
                edges = [edges[index] for index in selected]
            referenced = sorted({index for edge in edges for index in edge})
            remap = {old: new for new, old in enumerate(referenced)}
            vertices = [vertices[index] for index in referenced]
            edges = [(remap[first], remap[second]) for first, second in edges]
            remapped_faces = []
            for face in faces:
                if all(index in remap for index in face):
                    remapped_faces.append(tuple(remap[index] for index in face))
            faces = remapped_faces[:5000]
            min_point = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
            max_point = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
            center = [(low + high) / 2 for low, high in zip(min_point, max_point)]
            extent = max(max_point[axis] - min_point[axis] for axis in range(3)) or 1.0
            vertices = [tuple((value - center[axis]) * 3.0 / extent for axis, value in enumerate(vertex))
                        for vertex in vertices]
            self._vertices, self._edges, self._faces = vertices, edges, faces
            return True
        except Exception as exc:
            self._model_error = f"MODEL LOAD FAILED: {exc}"
            return False

    @staticmethod
    def _cylinder_mesh(radius, height, segments):
        vertices = []
        for z in (-height / 2, height / 2):
            vertices.extend((radius * math.cos(i * 2 * math.pi / segments),
                             radius * math.sin(i * 2 * math.pi / segments), z)
                            for i in range(segments))
        edges = []
        for i in range(segments):
            n = (i + 1) % segments
            edges += [(i, n), (segments + i, segments + n), (i, segments + i)]
        return vertices, edges

    @classmethod
    def _coin_mesh(cls):
        vertices, edges = cls._cylinder_mesh(1.35, 0.22, 32)
        for radius, z in ((0.98, -0.125), (0.98, 0.125), (0.62, -0.132), (0.62, 0.132)):
            start = len(vertices)
            vertices.extend((radius * math.cos(i * 2 * math.pi / 32),
                             radius * math.sin(i * 2 * math.pi / 32), z) for i in range(32))
            edges.extend((start + i, start + (i + 1) % 32) for i in range(32))
        return vertices, edges

    @staticmethod
    def _pen_mesh():
        body, edges = Hologram3DWidget._cylinder_mesh(0.16, 2.7, 16)
        tip_start = len(body)
        body.extend([(0.0, 0.0, -1.75)])
        for i in range(16):
            edges.append((tip_start, i))
        clip_start = len(body)
        body.extend([(-0.22, 0.0, 0.7), (0.22, 0.0, 0.7), (-0.22, 0.0, 1.4), (0.22, 0.0, 1.4)])
        edges.extend([(clip_start, clip_start + 1), (clip_start, clip_start + 2),
                      (clip_start + 1, clip_start + 3), (clip_start + 2, clip_start + 3)])
        return body, edges

    @staticmethod
    def _helmet_mesh():
        vertices, edges = [], []
        segments = 28

        # Upper shell: a tall, angular crown with visible front projection.
        shell_rings = [
            (-0.50, 0.95),
            (-0.20, 1.10),
            (0.12, 1.20),
            (0.42, 1.12),
            (0.70, 0.94),
            (0.90, 0.62),
            (1.02, 0.18),
        ]
        for y, radius in shell_rings:
            start = len(vertices)
            vertices.extend(
                (
                    radius * math.cos(i * 2 * math.pi / segments),
                    y,
                    radius * math.sin(i * 2 * math.pi / segments),
                )
                for i in range(segments)
            )
            if start:
                prev_start = start - segments
                edges.extend((prev_start + i, start + i) for i in range(segments))
            edges.extend((start + i, start + ((i + 1) % segments)) for i in range(segments))

        # Faceplate and jaw create the recognisable helmet front.
        face_start = len(vertices)
        face_points = [
            (-0.88, -0.18, 0.86), (0.88, -0.18, 0.86),
            (-0.98, -0.35, 0.72), (0.98, -0.35, 0.72),
            (-0.76, -0.72, 0.72), (0.76, -0.72, 0.72),
            (-0.62, -0.98, 0.48), (0.62, -0.98, 0.48),
            (-0.44, -1.25, 0.18), (0.44, -1.25, 0.18),
            (-0.56, -1.52, -0.12), (0.56, -1.52, -0.12),
            (-0.34, -1.70, -0.38), (0.34, -1.70, -0.38),
            (-0.20, -1.82, -0.52), (0.20, -1.82, -0.52),
        ]
        vertices.extend(face_points)
        face_edges = [
            (face_start, face_start + 1),
            (face_start, face_start + 2), (face_start + 1, face_start + 3),
            (face_start + 2, face_start + 4), (face_start + 3, face_start + 5),
            (face_start + 4, face_start + 6), (face_start + 5, face_start + 7),
            (face_start + 6, face_start + 8), (face_start + 7, face_start + 9),
            (face_start + 8, face_start + 10), (face_start + 9, face_start + 11),
            (face_start + 10, face_start + 12), (face_start + 11, face_start + 13),
            (face_start + 12, face_start + 14), (face_start + 13, face_start + 15),
            (face_start + 2, face_start + 3),
            (face_start + 6, face_start + 7),
            (face_start + 10, face_start + 11),
            (face_start + 12, face_start + 14), (face_start + 13, face_start + 15),
        ]
        edges.extend(face_edges)

        # Side ear/cheek supports to create a real helmet silhouette.
        for side in (-1.0, 1.0):
            ear = len(vertices)
            vertices.extend([
                (side * 0.92, 0.18, -0.18),
                (side * 1.06, -0.22, -0.22),
                (side * 1.00, -0.82, -0.28),
                (side * 0.68, -1.20, -0.16),
            ])
            edges.extend([
                (ear, ear + 1), (ear + 1, ear + 2), (ear + 2, ear + 3),
                (ear, ear + 2), (ear + 1, ear + 3),
            ])

        # Connect the shell to the faceplate for a continuous outline.
        shell_link = len(vertices)
        vertices.extend([
            (-0.70, -0.18, 0.62), (0.70, -0.18, 0.62),
            (-0.80, -0.60, 0.46), (0.80, -0.60, 0.46),
        ])
        edges.extend([
            (shell_link, face_start), (shell_link + 1, face_start + 1),
            (shell_link + 2, face_start + 2), (shell_link + 3, face_start + 3),
            (shell_link, shell_link + 2), (shell_link + 1, shell_link + 3),
        ])

        return vertices, edges

    @staticmethod
    def _pizza_mesh():
        vertices, edges = Hologram3DWidget._cylinder_mesh(1.35, 0.16, 28)
        # Crust ring and radial slice seams make the flat object readable in wireframe.
        for radius, z in ((1.16, 0.1), (0.92, 0.1)):
            start = len(vertices)
            vertices.extend((radius * math.cos(i * 2 * math.pi / 28),
                             radius * math.sin(i * 2 * math.pi / 28), z)
                            for i in range(28))
            edges.extend((start + i, start + (i + 1) % 28) for i in range(28))
        for i in range(0, 28, 2):
            edges.append((i, i + 28))
        for x, y in ((-0.45, 0.35), (0.3, 0.46), (0.55, -0.25), (-0.25, -0.42), (0.0, 0.05)):
            start = len(vertices)
            vertices.extend((x + 0.13 * math.cos(i * 2 * math.pi / 8),
                             y + 0.13 * math.sin(i * 2 * math.pi / 8), 0.14) for i in range(8))
            edges.extend((start + i, start + (i + 1) % 8) for i in range(8))
        return vertices, edges

    @staticmethod
    def _computer_mesh():
        vertices, edges = [], []

        def box(cx, cy, cz, sx, sy, sz):
            start = len(vertices)
            vertices.extend((cx + x * sx, cy + y * sy, cz + z * sz)
                            for z in (-1, 1) for y in (-1, 1) for x in (-1, 1))
            edges.extend((start + a, start + b) for a, b in (
                (0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4),
                (0, 4), (1, 5), (2, 6), (3, 7)))

        box(0, 0, 0, 1.45, 0.9, 0.42)
        box(-0.45, 0.0, 0.48, 0.52, 0.34, 0.08)  # motherboard
        box(0.55, 0.12, 0.5, 0.25, 0.24, 0.1)    # GPU
        box(-0.3, -0.42, 0.5, 0.18, 0.12, 0.1)   # CPU
        for x in (-0.95, 0.95):
            for y in (-0.52, 0.52):
                box(x, y, 0.08, 0.12, 0.06, 0.32)
        return vertices, edges

    @staticmethod
    def _spider_mask_mesh():
        base, edges = Hologram3DWidget._sphere_mesh()
        vertices = [(x * 0.88, y * 1.18, z * 0.72) for x, y, z in base]
        for side in (-1, 1):
            start = len(vertices)
            vertices.extend([(side * 0.27, 0.28, 0.69), (side * 0.58, 0.48, 0.57),
                             (side * 0.64, 0.18, 0.58), (side * 0.28, 0.02, 0.69)])
            edges.extend([(start, start + 1), (start + 1, start + 2),
                          (start + 2, start + 3), (start + 3, start)])
        return vertices, edges

    @staticmethod
    def _spider_symbol_mesh():
        vertices = [(0, 0.35, 0), (0, -0.35, 0)]
        edges = [(0, 1)]
        # Eight angular legs, each with a joint, form a recognizable stylized spider.
        for side in (-1, 1):
            for y, reach in ((0.24, 0.62), (0.0, 0.78), (-0.24, 0.62)):
                start = len(vertices)
                vertices.extend([(side * 0.08, y, 0), (side * reach * 0.62, y + side * 0.12, 0),
                                 (side * reach, y + side * 0.34, 0)])
                edges.extend([(start, start + 1), (start + 1, start + 2)])
        return vertices, edges

    @staticmethod
    def _combine_models(models):
        vertices, edges = [], []
        spacing = (len(models) - 1) * 1.8
        for index, (_label, (model_vertices, model_edges)) in enumerate(models):
            offset_x = index * 3.6 - spacing
            start = len(vertices)
            scale = 0.82 if len(models) > 1 else 1.0
            vertices.extend((x * scale + offset_x, y * scale, z * scale)
                            for x, y, z in model_vertices)
            edges.extend((start + first, start + second) for first, second in model_edges)
        return vertices, edges

    @staticmethod
    def _cube_mesh():
        vertices = [(x, y, z) for z in (-1, 1) for y in (-1, 1) for x in (-1, 1)]
        edges = [(0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)]
        return vertices, edges

    @staticmethod
    def _sphere_mesh():
        vertices, edges, rings, segments = [], [], 8, 24
        for ring in range(1, rings):
            phi = math.pi * ring / rings
            vertices.extend((math.sin(phi) * math.cos(i * 2 * math.pi / segments),
                             math.sin(phi) * math.sin(i * 2 * math.pi / segments),
                             math.cos(phi)) for i in range(segments))
        for ring in range(rings - 2):
            for i in range(segments):
                n = (i + 1) % segments
                edges += [(ring * segments + i, ring * segments + n),
                          (ring * segments + i, (ring + 1) * segments + i)]
        return vertices, edges

    def _animate(self):
        if self.isVisible():
            self._phase += 0.055
            self._yaw += 0.008
            self.update()

    def _project(self, vertex):
        x, y, z = self._transform(vertex)
        depth = max(0.2, z + 4.0)
        scale = min(self.width(), self.height()) * 0.31 * self._zoom / depth
        return QPointF(self.width() / 2 + x * scale, self.height() / 2 - y * scale)

    def _transform(self, vertex):
        x, y, z = vertex
        cy, sy = math.cos(self._yaw), math.sin(self._yaw)
        x, z = x * cy - z * sy, x * sy + z * cy
        cp, sp = math.cos(self._pitch), math.sin(self._pitch)
        y, z = y * cp - z * sp, y * sp + z * cp
        return x, y, z

    def _connected_surface_loops(self):
        if not self._vertices or not self._edges:
            return []

        adjacency = {i: [] for i in range(len(self._vertices))}
        for first, second in self._edges:
            if 0 <= first < len(self._vertices) and 0 <= second < len(self._vertices):
                adjacency[first].append(second)
                adjacency[second].append(first)

        used_edges = set()
        loops = []
        for start in range(len(self._vertices)):
            if not adjacency[start]:
                continue
            for nxt in adjacency[start]:
                edge_key = tuple(sorted((start, nxt)))
                if edge_key in used_edges:
                    continue
                path = [start]
                current = start
                prev = None
                used_edges.add(edge_key)
                while True:
                    choices = [n for n in adjacency[current] if tuple(sorted((current, n))) not in used_edges]
                    if not choices:
                        break
                    next_vertex = choices[0]
                    if prev is not None and next_vertex == prev and len(choices) > 1:
                        next_vertex = choices[1]
                    edge_key = tuple(sorted((current, next_vertex)))
                    used_edges.add(edge_key)
                    prev, current = current, next_vertex
                    path.append(current)
                    if current == start:
                        break
                    if len(path) > 80:
                        break
                if len(path) >= 3:
                    loops.append(path)
        return loops

    def paintEvent(self, _event):
        if not self._vertices:
            painter = QPainter(self)
            painter.setPen(QPen(QColor(135, 248, 255, 210), 1))
            painter.drawText(QRectF(20, self.height() / 2 - 30, self.width() - 40, 60),
                             Qt.AlignmentFlag.AlignCenter, self._model_error)
            painter.end()
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scan = (math.sin(self._phase) + 1) / 2

        if self._faces:
            projected_faces = []
            for face in self._faces:
                transformed = [self._transform(self._vertices[index]) for index in face]
                depth = sum(vertex[2] for vertex in transformed) / len(transformed)
                projected_faces.append((depth, face))

            for depth, face in sorted(projected_faces):
                alpha = max(32, min(140, int(58 + depth * 12)))
                polygon = QPolygonF([self._project(self._vertices[index]) for index in face])
                painter.setBrush(QColor(12, 160, 205, alpha))
                painter.setPen(QPen(QColor(0, 82, 112, 220), 1.8))
                painter.drawPolygon(polygon)

        outer = QColor(0, 20, 30, 220)
        inner = QColor(135, 248, 255, 245)
        painter.setPen(QPen(outer, 3.2))

        if self._faces:
            for face in self._faces:
                poly = QPolygonF([self._project(self._vertices[index]) for index in face])
                painter.drawPolyline(poly)
        else:
            loops = self._connected_surface_loops()
            for loop in loops:
                poly = QPolygonF([self._project(self._vertices[index]) for index in loop])
                if len(poly) >= 3:
                    painter.setPen(QPen(outer, 3.2))
                    painter.drawPolyline(poly)
                    painter.setPen(QPen(inner, 1.5))
                    painter.drawPolyline(poly)

        painter.setPen(QPen(inner, 1.5))
        for first, second in self._edges:
            painter.drawLine(self._project(self._vertices[first]), self._project(self._vertices[second]))

        painter.setPen(QPen(QColor(135, 248, 255, 220), 1))
        painter.drawText(18, 24, f"◈  {self._label}  //  3D HOLOGRAM")
        painter.setPen(QPen(QColor(0, 212, 255, 90), 1))
        y = int(40 + scan * max(1, self.height() - 70))
        painter.drawLine(18, y, self.width() - 18, y)
        close_rect = QRectF(self.width() - 42, 8, 24, 24)
        painter.setPen(QPen(QColor(135, 248, 255, 210), 1.2))
        painter.drawRoundedRect(close_rect, 4, 4)
        painter.drawLine(
            QPointF(close_rect.left() + 7, close_rect.top() + 7),
            QPointF(close_rect.right() - 7, close_rect.bottom() - 7),
        )
        painter.drawLine(
            QPointF(close_rect.right() - 7, close_rect.top() + 7),
            QPointF(close_rect.left() + 7, close_rect.bottom() - 7),
        )
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().x() >= self.width() - 42 and event.position().y() <= 36:
                self.hide()
                event.accept()
                return
            self._drag_start = event.position().toPoint()
            self._rotation_start = (self._yaw, self._pitch)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            delta = event.position().toPoint() - self._drag_start
            self._yaw = self._rotation_start[0] + delta.x() * 0.012
            self._pitch = max(-1.35, min(1.35, self._rotation_start[1] + delta.y() * 0.012))
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        self.unsetCursor()
        event.accept()

    def wheelEvent(self, event):
        self._zoom = max(0.55, min(1.8, self._zoom + event.angleDelta().y() / 2400))
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)


class BootOverlay(QWidget):
    """Short startup sequence that establishes the HUD before the workspace appears."""

    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self._progress = 0.0
        self._mode = "boot"
        self._closing = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {C.BG};")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def start(self):
        self._mode = "boot"
        self._closing = False
        self._progress = 0.0
        self._phase = 0.0
        self.show()
        self.raise_()
        self._timer.start(33)

    def start_shutdown(self):
        self._mode = "shutdown"
        self._closing = True
        self._progress = 1.0
        self._phase = 0.0
        self.show()
        self.raise_()
        self._timer.start(33)

    def start_restart(self):
        self._mode = "restart"
        self._closing = True
        self._progress = 1.0
        self._phase = 0.0
        self.show()
        self.raise_()
        self._timer.start(33)

    def finish(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._phase += 0.08
        if self._closing:
            self._progress = max(0.0, self._progress - 0.022)
        else:
            self._progress = min(1.0, self._progress + 0.018)
        if (not self._closing and self._progress >= 1.0) or (self._closing and self._progress <= 0.0):
            self.finish()
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), QColor(C.BG))
        cx, cy = W / 2, H / 2 - 32
        radius = min(W, H) * 0.18

        glow = QRadialGradient(cx, cy, radius * 2.8)
        if self._mode == "shutdown":
            core_color = QColor(255, 51, 85)
        elif self._mode == "restart":
            core_color = QColor(255, 157, 46)
        else:
            core_color = QColor(0, 212, 255)
        glow.setColorAt(0.0, QColor(core_color.red(), core_color.green(), core_color.blue(), 72))
        glow.setColorAt(0.45, QColor(0, 90, 140, 28))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QRectF(cx - radius * 2.8, cy - radius * 2.8, radius * 5.6, radius * 5.6))

        for index in range(3):
            ring = radius * (1.0 + index * 0.28)
            angle = self._phase * (1.0 - index * 0.15) + index * 2.0
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(core_color.red(), core_color.green(), core_color.blue(), 190 - index * 38), 2 if index == 0 else 1))
            rect = QRectF(cx - ring, cy - ring, ring * 2, ring * 2)
            p.drawArc(rect, int(math.degrees(angle) * 16), int((100 - index * 20) * 16))
            p.drawArc(rect, int(math.degrees(angle + math.pi) * 16), int((48 - index * 8) * 16))

        p.setPen(QPen(QColor(210, 248, 255), 1))
        p.setFont(QFont("Courier New", 22, QFont.Weight.Bold))
        p.drawText(QRectF(0, cy + radius * 1.65, W, 34), Qt.AlignmentFlag.AlignCenter, "J.A.R.V.I.S")
        p.setPen(QPen(QColor(255, 110, 130) if self._closing else QColor(0, 160, 190), 1))
        p.setFont(QFont("Courier New", 8))
        subtitle = (
            "SYSTEM POWERING DOWN" if self._mode == "shutdown"
            else "SYSTEM RESTARTING" if self._mode == "restart"
            else "NEURAL INTERFACE INITIALISING"
        )
        p.drawText(QRectF(0, cy + radius * 2.1, W, 22), Qt.AlignmentFlag.AlignCenter, subtitle)

        bar_w, bar_h = min(360, W * 0.42), 5
        bx, by = (W - bar_w) / 2, cy + radius * 2.75
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(4, 30, 42))
        p.drawRoundedRect(QRectF(bx, by, bar_w, bar_h), 2, 2)
        p.setBrush(core_color)
        p.drawRoundedRect(QRectF(bx, by, bar_w * self._progress, bar_h), 2, 2)
        p.setPen(QPen(QColor(70, 150, 170), 1))
        p.setFont(QFont("Courier New", 7))
        p.drawText(QRectF(0, by + 16, W, 18), Qt.AlignmentFlag.AlignCenter,
                   f"{('SHUTDOWN' if self._mode == 'shutdown' else 'RESTART' if self._mode == 'restart' else 'BOOT')} SEQUENCE  {int(self._progress * 100):02d}%")


class _FloatingPanel(QFrame):
    """A lightweight in-window dock that can be repositioned in edit mode."""

    position_changed = pyqtSignal()

    def __init__(self, title: str, parent=None, width=240, height=150):
        super().__init__(parent)
        self.setObjectName("FloatingPanel")
        self.setMinimumSize(width, height)
        self.resize(width, height)
        self.setStyleSheet(f"""
            QFrame#FloatingPanel {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(8, 24, 34, 246), stop:0.48 rgba(3, 14, 22, 242),
                    stop:1 rgba(1, 8, 14, 248));
                border: 1px solid {C.BORDER_B};
                border-radius: 10px;
            }}
            QLabel#FloatingTitle {{
                color: {C.PRI}; background: transparent;
                font: 700 8pt 'Courier New';
                letter-spacing: 2px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 180, 230, 92))
        self.setGraphicsEffect(shadow)
        self._drag_enabled = True
        self._drag_offset = None
        self._panel_phase = random.random() * math.pi * 2
        self._panel_timer = QTimer(self)
        self._panel_timer.timeout.connect(self._animate_panel)
        self._panel_timer.start(80)
        self._body = QWidget(self)
        self._body.setStyleSheet("background: transparent; border: none;")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(7)
        head = QHBoxLayout(); head.setContentsMargins(0, 0, 0, 0)
        marker = QLabel("▸", self)
        marker.setStyleSheet(f"color: {C.ACC}; background: transparent; font: 700 10pt 'Courier New';")
        head.addWidget(marker)
        label = QLabel(title, self); label.setObjectName("FloatingTitle")
        label.setCursor(Qt.CursorShape.OpenHandCursor)
        label.installEventFilter(self)
        head.addWidget(label); head.addStretch()
        root.addLayout(head)
        rule = QFrame(self)
        rule.setFixedHeight(2)
        rule.setStyleSheet(f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {C.PRI}, stop:0.45 {C.ACC}, stop:1 transparent); border: none;")
        root.addWidget(rule)
        root.addWidget(self._body, stretch=1)

    def _animate_panel(self):
        self._panel_phase = (self._panel_phase + 0.045) % (math.pi * 2)
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        pulse = 0.5 + 0.5 * math.sin(self._panel_phase)
        # Cinematic HUD corner marks and a restrained animated scan highlight.
        painter.setPen(QPen(QColor(0, 212, 255, 80 + int(pulse * 45)), 1.2))
        corner = 13
        for x, y, dx, dy in ((2, 2, 1, 1), (W - 2, 2, -1, 1),
                             (2, H - 2, 1, -1), (W - 2, H - 2, -1, -1)):
            painter.drawLine(QPointF(x, y), QPointF(x + dx * corner, y))
            painter.drawLine(QPointF(x, y), QPointF(x, y + dy * corner))
        scan_x = 18 + ((W - 36) * ((math.sin(self._panel_phase * 0.35) + 1) * 0.5))
        painter.setPen(QPen(QColor(0, 212, 255, 24), 1))
        painter.drawLine(QPointF(scan_x, 2), QPointF(scan_x, H - 2))
        painter.end()

    def enable_editing(self, enabled: bool):
        self.setStyleSheet(self.styleSheet().replace(
            f"border: 1px solid {C.BORDER_B};",
            f"border: 1px solid {C.PRI if enabled else C.BORDER_B};"
        ))

    def _set_active_state(self, active: bool):
        self.setWindowOpacity(1.0 if active else 0.72)

    def _apply_stack_offset(self, index: int = 0):
        if index <= 0:
            return
        self.move(self.x() + index * 10, self.y() + index * 12)

    def eventFilter(self, watched, event):
        if watched is not self and event.type() in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        }:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = self.mapFromGlobal(event.globalPosition().toPoint())
                watched.setCursor(Qt.CursorShape.ClosedHandCursor)
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                parent = self.parentWidget()
                if parent is not None:
                    new_pos = parent.mapFromGlobal(event.globalPosition().toPoint()) - self._drag_offset
                    self.move(new_pos)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
                watched.setCursor(Qt.CursorShape.OpenHandCursor)
                self.position_changed.emit()
                return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if self._drag_enabled and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_enabled and self._drag_offset is not None:
            self.move(self.pos() + event.position().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        if self._drag_enabled:
            self.position_changed.emit()
        super().mouseReleaseEvent(event)


class _InternalLogPanel(_FloatingPanel):
    def __init__(self, log: QWidget, parent=None):
        super().__init__("ACTIVITY LOG", parent, 360, 250)
        self.setMinimumSize(300, 190)
        self.setMaximumSize(720, 620)
        self._log = log
        self._log.setParent(self._body)
        self._log.setMinimumSize(0, 0)
        self._log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(log)
        self._collapsed = False

        self._min_btn = QPushButton("—", self)
        self._min_btn.setFixedSize(22, 20)
        self._min_btn.setStyleSheet(
            f"QPushButton {{ color: {C.TEXT_MED}; background: transparent; border: none; }}"
            f"QPushButton:hover {{ color: {C.PRI}; }}"
        )
        self._min_btn.clicked.connect(self.toggle_collapsed)
        self.layout().itemAt(0).layout().addWidget(self._min_btn)

        self._resize_grip = QSizeGrip(self)
        self._resize_grip.setToolTip("Resize activity log")
        self._resize_grip.resize(16, 16)
        self._resize_grip.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_grip.move(self.width() - 17, self.height() - 17)
        if hasattr(self, "_drag_enabled") and self._drag_enabled:
            self.position_changed.emit()

    def toggle_collapsed(self):
        self._collapsed = not self._collapsed
        self._body.setVisible(not self._collapsed)
        self.setMinimumHeight(42 if self._collapsed else 190)
        self.resize(self.width(), 42 if self._collapsed else max(250, self.height()))
        self._min_btn.setText("□" if self._collapsed else "—")


class MusicWidget(_FloatingPanel):
    """Compact media control surface for the active system player."""

    def __init__(self, parent=None):
        super().__init__("NOW PLAYING", parent, 340, 176)
        self._title = "No track selected"
        self._artist = "Media player ready"
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)

        top = QHBoxLayout(); top.setSpacing(8)
        self._cover = QLabel("♪")
        self._cover.setFixedSize(96, 96)
        self._cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover.setStyleSheet(f"""
            QLabel {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 {C.PRI_GHO}, stop:1 #06141e); color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 8px;
                font: 46px 'Segoe UI Symbol'; }}
        """)
        top.addWidget(self._cover)

        info = QVBoxLayout(); info.setSpacing(3)
        self._title_label = QLabel(self._title)
        self._title_label.setStyleSheet(f"color: {C.WHITE}; background: transparent; font: 700 12px 'Courier New';")
        self._title_label.setWordWrap(True)
        self._artist_label = QLabel(self._artist)
        self._artist_label.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; font: 9px 'Courier New';")
        self._artist_label.setWordWrap(True)
        info.addWidget(self._title_label)
        info.addWidget(self._artist_label)
        info.addStretch()
        top.addLayout(info, stretch=1)
        body.addLayout(top)

        controls = QHBoxLayout(); controls.setSpacing(4)
        for icon, tip, callback in (
            ("⏮", "Previous track", lambda: self._media_key("prevtrack")),
            ("▶", "Play / pause", lambda: self._media_key("playpause")),
            ("⏭", "Next track", lambda: self._media_key("nexttrack")),
            ("−", "Volume down", lambda: self._media_key("volumedown")),
            ("+", "Volume up", lambda: self._media_key("volumeup")),
        ):
            button = QPushButton(icon)
            button.setFixedSize(43, 29)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(f"""
                QPushButton {{ color: {C.TEXT}; background: rgba(4, 24, 35, 220);
                    border: 1px solid {C.BORDER_B}; border-radius: 6px; font-size: 15px; }}
                QPushButton:hover {{ color: {C.WHITE}; background: {C.PRI_GHO}; border-color: {C.PRI}; }}
                QPushButton:pressed {{ background: {C.ACC}; color: #001018; }}
            """)
            button.clicked.connect(callback)
            controls.addWidget(button)
        body.addLayout(controls)

    @staticmethod
    def _media_key(key: str):
        try:
            import pyautogui
            pyautogui.press(key)
        except Exception as exc:
            print(f"[Music] Media key failed: {exc}")

    def set_track(self, title: str, artist: str, cover_path: str | None = None):
        self._title_label.setText(title or "No track selected")
        self._artist_label.setText(artist or "Media player ready")
        if cover_path:
            pixmap = QPixmap(cover_path)
            if not pixmap.isNull():
                self._cover.setPixmap(pixmap.scaled(
                    96, 96, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                ))
                self._cover.setText("")

    def set_track_data(self, title: str, artist: str, cover_data: bytes = b""):
        self._title_label.setText(title or "No track selected")
        self._artist_label.setText(artist or "Media player ready")
        if cover_data:
            pixmap = QPixmap()
            if pixmap.loadFromData(cover_data):
                self._cover.setPixmap(pixmap.scaled(
                    96, 96, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                ))
                self._cover.setText("")

class ReminderWidget(_FloatingPanel):
    """Transient panel shown when a scheduled reminder is delivered."""

    def __init__(self, parent=None):
        super().__init__("REMINDER", parent, 360, 132)
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        self._close = QPushButton("×")
        self._close.setFixedSize(24, 24)
        self._close.setToolTip("Close notification")
        self._close.setStyleSheet(
            f"QPushButton {{ color: {C.TEXT_DIM}; background: transparent; border: none; font: 16px 'Segoe UI'; }}"
            f"QPushButton:hover {{ color: {C.RED}; }}"
        )
        self._close.clicked.connect(self.hide)
        header = QHBoxLayout()
        header.addStretch()
        header.addWidget(self._close)
        body.addLayout(header)
        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.setStyleSheet(
            f"color: {C.WHITE}; background: transparent; font: 700 13px 'Courier New';"
        )
        body.addWidget(self._message)
        self._time = QLabel()
        self._time.setStyleSheet(
            f"color: {C.ACC2}; background: transparent; font: 9px 'Courier New';"
        )
        body.addWidget(self._time)

    def show_reminder(self, message: str):
        self._message.setText(message or "Reminder")
        self._time.setText(time.strftime("%Y-%m-%d %H:%M"))
        self.setFixedHeight(132)
        self.show()
        self.raise_()
        QTimer.singleShot(15000, self.hide)


class _TimerRing(QWidget):
    """Circular countdown face with numeric hour positions and no hands."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.remaining = 0
        self.total = 1
        self.setMinimumSize(280, 280)

    def set_time(self, remaining: int, total: int):
        self.remaining = max(0, remaining)
        self.total = max(1, total)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = side * 0.42
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)

        painter.setPen(QPen(qcol(C.BORDER), 10))
        painter.drawEllipse(rect)
        painter.setPen(QPen(qcol(C.PRI), 10))
        span = int(-360 * 16 * self.remaining / self.total)
        painter.drawArc(rect, 90 * 16, span)

        painter.setPen(qcol(C.TEXT_DIM))
        painter.setFont(QFont("Courier New", max(9, int(side * 0.045)), QFont.Weight.Bold))
        for number in range(12):
            angle = math.radians(number * 30 - 90)
            x = center.x() + math.cos(angle) * radius * 0.78
            y = center.y() + math.sin(angle) * radius * 0.78
            label = str(12 if number == 0 else number)
            bounds = painter.fontMetrics().boundingRect(label)
            painter.drawText(QPointF(x - bounds.width() / 2, y + bounds.height() / 3), label)

        seconds = self.remaining
        display = f"{seconds // 60:02d}:{seconds % 60:02d}"
        painter.setPen(qcol(C.WHITE))
        painter.setFont(QFont("Courier New", max(22, int(side * 0.12)), QFont.Weight.Bold))
        bounds = painter.fontMetrics().boundingRect(display)
        painter.drawText(QPointF(center.x() - bounds.width() / 2, center.y() + bounds.height() / 3), display)


class ProductivityTimerWidget(_FloatingPanel):
    """Live circular countdown surface for countdown timers."""

    def __init__(self, parent=None):
        super().__init__("PRODUCTIVITY TIMER", parent, 370, 420)
        self._kind = "timer"
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)
        top = QHBoxLayout()
        self._phase = QLabel("TIMER")
        self._phase.setStyleSheet(f"color: {C.ACC2}; background: transparent; font: 700 9px 'Courier New';")
        top.addWidget(self._phase)
        top.addStretch()
        close = QPushButton("×")
        close.setFixedSize(24, 24)
        close.setToolTip("Close timer")
        close.setStyleSheet(f"QPushButton {{ color: {C.TEXT_DIM}; background: transparent; border: none; font: 16px 'Segoe UI'; }} QPushButton:hover {{ color: {C.RED}; }}")
        close.clicked.connect(self._close_timer)
        top.addWidget(close)
        body.addLayout(top)
        self._ring = _TimerRing()
        body.addWidget(self._ring, stretch=1)
        self._status = QLabel("WAITING")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; font: 700 9px 'Courier New';")
        body.addWidget(self._status)
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._refresh)

    def _close_timer(self):
        self._clock.stop()
        self.hide()

    def open_timer(self, kind: str):
        self._kind = kind
        self._refresh()
        self.show()
        self.raise_()
        self._clock.start(1000)

    def _refresh(self):
        try:
            data = json.loads((Path(__file__).resolve().parent / "memory" / "productivity.json").read_text(encoding="utf-8"))
        except Exception:
            data = {}
        item = data.get("timer")
        if not item:
            self._ring.set_time(0, 1)
            self._status.setText("STOPPED")
            self._phase.setText("TIMER")
            self._clock.stop()
            return
        self._phase.setText(f"TIMER · {item.get('label', 'Timer')}")
        remaining = max(0, int(item.get("ends_at", 0) - time.time()))
        total = item.get("duration", remaining or 1)
        self._status.setText("RUNNING")
        self._ring.set_time(remaining, total)


class _SystemMetricCard(QFrame):
    def __init__(self, label: str, value: float, text: str, color: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(62)
        self.setStyleSheet(
            f"QFrame {{ background: rgba(1, 15, 24, 230); border: 1px solid {C.BORDER_B}; border-radius: 5px; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 4, 5, 4)
        bar = MetricBar(label, color, self)
        bar.set_value(value, text)
        layout.addWidget(bar)


class SystemScanWidget(_FloatingPanel):
    """Sequential system analysis cards paced by JARVIS output speech."""

    def __init__(self, parent=None):
        super().__init__("SYSTEM ANALYSIS", parent, 350, 470)
        self.setStyleSheet("background: transparent; border: none;")
        self._cards: list[QWidget] = []
        self._index = 0
        self._pace_timer = QTimer(self)
        self._pace_timer.setSingleShot(True)
        self._pace_timer.timeout.connect(self._release_next)
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        self._cards_layout = body
        close = QPushButton("×")
        close.setFixedSize(24, 24)
        close.setToolTip("Close system analysis")
        close.setStyleSheet(f"QPushButton {{ color: {C.TEXT_DIM}; background: transparent; border: none; font: 16px 'Segoe UI'; }} QPushButton:hover {{ color: {C.RED}; }}")
        close.clicked.connect(self._close)
        header = self.layout().itemAt(0).layout()
        header.addWidget(close)

    def open_scan(self, status: dict, resource: str = ""):
        self._pace_timer.stop()
        while self._cards:
            card = self._cards.pop()
            card.deleteLater()
        values = (
            ("CPU LOAD", float(status.get("cpu_percent") or 0), f"{status.get('cpu_percent', '--')}%", C.PRI),
            ("MEMORY", float(status.get("ram_percent") or 0), f"{status.get('ram_percent', '--')}%", C.ACC2),
            ("GPU LOAD", float(status.get("gpu_percent") or 0), f"{status.get('gpu_percent') or 'N/A'}%", C.ACC),
            ("TEMPERATURE", min(100.0, float(status.get("cpu_temp_c") or 0)), f"{status.get('cpu_temp_c') or 'N/A'} C", "#ff6688"),
            ("UPTIME", 0, str(status.get('uptime', '--')), C.GREEN),
            ("PROCESSES", 0, str(status.get('process_count', '--')), C.GREEN),
        )
        resource_key = resource.lower().strip()
        aliases = {
            "cpu": "CPU LOAD", "processor": "CPU LOAD",
            "ram": "MEMORY", "memory": "MEMORY",
            "gpu": "GPU LOAD", "temperature": "TEMPERATURE",
            "temp": "TEMPERATURE", "uptime": "UPTIME",
            "process": "PROCESSES", "processes": "PROCESSES",
        }
        if resource_key in aliases:
            values = tuple(item for item in values if item[0] == aliases[resource_key])
        for label, value, text, color in values:
            card = _SystemMetricCard(label, value, text, color, self)
            card.hide()
            self._cards_layout.addWidget(card)
            self._cards.append(card)
        self._index = 0
        self.show()
        self.raise_()

    def advance_with_voice(self, _text: str):
        if self._index == 0 and _text.strip():
            self._release_next()

    def _release_next(self):
        if self._index >= len(self._cards):
            return
        self._cards[self._index].show()
        self._cards[self._index].raise_()
        self._index += 1
        if self._index < len(self._cards):
            self._pace_timer.start(2800)

    def _close(self):
        self._pace_timer.stop()
        self.hide()
        window = self.window()
        if hasattr(window, "_dismiss_content"):
            window._dismiss_content()

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self.setFixedHeight(38)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(QColor(2, 14, 23, 238)))
        p.setPen(QPen(qcol(C.BORDER_B), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 6, 6)
        p.setPen(QPen(QColor(0, 212, 255, 35), 1))
        p.drawLine(7, 23, W - 7, 23)

        bar_h   = 6
        bar_y   = H - bar_h - 5
        bar_w   = W - 12
        bar_x   = 6
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 3, 3)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 3, 3)
            p.setBrush(QBrush(QColor(255, 255, 255, 125)))
            p.drawRoundedRect(QRectF(bar_x + 2, bar_y + 1, max(0, fill_w - 4), 1), 1, 1)

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 5, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 4, W - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)


class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #031722, stop:1 #010a11);
                color: {C.TEXT};
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
                padding: 8px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {C.PRI_DIM}, stop:1 {C.PRI});
                border-radius: 5px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._ai_name_lc = "jarvis"   # updated when assistant name changes
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        _ai_pfx = f"{self._ai_name_lc}:"
        if   tl.startswith("you:"):                              self._tag = "you"
        elif tl.startswith(_ai_pfx) or tl.startswith("jarvis:"): self._tag = "ai"
        elif tl.startswith("file:"):                             self._tag = "file"
        elif "err" in tl:                                        self._tag = "err"
        else:                                                    self._tag = "sys"
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)

_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v","3gp","3g2","m2ts","mts","ts","divx"], "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for JARVIS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here  or  Click to Browse")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images · Video · Audio · PDF · Docs · Code · Data")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class HolographicFilePreview(QFrame):
    """Glass-panel file preview that opens inside the HUD instead of the OS viewer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HolographicFilePreview")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            QFrame#HolographicFilePreview {{
                background: rgba(3, 13, 18, 220);
                border: 1px solid rgba(0, 212, 255, 150);
                border-radius: 16px;
            }}
            QLabel {{ background: transparent; color: {C.TEXT}; }}
            QTextEdit {{
                background: rgba(0, 10, 15, 195);
                color: {C.TEXT};
                border: 1px solid rgba(0, 212, 255, 110);
                border-radius: 10px;
                padding: 8px;
            }}
        """)
        self._path: str | None = None
        self._dragging = False
        self._resizing = False
        self._drag_start = QPoint()
        self._window_start = QPoint()
        self._resize_anchor = QPoint()
        self._resize_origin = QSize()
        self._scanline_phase = 0
        self._stack_offset = QPoint(0, 0)
        self._minimized = False
        self._normal_geometry = QRect()
        self._focus_animations = []
        self._content_mode = "text"
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setBlurRadius(28)
        self._glow.setOffset(0, 0)
        self._glow.setColor(QColor(0, 212, 255, 210))
        self.setGraphicsEffect(self._glow)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(42)
        self._pulse_timer.timeout.connect(self._advance_scanline)

        self._image_label = QLabel(self)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background: transparent; border: 1px solid rgba(0, 212, 255, 120); border-radius: 10px;")
        self._video_widget = QVideoWidget(self)
        self._video_widget.setStyleSheet("background: rgba(2, 12, 16, 220); border: 1px solid rgba(0, 212, 255, 120); border-radius: 10px;")
        self._video_widget.hide()
        self._video_player = QMediaPlayer(self)
        self._video_audio = QAudioOutput(self)
        self._video_player.setAudioOutput(self._video_audio)
        self._video_player.setVideoOutput(self._video_widget)
        self._text_display = QTextEdit(self)
        self._text_display.setReadOnly(True)
        self._text_display.setFont(QFont("Courier New", 9))
        self._text_display.hide()
        self._image_label.hide()
        self._title = QLabel("FILE PREVIEW")
        self._title.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._title.setStyleSheet(f"color: {C.PRI}; background: transparent; letter-spacing: 2px;")
        self._meta = QLabel("")
        self._meta.setFont(QFont("Courier New", 7))
        self._meta.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._minimize_btn = QPushButton("▣")
        self._minimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._minimize_btn.setFixedSize(24, 22)
        self._minimize_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid rgba(0, 212, 255, 110); border-radius: 4px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI}; }}
        """)
        self._minimize_btn.clicked.connect(self._toggle_minimized)

        self._close_btn = QPushButton("✕")
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setFixedSize(24, 22)
        self._close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid rgba(0, 212, 255, 110); border-radius: 4px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI}; }}
        """)
        self._close_btn.clicked.connect(self.deleteLater)

        header = QHBoxLayout()
        header.setContentsMargins(12, 10, 12, 8)
        header.addWidget(self._title)
        header.addStretch()
        header.addWidget(self._meta)
        header.addWidget(self._minimize_btn)
        header.addWidget(self._close_btn)

        body = QVBoxLayout(self)
        body.setContentsMargins(12, 0, 12, 12)
        body.setSpacing(8)
        body.addLayout(header)
        body.addWidget(self._image_label, stretch=1)
        body.addWidget(self._video_widget, stretch=1)
        body.addWidget(self._text_display, stretch=1)
        self.hide()

    def _advance_scanline(self):
        self._scanline_phase = (self._scanline_phase + 1) % 1000
        self.update()

    def _set_active_state(self, active: bool):
        self.setWindowOpacity(1.0 if active else 0.65)
        self._glow.setBlurRadius(32 if active else 12)
        self._glow.setColor(QColor(0, 212, 255, 220 if active else 120))

    def _toggle_minimized(self):
        if self._minimized:
            if self._normal_geometry.isValid():
                self.setMinimumSize(320, 220)
                self.setMaximumSize(QSize(16777215, 16777215))
                self.setGeometry(self._normal_geometry)
            if self._content_mode == "image":
                self._image_label.show()
            else:
                self._text_display.show()
            self._minimized = False
            self._title.setText("FILE PREVIEW")
            self._set_active_state(True)
            return

        self._normal_geometry = self.geometry()
        self._image_label.hide()
        self._text_display.hide()
        self._minimized = True
        self._title.setText("FILE")
        self._meta.setText(Path(self._path).name if self._path else "document")
        self.setFixedSize(210, 88)
        parent = self.parent()
        if parent is not None:
            pad_x = max(20, parent.width() - 240)
            pad_y = max(70, parent.height() - 120)
            self.move(pad_x, pad_y)
        self._set_active_state(True)

    def _animate_focus(self):
        if self._minimized:
            return
        current = self.geometry()
        expanded = QRect(
            current.x() - 10,
            current.y() - 10,
            current.width() + 20,
            current.height() + 20,
        )
        self._glow.setBlurRadius(10)
        self._glow.setColor(QColor(0, 212, 255, 220))

        geo_anim = QPropertyAnimation(self, b"geometry", self)
        geo_anim.setDuration(180)
        geo_anim.setKeyValueAt(0.0, current)
        geo_anim.setKeyValueAt(0.45, expanded)
        geo_anim.setKeyValueAt(1.0, current)
        geo_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        glow_anim = QPropertyAnimation(self._glow, b"blurRadius", self)
        glow_anim.setDuration(180)
        glow_anim.setKeyValueAt(0.0, 28)
        glow_anim.setKeyValueAt(0.5, 44)
        glow_anim.setKeyValueAt(1.0, 28)
        glow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._focus_animations = [geo_anim, glow_anim]
        geo_anim.finished.connect(
            lambda: self._clear_preview_animations(geo_anim, glow_anim)
        )
        geo_anim.start()
        glow_anim.start()

    def _clear_preview_animations(self, *animations):
        for animation in animations:
            if animation in self._focus_animations:
                self._focus_animations.remove(animation)

    def _apply_stack_offset(self, index: int = 0):
        if index <= 0:
            self._stack_offset = QPoint(0, 0)
            return
        self._stack_offset = QPoint(index * 10, index * 12)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        if self._stack_offset:
            painter.translate(self._stack_offset.x(), self._stack_offset.y())
        glow = QColor(0, 212, 255, 80)
        dark = QColor(4, 19, 26, 235)
        deep = QColor(1, 10, 17, 245)

        gradient = QLinearGradient(QPointF(rect.topLeft()), QPointF(rect.bottomRight()))
        gradient.setColorAt(0.0, dark)
        gradient.setColorAt(0.5, QColor(6, 24, 33, 240))
        gradient.setColorAt(1.0, deep)
        painter.fillRect(rect, gradient)

        border_pen = QPen(QColor(0, 212, 255, 185), 1.5)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 16, 16)

        inner = rect.adjusted(8, 8, -8, -8)
        painter.setPen(QPen(QColor(0, 212, 255, 60), 1.0))
        painter.drawRoundedRect(inner, 12, 12)

        for y in range(10, rect.height(), 6):
            alpha = 18 + ((y + self._scanline_phase) % 24)
            painter.setPen(QPen(QColor(0, 212, 255, alpha), 1))
            painter.drawLine(12, y, rect.width() - 12, y)

        top_glow = QColor(0, 212, 255, 90)
        painter.setPen(QPen(top_glow, 1.2))
        painter.drawLine(18, 18, rect.width() - 18, 18)

        corner_pad = 22
        painter.setPen(QPen(QColor(0, 212, 255, 130), 1.5))
        painter.drawLine(corner_pad, 2, corner_pad + 42, 2)
        painter.drawLine(2, corner_pad, 2, corner_pad + 42)
        painter.drawLine(rect.width() - corner_pad - 42, 2, rect.width() - corner_pad, 2)
        painter.drawLine(rect.width() - 2, corner_pad, rect.width() - 2, corner_pad + 42)
        painter.drawLine(corner_pad, rect.height() - 2, corner_pad + 42, rect.height() - 2)
        painter.drawLine(2, rect.height() - corner_pad - 42, 2, rect.height() - corner_pad)
        painter.drawLine(rect.width() - corner_pad - 42, rect.height() - 2, rect.width() - corner_pad, rect.height() - 2)
        painter.drawLine(rect.width() - 2, rect.height() - corner_pad - 42, rect.width() - 2, rect.height() - corner_pad)

        painter.end()
        super().paintEvent(event)

    def show_path(self, path: str):
        self._path = path
        p = Path(path)
        self._title.setText("FILE PREVIEW")
        self._meta.setText(f"{p.name}  ·  {_fmt_size(p.stat().st_size) if p.exists() else 'unknown size'}")
        kind = _file_category(p)
        self._text_display.clear()
        self._image_label.clear()
        self._image_label.hide()
        self._video_widget.hide()
        try:
            self._video_player.stop()
        except Exception:
            pass
        self._text_display.hide()

        def _pdf_placeholder() -> QPixmap:
            w, h = 620, 420
            img = QImage(w, h, QImage.Format.Format_RGB32)
            img.fill(0x08151d)
            painter = QPainter(img)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QColor("#00d4ff"))
            painter.setBrush(QColor("#0b202d"))
            painter.drawRoundedRect(28, 28, w - 56, h - 56, 18, 18)
            painter.setPen(QColor("#00d4ff"))
            painter.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
            painter.drawText(54, 80, "PDF DOCUMENT")
            painter.setFont(QFont("Courier New", 10))
            painter.setPen(QColor("#8ffcff"))
            painter.drawText(54, 108, p.name)
            painter.setPen(QColor("#007a99"))
            for y in range(150, h - 60, 18):
                x0 = 54
                length = 190 + ((y * 13) % 210)
                painter.drawLine(x0, y, x0 + length, y)
            painter.setPen(QColor("#00d4ff"))
            painter.drawRect(54, 140, w - 180, h - 200)
            painter.setBrush(QColor("#001f2e"))
            painter.drawRoundedRect(54, 152, w - 180, h - 212, 10, 10)
            painter.setPen(QColor("#8ffcff"))
            painter.setFont(QFont("Courier New", 11))
            painter.drawText(74, 182, "page 01")
            painter.setPen(QColor("#5ab8cc"))
            painter.drawText(74, 202, "Adobe-style container")
            painter.drawText(74, 228, "holographic preview active")
            painter.end()
            return QPixmap.fromImage(img)

        try:
            if kind == "image":
                pix = QPixmap(path)
                if not pix.isNull():
                    self._image_label.setPixmap(pix.scaled(
                        520, 320,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                    self._image_label.show()
                    self._content_mode = "image"
                    self.resize(620, 420)
                    return

            if kind == "pdf":
                try:
                    import fitz
                    doc = fitz.open(path)
                    if doc.page_count > 0:
                        page = doc.load_page(0)
                        pix = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7))
                        qimg = QImage(
                            pix.samples,
                            pix.width,
                            pix.height,
                            pix.stride,
                            QImage.Format.Format_RGB888,
                        )
                        self._image_label.setPixmap(
                            QPixmap.fromImage(qimg).scaled(
                                520, 320,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
                        self._image_label.show()
                        self._content_mode = "image"
                        self.resize(620, 420)
                        return
                except Exception:
                    pass

                self._image_label.setPixmap(
                    _pdf_placeholder().scaled(
                        520, 320,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self._image_label.show()
                self._content_mode = "image"
                self.resize(620, 420)
                return

            if kind == "video":
                try:
                    if p.exists():
                        self._video_player.setSource(QUrl.fromLocalFile(str(p)))
                        self._video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
                        self._video_widget.show()
                        self._video_player.play()
                        self._content_mode = "video"
                        self.resize(620, 420)
                        return
                except Exception:
                    pass

            if kind in {"text", "code", "data", "json", "xml", "csv", "word", "excel", "pptx"}:
                content = ""
                try:
                    if p.suffix.lower() in {".txt", ".md", ".log", ".rst", ".csv", ".json", ".xml", ".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".cs", ".go", ".rs", ".sql", ".yaml", ".yml", ".toml", ".sh"}:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                    elif p.suffix.lower() in {".docx", ".xlsx", ".pptx"}:
                        content = f"[Office document preview]\n\n{p.name}\n\nThis file is being handled as a holographic document object."
                    else:
                        content = f"[File preview]\n\n{p.name}\n\n{_fmt_size(p.stat().st_size)}"
                    if len(content) > 12000:
                        content = content[:12000] + "\n\n[preview truncated]"
                except Exception:
                    content = f"[Preview unavailable]\n\n{p.name}\n\nUnable to read file contents for display."
                self._text_display.setPlainText(content)
                self._text_display.show()
                self._content_mode = "text"
                self.resize(620, 420)
                return
        except Exception:
            pass

        self._text_display.setPlainText(
            f"[FILE PREVIEW]\n\n{p.name}\n\nThis file type is supported in the Jarvis holographic workspace."
        )
        self._text_display.show()
        self._content_mode = "text"
        self.resize(620, 420)


    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        parent = self.parent()
        if parent is not None and hasattr(parent, "_file_previews"):
            previews = getattr(parent, "_file_previews", [])
            if self in previews:
                previews.remove(self)
                previews.append(self)
                parent._file_preview = self
        self.raise_()
        self.activateWindow()
        self._animate_focus()

        parent = self.parent()
        if parent is not None and hasattr(parent, "_file_previews"):
            previews = getattr(parent, "_file_previews", [])
            for idx, preview in enumerate(previews):
                active = preview is self
                preview._set_active_state(active)
                if active:
                    preview._apply_stack_offset(idx)
                else:
                    preview._apply_stack_offset(0)

        pos = event.pos()
        if pos.y() <= 34:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
            self._window_start = self.frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif pos.x() >= self.width() - 18 and pos.y() >= self.height() - 18:
            self._resizing = True
            self._resize_anchor = event.globalPosition().toPoint()
            self._resize_origin = self.size()
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            self.move(self._window_start + delta)
            return
        if self._resizing:
            delta = event.globalPosition().toPoint() - self._resize_anchor
            new_w = max(320, self._resize_origin.width() + delta.x())
            new_h = max(220, self._resize_origin.height() + delta.y())
            self.resize(new_w, new_h)
            return
        if event.pos().x() >= self.width() - 18 and event.pos().y() >= self.height() - 18:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.unsetCursor()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        self._resizing = False
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._path:
            return
        self.raise_()
        self._pulse_timer.start()

        final_rect = self.geometry()
        start_rect = QRect(
            final_rect.x() + max(28, final_rect.width() // 7),
            final_rect.y() + max(22, final_rect.height() // 5),
            max(140, int(final_rect.width() * 0.72)),
            max(90, int(final_rect.height() * 0.68)),
        )
        self.setGeometry(start_rect)
        self._glow.setBlurRadius(0)
        self._glow.setColor(QColor(0, 212, 255, 200))

        geo_anim = QPropertyAnimation(self, b"geometry", self)
        geo_anim.setDuration(420)
        geo_anim.setStartValue(start_rect)
        geo_anim.setEndValue(final_rect)
        geo_anim.setEasingCurve(QEasingCurve.Type.OutBack)

        glow_anim = QPropertyAnimation(self._glow, b"blurRadius", self)
        glow_anim.setDuration(420)
        glow_anim.setStartValue(0)
        glow_anim.setEndValue(32)
        glow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        fade_anim.setDuration(260)
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Keep one animation responsible for geometry; a concurrent pos
        # animation can overwrite geometry updates on Windows.
        self._focus_animations = [geo_anim, glow_anim, fade_anim]
        geo_anim.finished.connect(
            lambda: self._clear_preview_animations(geo_anim, glow_anim, fade_anim)
        )
        geo_anim.start()
        glow_anim.start()
        fade_anim.start()
        QTimer.singleShot(80, self._animate_focus)


class HolographicFolderPreview(_FloatingPanel):
    """Interactive folder panel that keeps its parent folder open."""

    item_opened = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("FOLDER", parent, 430, 420)
        self.setObjectName("HolographicFolderPreview")
        self.setStyleSheet(f"""
            QFrame#HolographicFolderPreview {{
                background: rgba(3, 13, 18, 232);
                border: 1px solid rgba(0, 212, 255, 180);
                border-radius: 14px;
            }}
            QLabel {{ background: transparent; color: {C.TEXT}; }}
            QListWidget {{
                background: rgba(0, 10, 15, 205);
                color: {C.TEXT};
                border: 1px solid rgba(0, 212, 255, 110);
                border-radius: 8px;
                padding: 6px;
                font: 9pt 'Courier New';
            }}
            QListWidget::item {{ padding: 8px 6px; border-bottom: 1px solid rgba(0, 212, 255, 35); }}
            QListWidget::item:hover {{ background: rgba(0, 212, 255, 35); color: {C.PRI}; }}
            QListWidget::item:selected {{ background: rgba(0, 212, 255, 55); color: {C.PRI}; }}
        """)
        close_button = QPushButton("✕", self)
        close_button.setFixedSize(24, 22)
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.setToolTip("Close folder")
        close_button.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid rgba(0, 212, 255, 110); border-radius: 4px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI}; }}
        """)
        close_button.clicked.connect(self.deleteLater)
        header = self.layout().itemAt(0).layout()
        if header is not None:
            header.addWidget(close_button)
        self._path = None
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        self._location = QLabel("", self._body)
        self._location.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._location.setWordWrap(True)
        self._items = QListWidget(self._body)
        self._items.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._items.itemClicked.connect(self._open_item)
        self._items.itemDoubleClicked.connect(self._open_item)
        body.addWidget(self._location)
        body.addWidget(self._items, stretch=1)

    def show_path(self, path: str):
        folder = Path(path).expanduser().resolve()
        if not folder.is_dir():
            return
        self._path = str(folder.resolve())
        self._location.setText(self._path)
        self._items.clear()
        try:
            entries = sorted(folder.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.lower()))
        except OSError:
            entries = []
        visible_entries = [entry for entry in entries if not entry.name.startswith(".")]
        for entry in visible_entries:
            prefix = "[DIR] " if entry.is_dir() else "[FILE]"
            item = QListWidgetItem(f"{prefix}  {entry.name}")
            item.setData(Qt.ItemDataRole.UserRole, str(entry))
            self._items.addItem(item)
        if not visible_entries:
            self._items.addItem("[EMPTY]")
        self.setWindowTitle(f"Folder — {folder.name}")
        self.resize(430, 420)

    def _open_item(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.item_opened.emit(str(path))


class _CameraPreview(QWidget):
    """Floating overlay that briefly shows what the camera captured."""

    _W, _H = 244, 188

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _CameraPreview {{
                background: rgba(0, 6, 10, 242);
                border: 1px solid {C.PRI};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 6)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        title = QLabel("◈  VISUAL INPUT")
        title.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setFont(QFont("Courier New", 8))
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; border: none;"
        )
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self._img_lbl)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    def show_frame(self, img_bytes: bytes) -> None:
        px = QPixmap()
        px.loadFromData(img_bytes)
        if not px.isNull():
            max_w = self._W - 12
            scaled = px.scaled(
                max_w, 160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setFixedSize(scaled.width(), scaled.height())
            self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(6_000)   # auto-dismiss after 6 s


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("◈  INITIALISATION REQUIRED", 13, True))
        layout.addWidget(_lbl("Configure J.A.R.V.I.S. before first boot.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("GEMINI API KEY", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, self._sel_os)


class HueWheel(QWidget):
    """
    Dairesel renk seçici. Kullanıcı tutamacı (küçük beyaz daire) çarkın
    çevresinde sürükleyerek TÜM renk tonları arasından seçim yapar.
    Merkezdeki dolu daire seçilen rengin canlı önizlemesidir.
    """

    hue_picked    = pyqtSignal(str)   # sürükleme sırasında (canlı)
    hue_committed = pyqtSignal(str)   # tutamaç bırakıldığında

    _RING = 16   # halka kalınlığı (px)

    def __init__(self, initial_hex: str = DEFAULT_UI_COLOR, parent=None):
        super().__init__(parent)
        self.setFixedSize(148, 148)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hue  = 0.53
        self._drag = False
        self.set_color(initial_hex)

    # ── API ──────────────────────────────────────────────────────────────────
    def color(self) -> str:
        return QColor.fromHsvF(self._hue, 1.0, 1.0).name()

    def set_color(self, hex_str: str):
        c = QColor((hex_str or "").strip())
        if c.isValid() and c.hsvHueF() >= 0:
            self._hue = c.hsvHueF()
            self.update()

    # ── geometri yardımcıları ────────────────────────────────────────────────
    def _ring_rect(self) -> QRectF:
        m = self._RING / 2 + 3
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def _hue_from_pos(self, pos: QPointF) -> float:
        c  = QRectF(self.rect()).center()
        dx = pos.x() - c.x()
        dy = c.y() - pos.y()          # ekran y'si aşağı — matematiksel eksene çevir
        ang = math.atan2(dy, dx)      # [-π, π], saat yönünün tersi
        return (ang / (2 * math.pi)) % 1.0

    # ── çizim ────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect   = self._ring_rect()
        center = rect.center()

        grad = QConicalGradient(center, 0)
        for i in range(0, 361, 20):
            grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))
        p.setPen(QPen(QBrush(grad), self._RING))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)

        # merkez önizleme dairesi
        preview = QColor.fromHsvF(self._hue, 1.0, 1.0)
        inner   = rect.adjusted(30, 30, -30, -30)
        p.setPen(QPen(qcol(C.BORDER_B), 1))
        p.setBrush(QBrush(preview))
        p.drawEllipse(inner)

        # sürüklenen tutamaç
        r   = rect.width() / 2
        ang = self._hue * 2 * math.pi
        hx  = center.x() + r * math.cos(ang)
        hy  = center.y() - r * math.sin(ang)
        p.setPen(QPen(QColor("#00060a"), 2))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QPointF(hx, hy), 7.5, 7.5)

    # ── fare ─────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        self._drag = True
        self._hue  = self._hue_from_pos(e.position())
        self.update()
        self.hue_picked.emit(self.color())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._hue = self._hue_from_pos(e.position())
            self.update()
            self.hue_picked.emit(self.color())

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.hue_committed.emit(self.color())


class CustomizeOverlay(QWidget):
    """Floating overlay — change assistant name, user name and UI colour."""

    saved = pyqtSignal(str, str, str)   # assistant_name, user_name, ui_color
    _OW, _OH = 400, 500

    def __init__(self, assistant_name="JARVIS", user_name="",
                 ui_color=DEFAULT_UI_COLOR, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            CustomizeOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(8)

        def _lbl(txt, fs=9, bold=False, color=C.PRI, align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt); w.setAlignment(align)
            w.setFont(QFont("Courier New", fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        _fs = (f"QLineEdit {{ background: #000d12; color: {C.TEXT}; "
               f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}"
               f"QLineEdit:focus {{ border: 1px solid {C.PRI}; }}")

        lay.addWidget(_lbl("⚙  CUSTOMISE ASSISTANT", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_lbl("ASSISTANT NAME", 8, color=C.TEXT_DIM,
                            align=Qt.AlignmentFlag.AlignLeft))
        self._name_input = QLineEdit(assistant_name)
        self._name_input.setFont(QFont("Courier New", 10))
        self._name_input.setFixedHeight(32)
        self._name_input.setStyleSheet(_fs)
        lay.addWidget(self._name_input)

        lay.addSpacing(4)
        lay.addWidget(_lbl("YOUR NAME  (leave blank for default sir / efendim)", 8,
                            color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        self._user_input = QLineEdit(user_name)
        self._user_input.setPlaceholderText("e.g.  Tony   (leave blank for auto)")
        self._user_input.setFont(QFont("Courier New", 10))
        self._user_input.setFixedHeight(32)
        self._user_input.setStyleSheet(_fs)
        lay.addWidget(self._user_input)

        # ── UI colour — renk çarkı ───────────────────────────────────────────
        lay.addSpacing(4)
        clr_hdr = QHBoxLayout()
        clr_hdr.addWidget(_lbl("UI COLOUR  —  drag the handle", 8,
                               color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        clr_hdr.addStretch()
        df_btn = QPushButton("DEFAULT")
        df_btn.setFixedSize(64, 20)
        df_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        df_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        df_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        df_btn.clicked.connect(lambda: self._set_color(DEFAULT_UI_COLOR))
        clr_hdr.addWidget(df_btn)
        lay.addLayout(clr_hdr)

        self._initial_color = (ui_color or DEFAULT_UI_COLOR).strip().lower()
        self._sel_color     = self._initial_color
        self.on_preview     = None   # callable(hex) — canlı önizleme; MainWindow bağlar

        self._wheel = HueWheel(self._sel_color)
        wheel_row = QHBoxLayout()
        wheel_row.addStretch(); wheel_row.addWidget(self._wheel); wheel_row.addStretch()
        lay.addLayout(wheel_row)
        self._wheel.hue_picked.connect(self._on_wheel_pick)
        self._wheel.hue_committed.connect(self._on_wheel_commit)

        self._hex_input = QLineEdit(self._sel_color)
        self._hex_input.setPlaceholderText("#00d4ff   (custom hex colour)")
        self._hex_input.setFont(QFont("Courier New", 10))
        self._hex_input.setFixedHeight(28)
        self._hex_input.setStyleSheet(_fs)
        self._hex_input.textEdited.connect(self._on_hex_edited)
        lay.addWidget(self._hex_input)

        lay.addSpacing(6)
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)

        save_btn = QPushButton("▸  APPLY CHANGES")
        save_btn.setFixedHeight(34)
        save_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setFixedHeight(34)
        cancel_btn.setFont(QFont("Courier New", 9))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

    # ── renk akışı ───────────────────────────────────────────────────────────
    def _set_color(self, hx: str, update_wheel: bool = True, preview: bool = True):
        """Seçili rengi günceller; hex kutusu + çark senkron kalır, tema canlı önizlenir."""
        self._sel_color = hx.strip().lower()
        self._hex_input.blockSignals(True)
        self._hex_input.setText(self._sel_color)
        self._hex_input.blockSignals(False)
        if update_wheel:
            self._wheel.set_color(self._sel_color)
        if preview and self.on_preview:
            self.on_preview(self._sel_color)

    def _on_wheel_pick(self, hx: str):
        # Sürükleme sırasında: hex kutusunu güncelle, temayı henüz uygulama
        self._sel_color = hx
        self._hex_input.blockSignals(True)
        self._hex_input.setText(hx)
        self._hex_input.blockSignals(False)

    def _on_wheel_commit(self, hx: str):
        # Tutamaç bırakıldı → tüm arayüzü canlı önizle
        self._set_color(hx, update_wheel=False)

    def _on_hex_edited(self, text: str):
        t = text.strip().lower()
        if t.startswith("#") and len(t) == 7:
            try:
                int(t[1:], 16)
            except ValueError:
                return
            self._set_color(t, update_wheel=True, preview=True)

    def _cancel(self):
        # Önizleme uygulandıysa açılıştaki renge geri dön
        if self.on_preview and self._sel_color != self._initial_color:
            self.on_preview(self._initial_color)
        self.hide()

    def _save(self):
        name = self._name_input.text().strip() or "JARVIS"
        user = self._user_input.text().strip()
        self.saved.emit(name, user, self._sel_color or DEFAULT_UI_COLOR)
        self.hide()


class PluginManagerOverlay(QWidget):
    """Floating overlay — lists discovered plugins with per-plugin ON/OFF toggles."""

    _OW = 420

    def __init__(self, plugins: list[dict], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            PluginManagerOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("🧩  PLUGIN MANAGER")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        if not plugins:
            empty = QLabel("No plugins found in /plugins.")
            empty.setFont(QFont("Courier New", 8))
            empty.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(empty)

        for p in plugins:
            lay.addLayout(self._build_row(p))

        lay.addSpacing(4)
        close_btn = QPushButton("CLOSE")
        close_btn.setFixedHeight(30)
        close_btn.setFont(QFont("Courier New", 9))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self.hide)
        lay.addWidget(close_btn)
        self.adjustSize()

    def _build_row(self, p: dict) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(6)

        label_text = p["name"] if p["valid"] else f"{p['name']}  (⚠ {p['file']})"
        lbl = QLabel(label_text)
        lbl.setFont(QFont("Courier New", 8))
        lbl.setStyleSheet(f"color: {C.TEXT if p['valid'] else C.TEXT_DIM}; background: transparent;")
        lbl.setToolTip(p["description"] if p["valid"] else p["error"])
        lbl.setWordWrap(False)
        row.addWidget(lbl, stretch=1)

        btn = QPushButton()
        btn.setFixedSize(72, 24)
        btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        if not p["valid"]:
            btn.setText("BROKEN")
            btn.setEnabled(False)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
            """)
        else:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._style_toggle(btn, p["enabled"])
            btn.clicked.connect(lambda _, name=p["name"], b=btn: self._toggle(name, b))
        row.addWidget(btn)
        return row

    def _style_toggle(self, btn: QPushButton, enabled: bool):
        if enabled:
            btn.setText("ON")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            btn.setText("OFF")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
            """)

    def _toggle(self, name: str, btn: QPushButton):
        from memory.config_manager import get_plugin_enabled, save_plugin_enabled
        new_val = not get_plugin_enabled(name)
        save_plugin_enabled(name, new_val)
        self._style_toggle(btn, new_val)


class SessionsOverlay(QWidget):
    """Floating manager for persistent work sessions."""

    _OW, _OH = 620, 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self._OW, self._OH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SessionsOverlay {{ background: rgba(0, 6, 10, 248); border: 1px solid {C.BORDER_B}; border-radius: 6px; }}
            QLabel {{ color: {C.TEXT_MED}; background: transparent; font: 8px 'Courier New'; }}
            QLineEdit, QTextEdit {{ background: #000d12; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 3px; padding: 5px; font: 8px 'Courier New'; }}
            QListWidget {{ background: {C.PANEL2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 3px; font: 8px 'Courier New'; }}
            QListWidget::item {{ padding: 7px 5px; border-bottom: 1px solid {C.BORDER}; }}
            QListWidget::item:selected {{ color: {C.PRI}; background: {C.PRI_GHO}; }}
            QPushButton {{ background: transparent; color: {C.TEXT_MED}; border: 1px solid {C.BORDER}; border-radius: 3px; padding: 5px; font: 8px 'Courier New'; }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}
        """)
        self._sessions = []
        self._selected = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(7)

        header = QHBoxLayout()
        title = QLabel("◈  WORK SESSIONS")
        title.setStyleSheet(f"color: {C.PRI}; font: 700 12px 'Courier New';")
        self._count = QLabel("0 SESSIONS")
        self._count.setStyleSheet(f"color: {C.PRI_DIM}; font: 700 8px 'Courier New';")
        refresh = QPushButton("REFRESH")
        refresh.setFixedWidth(78)
        refresh.clicked.connect(self._refresh)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._count)
        header.addWidget(refresh)
        layout.addLayout(header)

        content = QSplitter(Qt.Orientation.Horizontal)
        content.setChildrenCollapsible(False)
        self._list = QListWidget()
        self._list.setMinimumWidth(260)
        self._list.currentRowChanged.connect(self._select_session)
        content.addWidget(self._list)
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("Select a session to see its context.")
        self._detail.setMinimumHeight(155)
        content.addWidget(self._detail)
        content.setStretchFactor(0, 1)
        content.setStretchFactor(1, 2)
        layout.addWidget(content, stretch=1)

        search_row = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search title or topic")
        self._search_input.textChanged.connect(self._refresh)
        search_row.addWidget(self._search_input, stretch=1)
        delete = QPushButton("DELETE SELECTED")
        delete.clicked.connect(self._delete_selected)
        search_row.addWidget(delete)
        layout.addLayout(search_row)

        self._status = QLabel("Select a session or create a new one.")
        self._status.setStyleSheet(f"color: {C.TEXT_DIM}; font: 8px 'Courier New';")
        layout.addWidget(self._status)
        note_row = QHBoxLayout()
        self._note_input = QLineEdit()
        self._note_input.setPlaceholderText("Add a note to the selected session")
        self._note_input.returnPressed.connect(self._add_note)
        add_note = QPushButton("ADD NOTE")
        add_note.clicked.connect(self._add_note)
        note_row.addWidget(self._note_input, stretch=1)
        note_row.addWidget(add_note)
        layout.addLayout(note_row)

        form_title = QLabel("NEW SESSION")
        form_title.setStyleSheet(f"color: {C.PRI_DIM}; font: 700 8px 'Courier New';")
        layout.addWidget(form_title)
        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("Title")
        self._topic_input = QLineEdit()
        self._topic_input.setPlaceholderText("Topic")
        self._summary_input = QTextEdit()
        self._summary_input.setPlaceholderText("What is this session about?")
        self._summary_input.setFixedHeight(54)
        layout.addWidget(self._title_input)
        layout.addWidget(self._topic_input)
        layout.addWidget(self._summary_input)

        buttons = QHBoxLayout()
        create = QPushButton("CREATE SESSION")
        create.clicked.connect(self._create_session)
        focus = QPushButton("ACTIVATE SELECTED")
        focus.clicked.connect(self._focus_selected)
        close = QPushButton("CLOSE")
        close.clicked.connect(self.hide)
        buttons.addWidget(create)
        buttons.addWidget(focus)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._refresh()

    def _refresh(self):
        from memory.memory_manager import list_work_sessions
        self._sessions = list_work_sessions()
        self._list.clear()
        needle = self._search_input.text().strip().lower() if hasattr(self, "_search_input") else ""
        ordered = [session for session in reversed(self._sessions) if not needle or needle in (
            f"{session.get('title', '')} {session.get('topic', '')}"
        ).lower()]
        self._count.setText(f"{len(ordered)} SESSION{'S' if len(ordered) != 1 else ''}")
        for session in ordered:
            title = str(session.get("title", "Untitled Session"))[:32]
            topic = str(session.get("topic", "general"))[:20]
            updated = str(session.get("updated_at", session.get("created_at", "")))[:16]
            self._list.addItem(
                f"{title}\n{topic}  ·  {updated}"
            )
        if ordered:
            self._list.setCurrentRow(0)
        else:
            self._selected = None
            self._detail.setPlainText("No work sessions yet.\n\nCreate the first one below.")
            self._status.setText("No sessions available.")

    def _select_session(self, row: int):
        ordered = list(reversed(self._sessions))
        if row < 0 or row >= len(ordered):
            self._selected = None
            return
        self._selected = ordered[row]
        notes = self._selected.get("notes", [])
        note_text = "\n".join(
            f"• {n.get('text', '')}  [{n.get('created_at', '')}]" for n in notes[-10:]
        )
        detail = (
            f"{self._selected.get('title', 'Untitled Session')}\n"
            f"Topic: {self._selected.get('topic', 'general')}\n"
            f"Scope: {self._selected.get('scope', 'project')}\n"
            f"Updated: {self._selected.get('updated_at', self._selected.get('created_at', ''))}\n\n"
            f"{self._selected.get('summary', '')}\n\n"
            f"NOTES\n{note_text or 'No notes yet.'}"
        )
        self._detail.setPlainText(detail)
        self._status.setText(f"Selected: {self._selected.get('title', 'Untitled Session')}")

    def _create_session(self):
        from memory.memory_manager import create_work_session
        title = self._title_input.text().strip()
        topic = self._topic_input.text().strip()
        summary = self._summary_input.toPlainText().strip()
        if not title or not topic or not summary:
            self._status.setText("Title, topic and summary are required.")
            return
        create_work_session(title, topic, summary)
        self._title_input.clear()
        self._topic_input.clear()
        self._summary_input.clear()
        self._refresh()
        self._status.setText(f"Session created: {title}")

    def _add_note(self):
        if not self._selected:
            self._status.setText("Select a session before adding a note.")
            return
        note = self._note_input.text().strip()
        if not note:
            return
        from memory.memory_manager import append_work_session_note
        updated = append_work_session_note(self._selected.get("id", ""), note)
        if updated:
            self._selected = updated
            self._note_input.clear()
            self._select_session(self._list.currentRow())
            self._status.setText("Note added.")

    def _delete_selected(self):
        if not self._selected:
            self._status.setText("Select a session before deleting it.")
            return
        from memory.memory_manager import delete_work_session
        title = self._selected.get("title", "Untitled Session")
        if delete_work_session(self._selected.get("id", "")):
            self._selected = None
            self._refresh()
            self._status.setText(f"Session deleted: {title}")

    def _focus_selected(self):
        if not self._selected:
            return
        callback = getattr(self.window(), "on_text_command", None)
        if callback:
            callback(
                f"[WORK_SESSION_ACTIVE] Title: {self._selected.get('title')} | "
                f"Topic: {self._selected.get('topic')} | Summary: {self._selected.get('summary')}"
            )
        self.hide()


class ClipboardPanel(QWidget):
    """Floating panel shown when text is copied — offers quick Jarvis actions."""

    action_requested = pyqtSignal(str)
    _W, _H = 326, 112

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ClipboardPanel {{
                background: rgba(0, 8, 14, 248);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)
        self._clip_text = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 7)
        lay.setSpacing(4)

        hdr = QHBoxLayout(); hdr.setSpacing(4)
        icon_lbl = QLabel("◈  CLIPBOARD DETECTED")
        icon_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        icon_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent;")
        hdr.addWidget(icon_lbl); hdr.addStretch()
        x_btn = QPushButton("✕")
        x_btn.setFixedSize(16, 16)
        x_btn.setFont(QFont("Courier New", 8))
        x_btn.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        x_btn.clicked.connect(self.hide)
        hdr.addWidget(x_btn)
        lay.addLayout(hdr)

        self._preview = QLabel()
        self._preview.setFont(QFont("Courier New", 8))
        self._preview.setStyleSheet(f"""
            color: {C.TEXT}; background: {C.PANEL2};
            border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 6px;
        """)
        self._preview.setWordWrap(False)
        self._preview.setFixedHeight(28)
        lay.addWidget(self._preview)

        btn_row = QHBoxLayout(); btn_row.setSpacing(4)
        _bs = (f"QPushButton {{ background: {C.PANEL2}; color: {C.TEXT_MED}; "
               f"border: 1px solid {C.BORDER}; border-radius: 2px; }}"
               f"QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}")
        for label, cmd_fmt in [
            ("TRANSLATE", "Translate this text to English: {text}"),
            ("SUMMARISE", "Summarise this: {text}"),
            ("EXPLAIN",   "Explain this: {text}"),
            ("FIX",       "Fix grammar and spelling: {text}"),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(_bs)
            b.clicked.connect(lambda _, c=cmd_fmt: self._trigger(c))
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.hide)
        self.hide()

    def _trigger(self, cmd_fmt: str):
        if self._clip_text:
            self.action_requested.emit(cmd_fmt.format(text=self._clip_text[:800]))
        self.hide()

    def show_clipboard(self, text: str):
        self._clip_text = text
        preview = text[:58].replace('\n', ' ')
        if len(text) > 58:
            preview += "…"
        self._preview.setText(f'"{preview}"')
        self.show(); self.raise_()
        self._dismiss_timer.start(8000)


class RemoteKeyOverlay(QWidget):
    """Floating overlay — QR code for instant phone pairing + manual key fallback."""

    closed = pyqtSignal()

    _OW, _OH = 400, 465

    def __init__(self, url: str, key: str, auto_login_url: str = "",
                 manual_url: str = "", expiry_secs: int = 600, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            RemoteKeyOverlay {{
                background: rgba(0, 4, 12, 0.95);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)
        self._expiry          = time.time() + expiry_secs
        self._on_new_key      = None
        self._auto_login_url  = auto_login_url
        self._manual_url      = manual_url or url

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("◈  REMOTE ACCESS", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        # ── QR code ───────────────────────────────────────────────────────────
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(176, 176)
        self._qr_label.setStyleSheet(
            "background: white; border-radius: 10px; padding: 4px;"
        )
        qr_row = QHBoxLayout()
        qr_row.addStretch()
        qr_row.addWidget(self._qr_label)
        qr_row.addStretch()
        lay.addLayout(qr_row)

        self._update_qr(auto_login_url)

        lay.addWidget(_lbl("Scan with phone camera to connect instantly", 8, color=C.TEXT_DIM))

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_lbl("Or enter manually:", 7, color=C.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))

        self._url_lbl = QLabel(self._manual_url)
        self._url_lbl.setFont(QFont("Courier New", 8))
        self._url_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        self._url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._url_lbl)

        self._key_lbl = QLabel(key)
        self._key_lbl.setFont(QFont("Courier New", 28, QFont.Weight.Bold))
        self._key_lbl.setStyleSheet(f"""
            color: {C.ACC};
            background: {C.PANEL2};
            border: 1px solid {C.BORDER_B};
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 10px;
        """)
        self._key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._key_lbl)

        self._timer_lbl = QLabel()
        self._timer_lbl.setFont(QFont("Courier New", 8))
        self._timer_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._timer_lbl)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        new_btn = QPushButton("NEW KEY")
        new_btn.setFixedHeight(32)
        new_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 5px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        new_btn.clicked.connect(self._refresh_key)
        btn_row.addWidget(new_btn)

        close_btn = QPushButton("DISMISS")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self._do_close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._ctimer = QTimer(self)
        self._ctimer.timeout.connect(self._tick)
        self._ctimer.start(1000)
        self._tick()

    def set_new_key_callback(self, fn) -> None:
        self._on_new_key = fn

    def _update_qr(self, url: str) -> None:
        if not url:
            self._qr_label.setText("—")
            return
        try:
            import qrcode as _qrmod
            from io import BytesIO
            qr = _qrmod.QRCode(
                box_size=5, border=2,
                error_correction=_qrmod.constants.ERROR_CORRECT_M,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._qr_label.setPixmap(
                px.scaled(170, 170,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        except ImportError:
            self._qr_label.setText("pip install\nqrcode[pil]")
            self._qr_label.setFont(QFont("Courier New", 8))
            self._qr_label.setStyleSheet(
                "color: #888; background: white; border-radius: 10px; padding: 4px;"
            )
        except Exception:
            self._qr_label.setText(url[:28])
            self._qr_label.setFont(QFont("Courier New", 7))
            self._qr_label.setStyleSheet(
                f"color: {C.PRI}; background: white; border-radius: 10px; padding: 4px;"
            )

    def _tick(self):
        remaining = max(0, int(self._expiry - time.time()))
        m, s = divmod(remaining, 60)
        self._timer_lbl.setText(f"Key expires in  {m:02d}:{s:02d}")
        if remaining == 0:
            self._do_close()

    def mark_connected(self) -> None:
        """Call from any thread when a phone successfully connects."""
        self._ctimer.stop()
        self._key_lbl.setText("CONNECTED")
        self._key_lbl.setStyleSheet(f"""
            color: {C.GREEN};
            background: rgba(34,197,94,0.08);
            border: 2px solid rgba(34,197,94,0.4);
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 4px;
        """)
        self._qr_label.setText("✓")
        self._qr_label.setFont(QFont("Courier New", 54, QFont.Weight.Bold))
        self._qr_label.setStyleSheet(
            "color: #00ff88; background: #001a0d; border-radius: 10px;"
        )
        self._timer_lbl.setText("Phone connected — JARVIS ready")
        self._timer_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")

    def _refresh_key(self):
        if self._on_new_key:
            result = self._on_new_key()
            if result:
                url    = result[0]
                key    = result[1]
                auto   = result[2] if len(result) >= 3 else ""
                manual = result[3] if len(result) >= 4 else url
                self._manual_url     = manual or url
                self._url_lbl.setText(self._manual_url)
                self._key_lbl.setText(key)
                self._auto_login_url = auto
                self._update_qr(auto or url)
                self._expiry = time.time() + 600
                self._key_lbl.setStyleSheet(f"""
                    color: {C.ACC};
                    background: {C.PANEL2};
                    border: 1px solid {C.BORDER_B};
                    border-radius: 8px;
                    padding: 6px 4px;
                    letter-spacing: 10px;
                """)
                self._timer_lbl.setStyleSheet(
                    f"color: {C.TEXT_MED}; background: transparent;"
                )
                self._ctimer.start(1000)
                self._tick()

    def _do_close(self):
        self._ctimer.stop()
        self.hide()
        self.closed.emit()


class MicrophoneStatusIndicator(QWidget):
    """Widget that displays microphone connection status."""
    _mic_status_sig = pyqtSignal(str)  # "connected" | "disconnected" | "unavailable"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self._status = "connected"  # Default status
        self._mic_status_sig.connect(self._on_status_changed)
        self.setToolTip("Microphone: Connected")

    def _on_status_changed(self, status: str):
        """Update microphone status and appearance."""
        self._status = status
        if status == "connected":
            self.setToolTip("Microphone: Connected")
        elif status == "disconnected":
            self.setToolTip("Microphone: Disconnected")
        else:  # unavailable
            self.setToolTip("Microphone: Not Available")
        self.update()

    def set_status(self, status: str):
        """Thread-safe way to set microphone status."""
        self._mic_status_sig.emit(status)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Select color based on status
        if self._status == "connected":
            color = QColor(C.GREEN)
        elif self._status == "disconnected":
            color = QColor(C.ACC)  # Orange
        else:  # unavailable
            color = QColor(C.RED)

        # Draw background circle
        p.setBrush(QBrush(color))
        p.setPen(QPen(color, 1))
        p.drawEllipse(2, 2, 20, 20)

        # Draw microphone icon in white
        p.setPen(QPen(Qt.GlobalColor.white, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Microphone capsule (top)
        p.drawEllipse(8, 4, 8, 8)
        # Microphone stem (bottom)
        p.drawLine(12, 12, 12, 18)
        # Microphone base
        p.drawEllipse(10, 17, 4, 4)


class AudioSettingsOverlay(QFrame):
    """Settings surface for media handling while JARVIS is speaking."""
    saved = pyqtSignal(dict)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("AudioSettings")
        self.setFixedSize(390, 390)
        self.setStyleSheet(f"""
            QFrame#AudioSettings {{ background: {C.DARK}; border: 1px solid {C.BORDER_B}; border-radius: 6px; }}
            QLabel {{ color: {C.TEXT_MED}; background: transparent; font: 8px 'Courier New'; }}
            QLabel#Title {{ color: {C.PRI}; font: 700 12px 'Courier New'; }}
            QCheckBox, QRadioButton {{ color: {C.WHITE}; background: transparent; font: 8px 'Courier New'; }}
            QSlider::groove:horizontal {{ height: 4px; background: {C.BORDER}; }}
            QSlider::handle:horizontal {{ width: 12px; margin: -4px 0; background: {C.PRI}; border-radius: 6px; }}
            QPushButton {{ color: {C.PRI}; background: #00091a; border: 1px solid {C.PRI_DIM}; border-radius: 3px; padding: 5px; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
        """)
        self._settings = dict(settings)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        title = QLabel("AUDIO")
        title.setObjectName("Title")
        layout.addWidget(title)
        subtitle = QLabel("Riproduzione durante la voce di Jarvis")
        layout.addWidget(subtitle)

        self._adaptive = QCheckBox("Gestisci la riproduzione mentre Jarvis parla")
        self._adaptive.setChecked(bool(settings.get("adaptive_audio_enabled", True)))
        layout.addWidget(self._adaptive)
        self._adaptive_duck = QRadioButton("Abbassa il volume della riproduzione")
        self._adaptive_stop = QRadioButton("Metti in pausa la riproduzione")
        if settings.get("adaptive_audio_mode") == "stop":
            self._adaptive_stop.setChecked(True)
        else:
            self._adaptive_duck.setChecked(True)
        layout.addWidget(self._adaptive_duck)
        layout.addWidget(self._adaptive_stop)
        duck_value = int(settings.get("adaptive_audio_duck_percent", 40))
        self._adaptive_duck_slider, self._adaptive_duck_label = self._add_slider(
            layout, "Riduzione volume", -duck_value
        )
        self._adaptive.toggled.connect(self._set_adaptive_controls)
        self._adaptive_duck.toggled.connect(
            lambda checked: self._adaptive_duck_slider.setEnabled(
                self._adaptive.isChecked() and checked
            )
        )
        self._set_adaptive_controls(self._adaptive.isChecked())

        self._media_gate = QCheckBox(
            "Con riproduzione attiva, rispondi dopo 'Jarvis'"
        )
        self._media_gate.setChecked(bool(settings.get("voice_activation_enabled", False)))
        layout.addWidget(self._media_gate)

        self._push_to_talk = QCheckBox("Enable Push-to-Talk")
        self._push_to_talk.setChecked(bool(settings.get("push_to_talk_enabled", False)))
        self._push_to_talk.toggled.connect(
            lambda checked: self._media_gate.setChecked(False) if checked else None
        )
        layout.addWidget(self._push_to_talk)
        self._ptt_chord = QLineEdit(str(settings.get("push_to_talk_chord", "ctrl+space")))
        self._ptt_chord.setPlaceholderText("Shortcut, esempio: ctrl+space o f8")
        layout.addWidget(self._ptt_chord)
        ptt_hint = QLabel("Funziona anche mentre un'altra finestra è attiva su Windows.")
        ptt_hint.setWordWrap(True)
        ptt_hint.setStyleSheet(f"color: {C.TEXT_DIM}; font: 7px 'Courier New';")
        layout.addWidget(ptt_hint)
        layout.addStretch()

        save = QPushButton("SAVE AUDIO SETTINGS")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._save)
        layout.addWidget(save)
        close = QPushButton("CLOSE")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.hide)
        layout.addWidget(close)

    def _add_slider(self, layout, label_text: str, value: int):
        row = QHBoxLayout()
        label = QLabel(label_text)
        row.addWidget(label)
        value_label = QLabel()
        value_label.setFixedWidth(48)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(-100, 100)
        slider.setValue(max(-100, min(100, value)))
        slider.valueChanged.connect(lambda current: value_label.setText(f"{current:+d}%"))
        value_label.setText(f"{slider.value():+d}%")
        row.addWidget(slider, stretch=1)
        row.addWidget(value_label)
        layout.addLayout(row)
        return slider, value_label

    def _set_adaptive_controls(self, enabled: bool):
        self._adaptive_duck.setEnabled(enabled)
        self._adaptive_stop.setEnabled(enabled)
        self._adaptive_duck_slider.setEnabled(enabled and self._adaptive_duck.isChecked())

    def _save(self):
        ptt_enabled = self._push_to_talk.isChecked()
        settings = {
            "adaptive_audio_enabled": self._adaptive.isChecked(),
            "adaptive_audio_mode": "stop" if self._adaptive_stop.isChecked() else "duck",
            "adaptive_audio_duck_percent": abs(self._adaptive_duck_slider.value()),
            "voice_activation_enabled": self._media_gate.isChecked() and not ptt_enabled,
            "push_to_talk_enabled": ptt_enabled,
            "push_to_talk_chord": self._ptt_chord.text().strip().lower() or "ctrl+space",
        }
        try:
            data = _read_full_config()
            data.update(settings)
            API_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
            self.saved.emit(settings)
        except Exception as exc:
            print(f"[Audio] Settings save failed: {exc}")
        self.hide()


class ServiceStatusBar(QWidget):
    """Compact, readable health strip for the services users actually need."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER};")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(14)
        self._labels = {}
        for key, label in (("MIC", "MIC"), ("PTT", "PTT"), ("GEMINI", "GEMINI"),
                           ("GOOGLE", "GOOGLE"), ("REMOTE", "REMOTE")):
            item = QLabel(f"● {label}  --")
            item.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            item.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            item.setToolTip(f"Stato {label}")
            layout.addWidget(item)
            self._labels[key] = (item, label)
        layout.addStretch(1)

    def set_status(self, key: str, state: str, detail: str = ""):
        item_data = self._labels.get(key.upper())
        if not item_data:
            return
        item, label = item_data
        colors = {"ok": C.GREEN, "ready": C.GREEN, "active": C.ACC,
                  "warning": C.ACC2, "error": C.RED, "off": C.TEXT_DIM}
        normalized = state.lower()
        item.setText(f"● {label}  {detail or normalized.upper()}")
        item.setStyleSheet(
            f"color: {colors.get(normalized, C.PRI)}; background: transparent;"
        )


class MainWindow(QMainWindow):
    _log_sig        = pyqtSignal(str)
    _state_sig      = pyqtSignal(str)
    _content_sig    = pyqtSignal(str, str)   # (title, text) — thread-safe content display
    _file_preview_sig = pyqtSignal(str)      # open a holographic file preview
    _hologram3d_sig = pyqtSignal(str, str)  # description, optional real asset path
    _reconfig_sig   = pyqtSignal()           # trigger setup overlay from any thread
    _camera_sig     = pyqtSignal(bytes)      # show camera frame preview (small overlay)
    _cam_stream_sig = pyqtSignal(bool)       # True=start live stream, False=stop
    _cam_frame_sig  = pyqtSignal(bytes)      # live camera frame → HUD area
    _clipboard_sig  = pyqtSignal(str)        # clipboard text changed (thread-safe)
    _system_alert_sig = pyqtSignal(str)      # animated system alert
    _music_data_sig = pyqtSignal(str, str, bytes)
    _system_scan_sig = pyqtSignal(object, str)
    _mini_mode_sig = pyqtSignal(bool)
    _music_focus_sig = pyqtSignal()
    _reminder_sig   = pyqtSignal(str)
    _productivity_timer_sig = pyqtSignal(str)
    _system_scan_transcript_sig = pyqtSignal(str)
    _mic_status_sig = pyqtSignal(str)  # Microphone status signal
    _ptt_status_sig = pyqtSignal(bool, bool, str)  # enabled, held, chord
    _service_status_sig = pyqtSignal(str, str, str)
    _audio_level_sig = pyqtSignal(float)
    _phone_connected_sig = pyqtSignal()

    def __init__(self, face_path: str):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self._face_path = face_path

        # Load customization from config
        _cfg = _read_full_config()
        self._assistant_name: str = (_cfg.get("assistant_name") or "JARVIS").strip()
        _display = self._assistant_name.upper()

        # Kayıtlı UI rengini panel/stylesheet'ler kurulmadan ÖNCE uygula
        _ui_color = (_cfg.get("ui_color") or "").strip()
        if _ui_color and _ui_color.lower() != DEFAULT_UI_COLOR:
            apply_ui_accent(_ui_color)

        self.setWindowTitle(f"{_display} — MARK LI")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        # Keep the top-level HUD transparent so the desktop remains visible
        # behind JARVIS. Avoid window opacity on Windows because it forces an
        # unstable layered-window repaint path.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if _OS != "Windows":
            self.setWindowOpacity(0.96)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command   = None
        self.on_remote_clicked = None   # callable: () -> (url, key) | None
        self.on_interrupt      = None   # callable: () -> None — stop JARVIS mid-speech
        self.on_reminder       = None   # callable: (message) -> None
        self.on_audio_settings_changed = None
        self.on_restart        = None   # callable: () -> None — preserve context and restart
        self.on_reset_context  = None   # callable: () -> None — clear conversation context
        self.get_plugins       = None   # callable: () -> list[dict], set by JarvisLive
        self._muted            = False
        self._media_active     = False
        self._current_file: str | None = None
        self._remote_overlay: RemoteKeyOverlay | None = None
        self._customize_overlay: CustomizeOverlay | None = None
        self._audio_settings_overlay: AudioSettingsOverlay | None = None
        self._sessions_overlay: SessionsOverlay | None = None

        central = QWidget()
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        central.setStyleSheet("background: transparent;")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        self._service_status = ServiceStatusBar(central)
        root.addWidget(self._service_status)

        # Holographic workspace: the HUD is the visual anchor and all tools
        # float above the desktop inside this one window.
        workspace = QWidget()
        workspace.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        workspace.setStyleSheet("background: transparent;")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        self._left_panel = self._build_left_panel()
        self._left_panel.hide()

        self.hud = HudCanvas(face_path, _display)
        self._hologram3d = Hologram3DWidget(central)
        self._hologram3d.setGeometry(250, 90, 900, 560)
        # Extra transparent canvas width gives the focus animation room to
        # slide the hologram aside without clipping its outer rings.
        self.hud.setFixedSize(1000, 560)
        self._content_panel = self._build_content_panel()
        self._content_panel.setParent(central)
        self._content_panel.setMinimumSize(520, 170)
        self._content_panel.resize(760, 230)
        self._content_panel.setStyleSheet(f"""
            QWidget#ContentPanel {{
                background: rgba(9, 19, 24, 226);
                border: 1px solid {C.BORDER_B};
                border-radius: 8px;
            }}
        """)
        self._file_previews: list[HolographicFilePreview] = []
        self._file_preview = None

        self._right_panel = self._build_right_panel()
        self._right_panel.hide()

        self._hud_cam_stack = QStackedWidget()
        self._hud_cam_stack.addWidget(self.hud)
        self._hud_cam_stack.layout().setAlignment(
            self.hud, Qt.AlignmentFlag.AlignCenter
        )

        hud_row = QHBoxLayout(); hud_row.setContentsMargins(0, 0, 0, 0)
        hud_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hud_row.addWidget(self._hud_cam_stack, alignment=Qt.AlignmentFlag.AlignCenter)
        self._hud_row = hud_row
        workspace_layout.addLayout(hud_row, stretch=1)
        root.addWidget(workspace, stretch=1)

        self._workspace = workspace
        self._focus_mode = False
        self._focus_animations = []
        self._focus_original_geometry = {}
        self._mini_mode = False
        self._mini_original_sizes = None
        self._system_scan_timer = None
        self._build_holographic_widgets()

        # Quick-access drawer (floating overlay, built after central widget layout is done)
        self._quick_drawer = self._build_quick_drawer()
        self._update_autostart_btn(self._check_autostart())
        from memory.config_manager import get_brief_enabled as _gbe
        self._update_brief_btn(_gbe())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metrik güncelleme timer'ı
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._content_sig.connect(self._show_content)
        self._file_preview_sig.connect(self._show_file_preview)
        self._hologram3d_sig.connect(self._show_3d_hologram)
        self._reconfig_sig.connect(self._show_setup)
        self._camera_sig.connect(self._show_camera_frame)
        self._cam_stream_sig.connect(self._on_cam_stream)
        self._clipboard_sig.connect(self._show_clipboard_panel)
        self._system_alert_sig.connect(self._show_system_alert)
        self._music_data_sig.connect(self._music_widget.set_track_data)
        self._system_scan_sig.connect(self.show_system_scan)
        self._ptt_status_sig.connect(self._on_ptt_status)
        self._service_status_sig.connect(self._service_status.set_status)
        self._audio_level_sig.connect(self.hud.set_audio_level)
        self._phone_connected_sig.connect(self.notify_phone_connected)
        self.set_service_status("GEMINI", "ready", "READY")
        self.set_service_status("GOOGLE", "ready", "TOKEN" if (BASE_DIR / "config" / "google_token.json").exists() else "SETUP")
        self.set_service_status("REMOTE", "off", "OFF")
        self._mini_mode_sig.connect(lambda mini: self.enter_mini_mode() if mini else self.restore_presentation())
        self._music_focus_sig.connect(self.show_music_widget)
        self._cam_stop = threading.Event()
        self._music_poll_busy = False
        self._music_poll_timer = QTimer(self)
        self._music_poll_timer.timeout.connect(self._poll_music_session)
        self._music_poll_timer.start(2000)
        self._poll_music_session()

        # Camera preview overlay (child of central widget, positioned in resizeEvent)
        self._cam_preview = _CameraPreview(self.centralWidget())

        # Clipboard panel (child of central widget, bottom-center)
        self._clipboard_panel = ClipboardPanel(self.centralWidget())
        self._clipboard_panel.action_requested.connect(self._on_clipboard_action)
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)

        self._overlay: SetupOverlay | None = None
        self._system_alert_overlay = None
        self._system_alert_timer = None
        self._boot_overlay = BootOverlay(self.centralWidget())
        self._boot_overlay.setGeometry(self.centralWidget().rect())
        self._boot_overlay.start()
        QTimer.singleShot(4200, self._boot_overlay.finish)
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_intr = QShortcut(QKeySequence("Escape"), self)
        sc_intr.activated.connect(self._do_interrupt)

    def _poll_music_session(self):
        if self._music_poll_busy or _OS != "Windows":
            return
        self._music_poll_busy = True
        threading.Thread(target=self._read_music_session, daemon=True).start()

    def _read_music_session(self):
        try:
            asyncio.run(self._read_music_session_async())
        except Exception as exc:
            print(f"[Music] Metadata unavailable: {exc}")
        finally:
            self._music_poll_busy = False

    async def _read_music_session_async(self):
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager,
        )
        from winrt.windows.storage.streams import DataReader

        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        session = manager.get_current_session()
        if session is None:
            sessions = manager.get_sessions()
            session = sessions[0] if sessions else None
        if session is None:
            self._media_active = False
            return

        try:
            playback = session.get_playback_info()
            self._media_active = "playing" in str(playback.playback_status).lower()
        except Exception:
            self._media_active = True

        properties = await session.try_get_media_properties_async()
        title = properties.title or "No track selected"
        artist = properties.artist or properties.album_artist or "Unknown artist"
        cover = b""
        thumbnail = properties.thumbnail
        if thumbnail:
            stream = await thumbnail.open_read_async()
            size = int(stream.size)
            if size:
                reader = DataReader(stream)
                await reader.load_async(size)
                buffer = bytearray(size)
                reader.read_bytes(buffer)
                cover = bytes(buffer)
                reader.close()
            stream.close()
        self._music_data_sig.emit(title, artist, cover)

    def _build_holographic_widgets(self):
        """Compose compact HUD widgets without changing their existing callbacks."""
        saved_positions = _read_full_config().get("widget_positions", {})
        metric_data = (
            ("CPU LOAD", self._bar_cpu),
            ("MEMORY", self._bar_mem),
            ("NETWORK", self._bar_net),
            ("GPU LOAD", self._bar_gpu),
            ("TEMPERATURE", self._bar_tmp),
        )
        self._metric_panels = []
        for title, bar in metric_data:
            panel = _FloatingPanel(title, self.centralWidget(), 190, 84)
            body = QVBoxLayout(panel._body)
            body.setContentsMargins(0, 0, 0, 0)
            bar.setParent(panel._body)
            bar.setFixedHeight(46)
            body.addWidget(bar)
            panel.show()
            self._metric_panels.append(panel)

        self._microphone_panel = _FloatingPanel(
            "MICROPHONE", self.centralWidget(), 150, 136
        )
        mic_layout = QVBoxLayout(self._microphone_panel._body)
        mic_layout.setContentsMargins(0, 0, 0, 0)
        mic_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mute_btn.setParent(self._microphone_panel._body)
        self._mute_btn.setFixedSize(72, 58)
        self._mute_btn.setToolTip("Toggle microphone")
        self._style_mute_btn()
        mic_layout.addWidget(self._mute_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self._ptt_status = QLabel("PTT OFF", self._microphone_panel._body)
        self._ptt_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ptt_status.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; font: 7px 'Courier New';")
        mic_layout.addWidget(self._ptt_status)
        self._microphone_panel.show()

        self._keyboard_btn = QPushButton("⌨", self.centralWidget())
        self._keyboard_btn.setFixedSize(44, 44)
        self._keyboard_btn.setToolTip("Open command input")
        self._keyboard_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._keyboard_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0, 13, 20, 220); color: {C.TEXT_MED};
                border: 1px solid {C.BORDER_B}; border-radius: 22px;
                font: 18px 'Segoe UI Symbol';
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI}; }}
        """)
        self._keyboard_btn.clicked.connect(self._toggle_command_bar)
        self._keyboard_btn.show()

        self._music_widget = MusicWidget(self.centralWidget())
        self._music_widget.show()
        self._reminder_widget = ReminderWidget(self.centralWidget())
        self._reminder_widget.hide()
        self._productivity_timer_widget = ProductivityTimerWidget(self.centralWidget())
        self._productivity_timer_widget.hide()
        self._system_scan_widget = SystemScanWidget(self.centralWidget())
        self._system_scan_widget.hide()
        self._reminder_sig.connect(self._show_reminder_widget)
        self._productivity_timer_sig.connect(self._show_productivity_timer)
        self._system_scan_transcript_sig.connect(self._system_scan_widget.advance_with_voice)
        self._reminder_timer = QTimer(self)
        self._reminder_timer.timeout.connect(self._poll_reminder_events)
        self._reminder_timer.start(1000)

        self._log_panel = _InternalLogPanel(self._log, self.centralWidget())
        saved_log_size = saved_positions.get("log_size", {})
        if saved_log_size:
            self._log_panel.resize(
                max(360, saved_log_size.get("width", self._log_panel.width())),
                max(250, saved_log_size.get("height", self._log_panel.height())),
            )
        self._log_panel.show()
        self._log_panel.enable_editing(True)

        command = QFrame(self._workspace)
        command.setObjectName("CommandBar")
        command.setFixedSize(650, 52)
        command.setStyleSheet(f"""
            QFrame#CommandBar {{
                background: rgba(9, 19, 24, 232);
                border: 1px solid {C.BORDER_B};
                border-radius: 9px;
            }}
        """)
        command_layout = QHBoxLayout(command)
        command_layout.setContentsMargins(8, 8, 8, 8)
        command_layout.setSpacing(6)

        file_btn = QPushButton("＋")
        file_btn.setFixedSize(34, 34)
        file_btn.setToolTip("Attach file for context")
        file_btn.clicked.connect(self._drop_zone._browse)
        file_btn.setStyleSheet(f"""
            QPushButton {{ color: {C.TEXT_MED}; background: transparent;
                border: 1px solid {C.BORDER}; border-radius: 5px; font-size: 18px; }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI}; }}
        """)
        command_layout.addWidget(file_btn)

        self._input.setParent(command)
        self._input.setFixedHeight(34)
        self._input.setStyleSheet(f"""
            QLineEdit {{ background: rgba(4, 10, 14, 190); color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 5px; padding: 4px 10px; }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        command_layout.addWidget(self._input, stretch=1)

        send = QPushButton("➜")
        send.setFixedSize(38, 34)
        send.setToolTip("Send command")
        send.clicked.connect(self._send)
        send.setStyleSheet(f"""
            QPushButton {{ background: {C.PRI}; color: {C.WHITE}; border: none; border-radius: 5px; font-size: 17px; }}
            QPushButton:hover {{ background: {C.WHITE}; color: {C.PRI}; }}
        """)
        command_layout.addWidget(send)
        self._command_bar = command
        self._command_bar.hide()

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 14)
        row.addStretch(); row.addWidget(command); row.addStretch()
        self._workspace.layout().addLayout(row)

        self._positioned_widgets = [
            *self._metric_panels, self._log_panel, self._microphone_panel,
            self._music_widget,
        ]
        for panel in self._positioned_widgets:
            if isinstance(panel, _FloatingPanel):
                panel.position_changed.connect(self._save_widget_positions)
        self._saved_widget_positions = saved_positions
        self._position_holographic_widgets()

    def _save_widget_positions(self):
        positions = {
            str(index): {"x": widget.x(), "y": widget.y()}
            for index, widget in enumerate(self._positioned_widgets)
        }
        positions["log_size"] = {
            "width": self._log_panel.width(),
            "height": self._log_panel.height(),
        }
        try:
            data = _read_full_config()
            data["widget_positions"] = positions
            API_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
        except Exception as e:
            self._log.append_log(f"ERR: Widget layout save failed — {e}")

    def _position_holographic_widgets(self):
        if not hasattr(self, "_metric_panels"):
            return
        cw = self.centralWidget()
        if getattr(self, "_mini_mode", False):
            self._hud_cam_stack.move(cw.width() - 310, cw.height() - 330)
            log_width = min(420, max(300, cw.width() // 3))
            log_height = min(210, max(150, cw.height() // 4))
            self._log_panel.setGeometry(
                max(12, min(self._log_panel.x(), cw.width() - log_width - 12)),
                cw.height() - log_height - 18,
                log_width, log_height,
            )
            self._microphone_panel.move(cw.width() - 142, cw.height() - 136)
            self._keyboard_btn.move(cw.width() - 62, cw.height() - 78)
            return
        hud_width = min(1000, max(560, cw.width() - 40))
        if self.hud.width() != hud_width:
            self.hud.setFixedWidth(hud_width)
        positions = (
            (28, 92),
            (225, 72),
            (28, max(350, cw.height() - 220)),
            (max(320, cw.width() - 520), 350),
            (max(320, cw.width() - 520), max(450, cw.height() - 220)),
        )
        defaults = [
            *positions,
            (max(28, cw.width() - 338), 86),
            (cw.width() // 2 - 78, max(86, cw.height() - 122)),
            (max(24, cw.width() // 2 - 170), 82),
        ]
        for index, (widget, (x, y)) in enumerate(zip(self._positioned_widgets, defaults)):
            saved = self._saved_widget_positions.get(str(index), {})
            # Migrate the old broken microphone position saved at the origin.
            if index == len(self._positioned_widgets) - 1 and saved.get("x") == 0 and saved.get("y") == 0:
                saved = {}
            x = saved.get("x", x)
            y = saved.get("y", y)
            widget.move(max(12, min(x, cw.width() - widget.width() - 12)),
                        max(12, min(y, cw.height() - widget.height() - 12)))
        self._keyboard_btn.move(
            max(12, (cw.width() - self._keyboard_btn.width()) // 2),
            max(86, cw.height() - 122),
        )
        self._content_panel.move(
            max(12, (cw.width() - self._content_panel.width()) // 2),
            max(12, cw.height() - self._content_panel.height() - 76),
        )
        self._save_widget_positions()

    def _toggle_command_bar(self):
        if self._command_bar.isVisible():
            self._command_bar.hide()
            self._keyboard_btn.setDown(False)
            return
        self._command_bar.show()
        self._command_bar.raise_()
        self._input.setFocus()
        self._keyboard_btn.setDown(True)

    def enter_mini_mode(self):
        """Animate the hologram into a small bottom-right control island."""
        if self._mini_mode:
            self._log_panel.show()
            self._log_panel.raise_()
            return
        if self._focus_mode:
            self._dismiss_content()
        self._mini_mode = True
        self._command_bar.hide()
        self._mini_original_sizes = (self._hud_cam_stack.size(), self.hud.size())
        self._mini_original_log_geometry = self._log_panel.geometry()
        for widget in (*self._metric_panels, self._music_widget):
            widget.hide()
        log_width = min(420, max(300, self.centralWidget().width() // 3))
        log_height = min(210, max(150, self.centralWidget().height() // 4))
        self._log_panel.setGeometry(
            18, self.centralWidget().height() - log_height - 18,
            log_width, log_height,
        )
        self._log_panel.show()
        self._log_panel.raise_()
        self._hud_row.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self._hud_cam_stack.setFixedSize(290, 290)
        self.hud.setFixedSize(270, 270)
        self._hud_cam_stack.move(
            self.centralWidget().width() - 310,
            self.centralWidget().height() - 330,
        )
        self._microphone_panel.move(self.centralWidget().width() - 142, self.centralWidget().height() - 136)
        self._keyboard_btn.move(self.centralWidget().width() - 62, self.centralWidget().height() - 78)
        self._mute_btn.show()
        self._keyboard_btn.show()
        self._hud_cam_stack.raise_()
        self._mute_btn.raise_()
        self._keyboard_btn.raise_()

    def restore_presentation(self):
        """Return from compact presentation mode to the normal workspace."""
        if not self._mini_mode:
            return
        self._mini_mode = False
        self._hud_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hud_cam_stack.setMinimumSize(0, 0)
        self._hud_cam_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if self._mini_original_sizes:
            self._hud_cam_stack.setFixedSize(self._mini_original_sizes[0])
            self.hud.setFixedSize(self._mini_original_sizes[1])
        if self._mini_original_log_geometry:
            self._log_panel.setGeometry(self._mini_original_log_geometry)
        self._mini_original_log_geometry = None
        for widget in (*self._metric_panels, self._log_panel, self._music_widget):
            widget.show()
        self._position_holographic_widgets()

    def show_system_scan(self, status: dict, resource: str = ""):
        """Open metric cards; each card is released by spoken output."""
        cw = self.centralWidget()
        column_x = min(cw.width() - self._system_scan_widget.width() - 24,
                       cw.width() // 2 + 180)
        target = QRect(
            max(12, column_x),
            max(72, (cw.height() - self._system_scan_widget.height()) // 2),
            self._system_scan_widget.width(), self._system_scan_widget.height(),
        )
        self._show_focus_widget(self._system_scan_widget, target)
        self._system_scan_widget.open_scan(status, resource)

    def advance_system_scan_with_voice(self, text: str):
        self._system_scan_transcript_sig.emit(text)

    def show_music_widget(self):
        """Bring the now-playing widget forward for a music-status request."""
        if self._mini_mode:
            self.restore_presentation()
        if self._focus_mode:
            self._dismiss_content()
        self._music_widget.show()
        self._music_widget.raise_()
        self._music_widget.setStyleSheet(self._music_widget.styleSheet())

    def _show_reminder_widget(self, message: str):
        target = QRect(
            max(12, self.centralWidget().width() - self._reminder_widget.width() - 24),
            86, self._reminder_widget.width(), self._reminder_widget.height(),
        )
        self._show_focus_widget(self._reminder_widget, target)
        self._reminder_widget.show_reminder(message)

    def _show_productivity_timer(self, kind: str):
        target = QRect(
            max(12, self.centralWidget().width() - self._productivity_timer_widget.width() - 24),
            max(90, self.centralWidget().height() - self._productivity_timer_widget.height() - 24),
            self._productivity_timer_widget.width(), self._productivity_timer_widget.height(),
        )
        self._show_focus_widget(self._productivity_timer_widget, target)
        self._productivity_timer_widget.open_timer(kind)

    def _show_focus_widget(self, widget: QWidget, target: QRect):
        """Show an informational widget using the same focus transition as search."""
        if self._focus_mode:
            self._dismiss_content()
        self._animate_search_focus()
        self._content_panel.hide()
        start = QRect(target.x(), target.y() + 42, target.width(), target.height())
        widget.setGeometry(start)
        widget.show()
        widget.raise_()
        animation = QPropertyAnimation(widget, b"geometry", self)
        animation.setDuration(320)
        animation.setStartValue(start)
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start()
        self._focus_animations.append(animation)

    def _poll_reminder_events(self):
        events_dir = Path.home() / ".jarvis" / "reminders" / "events"
        if not events_dir.exists():
            return
        for event_path in sorted(events_dir.glob("*.json")):
            if event_path.name == "history.json":
                continue
            try:
                data = json.loads(event_path.read_text(encoding="utf-8"))
                event_path.unlink(missing_ok=True)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            message = str(data.get("message", "Reminder")).strip()
            if message:
                self._reminder_sig.emit(message)
                if self.on_reminder:
                    self.on_reminder(message)

    def _show_camera_frame(self, img_bytes: bytes):
        """Slot — display camera preview overlay (main thread)."""
        self._cam_preview.show_frame(img_bytes)
        cw = self.centralWidget()
        pw = _CameraPreview._W
        ph = self._cam_preview.height()
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )

    # --- Live camera stream in HUD area ------------------------------------
    def _on_cam_stream(self, start: bool) -> None:
        # Camera stream is displayed through the existing camera preview overlay,
        # matching the visual style of the other widgets.
        if start:
            return
        else:
            self._cam_preview.hide()

    def start_camera_stream(self) -> None:
        self._cam_stop.clear()
        self._cam_stream_sig.emit(True)
        t = threading.Thread(target=self._cam_loop, daemon=True, name="cam-stream")
        t.start()

    def _cam_loop(self) -> None:
        try:
            import cv2
            from actions.camera_widget import camera_manager

            if not camera_manager.start_camera(camera_index=0, fps=15):
                print("[Camera] Failed to start camera manager")
                self._cam_stream_sig.emit(False)
                return

            print("[Camera] Camera stream started with detection")

            while not self._cam_stop.is_set():
                try:
                    frame_data = camera_manager.get_frame()
                    if frame_data and frame_data.get('frame') is not None:
                        frame = frame_data['frame'].copy()
                        faces = frame_data.get('faces', [])
                        persons = frame_data.get('persons', [])

                        # Resize frame to maintain a compact look consistent with the rest of the UI
                        h, w = frame.shape[:2]
                        if w > 480:
                            scale = 480 / w
                            new_w = 480
                            new_h = int(h * scale)
                            frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

                        # Draw detections on the image before emitting through the standard overlay widget.
                        for face in faces:
                            x, y, fw, fh = face['x'], face['y'], face['w'], face['h']
                            cv2.rectangle(frame, (x, y), (x + fw, y + fh), (0, 255, 0), 2)
                            cv2.putText(frame, "FACE", (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

                        for person in persons:
                            x, y, pw, ph = person['x'], person['y'], person['w'], person['h']
                            cv2.rectangle(frame, (x, y), (x + pw, y + ph), (255, 0, 0), 2)
                            cv2.putText(frame, "PERSON", (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)

                        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        self._camera_sig.emit(buf.tobytes())

                    self._cam_stop.wait(0.033)
                except Exception as e:
                    print(f"[Camera] Frame processing error: {e}")
                    self._cam_stop.wait(0.1)

            camera_manager.stop_camera()
        except Exception as e:
            print(f"[Camera] Stream error: {e}")
        finally:
            self._cam_stream_sig.emit(False)

    def stop_camera_stream(self) -> None:
        self._cam_stop.set()

    # ------------------------------------------------------------------
    # Icon generation — arc-reactor style, rendered with Pillow
    # ------------------------------------------------------------------
    @staticmethod
    def _build_jarvis_icon(out_path: Path) -> bool:
        """
        Render a JARVIS arc-reactor icon at 4× resolution and downsample
        for crisp results at all sizes. Saves a multi-res .ico to out_path.
        Returns True on success.
        """
        try:
            import math
            import PIL.Image
            import PIL.ImageDraw
            import PIL.ImageFilter
        except ImportError:
            return False

        CYAN   = (0, 212, 255)
        DIM    = (0, 100, 140)
        DARK   = (0, 6, 10)
        GLOW   = (0, 160, 200)
        WHITE  = (220, 240, 255)

        def _render(sz: int) -> PIL.Image.Image:
            S  = sz * 4                     # draw at 4× then downscale
            img = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d   = PIL.ImageDraw.Draw(img)
            cx = cy = S // 2

            # ── filled background circle ──────────────────────────────────
            R = S // 2 - 2
            d.ellipse([cx-R, cy-R, cx+R, cy+R], fill=(*DARK, 255))

            # ── outer border ring ─────────────────────────────────────────
            lw = max(2, S // 40)
            d.ellipse([cx-R, cy-R, cx+R, cy+R],
                      outline=(*CYAN, 220), width=lw)

            # ── mid decorative ring ───────────────────────────────────────
            R2 = int(R * 0.72)
            d.ellipse([cx-R2, cy-R2, cx+R2, cy+R2],
                      outline=(*DIM, 180), width=max(1, lw // 2))

            # ── 6 radial spokes (hex bolt) ────────────────────────────────
            R_inner = int(R * 0.30)
            R_outer = int(R * 0.62)
            spoke_w = max(1, S // 80)
            for i in range(6):
                angle = math.radians(i * 60 - 30)
                x1 = cx + int(R_inner * math.cos(angle))
                y1 = cy + int(R_inner * math.sin(angle))
                x2 = cx + int(R_outer * math.cos(angle))
                y2 = cy + int(R_outer * math.sin(angle))
                d.line([x1, y1, x2, y2], fill=(*GLOW, 200), width=spoke_w)

            # ── 6 tick marks on outer ring ────────────────────────────────
            for i in range(6):
                angle = math.radians(i * 60)
                for dr in range(lw * 2):
                    rx = (R - lw - dr)
                    d.point(
                        [cx + int(rx * math.cos(angle)),
                         cy + int(rx * math.sin(angle))],
                        fill=(*WHITE, 220),
                    )

            # ── inner glowing ring ────────────────────────────────────────
            Ri = int(R * 0.26)
            d.ellipse([cx-Ri, cy-Ri, cx+Ri, cy+Ri],
                      outline=(*CYAN, 255), width=max(2, lw))

            # ── bright glow soft blur applied before core ─────────────────
            # (draw a slightly larger cyan circle on a separate layer)
            glow_layer = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = PIL.ImageDraw.Draw(glow_layer)
            Rc = int(R * 0.13)
            gd.ellipse([cx-Rc*2, cy-Rc*2, cx+Rc*2, cy+Rc*2],
                       fill=(*CYAN, 110))
            glow_layer = glow_layer.filter(PIL.ImageFilter.GaussianBlur(S // 14))
            img = PIL.Image.alpha_composite(img, glow_layer)
            d   = PIL.ImageDraw.Draw(img)

            # ── core dot ──────────────────────────────────────────────────
            d.ellipse([cx-Rc, cy-Rc, cx+Rc, cy+Rc], fill=(*WHITE, 255))

            # ── downscale to target size ──────────────────────────────────
            return img.resize((sz, sz), PIL.Image.LANCZOS)

        try:
            sizes  = [256, 128, 64, 48, 32, 16]
            frames = [_render(s) for s in sizes]
            frames[0].save(
                out_path,
                format="ICO",
                append_images=frames[1:],
                sizes=[(s, s) for s in sizes],
            )
            return True
        except Exception as e:
            print(f"[Shortcut] ⚠️  Icon generation failed: {e}")
            return False

    @staticmethod
    def _create_lnk_windows(lnk: str, target: str, args: str,
                             work_dir: str, icon_loc: str) -> None:
        """
        Create a Windows .lnk shortcut WITHOUT launching PowerShell or cmd.
        Tries win32com (pywin32) first; falls back to wscript.exe + VBScript.
        wscript.exe is a GUI-mode host — it never opens a console window.
        """
        # ── Option 1: pywin32 (pure Python COM, zero subprocess) ──────────
        try:
            from win32com.client import Dispatch   # type: ignore
            sh = Dispatch("WScript.Shell")
            sc = sh.CreateShortCut(lnk)
            sc.TargetPath       = target
            sc.Arguments        = f'"{args}"'
            sc.WorkingDirectory = work_dir
            sc.Description      = "J.A.R.V.I.S AI Assistant"
            sc.IconLocation     = icon_loc
            sc.save()
            return
        except ImportError:
            pass

        # ── Option 2: wscript.exe + VBScript (always available on Windows,
        #    GUI-mode executable — never opens a console window) ────────────
        vbs = "\n".join([
            'Set ws = CreateObject("WScript.Shell")',
            f'Set sc = ws.CreateShortcut("{lnk}")',
            f'sc.TargetPath = "{target}"',
            f'sc.Arguments = Chr(34) & "{args}" & Chr(34)',
            f'sc.WorkingDirectory = "{work_dir}"',
            'sc.Description = "J.A.R.V.I.S AI Assistant"',
            f'sc.IconLocation = "{icon_loc}"',
            'sc.Save',
        ])
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".vbs")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(vbs)
            proc = subprocess.Popen(
                ["wscript.exe", "/nologo", tmp],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
            proc.wait(timeout=10)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    @staticmethod
    def _get_desktop_dir() -> Path:
        """
        Resolve the user's REAL desktop directory instead of assuming
        ~/Desktop, which breaks when:
          • OneDrive "Known Folder Move" relocates the desktop
            (C:/Users/x/OneDrive/Desktop) — very common on Win 10/11;
          • the XDG desktop is localized on Linux (~/Masaüstü,
            ~/Schreibtisch, ~/Bureau, …).
        Falls back to ~/Desktop only as a last resort.
        """
        home = Path.home()
        _os = platform.system()

        if _os == "Windows":
            # ── 1) SHGetKnownFolderPath(FOLDERID_Desktop) — the canonical
            #       answer; follows OneDrive redirection. No dependencies. ──
            try:
                import ctypes
                from ctypes import wintypes

                class _GUID(ctypes.Structure):
                    _fields_ = [("Data1", wintypes.DWORD),
                                ("Data2", wintypes.WORD),
                                ("Data3", wintypes.WORD),
                                ("Data4", ctypes.c_ubyte * 8)]

                # FOLDERID_Desktop {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
                fid = _GUID(0xB4BFCC3A, 0xDB2C, 0x424C,
                            (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9,
                                                 0x9A, 0x87, 0xC6, 0x41))
                buf = ctypes.c_wchar_p()
                if ctypes.windll.shell32.SHGetKnownFolderPath(
                        ctypes.byref(fid), 0, None, ctypes.byref(buf)) == 0:
                    p = Path(buf.value)
                    ctypes.windll.ole32.CoTaskMemFree(buf)
                    if p.is_dir():
                        return p
            except Exception:
                pass

            # ── 2) Registry: User Shell Folders (may contain %VARS%) ──────
            try:
                import winreg
                with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion"
                        r"\Explorer\User Shell Folders") as key:
                    val, _t = winreg.QueryValueEx(key, "Desktop")
                p = Path(os.path.expandvars(val))
                if p.is_dir():
                    return p
            except Exception:
                pass

        elif _os == "Linux":
            # ── xdg-user-dir honours localized names (~/Masaüstü, …) ──────
            try:
                out = subprocess.run(["xdg-user-dir", "DESKTOP"],
                                     capture_output=True, text=True, timeout=5)
                p = Path(out.stdout.strip())
                if out.stdout.strip() and p != home and p.is_dir():
                    return p
            except Exception:
                pass
            try:
                cfg = home / ".config" / "user-dirs.dirs"
                for line in cfg.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("XDG_DESKTOP_DIR"):
                        val = line.split("=", 1)[1].strip().strip('"')
                        p = Path(val.replace("$HOME", str(home)))
                        if p != home and p.is_dir():
                            return p
            except Exception:
                pass

        # macOS: ~/Desktop is always the real path (localization is
        # display-only). Everything else lands here as a last resort.
        return home / "Desktop"

    def _create_desktop_shortcut(self):
        """
        Create a desktop shortcut on Windows / macOS / Linux.
        Never opens a terminal, console, or PowerShell window on any platform.
        """
        import stat as _stat
        script  = Path(__file__).resolve().parent / "main.py"
        python  = Path(sys.executable)
        desktop = self._get_desktop_dir()

        # Arc-reactor icon (.ico — also exported as .png for Linux/macOS)
        ico_path = Path(__file__).resolve().parent / "config" / "jarvis.ico"
        if not ico_path.exists():
            self._build_jarvis_icon(ico_path)

        try:
            _os = platform.system()

            # ── Windows ───────────────────────────────────────────────────────
            if _os == "Windows":
                pythonw  = python.parent / "pythonw.exe"
                target   = str(pythonw if pythonw.exists() else python)
                lnk      = str(desktop / "J.A.R.V.I.S.lnk")
                icon_loc = str(ico_path) if ico_path.exists() else f"{target},0"
                self._create_lnk_windows(lnk, target, str(script),
                                         str(script.parent), icon_loc)

            # ── macOS — proper .app bundle (no Terminal window) ───────────────
            elif _os == "Darwin":
                app     = desktop / "J.A.R.V.I.S.app"
                mac_dir = app / "Contents" / "MacOS"
                res_dir = app / "Contents" / "Resources"
                mac_dir.mkdir(parents=True, exist_ok=True)
                res_dir.mkdir(exist_ok=True)

                # Launcher executable (bash — runs as background process,
                # macOS does NOT open Terminal for executables inside .app bundles)
                launcher = mac_dir / "JARVIS"
                launcher.write_text(
                    "#!/usr/bin/env bash\n"
                    f'cd "{script.parent}"\n'
                    f'exec "{python}" "{script}"\n'
                )
                launcher.chmod(launcher.stat().st_mode
                               | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

                # Minimal Info.plist (required for .app recognition)
                (app / "Contents" / "Info.plist").write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>\n'
                    '  <key>CFBundleExecutable</key><string>JARVIS</string>\n'
                    '  <key>CFBundleIdentifier</key>'
                    '<string>com.jarvis.assistant</string>\n'
                    '  <key>CFBundleName</key><string>J.A.R.V.I.S</string>\n'
                    '  <key>CFBundlePackageType</key><string>APPL</string>\n'
                    '  <key>CFBundleVersion</key><string>1.0</string>\n'
                    '</dict></plist>\n'
                )

                # Optional: copy icon as .icns (skip silently if Pillow is missing)
                try:
                    import PIL.Image
                    icns = res_dir / "AppIcon.icns"
                    PIL.Image.open(ico_path).save(icns, format="ICNS")
                    # Inject icon reference into plist
                    plist = app / "Contents" / "Info.plist"
                    txt = plist.read_text()
                    plist.write_text(
                        txt.replace(
                            '</dict></plist>',
                            '  <key>CFBundleIconFile</key>'
                            '<string>AppIcon</string>\n</dict></plist>\n',
                        )
                    )
                except Exception:
                    pass  # icon is optional

            # ── Linux — .desktop file (Terminal=false, no console) ────────────
            else:
                # Export .ico → .png for better desktop integration
                png_path = ico_path.with_suffix(".png")
                if not png_path.exists() and ico_path.exists():
                    try:
                        import PIL.Image
                        PIL.Image.open(ico_path).resize(
                            (256, 256), PIL.Image.LANCZOS
                        ).save(png_path, format="PNG")
                    except Exception:
                        png_path = ico_path  # fallback to .ico

                icon_line = f"Icon={png_path}\n" if png_path.exists() else ""
                desk = desktop / "J.A.R.V.I.S.desktop"
                desk.write_text(
                    "[Desktop Entry]\n"
                    "Name=J.A.R.V.I.S\n"
                    f"Exec={python} {script}\n"
                    f"Path={script.parent}\n"
                    "Type=Application\n"
                    "Terminal=false\n"
                    "Categories=Utility;\n"
                    + icon_line
                )
                desk.chmod(desk.stat().st_mode | 0o755)

            self._log.append_log("SYS: Desktop shortcut created.")
        except Exception as e:
            self._log.append_log(f"ERR: Shortcut failed — {e}")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self.centralWidget()
        if hasattr(self, "_boot_overlay"):
            self._boot_overlay.setGeometry(cw.rect())
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._remote_overlay and self._remote_overlay.isVisible():
            ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
            self._remote_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._customize_overlay and self._customize_overlay.isVisible():
            ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
            self._customize_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        # Camera preview — bottom-right corner of the center/HUD area
        pw = _CameraPreview._W
        ph = self._cam_preview.height() or _CameraPreview._H
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )
        # Clipboard panel — bottom-center
        if hasattr(self, '_clipboard_panel') and self._clipboard_panel.isVisible():
            self._position_clipboard_panel()
        # Quick drawer — reposition if open
        if hasattr(self, '_quick_drawer') and self._quick_drawer.isVisible():
            self._position_quick_drawer()
        if hasattr(self, '_metric_panels'):
            self._position_holographic_widgets()
        if hasattr(self, '_hologram3d') and self._hologram3d.isVisible():
            self._hologram3d.setGeometry(
                max(20, (cw.width() - 900) // 2),
                max(60, (cw.height() - 560) // 2),
                min(900, cw.width() - 40),
                min(560, cw.height() - 80),
            )
        previews = getattr(self, '_file_previews', [])
        for preview in list(previews):
            if preview and preview.isVisible():
                preview.setGeometry(
                    max(20, preview.x()),
                    max(20, preview.y()),
                    preview.width(),
                    preview.height(),
                )

    def _update_metrics(self):
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bar_gpu.set_value(0, "N/A")

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(54)
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        w.setStyleSheet(f"background: transparent; border-bottom: 1px solid {C.BORDER_B};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 8))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_badge("MARK LI", C.PRI_DIM))
        lay.addSpacing(8)
        self._drawer_btn = QPushButton("⚙")
        self._drawer_btn.setFixedSize(26, 26)
        self._drawer_btn.setFont(QFont("Courier New", 11))
        self._drawer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drawer_btn.setToolTip("Settings & Controls")
        self._drawer_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 4px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI_DIM}; }}
            QPushButton:checked {{ color: {C.PRI}; border-color: {C.PRI}; background: {C.PRI_GHO}; }}
        """)
        self._drawer_btn.setCheckable(True)
        self._drawer_btn.clicked.connect(self._toggle_drawer)
        lay.addWidget(self._drawer_btn)

        lay.addSpacing(8)
        self._mic_indicator = MicrophoneStatusIndicator()
        self._mic_status_sig.connect(self._mic_indicator.set_status)
        lay.addWidget(self._mic_indicator)
        self._header_state = _badge("● INIT", C.ACC2)
        self._header_state.setObjectName("HeaderState")
        lay.addWidget(self._header_state)

        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(1)
        _disp = self._assistant_name.upper()
        self._title_lbl = QLabel(_disp)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        mid.addWidget(self._title_lbl)
        _sub_text = ("Just A Rather Very Intelligent System"
                     if _disp in ("JARVIS", "J.A.R.V.I.S")
                     else "Personal AI Assistant")
        self._sub_lbl = QLabel(_sub_text)
        self._sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_lbl.setFont(QFont("Courier New", 7))
        self._sub_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        mid.addWidget(self._sub_lbl)
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout(); right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Courier New", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        self._session_badge = QLabel("SECURE LINK  ·  LIVE")
        self._session_badge.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        self._session_badge.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
        self._session_badge.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._session_badge)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-right: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(6)

        hdr = QLabel("◈ SYS MONITOR")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)
        lay.addSpacing(2)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("MEM", C.ACC2)
        self._bar_net = MetricBar("NET", C.GREEN)
        self._bar_gpu = MetricBar("GPU", C.ACC)
        self._bar_tmp = MetricBar("TMP", "#ff6688")

        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        lay.addSpacing(4)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 4px;"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 5, 6, 5)
        ip_lay.setSpacing(3)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont("Courier New", 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addSpacing(4)

        lay.addStretch()

        for txt, col in [
            ("AI CORE\nACTIVE",  C.GREEN),
            ("SEC\nCLEARED",     C.PRI),
            ("PROTOCOL\nXLIX",   C.TEXT_DIM),
        ]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {col}; background: {C.PANEL2};"
                f"border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 4px;"
            )
            lay.addWidget(lbl)

        return w
    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-left: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        def _sec(txt):
            l = QLabel(f"▸ {txt}")
            l.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            return l

        lay.addWidget(_sec("ACTIVITY LOG"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_sec("FILE UPLOAD"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded — drop or click above to upload")
        self._file_hint.setFont(QFont("Courier New", 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_sec("COMMAND INPUT"))
        lay.addLayout(self._build_input_row())

        self._interrupt_btn = QPushButton("✋  INTERRUPT  [ESC]")
        self._interrupt_btn.setFixedHeight(34)
        self._interrupt_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._interrupt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._interrupt_btn.setStyleSheet(f"""
            QPushButton {{
                background: #140008; color: {C.MUTED_C};
                border: 1px solid {C.MUTED_C}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: #200010; border: 1px solid #ff6688;
            }}
            QPushButton:pressed {{
                background: #300018;
            }}
        """)
        self._interrupt_btn.clicked.connect(self._do_interrupt)
        lay.addWidget(self._interrupt_btn)

        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        return w

    def _build_quick_drawer(self) -> QWidget:
        """Floating overlay panel shown when the ⚙ header button is toggled."""
        _BTN_STYLE_PRI = f"""
            QPushButton {{
                background: #00091a; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
                text-align: left; padding: 0 8px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
        """
        _BTN_STYLE_DIM = f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
                text-align: left; padding: 0 8px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}
        """

        w = QWidget(self.centralWidget())
        w.setObjectName("QuickDrawer")
        w.setStyleSheet(f"""
            QWidget#QuickDrawer {{
                background: {C.DARK};
                border: 1px solid {C.BORDER_B};
                border-top: none;
                border-radius: 0 0 6px 6px;
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(5)

        hdr = QLabel("◈ CONTROLS")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)

        remote_btn = QPushButton("◉  REMOTE CONTROL")
        remote_btn.setFixedHeight(30)
        remote_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        remote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remote_btn.setStyleSheet(_BTN_STYLE_PRI)
        remote_btn.clicked.connect(self._open_remote)
        lay.addWidget(remote_btn)

        sc_btn = QPushButton("⊞  CREATE DESKTOP SHORTCUT")
        sc_btn.setFixedHeight(26)
        sc_btn.setFont(QFont("Courier New", 7))
        sc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sc_btn.setStyleSheet(_BTN_STYLE_DIM)
        sc_btn.clicked.connect(self._create_desktop_shortcut)
        lay.addWidget(sc_btn)

        self._autostart_btn = QPushButton("◉  AUTO-START: OFF")
        self._autostart_btn.setFixedHeight(26)
        self._autostart_btn.setFont(QFont("Courier New", 7))
        self._autostart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._autostart_btn.clicked.connect(self._toggle_autostart)
        lay.addWidget(self._autostart_btn)

        restart_btn = QPushButton("↻  RESTART ASSISTANT")
        restart_btn.setFixedHeight(26)
        restart_btn.setFont(QFont("Courier New", 7))
        restart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restart_btn.setStyleSheet(_BTN_STYLE_DIM)
        restart_btn.clicked.connect(self._restart_assistant)
        lay.addWidget(restart_btn)
        reset_btn = QPushButton("⌫  RESET CONVERSATION CONTEXT")
        reset_btn.setFixedHeight(26)
        reset_btn.setFont(QFont("Courier New", 7))
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.ACC};
                border: 1px solid {C.ACC}; border-radius: 3px; text-align: left; padding: 0 8px; }}
            QPushButton:hover {{ background: rgba(255,107,0,35); }}
        """)
        reset_btn.clicked.connect(self._reset_context)
        lay.addWidget(reset_btn)

        cust_btn = QPushButton("⚙  CUSTOMISE ASSISTANT")
        cust_btn.setFixedHeight(26)
        cust_btn.setFont(QFont("Courier New", 7))
        cust_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cust_btn.setStyleSheet(_BTN_STYLE_DIM)
        cust_btn.clicked.connect(self._open_customize)
        lay.addWidget(cust_btn)

        self._visual_mode_btn = QPushButton()
        self._visual_mode_btn.setFixedHeight(26)
        self._visual_mode_btn.setFont(QFont("Courier New", 7))
        self._visual_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._visual_mode_btn.setStyleSheet(_BTN_STYLE_DIM)
        self._visual_mode_btn.clicked.connect(self._cycle_visual_mode)
        lay.addWidget(self._visual_mode_btn)
        self._refresh_visual_mode_btn()

        audio_btn = QPushButton("♪  AUDIO SETTINGS")
        audio_btn.setFixedHeight(26)
        audio_btn.setFont(QFont("Courier New", 7))
        audio_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        audio_btn.setStyleSheet(_BTN_STYLE_DIM)
        audio_btn.clicked.connect(self._open_audio_settings)
        lay.addWidget(audio_btn)

        sessions_btn = QPushButton("◈  WORK SESSIONS")
        sessions_btn.setFixedHeight(26)
        sessions_btn.setFont(QFont("Courier New", 7))
        sessions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sessions_btn.setStyleSheet(_BTN_STYLE_DIM)
        sessions_btn.clicked.connect(self._open_sessions)
        lay.addWidget(sessions_btn)

        self._brief_btn = QPushButton()
        self._brief_btn.setFixedHeight(26)
        self._brief_btn.setFont(QFont("Courier New", 7))
        self._brief_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._brief_btn.clicked.connect(self._toggle_brief)
        lay.addWidget(self._brief_btn)

        plugin_btn = QPushButton("🧩  PLUGINS")
        plugin_btn.setFixedHeight(26)
        plugin_btn.setFont(QFont("Courier New", 7))
        plugin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        plugin_btn.setStyleSheet(_BTN_STYLE_DIM)
        plugin_btn.clicked.connect(self._open_plugin_manager)
        lay.addWidget(plugin_btn)

        w.adjustSize()
        return w

    def _restart_assistant(self):
        """Restart the same Jarvis process from the UI without hand-closing and reopening."""
        if self.on_restart:
            self.on_restart()

    def _reset_context(self):
        answer = QMessageBox.question(
            self,
            "Reset conversation context",
            "Clear the current conversation and start a fresh Gemini session?\n\n"
            "Long-term memory, work sessions, settings and Google access will not be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes and self.on_reset_context:
            self.on_reset_context()
            return
        try:
            self._quick_drawer.hide()
        except Exception:
            pass
        try:
            self.hide()
        except Exception:
            pass

        try:
            target = BASE_DIR / "main.py"
            command = [sys.executable, str(target)] + sys.argv[1:]
            startup = {"cwd": str(BASE_DIR)}
            if platform.system() == "Windows":
                startup["creationflags"] = subprocess.CREATE_NO_WINDOW
            subprocess.Popen(command, **startup)
        except Exception as exc:
            print(f"[UI] restart failed: {exc}")

        app = QApplication.instance()
        if app:
            app.quit()

    def _toggle_drawer(self, checked: bool):
        if checked:
            self._position_quick_drawer()
            self._quick_drawer.show()
            self._quick_drawer.raise_()
        else:
            self._quick_drawer.hide()

    def _position_quick_drawer(self):
        if not hasattr(self, '_quick_drawer'):
            return
        _W = 220
        self._quick_drawer.setFixedWidth(_W)
        self._quick_drawer.adjustSize()
        self._quick_drawer.setGeometry(12, 54, _W, self._quick_drawer.sizeHint().height())

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d14; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_content_panel(self) -> QWidget:
        """
        Collapsible panel below the HUD — shows search results, news, briefings.
        Hidden by default; appears when show_content() is called.
        """
        w = QWidget()
        w.setObjectName("ContentPanel")
        w.setStyleSheet(f"""
            QWidget#ContentPanel {{
                background: {C.PANEL};
                border-top: 1px solid {C.BORDER_B};
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 7, 12, 8)
        lay.setSpacing(5)

        # ── header row ───────────────────────────────────────────────────────
        hdr = QHBoxLayout(); hdr.setSpacing(6)

        dot = QLabel("◈")
        dot.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(dot)

        self._content_title_lbl = QLabel("BRIEFING")
        self._content_title_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._content_title_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent; letter-spacing: 1px;"
        )
        hdr.addWidget(self._content_title_lbl)
        hdr.addStretch()

        self._content_ts_lbl = QLabel("")
        self._content_ts_lbl.setFont(QFont("Courier New", 7))
        self._content_ts_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        hdr.addWidget(self._content_ts_lbl)

        dismiss = QPushButton("DISMISS  ✕")
        dismiss.setFont(QFont("Courier New", 7))
        dismiss.setFixedHeight(18)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 2px; padding: 0 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        dismiss.clicked.connect(self._dismiss_content)
        hdr.addWidget(dismiss)
        lay.addLayout(hdr)

        # ── separator ─────────────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep)

        # ── text display ──────────────────────────────────────────────────────
        self._content_display = QTextEdit()
        self._content_display.setReadOnly(True)
        self._content_display.setFont(QFont("Courier New", 8))
        self._content_display.setMinimumHeight(60)
        self._content_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._content_display.setStyleSheet(f"""
            QTextEdit {{
                background: {C.DARK};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 3px;
                padding: 6px 8px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG}; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 3px; min-height: 16px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; border: none;
            }}
        """)
        lay.addWidget(self._content_display)

        return w

    def _show_content(self, title: str, text: str):
        """Slot — runs on Qt main thread. Updates and shows the content panel."""
        import time as _time
        self._content_title_lbl.setText(title.upper()[:48])
        self._content_ts_lbl.setText(_time.strftime("%H:%M:%S"))
        self._content_display.setPlainText(text)
        self._content_display.moveCursor(
            self._content_display.textCursor().MoveOperation.Start
        )
        first_show = not self._content_panel.isVisible()
        self._content_panel.show()
        self._content_panel.raise_()
        if first_show:
            self._content_panel.setMinimumHeight(180)
            self._animate_search_focus()

    def _show_file_preview(self, path: str):
        """Open a holographic file preview instead of launching the OS default app."""
        if not path:
            return
        target = Path(path).expanduser()
        if target.exists() and target.is_dir():
            self._show_folder_preview(str(target.resolve()))
            return
        if not target.exists():
            return
        if self._focus_mode:
            self._dismiss_content()

        preview = HolographicFilePreview(self.centralWidget())
        preview.setGeometry(
            max(20, ((self.centralWidget().width() - 620) // 2) + len(self._file_previews) * 26),
            max(70, ((self.centralWidget().height() - 420) // 2) + len(self._file_previews) * 22),
            620,
            420,
        )
        preview.show_path(path)
        preview.show()
        preview.raise_()

        for existing in self._file_previews:
            existing._set_active_state(existing is preview)

        for idx, existing in enumerate(self._file_previews):
            if existing is preview:
                continue
            existing._apply_stack_offset(idx % 4)

        preview._apply_stack_offset(0)

        def _remove_preview(*_):
            if preview in self._file_previews:
                self._file_previews.remove(preview)

        preview.destroyed.connect(_remove_preview)
        self._file_previews.append(preview)
        self._file_preview = preview

        for idx, existing in enumerate(self._file_previews):
            if existing is preview:
                continue
            existing._apply_stack_offset(min(3, idx))

        preview._apply_stack_offset(0)

        if self._file_previews:
            for idx, existing in enumerate(self._file_previews):
                if idx == len(self._file_previews) - 1:
                    existing._apply_stack_offset(0)
                else:
                    existing._apply_stack_offset(min(3, idx + 1))

        preview.raise_()

        # snap to edge if the preview is too close to a border
        geo = preview.geometry()
        if geo.x() < 20:
            preview.move(20, geo.y())
        if geo.y() < 60:
            preview.move(geo.x(), 60)
        if geo.x() + geo.width() > self.centralWidget().width() - 20:
            preview.move(self.centralWidget().width() - geo.width() - 20, geo.y())
        if geo.y() + geo.height() > self.centralWidget().height() - 20:
            preview.move(geo.x(), self.centralWidget().height() - geo.height() - 20)

    def _show_3d_hologram(self, description: str, model_path: str = ""):
        """Show a procedural interactive 3D object directly over the HUD."""
        cw = self.centralWidget()
        self._hologram3d.setGeometry(
            max(20, (cw.width() - 900) // 2),
            max(60, (cw.height() - 560) // 2),
            min(900, cw.width() - 40),
            min(560, cw.height() - 80),
        )
        self._hologram3d.show_model(description, model_path)

    def _show_folder_preview(self, path: str):
        """Open a navigable folder panel without closing existing previews."""
        folder = Path(path).expanduser().resolve()
        if not folder.is_dir():
            return
        if self._focus_mode:
            self._dismiss_content()
        preview = HolographicFolderPreview(self.centralWidget())
        preview.setGeometry(
            max(20, ((self.centralWidget().width() - 430) // 2) + len(self._file_previews) * 26),
            max(70, ((self.centralWidget().height() - 420) // 2) + len(self._file_previews) * 22),
            430, 420,
        )
        preview.show_path(str(folder))
        preview.item_opened.connect(self._show_file_preview)
        preview.show()
        preview.raise_()
        preview.destroyed.connect(
            lambda *_: self._file_previews.remove(preview)
            if preview in self._file_previews else None
        )
        self._file_previews.append(preview)
        self._file_preview = preview
        for index, existing in enumerate(self._file_previews):
            existing._set_active_state(existing is preview)
            existing._apply_stack_offset(0 if existing is preview else min(3, index + 1))

    def _show_system_alert(self, text: str):
        """Flash a full-window warning before opening the alert in focus mode."""
        if self._focus_mode:
            self._dismiss_content()

        if self._system_alert_overlay:
            self._system_alert_overlay.deleteLater()

        overlay = QFrame(self.centralWidget())
        overlay.setGeometry(self.centralWidget().rect())
        overlay.setStyleSheet("background: rgba(150, 0, 18, 205);")
        overlay.raise_()

        layout = QVBoxLayout(overlay)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("⚠")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"color: {C.WHITE}; background: transparent; font: 72px 'Segoe UI Symbol';"
        )
        title = QLabel("SYSTEM ALERT")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {C.WHITE}; background: transparent; font: 700 20px 'Courier New';"
        )
        detail = QLabel(text.replace("[SYSTEM_ALERT]", "").strip())
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        detail.setMaximumWidth(720)
        detail.setStyleSheet(
            f"color: {C.WHITE}; background: transparent; font: 12px 'Courier New';"
        )
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addSpacing(10)
        layout.addWidget(detail)
        overlay.show()
        self._system_alert_overlay = overlay

        flashes = {"count": 0}
        timer = QTimer(self)
        self._system_alert_timer = timer

        def flash():
            flashes["count"] += 1
            overlay.setStyleSheet(
                "background: rgba(220, 0, 24, 225);"
                if flashes["count"] % 2 else "background: rgba(80, 0, 10, 185);"
            )
            if flashes["count"] >= 6:
                timer.stop()
                overlay.hide()
                overlay.deleteLater()
                self._system_alert_overlay = None
                self._system_alert_timer = None
                self._show_alert_panel(text)

        timer.timeout.connect(flash)
        timer.start(120)

    def _show_alert_panel(self, text: str):
        """Show a large dedicated alert display after the warning flash."""
        self._animate_search_focus(hud_offset=-420)
        if hasattr(self, "_alert_panel") and self._alert_panel:
            self._alert_panel.deleteLater()

        cw = self.centralWidget()
        panel = QFrame(cw)
        panel.setObjectName("SystemAlertPanel")
        panel.setStyleSheet(f"""
            QFrame#SystemAlertPanel {{
                background: rgba(32, 4, 10, 244);
                border: 2px solid {C.RED};
                border-radius: 12px;
            }}
            QLabel {{ background: transparent; color: {C.WHITE}; }}
        """)
        panel.setGeometry(
            max(20, cw.width() - min(680, cw.width() - 40) - 32),
            max(70, (cw.height() - 470) // 2),
            min(680, cw.width() - 40),
            min(470, cw.height() - 110),
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(38, 28, 38, 28)
        layout.setSpacing(8)

        header = QHBoxLayout()
        status = QLabel("●  CRITICAL SYSTEM WARNING")
        status.setStyleSheet(f"color: {C.RED}; font: 700 13px 'Courier New';")
        header.addWidget(status)
        header.addStretch()
        close = QPushButton("CLOSE")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(f"""
            QPushButton {{ color: {C.TEXT_MED}; background: transparent;
                border: 1px solid {C.BORDER_B}; border-radius: 4px; padding: 5px 12px; }}
            QPushButton:hover {{ color: {C.WHITE}; border-color: {C.RED}; }}
        """)
        close.clicked.connect(self._dismiss_alert)
        header.addWidget(close)
        layout.addLayout(header)

        icon = QLabel("⚠")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"color: {C.RED}; font: 92px 'Segoe UI Symbol';")
        layout.addWidget(icon)

        resource = "SYSTEM RESOURCE"
        value = "CRITICAL"
        lowered = text.lower()
        for key, label in (("ram", "RAM MEMORY"), ("cpu", "CPU LOAD"),
                           ("temperature", "CPU TEMPERATURE"), ("gpu", "GPU LOAD")):
            if key in lowered:
                resource = label
                break
        match = re.search(
            r"(?:at|is)\s+(\d+(?:\.\d+)?%|\d+(?:\.\d+)?\s*(?:°|º)?c)",
            lowered,
        )
        if match:
            value = match.group(1).upper()

        resource_label = QLabel(resource)
        resource_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        resource_label.setStyleSheet(f"color: {C.TEXT_MED}; font: 700 16px 'Courier New'; letter-spacing: 2px;")
        layout.addWidget(resource_label)
        value_label = QLabel(value)
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setStyleSheet(f"color: {C.RED}; font: 700 58px 'Courier New';")
        layout.addWidget(value_label)
        detail = QLabel(text.replace("[SYSTEM_ALERT]", "").strip())
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        detail.setStyleSheet(f"color: {C.WHITE}; font: 13px 'Courier New';")
        layout.addWidget(detail)
        panel.show()
        panel.raise_()
        self._alert_panel = panel

    def _dismiss_alert(self):
        if hasattr(self, "_alert_panel") and self._alert_panel:
            self._alert_panel.hide()
            self._alert_panel.deleteLater()
            self._alert_panel = None
        self._dismiss_content()

    def _animate_search_focus(self, hud_offset=-220):
        if self._focus_mode:
            return
        self._focus_mode = True
        cw = self.centralWidget()
        self._focus_original_geometry = {
            widget: widget.geometry()
            for widget in (*self._metric_panels, self._log_panel,
                           self._mute_btn, self._keyboard_btn,
                           self._music_widget)
        }
        self._focus_animations = []

        for widget, original in self._focus_original_geometry.items():
            target_x = -widget.width() - 40 if original.center().x() < cw.width() / 2 else cw.width() + 40
            animation = QPropertyAnimation(widget, b"pos", self)
            animation.setDuration(260)
            animation.setStartValue(original.topLeft())
            animation.setEndValue(QPointF(target_x, original.y()).toPoint())
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.start()
            self._focus_animations.append(animation)

        hud_animation = QPropertyAnimation(self.hud, b"presentation_x", self)
        hud_animation.setDuration(320)
        hud_animation.setStartValue(self.hud.presentation_x)
        # Keep the complete hologram inside the transparent HUD canvas.
        ring_radius = self.hud.height() * 0.54
        safe_offset = max(hud_offset, -(self.hud.width() / 2 - ring_radius))
        hud_animation.setEndValue(int(safe_offset))
        hud_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        hud_animation.start()
        self._focus_animations.append(hud_animation)

        target_width = min(760, max(520, cw.width() - 80))
        target_height = min(360, max(230, cw.height() - 180))
        self._content_panel.resize(target_width, target_height)
        target = QRect(
            max(12, cw.width() - target_width - 32),
            max(72, (cw.height() - target_height) // 2),
            target_width, target_height,
        )
        content_animation = QPropertyAnimation(self._content_panel, b"geometry", self)
        content_animation.setDuration(320)
        content_animation.setStartValue(self._content_panel.geometry())
        content_animation.setEndValue(target)
        content_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        content_animation.start()
        self._focus_animations.append(content_animation)

    def _dismiss_content(self):
        self._content_panel.hide()
        if not self._focus_mode:
            return
        self._focus_mode = False
        self._focus_animations = []
        for widget, original in self._focus_original_geometry.items():
            animation = QPropertyAnimation(widget, b"geometry", self)
            animation.setDuration(240)
            animation.setStartValue(widget.geometry())
            animation.setEndValue(original)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.start()
            self._focus_animations.append(animation)
        hud_animation = QPropertyAnimation(self.hud, b"presentation_x", self)
        hud_animation.setDuration(280)
        hud_animation.setStartValue(self.hud.presentation_x)
        hud_animation.setEndValue(0)
        hud_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        hud_animation.start()
        self._focus_animations.append(hud_animation)

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont("Courier New", 7))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("[F4] Mute  ·  [F11] Fullscreen"))
        lay.addStretch()
        lay.addWidget(_fl("By FatihMakes", C.PRI_DIM))
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Tell {self._assistant_name} what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        self._file_preview_sig.emit(path)
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def notify_phone_connected(self) -> None:
        if self._remote_overlay and self._remote_overlay.isVisible():
            self._remote_overlay.mark_connected()

    def _open_remote(self):
        if not self.on_remote_clicked:
            self._log.append_log("SYS: Dashboard not running — remote unavailable.")
            return
        result = self.on_remote_clicked()
        if not result:
            self._log.append_log("SYS: Could not generate remote key.")
            return
        url    = result[0]
        key    = result[1]
        auto   = result[2] if len(result) >= 3 else ""
        manual = result[3] if len(result) >= 4 else url
        if self._remote_overlay:
            self._remote_overlay._do_close()
        cw  = self.centralWidget()
        ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
        ov  = RemoteKeyOverlay(url, key, auto_login_url=auto, manual_url=manual,
                               expiry_secs=600, parent=cw)
        ov.set_new_key_callback(self.on_remote_clicked)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.closed.connect(lambda: setattr(self, '_remote_overlay', None))
        ov.show()
        self._remote_overlay = ov
        self._log.append_log(f"SYS: Remote key generated — manual: {manual or url}")

    # ── Auto-start ──────────────────────────────────────────────────────────────

    def _check_autostart(self) -> bool:
        """Returns True if auto-start is currently registered on this OS."""
        try:
            if _OS == "Windows":
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
                try:
                    winreg.QueryValueEx(key, "JARVIS_AI")
                    return True
                except FileNotFoundError:
                    return False
                finally:
                    winreg.CloseKey(key)
            elif _OS == "Darwin":
                return (Path.home() / "Library" / "LaunchAgents"
                        / "com.jarvis.assistant.plist").exists()
            else:
                return (Path.home() / ".config" / "autostart" / "jarvis.desktop").exists()
        except Exception:
            return False

    def _toggle_autostart(self):
        currently_on = self._check_autostart()
        try:
            script = str(Path(__file__).resolve().parent / "main.py")
            if _OS == "Windows":
                import winreg
                reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
                if currently_on:
                    winreg.DeleteValue(reg, "JARVIS_AI")
                else:
                    pythonw = Path(sys.executable).parent / "pythonw.exe"
                    exe = str(pythonw if pythonw.exists() else sys.executable)
                    winreg.SetValueEx(reg, "JARVIS_AI", 0, winreg.REG_SZ,
                                      f'"{exe}" "{script}"')
                winreg.CloseKey(reg)
            elif _OS == "Darwin":
                plist_dir = Path.home() / "Library" / "LaunchAgents"
                plist_dir.mkdir(parents=True, exist_ok=True)
                plist = plist_dir / "com.jarvis.assistant.plist"
                if currently_on:
                    plist.unlink(missing_ok=True)
                else:
                    plist.write_text(
                        '<?xml version="1.0" encoding="UTF-8"?>\n'
                        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                        '<plist version="1.0"><dict>\n'
                        '  <key>Label</key><string>com.jarvis.assistant</string>\n'
                        '  <key>ProgramArguments</key><array>\n'
                        f'    <string>{sys.executable}</string>\n'
                        f'    <string>{script}</string>\n'
                        '  </array>\n'
                        '  <key>RunAtLoad</key><true/>\n'
                        '</dict></plist>\n'
                    )
            else:
                desk_dir = Path.home() / ".config" / "autostart"
                desk_dir.mkdir(parents=True, exist_ok=True)
                desk = desk_dir / "jarvis.desktop"
                if currently_on:
                    desk.unlink(missing_ok=True)
                else:
                    desk.write_text(
                        "[Desktop Entry]\n"
                        f"Name={self._assistant_name}\n"
                        f"Exec={sys.executable} {script}\n"
                        "Type=Application\nTerminal=false\n"
                        "X-GNOME-Autostart-enabled=true\n"
                    )
            enabled = not currently_on
            self._update_autostart_btn(enabled)
            self._log.append_log(
                f"SYS: Auto-start {'enabled' if enabled else 'disabled'}.")
        except Exception as e:
            self._log.append_log(f"ERR: Auto-start failed — {e}")

    def _update_autostart_btn(self, enabled: bool):
        if not hasattr(self, '_autostart_btn'):
            return
        if enabled:
            self._autostart_btn.setText("◉  AUTO-START: ON")
            self._autostart_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            self._autostart_btn.setText("◉  AUTO-START: OFF")
            self._autostart_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    def _toggle_brief(self):
        from memory.config_manager import get_brief_enabled, save_brief_enabled
        new_val = not get_brief_enabled()
        save_brief_enabled(new_val)
        self._update_brief_btn(new_val)

    def _visual_modes(self):
        return (
            ("CYAN COMMAND", "#00d4ff"),
            ("AMBER TACTICAL", "#ff9d2e"),
            ("RED ALERT", "#ff3355"),
            ("GHOST MODE", "#a8c7d8"),
        )

    def _refresh_visual_mode_btn(self):
        if not hasattr(self, "_visual_mode_btn"):
            return
        current = (_read_full_config().get("ui_color") or DEFAULT_UI_COLOR).lower()
        modes = self._visual_modes()
        label = next((name for name, color in modes if color.lower() == current), "CUSTOM MODE")
        self._visual_mode_btn.setText(f"◉  MODE: {label}")

    def _cycle_visual_mode(self):
        modes = self._visual_modes()
        current = (_read_full_config().get("ui_color") or DEFAULT_UI_COLOR).lower()
        index = next((i for i, (_, color) in enumerate(modes) if color.lower() == current), -1)
        _, color = modes[(index + 1) % len(modes)]
        old = current_palette()
        if not apply_ui_accent(color):
            return
        retheme_all_widgets(old, current_palette())
        data = _read_full_config()
        data["ui_color"] = color
        try:
            API_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
        except OSError:
            pass
        self._refresh_visual_mode_btn()
        self._log.append_log(f"SYS: Visual mode changed — {color}")

    def _update_brief_btn(self, enabled: bool):
        if not hasattr(self, '_brief_btn'):
            return
        if enabled:
            self._brief_btn.setText("☀  MORNING BRIEF: ON")
            self._brief_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                    text-align: left; padding: 0 8px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            self._brief_btn.setText("☀  MORNING BRIEF: OFF")
            self._brief_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                    text-align: left; padding: 0 8px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    # ── Customization ────────────────────────────────────────────────────────────

    def _open_customize(self):
        cfg = _read_full_config()
        if self._customize_overlay:
            self._customize_overlay.hide()
        cw = self.centralWidget()
        ov = CustomizeOverlay(
            cfg.get("assistant_name", "JARVIS") or "JARVIS",
            cfg.get("user_name", ""),
            cfg.get("ui_color", "") or DEFAULT_UI_COLOR,
            parent=cw,
        )
        ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
        oh = min(oh, cw.height() - 16)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.on_preview = self._preview_ui_color
        ov.saved.connect(self._apply_name_update)
        ov.show()
        self._customize_overlay = ov
        for panel in (*self._metric_panels, self._log_panel, self._music_widget):
            panel.enable_editing(True)

    def _open_audio_settings(self):
        from core.audio_control import load_audio_settings
        if self._audio_settings_overlay:
            self._audio_settings_overlay.deleteLater()
        cw = self.centralWidget()
        overlay = AudioSettingsOverlay(load_audio_settings(), parent=cw)
        overlay.saved.connect(self._on_audio_settings_saved)
        overlay.move((cw.width() - overlay.width()) // 2, (cw.height() - overlay.height()) // 2)
        overlay.show()
        overlay.raise_()
        self._audio_settings_overlay = overlay

    def _open_sessions(self):
        if self._sessions_overlay:
            self._sessions_overlay.deleteLater()
        cw = self.centralWidget()
        overlay = SessionsOverlay(parent=cw)
        ow = min(SessionsOverlay._OW, max(360, cw.width() - 24))
        oh = min(SessionsOverlay._OH, max(360, cw.height() - 24))
        overlay.setGeometry(
            (cw.width() - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        overlay.show()
        overlay.raise_()
        self._sessions_overlay = overlay

    def _on_audio_settings_saved(self, settings: dict):
        if self.on_audio_settings_changed:
            self.on_audio_settings_changed(settings)
        self._log.append_log("SYS: Audio settings updated.")

    def _preview_ui_color(self, hex_color: str):
        """Canlı önizleme — tüm arayüzü yeni renge boyar (config'e YAZMAZ)."""
        old = current_palette()
        if apply_ui_accent(hex_color):
            retheme_all_widgets(old, current_palette())

    def _apply_name_update(self, name: str, user_name: str, ui_color: str = ""):
        """Update all name/theme-dependent UI elements and persist to config."""
        self._assistant_name = name.strip() or "JARVIS"
        display = self._assistant_name.upper()
        self.setWindowTitle(f"{display} — MARK LI")
        self._title_lbl.setText(display)
        if display in ("JARVIS", "J.A.R.V.I.S"):
            self._sub_lbl.setText("Just A Rather Very Intelligent System")
        else:
            self._sub_lbl.setText("Personal AI Assistant")
        self._log._ai_name_lc = self._assistant_name.lower()
        self.hud._assistant_name = display
        for panel in (*self._metric_panels, self._log_panel, self._music_widget):
            panel.enable_editing(False)

        color_changed = False
        if ui_color:
            old = current_palette()
            if apply_ui_accent(ui_color):
                # Tüm arayüzü (paneller, butonlar, kenarlıklar, HUD) canlı boya
                retheme_all_widgets(old, current_palette())
                color_changed = old["PRI"] != C.PRI

        try:
            data = _read_full_config()
            data["assistant_name"] = self._assistant_name
            data["user_name"] = user_name.strip()
            if ui_color:
                data["ui_color"] = ui_color.strip().lower()
            API_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
            self._log.append_log(f"SYS: Identity updated — {display}")
            if color_changed:
                self._log.append_log(f"SYS: UI colour applied — {ui_color}")
        except Exception as e:
            self._log.append_log(f"ERR: Config save failed — {e}")

    def _open_plugin_manager(self):
        plugins = self.get_plugins() if self.get_plugins else []
        cw = self.centralWidget()
        ov = PluginManagerOverlay(plugins, parent=cw)
        ov.adjustSize()
        ov.setGeometry(
            (cw.width()  - ov.width())  // 2,
            (cw.height() - ov.height()) // 2,
            ov.width(), ov.height(),
        )
        ov.show()
        ov.raise_()
        self._plugin_manager_overlay = ov   # keep a reference so it isn't GC'd

    # ── Clipboard intelligence ───────────────────────────────────────────────────

    def _on_clipboard_changed(self):
        try:
            text = QApplication.clipboard().text().strip()
            if len(text) >= 10:
                self._clipboard_sig.emit(text)
        except Exception:
            pass

    def set_service_status(self, key: str, state: str, detail: str = ""):
        self._service_status_sig.emit(key, state, detail)

    def _show_clipboard_panel(self, text: str):
        self._clipboard_panel.show_clipboard(text)
        self._position_clipboard_panel()

    def _position_clipboard_panel(self):
        cw = self.centralWidget()
        pw = ClipboardPanel._W
        ph = self._clipboard_panel.sizeHint().height() or ClipboardPanel._H
        x = (cw.width() - pw) // 2
        y = cw.height() - ph - 6
        self._clipboard_panel.setGeometry(x, y, pw, ph)
        self._clipboard_panel.raise_()

    def _on_clipboard_action(self, cmd: str):
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(cmd,), daemon=True).start()

    # ────────────────────────────────────────────────────────────────────────────

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()

    def _on_ptt_status(self, enabled: bool, held: bool, chord: str = "CTRL+SPACE"):
        if not hasattr(self, "_ptt_status"):
            return
        if not enabled:
            text, color = "PTT OFF", C.TEXT_DIM
        elif held:
            text, color = "PTT ACTIVE", C.GREEN
        else:
            text, color = f"PTT READY  {chord}", C.ACC
        self._ptt_status.setText(text)
        self._ptt_status.setStyleSheet(
            f"color: {color}; background: transparent; font: 700 7px 'Courier New';"
        )
        self.set_service_status("PTT", "active" if held else ("ready" if enabled else "off"), text)

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("🔇")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 22px;
                }}
                QPushButton:hover {{ background: #300018; }}
            """)
        else:
            self._mute_btn.setText("🎙")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 22px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")
        if hasattr(self, "_header_state"):
            colors = {
                "LISTENING": C.GREEN,
                "SPEAKING": C.ACC,
                "THINKING": C.ACC2,
                "PROCESSING": C.ACC2,
                "SLEEPING": C.TEXT_DIM,
            }
            self._header_state.setText(f"● {state}")
            self._header_state.setStyleSheet(
                f"color: {colors.get(state, C.PRI)}; background: transparent;"
            )

    def show_shutdown_animation(self):
        """Show the power-down sequence before the process exits."""
        if hasattr(self, "_boot_overlay"):
            self._boot_overlay.start_shutdown()
            QApplication.processEvents()

    def show_restart_animation(self):
        """Show the restart sequence before the replacement process starts."""
        if hasattr(self, "_boot_overlay"):
            self._boot_overlay.start_restart()
            QApplication.processEvents()

    def closeEvent(self, event):
        if getattr(self, "_allow_close", False):
            event.accept()
            return
        self._allow_close = True
        self.show_shutdown_animation()
        QTimer.singleShot(1450, self.close)
        event.ignore()

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 390
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, key: str, os_name: str):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            API_FILE.parent.mkdir(parents=True, exist_ok=True)
            API_FILE.write_text(
                json.dumps({"gemini_api_key": key, "os_system": os_name}, indent=4),
                encoding="utf-8",
            )
        except OSError as exc:
            self._log.append_log(f"ERR: Config save failed — {exc}\nSYS: Using a fallback config location.")
            try:
                fallback = Path.home() / "AppData" / "Local" / "Mark-LII" / "config" / "api_keys.json"
                fallback.parent.mkdir(parents=True, exist_ok=True)
                fallback.write_text(
                    json.dumps({"gemini_api_key": key, "os_system": os_name}, indent=4),
                    encoding="utf-8",
                )
                globals()["API_FILE"] = fallback
                globals()["CONFIG_DIR"] = fallback.parent
            except Exception as fallback_exc:
                self._log.append_log(f"ERR: Fallback config save failed — {fallback_exc}")
                self._ready = True
                return
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._assistant_name = _read_full_config().get("assistant_name", "JARVIS") or "JARVIS"
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. {self._assistant_name} online.")

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win.showMaximized()
        self.root = _RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_remote_clicked(self):
        return self._win.on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._win.on_remote_clicked = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    @property
    def on_restart(self):
        return self._win.on_restart

    @on_restart.setter
    def on_restart(self, cb):
        self._win.on_restart = cb

    @property
    def on_reset_context(self):
        return self._win.on_reset_context

    @on_reset_context.setter
    def on_reset_context(self, cb):
        self._win.on_reset_context = cb

    @property
    def on_audio_settings_changed(self):
        return self._win.on_audio_settings_changed

    @on_audio_settings_changed.setter
    def on_audio_settings_changed(self, cb):
        self._win.on_audio_settings_changed = cb

    @property
    def on_reminder(self):
        return self._win.on_reminder

    @on_reminder.setter
    def on_reminder(self, cb):
        self._win.on_reminder = cb

    def show_productivity_timer(self, kind: str):
        """Open and refresh the timer surface from worker threads."""
        self._win._productivity_timer_sig.emit(kind)

    @property
    def get_plugins(self):
        return self._win.get_plugins

    @get_plugins.setter
    def get_plugins(self, cb):
        self._win.get_plugins = cb

    def notify_phone_connected(self) -> None:
        self._win._phone_connected_sig.emit()

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def set_service_status(self, key: str, state: str, detail: str = ""):
        """Thread-safe forwarding for the service health strip."""
        self._win.set_service_status(key, state, detail)

    def set_audio_level(self, level: float):
        """Thread-safe audio level for the animated face and waveform."""
        self._win._audio_level_sig.emit(float(level))

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def show_content(self, title: str, text: str):
        """Thread-safe: display content in the panel below the HUD."""
        self._win._content_sig.emit(title[:48], text[:4000])

    def show_file_preview(self, file_path: str):
        """Thread-safe: render a selected file in the holographic preview panel."""
        if file_path:
            self._win._file_preview_sig.emit(file_path)

    def show_3d_hologram(self, description: str, model_path: str = ""):
        """Thread-safe: display an interactive procedural 3D hologram in the HUD."""
        if description:
            self._win._hologram3d_sig.emit(description, model_path)

    def show_system_scan(self, status: dict, resource: str = ""):
        """Present system metrics sequentially in the animated UI."""
        self._win._system_scan_sig.emit(status, resource)

    def advance_system_scan_with_voice(self, text: str):
        """Advance system metric cards from JARVIS spoken transcript."""
        self._win._system_scan_transcript_sig.emit(text)

    def show_music_widget(self):
        """Bring the current music player widget to the foreground."""
        self._win._music_focus_sig.emit()

    @property
    def media_active(self) -> bool:
        return self._win._media_active

    def enter_mini_mode(self):
        """Move JARVIS to the compact bottom-right presentation mode.

        Prefer the Qt signal, but never depend on signal delivery alone:
        a direct fallback call to ``MainWindow`` preserves the minimization
        contract when the signal transport is broken in the runtime.
        """
        try:
            self._win._mini_mode_sig.emit(True)
        except Exception:
            self._win.enter_mini_mode()

    def restore_presentation(self):
        """Restore the full holographic workspace.

        Prefer the Qt signal, but fall back directly to the real ``MainWindow``
        controller so the restore event cannot disappear into a broken signal chain.
        """
        try:
            self._win._mini_mode_sig.emit(False)
        except Exception:
            self._win.restore_presentation()

    def set_music_track(self, title: str, artist: str,
                        cover_path: str | None = None):
        """Update the music widget metadata and optional artwork."""
        self._win._music_widget.set_track(title, artist, cover_path)

    def show_system_alert(self, text: str):
        """Thread-safe: show an animated full-screen system warning."""
        self._win._system_alert_sig.emit(text[:4000])

    def show_shutdown_animation(self):
        """Show the red power-down sequence before an intentional exit."""
        self._win.show_shutdown_animation()

    def show_restart_animation(self):
        """Show the amber restart sequence before an intentional restart."""
        self._win.show_restart_animation()

    def set_microphone_status(self, status: str):
        """Thread-safe: update microphone connection status.
        Status can be: 'connected', 'disconnected', or 'unavailable'
        """
        self._win._mic_status_sig.emit(status)
        state = "ok" if status == "connected" else "error"
        self._win.set_service_status("MIC", state, status.upper())

    def set_ptt_status(self, enabled: bool, held: bool = False, chord: str = "CTRL+SPACE"):
        """Thread-safe: update the microphone panel's Push-to-Talk indicator."""
        self._win._ptt_status_sig.emit(bool(enabled), bool(held), chord)

    def prompt_reconfig(self):
        """Thread-safe: show the API key setup overlay (e.g. after an auth error)."""
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def show_camera_frame(self, img_bytes: bytes):
        """Thread-safe: show a webcam frame in the small overlay (screen captures)."""
        self._win._camera_sig.emit(img_bytes)

    def start_camera_stream(self) -> None:
        """Thread-safe: start live camera feed in the full HUD area."""
        self._win._cam_stream_sig.emit(True)

    def stop_camera_stream(self) -> None:
        """Thread-safe: stop the live camera feed."""
        self._win._cam_stream_sig.emit(False)

    @property
    def assistant_name(self) -> str:
        return self._win._assistant_name

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")