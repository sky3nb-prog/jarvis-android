"""
Weltlage-Globus für Jarvis: eigenes Fenster mit leuchtendem 3D-Globus.

Bedienung:
- Ansichten oben: Weltlage, Luftraum, Deutschland (oder Tasten 1/2/3, oder per Sprache)
- Maus ziehen = Globus drehen, Mausrad = zoomen, Doppelklick = Ansicht zurücksetzen
- Klick auf einen Punkt (Brennpunkt oder Flugzeug) oder auf einen Eintrag rechts = Details links, der Globus fliegt hin
- Stil: HOLOGRAMM (leuchtende Punkte wie im Video) oder SATELLIT (echte Erde wie bei Google Earth)
- ◐ = Farben (Glut, Jarvis, Radar, Violett), ⛶ oder F11 = Vollbild, Esc = Vollbild aus / schließen
- "Jarvis, wie ist die Lage?": Er spricht das Briefing, öffnet den Globus und fliegt die Brennpunkte nacheinander ab.

Die Erdkarten (Lichter bei Nacht, Landmasse, Satellitenbild) lädt Jarvis beim ersten Öffnen einmal herunter und
speichert sie im Ordner "globus" neben dem Programm. Gerechnet wird alles selbst mit numpy.
"""

import math
import os
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.request
import webbrowser

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageTk

import pc_flights
import pc_frameless
import pc_news

# --- Farbthemen ----------------------------------------------------------------------------
THEMES = {
    "Glut": dict(bg=(5, 8, 18), ocean=(7, 13, 28), land=(18, 27, 46), lights=(255, 156, 70), glow=(255, 92, 28),
                 dots=(150, 120, 110), accent=(255, 142, 48), accent2=(255, 214, 96), text=(255, 226, 204),
                 dim=(190, 146, 122), panel=(14, 12, 20), grid=(60, 38, 30)),
    "Jarvis": dict(bg=(2, 10, 18), ocean=(3, 16, 28), land=(8, 34, 50), lights=(120, 228, 255), glow=(0, 160, 255),
                   dots=(70, 150, 180), accent=(0, 207, 255), accent2=(170, 240, 255), text=(215, 243, 255),
                   dim=(125, 190, 214), panel=(4, 22, 34), grid=(10, 60, 80)),
    "Radar": dict(bg=(2, 12, 6), ocean=(3, 18, 9), land=(10, 40, 20), lights=(140, 255, 150), glow=(40, 220, 90),
                  dots=(80, 170, 100), accent=(70, 255, 120), accent2=(200, 255, 170), text=(215, 255, 222),
                  dim=(120, 196, 138), panel=(4, 22, 10), grid=(16, 70, 34)),
    "Violett": dict(bg=(8, 4, 20), ocean=(12, 7, 30), land=(30, 18, 58), lights=(205, 160, 255), glow=(150, 80, 255),
                    dots=(140, 110, 190), accent=(182, 140, 255), accent2=(255, 190, 250), text=(236, 226, 255),
                    dim=(170, 150, 210), panel=(16, 10, 30), grid=(50, 30, 80)),
}
THEME_NAMES = list(THEMES)
STYLES = ["Hologramm", "Satellit"]
VIEWS = [("weltlage", "Weltlage"), ("luftraum", "Luftraum"), ("deutschland", "Deutschland")]
# Startansicht je Ansicht: Breite, Länge, Zoom (Radius im Verhältnis zur Fenstergröße)
DEFAULT_CAM = {"weltlage": (22.0, 10.0, 0.40), "luftraum": (49.0, 11.0, 1.55), "deutschland": (51.2, 10.4, 4.6)}
ZOOM_LIMITS = (0.25, 14.0)
KIND_COLORS = {"konflikt": (255, 70, 60), "katastrophe": (255, 110, 40), "wetter": (90, 190, 255),
               "wirtschaft": (255, 210, 90), "politik": None, "gesellschaft": None, "sport": (120, 230, 140),
               "wissenschaft": (170, 150, 255), "lokal": (120, 255, 200)}

TEX_URLS = {
    "night": ("earth-night.jpg", ["https://unpkg.com/three-globe/example/img/earth-night.jpg",
                                  "https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-night.jpg"]),
    "water": ("earth-water.png", ["https://unpkg.com/three-globe/example/img/earth-water.png",
                                  "https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-water.png"]),
    "sat": ("earth-blue-marble.jpg", ["https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg",
                                      "https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-blue-marble.jpg"]),
}


def hexc(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb[:3])


def mix(a, b, t: float):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


# --- Dateien ---------------------------------------------------------------------------------
def _folder(sub: str = "") -> str:
    try:
        import pc_apps

        base = pc_apps.base_dir()
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "globus", sub) if sub else os.path.join(base, "globus")
    os.makedirs(path, exist_ok=True)
    return path


def _fetch(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Jarvis"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _download(name: str) -> str:
    fname, urls = TEX_URLS[name]
    path = os.path.join(_folder(), fname)
    if os.path.exists(path) and os.path.getsize(path) > 10_000:
        return path
    for url in urls:
        try:
            data = _fetch(url, 60)
            if len(data) > 10_000:
                with open(path, "wb") as f:
                    f.write(data)
                return path
        except Exception as e:
            print(f"Erdkarte {name} von {url} nicht geladen: {e}")
    return ""


def load_textures(want_sat: bool = False) -> dict:
    """-> {"lights": float32 HxW, "land": bool HxW, "sat": float32 HxWx3} (fehlende Teile = None)."""
    out = {"lights": None, "land": None, "sat": None}
    p = _download("night")
    if p:
        try:
            im = Image.open(p).convert("L")
            if im.width > 2048:
                im = im.resize((2048, 1024), Image.BILINEAR)
            a = np.asarray(im, dtype=np.float32) / 255.0
            out["lights"] = np.clip((a - 0.08) / 0.92, 0, 1) ** 1.35
        except Exception as e:
            print(f"Erdkarte (Lichter) defekt: {e}")
    p = _download("water")
    if p:
        try:
            im = Image.open(p).convert("L").resize((2048, 1024), Image.BILINEAR)
            m = np.asarray(im) > 127
            out["land"] = m if m.mean() < 0.5 else ~m  # Land ist der kleinere Teil (ca. 30 %)
        except Exception as e:
            print(f"Erdkarte (Land) defekt: {e}")
    if want_sat:
        out["sat"] = load_sat()
    return out


def load_sat():
    p = _download("sat")
    if not p:
        return None
    try:
        im = Image.open(p).convert("RGB")
        if im.width > 4096:
            im = im.resize((4096, 2048), Image.BILINEAR)
        return np.asarray(im, dtype=np.uint8)  # als Bytes speichern (spart viel Arbeitsspeicher)
    except Exception as e:
        print(f"Satellitenbild defekt: {e}")
        return None


# --- Renderer --------------------------------------------------------------------------------
class Projection:
    """Orthografische Ansicht: Mittelpunkt (cx, cy), Radius R in Pixeln, Blick auf Breite lat0.
    grid=True rechnet zusätzlich für jedes Bildpixel Breite/Länge aus (für das Erdbild)."""

    def __init__(self, w, h, cx, cy, R, lat0, grid=True):
        self.w, self.h, self.cx, self.cy, self.R, self.lat0 = w, h, cx, cy, R, lat0
        self._c, self._s = math.cos(math.radians(lat0)), math.sin(math.radians(lat0))
        if not grid:
            return
        x0, x1 = max(0, int(cx - R)), min(w, int(cx + R) + 1)
        y0, y1 = max(0, int(cy - R)), min(h, int(cy + R) + 1)
        if x1 <= x0 or y1 <= y0:
            x0 = y0 = 0
            x1 = y1 = 1
        ys, xs = np.mgrid[y0:y1, x0:x1]
        X = (xs + 0.5 - cx) / R
        Y = (cy - ys - 0.5) / R
        rr = X * X + Y * Y
        inside = rr < 1.0
        self.iy, self.ix = ys[inside], xs[inside]
        X, Y = X[inside], Y[inside]
        Z = np.sqrt(np.maximum(0.0, 1.0 - rr[inside]))
        wy = Y * self._c + Z * self._s
        wz = -Y * self._s + Z * self._c
        self.lat = np.degrees(np.arcsin(np.clip(wy, -1, 1))).astype(np.float32)
        self.lonrel = np.degrees(np.arctan2(X, wz)).astype(np.float32)
        self.shade = (0.28 + 0.72 * Z).astype(np.float32)
        self.edge = np.sqrt(rr[inside]).astype(np.float32)

    def project(self, lat, lon, lon0):
        """Breite/Länge (Arrays) -> Bildschirm x, y und sichtbar (Vorderseite)."""
        lat = np.radians(np.asarray(lat, dtype=np.float64))
        lr = np.radians(np.asarray(lon, dtype=np.float64) - lon0)
        x = np.cos(lat) * np.sin(lr)
        y = np.sin(lat)
        z = np.cos(lat) * np.cos(lr)
        Y = y * self._c - z * self._s
        Z = y * self._s + z * self._c
        return self.cx + x * self.R, self.cy - Y * self.R, Z > 0.02


class Renderer:
    def __init__(self):
        self.lights = self.land = self.sat = None
        self.theme = THEMES["Glut"]
        self.theme_name = "Glut"
        self.style = "Hologramm"
        self._tex = None
        self._tex_key = None
        self._proj: dict = {}
        self._bg: dict = {}
        self._static = None
        self._static_key = None
        rng = np.random.default_rng(7)
        self._stars = rng.random((260, 3))

    def set_textures(self, lights=None, land=None, sat=None):
        if lights is not None:
            self.lights = lights
        if land is not None:
            self.land = land
        if sat is not None:
            self.sat = sat
        self._tex = None
        self._static_key = None

    def set_theme(self, name):
        self.theme_name = name if name in THEMES else "Glut"
        self.theme = THEMES[self.theme_name]
        self._tex = None
        self._bg.clear()
        self._static_key = None

    def set_style(self, style):
        self.style = style if style in STYLES else "Hologramm"
        self._tex = None
        self._bg.clear()
        self._static_key = None

    def sat_mode(self) -> bool:
        return self.style == "Satellit" and self.sat is not None

    def glow_color(self):
        return (90, 165, 255) if self.sat_mode() else self.theme["glow"]

    def proj(self, w, h, cx, cy, R, lat0):
        key = (w, h, int(round(cx)), int(round(cy)), round(R, 1), round(lat0, 2))
        p = self._proj.get(key)
        if p is None:
            if len(self._proj) > 4:
                self._proj.clear()
            p = self._proj[key] = Projection(w, h, cx, cy, R, lat0)
        return p

    def _texture(self):
        key = (self.style, self.theme_name, id(self.lights), id(self.land), id(self.sat))
        if self._tex is None or self._tex_key != key:
            t = self.theme
            if self.sat_mode():
                self._tex = self.sat
            else:
                H, W = (self.lights.shape if self.lights is not None else
                        self.land.shape if self.land is not None else (512, 1024))
                tex = np.empty((H, W, 3), dtype=np.float32)
                tex[:] = t["ocean"]
                if self.land is not None:
                    land = self.land if self.land.shape == (H, W) else np.asarray(
                        Image.fromarray(self.land.astype(np.uint8) * 255).resize((W, H))) > 127
                    tex[land] = t["land"]
                if self.lights is not None:
                    tex += self.lights[..., None] * np.array(t["lights"], dtype=np.float32) * 0.95
                self._tex = tex
            self._tex_key = key
        return self._tex

    def _background(self, w, h, cx, cy, R):
        key = (w, h, int(cx), int(cy), int(R), self.theme_name, self.sat_mode())
        bg = self._bg.get(key)
        if bg is None:
            if len(self._bg) > 3:
                self._bg.clear()
            t = self.theme
            img = Image.new("RGB", (w, h), t["bg"])
            d = ImageDraw.Draw(img)
            for sx, sy, b in self._stars:
                v = int(40 + 120 * b)
                d.point((int(sx * w), int(sy * h)), fill=mix(t["bg"], (v, v, v), 0.8))
            if R < 1.2 * max(w, h):  # Leuchten um den Globus (nur wenn sein Rand zu sehen ist)
                glow = Image.new("L", (w, h), 0)
                gd = ImageDraw.Draw(glow)
                for i in range(26, 0, -1):
                    r = R * (1.0 + i * 0.0065)
                    a = int(190 * (1 - i / 27) ** 2.2)
                    gd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=a)
                glow = glow.filter(ImageFilter.GaussianBlur(max(2, min(R, 2000) * 0.02)))
                img = Image.composite(Image.new("RGB", (w, h), self.glow_color()), img, glow)
            bg = self._bg[key] = np.asarray(img, dtype=np.float32).copy()
        return bg

    def frame(self, w, h, cx, cy, R, lat0, lon0, q=1.0, smooth=False) -> Image.Image:
        """Erdbild in Fenstergröße w x h. q < 1 rechnet kleiner und vergrößert (flüssig beim Drehen)."""
        wq, hq = max(16, int(w * q)), max(16, int(h * q))
        p = self.proj(wq, hq, cx * q, cy * q, R * q, lat0)
        t = self.theme
        sat = self.sat_mode()
        bg = self._background(wq, hq, cx * q, cy * q, R * q)
        tex = self._texture()
        H, W = tex.shape[:2]
        uf = ((p.lonrel + lon0 + 180.0) % 360.0) / 360.0 * W
        vf = np.clip((90.0 - p.lat) / 180.0 * H, 0, H - 1.001)
        u = uf.astype(np.int32) % W
        v = vf.astype(np.int32)
        if smooth:
            fu, fv = (uf - np.floor(uf))[:, None], (vf - v)[:, None]
            u2, v2 = (u + 1) % W, np.minimum(v + 1, H - 1)
            base = (tex[v, u] * (1 - fu) + tex[v, u2] * fu) * (1 - fv) + (tex[v2, u] * (1 - fu) + tex[v2, u2] * fu) * fv
        else:
            base = tex[v, u].astype(np.float32)
        shade = (0.45 + 0.55 * p.shade) if sat else p.shade
        rim = (np.clip((p.edge - 0.72) / 0.28, 0, 1) ** 2.6 * (0.6 if sat else 0.95))[:, None] * \
            np.array(self.glow_color(), np.float32)
        col = base * shade[:, None] + rim
        px_per_deg = p.R * math.pi / 180.0
        if not sat:  # Gradnetz, ganz dezent (je näher, desto feiner)
            step = 30.0 if px_per_deg < 12 else 10.0 if px_per_deg < 40 else 2.0
            eps = max(0.01, 0.7 / px_per_deg)
            lon = (p.lonrel + lon0) % step
            la = p.lat % step
            grid = (np.minimum(lon, step - lon) < eps) | (np.minimum(la, step - la) < eps)
            col[grid] += np.array(t["grid"], np.float32) * 0.6
        out = bg.copy()
        out[p.iy, p.ix] = col
        if self.land is not None and not sat:  # gepunktete Kontinente
            zoomed = px_per_deg >= 12
            dstep = max(6, int(min(wq, hq) / 110)) if zoomed else max(3, int(min(wq, hq) / 150))
            sel = np.nonzero(((p.iy % dstep) == 0) & ((p.ix % dstep) == 0))[0]
            LH, LW = self.land.shape
            hit = sel[self.land[(v[sel].astype(np.int64) * LH) // H, (u[sel].astype(np.int64) * LW) // W]]
            dcol = np.array(t["dots"], np.float32) * p.shade[hit, None] * 0.95
            size = 2 if zoomed and q >= 1 else 1
            for dy in range(size):
                for dx in range(size):
                    out[np.minimum(p.iy[hit] + dy, hq - 1), np.minimum(p.ix[hit] + dx, wq - 1)] += dcol
        img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
        if (wq, hq) != (w, h):
            img = img.resize((w, h), Image.BILINEAR)
        return img

    def cached_frame(self, w, h, cx, cy, R, lat0, lon0) -> Image.Image:
        """Wie frame(), aber gemerkt, solange sich nichts ändert (stehender Globus = kaum Rechenzeit)."""
        key = (w, h, round(cx, 1), round(cy, 1), round(R, 1), round(lat0, 3), round(lon0, 3), self.style,
               self.theme_name, id(self.lights), id(self.land), id(self.sat))
        if self._static_key != key:
            self._static = self.frame(w, h, cx, cy, R, lat0, lon0, 1.0, smooth=True)
            self._static_key = key
        return self._static.copy()


# --- Fenster -------------------------------------------------------------------------------
class GlobeWindow:
    def __init__(self, root: tk.Tk, k: float, get_settings, save_setting):
        self.root, self.k = root, k
        self.get_settings, self.save_setting = get_settings, save_setting
        self.win = None
        self.view = "weltlage"
        self.r = Renderer()
        s = get_settings()
        self.r.set_theme(s.get("globe_theme", "Glut"))
        self.r.set_style(s.get("globe_style", "Hologramm"))
        self.cam = list(DEFAULT_CAM["weltlage"])
        self.anim = None  # (Start, Dauer, von, nach)
        self.open_ = False
        self.fullscreen = False
        self._prev_geo = None
        self._job = None
        self._photo = None
        self._img_item = None
        self.news = None
        self.planes_near: list = []
        self.planes_area: list = []
        self.planes_ts = 0.0
        self.area_ts = 0.0
        self.area_bbox = None
        self.home = (52.52, 13.40, "Berlin")
        self.status = ""
        self._tex_loading = False
        self._sat_loading = False
        self._threads_started = False
        self._labels: list = []
        self._t0 = time.time()
        self.drag = None
        self.last_input = 0.0
        self.selected = None  # ("punkt", dict) oder ("flug", dict)
        self.hits: list = []
        self.plane_xy = None
        self.panel_scroll = 0
        self._panel_sig = None
        self._card_sig = None
        self._imgs: dict = {}  # Bild-Adresse -> PIL-Bild (oder None = lädt/fehlt)
        self.tour_jobs: list = []
        self.s = 1.0

    # --- Öffentlich (nur im Tk-Thread aufrufen) ---
    def show(self, view: str = None):
        if self.win is None:
            self._create()
        if view in dict(VIEWS) and view != self.view:
            self.view = view
            self.cam = list(DEFAULT_CAM[view])
            self.selected = None
            self.panel_scroll = 0
        self.open_ = True
        self.win.deiconify()
        self._color_bar()
        self.win.lift()
        self.win.focus_force()
        if self.get_settings().get("globe_fullscreen") and not self.fullscreen:
            self.toggle_fullscreen()
        self._start_data()
        self._layout()
        if self._job is None:
            self._loop()

    def close(self):
        self.stop_tour()
        self.open_ = False
        if self.win is not None:
            if self.fullscreen:
                self.toggle_fullscreen()
            self.win.withdraw()

    def is_open(self) -> bool:
        return self.open_

    def set_view(self, view: str):
        if view in dict(VIEWS) and view != self.view:
            self.stop_tour()
            self.view = view
            self.selected = None
            self.panel_scroll = 0
            self.fly_to(*DEFAULT_CAM[view], dur=0.9)
            self._layout()
            self._start_data()

    def cycle_theme(self):
        cur = self.r.theme_name
        self.save_setting("globe_theme", THEME_NAMES[(THEME_NAMES.index(cur) + 1) % len(THEME_NAMES)])

    def toggle_style(self):
        self.save_setting("globe_style", "Satellit" if self.r.style != "Satellit" else "Hologramm")

    def apply_settings(self, s: dict):
        changed = False
        if s.get("globe_theme", "Glut") != self.r.theme_name:
            self.r.set_theme(s.get("globe_theme", "Glut"))
            changed = True
        if s.get("globe_style", "Hologramm") != self.r.style:
            self.r.set_style(s.get("globe_style", "Hologramm"))
            changed = True
            if self.r.style == "Satellit" and self.r.sat is None:
                self._load_sat()
        if changed and self.win is not None:
            self._layout()

    def toggle_fullscreen(self):
        if self.win is None:
            return
        self.fullscreen = not self.fullscreen
        try:
            self.win.attributes("-fullscreen", self.fullscreen)
        except Exception:
            self.fullscreen = False
        self.win.after(80, self._layout)

    # --- Kamera ---
    def fly_to(self, lat, lon, zoom=None, dur=1.4):
        lat = max(-80.0, min(80.0, float(lat)))
        zoom = self.cam[2] if zoom is None else zoom
        lon0 = self.cam[1]
        dl = ((float(lon) - lon0 + 180) % 360) - 180  # kürzester Weg um die Erde
        self.anim = (time.time(), dur, tuple(self.cam), (lat, lon0 + dl, zoom))

    def _step_anim(self) -> bool:
        if not self.anim:
            return False
        t0, dur, a, b = self.anim
        f = ease((time.time() - t0) / dur)
        # beim langen Flug kurz herauszoomen (wie Google Earth)
        far = abs(b[1] - a[1]) + abs(b[0] - a[0])
        dip = 1.0 - min(0.35, far / 400) * math.sin(math.pi * f)
        self.cam = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, (a[2] + (b[2] - a[2]) * f) * dip]
        if f >= 1:
            self.cam = list(b)
            self.anim = None
        return True

    def focus_zoom(self) -> float:
        return {"weltlage": 0.85, "luftraum": max(self.cam[2], 2.2), "deutschland": max(self.cam[2], 4.6)}[self.view]

    def select(self, kind, obj, fly=True):
        self.selected = (kind, obj)
        self._card_sig = None
        self._panel_sig = None
        if fly:
            self.fly_to(obj["lat"], obj["lon"], self.focus_zoom())
        if kind == "punkt" and obj.get("bild"):
            self._load_image(obj["bild"])

    # --- Tour ("Jarvis, wie ist die Lage?") ---
    def tour(self, seconds: float):
        """Fliegt die Brennpunkte aus dem Briefing nacheinander ab, passend zur Sprechdauer."""
        self.stop_tour()
        data = pc_news.get(wait=False)  # das Briefing wurde gerade geholt: dieselben Brennpunkte zeigen
        if data:
            self.news = data
            self._panel_sig = None
        pts = (self.news or {}).get("brennpunkte") or []
        stops = [p for p in pts if p.get("im_briefing")][:5] or pts[:4]
        if self.view != "weltlage":
            self.view = "weltlage"
            self.cam = list(DEFAULT_CAM["weltlage"])
            self._layout()
        self.selected = None
        if not stops:
            return
        per = max(3.5, (seconds - 1.0) / len(stops))
        for i, p in enumerate(stops):
            self.tour_jobs.append(self.win.after(int((0.6 + i * per) * 1000), lambda p=p: self.select("punkt", p)))
        self.tour_jobs.append(self.win.after(int((0.6 + len(stops) * per + 1.5) * 1000), self._tour_end))

    def _tour_end(self):
        self.tour_jobs = []
        self.fly_to(*DEFAULT_CAM["weltlage"][:2], DEFAULT_CAM["weltlage"][2], dur=2.0)

    def stop_tour(self):
        for job in self.tour_jobs:
            try:
                self.win.after_cancel(job)
            except Exception:
                pass
        self.tour_jobs = []

    # --- Aufbau ---
    def _color_bar(self):
        pc_frameless.color_titlebar(self.win, hexc(self.r.theme["bg"]), hexc(self.r.theme["dim"]))

    def _create(self):
        k = self.k
        self.win = tk.Toplevel(self.root)
        self.win.title("Jarvis – Weltlage")
        self.win.configure(bg=hexc(self.r.theme["bg"]))
        w, h = int(1280 * k), int(760 * k)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(w, sw - 40), min(h, sh - 80)
        self.win.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 20)}")
        self.win.minsize(int(720 * k), int(460 * k))
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        try:
            from pc_pill import make_app_icon

            self._icon = ImageTk.PhotoImage(make_app_icon(64))
            self.win.iconphoto(False, self._icon)
        except Exception:
            pass
        self.c = tk.Canvas(self.win, highlightthickness=0, bd=0, bg=hexc(self.r.theme["bg"]))
        self.c.pack(fill="both", expand=True)
        self.f_title = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.f_tab = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_big = tkfont.Font(family="Segoe UI", size=30, weight="bold")
        self.f_head = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.f_item = tkfont.Font(family="Segoe UI Semibold", size=10)
        self.f_text = tkfont.Font(family="Segoe UI", size=9)
        self.f_label = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        self.f_btn = tkfont.Font(family="Segoe UI Symbol", size=12)
        self._cfg_job = None
        self.win.bind("<Configure>", self._on_configure)
        self.win.bind("<Map>", lambda e: e.widget is self.win and self._color_bar())
        self.win.bind("<Escape>", lambda e: self.toggle_fullscreen() if self.fullscreen else self.close())
        self.win.bind("<F11>", lambda e: self.toggle_fullscreen())
        for i, (key, _) in enumerate(VIEWS):
            self.win.bind(str(i + 1), lambda e, key=key: self.set_view(key))
        self.c.bind("<ButtonPress-1>", self._press)
        self.c.bind("<B1-Motion>", self._motion)
        self.c.bind("<ButtonRelease-1>", self._release)
        self.c.bind("<Double-Button-1>", self._double)
        self.c.bind("<MouseWheel>", self._wheel)

    def _on_configure(self, e):
        if e.widget is not self.win:
            return
        if self._cfg_job:
            self.win.after_cancel(self._cfg_job)
        self._cfg_job = self.win.after(120, self._layout)

    def _sizes(self):
        self.win.update_idletasks()
        W, H = max(200, self.c.winfo_width()), max(200, self.c.winfo_height())
        return W, H, max(0.6, min(W / 1280, H / 760))

    def _globe_geom(self):
        """Mittelpunkt und Radius des Globus für die aktuelle Kamera."""
        W, H = self.size
        gw, gh = W - self.panel_w, H - self.top_h
        m = min(gw, gh)
        return gw / 2, self.top_h + gh * 0.53, m * self.cam[2]

    def _layout(self):
        """Baut die Oberfläche für die aktuelle Fenstergröße und Ansicht neu auf."""
        if self.win is None:
            return
        self._cfg_job = None
        W, H, s = self._sizes()
        self.size, self.s = (W, H), s
        t = self.r.theme
        for f, base in ((self.f_title, 11), (self.f_tab, 10), (self.f_big, 30), (self.f_head, 12), (self.f_item, 11),
                        (self.f_text, 10), (self.f_label, 8), (self.f_btn, 13)):
            f.configure(size=max(7, int(round(base * s))))
        c = self.c
        c.delete("all")
        c.configure(bg=hexc(t["bg"]))
        self.win.configure(bg=hexc(t["bg"]))
        self._color_bar()
        self.top_h = int(56 * s)
        self.panel_w = int(390 * s) if W > 900 * s else 0
        self._img_item = c.create_image(0, 0, anchor="nw", tags="globeimg")
        self._photo = None  # neues Bild-Element: Bild neu zuweisen (sonst bleibt es leer)
        self._labels = []
        self._panel_sig = None
        self._card_sig = None

        acc, txt, dim = hexc(t["accent"]), hexc(t["text"]), hexc(t["dim"])
        c.create_rectangle(0, 0, W, self.top_h, fill=hexc(t["bg"]), outline="", tags="bar")
        c.create_line(0, self.top_h, W, self.top_h, fill=hexc(mix(t["bg"], t["accent"], 0.35)), tags="bar")
        c.create_text(int(22 * s), self.top_h // 2, text="◉  J.A.R.V.I.S.", anchor="w", fill=acc, font=self.f_title,
                      tags="bar")
        tab_w = int(126 * s)
        x = W / 2 - tab_w * len(VIEWS) / 2
        for key, label in VIEWS:
            on = key == self.view
            tag = f"tab_{key}"
            r = int(15 * s)
            self._pill(x + 4, self.top_h / 2 - r, x + tab_w - 4, self.top_h / 2 + r,
                       mix(t["bg"], t["accent"], 0.85 if on else 0.14), tag)
            c.create_text(x + tab_w / 2, self.top_h / 2, text=label.upper(), font=self.f_tab,
                          fill=hexc(t["bg"]) if on else txt, tags=tag)
            c.tag_bind(tag, "<Button-1>", lambda e, key=key: self.set_view(key))
            self._hand(tag)
            x += tab_w
        # rechts: Stil, Farben, Vollbild
        bx = W - int(24 * s)
        for glyph, tag, fn in (("⛶", "b_full", self.toggle_fullscreen), ("◐", "b_theme", self.cycle_theme)):
            c.create_text(bx, self.top_h // 2, text=glyph, font=self.f_btn, fill=dim, tags=tag)
            c.tag_bind(tag, "<Button-1>", lambda e, fn=fn: fn())
            c.tag_bind(tag, "<Enter>", lambda e, tag=tag: (c.itemconfigure(tag, fill=acc), c.config(cursor="hand2")))
            c.tag_bind(tag, "<Leave>", lambda e, tag=tag: (c.itemconfigure(tag, fill=dim), c.config(cursor="")))
            bx -= int(40 * s)
        style_txt = "SATELLIT" if self.r.style == "Satellit" else "HOLOGRAMM"
        r = int(13 * s)
        pw = int(116 * s)
        self._pill(bx - pw, self.top_h / 2 - r, bx, self.top_h / 2 + r, mix(t["bg"], t["accent"], 0.14), "b_style")
        c.create_text(bx - pw / 2, self.top_h / 2, text="◎ " + style_txt, font=self.f_label, fill=txt, tags="b_style")
        c.tag_bind("b_style", "<Button-1>", lambda e: self.toggle_style())
        self._hand("b_style")

        self.t_big = c.create_text(int(30 * s), self.top_h + int(20 * s), text="", anchor="nw", fill=acc, font=self.f_big)
        self.t_sub = c.create_text(int(32 * s), self.top_h + int(72 * s), text="", anchor="nw", fill=txt, font=self.f_head)
        self.t_status = c.create_text(int(32 * s), H - int(14 * s), text="", anchor="sw", fill=dim, font=self.f_text)
        self.t_hint = c.create_text(W - self.panel_w - int(18 * s), H - int(14 * s), anchor="se", fill=dim,
                                    font=self.f_text, text="Ziehen = drehen · Mausrad = zoomen · Klick auf einen Punkt = Details")
        need_tex = self.r.lights is None and self.r.land is None
        if need_tex and not self._tex_loading:
            self._tex_loading = True
            threading.Thread(target=self._load_tex, daemon=True).start()
        if self.r.style == "Satellit" and self.r.sat is None:
            self._load_sat()

    def _pill(self, x0, y0, x1, y1, fill, tag):
        r = (y1 - y0) / 2
        c, col = self.c, hexc(fill)
        c.create_oval(x0, y0, x0 + 2 * r, y1, fill=col, outline="", tags=tag)
        c.create_oval(x1 - 2 * r, y0, x1, y1, fill=col, outline="", tags=tag)
        c.create_rectangle(x0 + r, y0, x1 - r, y1, fill=col, outline="", tags=tag)

    def _hand(self, tag):
        self.c.tag_bind(tag, "<Enter>", lambda e: self.c.config(cursor="hand2"), add="+")
        self.c.tag_bind(tag, "<Leave>", lambda e: self.c.config(cursor=""), add="+")

    def _after(self, fn):
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def _load_tex(self):
        tex = load_textures()

        def done():
            self.r.set_textures(tex["lights"], tex["land"])
            self._tex_loading = False
        self._after(done)

    def _load_sat(self):
        if self._sat_loading:
            return
        self._sat_loading = True

        def run():
            sat = load_sat()

            def done():
                self._sat_loading = False
                if sat is not None:
                    self.r.set_textures(sat=sat)
                    if self.win is not None:
                        self._layout()
            self._after(done)
        threading.Thread(target=run, daemon=True).start()

    def _load_image(self, url):
        if url in self._imgs:
            return
        self._imgs[url] = None

        def run():
            try:
                import hashlib

                path = os.path.join(_folder("bilder"), hashlib.sha1(url.encode()).hexdigest()[:20] + ".img")
                if not os.path.exists(path):
                    with open(path, "wb") as f:
                        f.write(_fetch(url, 15))
                im = Image.open(path).convert("RGB")
                im.thumbnail((900, 600))

                def done():
                    self._imgs[url] = im
                    self._card_sig = None
                self._after(done)
            except Exception as e:
                print(f"Bild nicht geladen: {e}")
        threading.Thread(target=run, daemon=True).start()

    # --- Maus ---
    def _in_globe(self, x, y) -> bool:
        if y < self.top_h or x > self.size[0] - self.panel_w:
            return False
        bb = self.c.bbox("card")
        return not (bb and bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3])

    def _press(self, e):
        if not self._in_globe(e.x, e.y):
            self.drag = None
            return
        self.drag = (e.x, e.y, list(self.cam), False)

    def _motion(self, e):
        if not self.drag:
            return
        x0, y0, cam0, moved = self.drag
        dx, dy = e.x - x0, e.y - y0
        if not moved and abs(dx) + abs(dy) < 5:
            return
        self.stop_tour()
        self.anim = None
        R = self._globe_geom()[2]
        deg = 57.2958 / max(1.0, R)
        self.cam = [max(-80.0, min(80.0, cam0[0] + dy * deg)), cam0[1] - dx * deg, cam0[2]]
        self.drag = (x0, y0, cam0, True)
        self.last_input = time.time()

    def _release(self, e):
        if not self.drag:
            return
        moved = self.drag[3]
        self.drag = None
        self.last_input = time.time()
        if not moved:
            self._click(e.x, e.y)

    def _double(self, e):
        if self._in_globe(e.x, e.y):
            self.stop_tour()
            self.selected = None
            self.fly_to(*DEFAULT_CAM[self.view], dur=1.0)

    def _wheel(self, e):
        W, H = self.size
        if self.panel_w and e.x > W - self.panel_w:
            self.panel_scroll = max(0, self.panel_scroll - int(e.delta / 120 * 60 * self.s))
            self._panel_sig = None
            return
        self.stop_tour()
        lo, hi = ZOOM_LIMITS
        z = max(lo, min(hi, self.cam[2] * (1.15 ** (e.delta / 120))))
        if self.anim:
            self.anim = (self.anim[0], self.anim[1], self.anim[2], (self.anim[3][0], self.anim[3][1], z))
        else:
            self.cam[2] = z
        self.last_input = time.time()

    def _click(self, x, y):
        best, bd = None, (14 * self.s) ** 2
        for hx, hy, kind, obj in self.hits:
            d = (hx - x) ** 2 + (hy - y) ** 2
            if d < bd:
                best, bd = (kind, obj), d
        if best is None and self.plane_xy is not None:
            px, py, planes = self.plane_xy
            if len(px):
                d = (px - x) ** 2 + (py - y) ** 2
                i = int(np.argmin(d))
                if d[i] < (9 * self.s) ** 2:
                    best = ("flug", planes[i])
        if best:
            self.stop_tour()
            self.select(*best)
        else:
            self.selected = None
            self._card_sig = None

    # --- Daten ---
    def _start_data(self):
        if self._threads_started:
            return
        self._threads_started = True
        threading.Thread(target=self._data_loop, daemon=True).start()

    def _data_loop(self):
        try:
            import pc_info

            city = self.get_settings().get("weather_city") or "Berlin"
            lat, lon, name = pc_info.geocode(city)
            self.home = (float(lat), float(lon), name)
        except Exception:
            pass
        last_news = 0.0
        while True:
            if not self.open_:
                time.sleep(1.0)
                continue
            now = time.time()
            if now - last_news > 60:
                last_news = now
                data = pc_news.get(wait=self.news is None)
                if data and data is not self.news:
                    self.news = data
                    self._panel_sig = None
            if self.view in ("luftraum", "deutschland") and now - self.planes_ts > 15:
                self.planes_ts = now
                try:
                    near = pc_flights.around(self.home[0], self.home[1], 250)
                    self._stamp(near, now)
                    self.planes_near = near
                    self.status = f"ADS-B live · {len(near)} Flugzeuge im Umkreis von 460 km um {self.home[2]}"
                except Exception as e:
                    self.status = f"Flugdaten gerade nicht erreichbar ({str(e)[:60]})"
                self._panel_sig = None
            bbox = (46.5, 4.5, 55.8, 16.5) if self.view == "deutschland" else (34, -25, 72, 45)
            wait = 0 if bbox != self.area_bbox else 300  # neues Gebiet sofort, sonst alle 5 Minuten (OpenSky-Limit)
            if now - self.area_ts > max(wait, 20) and (self.view != "weltlage" or not self.planes_area):
                self.area_ts = now
                try:
                    area = pc_flights.area(*bbox)
                    self._stamp(area, now)
                    self.planes_area, self.area_bbox = area, bbox
                except Exception as e:
                    print(f"OpenSky: {e}")
                    self.area_ts = now + 300
            time.sleep(1.0)

    @staticmethod
    def _stamp(planes, ts):
        for p in planes:
            p["ts"] = ts

    def _all_planes(self):
        near_ids = {p["id"] for p in self.planes_near}
        return self.planes_near + [p for p in self.planes_area if p["id"] not in near_ids]

    # --- Zeichnen ---
    def _loop(self):
        if not self.open_ or self.win is None:
            self._job = None
            return
        t0 = time.time()
        try:
            if self.win.state() != "iconic":
                self._render()
        except Exception as e:
            if str(e) != getattr(self, "_last_err", ""):
                self._last_err = str(e)
                print(f"Globus: {e}")
        spent = time.time() - t0
        busy = self.anim or self.drag or self.view == "weltlage"
        self._job = self.win.after(max(15, int((55 if busy else 100) - spent * 1000)), self._loop)

    def _render(self):
        r, t, s = self.r, self.r.theme, self.s
        W, H = self.size
        now = time.time()
        moving = self._step_anim() or bool(self.drag and self.drag[3])
        idle = now - self.last_input > 8 and not self.tour_jobs and not self.anim and not self.selected
        if self.view == "weltlage" and idle and not self.drag:
            self.cam[1] = (self.cam[1] + 0.12) % 360.0  # langsam drehen, wenn niemand etwas tut
        cx, cy, R = self._globe_geom()
        lat0, lon0 = self.cam[0], self.cam[1]
        if moving:
            img = r.frame(W, H, cx, cy, R, lat0, lon0, q=0.5)
        elif self.view == "weltlage" and idle:
            img = r.frame(W, H, cx, cy, R, lat0, lon0, q=1.0)
        else:
            img = r.cached_frame(W, H, cx, cy, R, lat0, lon0)
        p = Projection(W, H, cx, cy, R, lat0, grid=False)
        d = ImageDraw.Draw(img)
        pulse = (math.sin((now - self._t0) * 3.0) + 1) / 2
        self.hits = []
        self.plane_xy = None

        # Flugzeuge
        planes = self._all_planes() if self.view != "weltlage" else self.planes_area
        if planes:
            n = len(planes)
            lat, lon, tlat, tlon = np.empty(n), np.empty(n), np.empty(n), np.empty(n)
            for i, pl in enumerate(planes):
                dt = min(600.0, now - pl.get("ts", now))
                lat[i], lon[i] = pc_flights.move(pl, dt)
                tlat[i], tlon[i] = pc_flights.move(pl, dt - 90)  # Schweif: wo es vor 90 s war
            x, y, vis = p.project(lat, lon, lon0)
            x2, y2, _ = p.project(tlat, tlon, lon0)
            c2 = t["accent2"] if self.view != "weltlage" else mix(t["bg"], t["accent2"], 0.55)
            tail = mix(t["bg"], c2, 0.45)
            rad = max(1.0, 1.6 * s * (1.4 if self.cam[2] > 3 else 1.0))
            ok = vis & (x >= 0) & (x < W) & (y >= self.top_h) & (y < H)
            for i in np.nonzero(ok)[0]:
                d.line((x2[i], y2[i], x[i], y[i]), fill=tail, width=1)
                d.ellipse((x[i] - rad, y[i] - rad, x[i] + rad, y[i] + rad), fill=c2)
            idx = np.nonzero(ok)[0]
            self.plane_xy = (x[idx], y[idx], [planes[i] for i in idx])
            if self.selected and self.selected[0] == "flug":
                sp = self.selected[1]
                k = next((i for i in idx if planes[i] is sp), None)
                if k is not None:
                    rr = (7 + 4 * pulse) * s
                    d.ellipse((x[k] - rr, y[k] - rr, x[k] + rr, y[k] + rr), outline=t["text"], width=2)
        # Zuhause
        hx, hy, hv = p.project([self.home[0]], [self.home[1]], lon0)
        home_xy = (float(hx[0]), float(hy[0])) if hv[0] else None
        if home_xy:
            rr = (4 + 5 * pulse) * s
            d.ellipse((home_xy[0] - rr, home_xy[1] - rr, home_xy[0] + rr, home_xy[1] + rr), outline=t["accent"], width=2)
            d.ellipse((home_xy[0] - 2.5 * s, home_xy[1] - 2.5 * s, home_xy[0] + 2.5 * s, home_xy[1] + 2.5 * s), fill=t["text"])
        # Brennpunkte
        labels = []
        points = self._points()
        if points:
            x, y, vis = p.project([q["lat"] for q in points], [q["lon"] for q in points], lon0)
            for i, q in enumerate(points):
                if not vis[i] or not (0 <= x[i] < W - self.panel_w and self.top_h <= y[i] < H):
                    continue
                col = KIND_COLORS.get(q.get("art")) or t["accent"]
                imp = max(1, min(3, int(q.get("wichtig", 2))))
                sel = self.selected and self.selected[1] is q
                if self.view == "weltlage" and home_xy:
                    self._arc(d, p, (self.home[0], self.home[1]), (q["lat"], q["lon"]), lon0,
                              mix(t["bg"], col, 0.85 if sel else 0.5), now)
                rr = (5 + 3 * imp + 8 * ((pulse + i * 0.37) % 1.0)) * s
                d.ellipse((x[i] - rr, y[i] - rr, x[i] + rr, y[i] + rr), outline=mix(t["bg"], col, 0.75), width=2)
                rc = (2.5 + imp + (2 if sel else 0)) * s
                d.ellipse((x[i] - rc, y[i] - rc, x[i] + rc, y[i] + rc), fill=col)
                if sel:
                    d.ellipse((x[i] - rc - 6 * s, y[i] - rc - 6 * s, x[i] + rc + 6 * s, y[i] + rc + 6 * s),
                              outline=t["text"], width=2)
                labels.append((x[i], y[i], q, sel))
                self.hits.append((x[i], y[i], "punkt", q))
        # Bild ausgeben
        if self._photo is None or self._photo.width() != img.width or self._photo.height() != img.height:
            self._photo = ImageTk.PhotoImage(img)
            self.c.itemconfigure(self._img_item, image=self._photo)
        else:
            self._photo.paste(img)
        self._draw_labels(labels)
        self._update_texts(planes)
        self._draw_panel()
        self._draw_card()
        self.c.tag_raise("panel")
        self.c.tag_raise("card")

    def _points(self):
        if not self.news or self.view == "luftraum":
            return []
        pts = self.news.get("brennpunkte") or []
        if self.view == "deutschland":
            pts = [q for q in pts if q.get("deutschland")]
        return pts[:12]

    def _arc(self, d, p, a, b, lon0, col, now):
        """Großkreis-Bogen von a nach b (mit kleinem wandernden Lichtpunkt)."""
        la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
        v1 = np.array([math.cos(la1) * math.cos(lo1), math.cos(la1) * math.sin(lo1), math.sin(la1)])
        v2 = np.array([math.cos(la2) * math.cos(lo2), math.cos(la2) * math.sin(lo2), math.sin(la2)])
        om = math.acos(max(-1.0, min(1.0, float(v1 @ v2))))
        if om < 1e-3:
            return
        ts = np.linspace(0, 1, 40)
        pts = (np.sin((1 - ts) * om)[:, None] * v1 + np.sin(ts * om)[:, None] * v2) / math.sin(om)
        lift = 1 + 0.18 * om / math.pi * np.sin(ts * math.pi)
        lat = np.degrees(np.arcsin(np.clip(pts[:, 2], -1, 1)))
        lon = np.degrees(np.arctan2(pts[:, 1], pts[:, 0]))
        x, y, vis = p.project(lat, lon, lon0)
        x = p.cx + (x - p.cx) * lift
        y = p.cy + (y - p.cy) * lift
        for i in range(len(ts) - 1):
            if vis[i] and vis[i + 1]:
                d.line((x[i], y[i], x[i + 1], y[i + 1]), fill=col, width=1)
        k = int(((now * 0.35) % 1.0) * (len(ts) - 1))
        if vis[k]:
            d.ellipse((x[k] - 2, y[k] - 2, x[k] + 2, y[k] + 2), fill=mix(col, (255, 255, 255), 0.5))

    def _draw_labels(self, labels):
        c, t, s = self.c, self.r.theme, self.s
        for item in self._labels:
            c.delete(item)
        self._labels = []
        gw = self.size[0] - self.panel_w
        for x, y, q, sel in labels[:9]:
            if x > gw - 60 * s:
                continue
            txt = q.get("titel") or q.get("ort", "")
            col = hexc(t["text"]) if sel else hexc(mix(t["bg"], t["text"], 0.85))
            a = c.create_text(x + 13 * s, y - 9 * s, text=txt.upper(), anchor="w", fill=col, font=self.f_label)
            b = c.create_text(x + 13 * s, y + 7 * s, text=q.get("ort", ""), anchor="w", fill=hexc(t["dim"]),
                              font=self.f_label)
            self._labels += [a, b]

    def _update_texts(self, planes):
        c = self.c
        news = self.news or {}
        if self.view == "weltlage":
            n = len(news.get("brennpunkte") or [])
            big, sub = (f"{n}", "BRENNPUNKTE WELTWEIT") if n else ("…", "LADE NACHRICHTEN")
            st = time.strftime("%H:%M", time.localtime(news.get("zeit", time.time())))
            status = f"Stand {st} Uhr · tagesschau, DW, BBC, Google News"
        elif self.view == "luftraum":
            big, sub = f"{len(planes)}", "FLUGZEUGE ÜBER EUROPA"
            status = self.status or "Lade Flugdaten …"
        else:
            n = len([q for q in (news.get("brennpunkte") or []) if q.get("deutschland")])
            big, sub = f"{len(planes)}", f"FLUGZEUGE · {n} MELDUNGEN AUS DEUTSCHLAND"
            status = self.status or "Lade Flugdaten …"
        if self._tex_loading:
            status = "Lade Erdkarte (nur beim ersten Mal) … · " + status
        if self._sat_loading:
            status = "Lade Satellitenbild (nur beim ersten Mal, ca. 10 MB) … · " + status
        c.itemconfigure(self.t_big, text=big)
        c.itemconfigure(self.t_sub, text=sub)
        c.itemconfigure(self.t_status, text=status)

    # --- Rechte Spalte ---
    def _panel_entries(self):
        """Einträge der rechten Spalte: [(art, objekt, titel, unterzeile, farbe)]."""
        t = self.r.theme
        news = self.news or {}
        out = []
        if self.view in ("weltlage", "deutschland"):
            pts = self._points()
            for q in pts:
                col = KIND_COLORS.get(q.get("art")) or t["accent"]
                out.append(("punkt", q, q.get("titel", ""), f"{q.get('ort', '')} · {q.get('text', '')}", col))
            if self.view == "deutschland" and not pts:
                for it in (news.get("schlagzeilen") or [])[:10]:
                    out.append(("text", it, it["titel"], it.get("quelle", ""), t["dim"]))
        else:
            hl, ho = self.home[0], self.home[1]
            near = sorted(self.planes_near, key=lambda p: pc_flights.distance_km(hl, ho, p["lat"], p["lon"]))[:25]
            for p in near:
                km = pc_flights.distance_km(hl, ho, p["lat"], p["lon"])
                info = f"{km:.0f} km entfernt · {int(p['alt']):,} m · {int(p['speed'])} km/h".replace(",", ".")
                if p.get("type"):
                    info += f" · {p['type']}"
                out.append(("flug", p, p["call"] or p["id"], info, t["accent2"]))
        return out

    def _draw_panel(self):
        if not self.panel_w:
            return
        sel_id = id(self.selected[1]) if self.selected else None
        sig = (self.view, id(self.news), len(self.planes_near), self.size, self.r.theme_name, self.panel_scroll, sel_id)
        if sig == self._panel_sig:
            return
        self._panel_sig = sig
        c, t, s = self.c, self.r.theme, self.s
        c.delete("panel")
        W, H = self.size
        x0, y0, x1, y1 = W - self.panel_w + int(8 * s), self.top_h + int(14 * s), W - int(16 * s), H - int(18 * s)
        card = Image.new("RGBA", (int(x1 - x0), int(y1 - y0)), (0, 0, 0, 0))
        ImageDraw.Draw(card).rounded_rectangle((0, 0, card.width - 1, card.height - 1), radius=int(16 * s),
                                               fill=t["panel"] + (255,), outline=mix(t["bg"], t["accent"], 0.45) + (255,),
                                               width=max(1, int(1.5 * s)))
        bg = Image.new("RGB", card.size, t["bg"])
        bg.paste(card, (0, 0), card)
        self._panel_photo = ImageTk.PhotoImage(bg)
        c.create_image(x0, y0, anchor="nw", image=self._panel_photo, tags="panel")
        pad = int(18 * s)
        x, wrap = x0 + pad, int(x1 - x0 - 2 * pad)
        acc, txt, dim = hexc(t["accent"]), hexc(t["text"]), hexc(t["dim"])
        news = self.news or {}
        y = y0 + pad
        top_clip, bottom_clip = y0 + int(6 * s), y1 - int(10 * s)

        def put(item):
            bb = c.bbox(item)
            return bb[3] if bb else y

        # Kopf (scrollt mit)
        y -= self.panel_scroll
        heads = []
        if self.view == "weltlage":
            heads = [("LAGEBERICHT", news.get("briefing") or "Lade Nachrichten …"), ("BRENNPUNKTE", None)]
        elif self.view == "deutschland":
            heads = [("DEUTSCHLAND", None)]
        else:
            heads = [("IN DEINER NÄHE", f"Live-Flugzeuge rund um {self.home[2]}. Klick auf ein Flugzeug für Details.")]
        for head, body in heads:
            it = c.create_text(x, y, text=head, anchor="nw", fill=acc, font=self.f_head, tags="panel")
            y = put(it) + int(6 * s)
            if body:
                it = c.create_text(x, y, text=body, anchor="nw", fill=txt, font=self.f_text, width=wrap, tags="panel")
                y = put(it) + int(16 * s)
        for i, (kind, obj, title, sub, col) in enumerate(self._panel_entries()):
            tag = f"pe{i}"
            sel = self.selected is not None and self.selected[1] is obj
            ytop = y
            dot = c.create_oval(x, y + 6 * s, x + 9 * s, y + 15 * s, fill=hexc(col), outline="", tags=("panel", tag))
            it = c.create_text(x + 18 * s, y, text=title, anchor="nw", fill=txt, font=self.f_item,
                               width=wrap - 18 * s, tags=("panel", tag))
            y = put(it) + int(3 * s)
            sub_short = sub if len(sub) <= 170 else sub[:168].rsplit(" ", 1)[0] + " …"
            it2 = c.create_text(x + 18 * s, y, text=sub_short, anchor="nw", fill=dim, font=self.f_text,
                                width=wrap - 18 * s, tags=("panel", tag))
            y = put(it2) + int(14 * s)
            if sel:
                c.create_rectangle(x - 10 * s, ytop - 4 * s, x - 6 * s, y - 10 * s, fill=acc, outline="",
                                   tags=("panel", tag))
            if kind in ("punkt", "flug"):
                c.tag_bind(tag, "<Button-1>", lambda e, kind=kind, obj=obj: (self.stop_tour(), self.select(kind, obj)))
                self._hand(tag)
            if ytop < top_clip or y > bottom_clip:  # außerhalb des sichtbaren Bereichs: wieder weg
                c.delete(tag)
            if ytop > bottom_clip:
                break
        # Kopfzeilen, die nach oben herausgescrollt sind, verdecken
        for item in c.find_withtag("panel"):
            bb = c.bbox(item)
            if bb and item != c.find_withtag("panel")[0] and (bb[1] < top_clip or bb[3] > bottom_clip):
                c.delete(item)

    # --- Detailkarte links ---
    def _draw_card(self):
        sel = self.selected
        img = self._imgs.get(sel[1].get("bild")) if sel and sel[0] == "punkt" and sel[1].get("bild") else None
        sig = (id(sel[1]) if sel else None, self.size, self.r.theme_name, id(img))
        if sig == self._card_sig:
            return
        self._card_sig = sig
        c, t, s = self.c, self.r.theme, self.s
        c.delete("card")
        if not sel:
            return
        kind, obj = sel
        W, H = self.size
        cw = int(min(380 * s, (W - self.panel_w) * 0.34))
        x0, y0 = int(26 * s), self.top_h + int(118 * s)
        pad = int(16 * s)
        acc, txt, dim = hexc(t["accent"]), hexc(t["text"]), hexc(t["dim"])
        items = []
        y = y0 + pad
        photo = None
        if img is not None:
            iw = cw - 2 * pad
            ih = int(iw * img.height / max(1, img.width))
            ih = min(ih, int(230 * s))
            photo = ImageTk.PhotoImage(img.resize((iw, ih), Image.BILINEAR))
            self._card_photo = photo
            y += ih + int(12 * s)
        if kind == "punkt":
            col = KIND_COLORS.get(obj.get("art")) or t["accent"]
            items.append((obj.get("art", "").upper() + (" · " + obj.get("quelle", "") if obj.get("quelle") else ""),
                          self.f_label, hexc(col)))
            items.append((obj.get("titel", ""), self.f_head, txt))
            items.append((obj.get("ort", ""), self.f_text, acc))
            items.append((obj.get("text", ""), self.f_text, txt))
            if obj.get("schlagzeile") and obj.get("schlagzeile") != obj.get("titel"):
                items.append(("„" + obj["schlagzeile"] + "“", self.f_text, dim))
        else:
            km = pc_flights.distance_km(self.home[0], self.home[1], obj["lat"], obj["lon"])
            items.append(("FLUGZEUG · LIVE", self.f_label, hexc(t["accent2"])))
            items.append((obj.get("call") or obj.get("id", ""), self.f_head, txt))
            items.append((f"{km:.0f} km von {self.home[2]} entfernt", self.f_text, acc))
            info = f"Höhe {int(obj['alt']):,} m · {int(obj['speed'])} km/h · Kurs {int(obj['track'])}°".replace(",", ".")
            if obj.get("type"):
                info += f"\nTyp {obj['type']}"
            if obj.get("land"):
                info += f"\nRegistriert in {obj['land']}"
            items.append((info, self.f_text, txt))
        # erst Texte setzen, um die Höhe zu kennen
        created = []
        for text, font, col in items:
            if not text:
                continue
            it = c.create_text(x0 + pad, y, text=text, anchor="nw", fill=col, font=font, width=cw - 2 * pad,
                               tags="card")
            bb = c.bbox(it)
            y = (bb[3] if bb else y) + int(8 * s)
            created.append(it)
        link = None
        if kind == "punkt" and obj.get("link"):
            link = c.create_text(x0 + pad, y + int(2 * s), text="Artikel öffnen  ↗", anchor="nw", fill=acc,
                                 font=self.f_item, tags=("card", "card_link"))
            c.tag_bind("card_link", "<Button-1>", lambda e, u=obj["link"]: webbrowser.open(u))
            self._hand("card_link")
            y += int(30 * s)
        close = c.create_text(x0 + cw - pad, y0 + pad - 4 * s, text="✕", anchor="ne", fill=dim, font=self.f_btn,
                              tags=("card", "card_close"))
        c.tag_bind("card_close", "<Button-1>", lambda e: (setattr(self, "selected", None),
                                                          setattr(self, "_card_sig", None),
                                                          setattr(self, "_panel_sig", None)))
        self._hand("card_close")
        y1 = min(H - int(40 * s), y + pad)
        bgimg = Image.new("RGBA", (cw, max(10, int(y1 - y0))), (0, 0, 0, 0))
        ImageDraw.Draw(bgimg).rounded_rectangle((0, 0, bgimg.width - 1, bgimg.height - 1), radius=int(14 * s),
                                                fill=t["panel"] + (238,), outline=mix(t["bg"], t["accent"], 0.5) + (255,),
                                                width=max(1, int(1.5 * s)))
        self._card_bg = ImageTk.PhotoImage(bgimg)
        bgi = c.create_image(x0, y0, anchor="nw", image=self._card_bg, tags="card")
        c.tag_lower(bgi, created[0] if created else close)
        if photo is not None:
            c.create_image(x0 + pad, y0 + pad, anchor="nw", image=photo, tags="card")
        c.tag_raise("card")
        if link:
            c.tag_raise(link)
