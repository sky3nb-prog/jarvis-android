"""
Die goldene Daten-Kugel für das HUD (wie das Hologramm aus dem Film).

Damit sie flüssig läuft, wird sie nicht in jedem Bild neu gerechnet: Beim ersten Start (und nach einem Farbwechsel)
rechnet Jarvis einmal 48 Einzelbilder einer Drehung im Hintergrund (ca. 20 bis 40 Sekunden) und speichert sie im
Ordner "globus/kugel" neben dem Programm. Danach werden die Bilder nur noch abgespielt, das kostet kaum Rechenzeit.
Die Kugel ist sechsfach gleich aufgebaut, deshalb reichen 60 Grad Drehung für eine endlose, gleichmäßige Bewegung.

Das "Atmen" (Leuchten und Stimm-Ring) zeichnet das HUD selbst, abhängig von der Lautstärke (LEVEL).
"""

import math
import os
import threading

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

FRAMES = 48
BASE = 640  # Kantenlänge der gespeicherten Bilder
VERSION = "v2"
# Farbe -> (Grundfarbe, helle Farbe, Kern)
COLORS = {
    "Gold": ((255, 166, 36), (255, 214, 120), (255, 232, 176)),
    "Cyan": ((40, 190, 255), (150, 235, 255), (210, 248, 255)),
    "Rot": ((255, 70, 50), (255, 150, 120), (255, 210, 190)),
    "Grün": ((60, 230, 120), (170, 255, 190), (220, 255, 225)),
    "Violett": ((170, 110, 255), (215, 180, 255), (240, 225, 255)),
    "Weiß": ((200, 210, 225), (240, 245, 255), (255, 255, 255)),
}
COLOR_NAMES = list(COLORS)

LEVEL = {"mic": 0.0, "out": 0.0}  # aktuelle Lautstärke 0..1 (Mikrofon, Jarvis' Stimme)


def set_level(kind: str, value: float):
    """Glättet die Lautstärke ein wenig (schnell hoch, langsam runter)."""
    old = LEVEL.get(kind, 0.0)
    v = max(0.0, min(1.0, value))
    LEVEL[kind] = v if v > old else old * 0.85 + v * 0.15


def level() -> float:
    return max(LEVEL["mic"], LEVEL["out"])


def _rot(lat, lon, rx, ry):
    la, lo = np.radians(lat), np.radians(lon)
    x = np.cos(la) * np.sin(lo)
    y = np.sin(la)
    z = np.cos(la) * np.cos(lo)
    cy, sy = math.cos(ry), math.sin(ry)
    x, z = x * cy + z * sy, -x * sy + z * cy
    cx, sx = math.cos(rx), math.sin(rx)
    y, z = y * cx - z * sx, y * sx + z * cx
    return x, y, z


class _Design:
    """Zufällig, aber fest (gleicher Startwert): die Bausteine der Kugel für 60 Grad, sechsmal wiederholt."""

    def __init__(self, seed=7):
        rng = np.random.default_rng(seed)
        self.lines = []  # (Punkte [(lat, lon, r)], hell?, Breite)
        for shell, n, wmax in ((1.0, 90, 2), (0.9, 56, 2), (0.74, 40, 1), (0.55, 24, 1)):
            for _ in range(n):
                la = float(np.degrees(np.arcsin(rng.uniform(-1, 1))))
                lo = float(rng.uniform(0, 60))
                L = rng.uniform(2, 16) if rng.random() < 0.8 else rng.uniform(20, 42)
                along = rng.random() < 0.78
                pts = [(la, lo + t, shell) if along else (max(-89, min(89, la + t)), lo, shell)
                       for t in np.linspace(0, L, 6)]
                self.lines.append((pts, rng.random() < 0.12, int(rng.integers(1, wmax + 1))))
        for _ in range(44):  # ausfransender Rand
            la, lo = float(np.degrees(np.arcsin(rng.uniform(-1, 1)))), float(rng.uniform(0, 60))
            r0 = rng.uniform(0.98, 1.16)
            self.lines.append(([(la, lo, r0), (la, lo + rng.uniform(2, 9), r0 + rng.uniform(-0.02, 0.05))], False,
                               int(rng.integers(1, 3))))
        for _ in range(15):  # kurze Strahlen
            la, lo = float(np.degrees(np.arcsin(rng.uniform(-1, 1)))), float(rng.uniform(0, 60))
            self.lines.append(([(la, lo, rng.uniform(0.9, 1.0)), (la, lo, rng.uniform(1.06, 1.22))], True, 1))
        self.boxes = []
        for _ in range(20):
            la, lo = float(np.degrees(np.arcsin(rng.uniform(-0.9, 0.9)))), float(rng.uniform(0, 60))
            sh = float(rng.choice([1.0, 0.86, 0.7]))
            dw, dh = rng.uniform(3, 9), rng.uniform(2, 6)
            self.boxes.append((la, lo, sh, dw, dh, rng.random() < 0.5, rng.uniform(0.4, 1.0)))
        n = 300
        self.dots = (np.degrees(np.arcsin(rng.uniform(-1, 1, n))), rng.uniform(0, 60, n),
                     rng.choice([1.0, 0.93, 0.86, 0.6], n))
        # große Ringe: gestrichelt mit einem Muster, das sich alle 60 Grad wiederholt (nahtlose Schleife)
        self.arcs = []
        for _ in range(6):
            segs = []
            a = rng.uniform(0, 20)
            while a < 60:
                L = rng.uniform(8, 34)
                segs.append((a, min(60, a + L)))
                a += L + rng.uniform(4, 16)
            self.arcs.append((rng.uniform(-70, 70), segs, rng.uniform(0.55, 1.08)))


def render_frame(i: int, color: str = "Gold", size: int = BASE, rx: float = 0.35) -> Image.Image:
    base, hot, core = COLORS.get(color, COLORS["Gold"])
    d0 = _Design()
    S = size
    img = Image.new("RGB", (S, S), (0, 0, 0))
    d = ImageDraw.Draw(img)
    c, R = S / 2, S * 0.38
    ry = math.radians(i * 60.0 / FRAMES)

    def col(z, rgb, k=1.0):
        f = (0.08 + 0.92 * ((z + 1) / 2) ** 1.7) * k
        return tuple(int(min(255, v * f)) for v in rgb)

    for rep in range(6):
        off = rep * 60.0
        for pts, bright, w in d0.lines:
            la = np.array([p[0] for p in pts])
            lo = np.array([p[1] for p in pts]) + off
            r = np.array([p[2] for p in pts])
            x, y, z = _rot(la, lo, rx, ry)
            xy = list(zip(c + x * R * r, c - y * R * r))
            d.line(xy, fill=col(float(z.mean()), hot if bright else base, 1.2 if bright else 0.85), width=w)
        for la, lo, sh, dw, dh, outline, frac in d0.boxes:
            lo += off
            if outline:
                cl = np.array([la, la, la + dh, la + dh])
                cn = np.array([lo, lo + dw, lo + dw, lo])
                x, y, z = _rot(cl, cn, rx, ry)
                d.polygon(list(zip(c + x * R * sh, c - y * R * sh)), outline=col(float(z.mean()), base, 0.9))
            else:
                for k in range(3):
                    f = (k + 1) / 4
                    x, y, z = _rot(np.array([la + dh * f] * 2), np.array([lo, lo + dw * frac]), rx, ry)
                    d.line(list(zip(c + x * R * sh, c - y * R * sh)), fill=col(float(z.mean()), base, 0.8), width=1)
        la, lo, sh = d0.dots
        x, y, z = _rot(la, lo + off, rx, ry)
        for xx, yy, zz, s in zip(x, y, z, sh):
            d.point((c + xx * R * s, c - yy * R * s), fill=col(zz, hot, 0.9))
    for k, (tilt, segs, r) in enumerate(d0.arcs):  # große Ringe (drehen mit)
        for rep in range(6):
            for a0, a1 in segs:
                t = np.linspace(a0, a1, 14) + rep * 60.0 + i * 60.0 / FRAMES
                x, y, z = _rot(np.zeros_like(t), t, math.radians(tilt), 0.3 * k)
                for j in range(len(t) - 1):
                    d.line((c + x[j] * R * r, c - y[j] * R * r, c + x[j + 1] * R * r, c - y[j + 1] * R * r),
                           fill=col(z[j], hot, 1.1 if k < 2 else 0.7), width=3 if k < 2 else 2)
    for rr, w, f in ((0.16, 3, 1.2), (0.11, 2, 1.0), (0.07, 2, 1.3), (0.035, 2, 1.5)):
        d.ellipse((c - R * rr, c - R * rr * 0.92, c + R * rr, c + R * rr * 0.92), outline=col(1, hot, f), width=w)
    glow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(glow).ellipse((c - R * 0.09, c - R * 0.09, c + R * 0.09, c + R * 0.09), fill=200)
    glow = glow.filter(ImageFilter.GaussianBlur(R * 0.08))
    img = Image.composite(Image.new("RGB", (S, S), core), img, glow)
    # Leuchten (Bloom)
    a = np.asarray(img, np.float32)
    out = a.copy()
    for rad, kf in ((S * 0.004, 0.9), (S * 0.013, 0.7), (S * 0.035, 0.5), (S * 0.08, 0.35)):
        out += np.asarray(img.filter(ImageFilter.GaussianBlur(rad)), np.float32) * kf * 0.85
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def make_halo(size: int, color: str = "Gold") -> Image.Image:
    """Weiches Leuchten hinter der Kugel (wird zum "Atmen" heller und dunkler geschaltet)."""
    base = COLORS.get(color, COLORS["Gold"])[0]
    m = Image.new("L", (size, size), 0)
    r = size * 0.36
    ImageDraw.Draw(m).ellipse((size / 2 - r, size / 2 - r, size / 2 + r, size / 2 + r), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(size * 0.12))
    return Image.merge("RGB", [m.point(lambda v, k=k: int(v * k / 255 * 0.55)) for k in base])


class SphereFrames:
    """Lädt (oder rechnet) die Einzelbilder. ready() = wie viele schon da sind."""

    def __init__(self, folder: str):
        self.folder = folder
        self.color = None
        self.frames: list = []  # PIL-Bilder (BASE x BASE)
        self._lock = threading.Lock()
        self._job = 0

    def start(self, color: str):
        if color == self.color:
            return
        self.color = color if color in COLORS else "Gold"
        with self._lock:
            self.frames = []
        self._job += 1
        threading.Thread(target=self._work, args=(self._job, self.color), daemon=True).start()

    def ready(self) -> int:
        with self._lock:
            return len(self.frames)

    def get(self, i: int):
        with self._lock:
            return self.frames[i] if i < len(self.frames) else None

    def _work(self, job, color):
        sub = os.path.join(self.folder, f"{VERSION}_{color}")
        try:
            os.makedirs(sub, exist_ok=True)
        except Exception:
            sub = None
        for i in range(FRAMES):
            if job != self._job:
                return  # Farbe inzwischen geändert
            path = os.path.join(sub, f"{i:02d}.jpg") if sub else None
            img = None
            if path and os.path.exists(path):
                try:
                    img = Image.open(path).convert("RGB")
                    img.load()
                except Exception:
                    img = None
            if img is None:
                img = render_frame(i, color)
                if path:
                    try:
                        img.save(path, quality=92)
                    except Exception:
                        pass
            with self._lock:
                if job == self._job:
                    self.frames.append(img)
