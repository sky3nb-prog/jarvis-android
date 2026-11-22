"""
„Lies mir Faust vor und schick das als Sprachnachricht an TR9000“ – Jarvis lädt sich den echten (gemeinfreien)
Text von Projekt Gutenberg, liest ein Stück davon mit seiner Stimme vor und schickt es als Sprachnachricht über
WhatsApp (wortwörtlich, siehe pc_wavoice.py). Nur ein paar bekannte Klassiker hinterlegt (nicht irgendein Buch) –
und absichtlich nur ein Ausschnitt: das komplette Faust-Drama wären mehrere STUNDEN Audio, das würde WhatsApp und
Piper sprengen. Stattdessen der berühmte Eingangsmonolog ("Habe nun, ach! Philosophie ...").
"""
import html
import re
import time
import urllib.request

MAX_CHARS = 2600   # ungefähr 3-4 Minuten gesprochen – eine Sprachnachricht soll noch eine Sprachnachricht bleiben

WORKS = {
    "faust": {
        "name": "Faust (der Eingangsmonolog)",
        "url": "https://projekt-gutenberg.org/authors/johann-wolfgang-von-goethe/books/faust-eine-tragoedie/chapter/5",
        "start": "Habe nun, ach",
    },
}
_ALIAS = {"faust": "faust", "goethes faust": "faust", "den faust": "faust", "faust von goethe": "faust"}

PENDING = {"t": 0.0, "key": "", "an": ""}
SAY = None   # vom Programm gesetzt: Text ansagen (gleiches Muster wie pc_sticker.SAY)


def _lookup(name: str) -> str:
    n = name.strip(" .,!?").lower()
    n = re.sub(r"^(den|das|die)\s+", "", n)
    n = re.sub(r"\s+von\s+goethe$", "", n)
    return n if n in WORKS else (_ALIAS.get(name.strip(" .,!?").lower(), ""))


def _text_for(key: str) -> str:
    w = WORKS[key]
    req = urllib.request.Request(w["url"], headers={"User-Agent": "Mozilla/5.0 (Jarvis-PC)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode("utf-8", "replace")
    # grob: alle Tags raus, Entities auflösen, Whitespace glätten - reicht für Fließtext/Gedichtzeilen
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", raw))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    i = text.find(w["start"])
    if i < 0:
        raise RuntimeError("den Text konnte ich auf der Seite nicht finden")
    text = text[i:MAX_CHARS + i]
    # am letzten vollständigen Satzende abschneiden statt mitten im Wort
    cut = max(text.rfind(". "), text.rfind("! "), text.rfind("? "), text.rfind(".\n"))
    if cut > MAX_CHARS * 0.5:
        text = text[:cut + 1]
    return re.sub(r"\s+", " ", text).strip()


def _say(t: str):
    if SAY:
        try:
            SAY(t)
        except Exception:
            pass


def start(key: str, an: str) -> str:
    import threading
    import pc_wavoice
    w = WORKS[key]

    def run():
        try:
            text = _text_for(key)
        except Exception as e:
            _say(f"Den Text von {w['name']} konnte ich mir nicht holen ({e}).")
            return
        r = pc_wavoice.send(an, text, raw=True)
        _say(r)

    threading.Thread(target=run, daemon=True).start()
    return f"Okay, ich hol mir {w['name']} und schick's gleich als Sprachnachricht an {an} – das dauert einen Moment (Vorlesen + Versenden)."


def handle(command: str):
    """Sprachbefehl -> Antwort oder None."""
    global PENDING
    low = command.strip(" .!?,").lower()
    if PENDING["key"] and time.time() - PENDING["t"] < 90 and len(low.split()) <= 6:
        PENDING["t"] = 0
        an = re.sub(r"^(an|in|zu)\s+(die|den|der)?\s*", "", low).strip(" .")
        if an:
            raw = command.strip(" .!?,")
            an = raw[-len(an):] if raw.lower().endswith(an) else an
            return start(PENDING["key"], an)
        return None
    m = re.search(r"\blies?\s+(?:mir\s+)?(?:mal\s+)?(.+?)\s+vor\b"
                  r"(?:\s+und\s+schick(?:e)?\s+das\s+als\s+sprachnachricht\s+(?:(?:an|in)\s+(?:die|den|der)?\s*)?(.+))?$", low)
    if not m:
        return None
    key = _lookup(m.group(1))
    if not key:
        return None   # anderes Werk - nicht hinterlegt, lieber nichts sagen als falsch vorlesen
    an_low = (m.group(2) or "").strip(" .")
    if not an_low:
        PENDING.update(t=time.time(), key=key, an="")
        return f"Klar, {WORKS[key]['name']}. An wen soll ich das als Sprachnachricht schicken?"
    raw = command.strip(" .!?,")
    an = raw[-len(an_low):] if raw.lower().endswith(an_low) else an_low   # Groß-/Kleinschreibung wie gesagt
    try:
        import pc_gruppe
        an = pc_gruppe.resolve(an)
    except Exception:
        pass
    return start(key, an)
