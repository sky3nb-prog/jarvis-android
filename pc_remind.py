"""
Timer, Wecker und Erinnerungen per Sprache, ganz ohne Schlüssel.

Beispiele:
    "Stell einen Timer auf 10 Minuten"            "Timer für die Nudeln, 12 Minuten"
    "Erinnere mich in einer Stunde an die Pizza"  "Erinnere mich um 18 Uhr 30 an das Meeting"
    "Erinnere mich morgen um 9 Uhr an den Arzttermin"
    "Weck mich um 6:45"                           "Stell einen Wecker auf 7 Uhr"
    "Welche Timer laufen?"                        "Wie lange läuft der Timer noch?"
    "Lösche alle Timer" / "Lösche die Erinnerungen" / "Wecker aus"

Alles wird in erinnerungen.json neben dem Programm gespeichert, übersteht also einen Neustart.
Fällige Einträge meldet der Zeitplaner (Klasse Scheduler); was beim Ausschalten fällig wurde,
meldet er beim nächsten Start als "Verpasst".
"""

import datetime
import json
import os
import re
import threading
import time
import uuid

import pc_apps

FILE = "erinnerungen.json"
_lock = threading.RLock()
_items: list = []
_loaded = False

WEEKDAYS = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
WEEKDAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


# --- Speicher -----------------------------------------------------------------
def _path() -> str:
    return os.path.join(pc_apps.base_dir(), FILE)


def _load():
    global _loaded, _items
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            with open(_path(), encoding="utf-8") as f:
                _items = [i for i in json.load(f) if isinstance(i, dict) and "due" in i and "kind" in i]
        except Exception:
            _items = []


def _save():
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(_items, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def upcoming() -> list:
    """Alle offenen Einträge, der früheste zuerst."""
    _load()
    with _lock:
        return sorted((dict(i) for i in _items), key=lambda i: i["due"])


def add(kind: str, due: float, text: str = "") -> dict:
    _load()
    item = {"id": uuid.uuid4().hex[:8], "kind": kind, "due": float(due), "text": text, "created": time.time()}
    with _lock:
        _items.append(item)
        _save()
    return item


def remove(ids) -> int:
    _load()
    with _lock:
        before = len(_items)
        _items[:] = [i for i in _items if i["id"] not in set(ids)]
        _save()
        return before - len(_items)


def pop_due(now: float = None) -> list:
    """Nimmt alle fälligen Einträge aus der Liste und gibt sie mit der Verspätung in Sekunden zurück."""
    _load()
    now = time.time() if now is None else now
    with _lock:
        due = [(dict(i), now - i["due"]) for i in _items if i["due"] <= now]
        if due:
            _items[:] = [i for i in _items if i["due"] > now]
            _save()
        return due


# --- Zahlen und Zeiten verstehen ----------------------------------------------------
UNITS = {"null": 0, "ein": 1, "eins": 1, "eine": 1, "einen": 1, "einem": 1, "einer": 1, "zwei": 2, "drei": 3,
         "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12,
         "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18,
         "neunzehn": 19}
TENS = {"zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40, "fünfzig": 50, "sechzig": 60,
        "siebzig": 70, "achtzig": 80, "neunzig": 90}


def _word_number(tok: str):
    if tok in UNITS:
        return UNITS[tok]
    if tok in TENS:
        return TENS[tok]
    if tok == "hundert":
        return 100
    m = re.fullmatch(r"([a-zäöüß]+?)und([a-zäöüß]+)", tok)
    if m and m.group(1) in UNITS and m.group(2) in TENS:
        return UNITS[m.group(1)] + TENS[m.group(2)]
    return None


def _prep(text: str) -> str:
    """Kleinschreibung, ohne Satzzeichen, Zahlwörter als Ziffern ("zehn" -> "10")."""
    t = text.lower().replace(",", " , ").replace("½", " halbe ")
    t = re.sub(r"(?<=\d)[,.](?=\d)", ".", re.sub(r"(\d) , (\d)", r"\1.\2", t))
    t = re.sub(r"[^\w\säöüß:.]", " ", t)
    # "ein/eine/einen" nur vor Zeiteinheiten als Zahl lesen, sonst bleibt es ein Artikel
    t = re.sub(r"\b(ein|eine|einen|einem|einer)\b(?=\s+(?:halbe|stunde|minute|sekunde|viertel))", "1", t)

    def conv(m):
        n = _word_number(m.group(0))
        return str(n) if n is not None and m.group(0) not in ("ein", "eine", "einen", "einem", "einer", "eins") else m.group(0)

    t = re.sub(r"[a-zäöüß]+", conv, t)
    return re.sub(r"\s+", " ", t).strip()


DUR = re.compile(r"(\d+(?:\.\d+)?)\s*(sekunden?|sek\b|minuten?|min\b|stunden?|std\b|h\b)")


def parse_duration(t: str):
    """Dauer im Text -> (Sekunden, [gefundene Textstücke]) oder (None, [])."""
    total, spans = 0.0, []
    for pattern, secs in ((r"anderthalb stunden?", 5400), (r"dreiviertel ?stunde", 2700),
                          (r"(?:1 )?halbe stunde", 1800), (r"viertel ?stunde", 900)):
        m = re.search(pattern, t)
        if m:
            total += secs
            spans.append(m.group(0))
            t = t.replace(m.group(0), " ", 1)
    for m in DUR.finditer(t):
        value, unit = float(m.group(1)), m.group(2)
        total += value * (1 if unit.startswith("sek") else 60 if unit.startswith("min") else 3600)
        spans.append(m.group(0))
    return (int(round(total)), spans) if total > 0 else (None, [])


CLOCK = re.compile(
    r"\bum (?:(halb|viertel nach|viertel vor|dreiviertel) )?(\d{1,2})(?:[:.](\d{2}))?(?: uhr(?: (\d{1,2}))?)?"
)


CLOCK_AUF = re.compile(r"\bauf (\d{1,2})(?:[:.](\d{2})(?: uhr)?| uhr(?: (\d{1,2}))?)")


def parse_clock(t: str, now: datetime.datetime, prefer_pm: bool = False):
    """Uhrzeit im Text -> (Zeitpunkt, Textstück) oder (None, ""). prefer_pm: "um 7" heute Abend, wenn es früh schon vorbei ist."""
    m = CLOCK.search(t)
    if m:
        mod, hour = m.group(1), int(m.group(2))
        minute = int(m.group(3) or m.group(4) or 0)
    else:
        m = CLOCK_AUF.search(t)
        if not m:
            return None, ""
        mod, hour, minute = None, int(m.group(1)), int(m.group(2) or m.group(3) or 0)
    if mod == "halb":
        hour, minute = hour - 1, 30
    elif mod == "viertel nach":
        minute = 15
    elif mod in ("viertel vor", "dreiviertel"):
        hour, minute = hour - 1, 45
    if re.search(r"abends|nachmittags|nachts", t) and 1 <= hour < 12:
        hour += 12
    hour %= 24
    if minute > 59:
        return None, ""
    rest = t.replace("guten morgen", " ")
    day_offset, explicit = 0, False
    if "übermorgen" in rest:
        day_offset, explicit = 2, True
    elif re.search(r"\bmorgen\b", rest):
        day_offset, explicit = 1, True
    elif "heute" in rest:
        explicit = True
    else:
        for i, name in enumerate(WEEKDAYS):
            if name in rest:
                day_offset, explicit = (i - now.weekday()) % 7 or 7, True
                break
    due = (now + datetime.timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due <= now and not explicit:
        evening = due.replace(hour=hour + 12) if (prefer_pm and 1 <= hour < 12) else None
        due = evening if evening and evening > now else due + datetime.timedelta(days=1)
    return due, m.group(0)


# --- Formulierungen ---------------------------------------------------------------------
def fmt_duration(sec: float) -> str:
    sec = int(round(sec))
    if sec < 1:
        return "weniger als eine Sekunde"
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    parts = []
    if h:
        parts.append(f"{h} Stunde" + ("n" if h != 1 else ""))
    if m:
        parts.append(f"{m} Minute" + ("n" if m != 1 else ""))
    if s and not h:
        parts.append(f"{s} Sekunde" + ("n" if s != 1 else ""))
    return " und ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + " und " + parts[-1]


def fmt_clock(dt: datetime.datetime, now: datetime.datetime = None) -> str:
    now = now or datetime.datetime.now()
    at = f"{dt.hour} Uhr" if dt.minute == 0 else f"{dt.hour}:{dt.minute:02d} Uhr"
    days = (dt.date() - now.date()).days
    if days == 1:
        return f"morgen um {at}"
    if days == 2:
        return f"übermorgen um {at}"
    if days > 2:
        return f"am {WEEKDAY_NAMES[dt.weekday()]} um {at}"
    return f"um {at}"


_SWAP = {"ich": "du", "mein": "dein", "meine": "deine", "meinen": "deinen", "meinem": "deinem", "meiner": "deiner",
         "mir": "dir", "mich": "dich", "muss": "musst", "soll": "sollst", "will": "willst", "kann": "kannst",
         "habe": "hast", "bin": "bist", "möchte": "möchtest"}


def _content(t: str, spans: list) -> str:
    for sp in spans:
        t = t.replace(sp, " ", 1)
    t = re.sub(r"\b(guten morgen|heute|übermorgen|morgen|abends|nachmittags|nachts)\b", " ", t)
    t = re.sub(r"\b(am |an )?(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b", " ", t)
    t = re.sub(r"\b(in|um)\b(?=\s*$)", " ", t)
    t = re.sub(r"^\W*(bitte\s+)?(erinnere|erinner)\w*\s+mich\s*", "", t.strip())
    t = re.sub(r"\b(bitte|doch|mal|noch)\b", " ", t)
    t = re.sub(r"^\W*(in|um)\s+", "", t.strip())
    m = re.match(r"^\W*(daran\s*)?(dass\s+)?(.*)$", t.strip())
    daran, dass, body = bool(m.group(1)), bool(m.group(2)), m.group(3)
    body = re.sub(r"^an\s+", "", body.strip())
    body = " ".join(_SWAP.get(w, w) for w in body.split()).strip(" .,:")
    if not body:
        return "etwas"
    if dass:
        return "dass " + body  # Nebensatz: "dass du den Müll rausbringen musst"
    return ("daran, " + body) if daran else body


def _restore_case(text: str, original: str) -> str:
    """Übernimmt die Schreibweise der Wörter aus dem Original (Hauptwörter groß)."""
    known = {}
    for w in re.findall(r"[\wäöüÄÖÜß]+", original):
        known.setdefault(w.lower(), w)
    return " ".join(known.get(w, w) for w in text.split(" "))


def _timer_name(t: str, spans: list) -> str:
    for sp in spans:
        t = t.replace(sp, " ", 1)
    m = re.search(r"\bfür (?!\d)(.+)$", t.strip())
    name = m.group(1) if m else ""
    name = re.sub(r"\b(bitte|auf|noch|mal)\b", " ", name)
    return " ".join(name.split())


# --- Sprachbefehle -------------------------------------------------------------------------
KEYWORDS = re.compile(r"\b(timer|stoppuhr|wecker|erinner\w*|weck mich)\b|weck mich")


def _describe(item: dict, now: datetime.datetime) -> str:
    due = datetime.datetime.fromtimestamp(item["due"])
    remaining = item["due"] - now.timestamp()
    if item["kind"] == "timer":
        who = f" für {item['text']}" if item["text"] else ""
        return f"Timer{who}, noch {fmt_duration(remaining)}"
    if item["kind"] == "alarm":
        return f"Wecker {fmt_clock(due, now)}"
    plain = re.sub(r"^(daran,\s*|dass\s+)", "", item["text"])
    return f"{plain} {fmt_clock(due, now)}"


def handle(text: str, now: datetime.datetime = None):
    """Verarbeitet Timer-, Wecker- und Erinnerungsbefehle. Gibt die Antwort zurück oder None."""
    if not KEYWORDS.search(text.lower()) or re.search(r"\bich erinnere mich\b", text.lower()):
        return None
    now = now or datetime.datetime.now()
    t = _prep(text)
    items = upcoming()

    # Löschen und Abbrechen
    if re.search(r"\b(lösch\w*|stopp|stoppe|stoppen|stop|brich|brech\w*|beend\w*|entfern\w*|vergiss|deaktivier\w*|aus|"
                 r"ausschalten|absag\w*|storniere\w*)\b", t):
        if "wecker" in t:
            kinds = {"alarm"}
        elif "timer" in t or "stoppuhr" in t:
            kinds = {"timer"}
        elif "erinnerung" in t or "erinner" in t:
            kinds = {"reminder"}
        else:
            kinds = {"timer", "alarm", "reminder"}
        hits = [i for i in items if i["kind"] in kinds]
        if not hits:
            return "Da läuft nichts, was ich löschen könnte."
        everything = bool(re.search(r"\b(alle|alles|sämtliche)\b|erinnerungen|timer\b.*\bund\b", t)) or len(hits) == 1
        ids = [i["id"] for i in (hits if everything else hits[:1])]
        n = remove(ids)
        return "Okay, gelöscht." if n == 1 else f"Okay, {n} Einträge gelöscht."

    # Übersicht und Restzeit
    if re.search(r"\b(welche|wie viele|zeig|zeige|was für|liste|habe ich|läuft|laufen|noch|restzeit|wie lange)\b", t) \
            and not parse_duration(t)[0] and not CLOCK.search(t):
        if not items:
            return "Es sind keine Timer, Wecker oder Erinnerungen gestellt."
        if re.search(r"wie lange|noch", t) and ("timer" in t or "stoppuhr" in t):
            timers = [i for i in items if i["kind"] == "timer"]
            if not timers:
                return "Es läuft gerade kein Timer."
            return f"Der Timer läuft noch {fmt_duration(timers[0]['due'] - now.timestamp())}."
        want = {"alarm"} if "wecker" in t else {"timer"} if ("timer" in t or "stoppuhr" in t) else \
            {"reminder"} if "erinner" in t else {"timer", "alarm", "reminder"}
        shown = [i for i in items if i["kind"] in want][:5]
        if not shown:
            return "Dazu ist nichts gestellt."
        lead = {"timer": "Laufende Timer", "alarm": "Wecker", "reminder": "Erinnerungen"}.get(next(iter(want)), "Offen") \
            if len(want) == 1 else "Offen"
        return f"{lead}: " + "; ".join(_describe(i, now) for i in shown) + "."

    seconds, spans = parse_duration(t)
    clock, clock_span = parse_clock(t, now, prefer_pm="wecker" not in t and "weck mich" not in t)

    # Wecker
    if "wecker" in t or "weck mich" in t:
        if clock:
            add("alarm", clock.timestamp(), "")
            return f"Wecker gestellt: {fmt_clock(clock, now)}."
        if seconds:
            due = now + datetime.timedelta(seconds=seconds)
            add("alarm", due.timestamp(), "")
            return f"Wecker gestellt: in {fmt_duration(seconds)}."
        return "Wann soll ich dich wecken? Sag zum Beispiel: Weck mich um 7 Uhr."

    # Timer
    if "timer" in t or "stoppuhr" in t:
        if not seconds:
            return "Wie lange soll der Timer laufen? Sag zum Beispiel: Timer auf 5 Minuten."
        name = _restore_case(_timer_name(t, spans), text)
        add("timer", now.timestamp() + seconds, name)
        who = f" für {name}" if name else ""
        return f"Timer{who} gestellt: {fmt_duration(seconds)}."

    # Erinnerung
    if re.search(r"\berinner\w* (mich|mir)\b", t) and not re.search(r"\bich erinner", t):
        if not seconds and not clock:
            return "Wann soll ich dich erinnern? Sag zum Beispiel: Erinnere mich in zehn Minuten an die Pizza."
        content = _restore_case(_content(t, spans + ([clock_span] if clock_span else [])), text)
        if seconds and not clock:
            due_dt = now + datetime.timedelta(seconds=seconds)
            add("reminder", due_dt.timestamp(), content)
            return f"Okay, ich erinnere dich in {fmt_duration(seconds)} {_to_phrase(content)}."
        add("reminder", clock.timestamp(), content)
        return f"Okay, ich erinnere dich {fmt_clock(clock, now)} {_to_phrase(content)}."
    return None


def _to_phrase(text: str) -> str:
    """Wie der Inhalt in "ich erinnere dich ..." eingebaut wird."""
    if text.startswith("dass "):
        return "daran, " + text
    return text if text.startswith("daran,") else "an " + text


def due_text(item: dict, late: float = 0) -> str:
    """Satz, der gesprochen wird, wenn ein Eintrag fällig ist."""
    prefix = "Verpasst: " if late > 90 else ""
    if item["kind"] == "timer":
        who = f" für {item['text']}" if item["text"] else ""
        return f"{prefix}Der Timer{who} ist abgelaufen."
    if item["kind"] == "alarm":
        due = datetime.datetime.fromtimestamp(item["due"])
        return f"{prefix}Wecker! Es ist {due.hour}:{due.minute:02d} Uhr."
    text = item["text"]
    if text.startswith("dass "):
        return f"{prefix}Erinnerung: Denk daran, {text}."
    if text.startswith("daran,"):
        return f"{prefix}Erinnerung: Denk {text}."
    return f"{prefix}Erinnerung: Denk an {text}."


class Scheduler(threading.Thread):
    """Prüft jede Sekunde, ob etwas fällig ist, und ruft on_due(eintrag, verspätung_in_sekunden) auf."""

    def __init__(self, on_due):
        super().__init__(daemon=True)
        self.on_due = on_due

    def run(self):
        time.sleep(3)  # erst den Start abwarten
        while True:
            try:
                for item, late in pop_due():
                    self.on_due(item, late)
            except Exception as e:
                print(f"Erinnerungen: {e}")
            time.sleep(1)
