"""
Neues HUD (wie am Handy): 3D-Kugel mit Gehirn, Nervenstrang, Satelliten-Globus mit echten Satelliten.

Es läuft als kleine Webseite in einem eigenen Fenster von Microsoft Edge (App-Modus, ohne Adressleiste) – Edge ist
auf jedem Windows dabei und zeichnet über die Grafikkarte, dadurch ist alles flüssig. Jarvis selbst (Sprache, Befehle,
Wave Link ...) bleibt unverändert; dieses Modul ist nur die Brücke:

- ein lokaler Server auf 127.0.0.1 (nur dieser PC) liefert die Seite aus dem Ordner pc_web
- /events schickt Zustände live an die Seite (hört zu, denkt nach, spricht, Text, Lautstärke, "Gehirn", Lage)
- /api/... beantwortet Fragen der Seite (Einstellungen, Zuhause, Termine, Leistung, Lage ...)

Ohne Edge (oder mit "HUD-Stil: Klassisch" in den Einstellungen) gibt es weiter das bisherige HUD.
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pc_apps import base_dir

TITLE = "Jarvis HUD"
NO_WINDOW = 0x08000000
SAT_IDS = {25544, 48274, 20580, 40697, 43013}   # ISS, Tiangong, Hubble, Sentinel-2A, NOAA-20


def web_dir() -> str:
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "pc_web")


def find_edge():
    cands = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        b = os.environ.get(env)
        if b:
            cands.append(os.path.join(b, "Microsoft", "Edge", "Application", "msedge.exe"))
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        b = os.environ.get(env)
        if b:
            cands.append(os.path.join(b, "Google", "Chrome", "Application", "chrome.exe"))
    return next((c for c in cands if os.path.exists(c)), None)


def available() -> bool:
    try:
        import pc_hudwin
        own = pc_hudwin.available()
    except Exception:
        own = False
    return (own or find_edge() is not None) and os.path.isdir(web_dir())


# --- kleine Helfer ----------------------------------------------------------------------------------------
_geo = {}


def geocode(q: str):
    q = (q or "").strip()
    if not q:
        return None
    if q.lower() in _geo:
        return _geo[q.lower()]
    hit = None
    try:
        import pc_news
        hit = pc_news.geocode_exact(q)
    except Exception:
        pass
    _geo[q.lower()] = hit
    return hit


def tle_text() -> str:
    """Bahndaten der Satelliten (zweimal am Tag frisch)."""
    path = os.path.join(base_dir(), "satelliten.tle")
    try:
        if time.time() - os.path.getmtime(path) < 12 * 3600:
            with open(path, encoding="utf-8") as f:
                return f.read()
    except Exception:
        pass
    got = {}
    for g in ("stations", "resource", "science"):
        try:
            req = urllib.request.Request(f"https://celestrak.org/NORAD/elements/gp.php?GROUP={g}&FORMAT=tle", headers={"User-Agent": "Jarvis-PC"})
            lines = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace").replace("\r", "").splitlines()
            for i in range(len(lines) - 2):
                if lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
                    sid = int(lines[i + 1][2:7].strip() or 0)
                    if sid in SAT_IDS and sid not in got:
                        got[sid] = "\n".join((lines[i].strip(), lines[i + 1], lines[i + 2]))
        except Exception:
            pass
    for sid in SAT_IDS - set(got):
        try:
            req = urllib.request.Request(f"https://tle.ivanstanojevic.me/api/tle/{sid}", headers={"User-Agent": "Jarvis-PC"})
            o = json.loads(urllib.request.urlopen(req, timeout=10).read())
            got[sid] = "\n".join((o["name"], o["line1"], o["line2"]))
        except Exception:
            pass
    txt = "\n".join(got.values())
    if txt:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(txt)
        except Exception:
            pass
        return txt
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def think_for(text: str) -> list:
    """Welche "Hirnregionen" passen zu einem Befehl (für die Symbole in der Kugel)."""
    low = (text or "").lower()
    kinds = []
    for kind, words in (("videos", r"youtube|video|kanal|kanäle"), ("musik", r"musik|deezer|spotify|song|lied|lauter|leiser|wave ?link"),
                        ("web", r"such|google|internet|nachschauen|schau mal"), ("kalender", r"termin|kalender|morgen|heute an|wecker|timer|erinner"),
                        ("lage", r"lage|weltlage|wo ist|karte|flug"), ("nachrichten", r"nachricht|news|neues|lage"),
                        ("wetter", r"wetter|regen|temperatur|grad|sonne|schnee"), ("gedaechtnis", r"merk|weißt du|erinnerst|vergiss")):
        if re.search(words, low):
            kinds.append(kind)
    return kinds or ["gedaechtnis"]


# --- Taskleiste: das Edge-Fenster zu Jarvis zählen ----------------------------------------------------
APP_ID = "Jarvis.PCAssistent"


def set_app_id(hwnd):
    """Gibt dem Edge-Fenster die App-Kennung von Jarvis. Dann zeigt die Taskleiste das Jarvis-Symbol, und Anheften
    startet PC-Assistent.exe statt Edge. (SHGetPropertyStoreForWindow + IPropertyStore über ctypes.)"""
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

        def guid(s):
            import uuid
            u = uuid.UUID(s)
            g = GUID(u.time_low, u.time_mid, u.time_hi_version)
            g.d[:] = list(u.bytes[8:])
            return g

        class PKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

        class PROPVARIANT(ctypes.Structure):
            _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                        ("p", ctypes.c_void_p), ("p2", ctypes.c_void_p)]

        iid = guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")   # IID_IPropertyStore
        fmt = guid("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3")   # PKEY_AppUserModel_*
        store = ctypes.c_void_p()
        if ctypes.windll.shell32.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd), ctypes.byref(iid), ctypes.byref(store)) != 0:
            return False
        vtbl = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        SetValue = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PKEY), ctypes.POINTER(PROPVARIANT))(vtbl[6])
        Commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
        Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        keep = []

        def put(pid, text):
            buf = ctypes.create_unicode_buffer(text)
            keep.append(buf)
            pv = PROPVARIANT(31, 0, 0, 0, ctypes.cast(buf, ctypes.c_void_p), None)   # VT_LPWSTR
            SetValue(store, ctypes.byref(PKEY(fmt, pid)), ctypes.byref(pv))

        if getattr(sys, "frozen", False):
            put(2, f'"{sys.executable}"')          # RelaunchCommand: Klick aufs angeheftete Symbol startet Jarvis
            put(3, f"{sys.executable},0")           # RelaunchIconResource
            put(4, "Jarvis")                        # RelaunchDisplayNameResource
        put(5, APP_ID)                              # AppUserModel_ID (zuletzt)
        Commit(store)
        Release(store)
        return True
    except Exception as e:
        print(f"Taskleisten-Kennung ging nicht: {e}")
        return False


# --- Server -----------------------------------------------------------------------------------------------
class WebHud:
    def __init__(self, ui, run_text):
        self.ui = ui                 # pc_overlay.UI (für Einstellungen, Tk-Warteschlange)
        self.run_text = run_text     # führt einen Text als Befehl aus
        self.clients = []            # Warteschlangen der offenen Seiten
        self.proc = None
        self.port = 0
        self.lage = None
        self._tour = []
        self.open_on_connect = False   # Einstellungen öffnen, sobald die Seite da ist
        self._lock = threading.Lock()
        self._start_server()
        threading.Thread(target=self._levels, daemon=True).start()
        try:
            import pc_handy
            pc_handy.ON_STATUS = lambda d: self.push("phone", {"status": d, "age": 0})
        except Exception:
            pass

    # Ereignisse an alle offenen Seiten
    def push(self, kind: str, data=None):
        msg = json.dumps({"type": kind, "data": data if data is not None else {}}, ensure_ascii=False)
        with self._lock:
            for q in list(self.clients):
                try:
                    q.put_nowait(msg)
                except Exception:
                    pass

    def _levels(self):
        """Lautstärke (Mikrofon, Stimme) an die Kugel – nur wenn eine Seite offen ist."""
        last = -1.0
        while True:
            time.sleep(0.08)
            if not self.clients:
                continue
            try:
                import pc_sphere
                v = round(float(pc_sphere.level()), 2)
            except Exception:
                v = 0.0
            if abs(v - last) >= 0.03:
                last = v
                self.push("level", {"value": v})

    def _start_server(self):
        hud = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json; charset=utf-8"):
                b = body if isinstance(body, bytes) else body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                qs = dict(urllib.parse.parse_qsl(u.query))
                if u.path == "/events":
                    return hud._events(self)
                if u.path == "/phonecam.jpg":   # Bild der Handy-Kamera (kommt über den Fernzugriff)
                    import pc_fern
                    return self._send(200, pc_fern.PHONE_FRAME["jpg"], "image/jpeg")
                if u.path.startswith("/api/"):
                    try:
                        return self._send(200, json.dumps(hud.api(u.path[5:], qs), ensure_ascii=False))
                    except Exception as e:
                        return self._send(500, json.dumps({"error": str(e)}))
                path = os.path.normpath(os.path.join(web_dir(), (u.path.lstrip("/") or "hud.html")))
                if not path.startswith(os.path.normpath(web_dir())) or not os.path.isfile(path):
                    return self._send(404, "nicht gefunden", "text/plain")
                ext = os.path.splitext(path)[1].lower()
                ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                         ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"}.get(ext, "application/octet-stream")
                with open(path, "rb") as f:
                    self._send(200, f.read(), ctype)

            def do_POST(self):
                u = urllib.parse.urlparse(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    body = {}
                try:
                    return self._send(200, json.dumps(hud.action(u.path[5:], body) or {}, ensure_ascii=False))
                except Exception as e:
                    return self._send(500, json.dumps({"error": str(e)}))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _events(self, h):
        q = queue.Queue(maxsize=500)
        with self._lock:
            self.clients.append(q)
        if self.open_on_connect:
            self.open_on_connect = False
            q.put_nowait(json.dumps({"type": "open_settings", "data": {}}))
        try:
            h.send_response(200)
            h.send_header("Content-Type", "text/event-stream")
            h.send_header("Cache-Control", "no-store")
            h.end_headers()
            h.wfile.write(b": hallo\n\n")
            h.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                    h.wfile.write(("data: " + msg + "\n\n").encode("utf-8"))
                except queue.Empty:
                    h.wfile.write(b": ping\n\n")
                h.wfile.flush()
        except Exception:
            pass
        finally:
            with self._lock:
                if q in self.clients:
                    self.clients.remove(q)

    # --- Fragen der Seite --------------------------------------------------------------------------------
    def api(self, name: str, qs: dict):
        s = self.ui.settings
        if name == "settings":
            keys = ("assistant_name", "hud_mode", "hud_layout", "hud_buttons", "home_city", "lage_places", "lage_spin", "lage_orbits", "map_labels",
                    "lage_sat_tour", "globe_auto_open", "address_as")
            out = {k: s.get(k) for k in keys}
            out.update(lage_jump=s.get("globe_auto_open", True), lage_zoom=s.get("lage_sat_tour", True),
                       lage_labels=s.get("map_labels", True), strand=True, background=True)
            return out
        if name == "home":
            hit = (geocode(f"{s.get('home_address')}, {s.get('home_city')}") if s.get("home_address") else None) or geocode(s.get("home_city") or "Leonberg")
            return {"lat": hit[0], "lon": hit[1]} if hit else None
        if name == "tle":
            return {"text": tle_text()}
        if name == "phonecam":
            import pc_fern
            return {"live": time.time() - pc_fern.PHONE_FRAME["t"] < 4}
        if name == "syscheck":   # Statusseite: grüne/rote Punkte (frisch prüfen, wenn älter als 2 Min. oder ?neu=1)
            import pc_systemcheck
            if qs.get("neu") or time.time() - pc_systemcheck.LAST["t"] > 120:
                pc_systemcheck.run()
            return {"t": pc_systemcheck.LAST["t"], "items": pc_systemcheck.LAST["items"], "text": pc_systemcheck.summary()}
        if name == "ets2":   # Fahrtenseite (ETS2-Beifahrer)
            import pc_ets2
            return pc_ets2.STATE
        if name == "geocode":
            hit = geocode(qs.get("q", ""))
            return {"lat": hit[0], "lon": hit[1]} if hit else None
        if name == "favorites":
            return s.get("lage_places") or []
        if name == "city":
            return s.get("home_city") or "Leonberg"
        if name == "sys":
            return self._sys()
        if name == "termine":
            return self._termine()
        if name == "power":
            return {"on": not self.ui.sleeping()}
        if name == "phone":
            import pc_handy
            d = pc_handy.STATUS
            return {"paired": pc_handy.paired(), "status": d["data"], "age": int(time.time() - d["t"]) if d["t"] else None}
        if name == "settings_new":
            import pc_websettings
            return pc_websettings.unseen(s)
        if name == "settings_full":
            import pc_websettings
            return pc_websettings.schema(s)
        if name == "themen":
            import pc_themen
            return [t["name"] for t in pc_themen.all_topics(s)]
        return None

    def _sys(self):
        out = {}
        try:
            import psutil
            out.update(cpu=int(psutil.cpu_percent(interval=0.2)), ram=int(psutil.virtual_memory().percent),
                       ram_used=round(psutil.virtual_memory().used / 2**30, 1), ram_total=round(psutil.virtual_memory().total / 2**30))
        except Exception:
            pass
        try:
            import pc_remote
            g = pc_remote._gpu()
            if g:
                out["gpu"] = g
        except Exception:
            pass
        try:
            import pc_link
            out["handy"] = pc_link.STATUS or ""
            out["paired"] = True
        except Exception:
            pass
        return out

    def _termine(self):
        import datetime
        try:
            import pc_calendar
            now = datetime.datetime.now()
            evs = pc_calendar.events_between(now, now + datetime.timedelta(days=7))[:6]
            out = []
            for e in evs:
                st = e["start"]
                day = "heute" if st.date() == now.date() else "morgen" if st.date() == (now + datetime.timedelta(days=1)).date() else st.strftime("%a %d.%m.")
                out.append({"when": day + ("" if e.get("allday") else st.strftime(" %H:%M")), "title": str(e.get("summary") or "")[:40]})
            return out
        except Exception:
            return []

    # --- Aktionen der Seite ---------------------------------------------------------------------------------
    def action(self, name: str, body: dict):
        if name == "boot_done":   # Start-Animation: Gruß sprechen
            import pc_nachrichten, pc_talk
            bad = int(body.get("bad") or 0)
            who = getattr(pc_talk, "ADDRESS", "") or "Sir"
            t = f"Willkommen zurück, {who}. " + (f"{bad} System{'e brauchen' if bad > 1 else ' braucht'} Aufmerksamkeit – sag Statuscheck." if bad else "Alle Systeme bereit.")
            pc_nachrichten.incoming({"kind": "say", "force": True, "text": t})
            return {}
        if name == "boot_close":
            return {}
        if name == "cmd" and str(body.get("text") or "").strip():
            self.run_text(str(body["text"]).strip())
            return {"ok": True}
        if name == "ask" and str(body.get("text") or "").strip():   # getippt: still antworten (nur Text)
            self.run_text(str(body["text"]).strip()[:2000], True)
            return {"ok": True}
        if name == "mode":
            m = body.get("mode")
            if m == "flug":
                self.ui.q.put(("globe", "luftraum"))   # Flug-Modus gibt es (noch) im klassischen HUD
            elif m in ("fokus", "info", "lage", "steuern"):
                self.ui.post_setting("hud_mode", m)
            return {"ok": True}
        if name == "phone":   # Seite "Steuern": Handy fernsteuern
            threading.Thread(target=self._phone, args=(dict(body),), daemon=True).start()
            return {"ok": True}
        if name == "power":   # Schalter oben rechts: zuhören an/aus
            self.ui.q.put(("listen", bool(body.get("on"))))
            return {"ok": True}
        if name == "show":   # zweiter Start (z. B. über die Taskleiste)
            self.ui.q.put(("hud", "show"))
            return {"ok": True}
        if name == "settings":
            self.push("open_settings")
            return {"ok": True}
        if name == "settings_save":
            import pc_websettings
            self.ui.q.put(("apply", pc_websettings.save(self.ui.settings, body.get("values") or {})))
            return {"ok": True}
        if name == "settings_seen":   # Bereich angeschaut: Punkte weg
            keys = [str(k) for k in body.get("keys") or []]
            seen = list(self.ui.settings.get("seen_new") or [])
            add = [k for k in keys if k not in seen]
            if add:
                self.ui.post_setting("seen_new", seen + add)
            return {"ok": True}
        if name == "settings_run":
            import pc_websettings
            try:
                return pc_websettings.run(self.ui, str(body.get("name") or ""), body.get("values") or {})
            except Exception as e:
                return {"ok": False, "text": str(e)}
        if name == "getLage":
            threading.Thread(target=self._get_lage, args=(str(body.get("place") or ""), bool(body.get("force"))), daemon=True).start()
            return {"ok": True}
        if name == "note":
            return {"ok": True}
        return {"ok": False}

    def _phone(self, b: dict):
        import pc_handy
        op = b.get("op")
        try:
            if op == "refresh":
                if not pc_handy.refresh_status(bool(b.get("force"))):
                    self.push("phone_reply", {"ok": False, "text": "Dein Handy hat nicht geantwortet. Ist die Jarvis-App dort an (Schalter oben rechts)?"})
                return
            if op == "ctl":
                r = pc_handy.control(str(b.get("what")), **{k: v for k, v in b.items() if k not in ("op", "what")})
            elif op == "call":
                r = pc_handy.call(str(b.get("who") or ""))
            elif op == "media":
                r = {"ok": True, "text": pc_handy.send_media()}
            else:
                r = pc_handy.command(str(b.get("text") or ""))
        except Exception as e:
            r = {"ok": False, "text": f"Ging nicht: {e}"}
        self.push("phone_reply", r)

    def _get_lage(self, place: str, force: bool):
        import pc_news
        s = self.ui.settings
        try:
            if place == "@fuerdich":
                import pc_themen
                data = pc_themen.fuer_dich()
                if not data:
                    return self.push("lage_error", {"text": "Ich kenne deine Interessen noch nicht gut genug – trag in den Einstellungen unter Weltlage Themen ein oder frag mich einfach Dinge.", "ort": place})
            elif place:
                data = dict(pc_news.get_place(place))
            else:
                data = dict(pc_news.get(max_age=0 if force else pc_news.MAX_AGE) or {})
                if not data:
                    return self.push("lage_error", {"text": "Ich komme gerade an keine Nachrichten.", "ort": place})
                data["ort"] = s.get("home_city") or "Leonberg"
                hit = geocode(data["ort"])
                if hit:
                    data["lat"], data["lon"] = hit
            data["stadt"] = s.get("home_city") or "Leonberg"
            data.pop("schlagzeilen", None)
            if not place:
                self.lage = data
            self.push("lage", {"data": data, "tour": False})
        except Exception as e:
            self.push("lage_error", {"text": f"Lage nicht erreichbar ({e}).", "ort": place})

    # --- Lage-Tour beim Briefing --------------------------------------------------------------------------
    def tour(self, seconds: float):
        import pc_news
        data = self.lage or pc_news.get(wait=False)
        if not data:
            return
        data = dict(data)
        data.setdefault("stadt", self.ui.settings.get("home_city") or "Leonberg")
        data.pop("schlagzeilen", None)
        self.lage = data
        self.push("lage", {"data": data, "tour": True})
        pts = data.get("brennpunkte") or []
        idx = [i for i, p in enumerate(pts) if p.get("im_briefing")][:6] or list(range(min(5, len(pts))))
        for t in self._tour:
            t.cancel()
        self._tour, self._tour_idx, self._tour_done = [], idx, set()
        per = max(4.5, (seconds - 1.0) / max(1, len(idx)))
        for n, i in enumerate(idx):
            t = threading.Timer(2.5 + n * per, self._focus, args=(i, n + 1, len(idx)))
            t.daemon = True
            t.start()
            self._tour.append(t)
        end = threading.Timer(2.5 + len(idx) * per + 2, lambda: self.push("lage_focus", {"i": -1}))
        end.daemon = True
        end.start()
        self._tour.append(end)

    def _focus(self, i, n, of):
        if i in getattr(self, "_tour_done", set()):
            return
        self._tour_done.add(i)
        self.push("lage_focus", {"i": i, "n": n, "of": of})

    def on_text(self, text: str):
        """Jarvis spricht gerade diesen Satz: passt er zu einem Ort der Tour, dorthin fliegen."""
        if not self.lage or not getattr(self, "_tour_idx", None) or not text:
            return
        low = " " + re.sub(r"[^\wäöüß]+", " ", text.lower()) + " "
        pts = self.lage.get("brennpunkte") or []
        best, score = None, 0
        for i in self._tour_idx:
            p = pts[i]
            ort = str(p.get("ort") or "").lower().strip()
            sc = 4 if ort and (" " + ort + " ") in low else 0
            sc += sum(1 for w in re.findall(r"[\wäöüß]{5,}", (str(p.get("titel") or "") + " " + ort).lower()) if " " + w in low)
            if sc > score and i not in self._tour_done:
                best, score = i, sc
        if best is not None and score >= 2:
            self._focus(best, self._tour_idx.index(best) + 1, len(self._tour_idx))

    # --- Fenster --------------------------------------------------------------------------------------------
    def is_visible(self) -> bool:
        # Edge gibt den Start manchmal an einen schon laufenden Edge-Prozess ab, dann ist unser Prozess sofort weg,
        # das Fenster aber da. Darum zählt auch ein gefundenes Fenster.
        if self.proc is not None and self.proc.poll() is None:
            return True
        return bool(self._hwnd())

    def _hwnd(self):
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            found = []

            def cb(h, _):
                n = user32.GetWindowTextLengthW(h)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(h, buf, n + 1)
                    if buf.value.startswith(TITLE) and user32.IsWindowVisible(h):
                        found.append(h)
                return True
            user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
            return found[0] if found else None
        except Exception:
            return None

    def is_foreground(self) -> bool:
        if not self.is_visible():
            return False
        try:
            import ctypes
            return self._hwnd() == ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return False

    def show(self):
        if self.is_visible():
            h = self._hwnd()
            if not h and self.proc is not None and self.proc.poll() is None:
                return True   # Fenster ist gerade erst am Aufgehen – nicht noch eins starten
            if h:
                try:
                    import ctypes
                    if ctypes.windll.user32.IsIconic(h):
                        ctypes.windll.user32.ShowWindow(h, 9)   # nur wenn minimiert – Vollbild/maximiert bleibt so
                    ctypes.windll.user32.SetForegroundWindow(h)
                except Exception:
                    pass
            return True
        w = int(self.ui.settings.get("hud_width") or 1280)
        if not getattr(self, "_own_failed", False):
            try:
                import pc_hudwin
                if pc_hudwin.available():
                    # eigenes Fenster: zweiter Prozess derselben exe (gehört zu Jarvis, kein Edge)
                    me = [sys.executable] if getattr(sys, "frozen", False) else \
                        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pc_overlay.py")]
                    self.proc = subprocess.Popen(me + ["--hud", str(self.port), str(max(960, w)), str(int(max(960, w) * 0.62))],
                                                 creationflags=NO_WINDOW)
                    threading.Thread(target=self._watch_own, daemon=True).start()
                    return True
            except Exception as e:
                print(f"Eigenes HUD-Fenster ging nicht ({e}), nehme Edge.")
                self._own_failed = True
        return self._show_edge(w)

    def _watch_own(self):
        """Stürzt das eigene Fenster gleich am Anfang ab (z. B. WebView2 fehlt), einmalig auf Edge ausweichen."""
        p = self.proc
        t0 = time.time()
        while time.time() - t0 < 20:
            if p.poll() is not None:
                if p.returncode != 0 and not self._hwnd():
                    print(f"Eigenes HUD-Fenster beendet sich sofort (Code {p.returncode}), nehme Edge.")
                    self._own_failed = True
                    self._show_edge(int(self.ui.settings.get("hud_width") or 1280))
                return
            if self._hwnd():
                return
            time.sleep(0.3)

    def _show_edge(self, w):
        edge = find_edge()
        if not edge:
            return False
        prof = os.path.join(base_dir(), "hud_profil")
        self.proc = subprocess.Popen([edge, f"--app=http://127.0.0.1:{self.port}/hud.html", f"--user-data-dir={prof}",
                                      f"--window-size={max(960, w)},{int(max(960, w) * 0.62)}", "--no-first-run",
                                      "--no-default-browser-check", "--disable-features=Translate,msEdgeTranslate",
                                      "--autoplay-policy=no-user-gesture-required", "--force-dark-mode"], creationflags=NO_WINDOW)
        threading.Thread(target=self._color_caption, daemon=True).start()
        return True

    def _color_caption(self):
        """Titelleiste des Edge-Fensters (mit dem X) in den HUD-Farben: fast schwarz mit goldener Schrift und goldenem Rand."""
        for _ in range(60):   # das Fenster braucht ein paar Sekunden
            time.sleep(0.25)
            h = self._hwnd()
            if h:
                break
        else:
            return
        set_app_id(h)   # gehört in der Taskleiste zu Jarvis (eigenes Symbol, anheftbar) statt zu Edge
        try:
            import ctypes
            dwm = ctypes.windll.dwmapi
            dark = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(h, 20, ctypes.byref(dark), 4)
            for attr, rgb in ((35, (0x0a, 0x06, 0x02)), (36, (0xff, 0xd6, 0x78)), (34, (0x5a, 0x3e, 0x14))):
                v = ctypes.c_uint(rgb[0] | (rgb[1] << 8) | (rgb[2] << 16))   # 35 Leiste, 36 Schrift, 34 Rand
                dwm.DwmSetWindowAttribute(h, attr, ctypes.byref(v), 4)
        except Exception:
            pass

    def hide(self):
        h = self._hwnd()
        if h:
            try:
                import ctypes
                ctypes.windll.user32.PostMessageW(h, 0x0010, 0, 0)   # WM_CLOSE: Fenster sauber schließen
            except Exception:
                pass
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.proc = None
