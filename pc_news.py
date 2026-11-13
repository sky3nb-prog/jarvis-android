"""
Weltlage für Jarvis: holt aktuelle Nachrichten (tagesschau, Deutsche Welle, BBC) und macht daraus
- ein kurzes gesprochenes Lage-Briefing ("Jarvis, wie ist die Lage?" und beim Start)
- Brennpunkte mit Ort (Breiten- und Längengrad) für den Weltlage-Globus.

Mit Gemini-Schlüssel fasst Gemini die Lage zusammen und ordnet jeder Meldung einen Ort zu.
Ohne Schlüssel gibt es die Schlagzeilen, und die Orte werden über eine eingebaute Länderliste erkannt.
Alles wird 15 Minuten zwischengespeichert (auch in weltlage.json), damit es schnell geht.
"""

import html
import json
import os
import math
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

FEEDS = [
    ("tagesschau", "https://www.tagesschau.de/index~rss2.xml"),
    ("tagesschau Ausland", "https://www.tagesschau.de/ausland/index~rss2.xml"),
    ("DW", "https://rss.dw.com/xml/rss-de-all"),
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Google Top", "https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de"),  # die großen Themen des Tages
    ("Google Welt", "https://news.google.com/rss/headlines/section/topic/WORLD?hl=de&gl=DE&ceid=DE:de"),
]
# Lokale Suchen für Leonberg: Leonberger Kreiszeitung (heute bei der Stuttgarter Zeitung), Verkehr, Blaulicht, Umland
LOCAL_LEONBERG = [
    ("Lokal Leonberg", "Leonberg"),
    ("Lokal Kreiszeitung", "site:stuttgarter-zeitung.de Leonberg"),
    ("Lokal Verkehr", "Engelbergtunnel OR \"Leonberger Dreieck\" OR \"A8 Leonberg\" OR \"A81 Leonberg\" OR \"Leonberg Sperrung\""),
    ("Lokal Blaulicht", "Leonberg Polizei OR Feuerwehr OR Unfall"),
    ("Lokal Umland", "Renningen OR Rutesheim OR Ditzingen OR Gerlingen OR \"Weil der Stadt\" OR Weissach"),
    ("Lokal Landkreis", "\"Landkreis Böblingen\""),
]
MAX_AGE = 60 * 60  # Nachrichten höchstens stündlich neu zusammenfassen (schont das kostenlose Kontingent)
_last_fail = {"t": 0.0}
_last_try = {"t": 0.0}
_lock = threading.Lock()
_cache = {"ts": 0.0, "data": None}
_busy = threading.Lock()

# Eingebaute Orte für die Erkennung ohne KI: Name (klein, Wortanfang) -> (Breite, Länge, Anzeigename)
PLACES = {
    "leonberg": (48.8003, 9.0144, "Leonberg"), "eltingen": (48.7976, 9.0021, "Leonberg-Eltingen"),
    "höfingen": (48.8235, 8.9913, "Leonberg-Höfingen"), "warmbronn": (48.7712, 8.9738, "Leonberg-Warmbronn"),
    "gebersheim": (48.8297, 8.9655, "Leonberg-Gebersheim"), "renningen": (48.7656, 8.9381, "Renningen"),
    "rutesheim": (48.8085, 8.9452, "Rutesheim"), "ditzingen": (48.8264, 9.0668, "Ditzingen"),
    "gerlingen": (48.7999, 9.0631, "Gerlingen"), "weil der stadt": (48.7509, 8.8706, "Weil der Stadt"),
    "sindelfingen": (48.7133, 9.0028, "Sindelfingen"), "böblingen": (48.6856, 9.0153, "Böblingen"),
    "weissach": (48.8460, 8.9283, "Weissach"), "heimsheim": (48.8059, 8.8640, "Heimsheim"),
    "magstadt": (48.7428, 8.9653, "Magstadt"), "korntal": (48.8318, 9.1210, "Korntal-Münchingen"),
    "deutschland": (51.2, 10.4, "Deutschland"), "bundesregierung": (52.52, 13.40, "Berlin"),
    "berlin": (52.52, 13.40, "Berlin"), "hamburg": (53.55, 9.99, "Hamburg"), "münchen": (48.14, 11.58, "München"),
    "köln": (50.94, 6.96, "Köln"), "frankfurt": (50.11, 8.68, "Frankfurt"), "stuttgart": (48.78, 9.18, "Stuttgart"),
    "dresden": (51.05, 13.74, "Dresden"), "leipzig": (51.34, 12.37, "Leipzig"), "düsseldorf": (51.23, 6.77, "Düsseldorf"),
    "hannover": (52.37, 9.73, "Hannover"), "bremen": (53.08, 8.80, "Bremen"), "nürnberg": (49.45, 11.08, "Nürnberg"),
    "bayern": (48.9, 11.4, "Bayern"), "sachsen": (51.0, 13.3, "Sachsen"), "thüringen": (50.9, 11.0, "Thüringen"),
    "brandenburg": (52.4, 13.0, "Brandenburg"), "nrw": (51.5, 7.5, "NRW"), "nordrhein-westfalen": (51.5, 7.5, "NRW"),
    "baden-württemberg": (48.6, 9.0, "Baden-Württemberg"), "hessen": (50.6, 9.0, "Hessen"),
    "niedersachsen": (52.6, 9.8, "Niedersachsen"), "schleswig-holstein": (54.2, 9.8, "Schleswig-Holstein"),
    "mecklenburg": (53.6, 12.4, "Mecklenburg-Vorpommern"), "rheinland-pfalz": (49.9, 7.4, "Rheinland-Pfalz"),
    "saarland": (49.4, 6.9, "Saarland"), "sachsen-anhalt": (51.9, 11.7, "Sachsen-Anhalt"),
    "ukraine": (49.0, 31.4, "Ukraine"), "kiew": (50.45, 30.52, "Kiew"), "kyiv": (50.45, 30.52, "Kiew"),
    "russland": (55.75, 37.62, "Russland"), "russia": (55.75, 37.62, "Russland"), "moskau": (55.75, 37.62, "Moskau"),
    "kreml": (55.75, 37.62, "Moskau"), "israel": (31.8, 35.0, "Israel"), "gaza": (31.45, 34.4, "Gaza"),
    "westjordanland": (32.0, 35.25, "Westjordanland"), "libanon": (33.9, 35.8, "Libanon"), "lebanon": (33.9, 35.8, "Libanon"),
    "syrien": (35.0, 38.5, "Syrien"), "syria": (35.0, 38.5, "Syrien"), "iran": (32.4, 53.7, "Iran"),
    "irak": (33.3, 44.4, "Irak"), "iraq": (33.3, 44.4, "Irak"), "jemen": (15.6, 48.0, "Jemen"), "yemen": (15.6, 48.0, "Jemen"),
    "saudi": (24.7, 46.7, "Saudi-Arabien"), "türkei": (39.0, 35.2, "Türkei"), "turkey": (39.0, 35.2, "Türkei"),
    "ägypten": (30.0, 31.2, "Ägypten"), "egypt": (30.0, 31.2, "Ägypten"), "usa": (38.9, -77.04, "USA"),
    "washington": (38.9, -77.04, "Washington"), "weißen haus": (38.9, -77.04, "Washington"), "white house": (38.9, -77.04, "Washington"),
    "trump": (38.9, -77.04, "Washington"), "new york": (40.71, -74.0, "New York"), "kalifornien": (36.8, -119.4, "Kalifornien"),
    "california": (36.8, -119.4, "Kalifornien"), "texas": (31.0, -99.0, "Texas"), "florida": (27.8, -81.7, "Florida"),
    "kanada": (45.4, -75.7, "Kanada"), "canada": (45.4, -75.7, "Kanada"), "mexiko": (19.43, -99.13, "Mexiko"),
    "mexico": (19.43, -99.13, "Mexiko"), "brasilien": (-15.8, -47.9, "Brasilien"), "brazil": (-15.8, -47.9, "Brasilien"),
    "argentinien": (-34.6, -58.4, "Argentinien"), "venezuela": (10.5, -66.9, "Venezuela"), "kolumbien": (4.7, -74.1, "Kolumbien"),
    "chile": (-33.45, -70.67, "Chile"), "peru": (-12.05, -77.04, "Peru"), "kuba": (23.1, -82.4, "Kuba"),
    "china": (39.9, 116.4, "China"), "peking": (39.9, 116.4, "Peking"), "taiwan": (25.03, 121.56, "Taiwan"),
    "hongkong": (22.3, 114.17, "Hongkong"), "hong kong": (22.3, 114.17, "Hongkong"), "japan": (35.68, 139.69, "Japan"),
    "tokio": (35.68, 139.69, "Tokio"), "südkorea": (37.57, 126.98, "Südkorea"), "nordkorea": (39.03, 125.75, "Nordkorea"),
    "north korea": (39.03, 125.75, "Nordkorea"), "south korea": (37.57, 126.98, "Südkorea"), "indien": (28.6, 77.2, "Indien"),
    "india": (28.6, 77.2, "Indien"), "pakistan": (33.7, 73.1, "Pakistan"), "afghanistan": (34.5, 69.2, "Afghanistan"),
    "bangladesch": (23.8, 90.4, "Bangladesch"), "indonesien": (-6.2, 106.8, "Indonesien"), "philippinen": (14.6, 121.0, "Philippinen"),
    "vietnam": (21.03, 105.85, "Vietnam"), "thailand": (13.75, 100.5, "Thailand"), "myanmar": (19.75, 96.1, "Myanmar"),
    "australien": (-35.3, 149.1, "Australien"), "australia": (-35.3, 149.1, "Australien"), "neuseeland": (-41.3, 174.8, "Neuseeland"),
    "frankreich": (48.86, 2.35, "Frankreich"), "france": (48.86, 2.35, "Frankreich"), "paris": (48.86, 2.35, "Paris"),
    "großbritannien": (51.5, -0.13, "Großbritannien"), "london": (51.5, -0.13, "London"), "britain": (51.5, -0.13, "Großbritannien"),
    "uk": (51.5, -0.13, "Großbritannien"), "irland": (53.35, -6.26, "Irland"), "spanien": (40.42, -3.7, "Spanien"),
    "spain": (40.42, -3.7, "Spanien"), "portugal": (38.72, -9.14, "Portugal"), "italien": (41.9, 12.5, "Italien"),
    "italy": (41.9, 12.5, "Italien"), "rom": (41.9, 12.5, "Rom"), "vatikan": (41.9, 12.45, "Vatikan"), "papst": (41.9, 12.45, "Vatikan"),
    "österreich": (48.2, 16.37, "Österreich"), "wien": (48.2, 16.37, "Wien"), "schweiz": (46.95, 7.45, "Schweiz"),
    "niederlande": (52.37, 4.9, "Niederlande"), "belgien": (50.85, 4.35, "Belgien"), "brüssel": (50.85, 4.35, "Brüssel"),
    "eu-kommission": (50.85, 4.35, "Brüssel"), "nato": (50.88, 4.42, "Brüssel"), "polen": (52.23, 21.01, "Polen"),
    "poland": (52.23, 21.01, "Polen"), "tschechien": (50.08, 14.44, "Tschechien"), "ungarn": (47.5, 19.04, "Ungarn"),
    "rumänien": (44.43, 26.1, "Rumänien"), "bulgarien": (42.7, 23.32, "Bulgarien"), "griechenland": (37.98, 23.73, "Griechenland"),
    "serbien": (44.8, 20.47, "Serbien"), "kosovo": (42.66, 21.17, "Kosovo"), "dänemark": (55.68, 12.57, "Dänemark"),
    "grönland": (64.18, -51.7, "Grönland"), "greenland": (64.18, -51.7, "Grönland"), "schweden": (59.33, 18.07, "Schweden"),
    "norwegen": (59.91, 10.75, "Norwegen"), "finnland": (60.17, 24.94, "Finnland"), "baltikum": (56.9, 24.1, "Baltikum"),
    "litauen": (54.69, 25.28, "Litauen"), "lettland": (56.95, 24.1, "Lettland"), "estland": (59.44, 24.75, "Estland"),
    "belarus": (53.9, 27.57, "Belarus"), "moldau": (47.0, 28.86, "Moldau"), "georgien": (41.7, 44.8, "Georgien"),
    "armenien": (40.18, 44.51, "Armenien"), "aserbaidschan": (40.41, 49.87, "Aserbaidschan"), "sudan": (15.5, 32.56, "Sudan"),
    "äthiopien": (9.03, 38.74, "Äthiopien"), "somalia": (2.05, 45.32, "Somalia"), "kenia": (-1.29, 36.82, "Kenia"),
    "nigeria": (9.06, 7.49, "Nigeria"), "kongo": (-4.32, 15.31, "Kongo"), "südafrika": (-25.75, 28.19, "Südafrika"),
    "mali": (12.64, -8.0, "Mali"), "niger": (13.51, 2.11, "Niger"), "libyen": (32.89, 13.19, "Libyen"),
    "tunesien": (36.8, 10.18, "Tunesien"), "algerien": (36.75, 3.06, "Algerien"), "marokko": (34.02, -6.83, "Marokko"),
}

GENAU_TEXT = """   "genau" (wie genau der Ort ist: "punkt" = ein bestimmtes Gebäude, Platz, Tunnel, Brücke, Bahnhof, Kreuzung oder
   Autobahnabschnitt; "strasse"; "stadtteil"; "stadt"; "region"; "land") und "suche" (der genaueste Ort aus der Meldung
   als Suchbegriff für eine Karte, immer mit Stadt, z. B. "Römerberg, Frankfurt am Main", "Engelbergtunnel, Leonberg",
   "Hauptbahnhof, Stuttgart"; bei Ländern nur das Land). Nimm den genauesten Ort, den die Meldung hergibt."""

PROMPT = """Du bist der Lage-Analyst von J.A.R.V.I.S. Unten stehen nummerierte Schlagzeilen (#Nummer [Quelle] Titel: Text).
Meldungen mit [Lokal ...] stammen aus dem Wohnort des Nutzers ({city}) und der Umgebung.
Erstelle:
1. "briefing": ein gesprochenes Lage-Briefing auf Deutsch, 4 bis 6 kurze Sätze, sachlich und neutral, wie ein Butler,
   der seinem Chef die Lage zusammenfasst. Erst das Wichtigste aus der Welt und Deutschland, dann ein bis zwei Sätze
   zu {city} ("Aus {city}: ..."), wenn es dort etwas Interessantes gibt. Keine Listen, keine Sonderzeichen, keine Wertungen.
2. "brennpunkte": die 8 bis 12 wichtigsten Meldungen aus Welt und Deutschland (die wirklich großen, weltbewegenden
   Ereignisse mit "wichtig" 3) UND zusätzlich bis zu 12 lokale Meldungen aus {city} und Umgebung (art "lokal").
   Bei den lokalen Meldungen sind Verkehr (Sperrungen, Tunnel, Baustellen, Stau), Blaulicht, Stadtpolitik und
   Veranstaltungen besonders interessant; Verkehrsmeldungen gehören auch ins Briefing. Doppelte Meldungen nur einmal.
   Zuerst die im Briefing erwähnten, in derselben Reihenfolge.
   Für jede: "nr" (Nummer der Schlagzeile), "titel" (höchstens 6 Wörter, Deutsch), "ort" (Stadt oder Land; bei lokalen
   Meldungen Ortsteil, Straße oder Gebäude, wenn bekannt), "lat", "lon" (Zahlen; bei lokalen Meldungen so genau wie
   möglich, z. B. der Ortsteil statt der Ortsmitte), "art" (eine von: konflikt, politik, wirtschaft, wetter, katastrophe,
   gesellschaft, sport, wissenschaft, lokal), "wichtig" (1 bis 3), "deutschland" (true, wenn der Ort in Deutschland
   liegt), "im_briefing" (true, wenn im Briefing erwähnt), "text" (zwei Sätze, worum es geht),
{GENAU}
Antworte NUR mit JSON: {{"briefing": "...", "brennpunkte": [ ... ]}}""".replace("{GENAU}", GENAU_TEXT)


def _base_dir() -> str:
    try:
        import pc_apps

        return pc_apps.base_dir()
    except Exception:
        return os.path.dirname(os.path.abspath(__file__))


def _file() -> str:
    return os.path.join(_base_dir(), "weltlage.json")


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return " ".join(text.split())


IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
SKIP_TITLE = re.compile(r"^(?:faq|liveblog|live|ticker|newsblog|podcast|video|kommentar)\b", re.I)


def _image_of(it) -> str:
    """Bild-Adresse einer Meldung (enclosure, media:content, media:thumbnail oder erstes <img> im Text)."""
    for child in it.iter():
        tag = child.tag.split("}")[-1]
        url = child.attrib.get("url", "")
        typ = child.attrib.get("type", "") or child.attrib.get("medium", "")
        if tag in ("enclosure", "content", "thumbnail") and url and (tag == "thumbnail" or "image" in typ or
                                                                       url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp"))):
            return url
    for child in it:
        m = IMG_RE.search(child.text or "")
        if m:
            return html.unescape(m.group(1))
    return ""


def parse_feed(raw: bytes, source: str, limit: int = 12) -> list:
    """RSS 2.0 und RDF (Deutsche Welle) -> [{"titel", "text", "quelle", "link", "bild"}]."""
    root = ET.fromstring(raw)
    items = [el for el in root.iter() if el.tag.split("}")[-1] == "item"]
    out = []
    for it in items[: limit * 2]:
        fields = {child.tag.split("}")[-1]: (child.text or "") for child in it}
        title = _clean(fields.get("title", ""))
        if not title:
            continue
        if source.startswith(("Lokal", "Google")):  # Google News hängt " - Zeitung" an
            title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title)
        out.append({"titel": title, "text": _clean(fields.get("description", ""))[:260], "quelle": source,
                    "link": fields.get("link", "").strip(), "bild": _image_of(it)})
        if len(out) >= limit:
            break
    return out


CITY = ""  # Wohnort (aus den Einstellungen) für lokale Meldungen


def fetch_headlines() -> list:
    found, seen = [], set()
    feeds = list(FEEDS)
    if CITY:
        if CITY.lower() == "leonberg":
            searches = list(LOCAL_LEONBERG) + [("Lokal Stuttgart", "Stuttgart")]
        else:
            searches = [(f"Lokal {CITY}", f'"{CITY}"' if " " in CITY else CITY)]
        for source, query in searches:
            q = urllib.parse.quote(query)
            feeds.append((source, f"https://news.google.com/rss/search?q={q}+when:2d&hl=de&gl=DE&ceid=DE:de"))
    results = {}

    def load(source, url):  # alle Quellen gleichzeitig laden, das geht viel schneller
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Jarvis"})
            with urllib.request.urlopen(req, timeout=8) as r:
                results[source] = parse_feed(r.read(), source, limit=8 if source.startswith(("Lokal", "Google")) else 10)
        except Exception as e:
            print(f"Nachrichten von {source} nicht erreichbar: {e}")
    threads = [threading.Thread(target=load, args=f, daemon=True) for f in feeds]
    for t in threads:
        t.start()
    for t in threads:
        t.join(12)
    for source, _ in feeds:  # Reihenfolge wie in der Liste
        for item in results.get(source, []):
            key = item["titel"].lower()[:60]
            if key not in seen:
                seen.add(key)
                found.append(item)
    return found


def locate(text: str):
    """Ort aus der eingebauten Liste, der im Text vorkommt (oder None)."""
    low = " " + text.lower() + " "
    best = None
    for name, (lat, lon, label) in PLACES.items():
        m = re.search(r"[\s(„\"'-]" + re.escape(name) + r"\w{0,3}[\s,.:;!?)“\"'-]", low)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), lat, lon, label)
    return best[1:] if best else None


def _fallback(items: list) -> dict:
    points = []
    for it in items:
        hit = locate(it["titel"] + " " + it["text"])
        if hit and len(points) < 18:
            lat, lon, label = hit
            points.append({"titel": it["titel"][:60], "ort": label, "lat": lat, "lon": lon,
                           "art": "lokal" if it["quelle"].startswith("Lokal") else "politik",
                           "wichtig": 2, "deutschland": 47 <= lat <= 55.1 and 5.8 <= lon <= 15.1, "text": it["text"][:300],
                           "im_briefing": len(points) < 3, "link": it.get("link", ""), "bild": it.get("bild", ""),
                           "quelle": it.get("quelle", ""), "schlagzeile": it["titel"]})
    tops = [it["titel"].rstrip(".") for it in items if not SKIP_TITLE.match(it["titel"])
            and not it["quelle"].startswith("Lokal")][:3]
    briefing = ("Die wichtigsten Schlagzeilen: " + ". ".join(tops) + ".") if tops else ""
    return {"briefing": briefing, "brennpunkte": points}


def _ask_gemini(items: list):
    import pc_ai

    if not pc_ai.available():
        return None
    if time.time() - _last_fail["t"] < 20 * 60:  # gerade erst gescheitert: nicht gleich nochmal versuchen
        return None
    world = [it for it in items if not it["quelle"].startswith("Lokal")]
    local = [it for it in items if it["quelle"].startswith("Lokal")]
    use = world[:36] + local[:28]  # Lokales darf nicht hinten abgeschnitten werden
    lines = "\n".join(f"#{i} [{it['quelle']}] {it['titel']}: {it['text'][:130]}" for i, it in enumerate(use))
    try:
        raw = pc_ai.gemini_generate([{"role": "user", "parts": [{"text": lines}]}],
                                    PROMPT.format(city=CITY or "unbekannt"), json_mode=True, max_tokens=4500, timeout=50,
                                    prefer="gemini-flash-lite-latest")  # schnelles, sparsames Modell für die Nachrichten
    except Exception:
        _last_fail["t"] = time.time()
        raise
    return _parse(raw, use)


def _parse(raw: str, use: list) -> dict:
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    m = re.search(r"\{.*\}", raw, re.S)
    data = json.loads(m.group(0) if m else raw)
    points = []
    for p in data.get("brennpunkte") or []:
        try:
            lat, lon = float(p["lat"]), float(p["lon"])
        except Exception:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        src = {}
        try:
            src = use[int(p.get("nr"))]
        except Exception:
            pass
        points.append({"titel": str(p.get("titel", ""))[:60], "ort": str(p.get("ort", "")), "lat": lat, "lon": lon,
                       "art": str(p.get("art", "politik")), "wichtig": int(p.get("wichtig", 2) or 2),
                       "deutschland": bool(p.get("deutschland")), "im_briefing": bool(p.get("im_briefing")),
                       "text": str(p.get("text", ""))[:320], "link": src.get("link", ""), "bild": src.get("bild", ""),
                       "quelle": src.get("quelle", ""), "schlagzeile": src.get("titel", ""),
                       "genau": str(p.get("genau") or "").lower().strip(), "suche": str(p.get("suche") or "").strip()})
    return {"briefing": str(data.get("briefing", "")).strip(), "brennpunkte": points}


# --- Genaue Orte: "Engelbergtunnel, Leonberg" -> genaue Koordinaten (OpenStreetMap, kostenlos) ----------------
_GEO_FILE = "orte_genau.json"
_geo_mem: dict = {}
_geo_lock = threading.Lock()


def _geo_load():
    if _geo_mem:
        return
    try:
        with open(os.path.join(_base_dir(), _GEO_FILE), encoding="utf-8") as f:
            _geo_mem.update(json.load(f))
    except Exception:
        pass


def _geo_save():
    try:
        with _geo_lock:
            data = dict(_geo_mem)
        with open(os.path.join(_base_dir(), _GEO_FILE), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def _dist_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(min(1.0, math.sqrt(h)))


def geocode_exact(query: str):
    """Genaue Koordinaten für einen Ort wie "Römerberg, Frankfurt am Main". (lat, lon) oder None. Wird gemerkt."""
    key = query.lower().strip()
    if not key:
        return None
    _geo_load()
    if key in _geo_mem:
        hit = _geo_mem[key]
        return tuple(hit) if hit else None
    hit = None
    urls = [
        ("photon", "https://photon.komoot.io/api/?" + urllib.parse.urlencode({"q": query, "limit": 1, "lang": "de"})),
        ("osm", "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": query, "format": "json", "limit": 1, "accept-language": "de"})),
    ]
    failed = False
    for kind, url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-PC-Assistent/1.0 (privat)"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
            if kind == "photon":
                feats = data.get("features") or []
                if feats:
                    lon, lat = feats[0]["geometry"]["coordinates"][:2]
                    hit = (float(lat), float(lon))
            elif data:
                hit = (float(data[0]["lat"]), float(data[0]["lon"]))
        except Exception:
            failed = True
            continue
        if hit:
            break
    if hit or not failed:  # nur echte Ergebnisse merken (bei Netzproblemen später nochmal versuchen)
        with _geo_lock:
            _geo_mem[key] = list(hit) if hit else None
    return hit


def refine_points(points: list, only_briefing: bool = False):
    """Setzt die Punkte genau auf den Ort der Meldung (Platz, Tunnel, Gebäude ...) statt auf die Stadtmitte."""
    todo = [p for p in points if p.get("suche") and not p.get("genau_ok") and
            p.get("genau") in ("punkt", "strasse", "stadtteil") and (p.get("im_briefing") or not only_briefing)]
    if not todo:
        return

    def one(p):
        hit = geocode_exact(p["suche"])
        # nicht gefunden oder unplausibel weit weg (die KI-Koordinaten liegen grob richtig):
        # dann lieber nicht ganz so nah heran, sonst zeigt die Kamera auf die falsche Stelle
        if not hit or _dist_km(hit, (p["lat"], p["lon"])) > 80:
            p["genau"] = "stadt"
            return
        p["lat"], p["lon"] = round(hit[0], 6), round(hit[1], 6)
        p["genau_ok"] = True
    threads = [threading.Thread(target=one, args=(p,), daemon=True) for p in todo]
    for t in threads:
        t.start()
    for t in threads:
        t.join(8)
    _geo_save()


def get(max_age: float = MAX_AGE, wait: bool = True):
    """Aktuelle Weltlage: {"zeit", "briefing", "brennpunkte", "schlagzeilen"}. wait=False gibt sofort den letzten Stand
    zurück (oder None) und aktualisiert im Hintergrund."""
    with _lock:
        data, ts = _cache["data"], _cache["ts"]
    if data is None:
        try:
            with open(_file(), encoding="utf-8") as f:
                data = json.load(f)
            ts = float(data.get("zeit", 0))
            with _lock:
                _cache.update(data=data, ts=ts)
        except Exception:
            pass
    if data is not None and time.time() - ts < max_age:
        return data
    if not wait:
        if time.time() - _last_try["t"] > 120 and not _busy.locked():  # nicht jede Sekunde neu anstoßen
            _last_try["t"] = time.time()
            threading.Thread(target=refresh, daemon=True).start()
        return data
    return refresh() or data


def refresh():
    if not _busy.acquire(blocking=False):  # läuft schon: auf das Ergebnis warten
        with _busy:
            return _cache["data"]
    try:
        items = fetch_headlines()
        if not items:
            return None
        result = None
        try:
            result = _ask_gemini(items)
        except Exception as e:
            print(f"Weltlage: Gemini-Zusammenfassung nicht möglich ({e}), nehme die Schlagzeilen.")
        if not result or not result.get("briefing"):
            result = _fallback(items)
        try:
            refine_points(result.get("brennpunkte") or [], only_briefing=True)  # die Orte der Tour sofort genau
        except Exception as e:
            print(f"Weltlage: genaue Orte nicht möglich ({e})")
        result["zeit"] = time.time()
        result["schlagzeilen"] = items[:20]
        with _lock:
            _cache.update(data=result, ts=result["zeit"])
        try:
            with open(_file(), "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except Exception:
            pass

        def rest():  # die übrigen Punkte nebenbei genau machen und mit speichern
            try:
                refine_points(result.get("brennpunkte") or [])
                with open(_file(), "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False)
            except Exception:
                pass
        threading.Thread(target=rest, daemon=True).start()
        return result
    finally:
        _busy.release()


# --- Lage an einem beliebigen Ort (Lieblingsorte, "Wie ist die Lage in Seoul?") -------------------
PLACE_PROMPT = """Du bist der Lage-Analyst von J.A.R.V.I.S. Unten stehen nummerierte Schlagzeilen (#Nummer [Quelle] Titel: Text)
über {place}. Erstelle:
1. "briefing": ein gesprochenes Lage-Briefing auf Deutsch über {place}, 3 bis 5 kurze Sätze, sachlich, wie ein Butler.
   Beginne mit "Aus {place}:". Keine Listen, keine Sonderzeichen.
2. "brennpunkte": die 6 bis 12 interessantesten Meldungen aus {place} und Umgebung (Politik, Verkehr, Wetter, Ereignisse,
   Kultur, Sport). Zuerst die im Briefing erwähnten. Für jede: "nr", "titel" (höchstens 6 Wörter, Deutsch), "ort"
   (Stadtteil, Straße oder Gebäude, so genau wie möglich), "lat", "lon" (genaue Koordinaten des Ortes der Meldung),
   "art" (konflikt, politik, wirtschaft, wetter, katastrophe, gesellschaft, sport, wissenschaft, lokal),
   "wichtig" (1 bis 3), "deutschland" (true/false), "im_briefing" (true/false), "text" (zwei Sätze auf Deutsch),
{GENAU}
Antworte NUR mit JSON: {{"briefing": "...", "brennpunkte": [ ... ]}}""".replace("{GENAU}", GENAU_TEXT)
_places: dict = {}  # Ort (klein) -> Daten


def _geocode(place: str):
    hit = PLACES.get(place.lower())
    if hit:
        return hit
    try:
        import pc_info

        lat, lon, name = pc_info.geocode(place)
        return float(lat), float(lon), name
    except Exception:
        return None


def get_place(place: str, max_age: float = MAX_AGE):
    """Lage an einem Ort: {"ort", "lat", "lon", "briefing", "brennpunkte", ...}. Der eigene Wohnort = normale Lage."""
    place = " ".join(place.strip(" .,!?").split())
    if not place or place.lower() == (CITY or "").lower():
        return get()
    key = place.lower()
    hit = _places.get(key)
    if hit and time.time() - hit["zeit"] < max_age:
        return hit
    geo = _geocode(place)
    q = urllib.parse.quote(f'"{place}"' if " " in place else place)
    feeds = [(f"Lokal {place}", f"https://news.google.com/rss/search?q={q}+when:3d&hl=de&gl=DE&ceid=DE:de"),
             (f"Lokal {place} (en)", f"https://news.google.com/rss/search?q={q}+when:2d&hl=en-US&gl=US&ceid=US:en")]
    results = {}

    def load(src, url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Jarvis"})
            with urllib.request.urlopen(req, timeout=8) as r:
                results[src] = parse_feed(r.read(), src, limit=15)
        except Exception as e:
            print(f"Nachrichten zu {place} nicht erreichbar: {e}")
    threads = [threading.Thread(target=load, args=f, daemon=True) for f in feeds]
    for t in threads:
        t.start()
    for t in threads:
        t.join(12)
    items, seen = [], set()
    for src, _ in feeds:
        for it in results.get(src, []):
            k = it["titel"].lower()[:60]
            if k not in seen:
                seen.add(k)
                items.append(it)
    data = None
    try:
        import pc_ai

        if items and pc_ai.available() and time.time() - _last_fail["t"] > 5 * 60:
            use = items[:30]
            lines = "\n".join(f"#{i} [{it['quelle']}] {it['titel']}: {it['text'][:130]}" for i, it in enumerate(use))
            raw = pc_ai.gemini_generate([{"role": "user", "parts": [{"text": lines}]}], PLACE_PROMPT.format(place=place),
                                        json_mode=True, max_tokens=3500, timeout=45, prefer="gemini-flash-lite-latest")
            data = _parse(raw, use)
            refine_points(data.get("brennpunkte") or [])
    except Exception as e:
        print(f"Lage {place}: Zusammenfassung nicht möglich ({e})")
    if not data or not data.get("briefing"):
        pts = []
        if geo:
            for i, it in enumerate(items[:8]):  # ohne KI: Meldungen rund um die Ortsmitte
                a = i * 0.8
                pts.append({"titel": it["titel"][:60], "ort": geo[2], "lat": geo[0] + 0.02 * math.sin(a) * (i > 0),
                            "lon": geo[1] + 0.03 * math.cos(a) * (i > 0), "art": "lokal", "wichtig": 2,
                            "deutschland": False, "im_briefing": i < 3, "text": it["text"][:300],
                            "link": it.get("link", ""), "quelle": it.get("quelle", ""), "schlagzeile": it["titel"]})
        tops = [it["titel"].rstrip(".") for it in items[:3]]
        data = {"briefing": (f"Aus {place}: " + ". ".join(tops) + ".") if tops else
                f"Zu {place} habe ich gerade keine Meldungen gefunden.", "brennpunkte": pts}
    if geo:
        data["lat"], data["lon"] = geo[0], geo[1]
    elif data["brennpunkte"]:
        data["lat"], data["lon"] = data["brennpunkte"][0]["lat"], data["brennpunkte"][0]["lon"]
    data["ort"] = place
    data["zeit"] = time.time()
    data["schlagzeilen"] = items[:20]
    _places[key] = data
    return data


PLACE_ASK = re.compile(r"(?:lage|los|neu(?:es|igkeiten)?|nachrichten|news|passiert)\s+(?:in|aus|für|von|bei)\s+"
                       r"(?:der |dem |den )?([a-zäöüß][\w .'-]{1,40})$", re.I)


def briefing_text(timeout_s: float = 12.0) -> str:
    """Gesprochenes Lage-Briefing (leer, wenn keine Nachrichten erreichbar sind)."""
    box = {}
    t = threading.Thread(target=lambda: box.update(d=get()), daemon=True)
    t.start()
    t.join(timeout_s)
    data = box.get("d")
    if not data:
        return ""
    return (data.get("briefing") or "").strip()


# --- Sprachbefehle -----------------------------------------------------------------------
LAGE = re.compile(r"wie ist (?:so )?die lage|lagebericht|lagebild|briefing|weltlage|was ist (?:heute )?in der welt|"
                  r"was (?:gibt.?s|gibt es) neues in der welt|was ist (?:heute )?(?:so )?passiert|"
                  r"^(?:die |aktuelle |neueste |neuesten )?(?:nachrichten|news)$|(?:sag|erzähl|lies)\w* mir die (?:nachrichten|news)|"
                  r"was (?:gibt.?s|gibt es) für nachrichten|brennpunkte")
LUFT = re.compile(r"luftraum|was fliegt|welche[sn]? flugzeug|flugzeuge? (?:über|in der nähe|um mich|da oben|gerade)"
                  r"|flugverkehr|\bflüge\b.*(?:über|gerade)|über (?:mir|uns) fliegt|fliegt (?:da|gerade) (?:über|oben)")
DEUTSCHLAND = re.compile(r"(?:lage|karte|nachrichten) (?:in |von |für )?deutschland|deutschland ?karte")
CLOSE = re.compile(r"(?:schließ|schliess|mach|blend)\w*\s+(?:den |die )?(?:globus|weltlage|lage|karte)\w*\s*(?:zu|aus|weg)?|"
                   r"globus (?:zu|aus|weg|schließen)")
SHOW = re.compile(r"(?:zeig|öffne|mach)\w*\s+(?:mir\s+)?(?:den |die )?(?:globus|weltkarte|lage ?karte)")
