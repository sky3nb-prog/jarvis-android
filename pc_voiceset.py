"""
Einstellungen per Sprache ändern. Sie gelten sofort und werden gespeichert.

Beispiele (jeweils nach dem Aktivierungswort):
- "Dein Aktivierungswort ist ab jetzt Friday"      / "Ändere dein Weckwort zu Friday"
- "Füge Jay als Aktivierungswort hinzu"            (zusätzliches Wort, das alte bleibt)
- "Dein Name ist ab jetzt Friday"                  (so stellt er sich vor, steht im HUD)
- "Nenn mich Luan" / "Nenn mich Sir"               (Anrede)
- "Mein Wohnort ist Stuttgart"                     (Wetter, lokale Nachrichten)
- "Sprich schneller" / "Sprich langsamer"           / "Mach den Wecksound leiser"
- "Hör nach einem Befehl 8 Sekunden weiter"
- "Nimm die Stimme George"                          (ElevenLabs-Stimme) / "Nimm die normale Stimme"
- "Mach den Globus blau" / "Zeig den Globus als Satellit" / "Hologramm"
- "Mach das Briefing beim Start aus" / "... an"
- "Mach das HUD violett" (Farbe von HUD und Overlay)

handle(text, settings) gibt die Antwort zurück (oder None) und meldet die Änderungen über
pc_steuerung.request_setting (die Hauptschleife speichert und übernimmt sie sofort).
"""

import re

import pc_eleven
import pc_settings
import pc_steuerung

FILLER = r"(?:\s+(?:bitte|jetzt|mal|ab jetzt|ab sofort|von jetzt an|einfach))*"
WAKE_SET = [
    re.compile(r"(?:dein|das|mein|unser)?\s*(?:aktivierungs|weck|code|start)wort\s+(?:ist|lautet|soll|wird|heißt)"
               + FILLER + r"\s+(?:ab jetzt\s+|ab sofort\s+|jetzt\s+)?[„\"']?(?P<w>[\wäöüß\- ]{2,30}?)[“\"']?"
               r"(?:\s+sein|\s+lauten|\s+heißen)?$"),
    re.compile(r"(?:ändere|änder|setz|setze|stell|stelle|mach|mache)\w*\s+(?:dein|das|mein)?\s*(?:aktivierungs|weck|code)wort"
               + FILLER + r"\s+(?:auf|zu|in)\s+[„\"']?(?P<w>[\wäöüß\- ]{2,30}?)[“\"']?(?:\s+um)?$"),
    re.compile(r"(?:hör|höre)\s+(?:ab jetzt|ab sofort|von jetzt an|nur noch)\s+auf\s+(?:den namen\s+|das wort\s+)?"
               r"[„\"']?(?P<w>[\wäöüß\- ]{2,30}?)[“\"']?$"),
]
WAKE_ADD = re.compile(r"(?:füg|füge|nimm)\w*\s+[„\"']?(?P<w>[\wäöüß\- ]{2,30}?)[“\"']?\s+(?:als|zum|zu den)\s+"
                      r"(?:zusätzliche[sn]?\s+)?(?:aktivierungs|weck)w(?:ort|örter)n?\s*(?:hinzu|dazu|auf)?$")
NAME_SET = re.compile(r"(?:dein name|du heißt)\s+(?:ist|lautet)?" + FILLER + r"\s*[„\"']?(?P<w>[\wäöüß\.\- ]{2,30}?)[“\"']?$|"
                      r"(?:nenn|nenne)\s+dich\s+(?:ab jetzt\s+|ab sofort\s+)?[„\"']?(?P<w2>[\wäöüß\.\- ]{2,30}?)[“\"']?$")
ADDR_SET = re.compile(r"(?:nenn|nenne|sprich)\s+mich\s+(?:ab jetzt\s+|ab sofort\s+|bitte\s+)*(?:mit\s+)?[„\"']?"
                      r"(?P<w>[\wäöüß\.\- ]{2,30}?)[“\"']?(?:\s+an)?$")
ADDR_OFF = re.compile(r"(?:sprich|nenn)\s+mich\s+(?:ohne|nicht mehr mit)\s+(?:namen|anrede)")
CITY_SET = re.compile(r"(?:mein wohnort|ich wohne|mein ort|meine stadt|wetter ?ort|standort)\w*\s+(?:ist|in|lautet|auf)?"
                      + FILLER + r"\s*(?:in\s+)?(?P<w>[a-zäöüß][\wäöüß\- ]{1,30}?)$|"
                      r"(?:stell|setz|ändere)\w*\s+(?:den |meinen )?(?:wetter ?ort|wohnort|standort)\s+(?:auf|zu|nach)\s+"
                      r"(?P<w2>[a-zäöüß][\wäöüß\- ]{1,30}?)$")
FOLLOW_SET = re.compile(r"(?:hör|höre)\w*\s+(?:nach (?:einem|jedem) befehl\s+)?(?P<n>\d{1,2}|eine|zwei|drei|vier|fünf|sechs|"
                        r"sieben|acht|neun|zehn|zwölf|fünfzehn)\s+sekunden?\s+(?:lang\s+)?weiter")
NUM = {"eine": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
       "zwölf": 12, "fünfzehn": 15}
GLOBE_COLORS = {"orange": "Glut", "rot": "Glut", "glut": "Glut", "wie im video": "Glut", "blau": "Jarvis", "cyan": "Jarvis",
                "türkis": "Jarvis", "jarvis": "Jarvis", "grün": "Radar", "radar": "Radar", "lila": "Violett",
                "violett": "Violett", "pink": "Violett"}
HUD_COLORS = {"cyan": "Cyan", "türkis": "Cyan", "blau": "Blau", "violett": "Violett", "lila": "Violett", "rosa": "Rosa",
              "pink": "Rosa", "rot": "Rot", "orange": "Orange", "gold": "Gold", "gelb": "Gold", "grün": "Grün"}


def _clean_word(w: str) -> str:
    w = re.sub(r"\b(bitte|jetzt|ab|sofort|einfach|mal|okay)\b", " ", w.strip(" .,!?„“\"'"), flags=re.I)
    return " ".join(w.split())


_CITY_FILLER = {"für", "fürs", "alle", "alles", "die", "das", "den", "dem", "der", "nachrichten", "news", "wetter",
                "karte", "lokale", "lokalen", "und", "mein", "meine", "meinen", "standort", "wohnort", "ort", "stadt",
                "ist", "soll", "sein", "immer", "überall", "auf", "zu", "nach", "bei", "von"}


def _set(key, value):
    pc_steuerung.request_setting(key, value)


def handle(text: str, settings: dict):
    low = " ".join(re.sub(r"[.,!?]", " ", text.lower()).split())
    if not low:
        return None

    if re.search(r"(?:was|wie) (?:ist|lautet|heißt) (?:dein|das) (?:aktivierungs|weck)wort|auf welche[sn]? (?:wort|namen) hörst du", low):
        words = settings.get("wake_words") or ["jarvis"]
        return "Ich höre auf " + " und ".join(w.title() for w in words) + "."

    # Aktivierungswort hinzufügen
    m = WAKE_ADD.search(low)
    if m and re.search(r"aktivierungs|weck", low):
        w = _clean_word(m.group("w")).lower()
        if len(w) < 3:
            return "Das Wort ist mir zu kurz, dann würde ich ständig aus Versehen reagieren."
        words = [x for x in settings.get("wake_words", ["jarvis"]) if x]
        if w not in words:
            words.append(w)
        _set("wake_words", words)
        return f"Erledigt. Ich höre jetzt auf {', '.join(words[:-1])} und {words[-1]}." if len(words) > 1 \
            else f"Erledigt. Ich höre jetzt auf {w}."

    # Aktivierungswort ersetzen
    for pat in WAKE_SET:
        m = pat.search(low)
        if m:
            w = _clean_word(m.group("w")).lower()
            if len(w) < 3:
                return "Das Wort ist mir zu kurz, dann würde ich ständig aus Versehen reagieren. Nimm ein längeres."
            if len(w.split()) > 3:
                return "Das ist mir zu lang. Nimm ein Wort oder einen kurzen Namen."
            _set("wake_words", [w])
            return (f"Erledigt. Ab sofort höre ich auf {w.title()}. Auf das alte Wort reagiere ich nicht mehr. "
                    f"Falls ich dich damit schlecht verstehe, kannst du es in den Einstellungen unter Zuhören ändern.")

    # Name des Assistenten
    m = NAME_SET.search(low)
    if m:
        w = _clean_word(m.group("w") or m.group("w2") or "")
        if len(w) >= 2:
            _set("assistant_name", w.upper() if w.replace(".", "").isalpha() and len(w) <= 8 else w.title())
            return (f"Sehr gern, ab jetzt heiße ich {w.title()}. Mein Aktivierungswort bleibt gleich. "
                    f"Wenn ich auch auf {w.title()} hören soll, sag: Dein Aktivierungswort ist {w.title()}.")

    # Anrede
    if ADDR_OFF.search(low):
        _set("address_as", "")
        return "In Ordnung, ich spreche dich ohne Anrede an."
    m = ADDR_SET.search(low)
    if m:
        w = _clean_word(m.group("w"))
        if 2 <= len(w) <= 25 and not re.search(r"\b(später|morgen|heute|wenn|in \d)", w):
            _set("address_as", w.title() if w.lower() != "sir" else "Sir")
            return f"Sehr wohl, {w.title() if w.lower() != 'sir' else 'Sir'}."

    # Wohnort / Wetterort
    m = CITY_SET.search(low)
    if m:
        w = _clean_word(m.group("w") or m.group("w2") or "")
        # Füllwörter raus: "für alle Nachrichten Leonberg" -> "Leonberg"
        w = " ".join(x for x in w.split() if x.lower() not in _CITY_FILLER)
        if 2 <= len(w) <= 30:
            _set("weather_city", w.title())
            _set("home_city", w.title())
            return f"Notiert. Wetter, Karte und lokale Nachrichten kommen ab jetzt aus {w.title()}."

    # Weiterhören
    m = FOLLOW_SET.search(low)
    if m:
        n = m.group("n")
        n = int(n) if n.isdigit() else NUM.get(n, 5)
        n = max(0, min(15, n))
        _set("followup_seconds", n)
        return f"Okay, nach einem Befehl höre ich noch {n} Sekunden weiter zu."

    # Sprechtempo
    if re.search(r"sprich\w*\s+(?:etwas |ein bisschen |viel )?(schneller|langsamer)|rede\w*\s+(?:etwas )?(schneller|langsamer)", low):
        faster = "schneller" in low
        rate = max(-10, min(10, int(settings.get("voice_rate", 0)) + (2 if faster else -2)))
        _set("voice_rate", rate)
        return "Gern, ich spreche jetzt etwas schneller." if faster else "Gern, ich spreche jetzt etwas langsamer."

    # Wecksound
    m = re.search(r"(?:wecksound|aktivierungs ?sound|piep\w*|ton beim aktivieren)\s+(?:etwas |viel )?(lauter|leiser)|"
                  r"mach\w*\s+(?:den |das )?(?:wecksound|aktivierungs ?sound|piepen)\s+(?:etwas |viel )?(lauter|leiser|aus)", low)
    if m:
        what = m.group(1) or m.group(2)
        vol = int(settings.get("chime_volume", 45))
        vol = 0 if what == "aus" else max(0, min(100, vol + (15 if what == "lauter" else -15)))
        _set("chime_volume", vol)
        return "Der Wecksound ist aus." if vol == 0 else f"Der Wecksound ist jetzt auf {vol} Prozent."

    # Stimme (ElevenLabs)
    m = re.search(r"(?:nimm|nehm|wechsel\w*|benutz\w*|verwende\w*)\s+(?:zu\s+)?(?:die\s+)?(?:stimme\s+(?:von\s+)?)?"
                  r"(?P<w>[a-zäöü]+)(?:\s+als stimme|\s+stimme)?$", low)
    if m and "stimme" in low:
        w = m.group("w")
        if w in ("normale", "alte", "kostenlose", "microsoft", "online"):
            _set("voice_engine", "auto")
            return "Okay, ich nehme wieder die normale Online-Stimme."
        if w in ("elevenlabs", "eleven", "gute", "neue", "realistische"):
            _set("voice_engine", "eleven")
            return "Okay, ich spreche wieder mit der ElevenLabs-Stimme."
        for label, vid in pc_eleven.DEFAULT_VOICES:
            if label.lower().startswith(w):
                _set("voice_engine", "eleven")
                _set("eleven_voice", vid)
                _set("eleven_voice_name", label)
                return f"So klinge ich jetzt mit der Stimme {label.split(' –')[0]}. Wie gefällt sie dir?"
        names = ", ".join(lbl.split(" –")[0] for lbl, _ in pc_eleven.DEFAULT_VOICES)
        return f"Die Stimme {w.title()} kenne ich nicht. Zur Auswahl stehen {names}."

    # HUD-Modus
    if re.search(r"fokus ?-?modus|^fokus$|nur (?:noch )?(?:die|deine) kugel", low):
        _set("hud_mode", "fokus")
        return "Fokus-Modus. Nur noch ich."
    if re.search(r"info ?-?modus|^info$|zeig (?:wieder )?alle infos", low):
        _set("hud_mode", "info")
        return "Info-Modus. Alle Anzeigen sind zurück."
    if re.search(r"lage ?-?modus|globus ?-?modus", low):
        _set("hud_mode", "lage")
        return "Lage-Modus. Die Weltlage ist neben mir."
    # Farbe der Kugel
    m = re.search(r"(?:kugel|sphäre|kern)\w*\s+(?:in\s+|auf\s+)?(?P<w>gold|golden|orange|cyan|blau|türkis|rot|grün|lila|violett|weiß)|"
                  r"(?:mach|färb|stell)\w*\s+(?:dich|die kugel|deine kugel)\s+(?:in\s+|auf\s+)?(?P<w2>gold|golden|orange|cyan|"
                  r"blau|türkis|rot|grün|lila|violett|weiß)", low)
    if m:
        w = m.group("w") or m.group("w2")
        name = {"gold": "Gold", "golden": "Gold", "orange": "Gold", "cyan": "Cyan", "blau": "Cyan", "türkis": "Cyan",
                "rot": "Rot", "grün": "Grün", "lila": "Violett", "violett": "Violett", "weiß": "Weiß"}[w]
        _set("sphere_color", name)
        return f"Einen Moment, ich forme mich neu in {name}." if name != "Gold" else "Zurück zu Gold."

    # Karte / Globus
    if re.search(r"globus|weltkarte|\bkarte\b", low):
        if re.search(r"satellit|echt|realistisch|google", low):
            _set("map_style", "Satellit")
            return "Die Karte zeigt jetzt echte Satellitenbilder."
        if re.search(r"dunkel|hologramm|schlicht|einfarbig", low):
            _set("map_style", "Dunkel")
            return "Die Karte ist jetzt dunkel in deiner Farbe."
        if re.search(r"ortsnamen|beschriftung|städtenamen", low):
            on = not re.search(r"\b(aus|weg|ohne|keine)\b", low)
            _set("map_labels", on)
            return "Ortsnamen sind an." if on else "Ortsnamen sind aus."
        for word, theme in GLOBE_COLORS.items():
            if re.search(r"\b" + word + r"\b", low):
                _set("globe_theme", theme)
                return f"Die Karte leuchtet jetzt in {word}."
        if re.search(r"vollbild", low):
            on = not re.search(r"\b(nicht|kein|aus)\b", low)
            _set("globe_fullscreen", on)
            return "Die Karte öffnet sich ab jetzt im Vollbild." if on else "Die Karte öffnet sich wieder als Fenster."

    # Briefing beim Start
    if re.search(r"briefing|lagebericht", low) and re.search(r"start|anfang|hochfahren", low):
        on = not re.search(r"\b(aus|nicht|kein|keins|keinen|weg|deaktivier\w*|abschalt\w*)\b", low)
        _set("briefing_on_start", on)
        return "Beim Start bekommst du ab jetzt ein kurzes Lage-Briefing." if on else "Okay, beim Start gibt es kein Briefing mehr."

    # Farbe von HUD und Overlay
    m = re.search(r"(?:mach|färb|stell)\w*\s+(?:das |dein |die )?(?:hud|oberfläche|overlay|design|farbe)\w*\s+"
                  r"(?:auf\s+|in\s+)?(?P<w>[a-zäöü]+)$", low)
    if m and m.group("w") in HUD_COLORS:
        name = HUD_COLORS[m.group("w")]
        if name in pc_settings.THEMES:
            _set("accent", name)
            return f"Erledigt, alles leuchtet jetzt in {name}."
    return None
