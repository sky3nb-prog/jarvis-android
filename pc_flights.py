"""
Live-Flugdaten für den Luftraum-Globus. Öffentliche, kostenlose Quellen (ADS-B), kein Schlüssel nötig:
- airplanes.live / adsb.lol: alle Flugzeuge im Umkreis von bis zu 250 Seemeilen (ca. 460 km) um einen Punkt
- OpenSky Network: ein größeres Gebiet (z. B. ganz Europa); ohne Konto nur begrenzt oft, deshalb selten abgefragt

Jedes Flugzeug: {"id", "call", "lat", "lon", "alt" (m), "speed" (km/h), "track" (Grad), "type", "land"}
"""

import json
import math
import re
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 Jarvis", "Accept": "application/json"}


def _get(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _num(v, default=None):
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _from_adsbx(data: dict) -> list:
    out = []
    for a in data.get("ac") or data.get("aircraft") or []:
        lat, lon = _num(a.get("lat")), _num(a.get("lon"))
        if lat is None or lon is None:
            continue
        alt = a.get("alt_baro")
        if alt == "ground":
            continue
        alt_ft = _num(alt, _num(a.get("alt_geom"), 0.0))
        out.append({
            "id": str(a.get("hex", "")).lower(),
            "call": str(a.get("flight") or a.get("r") or a.get("hex") or "").strip(),
            "lat": lat, "lon": lon,
            "alt": (alt_ft or 0.0) * 0.3048,
            "speed": (_num(a.get("gs"), 0.0) or 0.0) * 1.852,
            "track": _num(a.get("track"), _num(a.get("true_heading"), 0.0)) or 0.0,
            "type": str(a.get("t") or ""),
            "desc": str(a.get("desc") or ""),  # z. B. "AIRBUS A-320neo"
            "op": str(a.get("ownOp") or ""),
            "land": "",
            "cat": str(a.get("category") or ""),  # A1 leicht ... A7 Hubschrauber
            "mil": bool(int(a.get("dbFlags") or 0) & 1),
        })
    return out


def around(lat: float, lon: float, radius_nm: int = 250) -> list:
    """Flugzeuge im Umkreis (bis 250 Seemeilen). Probiert mehrere kostenlose Dienste nacheinander."""
    radius_nm = max(10, min(250, int(radius_nm)))
    urls = [
        f"https://api.airplanes.live/v2/point/{lat:.4f}/{lon:.4f}/{radius_nm}",
        f"https://api.adsb.lol/v2/lat/{lat:.4f}/lon/{lon:.4f}/dist/{radius_nm}",
        f"https://api.adsb.lol/v2/point/{lat:.4f}/{lon:.4f}/{radius_nm}",
    ]
    last = None
    for url in urls:
        try:
            planes = _from_adsbx(_get(url))
            if planes or url == urls[-1]:
                return planes
        except Exception as e:
            last = e
    if last:
        raise last
    return []


def area(lamin: float, lomin: float, lamax: float, lomax: float) -> list:
    """Alle Flugzeuge in einem Rechteck (OpenSky, anonym). Bitte höchstens alle paar Minuten aufrufen."""
    url = (f"https://opensky-network.org/api/states/all?lamin={lamin:.2f}&lomin={lomin:.2f}"
           f"&lamax={lamax:.2f}&lomax={lomax:.2f}")
    data = _get(url, timeout=20)
    out = []
    for s in data.get("states") or []:
        try:
            lon, lat = _num(s[5]), _num(s[6])
            if lat is None or lon is None or s[8]:  # s[8] = am Boden
                continue
            out.append({
                "id": str(s[0]), "call": (s[1] or "").strip() or str(s[0]), "lat": lat, "lon": lon,
                "alt": _num(s[7], _num(s[13], 0.0)) or 0.0, "speed": (_num(s[9], 0.0) or 0.0) * 3.6,
                "track": _num(s[10], 0.0) or 0.0, "type": "", "land": s[2] or "",
            })
        except (IndexError, TypeError):
            continue
    return out


CARGO = ("FDX", "UPS", "GTI", "CLX", "BOX", "DHK", "DHX", "BCS", "ABW", "CKS", "MPH", "GEC", "CAO", "CKK", "SQC",
         "ICL", "TAY", "NCA", "AHK", "DAE", "MSX", "QTR", "ABR", "SWN", "ATN", "KAL", "CPA", "UAE", "ETD")
CARGO_STRICT = ("FDX", "UPS", "GTI", "CLX", "BOX", "DHK", "DHX", "BCS", "ABW", "CKS", "MPH", "GEC", "CAO", "CKK",
                "SQC", "ICL", "TAY", "NCA", "AHK", "DAE", "MSX", "ABR", "SWN", "ATN", "LCO", "RCF", "WGN", "EAT")
MILITARY = ("RCH", "GAF", "NATO", "RRR", "CFC", "IAM", "FAF", "BAF", "NAF", "PLF", "CTM", "ASY", "HKY", "DUKE",
            "LAGR", "HOMER", "FORTE", "JAKE", "NCHO", "SAM", "MMF", "SHF", "HUSAF", "AME", "GAM", "SPAR", "CNV", "TUAF")
KINDS = {"linie": "Linie", "fracht": "Fracht", "privat": "Privat", "militaer": "Militär"}


def kind(p: dict) -> str:
    """Grobe Einteilung: linie (Passagiere), fracht, privat (kleine Flugzeuge, Hubschrauber) oder militaer."""
    call = (p.get("call") or "").upper().replace(" ", "")
    if p.get("mil") or call.startswith(MILITARY):
        return "militaer"
    if call[:3] in CARGO_STRICT:
        return "fracht"
    cat = p.get("cat") or ""
    if cat in ("A1", "A7", "B1", "B4", "B6") or not re.match(r"^[A-Z]{3}\d", call):
        return "privat"  # leichte Flugzeuge, Hubschrauber, Segler oder Rufzeichen = Kennzeichen (D-EABC, N123AB)
    return "linie"


def distance_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


def move(p: dict, seconds: float) -> tuple:
    """Wo ist das Flugzeug nach `seconds` Sekunden, wenn es geradeaus weiterfliegt? (für flüssige Bewegung)"""
    d = p["speed"] / 3600.0 * seconds  # km
    if d <= 0:
        return p["lat"], p["lon"]
    t = math.radians(p["track"])
    lat = p["lat"] + (d * math.cos(t)) / 111.2
    lon = p["lon"] + (d * math.sin(t)) / (111.2 * max(0.1, math.cos(math.radians(p["lat"]))))
    return lat, lon


_route_cache: dict = {}
_type_cache: dict = {}
DIRS = ["Norden", "Nordosten", "Osten", "Südosten", "Süden", "Südwesten", "Westen", "Nordwesten"]


def route(callsign: str):
    """Woher und wohin? (adsbdb.com, kostenlos, ohne Schlüssel) -> {"airline", "von", "nach"} oder None."""
    cs = (callsign or "").strip().upper()
    if not cs or not any(ch.isdigit() for ch in cs):
        return None
    if cs in _route_cache:
        return _route_cache[cs]
    out = None
    try:
        r = (_get(f"https://api.adsbdb.com/v0/callsign/{cs}", timeout=6).get("response") or {}).get("flightroute")
        if isinstance(r, dict):
            def place(a):
                a = a or {}
                return a.get("municipality") or a.get("name") or a.get("iata_code") or ""
            out = {"airline": ((r.get("airline") or {}).get("name") or ""), "von": place(r.get("origin")),
                   "nach": place(r.get("destination"))}
    except Exception:
        out = None
    _route_cache[cs] = out
    return out


def aircraft(hex_id: str) -> str:
    """Flugzeugtyp im Klartext, z. B. "Airbus A320neo" (adsbdb.com)."""
    if not hex_id:
        return ""
    if hex_id in _type_cache:
        return _type_cache[hex_id]
    name = ""
    try:
        a = (_get(f"https://api.adsbdb.com/v0/aircraft/{hex_id}", timeout=6).get("response") or {}).get("aircraft")
        if isinstance(a, dict):
            maker, typ = (a.get("manufacturer") or "").strip(), (a.get("type") or "").strip()
            typ = re.sub(r"(\d)-\w+$", r"\1", typ)  # "A320-271N" -> "A320"
            maker = maker.split()[0].title() if maker else ""
            name = typ if maker and typ.lower().startswith(maker.lower()) else f"{maker} {typ}".strip()
    except Exception:
        name = ""
    _type_cache[hex_id] = name
    return name


def _nice_type(p: dict) -> str:
    t = aircraft(p.get("id", "")) or p.get("desc", "").title() or p.get("type", "")
    return t.replace("-", " ")


def describe(p: dict, home_lat: float, home_lon: float) -> str:
    """Ein Satz zu einem Flugzeug: Airline, Typ, von wo nach wo, Höhe, Richtung, Entfernung."""
    km = distance_km(home_lat, home_lon, p["lat"], p["lon"])
    r = route(p["call"]) or {}
    typ = _nice_type(p)
    who = r.get("airline") or p.get("op", "").title()
    call = p["call"] or "ein Flugzeug"
    num = re.sub(r"^[A-Z]{2,3}", "", call) if who else ""
    head = f"{who} Flug {num}" if who and num and num != call else (f"{who} {call}".strip() if who else call)
    if typ:
        head += f", eine {typ}"
    if r.get("von") and r.get("nach"):
        head += f", von {r['von']} nach {r['nach']}"
    alt = int(round(p["alt"] / 100.0) * 100)
    where = "" if km < 4 else f", {km:.0f} Kilometer entfernt"
    return f"{head}{where} in {alt} Metern Höhe, Richtung {DIRS[int((p['track'] % 360 + 22.5) // 45) % 8]}"


def summary(planes: list, home_lat: float, home_lon: float) -> str:
    """Gesprochen: welche Flugzeuge gerade über dir sind, mit Airline, Typ und Route."""
    if not planes:
        return "Gerade empfange ich keine Flugzeuge in deiner Nähe."
    near = sorted(planes, key=lambda p: distance_km(home_lat, home_lon, p["lat"], p["lon"]))
    n30 = [p for p in near if distance_km(home_lat, home_lon, p["lat"], p["lon"]) <= 30 and p["alt"] > 300]
    top = (n30 or near)[:3]
    first = describe(top[0], home_lat, home_lon)
    text = ("Über dir fliegt gerade " if distance_km(home_lat, home_lon, top[0]["lat"], top[0]["lon"]) < 15
            else "Das nächste Flugzeug ist ") + first + ". "
    if len(top) > 1:
        text += "Außerdem " + " und ".join(describe(p, home_lat, home_lon) for p in top[1:]) + ". "
    text += f"Insgesamt sind {len(n30)} Flugzeuge im Umkreis von 30 Kilometern und {len(planes)} im weiteren Umkreis."
    return text
