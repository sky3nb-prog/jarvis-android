"""
Einfache Unterhaltung, Wetterfragen und Kopfrechnen, ganz ohne API-Schlüssel.

Beispiele: "Wie wird das Wetter morgen?", "Brauche ich heute einen Regenschirm?",
"Wie geht's dir?", "Wer bist du?", "Wie spät ist es?", "Erzähl mir einen Witz",
"Was ist 12 mal 7?". Alles, was hier nicht erkannt wird, kann (mit API-Schlüssel) Claude
frei beantworten.

answer(text) gibt den Antworttext zurück oder None, wenn nichts passt.
"""

import ast
import datetime
import operator
import random
import re
import time

import pc_info

# Werden aus den Einstellungen gesetzt
NAME = "J.A.R.V.I.S."  # wie er sich vorstellt
ADDRESS = ""  # Anrede, z. B. "Sir" oder dein Name
CITY = "Karlsruhe"  # Standardort für das Wetter

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]

_cache: dict = {}  # Ort -> (Zeitpunkt, Wetterdaten)


# --- Hilfen ------------------------------------------------------------------
def _norm(text: str) -> str:
    t = re.sub(r"[^\w\säöüß]", " ", text.lower())
    return re.sub(r"\s+", " ", t).strip()


def _sir() -> str:
    return f", {ADDRESS}" if ADDRESS else ""


def _name() -> str:
    n = NAME.replace(".", "").strip() or "Jarvis"
    return n.title() if n.isupper() else n


def _num(x: float) -> str:
    n = round(x)
    return f"minus {abs(n)}" if n < 0 else str(n)


def _fmt(x: float) -> str:
    return (str(int(x)) if float(x).is_integer() else f"{x:.4f}".rstrip("0").rstrip(".")).replace(".", ",")


def short_hello() -> str:
    h = datetime.datetime.now().hour
    return ("Guten Morgen" if h < 11 else "Guten Tag" if h < 18 else "Guten Abend") + _sir() + "."


def greeting() -> str:
    h = datetime.datetime.now().hour
    part = "Guten Morgen" if h < 11 else "Guten Tag" if h < 18 else "Guten Abend"
    return f"{part}{_sir()}. Alle Systeme sind bereit."


# --- Wetter ---------------------------------------------------------------------
WEATHER_WORDS = re.compile(
    r"\b(wetter|regnet|regen|regnen|regenschirm|schirm|schneit|schnee|sonnig|sonne|gewitter|"
    r"temperatur|grad|wie warm|wie kalt|windig|wind|bewölkt|wolkig|jacke)\b")


def get_weather(city: str) -> dict:
    now = time.time()
    hit = _cache.get(city.lower())
    if hit and now - hit[0] < 600:
        return hit[1]
    data = pc_info.fetch_weather(city)
    _cache[city.lower()] = (now, data)
    return data


def _parse_day(t: str):
    """Welcher Tag ist gemeint? Gibt (Abstand in Tagen oder 'woche', Bezeichnung) zurück."""
    t = t.replace("guten morgen", " ")
    today = datetime.date.today()
    if "übermorgen" in t or "uebermorgen" in t:
        return 2, "Übermorgen"
    if re.search(r"\bmorgen\b", t):
        return 1, "Morgen"
    for i, name in enumerate(WEEKDAYS):
        if name.lower() in t:
            delta = (i - today.weekday()) % 7
            return (delta, f"Am {name}") if delta else (0, "Heute")
    if "woche" in t or "nächsten tage" in t or "naechsten tage" in t:
        return "woche", "Diese Woche"
    return 0, "Heute"


def _parse_city(t: str, default: str) -> str:
    t = re.sub(r"\b(heute|morgen|übermorgen|jetzt|gerade|draußen|diese woche)\b", " ", t.replace("guten morgen", " "))
    m = re.search(r"\bin ([a-zäöüß][a-zäöüß\- ]{1,30}?)\s*$", t.strip())
    return m.group(1).strip().title() if m else default


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _day_answer(w: dict, idx: int, label: str) -> str:
    full = w["full"]
    if idx >= len(full):
        return "So weit reicht meine Vorhersage leider nicht."
    d = full[idx]
    out = f"{label} in {w['city']}: {_lower_first(d['text'])}, {_num(d['min'])} bis {_num(d['max'])} Grad."
    if d["rain"] is not None:
        out += (f" Die Regenwahrscheinlichkeit liegt bei {int(d['rain'])} Prozent." if d["rain"] >= 20
                else " Es bleibt voraussichtlich trocken.")
    return out


def weather_answer(text: str, on_wait=None) -> str:
    t = _norm(text)
    city = _parse_city(t, CITY)
    day, label = _parse_day(t)
    if on_wait:
        on_wait()
    try:
        w = get_weather(city)
    except ValueError:
        return f"Den Ort {city} kenne ich leider nicht."
    except Exception:
        return "Ich komme gerade nicht an die Wetterdaten."

    if day == "woche":
        parts = [f"{WEEKDAYS[d['weekday']]} {_lower_first(d['text'])}, {_num(d['min'])} bis {_num(d['max'])} Grad"
                 for d in w["full"][1:4]]
        return f"Die nächsten Tage in {w['city']}: " + "; ".join(parts) + "."

    if re.search(r"regen|regnet|regnen|schirm|schneit|schnee|gewitter", t):
        d = w["full"][day] if day < len(w["full"]) else None
        if not d:
            return "So weit reicht meine Vorhersage leider nicht."
        p = d["rain"]
        if p is None:
            wet = bool(re.search(r"regen|schauer|niesel|gewitter|schnee", d["text"].lower()))
            return f"{label} wird es in {w['city']} {'voraussichtlich nass' if wet else 'wohl trocken bleiben'}."
        tip = "Ein Schirm wäre keine schlechte Idee." if p >= 50 else "Ein Schirm ist wohl nicht nötig."
        return f"{label} liegt die Regenwahrscheinlichkeit in {w['city']} bei {int(p)} Prozent. {tip}"

    now_query = day == 0 and (re.search(r"\b(ist|gerade|jetzt|aktuell|draußen)\b", t)
                              or re.search(r"wie (warm|kalt)|wie viel grad|wie viele grad|temperatur", t))
    if now_query and not re.search(r"\bwird\b", t):
        out = f"In {w['city']} sind es gerade {_num(w['temp'])} Grad, {_lower_first(w['text'])}."
        if abs(w["feels"] - w["temp"]) >= 2:
            out += f" Gefühlt sind es {_num(w['feels'])} Grad."
        today = w["full"][0]
        return out + f" Heute werden es bis zu {_num(today['max'])} Grad."
    return _day_answer(w, day, label)


# --- Kopfrechnen ------------------------------------------------------------------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(b) > 10:
            raise ValueError("zu groß")
        return _OPS[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    raise ValueError("nicht erlaubt")


def math_answer(text: str):
    t = text.lower().replace(",", ".")
    if not re.search(r"\d", t) or not re.search(r"\b(was|wie viel|wieviel|rechne|berechne|wie viele)\b", t):
        return None
    t = re.sub(r"\b(was|wie viel|wieviel|wie viele|ist|sind|ergibt|macht|rechne|berechne|bitte|mal)\b", lambda m: " * " if m.group(0) == "mal" else " ", t)
    for word, op in ((" geteilt durch ", " / "), (" durch ", " / "), (" plus ", " + "), (" minus ", " - "),
                     (" multipliziert mit ", " * "), (" hoch ", " ** "), (" x ", " * ")):
        t = t.replace(word, op)
    expr = re.sub(r"[^\d+\-*/(). ]", " ", t).strip()
    if not re.search(r"\d\s*[+\-*/]+\s*\d", expr):
        return None
    try:
        value = _eval(ast.parse(expr, mode="eval").body)
    except ZeroDivisionError:
        return "Durch null kann man nicht teilen."
    except Exception:
        return None
    return f"Das ergibt {_fmt(value)}."


# --- Plauderei ----------------------------------------------------------------------
JOKES = [
    "Warum können Geister so schlecht lügen? Weil man sie so leicht durchschaut.",
    "Was sagt die Null zur Acht? Schicker Gürtel!",
    "Treffen sich zwei Magnete. Sagt der eine: Was soll ich heute nur anziehen?",
    "Was ist grün und steht vor der Tür? Ein Klopfsalat.",
    "Warum ist der Computer nie hungrig? Er hat immer genug Bytes.",
    "Wie nennt man einen Bumerang, der nicht zurückkommt? Stock.",
    "Was macht ein Pirat am Computer? Er drückt die Enter-Taste.",
    "Warum gehen Ameisen nicht in die Kirche? Weil sie in Sekten sind.",
]


def _time(_):
    return f"Es ist {time.strftime('%H:%M')} Uhr."


def _date(_):
    d = datetime.date.today()
    return f"Heute ist {WEEKDAYS[d.weekday()]}, der {d.day}. {MONTHS[d.month - 1]} {d.year}."


def _hello(t):
    h = datetime.datetime.now().hour
    if "guten morgen" in t:
        return f"Guten Morgen{_sir()}. Schön, dich zu hören."
    if "guten abend" in t:
        return f"Guten Abend{_sir()}."
    if "guten tag" in t:
        return f"Guten Tag{_sir()}."
    part = "Guten Morgen" if h < 11 else "Hallo" if h < 18 else "Guten Abend"
    return random.choice([f"{part}{_sir()}. Was kann ich für dich tun?", f"Hallo{_sir()}. Schön, dass du da bist."])


RULES = [
    (r"\b(hallo|hi|hey|servus|moin|grüß dich|grüß gott|guten morgen|guten tag|guten abend)\b", _hello),
    (r"wie geht es dir|wie geht s dir|wie geht s|wie geht es|alles klar bei dir|wie läuft s|na wie gehts",
     lambda t: random.choice([
         f"Mir geht es gut, danke der Nachfrage{_sir()}. Und dir?",
         "Alle Systeme laufen einwandfrei. Wie geht es dir?",
         "Bestens. Heute gab es noch keinen einzigen Absturz. Und bei dir?"])),
    (r"^(gut|prima|super|sehr gut|bestens|ganz gut|mir geht s gut|es geht mir gut|auch gut|alles gut|passt)$",
     lambda t: random.choice(["Das freut mich zu hören.", "Wunderbar, dann kann der Tag nur gut werden."])),
    (r"^(schlecht|nicht so gut|müde|traurig|gestresst|geht so|mies)$|mir geht es (nicht so gut|schlecht)",
     lambda t: "Das tut mir leid. Kann ich dir irgendwie helfen?"),
    (r"wer bist du|wie heißt du|stell dich vor|was bist du|wer ist da",
     lambda t: f"Ich bin {_name()}, dein persönlicher Assistent auf diesem PC. Ich öffne Programme, steuere Musik, "
               "beantworte einfache Fragen und sage dir das Wetter."),
    (r"was kannst du|was machst du|was kannst du alles|wofür bist du|hilfe$",
     lambda t: "Ich kann Programme und Ordner öffnen, Musik steuern, in Discord stummschalten, dir das Wetter, die Uhrzeit "
               "und das Datum sagen, kleine Rechenaufgaben lösen und mich mit dir unterhalten. Sag zum Beispiel: öffne Steam."),
    (r"\b(danke|dankeschön|vielen dank|danke dir|merci)\b",
     lambda t: random.choice([f"Gern geschehen{_sir()}.", "Jederzeit.", "Sehr gern."])),
    (r"witz|bring mich zum lachen|etwas lustiges|was lustiges", lambda t: random.choice(JOKES)),
    (r"wie spät|wie viel uhr|wieviel uhr|uhrzeit", _time),
    (r"welcher tag|welches datum|den wievielten|welchen tag haben|welcher wochentag|das datum|welcher monat", _date),
    (r"wie alt bist du|wann wurdest du|wann bist du entstanden",
     lambda t: "Ich bin ziemlich neu, aber ich lerne schnell."),
    (r"gute nacht|schlaf gut", lambda t: f"Gute Nacht{_sir()}. Schlaf gut."),
    (r"ich (liebe|mag) dich", lambda t: "Das ist sehr nett. Ich mag unsere Zusammenarbeit auch."),
    (r"du bist (gut|toll|super|klasse|der beste|genial|cool|nett|großartig)",
     lambda t: random.choice(["Vielen Dank, das freut mich.", "Sehr freundlich von dir."])),
    (r"du bist (dumm|schlecht|doof|blöd|nutzlos)",
     lambda t: "Das tut mir leid. Sag mir, was ich besser machen kann."),
    (r"hörst du mich|bist du da|bist du wach|bist du noch da", lambda t: f"Ja, ich bin da{_sir()}."),
    (r"münze|kopf oder zahl", lambda t: random.choice(["Kopf.", "Zahl."])),
    (r"würfel|würfle", lambda t: f"Es ist eine {random.randint(1, 6)}."),
    (r"was gibt s neues|was ist los|was geht ab", lambda t: "Alles ruhig auf diesem PC. Und bei dir?"),
    (r"langweilig", lambda t: "Soll ich dir einen Witz erzählen oder etwas Musik anmachen?"),
    (r"tschüss|auf wiedersehen|bis später|bis bald|ciao|bis dann", lambda t: f"Bis später{_sir()}."),
]


FAST_ONLY = ("wie spät", "welcher tag", "münze", "würfel", "hörst du mich")  # bleiben auch mit KI sofort


def answer(text: str, on_wait=None, ai: bool = False):
    """Antwort auf eine einfache Frage oder Plauderei, sonst None.
    ai=True: Plaudern übernimmt die KI (mit Persönlichkeit und Gedächtnis); nur Uhrzeit, Datum usw. bleiben hier."""
    t = _norm(text)
    if not t:
        return None
    if WEATHER_WORDS.search(t):
        return weather_answer(text, on_wait)
    calc = math_answer(text)
    if calc:
        return calc
    for pattern, reply in RULES:
        if ai and not any(k in pattern for k in FAST_ONLY):
            continue
        if re.search(pattern, t):
            return reply(t) if callable(reply) else reply
    return None
