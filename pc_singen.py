"""
„Sing mal Happy Birthday für Mika in der Gruppe“ / „Sing mir mal 2 Zeilen von Jingle Bells“ – Jarvis „singt“
mit seiner Stimme (Piper). WICHTIG, ehrlich gesagt: Piper ist eine Text-Vorlese-Stimme, keine Gesangsstimme –
er trägt den Text rhythmisch/mit Betonung vor, trifft aber keine echte Melodie/Tonhöhe wie ein Mensch beim Singen.
Für echten Gesang bräuchte man eine andere (deutlich aufwändigere) Technik, die hier nicht eingebaut ist.

Nur Lieder, die wirklich gemeinfrei sind, sind hinterlegt (Geburtstag + ein paar Weihnachtsklassiker) – aktuelle,
noch geschützte Songs (z. B. "All I Want for Christmas Is You") darf Jarvis nicht mit dem echten Text nachsingen,
das sagt er dann auch so.

  "Sing mal Happy Birthday für Mika"              -> für mich (lokal über die Lautsprecher)
  "Sing mal Happy Birthday für Mika in der Gruppe" -> als WhatsApp-Sprachnachricht an "die Gruppe" (siehe pc_gruppe)
  "Sing mal Jingle Bells an Jannis"                -> als Sprachnachricht an Jannis
"""
import re
import threading

SAY = None   # vom Programm gesetzt: Text lokal ansagen/sprechen (gleiches Muster wie pc_sticker.SAY)

# Nur gemeinfreie Texte. Platzhalter {name} wird ersetzt, wenn eine Widmung dabei ist.
SONGS = {
    "happy birthday": {
        "aliases": ["happy birthday", "geburtstagslied", "geburtstagssong"],
        "mit_name": "Happy birthday to you, happy birthday to you, happy birthday dear {name}, happy birthday to you!",
        "ohne_name": "Happy birthday to you, happy birthday to you, happy birthday to you!",
        "intro": "Für dich, {name}!",
        "outro": "Hoch, hoch, hoch!",
    },
    "hoch soll er leben": {
        "aliases": ["hoch soll er leben", "hoch soll sie leben", "hoch soll er sie leben"],
        "mit_name": "Hoch soll {name} leben, hoch soll {name} leben, dreimal hoch!",
        "ohne_name": "Hoch soll er leben, hoch soll er leben, dreimal hoch!",
        "intro": "", "outro": "",
    },
    "jingle bells": {
        "aliases": ["jingle bells"],
        "ohne_name": "Jingle bells, jingle bells, jingle all the way! Oh what fun it is to ride in a one-horse open sleigh!",
        "intro": "", "outro": "",
    },
    "stille nacht": {
        "aliases": ["stille nacht", "silent night"],
        "ohne_name": "Stille Nacht, heilige Nacht, alles schläft, einsam wacht nur das traute, hochheilige Paar.",
        "intro": "", "outro": "",
    },
    "o tannenbaum": {
        "aliases": ["o tannenbaum", "oh tannenbaum"],
        "ohne_name": "O Tannenbaum, o Tannenbaum, wie treu sind deine Blätter.",
        "intro": "", "outro": "",
    },
    "we wish you a merry christmas": {
        "aliases": ["we wish you a merry christmas"],
        "ohne_name": "We wish you a merry Christmas, we wish you a merry Christmas, we wish you a merry Christmas and a happy new year!",
        "intro": "", "outro": "",
    },
}
_NICHT_FREI = ["all i want for christmas", "last christmas", "feliz navidad", "rockin' around the christmas tree",
               "driving home for christmas", "fairytale of new york"]

TRIGGER = re.compile(r"\bsing\w*\b", re.I)
PENDING = {"t": 0.0, "song": "", "name": "", "an": ""}


def _lookup(frag: str) -> str:
    f = frag.strip(" .,!?").lower()
    for key, s in SONGS.items():
        if any(a in f or f in a for a in s["aliases"]):
            return key
    return ""


def _lyrics(key: str, name: str) -> str:
    s = SONGS[key]
    body = s["mit_name"].format(name=name) if name and "mit_name" in s else s["ohne_name"]
    parts = [p.format(name=name) for p in (s.get("intro", ""), body, s.get("outro", "")) if p]
    return " ".join(parts)


def _say(t: str):
    if SAY:
        try:
            SAY(t)
        except Exception:
            pass


def _do(key: str, name: str, an: str):
    text = _lyrics(key, name)
    if not an:
        _say(text)   # für mich: ganz normal laut über die Lautsprecher
        return
    try:
        import pc_wavoice
        r = pc_wavoice.send(an, text, raw=True)
        _say(r)
    except Exception as e:
        _say(f"Das Singen als Sprachnachricht hat nicht geklappt: {e}")


def handle(command: str):
    """Sprachbefehl -> Antwort oder None. Läuft im Hintergrund (Piper braucht ein paar Sekunden)."""
    low = command.strip(" .!?,").lower()
    if not TRIGGER.search(low):
        return None
    for bad in _NICHT_FREI:
        if bad in low:
            return (f"„{bad.title()}“ ist noch geschützt (ganz normaler aktueller Song) – den echten Text darf ich dafür "
                     "nicht nachsingen. Klassiker wie Happy Birthday, Jingle Bells, Stille Nacht oder O Tannenbaum gehen aber.")
    name = ""
    m_name = re.search(r"\bfür\s+(?!mich\b|uns\b)([A-Za-zÄÖÜäöüß-]+)\b", low)
    rest = low
    if m_name:
        name = m_name.group(1)
        rest = low[:m_name.start()] + low[m_name.end():]
    an = ""
    m_an = re.search(r"\b(?:in|an)\s+(?:die|den|der)?\s*(gruppe\w*|[A-Za-zÄÖÜäöüß0-9]+)\b", rest)
    if m_an:
        an = m_an.group(1)
        rest = rest[:m_an.start()] + rest[m_an.end():]
        try:
            import pc_gruppe
            an = pc_gruppe.resolve(an)
        except Exception:
            pass
    song_frag = re.sub(r"^.*?\bsing\w*\b", "", rest, flags=re.I)
    song_frag = re.sub(r"^\s*(mal|mir|bitte|doch|einmal|von)\s+", "", song_frag).strip(" .,!?")
    key = _lookup(song_frag)
    if not key:
        return ("Das Lied kenn ich nicht (nur gemeinfreie Klassiker: Happy Birthday, Jingle Bells, Stille Nacht, "
                "O Tannenbaum, We Wish You A Merry Christmas) – und ich trage es vor, singe aber nicht wirklich "
                "mit Melodie, nur meine normale Stimme im Rhythmus.") if "sing" in low and len(song_frag) > 1 else None
    threading.Thread(target=_do, args=(key, name, an), daemon=True).start()
    ziel = f" an {an}" if an else " – gleich hörst du's"
    return f"Klar{ziel}." if an else "Klar, einen Moment – ich bin keine echte Gesangsstimme, aber ich geb mein Bestes:"
