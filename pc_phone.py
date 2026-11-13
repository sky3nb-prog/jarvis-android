"""
Verbindung zum Handy über ntfy (kostenlos, ohne Konto, App für Android und iPhone):

1. Nachrichten aufs Handy: Jarvis schickt z. B. eine Route als Benachrichtigung; Antippen öffnet Google Maps.
   Am Handy: App "ntfy" installieren, "+" und den Kanal aus den Jarvis-Einstellungen (Handy) abonnieren.
2. Standort vom Handy: Die App "OwnTracks" schickt deinen Standort an einen zweiten, geheimen Kanal, den Jarvis liest.
   In OwnTracks: Modus "HTTP", Adresse https://ntfy.sh/<Standort-Kanal> (steht in den Jarvis-Einstellungen).

Die Kanalnamen sind lange Zufallswörter, damit sie niemand errät. ntfy.sh bewahrt Nachrichten nur ein paar Stunden auf.
"""

import json
import secrets
import threading
import time
import urllib.request

SERVER = "https://ntfy.sh"
CHANNEL = "telegram"  # "telegram" = Jarvis-Bot, "whatsapp" = an deine eigene Nummer, "ntfy" = ntfy-App
MY_NUMBER = ""  # deine WhatsApp-Nummer (aus den Einstellungen)
PUSH_TOPIC = ""  # aus den Einstellungen
LOC_TOPIC = ""
_loc = {"lat": None, "lon": None, "ts": 0.0, "checked": 0.0}
_lock = threading.Lock()


def new_topic(kind: str) -> str:
    return f"jarvis-{kind}-{secrets.token_hex(8)}"


def push(title: str, message: str, click: str = "", tags: str = "round_pushpin") -> bool:
    """Nachricht aufs Handy: per WhatsApp an dich selbst oder über die ntfy-App. True = verschickt."""
    if CHANNEL == "telegram":
        import pc_telegram

        import html as _h
        text = f"<b>{_h.escape(title)}</b>\n{_h.escape(message)}"
        return pc_telegram.send(text, "In Google Maps öffnen" if click else "", click)
    if CHANNEL == "whatsapp":
        number = MY_NUMBER
        if not number:
            try:
                import pc_memory

                number = pc_memory.profile("telefon")
            except Exception:
                number = ""
        if number:
            import pc_messages

            text = f"*{title}*\n{message}" + (f"\n{click}" if click else "")
            return pc_messages.send_to_number(number, text)
        if not PUSH_TOPIC:
            return False
    if not PUSH_TOPIC:
        return False
    body = {"topic": PUSH_TOPIC, "title": title, "message": message, "tags": [tags]}
    if click:
        body["click"] = click
        body["actions"] = [{"action": "view", "label": "In Google Maps öffnen", "url": click}]
    req = urllib.request.Request(SERVER, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "Jarvis"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except Exception as e:
        print(f"ntfy: {e}")
        return False


def _poll():
    """Letzten Standort aus dem OwnTracks-Kanal holen."""
    if not LOC_TOPIC:
        return
    url = f"{SERVER}/{LOC_TOPIC}/json?poll=1&since=12h"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Jarvis"})
        with urllib.request.urlopen(req, timeout=10) as r:
            lines = r.read().decode("utf-8", "ignore").splitlines()
    except Exception as e:
        print(f"Standort nicht abrufbar: {e}")
        return
    best = None
    for line in lines:
        try:
            msg = json.loads(line)
            if msg.get("event") != "message":
                continue
            data = json.loads(msg.get("message") or "{}")
            if data.get("_type") != "location":
                continue
            ts = float(data.get("tst") or msg.get("time") or 0)
            if best is None or ts > best[2]:
                best = (float(data["lat"]), float(data["lon"]), ts)
        except Exception:
            continue
    if best:
        with _lock:
            if best[2] > _loc["ts"]:  # nur wenn neuer als der letzte (z. B. von Telegram)
                _loc.update(lat=best[0], lon=best[1], ts=best[2])


def location(max_age: float = 1800):
    """(lat, lon) vom Handy, wenn höchstens max_age Sekunden alt, sonst None."""
    if time.time() - _loc["checked"] > 60:
        _loc["checked"] = time.time()
        _poll()
    with _lock:
        if _loc["lat"] is not None and time.time() - _loc["ts"] <= max_age:
            return _loc["lat"], _loc["lon"]
    return None


def owntracks_url() -> str:
    return f"{SERVER}/{LOC_TOPIC}" if LOC_TOPIC else ""


def send_setup() -> bool:
    """Schickt dir die OwnTracks-Einrichtung aufs Handy (die Adresse zum Kopieren)."""
    url = owntracks_url()
    if not url:
        return False
    if CHANNEL == "telegram":
        return push("Standort teilen", "Hier im Chat: Büroklammer > Standort > Live-Standort teilen > "
                                       "bis ich es ausschalte. Fertig.")
    steps = ("1. App OwnTracks installieren und öffnen, Standort auf Immer erlauben.\n"
             "2. Oben links Menü > Einstellungen > Verbindung (iPhone: i-Symbol > Einstellungen).\n"
             "3. Modus: HTTP.\n"
             "4. Bei Host/URL genau diese Adresse einfügen (lange drauftippen zum Kopieren):\n" + url + "\n"
             "5. Rest leer lassen, speichern. Fertig - Jarvis sieht dich dann innerhalb weniger Minuten.")
    return push("OwnTracks einrichten", steps)


def age_text() -> str:
    if not _loc["ts"]:
        return "noch kein Standort empfangen"
    m = int((time.time() - _loc["ts"]) // 60)
    return "gerade eben" if m < 2 else f"vor {m} Minuten" if m < 120 else f"vor {m // 60} Stunden"


def where_text() -> str:
    """Für "Jarvis, wo bin ich?"."""
    loc = location(max_age=6 * 3600)
    if not loc:
        return "Ich weiß gerade nicht, wo du bist. Richte in den Einstellungen unter Handy den Standort ein."
    try:
        import urllib.parse

        url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
            {"lat": loc[0], "lon": loc[1], "format": "json", "accept-language": "de", "zoom": 17})
        req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-PC-Assistent/1.0 (privat)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            a = json.loads(r.read().decode("utf-8")).get("address") or {}
        street = " ".join(x for x in (a.get("road"), a.get("house_number")) if x)
        town = a.get("village") or a.get("town") or a.get("city") or a.get("municipality") or ""
        place = ", ".join(x for x in (street, town) if x) or "an einem unbekannten Ort"
    except Exception:
        place = f"bei {loc[0]:.4f}, {loc[1]:.4f}"
    return f"Laut deinem Handy bist du {place} ({age_text()})."
