"""
Eintragen und Tasten drücken, per Sprache, im Fenster, in dem du gerade bist:

  "Trag bitte meine E-Mail ein"      -> tippt deine gespeicherte E-Mail-Adresse in das Feld, in dem der Cursor steht
  "Gib meine Telefonnummer ein"      -> ebenso (auch Name, Vorname, Nachname, Adresse, Postleitzahl, Ort)
  "Drück Enter" / "Drück Tab"        -> drückt die Taste

Deine Daten trägst du in den Einstellungen unter "Meine Daten" ein oder sagst: "Meine E-Mail ist luca punkt muster at gmail punkt com".
Sie liegen nur in gedaechtnis.json auf diesem PC. Passwörter speichert und tippt Jarvis absichtlich nicht.
"""

import re
import time

import pc_memory

WORDS = "|".join(sorted((re.escape(w) for w in pc_memory.PROFILE_WORDS), key=len, reverse=True))
FILL = re.compile(
    rf"^(?:trag|trage|gib|gebe|schreib|schreibe|tipp|tippe|füg|füge|setz|setze)\w*\s+(?:bitte\s+|mal\s+|dort\s+|hier\s+|da\s+)*"
    rf"(?:meine?n?|mein)\s+(?P<what>{WORDS})(?:\s+(?:bitte|dort|hier|da|mal|jetzt))*(?:\s+(?:dort\s+|hier\s+|da\s+)?(?:ein|an|rein|hinein|ein\s+bitte))?$",
    re.I)
KEYS = {
    "enter": "enter", "eingabe": "enter", "return": "enter", "tab": "tab", "tabulator": "tab",
    "escape": "esc", "esc": "esc", "leertaste": "space", "löschen": "backspace", "rücktaste": "backspace",
    "pfeil runter": "down", "pfeil hoch": "up", "pfeil links": "left", "pfeil rechts": "right",
}
KEYCMD = re.compile(r"^(?:drück|drücke|druecke|drueck|tipp|tippe)\w*\s+(?:bitte\s+)?(?:die\s+)?(?:taste\s+)?(?P<k>[a-zäöüß ]+?)(?:\s+(?:taste|bitte))*$", re.I)


def fill(what: str) -> str:
    """Tippt einen Eintrag aus "Meine Daten" in das Feld, das gerade den Cursor hat."""
    import pc_messages

    field = pc_memory.PROFILE_WORDS.get(what.lower().strip(), what.lower().strip())
    value = pc_memory.profile(field)
    label = dict(pc_memory.PROFILE_FIELDS + [("name", "Name")]).get(field, field)
    if not value:
        return f"Deine {label} kenne ich noch nicht. Trag sie in den Einstellungen unter Meine Daten ein, oder sag zum Beispiel: Meine E-Mail ist …"
    pc_messages._paste(value)
    return f"Habe deine {label} eingetragen."


def press(key: str) -> str:
    import pyautogui

    name = KEYS.get(key.lower().strip())
    if not name:
        return ""
    pyautogui.press(name)
    return "Erledigt."


def handle(command: str):
    t = " ".join(command.strip(" .!?,").split())
    m = FILL.match(t)
    if m:
        return fill(m.group("what"))
    m = KEYCMD.match(t)
    if m and m.group("k").lower().strip() in KEYS:
        return press(m.group("k"))
    return None
