"""
Routen für Jarvis: "Wie lange brauche ich mit dem Fahrrad nach Rutesheim?"

- Start: dein aktueller Standort vom Handy (siehe pc_phone.py), sonst deine Adresse aus den Einstellungen, sonst dein Ort.
  "von meiner Adresse nach ...", "von Stuttgart nach ..." geht auch.
- Er rechnet bis zu drei Wege (OpenStreetMap-Routing, kostenlos, ohne Schlüssel) und sagt dir den schnellsten,
  den flachsten (Höhenmeter von Open-Meteo) und den kürzesten.
- "Schick mir den flachsten" -> der Weg kommt als Nachricht aufs Handy (ntfy) mit Link zu Google Maps.
- Fahrrad, zu Fuß oder Auto (ohne Angabe: Auto).
"""

import difflib
import json
import math
import re
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "Jarvis-PC-Assistent/1.0 (privat)"}
PROFILES = {"bike": ("routed-bike", "mit dem Fahrrad", "bicycling"),
            "foot": ("routed-foot", "zu Fuß", "walking"),
            "car": ("routed-car", "mit dem Auto", "driving")}
HOME_ADDRESS = ""  # aus den Einstellungen
HOME_CITY = "Leonberg"
_pending = {"routes": None, "until": 0.0, "dest": "", "mode": "car"}
SEND_ENABLED = False  # "aufs Handy schicken" ist vorerst aus (kommt mit dem Telefon-Projekt zurück)
ON_SHOW = None  # Programm setzt das: ON_SHOW(routes, index) zeigt die Wege auf der Karte

ASK = re.compile(r"(?:wie\s+(?:lange|weit)|route|wege?\b|wie\s+komme\s+ich|navigier\w*|fahrzeit|wie\s+viele?\s+minuten)"
                 r".*?\bnach\s+(.+)$", re.I)
FROM = re.compile(r"\bvon\s+(.+?)\s+(?:aus\s+)?nach\b", re.I)
MODE_WORDS = [("bike", r"fahrrad|\brad\b|radl|bike|velo|radeln"), ("foot", r"zu fuß|\bfuß\b|laufen|gehen|spazier|wandern"),
              ("car", r"\bauto\b|\bwagen\b|mit dem car")]


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


# --- Orte finden ---------------------------------------------------------------------------
def geocode(text: str, near=None):
    """Adresse oder Ort -> (lat, lon, Name). Bevorzugt Treffer in der Nähe."""
    q = text.strip(" .,!?")
    params = {"q": q, "format": "json", "limit": 5, "addressdetails": 0, "accept-language": "de"}
    if near:
        lat, lon = near
        params["viewbox"] = f"{lon - 1.5},{lat + 1.0},{lon + 1.5},{lat - 1.0}"
    try:
        res = _get("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params))
        if res:
            r = res[0]
            return float(r["lat"]), float(r["lon"]), r.get("display_name", q).split(",")[0]
    except Exception as e:
        print(f"Ort {q} nicht gefunden: {e}")
    try:  # verhört? ("Rotesheim" -> Rutesheim): mit bekannten Orten vergleichen
        import pc_news

        hit = difflib.get_close_matches(q.lower(), list(pc_news.PLACES), n=1, cutoff=0.75)
        if hit:
            return pc_news.PLACES[hit[0]]
        import pc_info

        lat, lon, name = pc_info.geocode(q)
        return float(lat), float(lon), name
    except Exception:
        return None


def home():
    if HOME_ADDRESS.strip():
        hit = geocode(HOME_ADDRESS)
        if hit:
            return hit[0], hit[1], "deiner Adresse"
    try:
        import pc_memory

        addr = " ".join(x for x in (pc_memory.profile("adresse"), pc_memory.profile("plz"), pc_memory.profile("ort")) if x)
        if addr.strip():
            hit = geocode(addr)
            if hit:
                return hit[0], hit[1], "deiner Adresse"
    except Exception:
        pass
    hit = geocode(HOME_CITY or "Leonberg")
    return (hit[0], hit[1], HOME_CITY) if hit else (48.8003, 9.0144, "Leonberg")


def here():
    """Wo bist du gerade? Handy-Standort (höchstens 30 Minuten alt), sonst Zuhause."""
    try:
        import pc_phone

        loc = pc_phone.location(max_age=1800)
        if loc:
            return loc[0], loc[1], "deinem Standort"
    except Exception:
        pass
    return home()


# --- Wege rechnen -----------------------------------------------------------------------
def _climb(coords) -> int:
    """Höhenmeter bergauf entlang des Weges (bis 100 Punkte, Open-Meteo)."""
    if len(coords) < 2:
        return 0
    step = max(1, len(coords) // 90)
    pts = coords[::step][:100]
    try:
        url = "https://api.open-meteo.com/v1/elevation?" + urllib.parse.urlencode(
            {"latitude": ",".join(f"{p[1]:.5f}" for p in pts), "longitude": ",".join(f"{p[0]:.5f}" for p in pts)})
        el = _get(url).get("elevation") or []
        return int(sum(max(0.0, b - a) for a, b in zip(el, el[1:])))
    except Exception:
        return -1


def routes(a, b, mode="car") -> list:
    """Bis zu drei Wege: [{"min", "km", "hm", "coords" [(lon, lat)], "label"}]."""
    prof = PROFILES.get(mode, PROFILES["car"])[0]
    url = (f"https://routing.openstreetmap.de/{prof}/route/v1/driving/{a[1]:.6f},{a[0]:.6f};{b[1]:.6f},{b[0]:.6f}"
           "?alternatives=3&overview=full&geometries=geojson&steps=false")
    data = _get(url, timeout=20)
    out = []
    for r in (data.get("routes") or [])[:3]:
        coords = r["geometry"]["coordinates"]
        out.append({"min": r["duration"] / 60.0, "km": r["distance"] / 1000.0, "coords": coords,
                    "hm": _climb(coords) if mode != "car" else 0})
    if not out:
        return out
    labels = {}
    labels.setdefault(min(range(len(out)), key=lambda i: out[i]["min"]), "schnellste")
    if mode != "car" and len(out) > 1:
        i = min(range(len(out)), key=lambda i: (out[i]["hm"] if out[i]["hm"] >= 0 else 9e9, out[i]["min"]))
        labels.setdefault(i, "flachste")
    i = min(range(len(out)), key=lambda i: out[i]["km"])
    labels.setdefault(i, "kürzeste")
    for i, r in enumerate(out):
        r["label"] = labels.get(i, "alternative")
    order = {"schnellste": 0, "flachste": 1, "kürzeste": 2}
    out.sort(key=lambda r: order.get(r["label"], 3))
    return out


def _dur(m: float) -> str:
    m = int(round(m))
    if m < 60:
        return f"{m} Minuten"
    return f"{m // 60} Stunde{'n' if m >= 120 else ''}" + (f" {m % 60} Minuten" if m % 60 else "")


def _km(k: float) -> str:
    return (f"{k:.1f}".replace(".", ",") if k < 20 else f"{k:.0f}") + " Kilometer"


def _name(r: dict) -> str:
    return "eine Alternative" if r["label"] == "alternative" else f"der {r['label']} Weg"


def maps_link(r: dict, a, b, mode: str) -> str:
    """Google-Maps-Link, der dem Weg folgt (3 Zwischenpunkte, mehr nimmt die Handy-App nicht)."""
    c = r["coords"]
    way = [c[int(len(c) * f)] for f in (0.25, 0.5, 0.75)] if len(c) > 8 else []
    p = {"api": 1, "origin": f"{a[0]:.6f},{a[1]:.6f}", "destination": f"{b[0]:.6f},{b[1]:.6f}",
         "travelmode": PROFILES.get(mode, PROFILES["car"])[2]}
    if way:
        p["waypoints"] = "|".join(f"{q[1]:.6f},{q[0]:.6f}" for q in way)
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(p)


# --- Sprache ----------------------------------------------------------------------------
def awaiting() -> bool:
    return _pending["routes"] is not None and time.time() < _pending["until"]


def _mode_of(low: str) -> str:
    for mode, pat in MODE_WORDS:
        if re.search(pat, low):
            return mode
    return "car"


def _clean_dest(text: str) -> str:
    text = re.sub(r"\s+(?:mit\s+(?:dem|der|meinem|meiner)?\s*\w+|zu fuß|per \w+|bitte|und zurück|fahren|laufen|gehen|"
                  r"radeln|brauche ich|komme ich)\b.*$", "", text.strip(" .,!?"), flags=re.I)
    return text.strip(" .,!?")


def _pick(low: str, rs: list):
    if re.search(r"\balle\b", low):
        return list(range(len(rs)))
    for i, r in enumerate(rs):
        if r["label"].rstrip("e") in low:  # "schnellsten", "flachsten", "kürzesten", "alternative"
            return [i]
        if r["label"] == "alternative" and re.search(r"andere|alternativ", low):
            return [i]
    for i, w in enumerate(("erst", "zweit", "dritt")):
        if w in low and i < len(rs):
            return [i]
    m = re.search(r"\b([123])\b", low)
    if m and int(m.group(1)) <= len(rs):
        return [int(m.group(1)) - 1]
    if re.search(r"(?:schick|send|handy|aufs telefon)", low):
        return [0]
    return None


def handle(text: str):
    low = text.lower().strip(" .,!?")
    if awaiting():
        if re.match(r"^(nein|nö|ne|lass|nicht nötig|brauch ich nicht)\b", low):
            _pending["routes"] = None
            return "Alles klar."
        idx = _pick(low, _pending["routes"])
        if idx is None and re.match(r"^(ja|jo|klar|gerne|bitte|mach|okay|ok)\b", low):
            idx = [0]
        if idx is not None:
            rs, a, b, mode = _pending["routes"], _pending["a"], _pending["b"], _pending["mode"]
            _pending["routes"] = None
            sent = []
            for i in idx:
                r = rs[i]
                title = f"{_name(r)[0].upper() + _name(r)[1:]} nach {_pending['dest']} ({_dur(r['min'])}, {_km(r['km'])})"
                body = f"{PROFILES[mode][1].capitalize()}: {_dur(r['min'])}, {_km(r['km'])}" + \
                       (f", {r['hm']} Höhenmeter bergauf" if r.get("hm", 0) > 0 else "") + ". Tippen öffnet Google Maps."
                try:
                    import pc_phone

                    ok = pc_phone.push(title, body, maps_link(r, a, b, mode))
                except Exception as e:
                    ok = False
                    print(f"Handy: {e}")
                if ON_SHOW:
                    ON_SHOW(rs, i, a, b)
                sent.append(ok)
            if not any(sent):
                return ("Ich kann dir noch nichts aufs Handy schicken. Richte das in den Einstellungen unter Handy ein, "
                        "das dauert zwei Minuten.")
            return "Ist auf deinem Handy. Gute Fahrt." if len(idx) == 1 else "Alle Wege sind auf deinem Handy."
    m = ASK.search(text)
    if not m:
        return None
    dest_txt = _clean_dest(m.group(1))
    if not dest_txt:
        return None
    mode = _mode_of(low)
    fm = FROM.search(text)
    if fm:
        src = fm.group(1).strip().lower()
        if re.search(r"meine[rm]? (adresse|wohnung|haus)|zu ?hause|daheim", src):
            a = home()
        elif re.search(r"\bhier\b|mir\b|meinem standort", src):
            a = here()
        else:
            hit = geocode(fm.group(1))
            if not hit:
                return f"{fm.group(1)} finde ich nicht."
            a = hit
    else:
        a = here()
    b = geocode(dest_txt, near=(a[0], a[1]))
    if not b:
        return f"{dest_txt} finde ich nicht. Sag es nochmal etwas genauer, zum Beispiel mit Straße."
    try:
        rs = routes(a, b, mode)
    except Exception as e:
        return f"Die Routenplanung ist gerade nicht erreichbar ({str(e)[:60]})."
    if not rs:
        return f"Ich finde keinen Weg nach {b[2]}."
    if SEND_ENABLED:
        _pending.update(routes=rs, until=time.time() + 120, dest=b[2], mode=mode, a=a, b=b)
    ask = " Welchen soll ich dir aufs Handy schicken?" if SEND_ENABLED else " Ich zeige dir die Wege auf der Karte."
    ask1 = " Soll ich dir den Weg aufs Handy schicken?" if SEND_ENABLED else ""
    if ON_SHOW:
        ON_SHOW(rs, None, a, b)
    how = PROFILES[mode][1]
    start = f" von {a[2]}" if a[2] else ""
    if len(rs) == 1:
        r = rs[0]
        return (f"Nach {b[2]}{start} {how}: {_dur(r['min'])}, {_km(r['km'])}" +
                (f", {r['hm']} Höhenmeter bergauf" if r["hm"] > 0 else "") + "." + ask1)
    parts = []
    for r in rs:
        extra = f", {r['hm']} Höhenmeter" if r["hm"] > 0 else ""
        parts.append(f"{_name(r)}: {_dur(r['min'])} bei {_km(r['km'])}{extra}")
    return (f"Nach {b[2]}{start} {how} gibt es {len(rs)} Wege: " + "; ".join(parts) +
            "." + ask)
