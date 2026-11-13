"""
Weltlage-Karte für Jarvis: echte Satellitenbilder (wie Google Earth) oder ein dunkler Stil in deiner Farbe.

Bedienung:
- Ansichten oben: LEONBERG (lokal), DEUTSCHLAND, WELT, LUFTRAUM (oder Tasten 1-4, oder per Sprache)
- Maus ziehen = verschieben, Mausrad = zoomen (bis auf Straßenebene), Doppelklick = näher heran, + / − unten rechts
- Klick auf einen Punkt, ein Flugzeug oder einen Eintrag rechts = Details links, die Karte fliegt hin
- Oben rechts: SATELLIT / DUNKEL, ABC = Ortsnamen ein/aus, ◐ = Farben, ⛶ (oder F11) = Vollbild, Esc = zurück
- "Jarvis, wie ist die Lage?": Er spricht das Briefing und fliegt die Orte nacheinander an.

Die Karte besteht aus Kacheln (256 x 256 Pixel), die nur bei Bedarf geladen und im Ordner "globus/kacheln"
gespeichert werden. Verschieben bewegt nur fertige Bilder, deshalb läuft es flüssig.
Quellen: Satellit von Esri World Imagery (Esri, Maxar, Earthstar Geographics), dunkle Karte von CARTO
(Kartendaten © OpenStreetMap-Mitwirkende). Beide sind für private Nutzung mit Quellenangabe gedacht.
"""

import collections
import math
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.request
import webbrowser

from PIL import Image, ImageDraw, ImageOps, ImageTk

import pc_flights
import pc_frameless
import pc_news

TILE = 256
SOURCES = {
    "Satellit": dict(url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                     labels="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
                     max=19, attr="Satellit: Esri, Maxar, Earthstar Geographics"),
    "Dunkel": dict(url="https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png",
                   labels="https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}.png",
                   max=19, attr="Karte: © OpenStreetMap-Mitwirkende, © CARTO"),
}
STYLES = list(SOURCES)
THEMES = {
    "Glut": dict(bg=(5, 8, 18), accent=(255, 142, 48), accent2=(255, 214, 96), text=(255, 230, 210),
                 dim=(196, 156, 128), panel=(16, 13, 20), tint=(255, 150, 60)),
    "Jarvis": dict(bg=(2, 10, 18), accent=(0, 207, 255), accent2=(170, 240, 255), text=(220, 245, 255),
                   dim=(130, 192, 214), panel=(5, 22, 34), tint=(60, 200, 255)),
    "Radar": dict(bg=(2, 12, 6), accent=(70, 255, 120), accent2=(200, 255, 170), text=(220, 255, 226),
                  dim=(124, 198, 140), panel=(5, 22, 11), tint=(80, 255, 130)),
    "Violett": dict(bg=(8, 4, 20), accent=(182, 140, 255), accent2=(255, 190, 250), text=(238, 228, 255),
                    dim=(172, 152, 212), panel=(17, 11, 31), tint=(170, 130, 255)),
}
THEME_NAMES = list(THEMES)
VIEWS = [("leonberg", "Leonberg"), ("deutschland", "Deutschland"), ("welt", "Welt"), ("luftraum", "Luftraum")]
KIND_COLORS = {"konflikt": (255, 80, 64), "katastrophe": (255, 120, 50), "wetter": (100, 196, 255),
               "wirtschaft": (255, 210, 90), "sport": (120, 230, 140), "wissenschaft": (176, 156, 255),
               "lokal": (110, 255, 205)}
HOME_DEFAULT = (48.8003, 9.0144, "Leonberg")


def hexc(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb[:3])


def mix(a, b, t: float):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ll2px(lat, lon, z):
    n = TILE * (2 ** z)
    lat = max(-85.05, min(85.05, lat))
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def px2ll(x, y, z):
    n = TILE * (2 ** z)
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def _base_folder(sub="") -> str:
    try:
        import pc_apps

        base = pc_apps.base_dir()
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "globus", sub) if sub else os.path.join(base, "globus")
    os.makedirs(path, exist_ok=True)
    return path


# --- Kacheln -------------------------------------------------------------------------------
class Tiles:
    """Lädt Kacheln im Hintergrund (mehrere gleichzeitig), merkt sie im Speicher und auf der Festplatte."""

    def __init__(self, on_ready):
        self.on_ready = on_ready  # wird im Lade-Thread aufgerufen: on_ready(key)
        self.mem: "collections.OrderedDict" = collections.OrderedDict()
        self.lock = threading.Lock()
        self.q: "queue.LifoQueue" = queue.LifoQueue()
        self.pending = set()
        self.failed = {}
        self.folder = _base_folder("kacheln")
        for _ in range(6):
            threading.Thread(target=self._worker, daemon=True).start()

    def get(self, key):
        with self.lock:
            img = self.mem.get(key)
            if img is not None:
                self.mem.move_to_end(key)
            return img

    def want(self, key):
        """key = (Quelle, Ebene "base"/"labels", z, x, y)."""
        with self.lock:
            if key in self.mem or key in self.pending:
                return
            if time.time() - self.failed.get(key, 0) < 60:
                return
            self.pending.add(key)
        self.q.put(key)

    def clear_queue(self):
        """Alte Wünsche verwerfen (z. B. nach einem Zoom), damit die sichtbaren Kacheln zuerst kommen."""
        try:
            while True:
                key = self.q.get_nowait()
                with self.lock:
                    self.pending.discard(key)
        except queue.Empty:
            pass

    def _path(self, key):
        src, layer, z, x, y = key
        return os.path.join(self.folder, f"{src}_{layer}", str(z), str(x), f"{y}.img")

    def _worker(self):
        while True:
            key = self.q.get()
            src, layer, z, x, y = key
            img = None
            path = self._path(key)
            try:
                if os.path.exists(path):
                    img = Image.open(path)
                    img.load()
                else:
                    url = SOURCES[src]["labels" if layer == "labels" else "url"]
                    url = url.format(z=z, x=x, y=y, s="abcd"[(x + y) % 4])
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Jarvis-Assistent"})
                    with urllib.request.urlopen(req, timeout=15) as r:
                        data = r.read()
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "wb") as f:
                        f.write(data)
                    img = Image.open(path)
                    img.load()
                img = img.convert("RGBA" if layer == "labels" else "RGB")
            except Exception:
                img = None
            with self.lock:
                self.pending.discard(key)
                if img is None:
                    self.failed[key] = time.time()
                else:
                    self.mem[key] = img
                    while len(self.mem) > 900:
                        self.mem.popitem(last=False)
            if img is not None:
                self.on_ready(key)


# --- Fenster -------------------------------------------------------------------------------
class GlobeWindow:
    """Das Weltlage-Fenster (der Name bleibt aus Kompatibilität, inzwischen ist es eine Karte)."""

    def __init__(self, root: tk.Tk, k: float, get_settings, save_setting, host=None):
        self.root, self.k = root, k
        self.host = host  # Funktion, die das HUD-Fenster liefert: dann öffnet sich die Karte IM HUD (wie die Einstellungen)
        self.embedded = False
        self.region = None  # (x, y, w, h) im HUD: Karte nur rechts im Lage-Screen statt über das ganze Fenster
        self.on_close = None  # wird aufgerufen, wenn die Karte im Lage-Screen geschlossen wird
        self.routes = None  # (Wege, gewählter Index, Start, Ziel) von pc_route
        self.news_override = None  # Lage eines anderen Ortes (Lieblingsort), sonst die normale Lage
        self.get_settings, self.save_setting = get_settings, save_setting
        s = get_settings()
        self.theme_name = s.get("globe_theme", "Glut") if s.get("globe_theme") in THEMES else "Glut"
        self.style = s.get("map_style", "Satellit") if s.get("map_style") in SOURCES else "Satellit"
        self.show_labels = bool(s.get("map_labels", True))
        self.win = None
        self.view = "leonberg"
        self.z = 13
        self.cx = self.cy = 0.0  # Mitte in Weltpixeln der aktuellen Zoomstufe
        self.home = HOME_DEFAULT
        self.open_ = False
        self.fullscreen = False
        self.news = None
        self.planes_near: list = []
        self.planes_area: list = []
        self.planes_ts = self.area_ts = 0.0
        self.area_bbox = None
        self.status = ""
        self.selected = None
        self.panel_scroll = 0
        self._panel_sig = self._card_sig = None
        self.tiles = Tiles(self._tile_loaded)
        self._placed: dict = {}  # (Ebene, tx, ty) -> (Canvas-Element, PhotoImage, vorläufig?)
        self._ready_q: "queue.Queue" = queue.Queue()
        self._tinted: "collections.OrderedDict" = collections.OrderedDict()
        self.drag = None
        self.fly_jobs: list = []
        self.tour_jobs: list = []
        self._imgs: dict = {}
        self._plane_map: dict = {}
        self._threads = False
        self._job = None
        self._last_planes = 0.0
        self.s = 1.0
        self.size = (1280, 760)
        self.top_h = 56
        self.panel_w = 0
        self._set_view_center("leonberg")

    @property
    def theme(self):
        return THEMES[self.theme_name]

    # --- Öffentlich (nur im Tk-Thread) ---
    def show(self, view: str = None, region=False):
        if region is None:  # ganz normal (ganzes Fenster): wieder die normale Lage
            self.region = None
            if self.news_override is not None:
                self.news_override = None
                self.news = pc_news.get(wait=False)
                self._panel_sig = None
        if self.win is None:
            self._create()
        if view == "weltlage":
            view = "welt"
        if view in dict(VIEWS) and view != self.view:
            self.view = view
            self.selected = None
            self.panel_scroll = 0
            self._set_view_center(view)
        self.open_ = True
        if self.embedded:
            self._place()
            self.win.lift()
            self.c.focus_set()
        else:
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

    def show_in(self, region, view=None):
        """Karte nur in einem Bereich des HUD zeigen (rechts im Lage-Screen)."""
        self.region = region
        self.show(view)

    def set_news(self, data):
        """Punkte eines bestimmten Ortes zeigen (None = wieder die normale Lage)."""
        self.news_override = data
        self.news = data if data is not None else pc_news.get(wait=False)
        self._panel_sig = self._card_sig = None
        self.selected = None
        self._ready_q.put("overlays")

    def set_routes(self, routes, idx, a, b):
        """Wege (schnellster, flachster, kürzester) auf der Karte zeigen und so zoomen, dass alles drauf ist."""
        self.routes = (routes, idx, a, b)
        self.selected = None
        lats = [p[1] for r in routes for p in r["coords"][::10]] + [a[0], b[0]]
        lons = [p[0] for r in routes for p in r["coords"][::10]] + [a[1], b[1]]
        span = max(max(lats) - min(lats), (max(lons) - min(lons)) * math.cos(math.radians(a[0])), 0.002)
        z = int(max(5, min(16, math.log2(360.0 / span) - 0.6)))
        self.fly_to((max(lats) + min(lats)) / 2, (max(lons) + min(lons)) / 2, z)
        self._ready_q.put("overlays")

    def _draw_routes(self):
        if not self.routes:
            return
        c, t, s = self.c, self.theme, self.s
        routes, idx, a, b = self.routes
        cols = [(255, 196, 70), (90, 200, 255), (170, 240, 170)]
        order = sorted(range(len(routes)), key=lambda i: (i == (idx if idx is not None else 0)))
        for i in order:  # gewählter Weg zuletzt (oben)
            r = routes[i]
            main = i == (idx if idx is not None else 0)
            pts = []
            step = max(1, len(r["coords"]) // 400)
            for lon, lat in r["coords"][::step] + [r["coords"][-1]]:
                pts += self._screen(lat, lon)
            if len(pts) >= 4:
                c.create_line(*pts, fill="#000000", width=max(3, int((8 if main else 6) * s)), tags="geo",
                              capstyle="round", joinstyle="round")
                c.create_line(*pts, fill=hexc(cols[i % 3]), width=max(2, int((5 if main else 3) * s)), tags="geo",
                              capstyle="round", joinstyle="round")
            lon, lat = r["coords"][len(r["coords"]) // 2]
            x, y = self._screen(lat, lon)
            label = f"{r['label']} · {int(round(r['min']))} min" + (f" · {r['hm']} hm" if r.get("hm", 0) > 0 else "")
            c.create_rectangle(x + 8 * s, y - 11 * s, x + 14 * s + self.f_label.measure(label), y + 11 * s,
                               fill=hexc(t["panel"]), outline=hexc(cols[i % 3]), tags="geo")
            c.create_text(x + 11 * s, y, text=label, anchor="w", fill=hexc(t["text"]), font=self.f_label, tags="geo")
        for (lat, lon, _n), col in ((a, "#6effcd"), (b, "#ff5a3c")):
            x, y = self._screen(lat, lon)
            r = 7 * s
            c.create_oval(x - r, y - r, x + r, y + r, fill=col, outline="#000000", width=2, tags="geo")

    def focus(self, obj, close=True):
        """Einen Brennpunkt zeigen und ganz nah heranfliegen (für das Briefing)."""
        self.stop_tour()
        self.selected = ("punkt", obj)
        self._card_sig = self._panel_sig = None
        z = 16 if obj.get("art") == "lokal" else 12 if obj.get("deutschland") else 11
        self.fly_to(obj["lat"], obj["lon"], z if close else None)
        if obj.get("bild"):
            self._load_image(obj["bild"])

    def close(self):
        self.stop_tour()
        was_region = self.region is not None and self.open_
        self.routes = None
        self.open_ = False
        if self.win is not None:
            if self.fullscreen:
                self.toggle_fullscreen()
            if self.embedded:
                self.win.place_forget()
            else:
                self.win.withdraw()
        if was_region and self.on_close:
            try:
                self.on_close()
            except Exception:
                pass

    def is_open(self) -> bool:
        return self.open_

    def set_view(self, view: str):
        if view == "weltlage":
            view = "welt"
        if view in dict(VIEWS) and view != self.view:
            self.stop_tour()
            self.view = view
            self.selected = None
            self.panel_scroll = 0
            lat, lon, z = self._view_target(view)
            self.fly_to(lat, lon, z)
            self._layout(keep_tiles=True)
            self._start_data()

    def cycle_theme(self):
        self.save_setting("globe_theme", THEME_NAMES[(THEME_NAMES.index(self.theme_name) + 1) % len(THEME_NAMES)])

    def toggle_style(self):
        self.save_setting("map_style", "Dunkel" if self.style == "Satellit" else "Satellit")

    def toggle_labels(self):
        self.save_setting("map_labels", not self.show_labels)

    def apply_settings(self, s: dict):
        theme = s.get("globe_theme", "Glut") if s.get("globe_theme") in THEMES else "Glut"
        style = s.get("map_style", "Satellit") if s.get("map_style") in SOURCES else "Satellit"
        labels = bool(s.get("map_labels", True))
        if (theme, style, labels) != (self.theme_name, self.style, self.show_labels):
            self.theme_name, self.style, self.show_labels = theme, style, labels
            self._tinted.clear()
            if self.win is not None:
                self._clear_tiles()
                self._layout()

    def toggle_fullscreen(self):
        if self.win is None:
            return
        self.fullscreen = not self.fullscreen
        if self.embedded:  # im HUD: ganze Fläche statt Fenster im Fenster
            self._place()
            self.win.after(80, self._layout)
            return
        try:
            self.win.attributes("-fullscreen", self.fullscreen)
        except Exception:
            self.fullscreen = False
        self.win.after(80, self._layout)

    # --- Kamera ---
    def _view_target(self, view):
        if view == "leonberg":
            return self.home[0], self.home[1], 13
        if view == "deutschland":
            return 51.1, 10.4, 6
        if view == "luftraum":
            return self.home[0], self.home[1], 8
        return 35.0, 15.0, 3

    def _set_view_center(self, view):
        lat, lon, z = self._view_target(view)
        self.z = z
        self.cx, self.cy = ll2px(lat, lon, z)

    def center_ll(self):
        return px2ll(self.cx, self.cy, self.z)

    def _set_zoom(self, z, anchor=None):
        """Zoomstufe ändern; anchor = Bildschirmpunkt, der an seinem Platz bleiben soll."""
        z = max(2, min(SOURCES[self.style]["max"], int(z)))
        if z == self.z:
            return
        mx, my = anchor if anchor else (self.vw / 2, self.top_h + self.vh / 2)
        ox, oy = mx - self.vw / 2, my - (self.top_h + self.vh / 2)
        f = 2 ** (z - self.z)
        self.cx, self.cy = (self.cx + ox) * f - ox, (self.cy + oy) * f - oy
        self.z = z
        self.tiles.clear_queue()
        self._clear_tiles()
        self._update_tiles()
        self._draw_overlays()

    def fly_to(self, lat, lon, z=None):
        """Flug wie bei Google Earth: kurz herauszoomen, hinüber, wieder hinein."""
        self.stop_fly()
        z = self.z if z is None else max(2, min(SOURCES[self.style]["max"], int(z)))
        clat, clon = self.center_ll()
        dist = pc_flights.distance_km(clat, clon, lat, lon)
        mid = min(self.z, z, max(3, int(12 - math.log2(max(1.0, dist)))))
        steps = []
        for zz in range(self.z - 1, mid - 1, -1):  # heraus
            steps.append(("z", zz, None))
        n = 8 if dist > 2 else 3
        for i in range(1, n + 1):  # hinüber (in Kartenkoordinaten der mittleren Stufe)
            steps.append(("p", mid, i / n))
        for zz in range(mid + 1, z + 1):  # hinein
            steps.append(("z", zz, None))
        start = (clat, clon)
        t = 0
        for kind, zz, f in steps:
            t += 150 if kind == "z" else 70
            self.fly_jobs.append(self.win.after(t, lambda kind=kind, zz=zz, f=f: self._fly_step(kind, zz, f, start, (lat, lon))))

    def _fly_step(self, kind, zz, f, a, b):
        if kind == "z":
            lat, lon = self.center_ll()
            self.z = zz
            self.cx, self.cy = ll2px(lat, lon, zz)
            self.tiles.clear_queue()
            self._clear_tiles()
        else:
            if self.z != zz:
                lat, lon = self.center_ll()
                self.z = zz
                self.cx, self.cy = ll2px(lat, lon, zz)
                self._clear_tiles()
            ax, ay = ll2px(a[0], a[1], zz)
            bx, by = ll2px(b[0], b[1], zz)
            e = f * f * (3 - 2 * f)
            self.cx, self.cy = ax + (bx - ax) * e, ay + (by - ay) * e
        self._update_tiles()
        self._draw_overlays()

    def stop_fly(self):
        for j in self.fly_jobs:
            try:
                self.win.after_cancel(j)
            except Exception:
                pass
        self.fly_jobs = []

    def select(self, kind, obj, fly=True):
        self.selected = (kind, obj)
        self._card_sig = self._panel_sig = None
        if fly:
            z = {"leonberg": 14, "deutschland": 9, "welt": 6, "luftraum": 10}[self.view]
            if kind == "punkt" and obj.get("art") == "lokal":
                z = max(z, 14)
            self.fly_to(obj["lat"], obj["lon"], max(self.z, z) if self.view != "welt" else z)
        if kind == "punkt" and obj.get("bild"):
            self._load_image(obj["bild"])
        self._draw_overlays()

    # --- Tour ---
    def tour(self, seconds: float):
        self.stop_tour()
        data = self.news_override or pc_news.get(wait=False)
        if data:
            self.news = data
            self._panel_sig = None
        pts = (self.news or {}).get("brennpunkte") or []
        stops = [p for p in pts if p.get("im_briefing")][:5] or pts[:4]
        if self.view != "welt":
            self.view = "welt"
            self._layout(keep_tiles=True)
        self.selected = None
        if not stops:
            return
        per = max(4.0, (seconds - 1.0) / len(stops))
        for i, p in enumerate(stops):
            self.tour_jobs.append(self.win.after(int((0.6 + i * per) * 1000), lambda p=p: self.select("punkt", p)))
        self.tour_jobs.append(self.win.after(int((0.6 + len(stops) * per + 1.5) * 1000), self._tour_end))

    def _tour_end(self):
        self.tour_jobs = []
        lat, lon, z = self._view_target(self.view)
        self.fly_to(lat, lon, z)

    def stop_tour(self):
        for j in self.tour_jobs:
            try:
                self.win.after_cancel(j)
            except Exception:
                pass
        self.tour_jobs = []

    # --- Aufbau ---
    def _place(self):
        if self.region and not self.fullscreen:
            x, y, w, h = self.region
            self.win.place(x=x, y=y, width=w, height=h, relx=0, rely=0, relwidth=0, relheight=0, anchor="nw")
            return
        if self.fullscreen:
            self.win.place(relx=0, rely=0, relwidth=1, relheight=1, x=0, y=0, anchor="nw")
        else:
            self.win.place(relx=0.5, rely=0.5, relwidth=0.96, relheight=0.94, anchor="center")

    def _color_bar(self):
        if self.embedded:
            return
        pc_frameless.color_titlebar(self.win, hexc(self.theme["bg"]), hexc(self.theme["dim"]))

    def _create(self):
        k = self.k
        parent = None
        try:
            parent = self.host() if self.host else None
        except Exception:
            parent = None
        if parent is not None:
            self.embedded = True
            self.win = tk.Frame(parent, bg=hexc(self.theme["bg"]), highlightthickness=1,
                                highlightbackground=hexc(mix(self.theme["bg"], self.theme["accent"], 0.45)), bd=0)
        else:
            self.win = tk.Toplevel(self.root)
            self.win.title("Jarvis – Weltlage")
            self.win.configure(bg=hexc(self.theme["bg"]))
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
        self.c = tk.Canvas(self.win, highlightthickness=0, bd=0, bg=hexc(self.theme["bg"]))
        self.c.pack(fill="both", expand=True)
        self.f_title = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.f_tab = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_big = tkfont.Font(family="Segoe UI", size=26, weight="bold")
        self.f_head = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.f_item = tkfont.Font(family="Segoe UI Semibold", size=11)
        self.f_text = tkfont.Font(family="Segoe UI", size=10)
        self.f_label = tkfont.Font(family="Segoe UI Semibold", size=9)
        self.f_small = tkfont.Font(family="Segoe UI", size=8)
        self.f_btn = tkfont.Font(family="Segoe UI Symbol", size=13)
        self._cfg_job = None
        self.win.bind("<Configure>", self._on_configure)
        self.win.bind("<Map>", lambda e: e.widget is self.win and self._color_bar())
        for w in ((self.win, self.c) if self.embedded else (self.win,)):  # im HUD bekommt die Karte die Tasten
            w.bind("<Escape>", lambda e: self.toggle_fullscreen() if self.fullscreen else self.close())
            w.bind("<F11>", lambda e: self.toggle_fullscreen())
            for i, (key, _) in enumerate(VIEWS):
                w.bind(str(i + 1), lambda e, key=key: self.set_view(key))
            w.bind("<plus>", lambda e: self._set_zoom(self.z + 1))
            w.bind("<minus>", lambda e: self._set_zoom(self.z - 1))
        self.c.bind("<Enter>", lambda e: self.c.focus_set(), add="+")
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
        self._cfg_job = self.win.after(150, self._layout)

    def _layout(self, keep_tiles=False):
        if self.win is None:
            return
        self._cfg_job = None
        self.win.update_idletasks()
        W, H = max(300, self.c.winfo_width()), max(300, self.c.winfo_height())
        s = max(0.65, min(W / 1280, H / 760))
        self.size, self.s = (W, H), s
        t = self.theme
        for f, base in ((self.f_title, 11), (self.f_tab, 10), (self.f_big, 26), (self.f_head, 12), (self.f_item, 11),
                        (self.f_text, 10), (self.f_label, 9), (self.f_small, 8), (self.f_btn, 13)):
            f.configure(size=max(7, int(round(base * s))))
        c = self.c
        c.configure(bg=hexc(t["bg"]))
        self.win.configure(bg=hexc(t["bg"]))
        self._color_bar()
        self.top_h = int(56 * s)
        self.panel_w = int(380 * s) if W > 900 * s else 0
        self.vw, self.vh = W, H - self.top_h
        c.delete("ui")
        c.delete("geo")
        c.delete("panel")
        c.delete("card")
        if not keep_tiles:
            self._clear_tiles()
        self._panel_sig = self._card_sig = None
        acc, txt, dim = hexc(t["accent"]), hexc(t["text"]), hexc(t["dim"])
        # oberer Balken
        c.create_rectangle(0, 0, W, self.top_h, fill=hexc(t["bg"]), outline="", tags=("ui", "bar"))
        c.create_line(0, self.top_h, W, self.top_h, fill=hexc(mix(t["bg"], t["accent"], 0.4)), tags="ui")
        c.create_text(int(22 * s), self.top_h // 2, text="◉  J.A.R.V.I.S.", anchor="w", fill=acc, font=self.f_title,
                      tags="ui")
        tab_w = int(122 * s)
        x = W / 2 - tab_w * len(VIEWS) / 2
        for key, label in VIEWS:
            on = key == self.view
            tag = f"tab_{key}"
            r = int(15 * s)
            self._pill(x + 4, self.top_h / 2 - r, x + tab_w - 4, self.top_h / 2 + r,
                       mix(t["bg"], t["accent"], 0.85 if on else 0.16), (tag, "ui"))
            c.create_text(x + tab_w / 2, self.top_h / 2, text=label.upper(), font=self.f_tab,
                          fill=hexc(t["bg"]) if on else txt, tags=(tag, "ui"))
            c.tag_bind(tag, "<Button-1>", lambda e, key=key: self.set_view(key))
            self._hand(tag)
            x += tab_w
        bx = W - int(24 * s)
        btns = (("⛶", "b_full", self.toggle_fullscreen), ("◐", "b_theme", self.cycle_theme))
        if self.embedded:
            btns = (("✕", "b_close", self.close),) + btns
        for glyph, tag, fn in btns:
            c.create_text(bx, self.top_h // 2, text=glyph, font=self.f_btn, fill=dim, tags=(tag, "ui"))
            c.tag_bind(tag, "<Button-1>", lambda e, fn=fn: fn())
            c.tag_bind(tag, "<Enter>", lambda e, tag=tag: (c.itemconfigure(tag, fill=acc), c.config(cursor="hand2")))
            c.tag_bind(tag, "<Leave>", lambda e, tag=tag: (c.itemconfigure(tag, fill=dim), c.config(cursor="")))
            bx -= int(40 * s)
        r = int(13 * s)
        for text, tag, fn, on, pw in ((("◎ " + self.style.upper()), "b_style", self.toggle_style, True, 118),
                                       ("ABC", "b_labels", self.toggle_labels, self.show_labels, 56)):
            w = int(pw * s)
            self._pill(bx - w, self.top_h / 2 - r, bx, self.top_h / 2 + r,
                       mix(t["bg"], t["accent"], 0.45 if on and tag == "b_labels" else 0.16), (tag, "ui"))
            c.create_text(bx - w / 2, self.top_h / 2, text=text, font=self.f_label, fill=txt, tags=(tag, "ui"))
            c.tag_bind(tag, "<Button-1>", lambda e, fn=fn: fn())
            self._hand(tag)
            bx -= w + int(10 * s)
        # Zoom-Knöpfe
        zx = W - self.panel_w - int(34 * s)
        for i, (glyph, dz) in enumerate((("+", 1), ("−", -1))):
            y = H - int(96 * s) + i * int(40 * s)
            tag = f"zoom{dz}"
            c.create_oval(zx - 16 * s, y - 16 * s, zx + 16 * s, y + 16 * s, fill=hexc(t["panel"]),
                          outline=hexc(mix(t["bg"], t["accent"], 0.6)), tags=(tag, "ui"))
            c.create_text(zx, y, text=glyph, font=self.f_head, fill=txt, tags=(tag, "ui"))
            c.tag_bind(tag, "<Button-1>", lambda e, dz=dz: (self.stop_tour(), self._set_zoom(self.z + dz)))
            self._hand(tag)
        # Texte
        self.t_big = c.create_text(int(28 * s), self.top_h + int(16 * s), text="", anchor="nw", fill=acc,
                                   font=self.f_big, tags="ui")
        self.t_sub = c.create_text(int(30 * s), self.top_h + int(60 * s), text="", anchor="nw", fill=txt,
                                   font=self.f_head, tags="ui")
        self.t_status = c.create_text(int(14 * s), H - int(8 * s), text="", anchor="sw", fill=txt,
                                      font=self.f_small, tags="ui")
        self.t_attr = c.create_text(W - self.panel_w - int(12 * s), H - int(8 * s), anchor="se",
                                    text=SOURCES[self.style]["attr"], fill=dim, font=self.f_small, tags="ui")
        self._update_tiles()
        self._draw_overlays()
        self._draw_panel()
        self._draw_card()
        self._raise()

    def _pill(self, x0, y0, x1, y1, fill, tags):
        r = (y1 - y0) / 2
        c, col = self.c, hexc(fill)
        c.create_oval(x0, y0, x0 + 2 * r, y1, fill=col, outline="", tags=tags)
        c.create_oval(x1 - 2 * r, y0, x1, y1, fill=col, outline="", tags=tags)
        c.create_rectangle(x0 + r, y0, x1 - r, y1, fill=col, outline="", tags=tags)

    def _hand(self, tag):
        self.c.tag_bind(tag, "<Enter>", lambda e: self.c.config(cursor="hand2"), add="+")
        self.c.tag_bind(tag, "<Leave>", lambda e: self.c.config(cursor=""), add="+")

    def _raise(self):
        c = self.c
        for tag in ("tile_base", "tile_labels"):
            c.tag_lower(tag)
        c.tag_lower("tile_labels")
        c.tag_lower("tile_base")
        for tag in ("geo", "planes", "markers", "callout", "ui", "panel", "card"):
            c.tag_raise(tag)

    # --- Kacheln anzeigen ---
    def _clear_tiles(self):
        self.c.delete("tile_base")
        self.c.delete("tile_labels")
        self._placed.clear()

    def _tile_loaded(self, key):  # Lade-Thread
        self._ready_q.put(key)

    def _tint(self, img, key):
        """Dunkle Karte in der Farbe des Themas einfärben; Satellitenbilder bekommen einen warmen Gold-Schimmer,
        damit die Karte zur goldenen Kugel im HUD passt."""
        hit = self._tinted.get(key)
        if hit is not None:
            return hit
        t = self.theme
        g = ImageOps.grayscale(img)
        if self.style != "Dunkel":
            warm = ImageOps.colorize(g, black=(8, 4, 0), white=mix((255, 214, 150), t["tint"], 0.35))
            out = Image.blend(img.convert("RGB"), warm, 0.38)
        else:
            g = g.point(lambda v: min(255, int(v * 2.4)))
            out = ImageOps.colorize(g, black=t["bg"], white=mix(t["bg"], t["tint"], 0.8))
        self._tinted[key] = out
        while len(self._tinted) > 400:
            self._tinted.popitem(last=False)
        return out

    def _preview(self, layer, z, tx, ty):
        """Solange die Kachel lädt: ein vergrößerter Ausschnitt einer schon geladenen gröberen Kachel."""
        n = 2 ** z
        for up in range(1, 6):
            pz = z - up
            if pz < 0:
                break
            f = 2 ** up
            px, py = (tx % n) // f, ty // f
            img = self.tiles.get((self.style, layer, pz, px, py))
            if img is not None:
                size = TILE // f
                ox, oy = ((tx % n) % f) * size, (ty % f) * size
                if size < 2:
                    return None
                part = img.crop((ox, oy, ox + size, oy + size)).resize((TILE, TILE), Image.BILINEAR)
                return self._tint(part, ("prev", layer, z, tx, ty)) if layer == "base" else part
        return None

    def _update_tiles(self):
        """Fehlende sichtbare Kacheln setzen, unsichtbare entfernen."""
        if self.win is None:
            return
        c = self.c
        z, n = self.z, 2 ** self.z
        left = self.cx - self.vw / 2
        top = self.cy - self.vh / 2
        tx0, tx1 = int(math.floor(left / TILE)), int(math.floor((left + self.vw) / TILE))
        ty0, ty1 = max(0, int(math.floor(top / TILE))), min(n - 1, int(math.floor((top + self.vh) / TILE)))
        layers = ["base"] + (["labels"] if self.show_labels else [])
        want = set()
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                for layer in layers:
                    want.add((layer, tx, ty))
        for key in list(self._placed):
            if key not in want:
                c.delete(self._placed.pop(key)[0])
        cxs = (ty0 + ty1) / 2
        order = sorted(want, key=lambda k: (k[0] != "base", (k[1] - (tx0 + tx1) / 2) ** 2 + (k[2] - cxs) ** 2))
        for layer, tx, ty in order:
            have = self._placed.get((layer, tx, ty))
            if have and not have[2]:
                continue
            key = (self.style, layer, z, tx % n, ty)
            img = self.tiles.get(key)
            final = img is not None
            if img is not None and layer == "base":
                img = self._tint(img, key)
            if img is None:
                self.tiles.want(key)
                if have:
                    continue
                img = self._preview(layer, z, tx, ty)
                if img is None:
                    continue
            photo = ImageTk.PhotoImage(img)
            x = tx * TILE - left
            y = ty * TILE - top + self.top_h
            if have:
                c.delete(have[0])
            item = c.create_image(x, y, anchor="nw", image=photo, tags=(f"tile_{layer}",))
            self._placed[(layer, tx, ty)] = (item, photo, not final)
        if layers == ["base"]:
            c.delete("tile_labels")
            for key in [k for k in self._placed if k[0] == "labels"]:
                self._placed.pop(key, None)
        self._raise()

    # --- Maus ---
    def _in_map(self, x, y) -> bool:
        if y < self.top_h or x > self.size[0] - self.panel_w:
            return False
        bb = self.c.bbox("card")
        return not (bb and bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3])

    def _press(self, e):
        self.drag = (e.x, e.y, e.x, e.y, False) if self._in_map(e.x, e.y) else None

    def _motion(self, e):
        if not self.drag:
            return
        x0, y0, lx, ly, moved = self.drag
        if not moved and abs(e.x - x0) + abs(e.y - y0) < 4:
            return
        self.stop_tour()
        self.stop_fly()
        dx, dy = e.x - lx, e.y - ly
        self.cx -= dx
        self.cy -= dy
        for tag in ("tile_base", "tile_labels", "geo"):
            self.c.move(tag, dx, dy)  # nur verschieben: flüssig
        self.drag = (x0, y0, e.x, e.y, True)
        now = time.time()
        if now - getattr(self, "_last_tile_upd", 0) > 0.08:
            self._last_tile_upd = now
            self._update_tiles()

    def _release(self, e):
        if not self.drag:
            return
        moved = self.drag[4]
        self.drag = None
        if moved:
            self._update_tiles()
            self._draw_overlays()

    def _double(self, e):
        if self._in_map(e.x, e.y):
            self.stop_tour()
            self._set_zoom(self.z + 1, (e.x, e.y))

    def _wheel(self, e):
        W, H = self.size
        if self.panel_w and e.x > W - self.panel_w:
            self.panel_scroll = max(0, self.panel_scroll - int(e.delta / 120 * 60 * self.s))
            self._panel_sig = None
            self._draw_panel()
            return
        self.stop_tour()
        self.stop_fly()
        now = time.time()
        if now - getattr(self, "_last_wheel", 0) < 0.12:  # Touchpads schicken viele kleine Schritte
            return
        self._last_wheel = now
        self._set_zoom(self.z + (1 if e.delta > 0 else -1), (e.x, e.y))

    # --- Daten ---
    def _start_data(self):
        if self._threads:
            return
        self._threads = True
        threading.Thread(target=self._data_loop, daemon=True).start()

    def _data_loop(self):
        city = (self.get_settings().get("home_city") or "Leonberg").strip()
        if city.lower() != "leonberg":
            try:
                import pc_info

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
                data = self.news_override or pc_news.get(wait=self.news is None)
                if data and data is not self.news:
                    self.news = data
                    self._panel_sig = None
                    self._ready_q.put("overlays")
            if self.view in ("luftraum", "leonberg", "deutschland") and now - self.planes_ts > 12:
                self.planes_ts = now
                try:
                    near = pc_flights.around(self.home[0], self.home[1], 250)
                    for p in near:
                        p["ts"] = now
                    self.planes_near = near
                    self.status = f"ADS-B live · {len(near)} Flugzeuge im Umkreis von 460 km um {self.home[2]}"
                except Exception as e:
                    self.status = f"Flugdaten gerade nicht erreichbar ({str(e)[:60]})"
                self._panel_sig = None
            if self.view == "luftraum":
                bbox = (34, -25, 72, 45)
                wait = 0 if bbox != self.area_bbox else 300
                if now - self.area_ts > max(wait, 20):
                    self.area_ts = now
                    try:
                        area = pc_flights.area(*bbox)
                        for p in area:
                            p["ts"] = now
                        self.planes_area, self.area_bbox = area, bbox
                    except Exception as e:
                        print(f"OpenSky: {e}")
                        self.area_ts = now + 300
            time.sleep(1.0)

    def _all_planes(self):
        if self.view == "welt":
            return []
        near_ids = {p["id"] for p in self.planes_near}
        extra = [p for p in self.planes_area if p["id"] not in near_ids] if self.view == "luftraum" else []
        return self.planes_near + extra

    def _points(self):
        """Alle Brennpunkte wie im Lage-Modus stehen immer auf der Karte; je nach Ansicht kommen die passenden zuerst."""
        pts = list((self.news or {}).get("brennpunkte") or [])
        hl, ho = self.home[0], self.home[1]
        if self.view == "deutschland":
            pts.sort(key=lambda q: (not q.get("deutschland"), -int(q.get("wichtig", 2))))
        elif self.view in ("leonberg", "luftraum"):
            pts.sort(key=lambda q: (not (q.get("art") == "lokal" or
                                         pc_flights.distance_km(hl, ho, q["lat"], q["lon"]) < 40), -int(q.get("wichtig", 2))))
        else:
            pts.sort(key=lambda q: -int(q.get("wichtig", 2)))
        return pts

    # --- Hauptschleife (Kacheln einsetzen, Flugzeuge bewegen) ---
    def _loop(self):
        if not self.open_ or self.win is None:
            self._job = None
            return
        try:
            new_tiles = False
            redraw = False
            for _ in range(40):
                try:
                    key = self._ready_q.get_nowait()
                except queue.Empty:
                    break
                if key == "overlays":
                    redraw = True
                elif key[2] == self.z and key[0] == self.style:
                    new_tiles = True
            if new_tiles and not self.drag:
                self._update_tiles()
            now = time.time()
            if (redraw or now - self._last_planes > 1.0) and not self.drag:
                self._last_planes = now
                self._draw_overlays()
            self._update_texts()
            self._draw_panel()
            self._draw_card()
        except Exception as e:
            if str(e) != getattr(self, "_last_err", ""):
                self._last_err = str(e)
                print(f"Karte: {e}")
        self._job = self.win.after(60, self._loop)

    # --- Punkte, Flugzeuge, Beschriftungen ---
    def _screen(self, lat, lon):
        x, y = ll2px(lat, lon, self.z)
        n = TILE * 2 ** self.z
        dx = x - self.cx
        if dx > n / 2:  # um die Erde herum: den nächsten Weg nehmen
            x -= n
        elif dx < -n / 2:
            x += n
        return x - self.cx + self.vw / 2, y - self.cy + self.vh / 2 + self.top_h

    def _visible(self, x, y, pad=0):
        return -pad <= x <= self.size[0] - self.panel_w + pad and self.top_h - pad <= y <= self.size[1] + pad

    def _draw_overlays(self):
        if self.win is None:
            return
        c, t, s = self.c, self.theme, self.s
        c.delete("geo")
        now = time.time()
        acc = hexc(t["accent"])
        self._draw_routes()
        # Flugzeuge
        self._plane_map = {}
        planes = self._all_planes()
        if planes:
            pc_col = hexc(t["accent2"])
            tail_col = hexc(mix((0, 0, 0), t["accent2"], 0.55))
            r = max(2.0, 2.4 * s * (1.4 if self.z >= 9 else 1.0))
            sel = self.selected[1] if self.selected and self.selected[0] == "flug" else None
            for p in planes:
                dt = min(600.0, now - p.get("ts", now))
                lat, lon = pc_flights.move(p, dt)
                x, y = self._screen(lat, lon)
                if not self._visible(x, y):
                    continue
                lat2, lon2 = pc_flights.move(p, dt - 60)
                x2, y2 = self._screen(lat2, lon2)
                if abs(x2 - x) + abs(y2 - y) > 2:
                    c.create_line(x2, y2, x, y, fill=tail_col, width=1, tags=("geo", "planes"))
                item = c.create_oval(x - r, y - r, x + r, y + r, fill=pc_col, outline="", tags=("geo", "planes", "plane"))
                self._plane_map[item] = p
                if p is sel:
                    c.create_oval(x - r * 3.5, y - r * 3.5, x + r * 3.5, y + r * 3.5, outline=hexc(t["text"]),
                                  width=2, tags=("geo", "planes"))
            c.tag_bind("plane", "<Button-1>", self._plane_click)
        # Zuhause
        hx, hy = self._screen(self.home[0], self.home[1])
        if self._visible(hx, hy):
            rr = 9 * s
            c.create_oval(hx - rr, hy - rr, hx + rr, hy + rr, outline=acc, width=2, tags=("geo", "markers"))
            c.create_oval(hx - 3.5 * s, hy - 3.5 * s, hx + 3.5 * s, hy + 3.5 * s, fill=hexc(t["text"]), outline="",
                          tags=("geo", "markers"))
            c.create_text(hx, hy + 18 * s, text=self.home[2].upper(), fill=hexc(t["text"]), font=self.f_small,
                          tags=("geo", "markers"))
        # Brennpunkte mit Beschriftung (Linie nach außen zu einem lesbaren Kästchen)
        boxes = []
        card_bb = c.bbox("card")
        if card_bb:
            boxes.append(card_bb)
        boxes.append((0, self.top_h, int(330 * s), self.top_h + int(100 * s)))  # große Zahl oben links
        pts = self._points()
        placed = []
        for i, q in enumerate(pts[:14]):
            x, y = self._screen(q["lat"], q["lon"])
            if not self._visible(x, y):
                continue
            placed.append((x, y, q))
        # wichtige zuerst beschriften
        placed.sort(key=lambda a: -(int(a[2].get("wichtig", 2)) + (5 if self.selected and self.selected[1] is a[2] else 0)))
        for x, y, q in placed:
            col = KIND_COLORS.get(q.get("art")) or t["accent"]
            sel = self.selected is not None and self.selected[1] is q
            tag = f"pt{id(q)}"
            rr = (6 + 2 * int(q.get("wichtig", 2))) * s
            c.create_oval(x - rr, y - rr, x + rr, y + rr, outline=hexc(col), width=2, tags=("geo", "markers", tag))
            c.create_oval(x - 4 * s, y - 4 * s, x + 4 * s, y + 4 * s, fill=hexc(col), outline="",
                          tags=("geo", "markers", tag))
            if sel:
                c.create_oval(x - rr - 6 * s, y - rr - 6 * s, x + rr + 6 * s, y + rr + 6 * s, outline=hexc(t["text"]),
                              width=2, tags=("geo", "markers", tag))
            title = q.get("titel") or q.get("ort", "")
            title = title if len(title) <= 32 else title[:31].rsplit(" ", 1)[0] + " …"
            sub = q.get("ort", "")
            tw = max(self.f_label.measure(title), self.f_small.measure(sub)) + 20 * s
            th = 38 * s
            spot = None
            for ox, oy in ((46, -58), (46, 22), (-46, -58), (-46, 22), (70, -18), (-70, -18), (46, -100), (-46, 64),
                           (110, -60), (-110, 30)):
                bx0 = x + ox * s - (tw if ox < 0 else 0)
                by0 = y + oy * s
                box = (bx0, by0, bx0 + tw, by0 + th)
                if not (self._visible(box[0], box[1]) and self._visible(box[2], box[3])):
                    continue
                if any(not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]) for b in boxes):
                    continue
                spot = (ox, box)
                break
            if spot is None:
                continue  # kein Platz: nur der Punkt (Titel steht rechts in der Liste)
            ox, box = spot
            boxes.append(box)
            ax = box[0] if ox > 0 else box[2]
            ay = box[1] + th / 2
            c.create_line(x, y, ax, ay, fill=hexc(col), width=1, tags=("geo", "callout", tag))
            c.create_rectangle(*box, fill=hexc(t["panel"]), outline=hexc(col) if sel else hexc(mix(t["panel"], col, 0.7)),
                               width=2 if sel else 1, tags=("geo", "callout", tag))
            c.create_rectangle(box[0], box[1], box[0] + 3 * s, box[3], fill=hexc(col), outline="",
                               tags=("geo", "callout", tag))
            c.create_text(box[0] + 10 * s, box[1] + 5 * s, text=title, anchor="nw", fill=hexc(t["text"]),
                          font=self.f_label, tags=("geo", "callout", tag))
            c.create_text(box[0] + 10 * s, box[1] + 21 * s, text=sub, anchor="nw", fill=hexc(t["dim"]),
                          font=self.f_small, tags=("geo", "callout", tag))
            c.tag_bind(tag, "<Button-1>", lambda e, q=q: (self.stop_tour(), self.select("punkt", q)))
            self._hand(tag)
        self._raise()

    def _plane_click(self, e):
        item = self.c.find_withtag("current")
        p = self._plane_map.get(item[0]) if item else None
        if p is not None:
            self.stop_tour()
            self.select("flug", p, fly=False)

    def _update_texts(self):
        c = self.c
        news = self.news or {}
        pts = self._points()
        if self.view == "leonberg":
            big, sub = f"{len(pts)}", f"MELDUNGEN AUS {self.home[2].upper()} UND UMGEBUNG"
        elif self.view == "deutschland":
            big, sub = f"{len(pts)}", "MELDUNGEN AUS DEUTSCHLAND"
        elif self.view == "welt":
            big, sub = (f"{len(pts)}", "BRENNPUNKTE WELTWEIT") if pts else ("…", "LADE NACHRICHTEN")
        else:
            big, sub = f"{len(self._all_planes())}", "FLUGZEUGE IN DER LUFT"
        st = time.strftime("%H:%M", time.localtime(news.get("zeit", time.time()))) if news else "--:--"
        status = f"Nachrichten von {st} Uhr · Zoom {self.z}"
        if self.view in ("luftraum", "leonberg") and self.status:
            status += " · " + self.status
        c.itemconfigure(self.t_big, text=big)
        c.itemconfigure(self.t_sub, text=sub)
        c.itemconfigure(self.t_status, text=status)
        c.itemconfigure(self.t_attr, text=SOURCES[self.style]["attr"])

    # --- Rechte Spalte ---
    def _panel_entries(self):
        t = self.theme
        news = self.news or {}
        out = []
        if self.view == "luftraum":
            hl, ho = self.home[0], self.home[1]
            near = sorted(self.planes_near, key=lambda p: pc_flights.distance_km(hl, ho, p["lat"], p["lon"]))[:25]
            for p in near:
                km = pc_flights.distance_km(hl, ho, p["lat"], p["lon"])
                info = f"{km:.0f} km entfernt · {int(p['alt']):,} m · {int(p['speed'])} km/h".replace(",", ".")
                if p.get("type"):
                    info += f" · {p['type']}"
                out.append(("flug", p, p["call"] or p["id"], info, t["accent2"]))
            return out
        for q in self._points():
            col = KIND_COLORS.get(q.get("art")) or t["accent"]
            out.append(("punkt", q, q.get("titel", ""), f"{q.get('ort', '')} · {q.get('text', '')}", col))
        if self.view == "leonberg":  # lokale Schlagzeilen ohne Ort zusätzlich
            for it in (news.get("schlagzeilen") or []):
                if it.get("quelle", "").startswith("Lokal"):
                    out.append(("text", it, it["titel"], it.get("quelle", "").replace("Lokal", "Lokal ·").strip(" ·"),
                                t["dim"]))
        return out

    def _draw_panel(self):
        if not self.panel_w or self.win is None:
            return
        sel_id = id(self.selected[1]) if self.selected else None
        sig = (self.view, id(self.news), len(self.planes_near) // 5, self.size, self.theme_name, self.panel_scroll, sel_id)
        if sig == self._panel_sig:
            return
        self._panel_sig = sig
        c, t, s = self.c, self.theme, self.s
        c.delete("panel")
        W, H = self.size
        x0, y0, x1, y1 = W - self.panel_w, self.top_h, W, H
        c.create_rectangle(x0, y0, x1, y1, fill=hexc(t["panel"]), outline="", tags="panel")
        c.create_line(x0, y0, x0, y1, fill=hexc(mix(t["bg"], t["accent"], 0.5)), tags="panel")
        pad = int(20 * s)
        x, wrap = x0 + pad, int(x1 - x0 - 2 * pad)
        acc, txt, dim = hexc(t["accent"]), hexc(t["text"]), hexc(t["dim"])
        news = self.news or {}
        top_clip, bottom_clip = y0 + int(4 * s), y1 - int(6 * s)
        y = y0 + pad - self.panel_scroll

        def put(item, yy):
            bb = c.bbox(item)
            return bb[3] if bb else yy

        if self.view == "welt":
            heads = [("LAGEBERICHT", news.get("briefing") or "Lade Nachrichten …"), ("BRENNPUNKTE", None)]
        elif self.view == "leonberg":
            heads = [(f"{self.home[2].upper()} & UMGEBUNG", None)]
        elif self.view == "deutschland":
            heads = [("DEUTSCHLAND", None)]
        else:
            heads = [("IN DEINER NÄHE", f"Live-Flugzeuge rund um {self.home[2]}. Klick auf ein Flugzeug für Details.")]
        for head, body in heads:
            it = c.create_text(x, y, text=head, anchor="nw", fill=acc, font=self.f_head, tags="panel")
            y = put(it, y) + int(8 * s)
            if body:
                it = c.create_text(x, y, text=body, anchor="nw", fill=txt, font=self.f_text, width=wrap, tags="panel")
                y = put(it, y) + int(18 * s)
        entries = self._panel_entries()
        if not entries:
            it = c.create_text(x, y, text="Gerade nichts Passendes. Wechsle oben die Ansicht oder frag Jarvis nach der Lage.",
                               anchor="nw", fill=dim, font=self.f_text, width=wrap, tags="panel")
        for i, (kind, obj, title, sub, col) in enumerate(entries):
            tag = f"pe{i}"
            sel = self.selected is not None and self.selected[1] is obj
            ytop = y
            c.create_oval(x, y + 6 * s, x + 9 * s, y + 15 * s, fill=hexc(col), outline="", tags=("panel", tag))
            it = c.create_text(x + 18 * s, y, text=title, anchor="nw", fill=txt, font=self.f_item,
                               width=wrap - 18 * s, tags=("panel", tag))
            y = put(it, y) + int(3 * s)
            sub_short = sub if len(sub) <= 150 else sub[:148].rsplit(" ", 1)[0] + " …"
            it2 = c.create_text(x + 18 * s, y, text=sub_short, anchor="nw", fill=dim, font=self.f_text,
                                width=wrap - 18 * s, tags=("panel", tag))
            y = put(it2, y) + int(16 * s)
            if sel:
                c.create_rectangle(x - 12 * s, ytop - 2 * s, x - 8 * s, y - 12 * s, fill=acc, outline="",
                                   tags=("panel", tag))
            if kind in ("punkt", "flug"):
                c.tag_bind(tag, "<Button-1>", lambda e, kind=kind, obj=obj: (self.stop_tour(), self.select(kind, obj)))
                self._hand(tag)
            elif kind == "text" and obj.get("link"):
                c.tag_bind(tag, "<Button-1>", lambda e, u=obj["link"]: webbrowser.open(u))
                self._hand(tag)
            if ytop < top_clip or y > bottom_clip:
                c.delete(tag)
            if ytop > bottom_clip:
                break
        first = c.find_withtag("panel")
        for item in first[2:]:  # Überschriften, die aus dem Bereich gescrollt sind
            bb = c.bbox(item)
            if bb and (bb[1] < top_clip or bb[3] > bottom_clip):
                c.delete(item)
        self._raise()

    # --- Detailkarte links ---
    def _load_image(self, url):
        if url in self._imgs:
            return
        self._imgs[url] = None

        def run():
            try:
                import hashlib

                path = os.path.join(_base_folder("bilder"), hashlib.sha1(url.encode()).hexdigest()[:20] + ".img")
                if not os.path.exists(path):
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Jarvis"})
                    with urllib.request.urlopen(req, timeout=15) as r:
                        data = r.read()
                    with open(path, "wb") as f:
                        f.write(data)
                im = Image.open(path).convert("RGB")
                im.thumbnail((900, 600))
                self._imgs[url] = im
                self._card_sig = None
            except Exception as e:
                print(f"Bild nicht geladen: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _draw_card(self):
        if self.win is None:
            return
        sel = self.selected
        img = self._imgs.get(sel[1].get("bild")) if sel and sel[0] == "punkt" and sel[1].get("bild") else None
        sig = (id(sel[1]) if sel else None, self.size, self.theme_name, id(img))
        if sig == self._card_sig:
            return
        self._card_sig = sig
        c, t, s = self.c, self.theme, self.s
        c.delete("card")
        if not sel:
            return
        kind, obj = sel
        W, H = self.size
        cw = int(min(380 * s, (W - self.panel_w) * 0.36))
        x0, y0 = int(20 * s), self.top_h + int(104 * s)
        pad = int(16 * s)
        acc, txt, dim = hexc(t["accent"]), hexc(t["text"]), hexc(t["dim"])
        y = y0 + pad
        photo = None
        if img is not None:
            iw = cw - 2 * pad
            ih = min(int(iw * img.height / max(1, img.width)), int(220 * s))
            photo = ImageTk.PhotoImage(img.resize((iw, ih), Image.BILINEAR))
            self._card_photo = photo
            y += ih + int(12 * s)
        items = []
        if kind == "punkt":
            col = KIND_COLORS.get(obj.get("art")) or t["accent"]
            items.append(((obj.get("art", "") or "").upper() + (" · " + obj["quelle"] if obj.get("quelle") else ""),
                          self.f_small, hexc(col)))
            items.append((obj.get("titel", ""), self.f_head, txt))
            items.append((obj.get("ort", ""), self.f_text, acc))
            items.append((obj.get("text", ""), self.f_text, txt))
            if obj.get("schlagzeile") and obj.get("schlagzeile") != obj.get("titel"):
                items.append(("„" + obj["schlagzeile"] + "“", self.f_text, dim))
        else:
            km = pc_flights.distance_km(self.home[0], self.home[1], obj["lat"], obj["lon"])
            items.append(("FLUGZEUG · LIVE", self.f_small, hexc(t["accent2"])))
            items.append((obj.get("call") or obj.get("id", ""), self.f_head, txt))
            items.append((f"{km:.0f} km von {self.home[2]} entfernt", self.f_text, acc))
            info = f"Höhe {int(obj['alt']):,} m · {int(obj['speed'])} km/h · Kurs {int(obj['track'])}°".replace(",", ".")
            if obj.get("type"):
                info += f"\nTyp {obj['type']}"
            if obj.get("land"):
                info += f"\nRegistriert in {obj['land']}"
            cs = (obj.get("call") or "").strip().upper()
            if cs in pc_flights._route_cache:  # Route (von -> nach) schon bekannt
                r = pc_flights._route_cache[cs] or {}
                if r.get("von") and r.get("nach"):
                    info = f"{r.get('airline', '')}\n{r['von']} → {r['nach']}\n".lstrip("\n") + info
            elif cs and not getattr(self, "_route_busy", None) == cs:
                self._route_busy = cs

                def fetch(cs=cs):
                    pc_flights.route(cs)
                    self._card_sig = None  # Karte beim nächsten Durchlauf mit Route neu zeichnen
                threading.Thread(target=fetch, daemon=True).start()
            items.append((info, self.f_text, txt))
        created = []
        for text, font, col in items:
            if not text:
                continue
            it = c.create_text(x0 + pad, y, text=text, anchor="nw", fill=col, font=font, width=cw - 2 * pad, tags="card")
            bb = c.bbox(it)
            y = (bb[3] if bb else y) + int(8 * s)
            created.append(it)
        if kind == "punkt" and obj.get("link"):
            c.create_text(x0 + pad, y + int(2 * s), text="Artikel öffnen  ↗", anchor="nw", fill=acc, font=self.f_item,
                          tags=("card", "card_link"))
            c.tag_bind("card_link", "<Button-1>", lambda e, u=obj["link"]: webbrowser.open(u))
            self._hand("card_link")
            y += int(30 * s)
        close = c.create_text(x0 + cw - pad, y0 + pad - 4 * s, text="✕", anchor="ne", fill=dim, font=self.f_btn,
                              tags=("card", "card_close"))
        c.tag_bind("card_close", "<Button-1>", lambda e: self._unselect())
        self._hand("card_close")
        y1 = min(H - int(40 * s), y + pad)
        bgimg = Image.new("RGBA", (cw, max(10, int(y1 - y0))), (0, 0, 0, 0))
        ImageDraw.Draw(bgimg).rounded_rectangle((0, 0, bgimg.width - 1, bgimg.height - 1), radius=int(14 * s),
                                                fill=t["panel"] + (240,), outline=mix(t["bg"], t["accent"], 0.55) + (255,),
                                                width=max(1, int(1.5 * s)))
        self._card_bg = ImageTk.PhotoImage(bgimg)
        bgi = c.create_image(x0, y0, anchor="nw", image=self._card_bg, tags="card")
        c.tag_lower(bgi, created[0] if created else close)
        if photo is not None:
            c.create_image(x0 + pad, y0 + pad, anchor="nw", image=photo, tags="card")
        self._raise()

    def _unselect(self):
        self.selected = None
        self._card_sig = self._panel_sig = None
        self._draw_overlays()
