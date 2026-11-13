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
    t0 = time.time()
    try:
        print(f"Handy-Auftrag {kind}: {str(data)[:120]}")
        _send(dict(kind=kind, id=mid, ts=int(time.time()), **{"from": "pc"}, **data))
        ev.wait(wait)
        r = _waiting[mid][1]
        print(f"Handy-Antwort {kind} nach {time.time() - t0:.1f} s: " + (str(r.get("text", ""))[:150] if r else "keine (Jarvis-App an? Schalter oben rechts an?)"))
        return r
    except Exception as e:
        print(f"Handy-Auftrag ging nicht: {e}")
        return None
    finally:
        _waiting.pop(mid, None)


STATUS = {"data": None, "t": 0.0}   # letzter Stand vom Handy (Akku, Lautstärken, was läuft, Termine)
ON_STATUS = None                    # vom HUD gesetzt: neuer Stand ist da


def on_reply(msg: dict):
    """Vom Fernbedienungs-Kanal (pc_remote): Antwort des Handys."""
    if isinstance(msg.get("status"), dict):
        STATUS.update(data=msg["status"], t=time.time())
        if ON_STATUS:
            try:
                ON_STATUS(STATUS["data"])
            except Exception:
                pass
    w = _waiting.get(str(msg.get("re") or ""))
    if w:
        w[1] = dict(msg, ok=bool(msg.get("ok", True)), text=str(msg.get("text") or ""))
        w[0].set()


# --- Erkennen, was ans Handy soll --------------------------------------------------------------------------
PHONE = r"(?:am|aufs|ans|übers|über das|über mein|über meinem|auf dem|auf meinem|mit dem|mit meinem|vom|von meinem)\s+(?:handy|telefon|smartphone|samsung)"
MEDIA = re.compile(r"(?:schick|send|leg|übertrag|übergib|mach|spiel|pack|bring)\w*\b.{0,40}\b(?:was ich (?:gerade |grad )?(?:hör|schau|guck)\w*|"
                   r"das lied|den song|den titel|das video|die musik|was (?:gerade |grad )?läuft|das hier)\b.{0,30}\b(?:handy|telefon)\b|"
                   r"(?:handy|telefon)\b.{0,30}\b(?:weiter ?hören|weiter ?schauen|weiter ?spielen)", re.I)
CALL = re.compile(r"\bruf\w*\b.{1,40}\ban\b|\banrufen\b|\btelefonier\w*\b|\bwähl\w*\b.{0,30}\bnummer\b", re.I)
CAL_VERB = re.compile(r"\b(?:ein)?trag\w*|\beinträg\w*|\bschreib\w*|\bnotier\w*|\berstell\w*|\banleg\w*|\bsetz\w*|\bfüg\w*|"
                      r"\bplan\w*|\bleg\w*\b.*\ban\b|\bin (?:den |meinen |dein |deinen )?kalender\b.*\bein\b|\bmach\w*\b.*\btermin|\bmerk\w*\b.*\bkalender|\berinner\w*", re.I)
CAL_WORD = re.compile(r"\bkalender\w*|\btermin\w*", re.I)
CAL_QUESTION = re.compile(r"^(?:was|welche\w*|wann|wie viele|hab ich|habe ich|steht|zeig\w*|lies|sag mir was)\b", re.I)


class _CalAdd:
    """„Trag … in den Kalender ein“, „kannst du mir was im Kalender eintragen in 48 Stunden“, „neuer Termin …“"""
    @staticmethod
    def search(low: str):
        low = re.sub(r"^(?:jarvis|friday|hey|okay|ok)[ ,]+", "", low.strip())
        low = re.sub(r"^(?:kannst du|könntest du|würdest du|bitte)\s+(?:mir\s+)?", "", low)
        if CAL_QUESTION.match(low) and not re.search(r"\b(?:ein)?trag|einträg", low):
            return None
        return CAL_WORD.search(low) and CAL_VERB.search(low) or re.match(r"^neuer termin\b", low)


CAL_ADD = _CalAdd()


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
    if re.search(r"\b(?:ich )?(?:fahr|fahre|geh|gehe|bin)\w* (?:jetzt |gleich |dann )*(?:los|unterwegs) (?:zu|nach|zum|zur)\b", low):
        # "ich fahr jetzt los zu Oma und Opa": das Handy merkt sich das Ziel und sagt kurz vor der Ankunft Bescheid
        r = ask("do", wait=25, text=text)
        if r is None:
            return "Dein Handy antwortet gerade nicht. Ist die Jarvis-App dort an?"
        return r.get("text") or "Gute Fahrt!"
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
    if re.match(r"^(?:jarvis |friday )?(?:kannst du mich |bitte )?erinner\w* mich\b", low) and not CAL_ADD.search(low):
        # „Erinnere mich in 2 Stunden an …“: der PC erinnert selbst (pc_remind), das Handy trägt es zusätzlich ein
        threading.Thread(target=lambda: ask("termin", wait=30, text=text), daemon=True).start()
        return None
    if CAL_ADD.search(low):
        # Das Handy trägt in deinen Kalender ein (Google, synchron) und prüft nach; der PC erinnert dich zusätzlich.
        r = ask("termin", wait=30, text=text)
        if r is None:
            return None   # Handy nicht erreichbar: der PC macht es wie bisher selbst
        if r.get("ok") and r.get("remind_at"):
            remind_here(str(r.get("title") or ""), float(r["remind_at"]))
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


# --- Seite "Steuern" im HUD ---------------------------------------------------------------------------------
_asked = {"t": 0.0}


def refresh_status(force: bool = False):
    """Stand vom Handy holen (kostet 2 Nachrichten, darum höchstens alle 2 Minuten). Gibt False zurück, wenn es nicht antwortet."""
    if not paired():
        print("Handy-Stand: nicht gekoppelt")
        return False
    if not force and time.time() - _asked["t"] < 120:
        return True
    _asked["t"] = time.time()
    r = ask("status", wait=20)
    if r is None:
        _asked["t"] = 0   # gleich nochmal erlauben
        return False
    return True


def control(what: str, **data) -> dict:
    """Musik-Tasten, Lautstärke, Lautlos, Lampe, Handy finden."""
    r = ask("ctl", wait=15, what=what, **data)
    return r or {"ok": False, "text": "Dein Handy antwortet gerade nicht. Ist die Jarvis-App dort an?"}


def command(text: str) -> dict:
    """Freier Befehl ans Handy (wie gesprochen beim Handy-Jarvis)."""
    r = ask("do", wait=30, text=text)
    return r or {"ok": False, "text": "Dein Handy antwortet gerade nicht. Ist die Jarvis-App dort an?"}


def call(who: str) -> dict:
    r = ask("call", wait=20, who=who)
    return r or {"ok": False, "text": "Dein Handy antwortet gerade nicht. Ist die Jarvis-App dort an?"}


# --- Wege planen (rechnet das Handy: kennt Standort, Gedächtnis, Läden entlang der Strecke) --------------------
ROUTE = re.compile(r"wann muss ich\b.*\b(?:los|aufbrechen|starten)|\broute\b|google maps|\bnavigation\b|\bnavigier\w*|"
                   r"\bich (?:möchte|will|muss|würde gern|wollte)\s+(?:\w+\s+){0,3}(?:zu|nach|zum|zur)\s+\w+|"
                   r"\bich (?:möchte|will|muss|würde gern|wollte|mag)\b.*\b\w*(?:fahr|radel|lauf|geh|los|hin|rüber)\w*\b.*\b(?:nach|zu|zum|zur|ins|in die)\b|"
                   r"\b(?:vorbei|zwischenstopp)\w*\b.*\b(?:nach|zu|zum|zur)\b|\b(?:nach|zu|zum|zur)\b.*\bvorbei\w*\b|"
                   r"\b(?:bahn|s-bahn|zug|bus)\b.*\b(?:nach|zu|zum|zur)\b|"
                   r"(?:wie\s+(?:lange|weit)|route|wege?\b|wie\s+komme\s+ich|navigier\w*|fahrzeit).*\b(?:nach|zu|zum|zur)\b", re.I)


def plan_route(text: str):
    """Wegewunsch ans Handy, Google Maps am PC öffnen. None, wenn das Handy nicht antwortet (dann plant der PC selbst)."""
    if not paired() or not ROUTE.search(text):
        return None
    if re.search(r"\b(?:youtube|discord|steam|chrome|spotify|deezer|whatsapp|netflix|twitch|instagram|tiktok|einstellungen|ordner|"
                 r"spiel|lied|musik|video|seite|website|app)\b", text, re.I) and not re.search(r"\broute\b|maps|navigation", text, re.I):
        return None   # „ich will zu YouTube“ ist kein Weg
    who = re.search(r"\ban\s+([A-ZÄÖÜ][\wäöüß-]+)\b", text)
    who = who.group(1) if who and who.group(1).lower() not in ("mein", "meine", "mich", "handy", "telefon", "google", "dem", "den", "der") else None
    r = ask("route", wait=45, text=text)
    if r is not None and who:
        r["send_to"] = who   # „… an Thomas schicken“ gilt vor der Einstellung
    if r is None:
        return None
    if r.get("url"):
        try:
            import webbrowser
            webbrowser.open(r["url"])
        except Exception:
            pass
    if r.get("send_to") and (r.get("message") or r.get("url")):
        r["message"] = r.get("message") or ("Route: " + str(r.get("url")))   # Link per WhatsApp an den eingestellten Kontakt (Einstellungen → Wege)
        def go():
            try:
                import pc_messages
                print("Route an", r["send_to"], "->", pc_messages.send_whatsapp(str(r["send_to"]), str(r["message"])))
            except Exception as e:
                print(f"Route per WhatsApp ging nicht: {e}")
        threading.Timer(4.0, go).start()   # erst nach dem Sprechen tippen
    return r.get("text") or "Den Weg konnte ich gerade nicht planen."


def remind_here(title: str, at: float):
    """Erinnerung am PC (wird gesprochen, wenn der PC dann läuft). Doppelte werden nicht angelegt."""
    import pc_remind
    if not title or at <= time.time():
        return
    for i in pc_remind.upcoming():
        if i.get("kind") == "reminder" and i.get("text") == title and abs(i.get("due", 0) - at) < 120:
            return
    pc_remind.add("reminder", at, title)
