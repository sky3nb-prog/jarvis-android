"""
Jarvis am PC sagt dem Handy, was es tun soll (über die Kopplung, verschlüsselt über ntfy.sh):

- "Ruf Mama an", "ruf über mein Handy Lisa an"         -> das Handy ruft an
- "Trag morgen um 15 Uhr Zahnarzt ein" (Handy gekoppelt) -> landet direkt im Handy-Kalender (Google, synchron)
- "Stell am Handy einen Wecker auf 7", "schick Lisa am Handy eine WhatsApp ..." -> alles, was der Handy-Jarvis kann
- "Schick mir, was ich gerade höre, aufs Handy"          -> Deezer/YouTube öffnet am Handy denselben Titel

Das Handy hört einen eigenen Kanal ab ("jh…", aus dem Kopplungscode), führt den Satz mit seinem eigenen Jarvis aus
und schickt die Antwort auf dem Fernbedienungs-Kanal zurück. Die spricht dann der PC.
Ein Auftrag kostet 2 Nachrichten (ntfy.sh erlaubt etwa 250 am Tag).
"""

import hashlib
import re
import threading
import time
import urllib.request
import uuid

import pc_link

_waiting = {}   # id -> [Event, Antwort]


def topic() -> str:
    n = pc_link._norm(pc_link.code()).encode()
    return "jh" + hashlib.sha256(b"jarvis-handy:" + n).hexdigest()[:30]


def paired() -> bool:
    try:
        return len(pc_link._norm(pc_link.code())) >= 12
    except Exception:
        return False


def _send(obj: dict):
    c = pc_link.code()
    r = urllib.request.Request(pc_link.SERVER + topic(), data=pc_link.encrypt(obj, c).encode(), method="POST")
    r.add_header("User-Agent", "Jarvis-PC")
    urllib.request.urlopen(r, timeout=20).read()


def ask(kind: str, wait: float = 25, **data):
    """Auftrag ans Handy. Gibt die Antwort des Handys zurück (dict mit ok/text) oder None, wenn es nicht antwortet."""
    mid = uuid.uuid4().hex[:12]
    ev = threading.Event()
    _waiting[mid] = [ev, None]
    try:
        _send(dict(kind=kind, id=mid, ts=int(time.time()), **{"from": "pc"}, **data))
        ev.wait(wait)
        return _waiting[mid][1]
    except Exception as e:
        print(f"Handy-Auftrag ging nicht: {e}")
        return None
    finally:
        _waiting.pop(mid, None)


def on_reply(msg: dict):
    """Vom Fernbedienungs-Kanal (pc_remote): Antwort des Handys."""
    w = _waiting.get(str(msg.get("re") or ""))
    if w:
        w[1] = {"ok": bool(msg.get("ok", True)), "text": str(msg.get("text") or "")}
        w[0].set()


# --- Erkennen, was ans Handy soll --------------------------------------------------------------------------
PHONE = r"(?:am|aufs|ans|übers|über das|über mein|über meinem|auf dem|auf meinem|mit dem|mit meinem|vom|von meinem)\s+(?:handy|telefon|smartphone|samsung)"
MEDIA = re.compile(r"(?:schick|send|leg|übertrag|übergib|mach|spiel|pack|bring)\w*\b.{0,40}\b(?:was ich (?:gerade |grad )?(?:hör|schau|guck)\w*|"
                   r"das lied|den song|den titel|das video|die musik|was (?:gerade |grad )?läuft|das hier)\b.{0,30}\b(?:handy|telefon)\b|"
                   r"(?:handy|telefon)\b.{0,30}\b(?:weiter ?hören|weiter ?schauen|weiter ?spielen)", re.I)
CALL = re.compile(r"\bruf\w*\b.{1,40}\ban\b|\banrufen\b|\btelefonier\w*\b|\bwähl\w*\b.{0,30}\bnummer\b", re.I)
CAL_ADD = re.compile(r"\b(trag|trage|erstell|erstelle|leg|lege|mach|mache|füg|füge|setz|setze|schreib|schreibe)\w*\b.*\b(termin|kalender\w*)\b"
                     r"|^neuer termin\b", re.I)


FILLER = r"\b(?:mal|bitte|doch|jetzt|gleich|kurz|schnell|einfach|für mich)\b"


def call_name(text: str):
    """„Ruf über mein Handy Mama an“ -> „Mama“, „kannst du Lisa anrufen“ -> „Lisa“. Sonst None."""
    low = text.lower().strip(" .!?")
    low = re.sub(r"\b(?:über|übers|mit|vom|von|auf|am)\s+(?:mein(?:em|en)?|das|dem|den)?\s*(?:handy|telefon|smartphone|samsung)\b", " ", low)
    low = re.sub(r"^(?:jarvis|hey|okay|ok)[ ,]+", "", low)
    low = re.sub(FILLER, " ", low)
    low = re.sub(r"\s+", " ", low).strip()
    m = re.search(r"\bruf\w*\s+(.+?)\s+an$", low) or re.search(r"(?:^|\b(?:du|sie|bitte)\s+)(.+?)\s+anrufen$", low) \
        or re.search(r"\btelefonier\w*\s+mit\s+(.+)$", low)
    if not m:
        return None
    name = re.sub(r"^(?:kannst du|könntest du|würdest du|du)\s+", "", m.group(1)).strip(" ,")
    name = re.sub(r"^(?:mein|meine|meinen|meinem|meiner|die|den|der)\s+", "", name)
    return name.title() if name else None


def handle(text: str):
    """Gibt die Antwort zurück, wenn der Satz ans Handy geht, sonst None."""
    if not paired():
        return None
    low = text.lower().strip()
    if MEDIA.search(low):
        return send_media()
    who = call_name(text) if CALL.search(low) and not re.search(r"discord|teams|skype|zoom", low) else None
    if who:   # Anruf: direkt ans Handy, ohne Umweg über die KI (schnell und zuverlässig)
        r = ask("call", wait=20, who=who)
        if r is None:
            return "Dein Handy antwortet gerade nicht. Ist die Jarvis-App dort an?"
        return r["text"] or f"Ich rufe {who} über dein Handy an."
    via_phone = re.search(r"\b" + PHONE + r"\b", low) is not None
    if via_phone or (CALL.search(low) and not re.search(r"discord|teams|skype|zoom", low)):
        r = ask("do", text=text)
        if r is None:
            return "Dein Handy antwortet gerade nicht. Ist die Jarvis-App dort an?"
        return r["text"] or ("Erledigt, am Handy." if r["ok"] else "Am Handy ging das nicht.")
    if CAL_ADD.search(low):
        r = ask("do", wait=20, text=text)
        if r is None:
            return None   # Handy nicht erreichbar: der PC trägt es wie bisher selbst ein
        return r["text"] or "Steht im Kalender auf deinem Handy."
    return None


def send_media():
    import pc_media
    now = pc_media.now()
    if not now or not (now.get("title") or "").strip():
        return "Am PC läuft gerade nichts, das ich dir schicken könnte."
    app = pc_media.app_name(now.get("app", ""))
    video = app in ("Chrome", "Edge", "Firefox", "Opera") or "youtube" in (now.get("app") or "").lower()
    r = ask("media", wait=15, title=now.get("title", ""), artist=now.get("artist", ""), app=app, video=video)
    what = f"„{now['title']}“" + (f" von {now['artist']}" if now.get("artist") and not video else "")
    if r is None:
        return f"Ich habe {what} ans Handy geschickt, aber es hat sich nicht gemeldet."
    return r["text"] or f"{what} ist jetzt auf deinem Handy."
