"""
Gedächtnis: Jarvis merkt sich, was du ihm sagst (Datei gedaechtnis.json neben dem Programm, nur auf diesem PC).

  "Merk dir, dass ich Cola Zero am liebsten mag"     -> speichert den Satz
  "Ich heiße Luca"                                   -> merkt sich deinen Namen
  "Was weißt du über mich?"                          -> liest vor, was er gespeichert hat
  "Vergiss, dass ich Cola mag" / "Vergiss alles"     -> löscht
  "Die Nummer von Mama ist 0170 1234567"             -> Kontakt für WhatsApp-Nachrichten

Die gespeicherten Sätze bekommt auch die KI (Gemini), damit Antworten persönlich werden. Dabei gehen sie zu Google.
Die Nummern der Kontakte bekommt die KI nicht.
"""

import json
import os
import re
import threading
import time

from pc_apps import base_dir

FILE = "gedaechtnis.json"
MAX_FACTS = 600
_LOCK = threading.Lock()


def path() -> str:
    return os.path.join(base_dir(), FILE)


def _load() -> dict:
    try:
        with open(path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data.get("facts"), list) and isinstance(data.get("contacts"), dict):
            return data
    except Exception:
        pass
    return {"facts": [], "contacts": {}, "profile": {}, "history": []}


def _save(data: dict):
    try:
        with open(path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Gedächtnis konnte nicht gespeichert werden: {e}")


def _clean(text: str) -> str:
    return " ".join(str(text).strip().strip(" ,.!?").split())


# --- Fakten ---------------------------------------------------------------------------------
def facts() -> list:
    with _LOCK:
        return [f["text"] for f in _load()["facts"]]


MONTHS = ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember"]


def parse_date(text: str):
    """Findet ein Datum wie "3. März" oder "12.5." im Text und gibt "MM-TT" zurück, sonst None."""
    low = text.lower().replace("maerz", "märz")
    m = re.search(r"\b(\d{1,2})\.?\s*(" + "|".join(MONTHS) + r")\b", low)
    if m:
        return f"{MONTHS.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(\d{1,2})\.\s*(\d{1,2})\.(?!\d)", low)
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(1)) <= 31:
        return f"{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def remember(text: str, date: str = None) -> str:
    text = _clean(text)
    if len(text) < 3:
        return "Was soll ich mir merken?"
    text = text[0].upper() + text[1:]
    if not date and re.search(r"geburtstag|jahrestag|hochzeitstag|termin", text, re.I):
        date = parse_date(text)
    if date and not re.fullmatch(r"\d{2}-\d{2}", str(date)):
        date = None
    with _LOCK:
        data = _load()
        if any(f["text"].lower() == text.lower() for f in data["facts"]):
            return "Das wusste ich schon."
        entry = {"text": text, "ts": int(time.time())}
        if date:
            entry["date"] = date
        data["facts"].append(entry)
        del data["facts"][:-MAX_FACTS]
        _save(data)
    return "Gemerkt."


def forget(query: str) -> int:
    words = [w for w in re.findall(r"[a-zäöüß0-9]{3,}", query.lower())]
    if not words:
        return 0
    with _LOCK:
        data = _load()
        keep = [f for f in data["facts"] if not any(w in f["text"].lower() for w in words)]
        removed = len(data["facts"]) - len(keep)
        data["facts"] = keep
        if removed:
            _save(data)
    return removed


def clear() -> int:
    with _LOCK:
        data = _load()
        n = len(data["facts"])
        data["facts"] = []
        _save(data)
    return n


def upcoming(days: int = 7) -> list:
    """Gemerkte Daten (Geburtstage usw.), die in den nächsten Tagen anstehen: [(Text, Tage bis dahin)]."""
    import datetime

    today, out = datetime.date.today(), []
    for f in _load()["facts"]:
        d = f.get("date")
        if not d:
            continue
        try:
            month, day = int(d[:2]), int(d[3:])
            when = datetime.date(today.year, month, day)
            if when < today:
                when = datetime.date(today.year + 1, month, day)
        except ValueError:
            continue
        if (when - today).days <= days:
            out.append((f["text"], (when - today).days))
    return sorted(out, key=lambda x: x[1])


def upcoming_text(days: int = 7) -> str:
    parts = []
    for text, n in upcoming(days):
        when = "heute" if n == 0 else "morgen" if n == 1 else f"in {n} Tagen"
        parts.append(f"{text} ({when})")
    return ("Übrigens, demnächst: " + "; ".join(parts) + ".") if parts else ""


def set_mood(text: str) -> str:
    """Wie der Nutzer gerade drauf ist (Jarvis merkt sich die letzten Stimmungen mit Datum)."""
    text = _clean(text)
    if len(text) < 2:
        return ""
    with _LOCK:
        data = _load()
        moods = data.get("moods") if isinstance(data.get("moods"), list) else []
        moods.append({"text": text, "ts": int(time.time())})
        data["moods"] = moods[-20:]
        _save(data)
    return ""


def moods_text() -> str:
    out = []
    for m in (_load().get("moods") or [])[-6:]:
        try:
            days = int((time.time() - m["ts"]) // 86400)
            when = "heute" if days == 0 else "gestern" if days == 1 else f"vor {days} Tagen"
            out.append(f"{when}: {m['text']}")
        except Exception:
            continue
    return "; ".join(out)


def load_history() -> list:
    return [h for h in _load().get("history", []) if isinstance(h, dict) and h.get("role") in ("user", "assistant")]


def save_history(history: list):
    with _LOCK:
        data = _load()
        data["history"] = history[-12:]
        _save(data)


def prompt_block() -> str:
    """Text für die KI: was Jarvis über den Nutzer weiß."""
    items = facts()[-250:]
    contacts = ", ".join(c.title() for c in _load()["contacts"])
    out = ""
    if items:
        out += "Das hat der Nutzer dir früher gesagt (\"ich/mein\" meint den Nutzer):\n" + "\n".join(f"- {t}" for t in items)
    if contacts:
        out += ("\n" if out else "") + f"Kontakte mit gespeicherter Nummer für WhatsApp: {contacts}."
    moods = moods_text()
    if moods:
        out += ("\n" if out else "") + f"So war der Nutzer zuletzt drauf: {moods}."
    return out


# --- Meine Daten (zum Eintragen in Formulare) ------------------------------------------------
PROFILE_FIELDS = [("vorname", "Vorname"), ("nachname", "Nachname"), ("email", "E-Mail"), ("telefon", "Telefonnummer"),
                  ("adresse", "Straße und Hausnummer"), ("plz", "Postleitzahl"), ("ort", "Ort")]
PROFILE_WORDS = {  # gesprochenes Wort -> Feld
    "e-mail": "email", "email": "email", "e-mail-adresse": "email", "emailadresse": "email", "mailadresse": "email",
    "mail": "email", "mail-adresse": "email", "e-mail adresse": "email", "email adresse": "email",
    "telefonnummer": "telefon", "telefon": "telefon", "handynummer": "telefon", "handy": "telefon", "nummer": "telefon",
    "vorname": "vorname", "nachname": "nachname", "familienname": "nachname", "name": "name", "namen": "name",
    "adresse": "adresse", "straße": "adresse", "strasse": "adresse", "postleitzahl": "plz", "plz": "plz",
    "wohnort": "ort", "ort": "ort", "stadt": "ort",
}


def profile(key: str) -> str:
    data = _load().get("profile", {})
    if key == "name":
        return " ".join(x for x in (data.get("vorname", ""), data.get("nachname", "")) if x)
    return data.get(key, "")


def set_profile(key: str, value: str) -> None:
    with _LOCK:
        data = _load()
        data.setdefault("profile", {})[key] = value.strip()
        _save(data)


def spoken_email(raw: str) -> str:
    """Macht aus "luca punkt muster at gmail punkt com" eine E-Mail-Adresse."""
    t = raw.strip().lower()
    t = re.sub(r"\s+(?:at|ät|ad|et|klammeraffe)\s+", "@", t)
    t = re.sub(r"\s+punkt\s+", ".", t)
    t = re.sub(r"\s+(?:minus|bindestrich)\s+", "-", t)
    t = re.sub(r"\s+(?:unterstrich)\s+", "_", t)
    return re.sub(r"\s+", "", t)


# --- Kontakte -------------------------------------------------------------------------------
def normalize_number(raw: str) -> str:
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    elif digits.startswith("0"):
        digits = "+49" + digits[1:]  # deutsche Nummer ohne Vorwahl
    elif not digits.startswith("+"):
        digits = "+" + digits
    return digits if len(re.sub(r"\D", "", digits)) >= 8 else ""


def set_contact(name: str, number: str) -> str:
    num = normalize_number(number)
    if not num:
        return "Die Nummer habe ich nicht richtig verstanden. Sag sie bitte nochmal Ziffer für Ziffer."
    with _LOCK:
        data = _load()
        data["contacts"][_clean(name).lower()] = num
        _save(data)
    return f"Okay, ich habe die Nummer von {_clean(name).title()} gespeichert."


def contact(name: str) -> str:
    key = _clean(name).lower()
    contacts = _load()["contacts"]
    return contacts.get(key) or next((n for k, n in contacts.items() if k in key.split()), "")


def pc_text_or(text: str, fallback: str) -> str:
    return text or fallback


# --- Sprachbefehle -------------------------------------------------------------------------
def handle(command: str):
    t = _clean(command)
    low = t.lower()

    m = re.match(r"^(?:merk|merke)\s+dir[,\s]+(?:bitte[,\s]+|mal[,\s]+|noch[,\s]+)*(?:dass\s+)?(.+)$", t, re.I) \
        or re.match(r"^(?:speicher|speichere)\s+(?:dir\s+)?(?:bitte\s+)?(?:ab\s*,?\s*)?(?:dass\s+)(.+)$", t, re.I)
    if m:
        return remember(m.group(1))

    m = re.match(r"^(?:ich heiße|ich heisse|mein name ist)\s+([A-ZÄÖÜa-zäöüß][\wäöüß\-]{1,20})$", t, re.I)
    if m:
        name = m.group(1).title()
        remember(f"Mein Name ist {name}")
        if not profile("vorname"):
            set_profile("vorname", name)
        return f"Freut mich, {name}. Ich merke mir das."
    m = re.match(r"^wann (?:habe ich|hab ich|hat (\w+)|haben (\w+)) geburtstag", low)
    if m:
        who = m.group(1) or m.group(2)
        hits = [x for x in facts() if "geburtstag" in x.lower() and (who.lower() in x.lower() if who else
                                                                      re.search(r"\b(ich|mein|meine|nutzer)\b", x, re.I))]
        return (" ".join(hits[-2:]) + ".") if hits else "Das hast du mir noch nicht gesagt."
    if re.search(r"was steht (in )?(den )?(nächsten|naechsten)? ?(tage|tagen|woche|zeit)? ?an\b|welche geburtstage", low):
        return pc_text_or(upcoming_text(30), "In den nächsten 30 Tagen steht nichts Gemerktes an.")
    if re.match(r"^wie (heiße|heisse) ich\b", low):
        for text in reversed(facts()):
            mm = re.match(r"^Mein Name ist (.+)$", text)
            if mm:
                return f"Du heißt {mm.group(1)}."
        return "Das hast du mir noch nicht gesagt."

    if re.search(r"was (weißt|weisst|wusstest|hast du dir gemerkt)|woran erinnerst du dich|was hast du (dir )?(über mich )?gespeichert", low) \
            and ("mich" in low or "gemerkt" in low or "gespeichert" in low):
        items = facts()
        if not items:
            return "Ich habe noch nichts über dich gespeichert. Sag zum Beispiel: Merk dir, dass ich gern Pizza esse."
        shown = items[-6:]
        return f"Ich habe mir {len(items)} {'Ding' if len(items) == 1 else 'Dinge'} gemerkt, zum Beispiel: " + "; ".join(shown) + "."

    if re.match(r"^vergiss\s+(?:bitte\s+)?(?:alles|alles was ich dir (?:gesagt|erzählt) habe|alle(?:s)? (?:fakten|infos|dinge))\b", low):
        n = clear()
        return f"Okay, ich habe alles vergessen ({n} Einträge)." if n else "Ich hatte nichts gespeichert."
    m = re.match(r"^vergiss\s+(?:bitte\s+)?(?:,?\s*dass\s+|das mit\s+|meinen?\s+|meine\s+)?(.+)$", t, re.I)
    if m and not re.search(r"timer|wecker|erinnerung|eingestellt", low):
        n = forget(m.group(1))
        return "Okay, vergessen." if n else "Dazu habe ich nichts gespeichert."

    m = re.match(r"^meine?n?\s+([a-zäöüß\- ]{2,25}?)\s+(?:ist|lautet)\s+(.+)$", t, re.I)
    if m and m.group(1).lower() in PROFILE_WORDS and PROFILE_WORDS[m.group(1).lower()] != "name":
        field, value = PROFILE_WORDS[m.group(1).lower()], m.group(2).strip()
        if field == "email":
            value = spoken_email(value)
            if "@" not in value:
                return "Die E-Mail-Adresse habe ich nicht verstanden. Trag sie am besten in den Einstellungen unter Meine Daten ein."
        elif field == "telefon":
            value = normalize_number(value) or value
        set_profile(field, value)
        label = dict(PROFILE_FIELDS).get(field, field)
        return f"Okay, deine {label} ist gespeichert."

    m = re.match(r"^(?:die\s+)?(?:handy|telefon|handynummer|telefonnummer|whatsapp)?\s*nummer\s+von\s+([\wäöüß ]{2,30}?)\s+ist\s+(.+)$", t, re.I) \
        or re.match(r"^([\wäöüß]{2,30}?)s\s+(?:handy|telefon)?nummer\s+ist\s+(.+)$", t, re.I)
    if m:
        return set_contact(m.group(1), m.group(2))
    return None
