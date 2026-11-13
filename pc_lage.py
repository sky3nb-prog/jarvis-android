"""
Globus für den Lage-Modus im HUD – eine Kugel, zwei Ansichten:

  GLOBUS   = Hologramm: dunkle Kugel, goldene Küstenlinien, Land aus leuchtenden Punkten, Gradnetz, Atmosphäre
  SATELLIT = dieselbe Kugel mit echtem Satellitenbild (Blue Marble der NASA), blau schimmernde Atmosphäre

Beide werden pro Bildpunkt mit numpy gerechnet (kein Zeichnen von tausenden Linien) – schnell genug für flüssige
Flüge. Die Punkte sind fest auf der Erde verankert, deshalb flimmert beim Drehen nichts. zoom > 1 = näher heran.

Daten lädt Jarvis einmal herunter und speichert sie im Ordner "globus".
"""

import collections
import math
import os
import threading
import time
import urllib.request

import numpy as np
from PIL import Image, ImageFilter

WATER_URLS = ["https://unpkg.com/three-globe/example/img/earth-water.png",
              "https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-water.png"]
SAT_URLS = ["https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg",
            "https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-blue-marble.jpg"]
_land = {"mask": None, "coast": None, "loading": False}
_sat = {"tex": None, "loading": False}
_night = {"tex": None, "loading": False}
NIGHT_URLS = ["https://unpkg.com/three-globe/example/img/earth-night.jpg",
              "https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-night.jpg"]
SUN = True  # Tag und Nacht wie gerade in echt
_geo_cache: dict = {}
_halo_cache: dict = {}

# Große Städte für Beschriftungen beim Heranzoomen (Name, Breite, Länge, Rang: 1 = immer, 3 = erst ganz nah)
CITIES = [
    ("Berlin", 52.52, 13.40, 1), ("London", 51.51, -0.13, 1), ("Paris", 48.86, 2.35, 1), ("Moskau", 55.76, 37.62, 1),
    ("New York", 40.71, -74.01, 1), ("Washington", 38.90, -77.04, 2), ("Los Angeles", 34.05, -118.24, 1),
    ("Peking", 39.90, 116.40, 1), ("Tokio", 35.68, 139.69, 1), ("Seoul", 37.57, 126.98, 1), ("Neu-Delhi", 28.61, 77.21, 1),
    ("Kairo", 30.04, 31.24, 1), ("Istanbul", 41.01, 28.98, 1), ("Kiew", 50.45, 30.52, 1), ("Jerusalem", 31.77, 35.21, 2),
    ("Teheran", 35.69, 51.39, 2), ("Dubai", 25.20, 55.27, 2), ("Sydney", -33.87, 151.21, 1), ("São Paulo", -23.55, -46.63, 1),
    ("Buenos Aires", -34.60, -58.38, 2), ("Mexiko-Stadt", 19.43, -99.13, 1), ("Lagos", 6.52, 3.38, 2),
    ("Johannesburg", -26.20, 28.05, 2), ("Nairobi", -1.29, 36.82, 2), ("Mumbai", 19.08, 72.88, 2), ("Singapur", 1.35, 103.82, 2),
    ("Shanghai", 31.23, 121.47, 2), ("Hongkong", 22.32, 114.17, 2), ("Bangkok", 13.76, 100.50, 2), ("Jakarta", -6.21, 106.85, 2),
    ("Toronto", 43.65, -79.38, 2), ("Chicago", 41.88, -87.63, 2), ("Madrid", 40.42, -3.70, 2), ("Rom", 41.90, 12.50, 2),
    ("Wien", 48.21, 16.37, 2), ("Warschau", 52.23, 21.01, 2), ("Stockholm", 59.33, 18.07, 2), ("Athen", 37.98, 23.73, 3),
    ("Brüssel", 50.85, 4.35, 3), ("Amsterdam", 52.37, 4.90, 3), ("Zürich", 47.38, 8.54, 3), ("München", 48.14, 11.58, 2),
    ("Hamburg", 53.55, 9.99, 3), ("Frankfurt", 50.11, 8.68, 3), ("Köln", 50.94, 6.96, 3), ("Stuttgart", 48.78, 9.18, 2),
    ("Taipeh", 25.03, 121.57, 3), ("Pjöngjang", 39.04, 125.76, 3), ("Riad", 24.71, 46.68, 3), ("Bagdad", 33.31, 44.36, 3),
    ("Damaskus", 33.51, 36.28, 3), ("Beirut", 33.89, 35.50, 3), ("Gaza", 31.50, 34.47, 3), ("Kapstadt", -33.92, 18.42, 3),
    ("Lima", -12.05, -77.04, 3), ("Bogotá", 4.71, -74.07, 3), ("Santiago", -33.45, -70.67, 3), ("Anchorage", 61.22, -149.90, 3),
    ("Reykjavík", 64.15, -21.94, 3), ("Honolulu", 21.31, -157.86, 3),
]


def _folder() -> str:
    try:
        import pc_apps

        base = pc_apps.base_dir()
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "globus")
    os.makedirs(path, exist_ok=True)
    return path


def _download(path, urls, min_size=10_000):
    if os.path.exists(path) and os.path.getsize(path) > min_size:
        return True
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Jarvis"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) > min_size:
                with open(path, "wb") as f:
                    f.write(data)
                return True
        except Exception as e:
            print(f"Globus-Daten von {url} nicht geladen: {e}")
    return False


def land_mask():
    """Landmaske (bool, 1024 x 2048) oder None, solange sie noch lädt. Lädt nebenbei die Küstenlinien."""
    if _land["mask"] is not None or _land["loading"]:
        return _land["mask"]
    _land["loading"] = True

    def run():
        path = os.path.join(_folder(), "earth-water.png")
        try:
            _download(path, WATER_URLS)
            im = Image.open(path).convert("L").resize((2048, 1024), Image.BILINEAR)
            m = np.asarray(im) > 127
            m = m if m.mean() < 0.5 else ~m
            # Küste = Land, das an Wasser grenzt (1 Pixel breit)
            er = m.copy()
            er[1:] &= m[:-1]
            er[:-1] &= m[1:]
            er[:, 1:] &= m[:, :-1]
            er[:, :-1] &= m[:, 1:]
            coast = (m & ~er).astype(np.float32)
            coast = np.asarray(Image.fromarray((coast * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6)),
                               np.float32) / 255.0
            _land["coast"] = np.clip(coast * 2.2, 0, 1)
            _land["mask"] = m
        except Exception as e:
            print(f"Landkarte nicht verfügbar: {e}")
        finally:
            _land["loading"] = False
    threading.Thread(target=run, daemon=True).start()
    return None


def sat_texture():
    """Satellitenbild der Erde (4096 x 2048, RGB) oder None, solange es lädt."""
    if _sat["tex"] is not None or _sat["loading"]:
        return _sat["tex"]
    _sat["loading"] = True

    def run():
        path = os.path.join(_folder(), "earth-blue-marble.jpg")
        try:
            if _download(path, SAT_URLS, 200_000):
                im = Image.open(path).convert("RGB")
                if im.size != (4096, 2048):
                    im = im.resize((4096, 2048), Image.BICUBIC)
                a = np.asarray(im, np.float32)
                # etwas kräftiger und kontrastreicher (Blue Marble ist recht blass)
                a = np.clip((a - 8) * 1.18, 0, 255)
                _sat["tex"] = a.astype(np.uint8)
        except Exception as e:
            print(f"Satellitenbild nicht verfügbar: {e}")
        finally:
            _sat["loading"] = False
    threading.Thread(target=run, daemon=True).start()
    return None


def sat_ready() -> bool:
    return _sat["tex"] is not None


def night_texture():
    """Stadtlichter bei Nacht (2048 x 1024, Helligkeit 0..1) oder None, solange es lädt."""
    if _night["tex"] is not None or _night["loading"]:
        return _night["tex"]
    _night["loading"] = True

    def run():
        path = os.path.join(_folder(), "earth-night.jpg")
        try:
            if _download(path, NIGHT_URLS, 100_000):
                im = Image.open(path).convert("L").resize((2048, 1024), Image.BILINEAR)
                a = np.asarray(im, np.float32) / 255.0
                _night["tex"] = np.clip((a - 0.06) * 1.6, 0, 1) ** 1.2
        except Exception as e:
            print(f"Nachtbild nicht verfügbar: {e}")
        finally:
            _night["loading"] = False
    threading.Thread(target=run, daemon=True).start()
    return None


def sun_position(t: float = None):
    """Breite und Länge, an der die Sonne gerade senkrecht steht (genau genug für die Tag-Nacht-Grenze)."""
    t = time.time() if t is None else t
    g = time.gmtime(t)
    doy = g.tm_yday + (g.tm_hour + g.tm_min / 60.0) / 24.0
    decl = -23.44 * math.cos(2 * math.pi / 365.0 * (doy + 10))
    b = 2 * math.pi * (doy - 81) / 364.0
    eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)  # Zeitgleichung in Minuten
    utc_h = g.tm_hour + g.tm_min / 60.0 + g.tm_sec / 3600.0
    lon = -15.0 * (utc_h - 12.0 + eot / 60.0)
    return decl, (lon + 180.0) % 360.0 - 180.0


def _daylight(lat, lon):
    """0 = Nacht, 1 = Tag, weicher Übergang in der Dämmerung."""
    d, ls = sun_position()
    la, dl = np.radians(lat), np.radians(lon - ls)
    cz = np.sin(la) * math.sin(math.radians(d)) + np.cos(la) * math.cos(math.radians(d)) * np.cos(dl)
    return np.clip((cz + 0.10) / 0.22, 0, 1)


# --- Kacheln für nahes Heranzoomen (bis Straßenebene) -----------------------------------------------
# Gleiche Quellen und gleicher Ordner wie die große Karte (pc_map), dadurch teilen sich beide den Zwischenspeicher.
TILE_URLS = {
    ("Satellit", "base"): "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    ("Satellit", "labels"): "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    ("Dunkel", "base"): "https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png",
    ("Dunkel", "labels"): "https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}.png",
}
MAX_LEVEL = 18
ON_TILE = None  # vom HUD gesetzt: wird aufgerufen, wenn neue Kacheln da sind (dann neu zeichnen)


class _Tiles:
    def __init__(self):
        self.mem = collections.OrderedDict()
        self.lock = threading.Lock()
        self.wanted = collections.OrderedDict()  # neueste Wünsche zuerst abarbeiten
        self.pending = set()
        self.failed = {}
        self.ev = threading.Event()
        self.started = False

    def get(self, key):
        """key = (Quelle, Ebene, z, x, y) -> numpy-Bild (uint8) oder None (wird dann im Hintergrund geladen)."""
        with self.lock:
            a = self.mem.get(key)
            if a is not None:
                self.mem.move_to_end(key)
                return a
            if key in self.pending or time.time() - self.failed.get(key, 0) < 60:
                return None
            self.wanted[key] = True
            self.wanted.move_to_end(key, last=False)
            while len(self.wanted) > 80:
                self.wanted.popitem(last=True)  # älteste (nicht mehr sichtbare) Wünsche verwerfen
        if not self.started:
            self.started = True
            for i in range(6):
                threading.Thread(target=self._worker, daemon=True, name=f"jarvis-kachel{i}").start()
        self.ev.set()
        return None

    def peek(self, key):
        with self.lock:
            return self.mem.get(key)

    def _path(self, key):
        src, layer, z, x, y = key
        return os.path.join(_folder(), "kacheln", f"{src}_{layer}", str(z), str(x), f"{y}.img")

    def _worker(self):
        while True:
            self.ev.wait(1.0)
            with self.lock:
                if not self.wanted:
                    self.ev.clear()
                    continue
                key, _ = self.wanted.popitem(last=False)
                self.pending.add(key)
            src, layer, z, x, y = key
            arr = None
            try:
                path = self._path(key)
                if not (os.path.exists(path) and os.path.getsize(path) > 100):
                    url = TILE_URLS[(src, layer)].format(z=z, x=x, y=y, s="abcd"[(x + y) % 4])
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Jarvis-Assistent"})
                    with urllib.request.urlopen(req, timeout=15) as r:
                        data = r.read()
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "wb") as f:
                        f.write(data)
                im = Image.open(path)
                im.load()
                im = im.convert("RGBA" if layer == "labels" else "RGB")
                if im.size != (256, 256):
                    im = im.resize((256, 256), Image.BILINEAR)
                arr = np.asarray(im, np.uint8)
            except Exception:
                arr = None
            with self.lock:
                self.pending.discard(key)
                if arr is None:
                    self.failed[key] = time.time()
                else:
                    self.mem[key] = arr
                    while len(self.mem) > 600:
                        self.mem.popitem(last=False)
            if arr is not None and ON_TILE:
                try:
                    ON_TILE()
                except Exception:
                    pass


TILES = _Tiles()


def level_for(R: float, lat0: float) -> int:
    """Welche Kachelstufe ist bei diesem Kugelradius (Bildpunkte) scharf genug?"""
    need = 2 * math.pi * R * max(0.05, math.cos(math.radians(lat0))) / 256.0
    return int(max(0, min(MAX_LEVEL, math.ceil(math.log2(max(1.0, need))))))


def zoom_for_level(level: float, size: int, lat0: float) -> float:
    """Umgekehrt: welcher Zoom zeigt etwa Kachelstufe `level` (12 = Stadt, 15 = Straßen)."""
    R = 256.0 * 2 ** level / (2 * math.pi * max(0.05, math.cos(math.radians(lat0))))
    return max(1.0, R / (size * 0.42))


def _tile_sample(src, layer, lat, lon, L, hq=False):
    """Farbe aus Kacheln der Stufe L (fehlt eine Kachel, wird eine gröbere genommen; sonst NaN-Maske)."""
    n = 2 ** L
    x = (lon + 180.0) / 360.0 * n * 256.0
    la = np.radians(np.clip(lat, -85.05, 85.05))
    y = (1.0 - np.log(np.tan(la) + 1.0 / np.cos(la)) / math.pi) / 2.0 * n * 256.0
    tx = np.clip((x // 256).astype(np.int64), 0, n - 1)
    ty = np.clip((y // 256).astype(np.int64), 0, n - 1)
    keys = tx * n + ty
    uniq, inv = np.unique(keys, return_inverse=True)
    ch = 4 if layer == "labels" else 3
    out = np.zeros((len(lat), ch), np.float32)
    ok = np.zeros(len(lat), bool)
    if len(uniq) > 120:  # viel zu viele Kacheln (sollte nicht vorkommen) -> lieber nichts
        return out, ok
    order = np.argsort(inv, kind="stable")
    bounds = np.searchsorted(inv[order], np.arange(len(uniq) + 1))
    for i, k in enumerate(uniq):
        sel = order[bounds[i]:bounds[i + 1]]
        if not len(sel):
            continue
        kx, ky = int(k // n), int(k % n)
        arr, lvl = TILES.get((src, layer, L, kx, ky)), L
        if arr is None:  # gröbere Kachel aus dem Speicher als Platzhalter (nur ansehen, nicht laden)
            for d in range(1, 6):
                if L - d < 0:
                    break
                arr = TILES.peek((src, layer, L - d, kx >> d, ky >> d))
                if arr is not None:
                    lvl = L - d
                    break
        if arr is None:
            continue
        f = 2 ** (L - lvl)
        px = (x[sel] / f) - (kx >> (L - lvl)) * 256.0
        py = (y[sel] / f) - (ky >> (L - lvl)) * 256.0
        xi = np.clip(px.astype(np.int32), 0, 255)
        yi = np.clip(py.astype(np.int32), 0, 255)
        out[sel] = arr[yi, xi]
        ok[sel] = True
    return out, ok


def project(lat, lon, lat0, lon0, cx, cy, R):
    """Breite/Länge -> Bildschirm (x, y, sichtbar, Tiefe z)."""
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float) - lon0)
    x = np.cos(la) * np.sin(lo)
    y = np.sin(la)
    z = np.cos(la) * np.cos(lo)
    c, s = math.cos(math.radians(lat0)), math.sin(math.radians(lat0))
    Y = y * c - z * s
    Z = y * s + z * c
    return cx + x * R, cy - Y * R, Z > 0.02, Z


def _geometry(S, R):
    """Was sich beim Drehen nicht ändert: welche Bildpunkte auf der Kugel liegen und deren Lage auf der Kugel."""
    key = (S, int(R))
    g = _geo_cache.get(key)
    if g is None:
        c = S / 2
        ys, xs = np.mgrid[0:S, 0:S].astype(np.float64 if R > S * 20 else np.float32)
        X = (xs + 0.5 - c) / R
        Y = (c - ys - 0.5) / R
        rr = X * X + Y * Y
        ins = rr < 1.0
        idx = np.flatnonzero(ins)
        Xi, Yi = X.ravel()[idx], Y.ravel()[idx]
        Zi = np.sqrt(np.maximum(0.0, 1 - rr.ravel()[idx]))
        # weiches Leuchten um den Rand (Atmosphäre), hängt nur von der Größe ab
        r = np.sqrt(rr)
        out = np.clip(r - 1.0, 0, None) * R / max(1.0, S * 0.018)
        halo = np.where(ins, 0.0, np.exp(-out) * 0.85 + np.exp(-out * 0.25) * 0.18).astype(np.float32)
        # Rand (Edge) zwischen 0.93 und 1.0
        edge = np.zeros(S * S, np.float32)
        edge[idx] = np.clip((np.sqrt(rr.ravel()[idx]) - 0.80) / 0.20, 0, 1) ** 3
        aa = np.clip((1.0 - np.sqrt(rr.ravel()[idx])) * R + 0.5, 0, 1).astype(np.float32)  # weicher Kugelrand
        g = dict(idx=idx, X=Xi, Y=Yi, Z=Zi, aa=aa[:, None], halo=halo.reshape(S, S), edge=edge.reshape(S, S))
        if len(_geo_cache) > 12:
            _geo_cache.clear()
        _geo_cache[key] = g
    return g


def _latlon(g, lat0, lon0):
    cl, sl = math.cos(math.radians(lat0)), math.sin(math.radians(lat0))
    wy = g["Y"] * cl + g["Z"] * sl
    wz = -g["Y"] * sl + g["Z"] * cl
    lat = np.degrees(np.arcsin(np.clip(wy, -1, 1)))
    lon = (np.degrees(np.arctan2(g["X"], wz)) + lon0 + 180.0) % 360.0 - 180.0
    return lat, lon


def _sample(tex, lat, lon, bilinear):
    H, W = tex.shape[:2]
    u = (lon + 180.0) / 360.0 * W - 0.5
    v = (90.0 - lat) / 180.0 * H - 0.5
    if not bilinear:
        return tex[np.clip(v.astype(np.int32), 0, H - 1), np.clip(u.astype(np.int32), 0, W - 1) % W].astype(np.float32)
    u0 = np.floor(u).astype(np.int32)
    v0 = np.floor(v).astype(np.int32)
    fu = (u - u0)[:, None] if tex.ndim == 3 else (u - u0)
    fv = (v - v0)[:, None] if tex.ndim == 3 else (v - v0)
    u0 %= W
    u1 = (u0 + 1) % W
    v0c = np.clip(v0, 0, H - 1)
    v1c = np.clip(v0 + 1, 0, H - 1)
    a = tex[v0c, u0].astype(np.float32)
    b = tex[v0c, u1].astype(np.float32)
    c = tex[v1c, u0].astype(np.float32)
    d = tex[v1c, u1].astype(np.float32)
    return (a * (1 - fu) + b * fu) * (1 - fv) + (c * (1 - fu) + d * fu) * fv


def _grid(lat, lon, px_per_deg, step=15.0):
    """Gradnetz als weiche Linien (Pixelbreite ~1), direkt pro Bildpunkt."""
    dl = np.abs(((lat + step / 2) % step) - step / 2) * px_per_deg
    coslat = np.maximum(0.05, np.cos(np.radians(lat)))
    dn = np.abs(((lon + step / 2) % step) - step / 2) * px_per_deg * coslat
    return np.clip(1.0 - np.minimum(dl, dn), 0, 1)


def render(size: int, lat0: float, lon0: float, color=(255, 166, 36), hot=(255, 214, 120),
           glow=(255, 110, 20), quality: bool = True, sea=(40, 150, 235), zoom: float = 1.0,
           style: str = "globus", scale: float = 0.5) -> Image.Image:
    """Der Globus als Bild (RGB auf Schwarz). Radius = 0.42 * size * zoom. style: "globus" oder "satellit".
    quality=False: schnelle Vorschau in kleinerer Auflösung (scale), dann hochgerechnet."""
    S = int(size)
    R = S * 0.42 * max(1.0, zoom)
    if math.log2(max(1.0, 2 * math.pi * R * max(0.05, math.cos(math.radians(lat0))) / 256.0)) >= FLAT_FROM:
        return render_flat(S, lat0, lon0, color, zoom, style)  # flach: immer volle Schärfe (ist schnell genug)
    if not quality:
        small = render_core(max(120, int(S * scale)), lat0, lon0, color, hot, glow, sea, zoom, style, False)
        return small.resize((S, S), Image.BILINEAR)
    img = render_core(S, lat0, lon0, color, hot, glow, sea, zoom, style, True)
    # leichtes Leuchten (Bloom)
    a = np.asarray(img, np.float32)
    b = a + np.asarray(img.filter(ImageFilter.GaussianBlur(S * 0.008)), np.float32) * (0.40 if style == "globus" else 0.25)
    return Image.fromarray(np.clip(b, 0, 255).astype(np.uint8))


FLAT_FROM = 8.3  # ab dieser Kachelstufe ist die Kugel praktisch flach -> direkt aus Kacheln zusammensetzen


def _tile_img(src, layer, z, x, y, want=True):
    """Kachel als PIL-Bild; fehlt sie, ein vergrößerter Ausschnitt einer gröberen (oder None)."""
    a = TILES.get((src, layer, z, x, y)) if want else TILES.peek((src, layer, z, x, y))
    if a is not None:
        return Image.fromarray(a)
    for d in range(1, 7):
        if z - d < 0:
            break
        p = TILES.peek((src, layer, z - d, x >> d, y >> d))
        if p is not None:
            k = 256 >> d
            ox, oy = (x - ((x >> d) << d)) * k, (y - ((y >> d) << d)) * k
            return Image.fromarray(p).crop((ox, oy, ox + k, oy + k)).resize((256, 256), Image.BILINEAR)
    return None


def render_flat(S, lat0, lon0, color, zoom, style):
    """Ganz nah dran: Kartenkacheln direkt zusammensetzen (Mercator) – scharf und sehr schnell."""
    R = S * 0.42 * zoom
    Lf = math.log2(max(1.0, 2 * math.pi * R * max(0.05, math.cos(math.radians(lat0))) / 256.0))
    Li = int(min(MAX_LEVEL, math.floor(Lf)))
    sc = 2 ** (Lf - Li)  # Vergrößerung der Kacheln
    n = 2 ** Li
    la = math.radians(max(-85.0, min(85.0, lat0)))
    cxm = (lon0 + 180.0) / 360.0 * n * 256.0
    cym = (1.0 - math.log(math.tan(la) + 1.0 / math.cos(la)) / math.pi) / 2.0 * n * 256.0
    half = S / 2.0 / sc
    x0, y0, x1, y1 = cxm - half, cym - half, cxm + half, cym + half
    tx0, ty0, tx1, ty1 = int(x0 // 256), int(max(0, y0 // 256)), int(x1 // 256), int(min(n - 1, y1 // 256))
    src = "Satellit" if style == "satellit" else "Dunkel"
    W, H = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    base = Image.new("RGB", (W, H), (2, 8, 14))
    lab = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            t = _tile_img(src, "base", Li, tx % n, ty)
            if t is not None:
                base.paste(t, ((tx - tx0) * 256, (ty - ty0) * 256))
            if Li >= 6:
                tl = _tile_img(src, "labels", Li, tx % n, ty)
                if tl is not None:
                    lab.paste(tl.convert("RGBA"), ((tx - tx0) * 256, (ty - ty0) * 256))
    box = (x0 - tx0 * 256, y0 - ty0 * 256, x1 - tx0 * 256, y1 - ty0 * 256)
    img = base.resize((S, S), Image.BILINEAR, box=box)
    if style != "satellit":  # dunkle Karte in Gold einfärben (Straßen leuchten)
        a = np.asarray(img, np.float32).mean(axis=2, keepdims=True)
        street = np.clip((a - 14.0) * 3.2, 0, 255) / 255.0
        img = Image.fromarray(np.clip(np.array((3, 10, 18), np.float32) + np.array(color, np.float32) * street * 1.05,
                                      0, 255).astype(np.uint8))
    else:
        img = Image.fromarray(np.clip(np.asarray(img, np.float32) * 1.08, 0, 255).astype(np.uint8))
    if Li >= 6:
        lb = lab.resize((S, S), Image.BILINEAR, box=box)
        if style != "satellit":
            r, g, b, al = lb.split()
            lb = Image.merge("RGBA", (r.point(lambda v: 255), g.point(lambda v: 236), b.point(lambda v: 200), al))
        img = Image.alpha_composite(img.convert("RGBA"), lb).convert("RGB")
    out = np.asarray(img, np.float32) * _vignette(S)[:, :, None]
    return Image.fromarray(out.astype(np.uint8))


def render_core(S, lat0, lon0, color, hot, glow, sea, zoom, style, hq):
    R = S * 0.42 * max(1.0, zoom)
    if level_for(R, lat0) >= FLAT_FROM - 0.01 and math.log2(max(1.0, 2 * math.pi * R * max(0.05, math.cos(
            math.radians(lat0))) / 256.0)) >= FLAT_FROM:
        return render_flat(S, lat0, lon0, color, zoom, style)
    g = _geometry(S, R)
    L = level_for(R, lat0)
    out = np.zeros((S * S, 3), np.float32)
    idx, Z = g["idx"], g["Z"]
    if len(idx):
        lat, lon = _latlon(g, lat0, lon0)
        px_deg = R * math.pi / 180.0 * np.maximum(0.15, Z)  # Bildpunkte pro Grad (mit Verkürzung zum Rand)
        shade = (0.30 + 0.70 * Z)[:, None]
        limb = ((1.0 - Z) ** 3)[:, None]
        tex = sat_texture() if style == "satellit" else None
        if tex is not None:
            col = _sample(tex, lat, lon, hq)
            if L >= 5:  # nah dran: echte Satellitenkacheln (bis Straßenebene)
                tc, ok = _tile_sample("Satellit", "base", lat, lon, min(L, 18))
                col[ok] = tc[ok]
            light = 0.45 + 0.55 * np.sqrt(Z)[:, None]
            col = col * light
            if SUN and zoom < 3.0:  # Nacht nur auf der ganzen Kugel – nah dran soll man alles klar erkennen
                day = 1.0 - (1.0 - _daylight(lat, lon)[:, None]) * min(1.0, (3.0 - zoom) / 1.5)
                nt = night_texture()
                lights = _sample(nt, lat, lon, False)[:, None] if nt is not None else 0.0
                col = col * (0.10 + 0.90 * day) + np.array((255, 196, 110), np.float32) * lights * (1 - day) * 0.95
            col = col * (1 - limb * 0.75) + np.array((70, 150, 255), np.float32) * limb * 1.05  # Atmosphäre am Rand
            gr = _grid(lat, lon, px_deg, 30.0)[:, None] * (0.10 if zoom < 2.5 else 0.0)
            col += np.array(color, np.float32) * gr
            if L >= 6:  # Grenzen und Ortsnamen
                lc, ok = _tile_sample("Satellit", "labels", lat, lon, min(L, 18))
                al = (lc[:, 3:4] / 255.0) * ok[:, None]
                col = col * (1 - al) + lc[:, :3] * al
            out[idx] = col * g["aa"]
        else:
            mask, coast = _land["mask"], _land["coast"]
            Hm, Wm = (1024, 2048)
            vi = np.clip(((90.0 - lat) / 180.0 * Hm).astype(np.int32), 0, Hm - 1)
            ui = np.clip(((lon + 180.0) / 360.0 * Wm).astype(np.int32), 0, Wm - 1)
            # Meer: dunkles Blau mit leichtem Verlauf, darüber feines blaues Raster
            ocean = np.array((2, 9, 18), np.float32) + np.array(sea, np.float32) * 0.07 * Z[:, None]
            col = ocean * shade
            if mask is not None:
                land = mask[vi, ui]
                cst = coast[vi, ui] if coast is not None else np.zeros_like(Z)
            else:
                land = np.zeros_like(Z, bool)
                cst = np.zeros_like(Z)
            # Punkte fest auf der Erde: Abstand in Grad, mit dem Zoom feiner (in Zweierstufen, damit nichts springt)
            sp = 0.85 / (2 ** int(math.log2(max(1.0, zoom))))
            a = lat / sp
            b = lon * np.maximum(0.2, np.cos(np.radians(lat))) / sp
            fa = a - np.floor(a) - 0.5
            fb = b - np.floor(b) - 0.5
            dot_r = 0.24
            d = np.sqrt(fa * fa + fb * fb)
            pxs = sp * px_deg  # Abstand zweier Punkte in Bildpunkten
            soft = np.clip((dot_r - d) * pxs * 1.6 + 0.5, 0, 1)  # weicher Punktrand gegen Treppen
            dots = soft * land
            hotv = np.array(hot, np.float32)
            colv = np.array(color, np.float32)
            col = col + (colv * 0.07 * land[:, None]) * shade            # Land leicht eingefärbt
            col = col + (colv * 0.55 + hotv * 0.30)[None, :] * (dots * 0.95)[:, None] * shade   # leuchtende Landpunkte
            sea_dots = soft * (~land) * 0.12
            col = col + np.array(sea, np.float32)[None, :] * sea_dots[:, None] * shade
            col = col + np.array((255, 205, 120), np.float32)[None, :] * (cst * 0.95)[:, None] * (0.45 + 0.55 * Z)[:, None]
            gr = _grid(lat, lon, px_deg, 15.0 if zoom < 3 else 5.0)
            col = col + colv * (gr * 0.30)[:, None] * shade
            if SUN and zoom < 3.0:  # Nachtseite dunkler, Städte leuchten golden
                day = 1.0 - (1.0 - _daylight(lat, lon)[:, None]) * min(1.0, (3.0 - zoom) / 1.5)
                nt = night_texture()
                col = col * (0.22 + 0.78 * day)
                if nt is not None:
                    col = col + hotv[None, :] * _sample(nt, lat, lon, False)[:, None] * (1 - day) * 1.2
            col = col + np.array(glow, np.float32) * limb * 0.55  # glühender Rand
            if L >= 6:  # nah dran: Straßenkarte in Gold (dunkle Karte, eingefärbt) mit Ortsnamen
                tc, ok = _tile_sample("Dunkel", "base", lat, lon, min(L, 18))
                if ok.any():
                    lum = tc.mean(axis=1, keepdims=True)
                    street = np.clip((lum - 14.0) * 3.2, 0, 255) / 255.0
                    tinted = np.array((3, 10, 18), np.float32) + colv[None, :] * street * 1.05
                    mix = min(1.0, (L - 5) / 2.0)
                    col[ok] = col[ok] * (1 - mix) + tinted[ok] * mix
                lc, okl = _tile_sample("Dunkel", "labels", lat, lon, min(L, 18))
                al = (lc[:, 3:4] / 255.0) * okl[:, None]
                col = col * (1 - al) + np.array((255, 236, 200), np.float32) * al
            out[idx] = col * g["aa"]
    img = out.reshape(S, S, 3)
    if zoom > 1.15:  # nah dran: Ränder weich ausblenden, damit kein hartes Rechteck entsteht
        img *= _vignette(S)[:, :, None]
    # Atmosphäre außen
    halo_col = np.array((80, 160, 255) if style == "satellit" else glow, np.float32)
    img += g["halo"][:, :, None] * halo_col * (0.75 if style == "satellit" else 0.55)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


_vig_cache: dict = {}


def _vignette(S):
    v = _vig_cache.get(S)
    if v is None:
        t = (np.arange(S, dtype=np.float32) + 0.5) / S
        e = np.clip(np.minimum(t, 1 - t) / 0.09, 0, 1)
        e = e * e * (3 - 2 * e)
        v = np.outer(e, e)
        _vig_cache[S] = v
    return v


def wipe(a: Image.Image, b: Image.Image, t: float, line=(255, 210, 120)) -> Image.Image:
    """Übergang Globus <-> Satellit: eine leuchtende Abtastlinie läuft von oben nach unten (t = 0..1)."""
    A = np.asarray(a, np.float32)
    B = np.asarray(b, np.float32)
    S = A.shape[0]
    y = np.arange(S, dtype=np.float32)[:, None, None]
    edge = t * S * 1.1 - S * 0.05
    m = np.clip((edge - y) / (S * 0.04), 0, 1)
    out = A * (1 - m) + B * m
    glow = np.exp(-((y - edge) / (S * 0.012)) ** 2) * ((A + B).sum(axis=2, keepdims=True) > 30)
    out += glow * np.array(line, np.float32) * 0.9
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def great_circle(a, b, n=40):
    """Punkte (lat, lon) auf dem kürzesten Weg von a nach b."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    v1 = np.array([math.cos(la1) * math.cos(lo1), math.cos(la1) * math.sin(lo1), math.sin(la1)])
    v2 = np.array([math.cos(la2) * math.cos(lo2), math.cos(la2) * math.sin(lo2), math.sin(la2)])
    om = math.acos(max(-1.0, min(1.0, float(v1 @ v2))))
    if om < 1e-4:
        return np.array([a[0]]), np.array([a[1]]), np.zeros(1)
    t = np.linspace(0, 1, n)
    pts = (np.sin((1 - t) * om)[:, None] * v1 + np.sin(t * om)[:, None] * v2) / math.sin(om)
    lat = np.degrees(np.arcsin(np.clip(pts[:, 2], -1, 1)))
    lon = np.degrees(np.arctan2(pts[:, 1], pts[:, 0]))
    lift = 0.14 * om / math.pi * np.sin(t * math.pi)
    return lat, lon, lift
