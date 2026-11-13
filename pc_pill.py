"""
Grafik-Bausteine für Overlay und HUD (Pillow, glatte Kanten, keine Fenster-Abhängigkeit):

- make_pill:         abgerundetes Textfeld mit dünnem Farbverlauf-Rahmen (optional X-Knopf)
- make_orb:          kleiner animierter Kreis (Zustände: idle, listening, thinking, speaking, error)
- make_background:   dunkler HUD-Hintergrund mit leuchtenden Punkten
- make_reactor_base: Grundplatte des großen HUD-Kreises mit Ringen und Teilstrichen
- make_ring_button:  runder Knopf mit Leuchtring
- make_gauge:        Ring-Anzeige (z. B. CPU, RAM)
- make_card:         abgerundete, leicht durchscheinende Karte mit dünnem Rahmen

Die Ecken von Pill und Orb sind in KEY_RGB gezeichnet. Das Overlay-Fenster macht genau
diese Farbe durchsichtig, daher wirken die Formen wie frei schwebend.
"""

import colorsys
import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

KEY_RGB = (1, 1, 1)
FILL = (20, 20, 26)
BORDER_C1 = (0, 207, 255)  # Cyan wie im HUD
BORDER_C2 = (140, 238, 255)  # helleres Cyan
X_BG = (48, 48, 60)
X_FG = (215, 219, 228)
CYAN = (0, 200, 255)
CYAN_L = (120, 230, 255)
SS = 4  # Überabtastung für glatte Kanten
SSO = 3  # Überabtastung für den Orb (wird oft neu gezeichnet)

_RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS


HUE_SHIFT = 0.0  # Farbthema: Verschiebung des Farbtons in Grad (0 = Cyan)


def set_hue_shift(degrees: float):
    global HUE_SHIFT
    HUE_SHIFT = float(degrees) % 360


def shift_rgb(c):
    """Farbe (R, G, B) im aktuellen Farbthema."""
    if not HUE_SHIFT:
        return tuple(c)
    h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in c[:3]))
    r, g, b = colorsys.hsv_to_rgb((h + HUE_SHIFT / 360) % 1.0, s, v)
    return (round(r * 255), round(g * 255), round(b * 255)) + tuple(c[3:])


def shift_hex(hexstr: str) -> str:
    """Farbe '#rrggbb' im aktuellen Farbthema."""
    c = tuple(int(hexstr[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % shift_rgb(c)


def shift_image(img: Image.Image) -> Image.Image:
    """Bild im aktuellen Farbthema (graue und durchsichtige Anteile bleiben, wie sie sind)."""
    if not HUE_SHIFT:
        return img
    alpha = img.getchannel("A") if img.mode == "RGBA" else None
    hsv = img.convert("RGB").convert("HSV")
    h, s, v = hsv.split()
    delta = int(round(HUE_SHIFT / 360 * 256))
    h = h.point(lambda x: (x + delta) % 256)
    out = Image.merge("HSV", (h, s, v)).convert("RGB")
    if alpha is not None:
        out.putalpha(alpha)
    return out


def mix(a, b, f):
    return tuple(int(x + (y - x) * f) for x, y in zip(a, b))


def scale(c, s):
    return tuple(max(0, min(255, int(v * s))) for v in c)


# --- Textfeld ---------------------------------------------------------------
def make_pill(w: int, h: int, radius: int, border: int, x_center=(0, 0), x_radius: int = 0) -> Image.Image:
    """Abgerundetes Textfeld. x_radius = 0: ohne X-Knopf."""
    W, H = w * SS, h * SS
    r, b = radius * SS, border * SS

    outer = Image.new("L", (W, H), 0)
    ImageDraw.Draw(outer).rounded_rectangle((0, 0, W - 1, H - 1), radius=r, fill=255)
    inner = Image.new("L", (W, H), 0)
    ImageDraw.Draw(inner).rounded_rectangle(
        (b, b, W - 1 - b, H - 1 - b), radius=max(0, r - b), fill=255
    )
    ring = ImageChops.subtract(outer, inner)

    img = Image.new("RGB", (W, H), KEY_RGB)
    img.paste(Image.new("RGB", (W, H), FILL), (0, 0), outer)

    # Rahmen mit Farbverlauf: an den Seiten Blau, in der Mitte Violett
    t = np.linspace(0, 1, W)
    f = 1 - np.abs(2 * t - 1)
    c1, c2 = np.array(BORDER_C1, float), np.array(BORDER_C2, float)
    row = c1[None, :] * (1 - f[:, None]) + c2[None, :] * f[:, None]
    arr = np.ascontiguousarray(np.broadcast_to(row[None, :, :], (H, W, 3))).astype("uint8")
    img.paste(Image.fromarray(arr), (0, 0), ring)

    if x_radius > 0:  # Runder X-Knopf mit abgerundeten Strichen
        d = ImageDraw.Draw(img)
        cx, cy = x_center[0] * SS, x_center[1] * SS
        xr = x_radius * SS
        d.ellipse((cx - xr, cy - xr, cx + xr, cy + xr), fill=X_BG)
        arm = xr * 0.36
        lw = max(2, int(xr * 0.16))
        for sx, sy in ((1, 1), (1, -1)):
            p0 = (cx - arm * sx, cy - arm * sy)
            p1 = (cx + arm * sx, cy + arm * sy)
            d.line((*p0, *p1), fill=X_FG, width=lw)
            for px, py in (p0, p1):
                d.ellipse((px - lw / 2, py - lw / 2, px + lw / 2, py + lw / 2), fill=X_FG)

    return shift_image(img.resize((w, h), _RESAMPLE))


# --- Kleiner Kreis (Orb) ----------------------------------------------------
def make_orb(d: int, t: float, state: str = "idle") -> Image.Image:
    """Ein Bild des kleinen Kreises zum Zeitpunkt t (Sekunden) im gegebenen Zustand."""
    S = d * SSO
    img = Image.new("RGB", (S, S), KEY_RGB)
    dr = ImageDraw.Draw(img)
    c = S / 2
    m = 2 * SSO
    dr.ellipse((m, m, S - m, S - m), fill=FILL)
    pulse = 0.5 + 0.5 * math.sin(t * (2.0 if state in ("idle", "error") else 5.0))
    rw = max(2, int(d * 0.06 * SSO))
    bbox = (m, m, S - m, S - m)
    base = mix(BORDER_C1, BORDER_C2, 0.5)

    if state == "error":
        dr.arc(bbox, 0, 360, fill=scale((255, 110, 110), 0.7 + 0.3 * pulse), width=rw)
    elif state == "listening":
        dr.arc(bbox, 0, 360, fill=scale(BORDER_C1, 0.75 + 0.25 * pulse), width=rw)
        frac = (t * 0.9) % 1.0  # Welle, die nach außen läuft
        rr = c * (0.45 + 0.42 * frac)
        dr.ellipse((c - rr, c - rr, c + rr, c + rr), outline=scale(BORDER_C1, 0.55 * (1 - frac)), width=SSO)
    elif state == "thinking":
        dr.arc(bbox, 0, 360, fill=scale(base, 0.35), width=rw)
        a0 = (t * 280) % 360
        dr.arc(bbox, a0, a0 + 110, fill=BORDER_C2, width=rw)
        dr.arc(bbox, a0 + 180, a0 + 230, fill=BORDER_C1, width=rw)
    elif state == "speaking":
        dr.arc(bbox, 0, 360, fill=scale(BORDER_C2, 0.7 + 0.3 * pulse), width=rw)
    else:  # idle
        dr.arc(bbox, 0, 360, fill=scale(base, 0.4 + 0.2 * pulse), width=rw)

    if state == "speaking":  # kleine Schallbalken
        for i in range(5):
            x = c + (i - 2) * S * 0.095
            hh = S * (0.10 + 0.22 * (0.5 + 0.5 * math.sin(t * 9 + i * 1.4)))
            bw = S * 0.045
            dr.rounded_rectangle((x - bw / 2, c - hh / 2, x + bw / 2, c + hh / 2), radius=bw / 2, fill=CYAN_L)
    else:  # leuchtender Kern
        bright = 0.55 if state == "idle" else 1.0
        core_r = c * (0.17 + 0.05 * pulse + (0.04 if state == "listening" else 0))
        for i in range(10):
            f = i / 9
            rr = core_r * (1.9 - 1.4 * f)
            col = mix(FILL, scale(CYAN_L, bright), f ** 1.6)
            dr.ellipse((c - rr, c - rr, c + rr, c + rr), fill=col)
        rr = core_r * 0.35
        dr.ellipse((c - rr, c - rr, c + rr, c + rr), fill=scale((235, 252, 255), bright))

    out = img.resize((d, d), _RESAMPLE)
    return out if state == "error" else shift_image(out)  # Fehler bleiben rot


# --- HUD-Grafiken -------------------------------------------------------------
def make_background(W: int, H: int, seed: int = 7) -> Image.Image:
    rng = np.random.default_rng(seed)
    top, bot = np.array((2, 10, 20), float), np.array((3, 34, 56), float)
    y = np.linspace(0, 1, H)[:, None, None]
    grad = np.broadcast_to(top + (bot - top) * y, (H, W, 3)).astype("uint8")
    base = Image.fromarray(np.ascontiguousarray(grad))

    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for _ in range(int(W * H / 9000)):  # leuchtende Punkte
        x, yy = rng.uniform(0, W), rng.uniform(0, H)
        r = rng.uniform(1.5, 4.5)
        col = scale((0, 170, 255), rng.uniform(0.25, 0.9))
        gd.ellipse((x - r, yy - r, x + r, yy + r), fill=col)
    for _ in range(14):  # feine waagerechte Lichtlinien
        yy = rng.uniform(0.05, 0.95) * H
        x0 = rng.uniform(0, 0.6) * W
        gd.line((x0, yy, x0 + rng.uniform(0.15, 0.5) * W, yy), fill=(0, 120, 190), width=1)
    blurred = glow.filter(ImageFilter.GaussianBlur(4))
    out = ImageChops.add(base, blurred)
    return shift_image(ImageChops.add(out, glow.point(lambda v: int(v * 0.45))))


def _glow_composite(layers_under, rings, blur):
    glow = rings.filter(ImageFilter.GaussianBlur(blur))
    out = layers_under
    out = Image.alpha_composite(out, glow)
    return Image.alpha_composite(out, rings)


def make_reactor_base(size: int) -> Image.Image:
    """Grundplatte des großen Kreises: dunkle Scheibe, feine Ringe, Teilstriche (RGBA)."""
    ss = 2
    N = size * ss
    c = N / 2
    R = c * 0.97
    disc = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse((c - R, c - R, c + R, c + R), fill=(3, 16, 28, 215))
    rings = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(rings)
    for frac, w, a in ((0.97, 3, 210), (0.90, 1, 120), (0.78, 2, 150), (0.62, 1, 110), (0.46, 2, 130), (0.30, 1, 100)):
        r = R * frac / 0.97
        d.ellipse((c - r, c - r, c + r, c + r), outline=(0, 190, 240, a), width=w * ss)
    for deg in range(0, 360, 3):
        long_tick = deg % 15 == 0
        r0 = R * (0.835 if long_tick else 0.865)
        r1 = R * 0.905
        a = math.radians(deg)
        d.line(
            (c + r0 * math.cos(a), c + r0 * math.sin(a), c + r1 * math.cos(a), c + r1 * math.sin(a)),
            fill=(0, 205, 255, 175 if long_tick else 95),
            width=ss * (2 if long_tick else 1),
        )
    out = _glow_composite(disc, rings, 4 * ss / 2)
    return shift_image(out.resize((size, size), _RESAMPLE))


def make_ring_button(d: int) -> Image.Image:
    """Runder Knopf mit Leuchtring (RGBA)."""
    ss = 3
    N = d * ss
    pad = 6 * ss
    base = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(base).ellipse((pad, pad, N - pad, N - pad), fill=(2, 22, 36, 235))
    rings = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rings)
    rd.ellipse((pad, pad, N - pad, N - pad), outline=(0, 205, 255, 255), width=int(d * 0.045 * ss))
    inset = pad + d * 0.09 * ss
    rd.ellipse((inset, inset, N - inset, N - inset), outline=(0, 120, 170, 140), width=ss)
    out = _glow_composite(base, rings, 3 * ss)
    return shift_image(out.resize((d, d), _RESAMPLE))


def make_gauge(d: int, frac: float, color=(0, 215, 255), thin_inner: bool = False) -> Image.Image:
    """Ring-Anzeige, die zu frac (0 bis 1) gefüllt ist (RGBA)."""
    frac = max(0.0, min(1.0, frac))
    ss = 3
    N = d * ss
    pad = 7 * ss
    w = max(3, int(d * 0.085 * ss))
    base = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(base).ellipse((pad, pad, N - pad, N - pad), fill=(2, 18, 30, 170))
    rings = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rings)
    bbox = (pad, pad, N - pad, N - pad)
    rd.arc(bbox, 0, 360, fill=(0, 80, 120, 150), width=w)
    if frac > 0.003:
        rd.arc(bbox, -90, -90 + 360 * frac, fill=color + (255,), width=w)
    if thin_inner:
        inset = pad + w + 5 * ss
        rd.ellipse((inset, inset, N - inset, N - inset), outline=(0, 150, 200, 150), width=ss)
    out = _glow_composite(base, rings, 2.5 * ss)
    return shift_image(out.resize((d, d), _RESAMPLE))


def make_app_icon(d: int = 256) -> Image.Image:
    """Programm-Symbol: Cyan-Ring mit leuchtendem Kern auf dunklem Grund (RGBA)."""
    ss = 2
    N = d * ss
    base = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    bd = ImageDraw.Draw(base)
    pad = int(N * 0.04)
    bd.ellipse((pad, pad, N - pad, N - pad), fill=(3, 16, 28, 255))
    rings = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rings)
    rd.ellipse((pad, pad, N - pad, N - pad), outline=(0, 207, 255, 255), width=int(N * 0.07))
    inset = int(N * 0.22)
    rd.arc((inset, inset, N - inset, N - inset), 200, 340, fill=(140, 238, 255, 255), width=int(N * 0.045))
    rd.arc((inset, inset, N - inset, N - inset), 20, 160, fill=(0, 160, 210, 255), width=int(N * 0.045))
    c = N / 2
    for i in range(10):
        f = i / 9
        r = N * 0.17 * (1.8 - 1.3 * f)
        col = mix((3, 16, 28), (120, 230, 255), f ** 1.6) + (255,)
        rd.ellipse((c - r, c - r, c + r, c + r), fill=col)
    out = _glow_composite(base, rings, N * 0.012)
    return out.resize((d, d), _RESAMPLE)


def make_card(w: int, h: int, radius: int, border: int = 1) -> Image.Image:
    """Abgerundete Karte für Bereiche im HUD: dunkel, leicht durchscheinend, dünner Rahmen (RGBA)."""
    ss = 3
    W, H = w * ss, h * ss
    r, b = radius * ss, max(1, border) * ss
    outer = Image.new("L", (W, H), 0)
    ImageDraw.Draw(outer).rounded_rectangle((0, 0, W - 1, H - 1), radius=r, fill=255)
    inner = Image.new("L", (W, H), 0)
    ImageDraw.Draw(inner).rounded_rectangle((b, b, W - 1 - b, H - 1 - b), radius=max(0, r - b), fill=255)
    ring = ImageChops.subtract(outer, inner)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (W, H), (3, 20, 32, 175)), (0, 0), inner)
    img.paste(Image.new("RGBA", (W, H), (11, 110, 140, 235)), (0, 0), ring)
    return shift_image(img.resize((w, h), _RESAMPLE))
