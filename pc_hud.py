"""
HUD von Jarvis (Windows) im neuen Design: die goldene Daten-Kugel in der Mitte.

Zwei Modi (oben rechts umschalten, in den Einstellungen oder per Sprache "Fokus-Modus" / "Info-Modus"):
- INFO:  Kugel mit blauen Ringen, links Zeit, Wetter und System, rechts Termine, Lage und Verlauf,
         oben bis zu 12 frei belegbare Schnellstart-Knöpfe
- FOKUS: nur die große Kugel auf Schwarz, darunter, was gerade gesagt wird

Die Kugel atmet mit der Lautstärke (Mikrofon und Jarvis' Stimme). Öffnest du die Weltlage, löst sich ein
Datenpunkt aus der Kugel und fliegt hinaus, dann öffnet sich die Karte.

Das Fenster ist ein normales Programm-Fenster (Titelleiste in der HUD-Farbe), Größe frei änderbar.
"""

import ctypes
import datetime
import math
import os
import re
import shutil
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk

import pc_frameless
import pc_pill as P
import pc_remind
import pc_settings
import pc_settingsui
import pc_sphere
from pc_info import InfoWorker
from pc_perf import PerfWorker
from pc_settingsui import SettingsDialog
from pc_flugmode import FlugMixin

try:  # optional: für die Netzwerk-Anzeige (pip install psutil)
    import psutil
except Exception:  # noqa: BLE001
    psutil = None

HUD_BUTTONS = pc_settings.DEFAULT_BUTTONS
BASE_W, BASE_H = 1600, 900  # Entwurfsgröße (wie die Vorschaubilder), alles skaliert mit
MIN_W, MIN_H = 960, 560
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
STATE_TEXT = {"idle": "bereit · sag „{w}“", "listening": "hört zu …", "thinking": "denkt nach …",
              "speaking": "spricht …", "error": "Fehler"}


def hexc(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb[:3])


def short(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"




def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


# --- Systemwerte (ohne Zusatzpakete über Windows-Funktionen) ----------------
class _FILETIME(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


class _MEMSTATUS(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class Stats:
    def __init__(self):
        self._k32 = ctypes.windll.kernel32
        self._k32.GetTickCount64.restype = ctypes.c_ulonglong
        self._last = self._times()
        self._net_last = None

    def _times(self):
        idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
        self._k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        val = lambda f: (f.hi << 32) | f.lo  # noqa: E731
        return val(idle), val(kern), val(user)

    def cpu(self) -> float:
        idle, kern, user = self._times()
        li, lk, lu = self._last
        self._last = (idle, kern, user)
        total = (kern - lk) + (user - lu)  # Kernel-Zeit enthält die Leerlaufzeit
        if total <= 0:
            return 0.0
        return max(0.0, min(1.0, (total - (idle - li)) / total))

    def ram(self) -> float:
        ms = _MEMSTATUS()
        ms.dwLength = ctypes.sizeof(ms)
        self._k32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return ms.dwMemoryLoad / 100.0

    def mem_info(self):
        ms = _MEMSTATUS()
        ms.dwLength = ctypes.sizeof(ms)
        self._k32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return ms.ullTotalPhys, ms.ullAvailPhys

    def uptime_text(self) -> str:
        sec = int(self._k32.GetTickCount64() / 1000)
        return f"Laufzeit {sec // 86400}d {sec % 86400 // 3600}h {sec % 3600 // 60}min"

    def drives(self, limit: int = 3):
        out = []
        mask = self._k32.GetLogicalDrives()
        for i in range(26):
            if not (mask >> i) & 1:
                continue
            letter = chr(65 + i)
            path = f"{letter}:\\"
            try:
                if self._k32.GetDriveTypeW(path) != 3:  # nur feste Laufwerke
                    continue
                u = shutil.disk_usage(path)
                out.append((letter, u.total, u.free))
            except Exception:  # noqa: BLE001
                continue
            if len(out) >= limit:
                break
        return out

    def net_text(self):
        if not psutil:
            return None
        try:
            c = psutil.net_io_counters()
            now = time.time()
            if self._net_last is None:
                self._net_last = (c.bytes_sent, c.bytes_recv, now)
                return "Netz  ↑ 0 B/s  ↓ 0 B/s"
            ls, lr, lt = self._net_last
            dt = max(0.1, now - lt)
            self._net_last = (c.bytes_sent, c.bytes_recv, now)
            return f"Netz  ↑ {fmt_bytes((c.bytes_sent - ls) / dt)}/s  ↓ {fmt_bytes((c.bytes_recv - lr) / dt)}/s"
        except Exception:  # noqa: BLE001
            return None




# --- Hintergrund (wird nur bei Größe, Modus oder Farbe neu gerechnet) ------------------------
def _font(size, bold=False):
    from PIL import ImageFont

    for name in (("segoeuib.ttf", "seguisb.ttf") if bold else ("segoeui.ttf",)) + ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_info_background(W, H, sc, ox, oy, cyan, cards, cx, cy):
    """Dunkelblau mit Vignette, blauen HUD-Ringen, Schaltkreis-Linien und den Kartenrahmen."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    v = 1 - 0.55 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    v = np.clip(v, 0, 1)
    base = np.stack([2 + 0 * v, 8 + 10 * v, 14 + 22 * v], -1)
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(4)
    for _ in range(int(140 * sc)):  # feine Sternchen
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        b = int(rng.uniform(40, 110))
        d.point((x, y), fill=(int(b * cyan[0] / 255), int(b * cyan[1] / 255), int(b * cyan[2] / 255)))
    S = lambda v: v * sc  # noqa: E731
    dim = tuple(int(c * 0.45) for c in cyan)
    vdim = tuple(int(c * 0.22) for c in cyan)
    ring = Image.new("RGB", (W, H), (0, 0, 0))
    rd = ImageDraw.Draw(ring)
    for r, w, segs, col in ((410, 2, 3, dim), (380, 1, 0, vdim), (300, 2, 9, dim), (285, 1, 0, vdim)):
        R = S(r)
        box = (cx - R, cy - R, cx + R, cy + R)
        if segs == 0:
            rd.ellipse(box, outline=col, width=max(1, int(w * sc)))
        else:
            for k in range(segs):
                a0 = k * 360 / segs + rng.uniform(0, 20)
                rd.arc(box, a0, a0 + 360 / segs * rng.uniform(0.35, 0.7), fill=col, width=max(1, int(w * sc)))
    for a in range(0, 360, 3):  # Teilstriche
        r0, r1 = S(392), S(398 if a % 15 else 405)
        ra = math.radians(a)
        rd.line((cx + math.cos(ra) * r0, cy + math.sin(ra) * r0, cx + math.cos(ra) * r1, cy + math.sin(ra) * r1), fill=vdim)
    for side in (-1, 1):  # Schaltkreis-Leitungen zu den Karten
        for i in range(9):
            y = cy - S(160) + i * S(40) + rng.uniform(-6, 6) * sc
            x0 = cx + side * S(420)
            x1 = x0 + side * rng.uniform(20, 50) * sc
            x2 = x1 + side * S(14)
            y2 = y + rng.choice([-16, 0, 16]) * sc
            x3 = x2 + side * rng.uniform(20, 46) * sc
            rd.line((x0, y, x1, y, x2, y2, x3, y2), fill=dim, width=1)
            rd.ellipse((x3 - 2.5 * sc, y2 - 2.5 * sc, x3 + 2.5 * sc, y2 + 2.5 * sc), outline=cyan)
    glow = ring.filter(ImageFilter.GaussianBlur(max(2, 6 * sc)))
    arr = np.asarray(img, np.int32) + np.asarray(ring, np.int32) + (np.asarray(glow, np.int32) * 0.8).astype(np.int32)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    m = Image.new("L", (W, H), 0)  # warmes Leuchten hinter der Kugel (wie im Vorschaubild)
    ImageDraw.Draw(m).ellipse((cx - S(300), cy - S(300), cx + S(300), cy + S(300)), fill=110)
    m = m.filter(ImageFilter.GaussianBlur(S(135)))
    img = Image.composite(Image.new("RGB", (W, H), (70, 36, 0)), img, m)
    d = ImageDraw.Draw(img)
    for (x0, y0, x1, y1) in cards:  # Kartenrahmen
        d.rounded_rectangle((x0, y0, x1, y1), radius=int(14 * sc), outline=tuple(int(c * 0.6) for c in cyan),
                            width=max(1, int(sc)), fill=(4, 12, 20))
        d.line((x0 + 14 * sc, y0, x0 + 70 * sc, y0), fill=cyan, width=max(2, int(3 * sc)))
    return img


def make_dark_background(W, H, glows):
    """Schwarz mit weichem, warmem Leuchten (glows = [(x, y, Radius, Farbe, Stärke)])."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    for x, y, r, col, a in glows:
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).ellipse((x - r, y - r, x + r, y + r), fill=a)
        m = m.filter(ImageFilter.GaussianBlur(max(4, r * 0.45)))
        img = Image.composite(Image.new("RGB", (W, H), col), img, m)
    return img


class HudWindow(FlugMixin):
    def __init__(self, root: tk.Tk, k: float, on_command, get_settings, on_save_settings, on_width):
        self.root, self.k = root, k
        self.on_command, self.get_settings = on_command, get_settings
        self.on_save_settings, self.on_width = on_save_settings, on_width
        self.on_globe = None
        self.map = None  # Satellitenkarte (pc_map.GlobeWindow), wird vom Programm gesetzt
        self.lage_view = "globus"  # rechts im Lage-Screen: "globus" (Hologramm) oder "satellit"
        self._lage_place = None  # None = normale Lage, sonst ein Lieblingsort ("Seoul")
        self._place_data = None
        s = get_settings()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w = int(min(max(MIN_W * k, s.get("hud_width", 1280) * k), sw * 0.94))
        h = int(min(w * BASE_H / BASE_W, sh * 0.88))
        self.win = tk.Toplevel(root)
        self.win.title("Jarvis")
        self.win.configure(bg="#02080e")
        self.win.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - int(20 * k))}")
        self.win.minsize(int(MIN_W * k * 0.8), int(MIN_H * k * 0.8))
        self.win.protocol("WM_DELETE_WINDOW", self.minimize)
        self.win.bind("<Map>", self._on_map)
        self.win.bind("<Unmap>", self._on_unmap)
        self.win.bind("<Configure>", self._on_configure)
        try:
            self._icon = ImageTk.PhotoImage(P.make_app_icon(64))
            self.win.iconphoto(True, self._icon)
        except Exception:  # noqa: BLE001
            pass
        self.c = tk.Canvas(self.win, bg="#02080e", highlightthickness=0, bd=0)
        self.c.pack(fill="both", expand=True)

        self.stats = Stats()
        self.worker = InfoWorker(get_settings, self.is_visible)
        self.worker.start()
        self.perf = PerfWorker(get_settings, self.is_visible)
        self.perf.start()
        self.sphere = pc_sphere.SphereFrames(os.path.join(pc_settings.base_dir(), "globus", "kugel"))
        self.sphere.start(s.get("sphere_color", "Gold"))
        self._sph_photos: list = []
        self._sph_size = 0
        self._sph_t = 0.0
        self._halo_photos: list = []
        self.state = "idle"
        self.status_text = "bereit"
        self.log: list = []
        self.shown = False
        self.animate = True
        self.pulse_t = 0.0
        self._last_tick = time.time()
        self._tick_job = self._slow_job = self._cfg_job = None
        self._dialog = None
        self._build_sig = None
        self._data = {"termine": [], "lage": None}
        self._launch = None
        self._sigs: dict = {}
        self.f = {}
        for key, fam, size, wt in (("big", "Segoe UI Semibold", 34, "normal"), ("huge", "Segoe UI Semibold", 30, "normal"),
                                   ("head", "Segoe UI Semibold", 11, "normal"), ("text", "Segoe UI", 11, "normal"),
                                   ("small", "Segoe UI", 9, "normal"), ("btn", "Segoe UI Symbol", 15, "normal"),
                                   ("name", "Segoe UI Semibold", 17, "normal"), ("say", "Segoe UI", 14, "normal"),
                                   ("tiny", "Segoe UI", 8, "normal"), ("label", "Segoe UI Semibold", 10, "normal"),
                                   ("city", "Segoe UI", 9, "normal")):
            self.f[key] = tkfont.Font(family=fam, size=size, weight=wt)
        threading.Thread(target=self._data_loop, daemon=True).start()
        self._build()
        self.win.withdraw()

    # --- Öffentlich (nur im Tk-Thread aufrufen) ---
    def show(self):
        self.win.deiconify()
        self._color_bar()
        self.win.lift()
        if not getattr(self, "_maxed", False):  # groß: nicht über die Taskleiste legen
            self.win.attributes("-topmost", True)
            self.win.after(400, lambda: self.win.attributes("-topmost", bool(self.get_settings().get("hud_topmost"))))
        else:
            self.win.focus_force()

    def hide(self):
        self.win.withdraw()

    def minimize(self):
        self.win.iconify()

    def is_visible(self) -> bool:
        return self.shown

    def is_foreground(self) -> bool:
        if not self.shown:
            return False
        try:
            return self.win.focus_displayof() is not None
        except Exception:  # noqa: BLE001
            return False

    def set_state(self, state: str):
        self.state = state if state in STATE_TEXT else "idle"
        self._update_status()

    def set_status(self, text: str):
        self.status_text = text[:160]
        self._update_status()

    def add_log(self, role: str, text: str):
        self.log.append((role, text))
        self.log = self.log[-8:]
        self._sigs.pop("verlauf", None)

    def apply_settings(self, s: dict):
        if self._signature() != self._build_sig:
            self._build()
        self.animate = bool(s.get("hud_animation", True))
        self.win.attributes("-alpha", max(0.4, min(1.0, float(s.get("hud_alpha", 100)) / 100.0)))
        self.win.attributes("-topmost", bool(s.get("hud_topmost")) and not getattr(self, "_maxed", False))
        self.update_new_dot()
        self.worker.refresh_weather()

    def set_mode(self, mode: str):
        if mode in ("fokus", "info", "lage", "flug") and mode != self.get_settings().get("hud_mode", "info"):
            s = dict(self.get_settings())
            s["hud_mode"] = mode
            self.on_save_settings(s)

    def open_settings(self):
        if self._dialog and self._dialog.exists():
            self._dialog.lift()
            return
        self._dialog = SettingsDialog(self.win, self.get_settings(), self.on_save_settings, on_seen=self._on_seen,
                                      on_globe=lambda: self.on_globe and self.on_globe())

    def update_new_dot(self):
        try:
            show = pc_settingsui.has_unseen(self.get_settings())
            self.c.itemconfigure("newdot", state="normal" if show else "hidden")
        except Exception:  # noqa: BLE001
            pass

    def launch(self, callback):
        """Weltlage: ein Datenpunkt löst sich aus der Kugel und fliegt hinaus, danach callback()."""
        if not self.shown or not self.animate or self.win.state() == "iconic":
            callback()
            return
        self._launch = (time.time(), callback)

    # --- intern ---
    def _signature(self):
        s = self.get_settings()
        return (P.HUE_SHIFT, repr(s.get("hud_buttons")), s.get("assistant_name"), s.get("hud_mode", "info"),
                s.get("sphere_color", "Gold"), s.get("weather_city"), tuple(s.get("wake_words") or []))

    def _on_seen(self, seen: list):
        s = dict(self.get_settings())
        s["seen_new"] = list(seen)
        self.on_save_settings(s)
        self.update_new_dot()

    def _color_bar(self):
        bg = "#000000" if self.mode in ("fokus", "lage", "flug") else "#02080e"
        pc_frameless.color_titlebar(self.win, bg, "#7fb3c8")

    def _buttons(self):
        out = []
        own = self.get_settings().get("hud_buttons")
        for item in (HUD_BUTTONS if own is None else own):
            try:
                glyph, label, cmd = item[0], item[1], item[2]
            except Exception:  # noqa: BLE001
                continue
            if label and cmd:
                out.append((glyph or str(label)[:1].upper(), label, cmd))
        return out[:12]

    def _hand(self, tag):
        self.c.tag_bind(tag, "<Enter>", lambda e: self.c.config(cursor="hand2"), add="+")
        self.c.tag_bind(tag, "<Leave>", lambda e: self.c.config(cursor=""), add="+")

    def _on_configure(self, e):
        if e.widget is not self.win:
            return
        try:
            st = self.win.state()
        except Exception:  # noqa: BLE001
            st = "normal"
        if st == "zoomed" and not getattr(self, "_fixing_max", False):
            self._fixing_max = True
            self.win.after(10, self._fit_work_area)
        elif st == "normal" and not getattr(self, "_maxed", False):
            self._normal_geo = self.win.geometry()
        if self._cfg_job:
            self.win.after_cancel(self._cfg_job)
        self._cfg_job = self.win.after(200, self._resized)

    def _fit_work_area(self):
        """Maximieren: genau die freie Bildschirmfläche nehmen, ohne die Taskleiste zu berühren (sonst versteckt
        Windows die Taskleiste und sie kommt nur noch hoch, wenn man mit der Maus nach unten fährt).
        Ein zweiter Klick auf Maximieren holt die alte Größe zurück."""
        try:
            wa = pc_frameless.work_area()
            if not wa:
                return
            if getattr(self, "_maxed", False):  # schon groß -> zurück zur alten Größe
                self._maxed = False
                self.win.state("normal")
                if getattr(self, "_normal_geo", None):
                    self.win.geometry(self._normal_geo)
                return
            x, y, w, h = wa
            self.win.state("normal")
            self.win.update_idletasks()
            bx = max(0, self.win.winfo_rootx() - self.win.winfo_x())
            top = max(0, self.win.winfo_rooty() - self.win.winfo_y())
            self._maxed = True
            self.win.geometry(f"{max(400, w - 2 * bx)}x{max(300, h - top - bx)}+{x}+{y}")
            self.win.attributes("-topmost", False)
        except Exception as e:  # noqa: BLE001
            print(f"Maximieren: {e}")
        finally:
            self.win.after(300, lambda: setattr(self, "_fixing_max", False))

    def _resized(self):
        self._cfg_job = None
        w, h = self.c.winfo_width(), self.c.winfo_height()
        if (w, h) != getattr(self, "_size", None) and w > 200 and h > 200:
            self._build()
            if self.win.state() == "normal" and not getattr(self, "_maxed", False):
                self.on_width(int(w / self.k))

    # --- Aufbau ---
    def _build(self):
        self._build_sig = self._signature()
        s_ = self.get_settings()
        prev_mode = getattr(self, "mode", None)
        self.mode = s_.get("hud_mode", "info") if s_.get("hud_mode") in ("info", "fokus", "lage", "flug") else "info"
        fokus = self.mode == "fokus"
        lage = self.mode in ("lage", "flug")  # Flugverkehr nutzt denselben Globus
        if not lage and self.map is not None and self.map.is_open() and self.map.region:
            self.map.on_close = None  # Lage-Screen verlassen: Satellitenbild rechts schließen
            self.map.close()
        dark = fokus or lage
        self.win.update_idletasks()
        W, H = max(400, self.c.winfo_width()), max(300, self.c.winfo_height())
        self._size = (W, H)
        sc = min(W / BASE_W, H / BASE_H)
        ox, oy = (W - BASE_W * sc) / 2, (H - BASE_H * sc) / 2
        self.sc, self.ox, self.oy = sc, ox, oy
        X = lambda v: ox + v * sc  # noqa: E731
        Y = lambda v: oy + v * sc  # noqa: E731
        S = lambda v: v * sc  # noqa: E731
        for key, base in (("big", 34), ("huge", 30), ("head", 11), ("text", 11), ("small", 9), ("btn", 15), ("name", 17),
                          ("say", 14), ("tiny", 8)):
            self.f[key].configure(size=max(6, int(round(base * sc * 1.25 if key in ("text", "small", "tiny", "head") else base * sc))))
        c = self.c
        c.delete("all")
        self._sigs = {}
        self.cyan = P.shift_rgb((60, 200, 255))
        CY, CYD = hexc(self.cyan), hexc(tuple(int(v * 0.55) for v in self.cyan))
        self.hot = pc_sphere.COLORS.get(s_.get("sphere_color", "Gold"), pc_sphere.COLORS["Gold"])[1]
        GOLD = hexc(self.hot)
        TXT, DIM = "#c8e6f5", hexc(tuple(int(v * 0.75) for v in self.cyan))
        self.colors = dict(cyan=CY, cyand=CYD, gold=GOLD, txt=TXT, dim=DIM)
        flug = self.mode == "flug"
        self.cx, self.cy = (W / 2, H * 0.45) if fokus else (X(230), Y(390)) if flug else (X(380), Y(470)) if lage \
            else (X(800), Y(450))

        # Hintergrund
        cards_l = [(30, 100, 360, 260), (30, 276, 360, 560), (30, 576, 360, 860)]
        cards_r = [(1240, 100, 1570, 330), (1240, 346, 1570, 620), (1240, 636, 1570, 860)]
        if dark:  # Schwarz mit warmem Leuchten hinter Kugel (und Globus) wie in den Vorschaubildern
            c.configure(bg="#000000")
            self.win.configure(bg="#000000")
            glows = [(self.cx, self.cy, (min(W, H) * 0.42) if fokus else S(240), (60, 28, 0), 125)]
            if flug:
                glows[0] = (self.cx, self.cy, S(170), (60, 28, 0), 125)
                glows.append((X(800), Y(480), S(280), (60, 26, 0), 80))
                glows.append((X(800), Y(480), S(360), (0, 22, 38), 45))
                glows.append((X(1370), Y(490), S(260), (0, 18, 30), 60))
            elif lage:
                glows.append((X(1060), Y(470), S(300), (70, 30, 0), 95))
                glows.append((X(230), Y(740), S(240), (0, 26, 44), 110))  # kühles Blau unten links (Karte)
                glows.append((X(1060), Y(470), S(380), (0, 22, 38), 40))
            self._bg_img = make_dark_background(W, H, glows)  # bleibt für den Lage-Globus (wird daraufgerechnet)
            self._bg_photo = ImageTk.PhotoImage(self._bg_img)
            c.create_image(0, 0, anchor="nw", image=self._bg_photo)
        else:
            c.configure(bg="#02080e")
            self.win.configure(bg="#02080e")
            boxes = [(X(a), Y(b), X(cc), Y(d)) for a, b, cc, d in cards_l + cards_r]
            bg = make_info_background(W, H, sc, ox, oy, self.cyan, boxes, self.cx, self.cy)
            self._bg_photo = ImageTk.PhotoImage(bg)
            c.create_image(0, 0, anchor="nw", image=self._bg_photo)
        self._color_bar()

        # drehende Ringe (Info)
        self.arcs = []
        if not dark:
            for r, wd, specs, speed, col in ((350, 5, [(0, 70), (120, 70), (240, 70)], 12, CY),
                                             (330, 2, [(i * 45, 26) for i in range(8)], -18, CYD)):
                R = S(r)
                for off, ext in specs:
                    item = c.create_arc(self.cx - R, self.cy - R, self.cx + R, self.cy + R, start=off, extent=ext,
                                        style="arc", width=max(1, int(wd * sc)), outline=col)
                    self.arcs.append((item, off, speed))
            self.phase = 0.0

        # Kugel
        D = int(min(W, H) * 0.80) if fokus else int(S(300)) if flug else int(S(470)) if lage else int(S(560))
        if D != self._sph_size or self.sphere.color != s_.get("sphere_color", "Gold"):
            self._sph_photos, self._halo_photos, self._sph_size = [], [], D
        self.sphere.start(s_.get("sphere_color", "Gold"))
        if not self._halo_photos:
            halo = pc_sphere.make_halo(D, self.sphere.color)
            for kk in (0.35, 0.55, 0.75, 0.95, 1.15):
                img = halo.point(lambda v, kk=kk: min(255, int(v * kk)))
                rgba = img.convert("RGBA")
                rgba.putalpha(img.convert("L"))
                self._halo_photos.append(ImageTk.PhotoImage(rgba))
        self.halo_item = c.create_image(self.cx, self.cy, image=self._halo_photos[1])
        self.sphere_item = c.create_image(self.cx, self.cy, image=self._sph_photos[0] if self._sph_photos else "")
        self.wave_item = c.create_line(0, 0, 0, 0, fill=GOLD, width=max(1, int(2 * sc)), smooth=True, state="hidden")
        self._sph_r = D * 0.47
        self.launch_items = [c.create_line(0, 0, 0, 0, fill=GOLD, width=max(1, int(3 * sc)), smooth=True,
                                           state="hidden"),
                             c.create_oval(0, 0, 0, 0, outline=GOLD, width=max(1, int(2 * sc)), state="hidden")]

        # Name und Status unter der Kugel
        name = s_.get("assistant_name") or "J.A.R.V.I.S."
        if fokus:  # zweiter, ruhiger Ring wie im Vorschaubild
            r2 = D * 0.49
            c.create_oval(self.cx - r2, self.cy - r2, self.cx + r2, self.cy + r2, outline="#7a4c10", width=1)
        if lage:
            ty = self.cy + D * 0.47
            c.create_text(self.cx, ty, text=name, fill=GOLD, font=self.f["head"])
            self.t_state = c.create_text(self.cx, ty + S(22), text="", fill="#c89a58", font=self.f["tiny"])
            self.t_say = c.create_text(X(800), Y(884), text="", fill="#ffe1b4", font=self.f["small"], width=int(S(900)))
        elif fokus:
            ty = self.cy + D * 0.47 + S(10)
            c.create_text(self.cx, ty, text=name, fill=GOLD, font=self.f["name"])
            self.t_state = c.create_text(self.cx, ty + S(30), text="", fill="#c89a58", font=self.f["small"])
            self.t_say = c.create_text(self.cx, ty + S(62), text="", fill="#ffe1b4", font=self.f["say"],
                                       width=int(W * 0.75), justify="center")
        else:
            c.create_text(X(800), Y(830), text=name, fill=GOLD, font=self.f["name"])
            self.t_state = c.create_text(X(800), Y(858), text="", fill=CY, font=self.f["small"])
            self.t_say = c.create_text(X(800), Y(884), text="", fill=TXT, font=self.f["small"], width=int(S(820)))
        self._update_status()

        # Kopfzeile: Zahnrad, Lage, Knöpfe, Modus
        if dark:  # auf Schwarz: Blau gedämpft, damit nur die Kugel leuchtet
            CY, CYD = hexc(tuple(int(v * 0.42) for v in self.cyan)), hexc(tuple(int(v * 0.22) for v in self.cyan))
        r = S(24)
        gx, gy = (X(52), Y(54)) if not dark else (S(40), S(40))
        c.create_oval(gx - r, gy - r, gx + r, gy + r, outline=CYD, width=max(1, int(2 * sc)),
                      fill="#010508" if dark else "#03101a", tags="gear")
        c.create_text(gx, gy, text="⚙", fill=CY, font=self.f["btn"], tags="gear")
        c.create_oval(gx + r * 0.45, gy - r * 1.15, gx + r * 0.95, gy - r * 0.65, fill="#ff5a5a", outline="",
                      tags=("gear", "newdot"), state="hidden")
        c.tag_bind("gear", "<Button-1>", lambda e: self.open_settings())
        self._hand("gear")
        row = [("◍", "Lage", None), ("✆", "Reden", "lass uns reden")] + self._buttons()  # Reden = Live-Gespräch
        if fokus:
            row = row[:2]
        elif lage:
            row = []
        n = len(row)
        step = min(72.0, 860.0 / max(1, n))
        for i, (glyph, label, cmd) in enumerate(row):
            if fokus:
                bx, by = gx + S(64) * (i + 1), gy
            else:
                bx, by = X(800 + (i - (n - 1) / 2) * step), Y(54)
            tag = f"b{i}"
            col = GOLD if cmd is None else "#96dcfa"
            c.create_oval(bx - r, by - r, bx + r, by + r, outline=CYD, width=max(1, int(2 * sc)),
                          fill="#010508" if dark else "#03101a", tags=tag)
            c.create_text(bx, by, text=glyph, fill=col, font=self.f["btn"], tags=tag)
            if not fokus:
                c.create_text(bx, by + r + S(12), text=short(label, 11), fill=DIM, font=self.f["tiny"], tags=tag)
            if cmd is None:  # Lage-Modus (Globus wie im Vorschaubild 3)
                c.tag_bind(tag, "<Button-1>", lambda e: self.set_mode("lage"))
            else:
                c.tag_bind(tag, "<Button-1>", lambda e, cmd=cmd: self.on_command(cmd))
            self._hand(tag)
        # Modus-Umschalter oben rechts: FOKUS · INFO · LAGE
        accent = "#ffb446" if dark else CY
        for i, (icon, label, mode) in enumerate((("◉", "FOKUS", "fokus"), ("▦", "INFO", "info"), ("◍", "LAGE", "lage"),
                                                 ("✈", "FLUG", "flug"))):
            on = mode == self.mode
            x1 = W - S(20) - (3 - i) * S(118)
            x0, y0, y1 = x1 - S(108), (S(22) if dark else Y(38)), (S(22) if dark else Y(38)) + S(32)
            tag = f"mode_{mode}"
            self._pill(x0, y0, x1, y1, ("#3a2608" if dark else "#0a3348") if on else ("#0c0c10" if dark else "#03101a"),
                       accent if on else ("#46402c" if dark else CYD), tag)
            c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=f"{icon}  {label}", font=self.f["small"],
                          fill=accent if on else ("#968264" if dark else DIM), tags=tag)
            c.tag_bind(tag, "<Button-1>", lambda e, mode=mode: self.set_mode(mode))
            self._hand(tag)
        # (der alte "Oben"-Pfeil ist weg; "immer im Vordergrund" gibt es weiter in den Einstellungen)

        # Karten (nur Info)
        self.cards = {}
        if lage:
            if prev_mode != self.mode:
                self._flug_entered = False
            self._build_lage(W, H, X, Y, S, prev_mode not in ("lage", "flug"))
        if not dark:
            for key, (x0, y0, x1, y1), title in (("zeit", cards_l[0], "ZEIT"), ("wetter", cards_l[1], "WETTER"),
                                                  ("system", cards_l[2], "SYSTEM"), ("termine", cards_r[0], "TERMINE"),
                                                  ("lage", cards_r[1], "LAGE"), ("verlauf", cards_r[2], "VERLAUF")):
                box = (X(x0), Y(y0), X(x1), Y(y1))
                self.cards[key] = box
                c.create_text(box[0] + S(16), box[1] + S(14), text=title, fill=CY, font=self.f["head"], anchor="nw",
                              tags=f"title_{key}")
            # Systemzeilen (Balken werden nur verschoben)
            x0, y0, x1, _ = self.cards["system"]
            self.sys_rows = []
            for i, label in enumerate(("CPU", "RAM", "GPU", "C:", "Netz")):
                y = y0 + S(52) + i * S(48)
                c.create_text(x0 + S(16), y, text=label, fill=TXT, font=self.f["text"], anchor="w")
                val = c.create_text(x1 - S(16), y, text="", fill=GOLD, font=self.f["text"], anchor="e")
                bx0, bx1 = x0 + S(16), x1 - S(16)
                c.create_rectangle(bx0, y + S(14), bx1, y + S(20), outline=CYD)
                bar = c.create_rectangle(bx0, y + S(14), bx0, y + S(20), fill=CY, outline="")
                self.sys_rows.append((val, bar, bx0, bx1, y))
            c.tag_bind("title_lage", "<Button-1>", lambda e: self.on_globe and self.launch(self.on_globe))
        self._raise_top()
        self.update_new_dot()
        self._slow(force=True)

    def _pill(self, x0, y0, x1, y1, fill, outline, tag):
        c, r = self.c, (y1 - y0) / 2
        pts = []
        for a in range(90, 271, 15):
            pts += [x0 + r + r * math.cos(math.radians(a)), y0 + r - r * math.sin(math.radians(a))]
        for a in range(-90, 91, 15):
            pts += [x1 - r + r * math.cos(math.radians(a)), y0 + r - r * math.sin(math.radians(a))]
        c.create_polygon(pts, fill=fill, outline=outline, width=1, smooth=False, tags=tag)

    def _raise_top(self):
        for tag in ("gear", "mode_fokus", "mode_info", "mode_lage", "mode_flug", "lagecard", "lagetog", "lagechip", "lagezoom"):
            self.c.tag_raise(tag)

    def _toggle_topmost(self):
        s = dict(self.get_settings())
        s["hud_topmost"] = not s.get("hud_topmost")
        self.on_save_settings(s)
        self.c.itemconfigure(self.pin, fill=self.colors["cyan"] if s["hud_topmost"] else self.colors["dim"])

    def _update_status(self):
        try:
            words = self.get_settings().get("wake_words") or ["jarvis"]
            st = STATE_TEXT.get(self.state, "").replace("{w}", words[0].title())
            self.c.itemconfigure(self.t_state, text=st)
            say = self.status_text
            say = "" if say in ("bereit", "abgebrochen") or say.startswith(("Bereit", "Starte")) else say
            self.c.itemconfigure(self.t_say, text=short(say, 180))
        except Exception:  # noqa: BLE001
            pass

    # --- Lage-Modus (Vorschaubild 3): Kugel links, Datenstrang, Hologramm-Globus rechts -------------
    LAGE_HOME = (48.8003, 9.0144)

    def _build_lage(self, W, H, X, Y, S, reveal):
        import pc_lage

        c = self.c
        flug = self.mode == "flug"
        G = int(S(600 if flug else 640))
        self.lg = dict(cx=X(800 if flug else 1060), cy=Y(480 if flug else 470), size=G, R=G * 0.42, X=X, Y=Y, S=S)
        if not hasattr(self, "lage_cam"):
            self.lage_cam = [45.0, 12.0]
            self.lage_sel = None
            self._lage_img = None
            self._lage_key = None
            self._lage_job = None
            self._lage_anim = None
            self._lage_tour = []
            self._lage_drag = None
        if not hasattr(self, "lage_zoom"):
            self.lage_zoom = 1.0
            self._zoom_goal = None
            self._lage_spinning = False
            self._lage_touch = time.time()  # letzte Bedienung (danach dreht sich die Erde langsam weiter)
            pc_lage.ON_TILE = self._lage_tile_ready
        pc_lage.land_mask()
        pc_lage.night_texture()
        if self.lage_view == "satellit":
            pc_lage.sat_texture()
        gold = self.colors["gold"]
        # Datenstrang von der Kugel zum Globus
        pts = []
        sx, sy = self.cx + S(90), self.cy - S(50)
        ex, ey = self.lg["cx"] - self.lg["R"] - S(20), self.lg["cy"]
        for k in range(61):
            u = k / 60
            pts += [sx + (ex - sx) * u, sy + (ey - sy) * u - S(170) * math.sin(math.pi * u)]
        self.lg["trail"] = pts
        self.lage_trail = c.create_line(*pts, fill="#6a4a18", width=max(1, int(S(2))), smooth=True, tags="lagegfx")
        self.lage_pulse = c.create_oval(0, 0, 0, 0, fill=gold, outline="", tags="lagegfx")
        self.lage_end = [c.create_oval(ex - r, ey - r, ex + r, ey + r, outline=col, width=2, tags="lagegfx")
                         for r, col in ((S(22), "#3cc8ff"), (S(14), gold), (S(7), gold))]
        # Globus
        self.lage_item = c.create_image(self.lg["cx"], self.lg["cy"], image="", tags="lagegfx")
        # öffnende Klammern um den Globus
        self.lage_brackets = []
        for k in range(3):
            a = int(200 * (1 - k * 0.3))
            col = hexc((a, int(a * 0.62), int(a * 0.2))) if k < 2 else "#2a8fc4"  # äußere Klammer blau
            for sxn, syn in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                l1 = c.create_line(0, 0, 0, 0, fill=col, width=2, tags="lagegfx")
                l2 = c.create_line(0, 0, 0, 0, fill=col, width=2, tags="lagegfx")
                self.lage_brackets.append((k, sxn, syn, l1, l2))
        # große Zahl oben links
        self.lage_big = c.create_text(X(64), Y(64), text="", anchor="nw", fill=gold, font=self.f["big"])
        self.lage_sub = c.create_text(X(66), Y(124), text="", anchor="nw", fill="#ffdcaa", font=self.f["head"])
        self.lage_hint = c.create_text(X(66), Y(150), text="„Wie ist die Lage?“ – Jarvis fliegt die Orte ab · ziehen = drehen · Mausrad = zoomen",
                      anchor="nw", fill="#7fb3c8", font=self.f["small"])
        c.create_line(X(64), Y(176), X(330), Y(176), fill="#16506a", tags="lagegfx")
        c.create_line(X(64), Y(176), X(130), Y(176), fill="#3cc8ff", width=2, tags="lagegfx")
        # rechts: Bereich für Globus oder Satellitenbild, oben der Umschalter
        rx0, ry0 = int(X(690)), int(Y(108))
        self.lg["region"] = (rx0, ry0, int(W - S(16) - rx0), int(H - S(16) - ry0))
        self.lg["toggle_y"] = Y(72)
        self._globe_items = [self.lage_item] + self.lage_end + [b[3] for b in self.lage_brackets] + \
            [b[4] for b in self.lage_brackets]
        self._lage_toggle()
        if self.mode == "flug":
            self._flug_build()
        else:
            self._lage_chips()
        # Drehen mit der Maus
        c.tag_bind(self.lage_item, "<ButtonPress-1>", self._lage_press)
        c.tag_bind(self.lage_item, "<B1-Motion>", self._lage_motion)
        c.tag_bind(self.lage_item, "<ButtonRelease-1>", self._lage_release)
        c.tag_bind(self.lage_item, "<Double-Button-1>", self._lage_dbl)
        if not getattr(self, "_wheel_bound", False):  # nur einmal binden (der Lage-Screen wird öfter neu aufgebaut)
            c.bind("<MouseWheel>", self._lage_wheel, add="+")
            self._wheel_bound = True
        self._lage_zoom_buttons()
        self._lage_reveal = time.time() if reveal else time.time() - 10
        self._lage_key = None
        self._lage_img = None
        self._lage_sig = None
        self._lage_render(full=True)
        self._lage_data()
        if self.mode == "flug":  # Flugverkehr: keine Meldungs-Punkte
            self.c.itemconfigure(self.lage_big, text="…")

    # --- Zoom ---
    ZOOM_MAX = 60000.0  # etwa Straßenebene

    def _lage_tile_ready(self):
        """Neue Kacheln sind da (aus einem Lade-Thread): gebündelt neu zeichnen."""
        if getattr(self, "_tile_job", None):
            return

        def go():
            self._tile_job = None
            self._tile_gen = getattr(self, "_tile_gen", 0) + 1
            if self.mode in ("lage", "flug") and not self._lage_anim and not self._lage_drag:
                self._lage_render(full=True)
        try:
            self._tile_job = self.win.after(250, go)
        except Exception:  # noqa: BLE001
            self._tile_job = None

    def _lage_zoom_buttons(self):
        c, S = self.c, self.lg["S"]
        c.delete("lagezoom")
        G = self.lg["size"]
        x1, y1 = self.lg["cx"] + G / 2 - S(6), self.lg["cy"] + G / 2 - S(6)
        for i, (label, f) in enumerate((("−", 1 / 2.2), ("+", 2.2))):
            x0 = x1 - S(38) * (2 - i)
            tag = f"lagezoom{i}"
            self._pill(x0, y1 - S(32), x0 + S(32), y1, "#06141e", "#16506a", ("lagezoom", tag))
            c.create_text(x0 + S(16), y1 - S(16), text=label, fill="#ffd28c", font=self.f["head"], tags=("lagezoom", tag))
            c.tag_bind(tag, "<Button-1>", lambda e, f=f: self._lage_zoom_to((self._zoom_goal or self.lage_zoom) * f))
            self._hand(tag)
        self.lage_zoomtxt = c.create_text(x1 - S(84), y1 - S(16), text="", anchor="e", fill="#7fb3c8",
                                          font=self.f["tiny"], tags="lagezoom")
        self._lage_zoom_label()

    def _lage_zoom_label(self):
        try:
            z = self.lage_zoom
            km = 40075.0 * math.cos(math.radians(self.lage_cam[0])) / (2 * math.pi) / z  # sichtbarer Radius
            text = "" if z < 1.05 else (f"{km:,.0f} km".replace(",", ".") if km >= 10 else f"{km * 1000:,.0f} m".replace(",", "."))
            self.c.itemconfigure(self.lage_zoomtxt, text=text)
        except Exception:  # noqa: BLE001
            pass

    def _lage_inside(self, x, y):
        G = self.lg["size"] / 2
        return abs(x - self.lg["cx"]) < G and abs(y - self.lg["cy"]) < G

    def _lage_zooming(self):
        return self._zoom_goal is not None

    def _lage_wheel(self, e):
        if self.mode not in ("lage", "flug") or not hasattr(self, "lg") or not self._lage_inside(e.x, e.y):
            return
        self._lage_zoom_to((self._zoom_goal or self.lage_zoom) * (1.45 if e.delta > 0 else 1 / 1.45), anchor=(e.x, e.y))

    def _lage_dbl(self, e):
        self._lage_zoom_to((self._zoom_goal or self.lage_zoom) * 2.5, anchor=(e.x, e.y))

    def _lage_zoom_to(self, z, anchor=None, smooth=True):
        """Weich zoomen: das Ziel wird gemerkt, jeder Takt kommt ein Stück näher (zur Maus hin, wie bei Google Earth)."""
        z = max(1.0, min(self.ZOOM_MAX, z))
        self.stop_lage_tour()
        self._lage_touch = time.time()
        if self._lage_anim:
            self._lage_anim = None
        self._zoom_goal = z
        self._zoom_anchor = anchor
        self.c.itemconfigure("lagegeo", state="hidden")

    def _tick_zoom(self, dt):
        goal = self._zoom_goal
        if goal is None:
            return
        z0 = self.lage_zoom
        lz = math.log(z0) + (math.log(goal) - math.log(z0)) * min(1.0, dt * 9.0)
        z1 = math.exp(lz)
        if abs(math.log(goal / z1)) < 0.01:
            z1 = goal
        a = self._zoom_anchor
        if a is not None:  # der Punkt unter der Maus bleibt ungefähr unter der Maus
            R0 = self.lg["R"]
            dx, dy = a[0] - self.lg["cx"], a[1] - self.lg["cy"]
            k = 1.0 / z0 - 1.0 / z1
            lat = self.lage_cam[0]
            self.lage_cam[0] = max(-80.0, min(80.0, lat - dy / R0 * 57.2958 * k))
            self.lage_cam[1] += dx / R0 * 57.2958 * k / max(0.2, math.cos(math.radians(lat)))
        self.lage_zoom = z1
        self._lage_zoom_label()
        if z1 == goal:
            self._zoom_goal = None
            self._lage_render(full=False)
            self._lage_sig = None
            self._lage_render(full=True)
        else:
            self._lage_render(full=False)

    def _tick_spin(self, now, dt):
        """Die Erde dreht sich langsam weiter, solange niemand sie bedient (Tag und Nacht sind echt)."""
        idle = (now - self._lage_touch > 8 and not self._lage_anim and not self._lage_drag and self._zoom_goal is None
                and not self._tour_on() and self.lage_zoom < 1.8 and self.mode == "lage" and not self.lage_sel
                and self.get_settings().get("lage_spin", True))
        self._lage_spinning = idle
        if not idle:
            return
        self.lage_cam[1] += dt * 0.8  # Grad pro Sekunde
        if now - getattr(self, "_spin_last", 0) > 0.15:
            self._spin_last = now
            self._lage_render(full=False, scale=1.0)

    # --- Umschalter Globus / Satellit und Lieblingsorte ---
    def _lage_sat(self) -> bool:
        return False  # das Satellitenbild ist jetzt die Kugel selbst (kein eigenes Kartenfenster mehr)

    def _lage_toggle(self):
        c, S = self.c, self.lg["S"]
        c.delete("lagetog")
        cx, y0 = self.lg["cx"], self.lg["toggle_y"]
        w = S(150)
        for i, (label, view) in enumerate((("◍  GLOBUS", "globus"), ("🛰  SATELLIT", "satellit"))):
            on = view == self.lage_view
            x0 = cx - w - S(4) + i * (w + S(8))
            tag = f"lagetog_{view}"
            self._pill(x0, y0, x0 + w, y0 + S(30), "#3a2608" if on else "#06141e", "#ffb446" if on else "#16506a",
                       ("lagetog", tag))
            c.create_text(x0 + w / 2, y0 + S(15), text=label, font=self.f["small"],
                          fill="#ffd28c" if on else "#7fb3c8", tags=("lagetog", tag))
            c.tag_bind(tag, "<Button-1>", lambda e, view=view: self.set_lage_view(view))
            self._hand(tag)

    def _lage_chips(self):
        """Orte zum Anklicken: Zuhause (normale Lage) und die Lieblingsorte aus den Einstellungen."""
        c, S, X, Y = self.c, self.lg["S"], self.lg["X"], self.lg["Y"]
        c.delete("lagechip")
        places = [None] + [p for p in (self.get_settings().get("lage_places") or []) if str(p).strip()][:7]
        x, y = X(64), Y(192)
        for i, place in enumerate(places):
            label = ("⌂ " + self._home_name()) if place is None else str(place)
            on = (place is None and not self._lage_place) or (place and self._lage_place and
                                                               place.lower() == self._lage_place.lower())
            w = self.f["small"].measure(label) + S(26)
            if x + w > X(660):
                x, y = X(64), y + S(36)
            tag = f"lagechip{i}"
            self._pill(x, y, x + w, y + S(28), "#3a2608" if on else "#06141e", "#ffb446" if on else "#16506a",
                       ("lagechip", tag))
            c.create_text(x + w / 2, y + S(14), text=label, font=self.f["small"],
                          fill="#ffd28c" if on else "#9cc8dc", tags=("lagechip", tag))
            c.tag_bind(tag, "<Button-1>", lambda e, place=place: self.show_place(place))
            self._hand(tag)
            x += w + S(8)

    def set_lage_view(self, view: str, force=False):
        """Globus <-> Satellit: dieselbe Kugel wechselt die Oberfläche (Abtastlinie läuft darüber)."""
        import pc_lage

        if view == self.lage_view and not force:
            return
        old = self.lage_view
        self.lage_view = view
        if view == "satellit":
            pc_lage.sat_texture()
        if self.mode not in ("lage", "flug"):
            return
        self._lage_toggle()
        if view == "satellit" and not pc_lage.sat_ready():  # Bild lädt noch (nur beim allerersten Mal)
            self._lage_wait_sat()
            return
        if old == view:
            self._lage_key = None
            self._lage_render(full=True)
            return
        lat0, lon0 = self.lage_cam
        G, base, hot, z = self.lg["size"], self._lage_base(), self.hot, self.lage_zoom
        job = object()
        frames: list = []
        n = 14
        self._lage_anim = dict(job=job, frames=frames, n=n, a=[lat0, lon0, z], b=[lat0, lon0, z], t0=None, shown=-1)
        self.c.itemconfigure("lagegeo", state="hidden")

        def run():
            a = pc_lage.render(G, lat0, lon0, base, hot, quality=True, zoom=z, style=old)
            b = pc_lage.render(G, lat0, lon0, base, hot, quality=True, zoom=z, style=view)
            for i in range(n):
                if self._lage_anim is None or self._lage_anim.get("job") is not job:
                    return
                t = (i + 1) / n
                frames.append(((lat0, lon0, z), self._lage_compose(pc_lage.wipe(a, b, t * t * (3 - 2 * t)))))
            self._lage_key = None
        threading.Thread(target=run, daemon=True).start()

    def _lage_wait_sat(self):
        import pc_lage

        c, S = self.c, self.lg["S"]
        c.delete("lagewait")
        if self.mode not in ("lage", "flug") or self.lage_view != "satellit":
            return
        if pc_lage.sat_ready():
            self._lage_key = None
            self.lage_view = "globus"
            self.set_lage_view("satellit")
            return
        c.create_text(self.lg["cx"], self.lg["cy"] + self.lg["size"] * 0.46, text="Satellitenbild wird geladen (einmalig) …",
                      fill="#9cc8dc", font=self.f["small"], tags="lagewait")
        self.win.after(500, self._lage_wait_sat)

    def show_place(self, place, data=None):
        """Lage eines Lieblingsortes zeigen (None = wieder die normale Lage mit Zuhause)."""
        import pc_news

        home = self._home_name().lower()
        if not place or str(place).strip().lower() == home:
            self._lage_place, self._place_data = None, None
            self._data["lage"] = pc_news.get(max_age=3600, wait=False)
            target, z = self.LAGE_HOME, 6
        else:
            place = str(place).strip()
            self._lage_place = place
            if data is None:  # erst laden (im Hintergrund), dann zeigen
                self._place_data = None
                self._data["lage"] = None

                def run(place=place):
                    d = pc_news.get_place(place)
                    try:
                        self.win.after(0, lambda: self._lage_place == place and self.show_place(place, d))
                    except Exception:  # noqa: BLE001
                        pass
                threading.Thread(target=run, daemon=True).start()
                if self.mode == "lage":
                    self._lage_chips()
                    self._lage_sig = None
                    self._lage_data()
                return
            self._place_data = data
            self._data["lage"] = data
            target, z = (data.get("lat"), data.get("lon")), 10
        self.lage_sel = None
        self._lage_sig = None
        if self.mode not in ("lage", "flug"):
            return
        self._lage_chips()
        self._lage_data()
        if target[0] is not None:
            import pc_lage

            far = target == self.LAGE_HOME
            self._lage_fly(target[0] - (8 if far else 0), target[1],
                           zoom=1.0 if far else pc_lage.zoom_for_level(9.5, self.lg["size"], target[0]))

    def _lage_base(self):
        return tuple(int(v * 0.95) for v in pc_sphere.COLORS.get(self.sphere.color, pc_sphere.COLORS["Gold"])[0])

    def _lage_compose(self, img):
        """Globus auf den Hintergrund rechnen -> fertiges RGB-Bild (Tk muss dann nichts mehr mischen = flüssig)."""
        G = self.lg["size"]
        if img.size != (G, G):
            img = img.resize((G, G), Image.BILINEAR)
        bg = getattr(self, "_bg_img", None)
        if bg is None:
            return img
        x0, y0 = int(self.lg["cx"] - G / 2), int(self.lg["cy"] - G / 2)
        return ImageChops.add(bg.crop((x0, y0, x0 + G, y0 + G)), img)

    def _lage_show(self, img):
        """Fertiges Bild anzeigen; dasselbe Tk-Bild wird nur neu befüllt (schneller als jedes Mal ein neues)."""
        if self._lage_img is not None and (self._lage_img.width(), self._lage_img.height()) == img.size:
            self._lage_img.paste(img)
        else:
            self._lage_img = ImageTk.PhotoImage(img)
            self.c.itemconfigure(self.lage_item, image=self._lage_img)

    def _lage_render(self, full=True, scale=0.5):
        """Globus neu rechnen lassen. Ein eigener Thread rechnet immer nur den NEUESTEN Wunsch (beim Ziehen und
        Zoomen werden Zwischenstände übersprungen) – dadurch bleibt die Oberfläche flüssig."""
        import pc_lage

        G = self.lg["size"]
        key = (round(self.lage_cam[0], 3), round(self.lage_cam[1], 3), round(self.lage_zoom, 4), self.lage_view, G,
               self.sphere.color, pc_lage._land["mask"] is not None, pc_lage.sat_ready(),
               getattr(self, "_tile_gen", 0), int(time.time() // 120))
        if full and key == self._lage_key:
            return
        self._lage_seq = getattr(self, "_lage_seq", 0) + 1
        self._lage_req = (list(self.lage_cam), self.lage_zoom, self.lage_view, full, scale, key, self._lage_seq)
        if not getattr(self, "_lage_worker", None):
            self._lage_ev = threading.Event()
            self._lage_worker = threading.Thread(target=self._lage_work, daemon=True, name="jarvis-globus")
            self._lage_worker.start()
        self._lage_ev.set()

    def _lage_work(self):
        import pc_lage

        while True:
            self._lage_ev.wait()
            self._lage_ev.clear()
            req = self._lage_req
            if req is None:
                continue
            cam, z, style, full, scale, key, seq = req
            try:
                G, base, hot = self.lg["size"], self._lage_base(), self.hot
                img = pc_lage.render(G, cam[0], cam[1], base, hot, quality=full, zoom=z, style=style, scale=scale)
                img = self._lage_compose(img)
            except Exception as e:  # noqa: BLE001
                print(f"Globus: {e}")
                continue
            try:
                self.win.after(0, lambda img=img, seq=seq, full=full, key=key: self._lage_set(img, seq, full, key))
            except Exception:  # noqa: BLE001
                pass

    def _lage_set(self, img, seq, full, key):
        if self._lage_anim or self.mode not in ("lage", "flug") or seq < getattr(self, "_lage_shown", 0):
            return  # inzwischen ein Flug oder schon ein neueres Bild
        self._lage_shown = seq
        self._lage_show(img)
        if full:
            self._lage_key = key
            self._lage_sig = None  # Punkte passend zur neuen Lage neu setzen
            if not self._lage_drag and not self._lage_zooming():
                self._lage_overlay()
        elif self._lage_spinning:
            self._lage_sig = None
            self._lage_overlay()

    def _lage_points(self):
        data = self._data.get("lage") or {}
        return (data.get("brennpunkte") or [])[:24]

    def _lage_data(self):
        if self.mode == "flug":
            self._flug_data()
            return
        try:
            import pc_news

            d = self._place_data if self._lage_place else pc_news.get(max_age=3600, wait=False)
            if d is not None and d is not self._data.get("lage"):
                self._data["lage"] = d
                self._lage_sig = None
        except Exception:  # noqa: BLE001
            pass
        pts = self._lage_points()
        n = len([q for q in pts if q.get("art") != "lokal"])
        nl = len(pts) - n
        if self._lage_place:
            self.c.itemconfigure(self.lage_big, text=str(len(pts)) if self._place_data else "…")
            self.c.itemconfigure(self.lage_sub, text=(f"MELDUNGEN AUS {self._lage_place.upper()}" if self._place_data
                                                      else f"LADE {self._lage_place.upper()} …"))
        else:
            self.c.itemconfigure(self.lage_big, text=str(n) if pts else "…")
            self.c.itemconfigure(self.lage_sub, text=("BRENNPUNKTE WELTWEIT" + (f" · {nl} AUS {self._home_name().upper()}"
                                                                              if nl else "")) if pts else "LADE DIE LAGE …")
        self._lage_overlay()

    def _home_name(self):
        return (self.get_settings().get("home_city") or "Leonberg").strip().title()

    def _lage_overlay(self):
        """Punkte, Bögen von Zuhause, Beschriftungen mit Linie nach außen (nur bei Änderungen neu)."""
        import pc_lage

        if self._lage_anim or self._lage_drag:  # erst zeichnen, wenn der Globus steht
            return
        if self.mode == "flug":
            self._flug_overlay()
            return
        if self._lage_sat():
            self.c.delete("lagegeo")
            self._lage_card()
            return
        sig = (tuple(self.lage_cam), self.lage_zoom, self.lage_view, id(self._data.get("lage")), id(self.lage_sel),
               self._lage_img is not None)
        if sig == self._lage_sig:
            return
        self._lage_sig = sig
        c, S = self.c, self.lg["S"]
        c.delete("lagegeo")
        cx, cy, R = self.lg["cx"], self.lg["cy"], self.lg["R"] * self.lage_zoom
        lat0, lon0 = self.lage_cam
        pts = self._lage_points()
        home = self.LAGE_HOME
        hx, hy, hv, _ = pc_lage.project([home[0]], [home[1]], lat0, lon0, cx, cy, R)
        self._lage_cities(lat0, lon0, cx, cy, R)
        if hv[0] and self._lage_inside(hx[0], hy[0]):
            r = S(6)
            c.create_oval(hx[0] - r, hy[0] - r, hx[0] + r, hy[0] + r, outline="#6effcd", width=2, tags="lagegeo")
        boxes = []
        labels = []
        for q in pts:
            x, y, v, z = pc_lage.project([q["lat"]], [q["lon"]], lat0, lon0, cx, cy, R)
            if not v[0] or not self._lage_inside(x[0], y[0]):
                continue
            x, y = float(x[0]), float(y[0])
            kind = q.get("art")
            col = "#6effcd" if kind == "lokal" else "#ff5a3c" if kind in ("konflikt", "katastrophe") else self.colors["gold"]
            if hv[0] and kind != "lokal":  # Bogen von Zuhause
                la, lo, lift = pc_lage.great_circle(home, (q["lat"], q["lon"]), 30)
                ax, ay, av, _ = pc_lage.project(la, lo, lat0, lon0, cx, cy, R)
                ax = cx + (ax - cx) * (1 + lift)
                ay = cy + (ay - cy) * (1 + lift)
                flat = []
                for i in range(len(ax)):
                    if av[i] and self._lage_inside(ax[i], ay[i]):
                        flat += [ax[i], ay[i]]
                if len(flat) >= 4:
                    c.create_line(*flat, fill=hexc(tuple(int(int(col[i:i + 2], 16) * 0.55) for i in (1, 3, 5))),
                                  width=1, smooth=True, tags="lagegeo")
            sel = q is self.lage_sel
            tag = f"lq{id(q)}"
            for rr, w in ((S(14), 1), (S(8), 2)):
                c.create_oval(x - rr, y - rr, x + rr, y + rr, outline=col, width=w, tags=("lagegeo", tag))
            c.create_oval(x - S(4), y - S(4), x + S(4), y + S(4), fill=col, outline="", tags=("lagegeo", tag))
            if sel:
                c.create_oval(x - S(22), y - S(22), x + S(22), y + S(22), outline="#ffffff", width=2, tags=("lagegeo", tag))
            c.tag_bind(tag, "<Button-1>", lambda e, q=q: self._lage_select(q))
            self._hand(tag)
            labels.append((x, y, q, col, sel))
        # Beschriftungen: Linie schräg nach außen, dann Unterstrich mit Text (wie im Vorschaubild)
        labels.sort(key=lambda a: (not a[4], -int(a[2].get("wichtig", 2))))
        boxes += getattr(self, "_city_boxes", [])
        for x, y, q, col, sel in labels[:7 if self.lage_zoom < 1.5 else 10]:
            name = (q.get("titel") or q.get("ort") or "").upper()
            name = name if len(name) <= 30 else name[:29] + "…"
            tw = self.f["label"].measure(name) + S(16)
            spot = None
            for ox, oy in ((40, -40), (40, 34), (-40, -40), (-40, 34), (70, -70), (-70, -70), (70, 64), (-70, 64)):
                ex, ey = x + S(ox), y + S(oy)
                bx0 = ex if ox > 0 else ex - tw
                box = (bx0, ey - S(26), bx0 + tw, ey + S(2))
                if any(not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]) for b in boxes):
                    continue
                spot = (ex, ey, ox, box)
                break
            if not spot:
                continue
            ex, ey, ox, box = spot
            boxes.append(box)
            tag = f"lq{id(q)}"
            c.create_line(x, y, ex, ey, fill=col, width=1, tags=("lagegeo", tag))
            # dunkles Schild hinter dem Text, damit man ihn auf jedem Untergrund lesen kann
            c.create_rectangle(*box, fill="#030c14", outline=col, width=1, tags=("lagegeo", tag))
            c.create_line(box[0], box[1], box[0], box[3], fill=col, width=max(2, int(S(3))), tags=("lagegeo", tag))
            c.create_text((box[0] + box[2]) / 2 + S(1), (box[1] + box[3]) / 2, text=name, anchor="center",
                          fill="#ffffff" if sel else "#ffe6c4", font=self.f["label"], tags=("lagegeo", tag))
        self._lage_card()
        self._raise_top()

    def _lage_cities(self, lat0, lon0, cx, cy, R):
        """Städtenamen auf der Kugel – je näher man heranzoomt, desto mehr."""
        import pc_lage

        c, S = self.c, self.lg["S"]
        self._city_boxes = []
        z = self.lage_zoom
        rank = 0 if z < 1.4 and self.lage_view != "satellit" else 1 if z < 2.2 else 2 if z < 3.5 else 3
        if rank == 0:
            return
        sel = [ct for ct in pc_lage.CITIES if ct[3] <= rank]
        xs, ys, vs, zs = pc_lage.project([ct[1] for ct in sel], [ct[2] for ct in sel], lat0, lon0, cx, cy, R)
        for ct, x, y, v, d in zip(sel, xs, ys, vs, zs):
            if not v or d < 0.25 or not self._lage_inside(x, y):
                continue
            w = self.f["city"].measure(ct[0])
            box = (x + S(5), y - S(9), x + S(9) + w, y + S(8))
            if any(not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]) for b in self._city_boxes):
                continue
            self._city_boxes.append(box)
            r = S(2.5)
            c.create_oval(x - r, y - r, x + r, y + r, fill="#ffffff", outline="", tags="lagegeo")
            c.create_text(x + S(7) + 1, y + 1, text=ct[0], anchor="w", fill="#000000", font=self.f["city"], tags="lagegeo")
            c.create_text(x + S(7), y, text=ct[0], anchor="w", fill="#eaf6ff", font=self.f["city"], tags="lagegeo")

    def _lage_select(self, q, fly=True):
        if self.mode not in ("lage", "flug"):
            return
        self.lage_sel = q
        self._lage_sig = None
        if fly:
            import pc_lage

            # so nah, wie der Ort genau bekannt ist: Gebäude/Straße ganz nah, Stadt, Region, Land
            lvl = {"punkt": 16.0, "strasse": 15.5, "stadtteil": 13.5, "stadt": 11.5, "region": 8.0, "land": 5.5}.get(
                str(q.get("genau") or ""), 12.0 if q.get("art") == "lokal" else 7.0)
            z = pc_lage.zoom_for_level(lvl, self.lg["size"], q["lat"])
            self._lage_fly(q["lat"], q["lon"], zoom=z)
        else:
            self._lage_overlay()

    def _lage_card(self):
        c, S, X, Y = self.c, self.lg["S"], self.lg["X"], self.lg["Y"]
        c.delete("lagecard")
        q = self.lage_sel
        if not q:
            return
        x0, y0, x1 = X(60), Y(600), X(440)
        pad = S(16)
        col = "#6effcd" if q.get("art") == "lokal" else "#ff9c3c"
        y = y0 + S(14)
        items = [c.create_text(x0 + pad, y, text=(q.get("titel") or "").upper() + " · " + (q.get("ort") or "").upper(),
                               anchor="nw", fill=col, font=self.f["head"], width=int(x1 - x0 - 2 * pad), tags="lagecard")]
        bb = c.bbox(items[-1])
        y = (bb[3] if bb else y + S(20)) + S(8)
        for text, fill in ((q.get("text", ""), "#e6f0f8"), (("Quelle: " + q["quelle"]) if q.get("quelle") else "", "#b4c8d2")):
            if not text:
                continue
            items.append(c.create_text(x0 + pad, y, text=text, anchor="nw", fill=fill, font=self.f["small"],
                                       width=int(x1 - x0 - 2 * pad), tags="lagecard"))
            bb = c.bbox(items[-1])
            y = (bb[3] if bb else y + S(20)) + S(6)
        if q.get("link"):
            items.append(c.create_text(x0 + pad, y + S(4), text="Artikel öffnen  ↗", anchor="nw", fill="#ffd28c",
                                       font=self.f["small"], tags=("lagecard", "lagelink")))
            import webbrowser

            c.tag_bind("lagelink", "<Button-1>", lambda e, u=q["link"]: webbrowser.open(u))
            self._hand("lagelink")
            y += S(28)
        y1 = max(y + pad, y0 + S(120))
        rect = c.create_rectangle(x0, y0, x1, y1, fill="#04121c", outline="#16506a", tags="lagecard")
        acc = c.create_line(x0 + S(14), y0, x0 + S(70), y0, fill=col, width=max(2, int(S(3))), tags="lagecard")
        c.tag_lower(rect, items[0])
        c.tag_raise(acc)

    LAGE_FPS = 30

    def _lage_fly(self, lat, lon, dur=1.4, zoom=None, force=False):
        """Flug zum Ort wie bei Google Earth (bei großer Strecke kurz heraus, hinüber, wieder hinein).
        Alle Zwischenbilder rechnet ein Hintergrund-Thread vorab, die Anzeige spielt sie nur ab."""
        import pc_lage

        lat = max(-70.0, min(75.0, lat))
        z0 = self.lage_zoom
        z1 = z0 if zoom is None else max(1.0, min(self.ZOOM_MAX, zoom))
        a = list(self.lage_cam)
        dl = ((lon - a[1] + 180) % 360) - 180
        b = [lat, a[1] + dl]
        dist = abs(b[0] - a[0]) + abs(dl)
        if dist < 0.3 and abs(z1 - z0) < 0.01 and not force:
            self._lage_overlay()
            return
        dip = min(1.0, dist / 40.0)  # wie weit zwischendurch herausgezoomt wird
        if zoom is not None and dur == 1.4:  # Standard: kurze Strecken schnell, lange etwas länger
            dur = 0.7 + 0.9 * min(1.0, dist / 90.0) + 0.25 * min(1.0, abs(math.log(z1 / z0)) / 6)
        self._zoom_goal = None
        self._lage_touch = time.time()
        n = max(8, int(dur * self.LAGE_FPS))
        frames: list = []
        job = object()
        self._lage_anim = dict(job=job, frames=frames, n=n, a=a + [z0], b=b + [z1], t0=None, shown=-1)
        self.c.itemconfigure("lagegeo", state="hidden")  # Punkte erst wieder, wenn der Globus steht
        G, base, hot, style = self.lg["size"], self._lage_base(), self.hot, self.lage_view

        def run():
            for i in range(n):
                if self._lage_anim is None or self._lage_anim.get("job") is not job:
                    return
                e = (i + 1) / n
                e = e * e * (3 - 2 * e)
                lz = math.log(z0) + (math.log(z1) - math.log(z0)) * e
                # unterwegs herauszoomen (logarithmisch), damit man sieht, wohin es geht
                top = math.log(max(1.0, min(z0, z1, 3.0 / max(0.05, dip))))
                lz = min(lz, lz - dip * (lz - top) * math.sin(math.pi * e)) if dip > 0.05 else lz
                zz = math.exp(lz)
                cam = (a[0] + (b[0] - a[0]) * e, a[1] + (b[1] - a[1]) * e, max(1.0, zz))
                img = pc_lage.render(G, cam[0], cam[1], base, hot, quality=False, zoom=cam[2], style=style)
                frames.append((cam, self._lage_compose(img)))
        threading.Thread(target=run, daemon=True).start()

    def _tick_lage(self, now):
        c, S = self.c, self.lg["S"]
        f = (now - self._lage_reveal) / 0.9
        trail = self.lg["trail"]
        if f < 1.3:  # nur während des Aufklappens ändern (spart viel Neuzeichnen)
            n = max(2, int(len(trail) / 2 * min(1.0, f / 0.6)))
            c.coords(self.lage_trail, *trail[:n * 2])
            g = max(0.0, min(1.0, (f - 0.55) / 0.45))
            sat = self._lage_sat()
            c.itemconfigure(self.lage_item, state="normal" if g > 0 and not sat else "hidden")
            for item in self.lage_end:
                c.itemconfigure(item, state="normal" if f >= 0.6 and not sat else "hidden")
            cx, cy = self.lg["cx"], self.lg["cy"]
            for k, sxn, syn, l1, l2 in self.lage_brackets:
                d = S(330 + k * 22) * (self.lg["size"] / S(640)) * (0.55 + 0.45 * g)
                L = S(60)
                x0, y0 = cx + sxn * d, cy + syn * d
                c.coords(l1, x0, y0, x0 - sxn * L, y0)
                c.coords(l2, x0, y0, x0, y0 - syn * L)
                st = "normal" if g > 0 and not sat else "hidden"
                c.itemconfigure(l1, state=st)
                c.itemconfigure(l2, state=st)
        # wandernder Lichtpunkt auf dem Datenstrang
        u = (now * 0.5) % 1.0
        i = int(u * (len(trail) // 2 - 1))
        px, py = trail[i * 2], trail[i * 2 + 1]
        r = S(4)
        c.coords(self.lage_pulse, px - r, py - r, px + r, py + r)
        dt = min(0.1, now - getattr(self, "_lage_tick_t", now))
        self._lage_tick_t = now
        self._tick_zoom(dt)
        self._tick_spin(now, dt)
        # Kamera-Flug: fertige Zwischenbilder abspielen
        an = self._lage_anim
        if an:
            frames = an["frames"]
            if an["t0"] is None and len(frames) < min(5, an["n"]):
                return  # erst ein paar Bilder vorrechnen lassen, dann ruckelfrei abspielen
            if an["t0"] is None:
                an["t0"] = now
            idx = min(int((now - an["t0"]) * self.LAGE_FPS), len(frames) - 1)
            if idx != an["shown"]:
                an["shown"] = idx
                cam, img = frames[idx]
                self.lage_cam = [cam[0], cam[1]]
                self.lage_zoom = cam[2]
                self._lage_show(img)
            if idx >= an["n"] - 1:
                self._lage_anim = None
                self.lage_cam = list(an["b"][:2])
                self.lage_zoom = an["b"][2]
                self._lage_zoom_label()
                self._lage_sig = None
                self._lage_overlay()
                self._lage_render(full=True)

    def _lage_press(self, e):
        self._lage_touch = time.time()
        self._zoom_goal = None
        self._lage_drag = (e.x, e.y, list(self.lage_cam), False)
        self._lage_anim = None
        self.stop_lage_tour()

    def _lage_motion(self, e):
        if not self._lage_drag:
            return
        x0, y0, cam, moved = self._lage_drag
        if not moved and abs(e.x - x0) + abs(e.y - y0) < 4:
            return
        deg = 57.3 / max(1.0, self.lg["R"] * self.lage_zoom)
        self.lage_cam = [max(-80.0, min(80.0, cam[0] + (e.y - y0) * deg)),
                         cam[1] - (e.x - x0) * deg / max(0.25, math.cos(math.radians(cam[0]))) ** (1 if self.lage_zoom > 3 else 0)]
        self._lage_touch = time.time()
        if not moved:
            self.c.itemconfigure("lagegeo", state="hidden")
        self._lage_drag = (x0, y0, cam, True)
        now = time.time()
        if now - getattr(self, "_lage_last_prev", 0) > 0.012:  # der Rechen-Thread nimmt sowieso nur den neuesten Stand
            self._lage_last_prev = now
            self._lage_render(full=False)

    def _lage_release(self, e):
        moved = self._lage_drag and self._lage_drag[3]
        self._lage_drag = None
        if moved:
            self._lage_render(full=False)
            self._lage_sig = None
            self._lage_overlay()
            self._lage_render(full=True)

    def lage_tour(self, seconds: float):
        """Während Jarvis das Briefing spricht: die Orte anfliegen – passend zu dem, was er gerade sagt.
        Jeder gesprochene Satz kommt über lage_on_text() herein. Falls keiner passt, geht es nach Zeitplan weiter."""
        self.stop_lage_tour()
        if self.mode != "lage":
            return
        self._lage_data()
        pts = self._lage_points()
        stops = [q for q in pts if q.get("im_briefing")][:8] or pts[:5]
        if not stops:
            return
        if self.get_settings().get("lage_sat_tour", True) and self.lage_view != "satellit":
            self.set_lage_view("satellit")  # beim Briefing wird die Kugel zum Satellitenbild und zoomt an die Orte
        self._tour_stops = stops
        self._tour_until = time.time() + seconds + 6
        self._tour_text = False
        self._tour_done = set()
        per = max(4.5, (seconds - 1.0) / len(stops))
        for i, q in enumerate(stops):
            self._lage_tour.append(self.win.after(int((2.5 + i * per) * 1000), lambda q=q: self._lage_stop(q)))

    def _tour_on(self):
        return time.time() < getattr(self, "_tour_until", 0)

    def lage_on_text(self, text: str):
        """Jarvis spricht gerade diesen Satz: passt er zu einem Ort, fliegt der Globus genau jetzt dorthin."""
        if self.mode != "lage" or not self._tour_on() or not text:
            return
        low = " " + re.sub(r"[^\wäöüß]+", " ", text.lower()) + " "
        best, score = None, 0
        for q in list(self._tour_stops) + [p for p in self._lage_points() if p not in self._tour_stops]:
            ort = str(q.get("ort") or "").lower().strip()
            sc = 0
            if ort and (" " + ort + " ") in low:
                sc += 4
            for w in re.findall(r"[\wäöüß]{5,}", (str(q.get("titel") or "") + " " + ort).lower()):
                if " " + w in low:
                    sc += 1
            if id(q) in self._tour_done:
                sc -= 2
            if sc > score:
                best, score = q, sc
        if best is None or score < 2:
            return
        if not self._tour_text:  # ab jetzt nur noch passend zum Text, nicht mehr nach Zeitplan
            self._tour_text = True
            for jb in self._lage_tour:
                try:
                    self.win.after_cancel(jb)
                except Exception:  # noqa: BLE001
                    pass
            self._lage_tour = []
        if self.lage_sel is best:
            return
        self._tour_done.add(id(best))
        self._lage_select(best)

    def _lage_stop(self, q):
        if self.mode != "lage" or getattr(self, "_tour_text", False):
            return
        self._lage_select(q)

    def stop_lage_tour(self):
        for j in getattr(self, "_lage_tour", []):
            try:
                self.win.after_cancel(j)
            except Exception:  # noqa: BLE001
                pass
        self._lage_tour = []
        self._tour_until = 0
        self._tour_stops = []

    # --- Daten im Hintergrund (Termine, Lage) ---
    def _data_loop(self):
        while True:
            try:
                termine = []
                now = datetime.datetime.now()
                try:
                    import pc_calendar

                    if pc_calendar.configured():
                        end = now.replace(hour=23, minute=59, second=59)
                        for e in pc_calendar.events_between(now.replace(hour=0, minute=0, second=0), end)[:8]:
                            if e["allday"] or e["end"] > now:
                                termine.append(("ganztägig" if e["allday"] else e["start"].strftime("%H:%M"), e["summary"]))
                except Exception:  # noqa: BLE001
                    pass
                self._data["termine"] = termine
                try:
                    import pc_news

                    if not self._lage_place:
                        self._data["lage"] = pc_news.get(max_age=3600, wait=False)  # höchstens stündlich neu
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                pass
            time.sleep(120)

    # --- Anzeige-Schleifen ---
    def _on_map(self, event):
        if event.widget is not self.win:
            return
        self._color_bar()
        self.shown = True
        self._last_tick = time.time()
        if self._tick_job is None:
            self._tick()
        if self._slow_job is None:
            self._slow()

    def _on_unmap(self, event):
        if event.widget is self.win:
            self.shown = False

    SPHERE_FPS = {"idle": 12, "listening": 18, "thinking": 30, "speaking": 16, "error": 6}

    def _tick(self):
        if not self.shown:
            self._tick_job = None
            return
        c = self.c
        now = time.time()
        dt = min(0.2, now - self._last_tick)
        self._last_tick = now
        try:
            self.pulse_t += dt * (2.0 if self.state == "idle" else 6.0)
            if self.animate and self.arcs:
                self.phase += dt * (1.0 if self.state == "idle" else 2.4)
                for item, off, sp in self.arcs:
                    c.itemconfigure(item, start=(off + self.phase * sp) % 360)
            self._tick_sphere(dt)
            self._tick_launch(now)
            if self.mode in ("lage", "flug"):
                self._tick_lage(now)
        except Exception as e:  # noqa: BLE001
            print(f"HUD: {e}")
        flying = self.mode in ("lage", "flug") and (getattr(self, "_lage_anim", None) or getattr(self, "_zoom_goal", None))
        self._tick_job = self.win.after(15 if flying else 40 if self.animate else 200, self._tick)  # Flüge flüssig

    def _tick_sphere(self, dt):
        c = self.c
        ready = self.sphere.ready()
        made = 0
        while len(self._sph_photos) < ready and made < 3:
            img = self.sphere.get(len(self._sph_photos))
            if img is None:
                break
            if img.width != self._sph_size:
                img = img.resize((self._sph_size, self._sph_size), Image.BILINEAR)
            rgba = img.convert("RGBA")
            rgba.putalpha(img.convert("L").point(lambda v: min(255, int(v * 1.6))))
            self._sph_photos.append(ImageTk.PhotoImage(rgba))
            made += 1
        n = len(self._sph_photos)
        if n:
            if self.animate and n >= pc_sphere.FRAMES:
                self._sph_t += dt * self.SPHERE_FPS.get(self.state, 12)
                idx = int(self._sph_t) % n
            else:
                idx = 0
            c.itemconfigure(self.sphere_item, image=self._sph_photos[idx])
        lvl = pc_sphere.level() if self.state != "idle" else pc_sphere.level() * 0.3
        if self.state == "speaking" and lvl < 0.05:
            lvl = 0.25 + 0.2 * math.sin(time.time() * 9) ** 2
        pulse = 0.5 + 0.5 * math.sin(self.pulse_t)
        e = min(1.0, 0.12 + 0.25 * pulse * (1.0 if self.state != "idle" else 0.5) + lvl * 0.9)
        if self._halo_photos:
            c.itemconfigure(self.halo_item, image=self._halo_photos[min(len(self._halo_photos) - 1, int(e * 4.99))])
        if self.animate and (self.state not in ("idle", "error") or self.mode == "fokus"):
            t = time.time()
            r0 = self._sph_r
            amp = r0 * (0.012 + 0.07 * lvl)
            pts = []
            for k in range(97):
                a = 2 * math.pi * k / 96
                w = math.sin(a * 5 + t * 3.1) * 0.5 + math.sin(a * 11 - t * 4.7) * 0.3 + math.sin(a * 17 + t * 7.3) * 0.2
                rr = r0 + amp * w
                pts += [self.cx + math.cos(a) * rr, self.cy + math.sin(a) * rr]
            c.coords(self.wave_item, *pts)
            c.itemconfigure(self.wave_item, state="normal")
        else:
            c.itemconfigure(self.wave_item, state="hidden")

    def _tick_launch(self, now):
        if not self._launch:
            return
        t0, cb = self._launch
        f = (now - t0) / 0.7
        line, dot = self.launch_items
        if f >= 1:
            self._launch = None
            self.c.itemconfigure(line, state="hidden")
            self.c.itemconfigure(dot, state="hidden")
            try:
                cb()
            except Exception as e:  # noqa: BLE001
                print(f"Weltlage: {e}")
            return
        W, H = self._size
        sx, sy = self.cx, self.cy
        ex, ey = W + 40, self.cy - H * 0.25
        pts = []
        for k in range(0, 31):
            u = (k / 30) * f
            x = sx + (ex - sx) * u
            y = sy + (ey - sy) * u - H * 0.18 * math.sin(math.pi * u)
            pts += [x, y]
        self.c.coords(line, *pts)
        r = (6 + 18 * f) * self.sc * 1.5
        x, y = pts[-2], pts[-1]
        self.c.coords(dot, x - r, y - r, x + r, y + r)
        self.c.itemconfigure(line, state="normal")
        self.c.itemconfigure(dot, state="normal")

    def _slow(self, force=False):
        """Einmal pro Sekunde: Uhr, System, Karten (nur neu zeichnen, wenn sich etwas geändert hat)."""
        if not force:
            if not self.shown:
                self._slow_job = None
                return
            self._slow_job = self.win.after(1000, self._slow)
        if self.mode in ("lage", "flug"):
            self._lage_data()
            if not (self._lage_anim or self._lage_drag or self._zoom_goal or self._lage_spinning):
                self._lage_render(full=True)  # alle 2 Minuten neu (Tag-Nacht-Grenze wandert), sonst nichts zu tun
            return
        if self.mode == "fokus" or not self.cards:
            return
        try:
            self._card_zeit()
            self._card_system()
            self._card_wetter()
            self._card_termine()
            self._card_lage()
            self._card_verlauf()
        except Exception as e:  # noqa: BLE001
            print(f"HUD-Karten: {e}")

    def _redraw(self, key, sig) -> bool:
        if self._sigs.get(key) == sig:
            return False
        self._sigs[key] = sig
        self.c.delete(f"cc_{key}")
        return True

    def _t(self, key, x, y, text, font="text", fill=None, anchor="nw", width=None):
        kw = {"width": width} if width else {}
        return self.c.create_text(x, y, text=text, font=self.f[font], fill=fill or self.colors["txt"], anchor=anchor,
                                  tags=f"cc_{key}", **kw)

    def _card_zeit(self):
        t = time.localtime()
        if not self._redraw("zeit", time.strftime("%H:%M:%S %d", t)):
            return
        x0, y0, x1, y1 = self.cards["zeit"]
        S = lambda v: v * self.sc  # noqa: E731
        self._t("zeit", x0 + S(16), y0 + S(40), time.strftime("%H:%M", t), "big", self.colors["gold"])
        self._t("zeit", x0 + S(16) + self.f["big"].measure("00:00") + S(8), y0 + S(62), time.strftime(":%S", t), "text",
                self.colors["dim"])
        self._t("zeit", x0 + S(16), y0 + S(112), f"{WEEKDAYS[t.tm_wday]}, {t.tm_mday}. {MONTHS[t.tm_mon - 1]} {t.tm_year}")

    def _card_system(self):
        p = self.perf.snapshot()
        cpu, ram = self.stats.cpu(), self.stats.ram()
        drives = self.stats.drives(1)
        disk = (1 - drives[0][2] / drives[0][1]) if drives and drives[0][1] else None
        down, up = p.get("net_down"), p.get("net_up")
        gpu = p.get("gpu")
        temps = self.worker.snapshot().get("temps") or {}
        gtemp = next((v for k, v in temps.items() if "gpu" in k.lower()), None)
        rows = [(cpu, f"{cpu * 100:.0f} %"), (ram, f"{ram * 100:.0f} %"),
                ((gpu or 0) / 100, (f"{gpu:.0f} %" if gpu is not None else "–") + (f" · {gtemp:.0f}°C" if gtemp else "")),
                (disk or 0, f"{drives[0][2] / 1e9:.0f} GB frei" if drives else "–"),
                (min(1.0, ((down or 0) + (up or 0)) / 5e6), f"↓ {fmt_bytes(down)}/s" if down is not None else "–")]
        for (val, bar, bx0, bx1, y), (frac, text) in zip(self.sys_rows, rows):
            frac = max(0.0, min(1.0, frac))
            self.c.coords(bar, bx0, y + 14 * self.sc, bx0 + (bx1 - bx0) * frac, y + 20 * self.sc)
            self.c.itemconfigure(bar, fill="#ff7a7a" if frac > 0.9 else self.colors["cyan"])
            self.c.itemconfigure(val, text=text)

    def _card_wetter(self):
        cfg, snap = self.get_settings(), self.worker.snapshot()
        w = snap["weather"] if cfg.get("show_weather") else None
        if not self._redraw("wetter", (repr(w), snap.get("weather_err"), bool(cfg.get("show_weather")))):
            return
        x0, y0, x1, y1 = self.cards["wetter"]
        S = lambda v: v * self.sc  # noqa: E731
        key = "wetter"
        if not cfg.get("show_weather"):
            self._t(key, x0 + S(16), y0 + S(48), "Wetter ist ausgeschaltet.", "small", self.colors["dim"])
            return
        if not w:
            self._t(key, x0 + S(16), y0 + S(48), "Wetter nicht erreichbar" if snap.get("weather_err") else "Wetter lädt …",
                    "small", self.colors["dim"])
            return
        self._t(key, x1 - S(16), y0 + S(14), w["city"], "small", self.colors["dim"], anchor="ne")
        self._t(key, x0 + S(16), y0 + S(40), f"{w['temp']:.0f}°", "big", self.colors["gold"])
        self._t(key, x0 + S(120), y0 + S(48), short(w["text"], 22), "text")
        self._t(key, x0 + S(120), y0 + S(72), f"gefühlt {w['feels']:.0f}° · {w['wind']:.0f} km/h", "small", self.colors["dim"])
        for i, (day, lo, hi, text) in enumerate((w.get("days") or [])[:6]):
            yy = y0 + S(112) + i * S(27)
            self._t(key, x0 + S(16), yy, day, "small", self.colors["dim"])
            self._t(key, x0 + S(56), yy, short(text, 18), "small")
            self._t(key, x1 - S(16), yy, f"{lo:.0f}° / {hi:.0f}°", "small", self.colors["gold"], anchor="ne")

    def _card_termine(self):
        rem = pc_remind.upcoming()[:6]
        termine = self._data.get("termine") or []
        sig = (tuple(termine), tuple((e["id"], e["due"]) for e in rem), time.strftime("%H:%M"))
        if not self._redraw("termine", sig):
            return
        x0, y0, x1, y1 = self.cards["termine"]
        S = lambda v: v * self.sc  # noqa: E731
        key = "termine"
        rows = []
        for when, what in termine:
            rows.append((when, what))
        for e in rem:
            due = datetime.datetime.fromtimestamp(e["due"])
            left = e["due"] - time.time()
            when = (f"in {int(left // 60)} min" if left < 3600 else due.strftime("%H:%M")) if e["kind"] == "timer" else \
                due.strftime("%H:%M")
            label = {"timer": "Timer" + (f" · {e['text']}" if e["text"] else ""), "alarm": "Wecker"}.get(e["kind"]) or \
                re.sub(r"^(daran,\s*|dass\s+)", "", e["text"])
            rows.append((when, label))
        if not rows:
            self._t(key, x0 + S(16), y0 + S(48), "Heute steht nichts an. Sag z. B.: „Timer auf 5 Minuten“.",
                    "small", self.colors["dim"], width=int(x1 - x0 - S(32)))
            return
        for i, (when, what) in enumerate(rows[:7]):
            yy = y0 + S(46) + i * S(25)
            self._t(key, x0 + S(16), yy, when, "small", self.colors["dim"])
            self._t(key, x1 - S(16), yy, short(what, 26), "small", self.colors["gold"], anchor="ne")

    def _card_lage(self):
        data = self._data.get("lage") or {}
        pts = data.get("brennpunkte") or []
        if not self._redraw("lage", (id(data), len(pts))):
            return
        x0, y0, x1, y1 = self.cards["lage"]
        S = lambda v: v * self.sc  # noqa: E731
        key = "lage"
        self.c.itemconfigure("title_lage", text=f"LAGE · {len(pts)} BRENNPUNKTE" if pts else "LAGE")
        if not pts:
            self._t(key, x0 + S(16), y0 + S(48), "Sag „Wie ist die Lage?“ oder klick auf ◍.", "small", self.colors["dim"],
                    width=int(x1 - x0 - S(32)))
            return
        local = [q for q in pts if q.get("art") == "lokal"]
        world = [q for q in pts if q.get("art") != "lokal"]
        lines = [(q, False) for q in world[:4]] + [(q, True) for q in local[:2]]
        y = y0 + S(46)
        for q, loc in lines:
            col = "#6effcd" if loc else self.colors["gold"]
            it = self._t(key, x0 + S(16), y, "●", "tiny", col)
            it2 = self._t(key, x0 + S(32), y - S(2), short(f"{q.get('ort', '')}: {q.get('titel', '')}", 46), "small",
                          width=int(x1 - x0 - S(48)))
            bb = self.c.bbox(it2)
            y = (bb[3] if bb else y + S(20)) + S(6)
            if y > y1 - S(40):
                break
        self._t(key, x0 + S(16), y1 - S(28), "Klick auf LAGE oder ◍ = Karte öffnen", "tiny", self.colors["dim"])
        self.c.tag_bind(f"cc_{key}", "<Button-1>", lambda e: self.on_globe and self.launch(self.on_globe))

    def _card_verlauf(self):
        if not self._redraw("verlauf", tuple(self.log)):
            return
        x0, y0, x1, y1 = self.cards["verlauf"]
        S = lambda v: v * self.sc  # noqa: E731
        key = "verlauf"
        if not self.log:
            self._t(key, x0 + S(16), y0 + S(48), "Noch nichts gesagt.", "small", self.colors["dim"])
            return
        y = y0 + S(46)
        for role, text in self.log[-6:]:
            name = "Du" if role == "Du" else "Jarvis"
            it = self._t(key, x0 + S(16), y, f"{name}: {short(text, 70)}", "small",
                         self.colors["cyan"] if role == "Du" else self.colors["txt"], width=int(x1 - x0 - S(32)))
            bb = self.c.bbox(it)
            y = (bb[3] if bb else y + S(20)) + S(5)
            if y > y1 - S(20):
                break
