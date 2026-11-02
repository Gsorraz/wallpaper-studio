#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wallpaper Studio — papel de parede por monitor (Windows)
=========================================================
• Detecta as telas conectadas (resolução física, Hz, escala do Windows, posição, principal)
• Papel de parede diferente em cada tela  OU  uma imagem estendida em todas
• Modos iguais aos do Windows: Preencher, Ajustar, Ampliar, Lado a lado, Centralizar, Estender
  — só que individual por tela
• Ajuste fino por tela: posição, escala, rotação, perspectiva H/V, espelhar, cor de fundo
• Mouse: arrastar = mover · roda = zoom · Ctrl+roda = girar · Shift+arrastar = perspectiva
• Aplica no Windows montando UMA imagem do tamanho da área de trabalho virtual
  e usando o estilo "Estender" (Span) — assim cada tela recebe exatamente o seu pedaço.

Rodar:  pip install -r requirements.txt   →   python main.py   (ou F5 no VS Code)
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QGuiApplication, QIcon,
                           QImage, QImageReader, QKeySequence, QPainter, QPainterPath,
                           QPen, QPixmap, QTransform, QFontDatabase, QFontMetrics)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QColorDialog,
                               QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QSlider, QSplitter, QStatusBar, QSystemTrayIcon,
                               QToolButton, QVBoxLayout, QWidget)

IS_WIN = sys.platform == "win32"
APP_NAME = "Wallpaper Studio"
DATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "WallpaperStudio"
CONFIG_FILE = DATA_DIR / "config.json"
IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff", ".jfif")
ACCENT = "#0a84ff"        # azul do sistema (Apple, tema escuro)
ICON_NAME = "wallpaper_engine_macos_bigsur_icon_189566.ico"


def resource_path(name: str) -> Path:
    """Arquivo ao lado do main.py, ou dentro do .exe do PyInstaller (sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) if base else Path(__file__).resolve().parent) / name


def app_icon() -> QIcon:
    return QIcon(str(resource_path(ICON_NAME)))


_ICON_FONT: str | None = None


def glyph_icon(code: str, color: str = "#f5f5f7", size: int = 16) -> QIcon:
    """Ícone desenhado com a fonte de ícones do Windows (Segoe Fluent/MDL2); vazio se não houver."""
    global _ICON_FONT
    if _ICON_FONT is None:
        fams = set(QFontDatabase.families())
        _ICON_FONT = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), "")
    if not _ICON_FONT:
        return QIcon()
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont(_ICON_FONT)
    f.setPixelSize(size)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, code)
    p.end()
    return QIcon(pm)


def with_icon(btn, code: str, color: str = "#f5f5f7"):
    """Põe o ícone no botão (alinhado ao texto). Retorna True se conseguiu."""
    ic = glyph_icon(code, color)
    if ic.isNull():
        return False
    btn.setIcon(ic)
    btn.setIconSize(QSize(16, 16))
    return True

# (chave interna, rótulo igual ao do Windows, dica)
FIT_MODES = [
    ("fill", "Preencher", "Cobre a tela inteira, cortando sobras (padrão do Windows)"),
    ("fit", "Ajustar", "Mostra a imagem inteira; sobra vira cor de fundo"),
    ("stretch", "Ampliar", "Estica para o tamanho exato da tela (pode distorcer)"),
    ("tile", "Lado a lado", "Repete a imagem no tamanho original"),
    ("center", "Centralizar", "Tamanho original no centro da tela"),
]


# ════════════════════════════════════════════════════════════════════════════
#  Modelo
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class WallCfg:
    image: str = ""
    mode: str = "fill"
    scale: float = 100.0      # %
    offset_x: float = 0.0     # % da largura da tela
    offset_y: float = 0.0     # % da altura da tela
    rotation: float = 0.0     # graus
    persp_h: float = 0.0      # -100..100  (+ = lado direito "mais longe")
    persp_v: float = 0.0      # -100..100  (+ = topo "mais longe")
    flip_h: bool = False
    flip_v: bool = False
    bg: str = "#000000"

    def copy(self) -> "WallCfg":
        return WallCfg(**asdict(self))

    def key(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    def reset_adjust(self):
        self.scale, self.offset_x, self.offset_y = 100.0, 0.0, 0.0
        self.rotation = self.persp_h = self.persp_v = 0.0
        self.flip_h = self.flip_v = False

    @staticmethod
    def from_dict(d: dict) -> "WallCfg":
        """Lê um dict vindo de config/perfil; valor de tipo errado ou fora da faixa vira o padrão."""
        base = WallCfg()
        if not isinstance(d, dict):
            return base
        limits = {"scale": (10, 500), "offset_x": (-200, 200), "offset_y": (-200, 200),
                  "rotation": (-180, 180), "persp_h": (-100, 100), "persp_v": (-100, 100)}
        out = {}
        for f in fields(WallCfg):
            if f.name not in d:
                continue
            v, default = d[f.name], getattr(base, f.name)
            if isinstance(default, bool):
                if isinstance(v, bool):
                    out[f.name] = v
            elif isinstance(default, float):
                if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                    lo, hi = limits[f.name]
                    out[f.name] = float(max(lo, min(hi, v)))
            elif f.name == "mode":
                if v in {k for k, _, _ in FIT_MODES}:
                    out[f.name] = v
            elif f.name == "bg":
                if isinstance(v, str) and QColor(v).isValid():
                    out[f.name] = v
            elif isinstance(v, str):
                out[f.name] = v
        return WallCfg(**out)


@dataclass
class SpanAdj:
    """Ajuste da parte de UMA tela quando a imagem está estendida em todas."""
    offset_x: float = 0.0     # % da largura da tela
    offset_y: float = 0.0     # % da altura da tela
    scale: float = 100.0      # %

    def key(self) -> tuple:
        return (self.offset_x, self.offset_y, self.scale)

    def is_default(self) -> bool:
        return self.key() == (0.0, 0.0, 100.0)

    @staticmethod
    def from_dict(d: dict) -> "SpanAdj":
        out = SpanAdj()
        if not isinstance(d, dict):
            return out
        for name, lo, hi in (("offset_x", -200, 200), ("offset_y", -200, 200), ("scale", 10, 500)):
            v = d.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                setattr(out, name, float(max(lo, min(hi, v))))
        return out


@dataclass
class Monitor:
    index: int
    device: str               # \\.\DISPLAY1
    name: str                 # nome amigável
    x: int
    y: int
    w: int
    h: int
    hz: int = 0
    primary: bool = False
    scale_pct: int = 100
    qscreen: object = field(default=None, repr=False, compare=False)


# ════════════════════════════════════════════════════════════════════════════
#  Detecção de monitores
# ════════════════════════════════════════════════════════════════════════════
def _detect_windows() -> list[Monitor]:
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    try:
        shcore = ctypes.windll.shcore
    except OSError:
        shcore = None

    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]

    class DEVMODEW(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
            ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD),
            ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
            ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
            ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
            ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
            ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
            ("dmCollate", ctypes.c_short), ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD),
            ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD),
            ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD),
        ]

    MonitorEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                         ctypes.POINTER(RECT), wintypes.LPARAM)
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(RECT),
                                           MonitorEnumProc, wintypes.LPARAM]
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
    user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                            ctypes.POINTER(DEVMODEW)]
    user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.POINTER(DISPLAY_DEVICEW), wintypes.DWORD]
    if shcore:
        shcore.GetDpiForMonitor.argtypes = [wintypes.HMONITOR, ctypes.c_int,
                                            ctypes.POINTER(wintypes.UINT),
                                            ctypes.POINTER(wintypes.UINT)]

    handles = []
    proc = MonitorEnumProc(lambda hmon, hdc, rc, lp: handles.append(hmon) or True)
    user32.EnumDisplayMonitors(None, None, proc, 0)

    out = []
    for h in handles:
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if not user32.GetMonitorInfoW(h, ctypes.byref(mi)):
            continue
        dev = mi.szDevice
        r = mi.rcMonitor
        x, y, w, hh, hz = r.left, r.top, r.right - r.left, r.bottom - r.top, 0
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        if user32.EnumDisplaySettingsW(dev, 0xFFFFFFFF, ctypes.byref(dm)):  # ENUM_CURRENT_SETTINGS
            x, y = dm.dmPositionX, dm.dmPositionY          # sempre em pixels físicos
            w, hh = dm.dmPelsWidth, dm.dmPelsHeight
            hz = dm.dmDisplayFrequency
        name = dev
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if user32.EnumDisplayDevicesW(dev, 0, ctypes.byref(dd), 0) and dd.DeviceString:
            name = dd.DeviceString
        scale = 100
        if shcore:
            dx, dy = wintypes.UINT(), wintypes.UINT()
            try:
                if shcore.GetDpiForMonitor(h, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                    scale = round(dx.value / 96 * 100)
            except Exception:
                pass
        out.append(Monitor(0, dev, name, x, y, w, hh, hz, bool(mi.dwFlags & 1), scale))
    return out


def _detect_qt() -> list[Monitor]:
    out = []
    prim = QGuiApplication.primaryScreen()
    for s in QGuiApplication.screens():
        g, r = s.geometry(), s.devicePixelRatio()
        out.append(Monitor(0, s.name(), s.model() or s.name(),
                           round(g.x() * r), round(g.y() * r),
                           round(g.width() * r), round(g.height() * r),
                           round(s.refreshRate()),
                           prim is not None and s.name() == prim.name(), round(r * 100)))
    return out


def _attach_qt_screens(mons: list[Monitor]):
    """Liga cada monitor ao QScreen (para o 'Identificar') e pega um nome mais amigável."""
    screens = QGuiApplication.screens()
    for m in mons:
        best, bd = None, float("inf")
        for s in screens:
            if s.name() == m.device:
                best = s
                break
            g, r = s.geometry(), s.devicePixelRatio()
            d = (abs(g.x() * r - m.x) + abs(g.y() * r - m.y)
                 + abs(g.width() * r - m.w) + abs(g.height() * r - m.h))
            if d < bd:
                best, bd = s, d
        m.qscreen = best
        if best is not None:
            nm, model = best.name(), best.model()
            if nm and not nm.startswith("\\\\.\\") and nm != m.device:
                m.name = nm
            elif model:
                m.name = model


def _device_order(dev: str) -> int:
    digits = "".join(c for c in dev if c.isdigit())
    return int(digits) if digits else 999


def detect_monitors() -> list[Monitor]:
    mons: list[Monitor] = []
    if IS_WIN:
        try:
            mons = _detect_windows()
        except Exception as e:  # noqa: BLE001
            print("Detecção Win32 falhou, usando Qt:", e)
    if not mons:
        mons = _detect_qt()
    mons.sort(key=lambda m: _device_order(m.device))
    for i, m in enumerate(mons, 1):
        m.index = i
    _attach_qt_screens(mons)
    return mons


def virtual_bbox(mons: list[Monitor]) -> tuple[int, int, int, int]:
    if not mons:
        return 0, 0, 1920, 1080
    minx = min(m.x for m in mons)
    miny = min(m.y for m in mons)
    maxx = max(m.x + m.w for m in mons)
    maxy = max(m.y + m.h for m in mons)
    return minx, miny, maxx - minx, maxy - miny


# ════════════════════════════════════════════════════════════════════════════
#  Imagens
# ════════════════════════════════════════════════════════════════════════════
class ImageStore:
    PREVIEW_MAX = 1800

    def __init__(self):
        self._prev: dict[str, tuple] = {}
        self._thumbs: dict[str, QPixmap] = {}

    @staticmethod
    def _read(path: str) -> QImage:
        if not path or not os.path.isfile(path):
            return QImage()
        r = QImageReader(path)
        r.setAutoTransform(True)        # respeita rotação EXIF de fotos de celular
        return r.read()

    def preview(self, path: str):
        """(imagem reduzida para pré-visualização, (largura, altura) originais)"""
        if not path:
            return None, (0, 0)
        if path not in self._prev:
            img = self._read(path)
            if img.isNull():
                self._prev[path] = (None, (0, 0))
            else:
                size = (img.width(), img.height())
                if max(size) > self.PREVIEW_MAX:
                    img = img.scaled(self.PREVIEW_MAX, self.PREVIEW_MAX,
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
                img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                self._prev[path] = (img, size)
        return self._prev[path]

    def full(self, path: str):
        img = self._read(path)
        return None if img.isNull() else img

    def thumb(self, path: str, w=128, h=72) -> QPixmap | None:
        key = f"{path}|{w}x{h}"
        if key not in self._thumbs:
            img, _ = self.preview(path)
            if img is None:
                return None
            s = img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
            s = s.copy((s.width() - w) // 2, (s.height() - h) // 2, w, h)
            self._thumbs[key] = QPixmap.fromImage(s)
        return self._thumbs[key]

    def forget(self, path: str):
        self._prev.pop(path, None)
        for k in [k for k in self._thumbs if k.startswith(path + "|")]:
            self._thumbs.pop(k)


# ════════════════════════════════════════════════════════════════════════════
#  Renderização (mesma função para prévia e para o arquivo final)
# ════════════════════════════════════════════════════════════════════════════
def square_to_quad(q) -> QTransform:
    """Homografia do quadrado unitário (0,0)(1,0)(1,1)(0,1) → quadrilátero q."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = q
    sx, sy = x0 - x1 + x2 - x3, y0 - y1 + y2 - y3
    if abs(sx) < 1e-9 and abs(sy) < 1e-9:
        return QTransform(x1 - x0, y1 - y0, 0, x3 - x0, y3 - y0, 0, x0, y0, 1)
    dx1, dx2, dy1, dy2 = x1 - x2, x3 - x2, y1 - y2, y3 - y2
    den = dx1 * dy2 - dx2 * dy1
    if abs(den) < 1e-12:
        return QTransform()
    g = (sx * dy2 - dx2 * sy) / den
    h = (dx1 * sy - sx * dy1) / den
    a, b, c = x1 - x0 + g * x1, x3 - x0 + h * x3, x0
    d, e, f = y1 - y0 + g * y1, y3 - y0 + h * y3, y0
    return QTransform(a, d, g, b, e, h, c, f, 1)


def keystone_quad(rect: QRectF, ph: float, pv: float, rot_deg: float):
    """Cantos (TL, TR, BR, BL) do retângulo com perspectiva e rotação aplicadas."""
    k = 0.6
    ph, pv = max(-100.0, min(100.0, ph)) / 100.0, max(-100.0, min(100.0, pv)) / 100.0
    s_r, s_l = 1 - max(ph, 0) * k, 1 + min(ph, 0) * k
    s_t, s_b = 1 - max(pv, 0) * k, 1 + min(pv, 0) * k
    cx, cy = rect.center().x(), rect.center().y()
    hw, hh = rect.width() / 2, rect.height() / 2
    pts = [(cx - hw * s_t, cy - hh * s_l), (cx + hw * s_t, cy - hh * s_r),
           (cx + hw * s_b, cy + hh * s_r), (cx - hw * s_b, cy + hh * s_l)]
    if rot_deg:
        a = math.radians(rot_deg)
        ca, sa = math.cos(a), math.sin(a)
        pts = [(cx + (x - cx) * ca - (y - cy) * sa, cy + (x - cx) * sa + (y - cy) * ca)
               for x, y in pts]
    return pts


def paint_wallpaper(p: QPainter, cfg: WallCfg, img: QImage | None,
                    orig_w: int, orig_h: int, target: QRectF, k: float):
    """
    Desenha o papel de parede de `cfg` dentro de `target`.
    k = pixels de saída por pixel físico da tela (1.0 no arquivo final, <1 na prévia).
    `img` pode ser uma versão reduzida; orig_w/orig_h são as dimensões reais.
    """
    p.save()
    if p.hasClipping():
        p.setClipRect(target, Qt.ClipOperation.IntersectClip)
    else:
        p.setClipRect(target)
    p.fillRect(target, QColor(cfg.bg))
    if img is None or img.isNull() or orig_w <= 0 or orig_h <= 0:
        p.restore()
        return
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    W, H = target.width(), target.height()
    iw, ih = orig_w, orig_h
    su = max(cfg.scale, 1) / 100.0
    if cfg.mode == "fill":
        s = max(W / iw, H / ih)
        bw, bh = iw * s, ih * s
    elif cfg.mode == "fit":
        s = min(W / iw, H / ih)
        bw, bh = iw * s, ih * s
    elif cfg.mode == "stretch":
        bw, bh = W, H
    else:  # center / tile → tamanho original
        bw, bh = iw * k, ih * k
    bw, bh = bw * su, bh * su
    cx = target.center().x() + cfg.offset_x / 100.0 * W
    cy = target.center().y() + cfg.offset_y / 100.0 * H

    if cfg.mode == "tile":
        src = img
        if cfg.flip_h or cfg.flip_v:
            src = img.transformed(QTransform.fromScale(-1 if cfg.flip_h else 1,
                                                       -1 if cfg.flip_v else 1))
        quad = keystone_quad(target, cfg.persp_h, cfg.persp_v, cfg.rotation)
        world = (QTransform.fromTranslate(-target.x(), -target.y())
                 * QTransform.fromScale(1 / W, 1 / H) * square_to_quad(quad))
        p.setTransform(world, True)
        brush = QBrush(src)
        brush.setTransform(QTransform.fromScale(bw / src.width(), bh / src.height())
                           * QTransform.fromTranslate(cx - bw / 2, cy - bh / 2))
        p.fillRect(target.adjusted(-W, -H, W, H), brush)
    else:
        rect = QRectF(cx - bw / 2, cy - bh / 2, bw, bh)
        quad = keystone_quad(rect, cfg.persp_h, cfg.persp_v, cfg.rotation)
        dw, dh = img.width(), img.height()
        pre = QTransform()
        if cfg.flip_h or cfg.flip_v:
            pre = QTransform(-1 if cfg.flip_h else 1, 0, 0, -1 if cfg.flip_v else 1,
                             dw if cfg.flip_h else 0, dh if cfg.flip_v else 0)
        t = pre * QTransform.fromScale(1 / dw, 1 / dh) * square_to_quad(quad)
        p.setTransform(t, True)
        p.drawImage(0, 0, img)
    p.restore()


def paint_span_part(p: QPainter, cfg: WallCfg, adj: SpanAdj, img: QImage | None,
                    orig_w: int, orig_h: int, bbox: QRectF, part: QRectF, k: float):
    """
    Modo estendido: desenha a imagem inteira (`bbox` = área de todas as telas) mas só dentro de
    `part` (uma tela). `adj` desloca/amplia somente o que aparece nessa tela, sem mexer nas outras.
    """
    p.save()
    if p.hasClipping():
        p.setClipRect(part, Qt.ClipOperation.IntersectClip)
    else:
        p.setClipRect(part)
    p.fillRect(part, QColor(cfg.bg))
    c = part.center()
    s = max(adj.scale, 1) / 100.0
    t = (QTransform.fromTranslate(-c.x(), -c.y()) * QTransform.fromScale(s, s)
         * QTransform.fromTranslate(c.x() + adj.offset_x / 100.0 * part.width(),
                                    c.y() + adj.offset_y / 100.0 * part.height()))
    p.setTransform(t, True)
    paint_wallpaper(p, cfg, img, orig_w, orig_h, bbox, k)
    p.restore()


def build_composite(mons, cfgs, span_mode, span_cfg, store: ImageStore, span_adj=None) -> QImage:
    """Imagem única do tamanho da área de trabalho virtual (pixels físicos)."""
    minx, miny, bw, bh = virtual_bbox(mons)
    out = QImage(bw, bh, QImage.Format.Format_RGB32)
    out.fill(QColor("#000000"))
    p = QPainter(out)
    loaded: dict[str, QImage | None] = {}

    def get(path):
        if path not in loaded:
            loaded[path] = store.full(path) if path else None
        return loaded[path]

    if span_mode:
        img = get(span_cfg.image)
        iw, ih = (img.width(), img.height()) if img else (0, 0)
        for m in mons:
            adj = (span_adj or {}).get(m.device) or SpanAdj()
            paint_span_part(p, span_cfg, adj, img, iw, ih, QRectF(0, 0, bw, bh),
                            QRectF(m.x - minx, m.y - miny, m.w, m.h), 1.0)
    else:
        for m in mons:
            c = cfgs[m.device]
            img = get(c.image)
            paint_wallpaper(p, c, img, img.width() if img else 0, img.height() if img else 0,
                            QRectF(m.x - minx, m.y - miny, m.w, m.h), 1.0)
    p.end()
    return out


def set_windows_wallpaper_span(path: str) -> bool:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0,
                        winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "WallpaperStyle", 0, winreg.REG_SZ, "22")   # 22 = Estender
        winreg.SetValueEx(k, "TileWallpaper", 0, winreg.REG_SZ, "0")
        winreg.SetValueEx(k, "JPEGImportQuality", 0, winreg.REG_DWORD, 100)
    SPI_SETDESKWALLPAPER, SPIF = 20, 0x01 | 0x02
    return bool(ctypes.windll.user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, path, SPIF))


# ════════════════════════════════════════════════════════════════════════════
#  Widgets
# ════════════════════════════════════════════════════════════════════════════
def _fit_bold(btn: QPushButton):
    """Botão que fica em negrito (marcado/accent) precisa de largura pelo texto em negrito,
    senão o fim do texto é cortado."""
    f = QFont(btn.font())
    f.setBold(True)
    f.setPointSizeF(10)
    btn.setMinimumWidth(QFontMetrics(f).horizontalAdvance(btn.text()) + 40)


class SliderRow(QWidget):
    valueChanged = Signal(float)

    def __init__(self, label, lo, hi, default=0.0, suffix="", decimals=0, step=1.0):
        super().__init__()
        self.default = default
        self._mult = 10 ** decimals
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 2, 0, 2)
        v.setSpacing(2)
        top = QHBoxLayout()
        lab = QLabel(label)
        lab.setObjectName("rowLabel")
        lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # nunca alarga o painel
        lab.setToolTip(label)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(84)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        rst = QToolButton()
        if not with_icon(rst, "", "#98989f"):
            rst.setText("↺")
        rst.setToolTip("Voltar ao padrão")
        rst.setObjectName("mini")
        rst.clicked.connect(lambda: self.setValue(self.default, emit=True))
        top.addWidget(lab, 1)
        top.addWidget(self.spin)
        top.addWidget(rst)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(lo * self._mult), int(hi * self._mult))
        v.addLayout(top)
        v.addWidget(self.slider)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        self.setValue(default)

    def _from_slider(self, iv):
        self.spin.blockSignals(True)
        self.spin.setValue(iv / self._mult)
        self.spin.blockSignals(False)
        self.valueChanged.emit(iv / self._mult)

    def _from_spin(self, fv):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(fv * self._mult)))
        self.slider.blockSignals(False)
        self.valueChanged.emit(fv)

    def value(self) -> float:
        return self.spin.value()

    def setValue(self, v, emit=False):
        for w in (self.spin, self.slider):
            w.blockSignals(True)
        self.spin.setValue(v)
        self.slider.setValue(int(round(v * self._mult)))
        for w in (self.spin, self.slider):
            w.blockSignals(False)
        if emit:
            self.valueChanged.emit(self.spin.value())


class PropertiesPanel(QWidget):
    changed = Signal()
    choose_image = Signal()
    remove_image = Signal()
    copy_to_all = Signal()
    reset_adjust = Signal()
    recent_picked = Signal(str)

    def __init__(self, store: ImageStore):
        super().__init__()
        self.store = store
        self.cfg: WallCfg | None = None
        self.setObjectName("panel")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)

        self.title = QLabel("—")
        self.title.setObjectName("panelTitle")
        self.title.setWordWrap(True)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("muted")
        self.subtitle.setWordWrap(True)
        v.addWidget(self.title)
        v.addWidget(self.subtitle)

        # — imagem
        v.addWidget(self._section("Imagem"))
        self.thumb = QLabel()
        self.thumb.setObjectName("thumb")
        self.thumb.setFixedHeight(150)
        self.thumb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.thumb.setMinimumWidth(1)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.thumb)
        self.img_name = QLabel("")
        self.img_name.setObjectName("muted")
        self.img_name.setWordWrap(True)
        v.addWidget(self.img_name)
        row = QHBoxLayout()
        b1 = QPushButton("Escolher imagem…")
        with_icon(b1, "", "#ffffff")
        b1.setObjectName("accent")
        _fit_bold(b1)
        b1.clicked.connect(self.choose_image)
        b2 = QPushButton("Cor sólida")
        with_icon(b2, "")
        b2.setToolTip("Remove a imagem e deixa só a cor de fundo")
        b2.clicked.connect(self.remove_image)
        row.addWidget(b1, 1)
        row.addWidget(b2)
        v.addLayout(row)

        # — ajuste da parte desta tela (só no modo estendido)
        self.adj: SpanAdj | None = None
        self.adj_box = QWidget()
        av = QVBoxLayout(self.adj_box)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(6)
        self.adj_section = self._section("Ajuste só desta tela")
        av.addWidget(self.adj_section)
        self.adj_tip = QLabel("Move ou amplia apenas o pedaço da imagem que aparece nesta tela, "
                              "sem mexer nas outras. Clique numa tela e use Alt + arrastar / Alt + roda.")
        self.adj_tip.setObjectName("muted")
        self.adj_tip.setWordWrap(True)
        av.addWidget(self.adj_tip)
        self.a_x = SliderRow("Posição horizontal", -200, 200, 0, " %", 1, 0.5)
        self.a_y = SliderRow("Posição vertical", -200, 200, 0, " %", 1, 0.5)
        self.a_scale = SliderRow("Escala", 10, 500, 100, " %")
        for w in (self.a_x, self.a_y, self.a_scale):
            av.addWidget(w)
        b_adj = QPushButton("Restaurar esta tela")
        with_icon(b_adj, "")
        b_adj.clicked.connect(self._reset_adj)
        av.addWidget(b_adj)
        v.addWidget(self.adj_box)
        self.adj_box.setVisible(False)

        # — ajuste
        v.addWidget(self._section("Ajuste (como no Windows)"))
        self.mode = QComboBox()
        for key, label, tip in FIT_MODES:
            self.mode.addItem(label, key)
            self.mode.setItemData(self.mode.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        self.mode.currentIndexChanged.connect(self._on_mode)
        v.addWidget(self.mode)
        self.mode_tip = QLabel("")
        self.mode_tip.setObjectName("muted")
        self.mode_tip.setWordWrap(True)
        v.addWidget(self.mode_tip)

        bg_row = QHBoxLayout()
        bg_row.addWidget(QLabel("Cor de fundo"))
        bg_row.addStretch(1)
        self.bg_btn = QPushButton()
        self.bg_btn.setFixedSize(64, 26)
        self.bg_btn.clicked.connect(self._pick_bg)
        bg_row.addWidget(self.bg_btn)
        v.addLayout(bg_row)

        # — posição e escala
        v.addWidget(self._section("Posição e escala"))
        self.s_scale = SliderRow("Escala", 10, 500, 100, " %")
        self.s_x = SliderRow("Posição horizontal", -200, 200, 0, " %", 1, 0.5)
        self.s_y = SliderRow("Posição vertical", -200, 200, 0, " %", 1, 0.5)
        self.s_rot = SliderRow("Rotação", -180, 180, 0, "°", 1, 0.5)
        for w in (self.s_scale, self.s_x, self.s_y, self.s_rot):
            v.addWidget(w)

        # — perspectiva
        v.addWidget(self._section("Perspectiva"))
        self.s_ph = SliderRow("Horizontal (esq ↔ dir)", -100, 100, 0, "")
        self.s_pv = SliderRow("Vertical (topo ↔ base)", -100, 100, 0, "")
        v.addWidget(self.s_ph)
        v.addWidget(self.s_pv)
        fl = QHBoxLayout()
        self.c_fh = QCheckBox("Espelhar ↔")
        self.c_fv = QCheckBox("Espelhar ↕")
        fl.addWidget(self.c_fh)
        fl.addWidget(self.c_fv)
        fl.addStretch(1)
        v.addLayout(fl)

        row2 = QHBoxLayout()
        b3 = QPushButton("Restaurar")
        b3.setToolTip("Volta escala, posição, rotação e perspectiva ao padrão (tecla R)")
        with_icon(b3, "")
        b3.clicked.connect(self.reset_adjust)
        self.b_copy = QPushButton("Copiar p/ todas")
        self.b_copy.setToolTip("Replica os ajustes desta tela em todas as telas")
        with_icon(self.b_copy, "")
        self.b_copy.clicked.connect(self.copy_to_all)
        row2.addWidget(b3)
        row2.addWidget(self.b_copy)
        v.addLayout(row2)

        # — recentes
        v.addWidget(self._section("Recentes"))
        self.recent = QListWidget()
        self.recent.setViewMode(QListWidget.ViewMode.IconMode)
        self.recent.setIconSize(QSize(96, 54))
        self.recent.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.recent.setMovement(QListWidget.Movement.Static)
        self.recent.setSpacing(4)
        self.recent.setFixedHeight(140)
        self.recent.itemClicked.connect(
            lambda it: self.recent_picked.emit(it.data(Qt.ItemDataRole.UserRole)))
        v.addWidget(self.recent)

        tips = QLabel("<b>Atalhos na área das telas</b><br>"
                      "Arrastar → mover · Roda → zoom<br>"
                      "Ctrl + roda / Ctrl + arrastar → girar<br>"
                      "Shift + arrastar → perspectiva<br>"
                      "Setas → ajuste fino (Shift = 10×) · R → restaurar<br>"
                      "Estendido: Alt + arrastar / Alt + roda / Alt + setas → só a tela escolhida<br>"
                      "Duplo clique ou arrastar arquivo do Explorer → trocar imagem")
        tips.setObjectName("tips")
        tips.setWordWrap(True)
        v.addWidget(tips)
        v.addStretch(1)

        # conexões
        self.s_scale.valueChanged.connect(lambda x: self._set("scale", x))
        self.s_x.valueChanged.connect(lambda x: self._set("offset_x", x))
        self.s_y.valueChanged.connect(lambda x: self._set("offset_y", x))
        self.s_rot.valueChanged.connect(lambda x: self._set("rotation", x))
        self.s_ph.valueChanged.connect(lambda x: self._set("persp_h", x))
        self.s_pv.valueChanged.connect(lambda x: self._set("persp_v", x))
        self.c_fh.toggled.connect(lambda b: self._set("flip_h", b))
        self.c_fv.toggled.connect(lambda b: self._set("flip_v", b))
        self.a_x.valueChanged.connect(lambda x: self._set_adj("offset_x", x))
        self.a_y.valueChanged.connect(lambda x: self._set_adj("offset_y", x))
        self.a_scale.valueChanged.connect(lambda x: self._set_adj("scale", x))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.refresh_thumb()     # a miniatura acompanha a largura do painel

    def _set_adj(self, attr, val):
        if self.adj is not None:
            setattr(self.adj, attr, val)
            self.changed.emit()

    def _reset_adj(self):
        if self.adj is not None:
            self.adj.offset_x, self.adj.offset_y, self.adj.scale = 0.0, 0.0, 100.0
            self.refresh_values()
            self.changed.emit()

    @staticmethod
    def _section(text):
        lab = QLabel(text.upper())
        lab.setObjectName("section")
        lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return lab

    def _set(self, attr, val):
        if self.cfg is not None:
            setattr(self.cfg, attr, val)
            self.changed.emit()

    def _on_mode(self, i):
        key = self.mode.itemData(i)
        self.mode_tip.setText(next(t for k, _, t in FIT_MODES if k == key))
        self._set("mode", key)

    def _pick_bg(self):
        if self.cfg is None:
            return
        c = QColorDialog.getColor(QColor(self.cfg.bg), self, "Cor de fundo")
        if c.isValid():
            self.cfg.bg = c.name()
            self._paint_bg_btn()
            self.refresh_thumb()
            self.changed.emit()

    def _paint_bg_btn(self):
        if self.cfg:
            self.bg_btn.setStyleSheet(f"background:{self.cfg.bg}; border:1px solid #636366;"
                                      "border-radius:6px;")

    def set_target(self, title, subtitle, cfg: WallCfg, span: bool, adj: SpanAdj | None = None,
                   adj_title: str = ""):
        self.cfg = cfg
        self.adj = adj
        self.adj_box.setVisible(adj is not None)
        if adj is not None:
            self.adj_section.setText(adj_title.upper())
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.b_copy.setVisible(not span)
        self.refresh_values()

    def refresh_values(self):
        c = self.cfg
        if c is None:
            return
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(max(0, self.mode.findData(c.mode)))
        self.mode.blockSignals(False)
        self.mode_tip.setText(next(t for k, _, t in FIT_MODES if k == c.mode))
        self.s_scale.setValue(c.scale)
        self.s_x.setValue(c.offset_x)
        self.s_y.setValue(c.offset_y)
        self.s_rot.setValue(c.rotation)
        self.s_ph.setValue(c.persp_h)
        self.s_pv.setValue(c.persp_v)
        for cb, val in ((self.c_fh, c.flip_h), (self.c_fv, c.flip_v)):
            cb.blockSignals(True)
            cb.setChecked(val)
            cb.blockSignals(False)
        if self.adj is not None:
            self.a_x.setValue(self.adj.offset_x)
            self.a_y.setValue(self.adj.offset_y)
            self.a_scale.setValue(self.adj.scale)
        self._paint_bg_btn()
        self.refresh_thumb()

    def refresh_thumb(self):
        c = self.cfg
        w, h = max(self.thumb.width(), 120), 150
        pm = QPixmap(w, h)
        pm.fill(QColor(c.bg if c else "#000"))
        if c and c.image:
            img, size = self.store.preview(c.image)
            if img is not None:
                s = img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                p = QPainter(pm)
                p.drawImage((w - s.width()) // 2, (h - s.height()) // 2, s)
                p.end()
                self.img_name.setText(f"{Path(c.image).name}  ·  {size[0]}×{size[1]} px")
            else:
                self.img_name.setText(f"⚠ Imagem não encontrada: {c.image}")
        else:
            self.img_name.setText("Sem imagem — usando cor sólida")
        self.thumb.setPixmap(pm)

    def set_recents(self, paths):
        self.recent.clear()
        for p in paths:
            pm = self.store.thumb(p, 96, 54)
            if pm is None:
                continue
            it = QListWidgetItem(QIcon(pm), "")
            it.setToolTip(p)
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setSizeHint(QSize(104, 62))
            self.recent.addItem(it)


class LayoutCanvas(QWidget):
    """Área que desenha as telas na disposição real e permite editar com o mouse."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(520, 360)
        self._cache: dict[tuple, QPixmap] = {}
        self._drag = None

    # ——— geometria
    def layout_rects(self):
        mons = self.win.monitors
        if not mons:
            return [], QRectF(), 1.0
        minx, miny, bw, bh = virtual_bbox(mons)
        if bw <= 0 or bh <= 0:
            return [], QRectF(), 1.0
        margin = 40
        sc = max(0.01, min((self.width() - 2 * margin) / bw, (self.height() - 2 * margin) / bh))
        ox = (self.width() - bw * sc) / 2
        oy = (self.height() - bh * sc) / 2
        rects = [QRectF(ox + (m.x - minx) * sc, oy + (m.y - miny) * sc, m.w * sc, m.h * sc)
                 for m in mons]
        return rects, QRectF(ox, oy, bw * sc, bh * sc), sc

    def monitor_at(self, pos: QPointF):
        rects, _, _ = self.layout_rects()
        for i, r in enumerate(rects):
            if r.contains(pos):
                return i
        return None

    # ——— renderização com cache
    def _render(self, key, cfg, w, h, k):
        dpr = self.devicePixelRatioF()
        full_key = (key, cfg.key(), int(w), int(h), dpr)
        pm = self._cache.get(full_key)
        if pm is None:
            if len(self._cache) > 48:
                self._cache.clear()
            pm = QPixmap(max(1, math.ceil(w * dpr)), max(1, math.ceil(h * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(QColor("#000"))
            img, (iw, ih) = self.win.store.preview(cfg.image)
            p = QPainter(pm)
            paint_wallpaper(p, cfg, img, iw, ih, QRectF(0, 0, w, h), k)
            p.end()
            self._cache[full_key] = pm
        return pm

    def _render_part(self, key, cfg, adj, bbox: QRectF, r: QRectF, k):
        """Pedaço da imagem estendida que cai na tela `r`, já com o ajuste só dessa tela."""
        dpr = self.devicePixelRatioF()
        w, h = r.width(), r.height()
        full_key = (key, "part", cfg.key(), adj.key(), int(bbox.width()), int(bbox.height()),
                    int(w), int(h), int(r.x() - bbox.x()), int(r.y() - bbox.y()), dpr)
        pm = self._cache.get(full_key)
        if pm is None:
            if len(self._cache) > 48:
                self._cache.clear()
            pm = QPixmap(max(1, math.ceil(w * dpr)), max(1, math.ceil(h * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(QColor("#000"))
            img, (iw, ih) = self.win.store.preview(cfg.image)
            p = QPainter(pm)
            paint_span_part(p, cfg, adj, img, iw, ih,
                            QRectF(bbox.x() - r.x(), bbox.y() - r.y(), bbox.width(), bbox.height()),
                            QRectF(0, 0, w, h), k)
            p.end()
            self._cache[full_key] = pm
        return pm

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#161618"))
        # grade de pontos
        p.setPen(QPen(QColor("#262629"), 1.6))
        for x in range(12, self.width(), 24):
            for y in range(12, self.height(), 24):
                p.drawPoint(x, y)

        win = self.win
        rects, bbox, sc = self.layout_rects()
        if not rects:
            p.setPen(QColor("#98989f"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Nenhuma tela detectada")
            return
        for i, (m, r) in enumerate(zip(win.monitors, rects)):
            inner = r.adjusted(3, 3, -3, -3)
            path = QPainterPath()
            path.addRoundedRect(inner, 7, 7)
            # sombra
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 110))
            p.drawRoundedRect(inner.translated(0, 5), 8, 8)
            p.restore()

            p.save()
            p.setClipPath(path)
            if win.span_mode:
                cfg = win.span_cfg
                adj = win.span_adj.get(m.device) or SpanAdj()
                p.drawPixmap(r.topLeft(), self._render_part(m.device, cfg, adj, bbox, r, sc))
            else:
                cfg = win.cfgs[m.device]
                p.drawPixmap(r.topLeft(), self._render(m.device, cfg, r.width(), r.height(), sc))
            if not cfg.image or win.store.preview(cfg.image)[0] is None:
                p.setPen(QColor(255, 255, 255, 150))
                f = p.font()
                f.setPointSizeF(9.5)
                p.setFont(f)
                msg = ("⚠ Imagem não encontrada" if cfg.image else
                       "Arraste uma imagem aqui\nou dê dois cliques")
                p.drawText(inner, Qt.AlignmentFlag.AlignCenter, msg)
            p.restore()

            selected = i == win.selected
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(ACCENT) if (selected or win.span_mode) else QColor("#48484a"),
                          2.6 if selected else 1.4))
            p.drawRoundedRect(inner, 7, 7)
            self._draw_badges(p, inner, m, selected)

        if win.span_mode:
            p.setPen(QPen(QColor(ACCENT), 1.2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(bbox.adjusted(-8, -8, 8, 8), 10, 10)
            p.setPen(QColor(ACCENT))
            f = p.font()
            f.setPointSizeF(9)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(bbox.x() - 8, bbox.y() - 28, 560, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "ESTENDIDO — arraste = imagem toda · Alt + arrastar = só a tela escolhida")

    def _draw_badges(self, p: QPainter, r: QRectF, m: Monitor, selected: bool):
        # número da tela
        badge = QRectF(r.x() + 10, r.y() + 10, 28, 28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ACCENT) if selected else QColor(20, 22, 28, 210))
        p.drawEllipse(badge)
        p.setPen(QColor("white"))
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(10.5)
        p.setFont(f)
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(m.index))
        # legenda
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        txt = f"{m.w}×{m.h}" + (f" · {m.hz} Hz" if m.hz else "") + (" · ★ Principal" if m.primary else "")
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(txt) + 16
        if tw < r.width() - 16:
            pill = QRectF(r.x() + 10, r.bottom() - 30, tw, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(15, 17, 21, 200))
            p.drawRoundedRect(pill, 11, 11)
            p.setPen(QColor("#f5f5f7"))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, txt)

    # ——— mouse / teclado
    def _ref_rect(self):
        rects, bbox, _ = self.layout_rects()
        if self.win.span_mode:
            return bbox
        return rects[self.win.selected] if rects else QRectF(0, 0, 1, 1)

    def _alt(self, mods) -> bool:
        """Alt no modo estendido = mexe só na tela escolhida, não na imagem toda."""
        return bool(mods & Qt.KeyboardModifier.AltModifier) and self.win.span_mode

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        i = self.monitor_at(e.position())
        if i is not None and i != self.win.selected:
            self.win.select(i)
        if i is not None:
            c = self.win.active_cfg()
            a = self.win.active_adj()
            self._drag = (e.position(), c.offset_x, c.offset_y, c.persp_h, c.persp_v, c.rotation,
                          a.offset_x if a else 0.0, a.offset_y if a else 0.0)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.monitor_at(e.position()) is not None
                           else Qt.CursorShape.ArrowCursor)
            return
        start, ox, oy, ph, pv, rot, aox, aoy = self._drag
        dx, dy = e.position().x() - start.x(), e.position().y() - start.y()
        c = self.win.active_cfg()
        mods = e.modifiers()
        clamp = lambda v, lo, hi: max(lo, min(hi, v))  # noqa: E731
        if self._alt(mods):
            a = self.win.active_adj()
            r = self.layout_rects()[0][self.win.selected]
            a.offset_x = round(clamp(aox + dx / r.width() * 100, -200, 200), 1)
            a.offset_y = round(clamp(aoy + dy / r.height() * 100, -200, 200), 1)
            self.win.on_cfg_edited(from_canvas=True)
            return
        ref = self._ref_rect()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            c.persp_h = round(clamp(ph + dx / ref.width() * 200, -100, 100))
            c.persp_v = round(clamp(pv - dy / ref.height() * 200, -100, 100))
        elif mods & Qt.KeyboardModifier.ControlModifier:
            c.rotation = round(clamp(rot + dx * 0.5, -180, 180), 1)
        else:
            c.offset_x = round(clamp(ox + dx / ref.width() * 100, -200, 200), 1)
            c.offset_y = round(clamp(oy + dy / ref.height() * 100, -200, 200), 1)
        self.win.on_cfg_edited(from_canvas=True)

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor if self.monitor_at(e.position()) is not None
                       else Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, e):
        i = self.monitor_at(e.position())
        if i is not None:
            self.win.select(i)
            self.win.choose_image()

    def wheelEvent(self, e):
        i = self.monitor_at(e.position())
        if i is None:
            return
        if i != self.win.selected:
            self.win.select(i)
        steps = (e.angleDelta().y() or e.angleDelta().x()) / 120.0   # Alt pode trocar o eixo da roda
        c = self.win.active_cfg()
        if self._alt(e.modifiers()):
            a = self.win.active_adj()
            a.scale = max(10, min(500, round(a.scale * (1.06 ** steps))))
        elif e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            c.rotation = max(-180, min(180, round(c.rotation + steps * 2, 1)))
        else:
            c.scale = max(10, min(500, round(c.scale * (1.06 ** steps))))
        self.win.on_cfg_edited(from_canvas=True)

    def keyPressEvent(self, e):
        c = self.win.active_cfg()
        step = 5.0 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.5
        k = e.key()
        if k == Qt.Key.Key_Tab and self.win.monitors:     # troca de tela (também no estendido)
            self.win.select((self.win.selected + 1) % len(self.win.monitors))
            return
        if self._alt(e.modifiers()):
            a = self.win.active_adj()
            if k == Qt.Key.Key_Left:
                a.offset_x -= step
            elif k == Qt.Key.Key_Right:
                a.offset_x += step
            elif k == Qt.Key.Key_Up:
                a.offset_y -= step
            elif k == Qt.Key.Key_Down:
                a.offset_y += step
            elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                a.scale = min(500, a.scale + (10 if step > 1 else 1))
            elif k == Qt.Key.Key_Minus:
                a.scale = max(10, a.scale - (10 if step > 1 else 1))
            elif k == Qt.Key.Key_R:
                a.offset_x, a.offset_y, a.scale = 0.0, 0.0, 100.0
            else:
                return super().keyPressEvent(e)
            self.win.on_cfg_edited(from_canvas=True)
            return
        if k == Qt.Key.Key_Left:
            c.offset_x -= step
        elif k == Qt.Key.Key_Right:
            c.offset_x += step
        elif k == Qt.Key.Key_Up:
            c.offset_y -= step
        elif k == Qt.Key.Key_Down:
            c.offset_y += step
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            c.scale = min(500, c.scale + (10 if step > 1 else 1))
        elif k == Qt.Key.Key_Minus:
            c.scale = max(10, c.scale - (10 if step > 1 else 1))
        elif k == Qt.Key.Key_R:
            c.reset_adjust()
        else:
            return super().keyPressEvent(e)
        self.win.on_cfg_edited(from_canvas=True)

    def focusNextPrevChild(self, nxt):  # deixa o Tab trocar de tela
        return False

    # ——— arrastar arquivo do Explorer
    @staticmethod
    def _image_from_mime(md):
        if md.hasUrls():
            for u in md.urls():
                pth = u.toLocalFile()
                if pth.lower().endswith(IMG_EXT):
                    return pth
        return None

    def dragEnterEvent(self, e):
        if self._image_from_mime(e.mimeData()):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self._image_from_mime(e.mimeData()):
            i = self.monitor_at(e.position())
            if i is not None and i != self.win.selected and not self.win.span_mode:
                self.win.select(i)
            e.acceptProposedAction()

    def dropEvent(self, e):
        pth = self._image_from_mime(e.mimeData())
        if not pth:
            return
        i = self.monitor_at(e.position())
        if i is not None:
            self.win.select(i)
        self.win.set_image(pth)
        e.acceptProposedAction()


class IdentifyOverlay(QWidget):
    """Número grande em cada tela, igual ao 'Identificar' do Windows."""

    def __init__(self, m: Monitor):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.m = m
        g: QRect = m.qscreen.geometry()
        self.resize(240, 240)
        self.move(g.x() + 48, g.y() + 48)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(15, 17, 21, 225))
        p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 22, 22)
        p.setPen(QColor("white"))
        f = QFont(self.font())
        f.setPointSize(84)
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect().adjusted(0, -20, 0, -20), Qt.AlignmentFlag.AlignCenter, str(self.m.index))
        f.setPointSize(10)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#aab2c5"))
        p.drawText(self.rect().adjusted(10, 160, -10, -10), Qt.AlignmentFlag.AlignHCenter,
                   f"{self.m.w}×{self.m.h}\n{self.m.name}")


# ════════════════════════════════════════════════════════════════════════════
#  Janela principal
# ════════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())      # canto da janela e barra de tarefas
        self.resize(1380, 820)
        self.store = ImageStore()
        self.monitors: list[Monitor] = []
        self.cfgs: dict[str, WallCfg] = {}
        self.span_cfg = WallCfg()
        self.span_adj: dict[str, SpanAdj] = {}   # ajuste só de uma tela no modo estendido
        self.span_mode = False
        self.selected = 0
        self.recents: list[str] = []
        self._overlays = []
        self._restoring = False

        self._load_config()
        self._build_ui()
        self._build_tray()

        self._save_timer = QTimer(self, singleShot=True, interval=700)
        self._save_timer.timeout.connect(self._commit)
        self._redetect_timer = QTimer(self, singleShot=True, interval=600)
        self._redetect_timer.timeout.connect(self.redetect)

        app = QGuiApplication.instance()
        app.screenAdded.connect(self._watch_screens)
        app.screenRemoved.connect(lambda *_: self._redetect_timer.start())
        self._watch_screens()

        self.redetect()
        self.history = [self._snapshot()]

    # ——— UI
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("toolbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(8)
        logo = QLabel("▣  Wallpaper Studio")
        logo.setObjectName("logo")
        h.addWidget(logo)
        h.addSpacing(14)

        self.btn_ind = QPushButton("Individual por tela")
        self.btn_span = QPushButton("Estender em todas")
        grp = QButtonGroup(self)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        for i, b in enumerate((self.btn_ind, self.btn_span)):
            b.setCheckable(True)
            b.setObjectName("segL" if i == 0 else "segR")
            _fit_bold(b)
            grp.addButton(b)
            seg.addWidget(b)
        h.addLayout(seg)
        h.addSpacing(14)
        self.btn_ind.setChecked(not self.span_mode)
        self.btn_span.setChecked(self.span_mode)
        self.btn_ind.clicked.connect(lambda: self.set_span(False))
        self.btn_span.clicked.connect(lambda: self.set_span(True))

        for text, tip, slot in (("⟳  Detectar telas", "Lê de novo monitores e resoluções", self.redetect),
                                ("Identificar", "Mostra o número em cada tela", self.identify),
                                ("↶  Desfazer", "Ctrl+Z", self.undo)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            h.addWidget(b)
        h.addStretch(1)
        b = QPushButton("Abrir perfil")
        b.clicked.connect(self.load_profile)
        h.addWidget(b)
        b = QPushButton("Salvar perfil")
        b.clicked.connect(self.save_profile)
        h.addWidget(b)
        self.btn_apply = QPushButton("✓  Aplicar no Windows" if IS_WIN else "✓  Gerar imagem")
        self.btn_apply.setObjectName("accent")
        _fit_bold(self.btn_apply)
        self.btn_apply.setToolTip("Ctrl+Enter")
        self.btn_apply.clicked.connect(self.apply)
        h.addWidget(self.btn_apply)
        root.addWidget(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = LayoutCanvas(self)
        split.addWidget(self.canvas)
        self.panel = PropertiesPanel(self.store)
        scroll = QScrollArea()
        scroll.setWidget(self.panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(360)
        scroll.setMaximumWidth(520)
        scroll.setObjectName("panelScroll")
        split.addWidget(scroll)
        split.setStretchFactor(0, 1)
        split.setSizes([1000, 400])
        root.addWidget(split, 1)
        self.setCentralWidget(central)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_lbl = QLabel("")
        self.status.addWidget(self.status_lbl)

        self.panel.changed.connect(lambda: self.on_cfg_edited(from_canvas=False))
        self.panel.choose_image.connect(self.choose_image)
        self.panel.remove_image.connect(lambda: self.set_image(""))
        self.panel.copy_to_all.connect(self.copy_to_all)
        self.panel.reset_adjust.connect(self.reset_adjust)
        self.panel.recent_picked.connect(self.set_image)
        self.panel.set_recents(self.recents)

        for seq, slot in (("Ctrl+Z", self.undo), ("Ctrl+O", self.choose_image),
                          ("Ctrl+Return", self.apply), ("F5", self.redetect)):
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(slot)
            self.addAction(a)

    def _build_tray(self):
        """Ícone perto do relógio: clique abre/traz a janela; menu com Abrir, Aplicar e Sair."""
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu(self)
        menu.addAction("Abrir Wallpaper Studio", self._show_front)
        menu.addAction("Aplicar no Windows" if IS_WIN else "Gerar imagem", self.apply)
        menu.addSeparator()
        menu.addAction("Sair", self.close)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self._show_front() if r in (QSystemTrayIcon.ActivationReason.Trigger,
                                                  QSystemTrayIcon.ActivationReason.DoubleClick)
            else None)
        self.tray.show()

    def _show_front(self):
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _watch_screens(self, *_):
        if not hasattr(self, "_watched"):
            self._watched = set()
        for s in QGuiApplication.screens():
            if id(s) not in self._watched:   # liga cada tela uma vez só
                self._watched.add(id(s))
                s.geometryChanged.connect(lambda *_a: self._redetect_timer.start())
                s.refreshRateChanged.connect(lambda *_a: self._redetect_timer.start())
        if _:
            self._redetect_timer.start()

    # ——— estado
    def active_cfg(self) -> WallCfg:
        if self.span_mode or not self.monitors:
            return self.span_cfg
        return self.cfgs[self.monitors[self.selected].device]

    def active_adj(self) -> "SpanAdj | None":
        """Ajuste só da tela escolhida (só existe no modo estendido)."""
        if not self.span_mode or not self.monitors:
            return None
        return self.span_adj.setdefault(self.monitors[self.selected].device, SpanAdj())

    def redetect(self):
        self.monitors = detect_monitors()
        for m in self.monitors:
            self.cfgs.setdefault(m.device, WallCfg())
        self.selected = min(self.selected, max(0, len(self.monitors) - 1))
        self.canvas._cache.clear()
        self.refresh_panel()
        self.canvas.update()
        minx, miny, bw, bh = virtual_bbox(self.monitors)
        parts = [f"{m.index}: {m.w}×{m.h}" + (f"@{m.hz}Hz" if m.hz else "") for m in self.monitors]
        self.status_lbl.setText(f"{len(self.monitors)} tela(s) detectada(s)  ·  área total {bw}×{bh} px"
                                f"  ·  " + "   ".join(parts))

    def select(self, i: int):
        self.selected = i
        self.refresh_panel()
        self.canvas.update()

    def refresh_panel(self):
        if not self.monitors:
            return
        if self.span_mode:
            _, _, bw, bh = virtual_bbox(self.monitors)
            m = self.monitors[self.selected]
            self.panel.set_target("Todas as telas — Estendido",
                                  f"Uma imagem sobre a área total de {bw}×{bh} px "
                                  f"({len(self.monitors)} telas). Clique numa tela para ajustar só ela.",
                                  self.span_cfg, True, self.active_adj(),
                                  f"Ajuste só da tela {m.index} ({m.w}×{m.h})")
        else:
            m = self.monitors[self.selected]
            sub = (f"{m.w}×{m.h} px" + (f" · {m.hz} Hz" if m.hz else "")
                   + f" · Escala {m.scale_pct}%\nPosição ({m.x}, {m.y})"
                   + (" · ★ Tela principal" if m.primary else ""))
            self.panel.set_target(f"Tela {m.index} — {m.name}", sub, self.cfgs[m.device], False)

    def on_cfg_edited(self, from_canvas=False):
        if from_canvas:
            self.panel.refresh_values()
        self.canvas.update()
        if not self._restoring:
            self._save_timer.start()

    def set_span(self, on: bool):
        self.span_mode = on
        if on and not self.span_cfg.image and self.monitors:
            self.span_cfg.image = self.cfgs[self.monitors[self.selected].device].image
        self.btn_span.setChecked(on)
        self.btn_ind.setChecked(not on)
        self.refresh_panel()
        self.on_cfg_edited()

    def set_image(self, path: str):
        if path:
            self.store.forget(path)
            if self.store.preview(path)[0] is None:
                QMessageBox.warning(self, APP_NAME, f"Não consegui abrir a imagem:\n{path}")
                return
            self.recents = [path] + [r for r in self.recents if r != path]
            self.recents = self.recents[:16]
            self.panel.set_recents(self.recents)
        self.active_cfg().image = path
        self.panel.refresh_values()
        self.on_cfg_edited()

    def choose_image(self):
        start = os.path.dirname(self.active_cfg().image) if self.active_cfg().image else str(Path.home() / "Pictures")
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher imagem", start,
            "Imagens (" + " ".join("*" + e for e in IMG_EXT) + ");;Todos os arquivos (*)")
        if path:
            self.set_image(path)

    def copy_to_all(self):
        src = self.active_cfg()
        for m in self.monitors:
            self.cfgs[m.device] = src.copy()
        self.refresh_panel()
        self.on_cfg_edited()
        self.status.showMessage("Configuração copiada para todas as telas.", 3000)

    def reset_adjust(self):
        self.active_cfg().reset_adjust()
        self.panel.refresh_values()
        self.on_cfg_edited()

    # ——— identificar
    def identify(self):
        for o in self._overlays:
            o.close()
        self._overlays = [IdentifyOverlay(m) for m in self.monitors if m.qscreen is not None]
        for o in self._overlays:
            o.show()
        QTimer.singleShot(2500, lambda: [o.close() for o in self._overlays])

    # ——— aplicar
    def apply(self):
        if not self.monitors:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            t0 = time.time()
            img = build_composite(self.monitors, self.cfgs, self.span_mode, self.span_cfg, self.store,
                                  self.span_adj)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            out = DATA_DIR / f"wallpaper_{int(time.time())}.png"   # nome novo força o Windows a recarregar
            if not img.save(str(out), "PNG", 90):
                raise OSError(f"não consegui gravar {out}")
            ok = set_windows_wallpaper_span(str(out)) if IS_WIN else True
            if ok:   # só apaga os antigos depois de o novo estar aplicado
                for old in DATA_DIR.glob("wallpaper_*.png"):
                    if old != out:
                        try:
                            old.unlink()
                        except OSError:
                            pass
            self._commit()
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, APP_NAME, f"Erro ao aplicar:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        dt = time.time() - t0
        if IS_WIN and ok:
            self.status.showMessage(f"Papel de parede aplicado ({img.width()}×{img.height()} px, "
                                    f"{dt:.1f}s).", 6000)
        elif IS_WIN:
            QMessageBox.warning(self, APP_NAME, "O Windows recusou o papel de parede.")
        else:
            QMessageBox.information(self, APP_NAME, f"Imagem gerada (fora do Windows não aplica):\n{out}")

    # ——— persistência
    def _to_dict(self, with_recents=True):
        d = {"version": 1, "span_mode": self.span_mode, "span": asdict(self.span_cfg),
             "monitors": {k: asdict(v) for k, v in self.cfgs.items()}}
        # números sempre como float (50 vs 50.0 mudaria o snapshot e travaria o desfazer)
        d["span_adj"] = {k: asdict(a) for k, a in self.span_adj.items() if not a.is_default()}
        for c in [d["span"], *d["monitors"].values(), *d["span_adj"].values()]:
            for k, v in c.items():
                if isinstance(v, int) and not isinstance(v, bool):
                    c[k] = float(v)
        if with_recents:
            d["recents"] = self.recents
        return d

    def _from_dict(self, d: dict, with_recents=True):
        if not isinstance(d, dict):
            raise ValueError("o arquivo não tem o formato esperado")
        mons = d.get("monitors", {})
        self.span_mode = d.get("span_mode", False) is True
        self.span_cfg = WallCfg.from_dict(d.get("span", {}))
        self.cfgs = ({k: WallCfg.from_dict(v) for k, v in mons.items()}
                     if isinstance(mons, dict) else {})
        for m in self.monitors:
            self.cfgs.setdefault(m.device, WallCfg())
        adj = d.get("span_adj", {})
        self.span_adj = ({k: SpanAdj.from_dict(v) for k, v in adj.items() if isinstance(k, str)}
                         if isinstance(adj, dict) else {})
        if with_recents:
            rec = d.get("recents", [])
            self.recents = [p for p in rec if isinstance(p, str)] if isinstance(rec, list) else []

    def _load_config(self):
        try:
            self._from_dict(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError):   # arquivo ausente, ilegível ou fora do formato: começa do zero
            pass

    def _snapshot(self):
        return json.dumps(self._to_dict(with_recents=False), sort_keys=True)

    def _commit(self):
        """Salva no disco e registra um ponto de desfazer."""
        self._save_timer.stop()
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(self._to_dict(), indent=2, ensure_ascii=False),
                                   encoding="utf-8")
        except OSError as e:
            print("Não salvei a configuração:", e)
        snap = self._snapshot()
        if not self.history or self.history[-1] != snap:
            self.history.append(snap)
            self.history = self.history[-100:]

    def undo(self):
        self._commit()
        if len(self.history) < 2:
            self.status.showMessage("Nada para desfazer.", 2000)
            return
        self.history.pop()
        self._restoring = True
        self._from_dict(json.loads(self.history[-1]), with_recents=False)
        self.btn_span.setChecked(self.span_mode)
        self.btn_ind.setChecked(not self.span_mode)
        self.refresh_panel()
        self.canvas.update()
        self._restoring = False
        self._commit()   # grava o estado desfeito (o snapshot é igual ao último, não duplica o histórico)

    def save_profile(self):
        path, _ = QFileDialog.getSaveFileName(self, "Salvar perfil", str(Path.home() / "wallpaper_perfil.json"),
                                              "Perfil (*.json)")
        if path:
            Path(path).write_text(json.dumps(self._to_dict(False), indent=2, ensure_ascii=False),
                                  encoding="utf-8")
            self.status.showMessage(f"Perfil salvo: {path}", 4000)

    def load_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir perfil", str(Path.home()), "Perfil (*.json)")
        if not path:
            return
        try:
            self._from_dict(json.loads(Path(path).read_text(encoding="utf-8")), with_recents=False)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, APP_NAME, f"Perfil inválido:\n{e}")
            return
        self.set_span(self.span_mode)
        self.status.showMessage(f"Perfil carregado: {Path(path).name}", 4000)

    def closeEvent(self, e):
        self._commit()
        if getattr(self, "tray", None) is not None:
            self.tray.hide()      # não deixa ícone fantasma na bandeja
        super().closeEvent(e)


# ════════════════════════════════════════════════════════════════════════════
STYLE = f"""
* {{ font-family: 'SF Pro Text', 'Segoe UI Variable Text', 'Segoe UI', sans-serif; font-size: 10pt; }}
QMainWindow, QWidget {{ background: #1c1c1e; color: #f5f5f7; }}
#toolbar {{ background: #232326; border-bottom: 1px solid #38383a; }}
#logo {{ font-size: 12pt; font-weight: 700; color: #ffffff; }}
QPushButton {{ background: #3a3a3c; border: none; border-radius: 9px;
               padding: 7px 14px; color: #f5f5f7; }}
QPushButton:hover {{ background: #48484a; }}
QPushButton:pressed {{ background: #2c2c2e; }}
QPushButton#accent {{ background: {ACCENT}; color: white; font-weight: 600; }}
QPushButton#accent:hover {{ background: #409cff; }}
QPushButton#accent:pressed {{ background: #0071e3; }}
QPushButton#segL {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
QPushButton#segR {{ border-top-left-radius: 0; border-bottom-left-radius: 0; }}
QPushButton#segL:checked, QPushButton#segR:checked {{ background: {ACCENT}; color: white; font-weight: 600; }}
QToolButton#mini {{ background: transparent; border: none; color: #98989f; padding: 0 4px; }}
QToolButton#mini:hover {{ color: white; }}
#panel {{ background: #232326; }}
#panelScroll {{ border: none; border-left: 1px solid #38383a; background: #232326; }}
#panelTitle {{ font-size: 13pt; font-weight: 700; color: white; }}
#muted {{ color: #98989f; font-size: 9pt; }}
#section {{ color: #8e8e93; font-size: 8pt; font-weight: 700; letter-spacing: 1px;
            padding-top: 10px; border-top: 1px solid #38383a; margin-top: 4px; }}
#rowLabel {{ color: #d1d1d6; }}
#thumb {{ background: #161618; border: 1px solid #38383a; border-radius: 12px; }}
#tips {{ color: #98989f; font-size: 8.5pt; background: #2c2c2e; border-radius: 12px; padding: 10px; }}
QLabel, QCheckBox {{ background: transparent; }}
QComboBox {{ background: #2c2c2e; border: 1px solid #48484a; border-radius: 8px;
               padding: 5px 10px; color: #f5f5f7; }}
QDoubleSpinBox {{ background: #2c2c2e; border: 1px solid #48484a; border-radius: 8px;
               padding: 2px 6px; color: #f5f5f7; min-height: 22px; }}
QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0px; height: 0px; border: none; }}
QComboBox QAbstractItemView {{ background: #2c2c2e; border: 1px solid #48484a; border-radius: 8px;
               selection-background-color: {ACCENT}; outline: none; }}
QSlider::groove:horizontal {{ height: 4px; background: #48484a; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 16px; height: 16px; margin: -6px 0;
               border-radius: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid #636366;
               background: #2c2c2e; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QListWidget {{ background: #161618; border: 1px solid #38383a; border-radius: 10px; padding: 4px; }}
QListWidget::item:selected {{ background: #0a3d73; border-radius: 8px; }}
QStatusBar {{ background: #232326; color: #98989f; border-top: 1px solid #38383a; }}
QStatusBar QLabel {{ background: transparent; color: #98989f; padding: 2px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #48484a; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QSplitter::handle {{ background: #38383a; width: 1px; }}
QToolTip {{ background: #2c2c2e; color: #f5f5f7; border: 1px solid #48484a; border-radius: 6px; padding: 4px; }}
QMenu {{ background: #2c2c2e; border: 1px solid #48484a; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QMenu::separator {{ height: 1px; background: #48484a; margin: 5px 8px; }}
QMessageBox {{ background: #2c2c2e; }}
"""


def main():
    if IS_WIN:
        try:  # ícone próprio na barra de tarefas
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("gian.wallpaperstudio")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
