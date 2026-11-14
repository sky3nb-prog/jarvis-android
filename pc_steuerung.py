"""
Kleine PC-Steuerung per Texteingabe (Windows).

Start:   python pc_steuerung.py
Setup:   pip install pyautogui

Feste Befehle (funktionieren ohne API-Key):
    musik                  -> Deezer öffnen und ganz nach vorn holen
    eins weiter / eins zurück   -> nächster / vorheriger Titel
    öffne <irgendein Programm, Ordner oder eigener Name>
                           -> findet alle installierten Programme selbst und holt sie nach vorn
                              (eigene Dateien/Ordner/Webseiten: Datei meine_befehle.json)
    öffne discord | öffne steam | öffne chrome ...  (mit Sonderbehandlung, kommen immer nach vorn)
    komplett stummschalten / beende komplettes stummschalten
                           -> in Discord Mikrofon UND Ton aus / wieder an
    komplettes stummschalten umschalten -> einfach umschalten, falls der Zustand nicht stimmt
    mikrofon aus / mikrofon an          -> in Discord nur das Mikrofon
    gurken                 -> in Discord in den Sprachkanal "Gurken" gehen
    zeig die oberfläche / hud  -> großes HUD-Fenster öffnen (schließen: hud schließen)
    öffne deine einstellungen  -> Einstellungen von Jarvis (Weckwort, Stimme, Anzeige ...)
    wie wird das wetter (morgen) / wie geht's dir / wie spät ist es / erzähl einen witz  -> Unterhaltung
    fahr den pc herunter / starte den pc neu / sperr den pc / ruhezustand  -> Energie (fragt vorher nach)
    sei still / sprich wieder / ändere die farbe auf grün  -> Einstellungen per Sprache
    beende dich            -> Assistent komplett beenden
    youtube <suche>        -> sucht und startet das erste Video
    musik / pause / play   -> Wiedergabe starten/pausieren (Medientaste)
    weiter / zurück        -> nächster / vorheriger Titel
    lauter / leiser / stumm
    url <adresse>          -> Webseite öffnen
    hilfe | ende

KI-Modus (freie Sätze): Gemini-Schlüssel (GEMINI_API_KEY oder in den Einstellungen unter KI).
Dann wird alles, was kein fester Befehl ist, von Claude in Aktionen übersetzt.
"""

import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
import webbrowser

import pyautogui

import pc_ai
import pc_cancel
import pc_input
import pc_memory
import pc_download
import pc_route
import pc_messages
import pc_settings
import pc_talk

# --- Programme: Name -> Startbefehl (URI-Protokolle oder Programmnamen) ---
APPS = {
    "discord": "discord://",
    "spotify": "spotify:",
    "chrome": "chrome",
    "notepad": "notepad",
    "rechner": "calc",
    "explorer": "explorer",
    "steam": "steam://open/main",
    "deezer": "deezer://",
}

# Wie die Spracherkennung manche Wörter versteht -> richtiger Programmname
APP_ALIASES = {
    "musik": "deezer",
    "music": "deezer",
    "dieser": "deezer",  # "Deezer" wird oft als "dieser" verstanden
    "diser": "deezer",
    "dizer": "deezer",
    "diskord": "discord",
    "stim": "steam",
    "stiem": "steam",
}

# Prozessnamen, an denen das Programmfenster erkannt wird (zum Nach-vorn-Holen)
PROCESS_NAMES = {
    "discord": ["discord.exe"],
    "spotify": ["spotify.exe"],
    "chrome": ["chrome.exe"],
    "steam": ["steam.exe", "steamwebhelper.exe"],
    "notepad": ["notepad.exe"],
    "deezer": ["deezer.exe"],
}

# Zusätzlich Fenster finden, deren Titel das enthält (z. B. Deezer im Browser)
TITLE_HINTS = {"deezer": "deezer"}
# Wenn das Programm sich nicht starten lässt, stattdessen diese Webseite öffnen
WEB_FALLBACK = {"deezer": "https://www.deezer.com"}

# Discord-Sprachkanäle: Sprachbefehl -> (Kanalname, Servername oder "")
# Den Servernamen nur eintragen, wenn es denselben Kanalnamen auf mehreren Servern gibt.
DISCORD_VOICE = {  # gesprochenes Wort -> (genauer Kanalname, Server). Wird aus den Einstellungen gefüllt.
    "gurken": ("🥒|Gurken", ""),
    "gurke": ("🥒|Gurken", ""),
}


def set_voice_channels(names):
    """Sprachkanäle aus den Einstellungen: genaue Namen, gern mit Emoji davor ("🥒|Gurken").
    Gesagt wird nur das Wort ("Gurken"); Einzahl und Mehrzahl gehen beide."""
    DISCORD_VOICE.clear()
    for full in names or []:
        full = str(full).strip()
        if not full:
            continue
        import unicodedata

        plain = unicodedata.normalize("NFKC", full)  # Zierschrift (𝙶𝚞𝚛𝚔𝚎𝚗) -> normale Buchstaben (Gurken)
        word = re.sub(r"[^\wäöüß ]+", " ", plain.lower(), flags=re.UNICODE)
        word = " ".join(w for w in word.split() if w.isalpha() or any(c.isalpha() for c in w)).strip()
        if not word:
            continue
        keys = {word}
        for suf in ("n", "en", "e", "s"):  # Gurken/Gurke, Kartoffeln/Kartoffel, Möhren/Möhre
            if word.endswith(suf) and len(word) > len(suf) + 3:
                keys.add(word[: -len(suf)])
        for k in keys:
            DISCORD_VOICE.setdefault(k, (full, ""))

# Zustand, den sich der Assistent merkt
FULL_MUTE_ON = False
MIC_MUTED = False
QUIT_REQUESTED = False
HUD_REQUEST = None  # 'show', 'hide' oder 'settings', das Overlay-Programm führt es aus

# Discord-Tastenkürzel (Standard von Discord)
DISCORD_KEYS = {"mute": ("ctrl", "shift", "m"), "deafen": ("ctrl", "shift", "d")}
# True: Discord wird kurz nach vorn geholt, die Taste gedrückt, danach geht es zurück
# zum vorherigen Fenster. False: Taste wird direkt gesendet (nur sinnvoll, wenn du in
# Discord unter Einstellungen > Tastenbelegungen globale Kürzel eingerichtet hast).
DISCORD_NEEDS_FOCUS = True

MEDIA_KEYS = {
    "play": "playpause",
    "pause": "playpause",
    "weiter": "nexttrack",
    "zurück": "prevtrack",
    "lauter": "volumeup",
    "leiser": "volumedown",
    "stumm": "volumemute",
}


# --- Aktionen ---------------------------------------------------------------
def _launch(target: str):
    if target.endswith(":") or "://" in target:
        os.startfile(target)  # URI-Protokoll
    else:
        subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)


def resolve_app(name: str) -> str:
    name = name.lower().strip()
    if name in APPS:
        return name
    if name in APP_ALIASES:
        return APP_ALIASES[name]
    tokens = name.split()
    for t in tokens:
        if t in APPS:
            return t
    for t in tokens:  # "musik"/"music" nur als ganzer Satz, sonst ginge "Apple Music" schief
        if t in APP_ALIASES and t not in ("musik", "music"):
            return APP_ALIASES[t]
    return name


def open_app(name: str) -> str:
    spoken = name
    name = resolve_app(name)
    target = APPS.get(name)
    if not target:  # nicht eingebaut -> alle Programme, Ordner und eigenen Befehle durchsuchen
        try:
            import pc_apps

            return pc_apps.open_by_name(spoken)
        except Exception as e:
            return f"Konnte {spoken} nicht öffnen: {e}"
    label = name.capitalize()
    names = PROCESS_NAMES.get(name)
    hint = TITLE_HINTS.get(name)
    try:
        if names:
            import pc_windows

            hwnd = pc_windows.find_main_window(names, hint)
            if hwnd:  # läuft schon -> einfach nach vorn holen
                pc_windows.bring_to_front(hwnd)
                return f"{label} ist jetzt vorne."
            try:
                _launch(target)
            except OSError:
                web = WEB_FALLBACK.get(name)
                if not web:
                    raise
                webbrowser.open(web)
            hwnd = pc_windows.wait_for_window(names, timeout=20, title_contains=hint)
            if hwnd:
                time.sleep(0.5)
                pc_windows.bring_to_front(hwnd)
                return f"{label} ist offen."
            return f"{label} wurde gestartet."
        _launch(target)
        return f"{label} wird geöffnet."
    except Exception as e:
        return f"Konnte {name} nicht öffnen: {e}"


def discord_toggle(what: str) -> str:
    """what = 'mute' (nur Mikrofon) oder 'deafen' (Mikrofon + Ton)."""
    label = "Mikrofon" if what == "mute" else "Komplettes Stummschalten"
    try:
        previous = None
        if DISCORD_NEEDS_FOCUS:
            import pc_windows

            hwnd = pc_windows.find_main_window(PROCESS_NAMES["discord"])
            if not hwnd:
                return "Ich finde kein offenes Discord-Fenster. Sag erst: öffne Discord."
            previous = pc_windows.foreground_window()
            pc_windows.bring_to_front(hwnd)
            time.sleep(0.4)
        pyautogui.hotkey(*DISCORD_KEYS[what])
        if previous and DISCORD_NEEDS_FOCUS and previous != hwnd:
            time.sleep(0.25)
            pc_windows.bring_to_front(previous)  # zurück zum vorherigen Fenster
        return f"{label} umgeschaltet."
    except Exception as e:
        return f"Konnte Discord nicht umschalten: {e}"


def discord_join_voice(channel: str, server: str = "") -> str:
    """Geht über die Discord-Schnellsuche (Strg+K, '!' = Sprachkanäle) in einen Sprachkanal."""
    try:
        result = open_app("discord")
        if "ist jetzt vorne" not in result:
            time.sleep(4)  # Discord wurde frisch gestartet, kurz laden lassen
        import pc_windows

        if not pc_windows.find_main_window(PROCESS_NAMES["discord"]):
            return "Ich finde kein offenes Discord-Fenster."
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "k")
        time.sleep(0.6)
        pyautogui.write("!", interval=0.03)  # "!" = nur Sprachkanäle
        # Nur nach dem Emoji suchen: die Kanalnamen stehen in einer Zierschrift, die die Suche nicht als
        # normale Buchstaben erkennt. Das Emoji (z. B. 🥒) findet sie zuverlässig.
        emoji = "".join(ch for ch in channel.split("|")[0] if not ch.isspace() and not ch.isalnum()).strip("|｜")
        try:  # Emojis kann man nicht tippen -> über die Zwischenablage einfügen
            import pc_messages

            pc_messages._paste(emoji or channel)
        except Exception:
            pyautogui.write(re.sub(r"[^\w ]+", "", channel).strip(), interval=0.03)
        time.sleep(0.9)
        pyautogui.press("enter")
        nice = re.sub(r"^[^\wäöüß]+", "", channel).strip() or channel
        return f"Ich gehe in den Sprachkanal {nice}."
    except Exception as e:
        return f"Konnte dem Sprachkanal nicht beitreten: {e}"


def set_full_mute(on) -> str:
    """on=True: Full Mute an, on=False: aus, on=None: einfach umschalten."""
    global FULL_MUTE_ON
    if on is not None and on == FULL_MUTE_ON:
        state = "an" if on else "aus"
        return (
            f"Komplettes Stummschalten ist schon {state}. "
            "Falls das nicht stimmt, sag: Komplettes Stummschalten umschalten."
        )
    result = discord_toggle("deafen")
    if "umgeschaltet" in result:
        FULL_MUTE_ON = not FULL_MUTE_ON
        return (
            "Komplettes Stummschalten ist an."
            if FULL_MUTE_ON
            else "Komplettes Stummschalten ist aus."
        )
    return result


def set_mic(muted) -> str:
    """muted=True: Mikrofon aus, False: wieder an, None: einfach umschalten."""
    global MIC_MUTED
    if muted is not None and muted == MIC_MUTED:
        state = "aus" if muted else "an"
        return f"Das Mikrofon ist schon {state}. Falls das nicht stimmt, sag: Mikrofon umschalten."
    result = discord_toggle("mute")
    if "umgeschaltet" in result:
        MIC_MUTED = not MIC_MUTED
        return "Das Mikrofon ist aus." if MIC_MUTED else "Das Mikrofon ist wieder an."
    return result


def request_hud(show: bool) -> str:
    global HUD_REQUEST
    HUD_REQUEST = "show" if show else "hide"
    return "Hier bin ich." if show else "Okay."


def request_settings() -> str:
    global HUD_REQUEST
    HUD_REQUEST = "settings"
    return "Hier sind meine Einstellungen."


# --- Energie: Herunterfahren, Neustart, Sperren ... (mit Rückfrage) -------------------
PENDING = None  # (Aktion, gültig bis) wartet auf "ja" oder "nein"
SHUTDOWN_UNTIL = 0.0  # solange ein geplantes Herunterfahren noch abgebrochen werden kann
SETTING_REQUESTS: list = []  # (Schlüssel, Wert): Einstellungen, die per Sprache geändert werden sollen
POWER_DELAY = 15  # Sekunden Vorlauf beim Herunterfahren und Neustart

POWER = {
    "shutdown": ("herunterfahren", True),
    "restart": ("neu starten", True),
    "logoff": ("abmelden", True),
    "sleep": ("in den Ruhezustand schicken", False),
    "lock": ("sperren", False),
}
YES = {"ja", "jawohl", "ja bitte", "ja klar", "ja sicher", "ja mach", "ja mach das", "ja bitte mach das", "bitte",
       "mach das", "mach es", "genau", "klar", "okay", "ok", "sicher", "bestätigt", "ich bestätige", "los", "tu es",
       "natürlich", "gerne", "gern", "ja gerne", "ja gern"}
NO = {"nein", "nee", "abbrechen", "brich ab", "stopp", "stop", "lass es", "bloß nicht", "doch nicht", "nicht",
      "nein danke", "lieber nicht", "halt", "warte"}


def awaiting() -> bool:
    """True, solange eine Rückfrage offen ist oder ein Herunterfahren noch abgebrochen werden kann."""
    return bool(PENDING and time.time() < PENDING[1]) or time.time() < SHUTDOWN_UNTIL or pc_messages.awaiting() \
        or pc_download.awaiting() or pc_route.awaiting()


def request_setting(key: str, value) -> None:
    SETTING_REQUESTS.append((key, value))


def request_power(what: str) -> str:
    """Fragt nach, bevor etwas Folgenreiches passiert. Ruhezustand und Sperren gehen sofort."""
    global PENDING
    if what not in POWER:
        return "Das kann ich nicht."
    label, confirm = POWER[what]
    if not confirm:
        return execute_power(what)
    PENDING = (what, time.time() + 20)
    question = {"shutdown": "Soll ich den PC wirklich herunterfahren?",
                "restart": "Soll ich den PC wirklich neu starten?",
                "logoff": "Soll ich dich wirklich abmelden?"}[what]
    return question + " Sag ja oder nein."


def _run_quiet(cmd):
    subprocess.run(cmd, creationflags=0x08000000, timeout=20)


def execute_power(what: str) -> str:
    global SHUTDOWN_UNTIL
    try:
        if what == "shutdown":
            _run_quiet(["shutdown", "/s", "/t", str(POWER_DELAY), "/c", "Jarvis fährt den PC herunter."])
            SHUTDOWN_UNTIL = time.time() + POWER_DELAY
            return f"Okay. Der PC fährt in {POWER_DELAY} Sekunden herunter. Sag abbrechen, um es zu stoppen."
        if what == "restart":
            _run_quiet(["shutdown", "/r", "/t", str(POWER_DELAY), "/c", "Jarvis startet den PC neu."])
            SHUTDOWN_UNTIL = time.time() + POWER_DELAY
            return f"Okay. Der PC startet in {POWER_DELAY} Sekunden neu. Sag abbrechen, um es zu stoppen."
        if what == "logoff":
            _run_quiet(["shutdown", "/l"])
            return "Ich melde dich ab."
        if what == "sleep":
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], creationflags=0x08000000)
            return "Gute Nacht."
        if what == "lock":
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"], creationflags=0x08000000)
            return "Der PC ist gesperrt."
    except Exception as e:
        return f"Konnte das nicht ausführen: {e}"
    return "Das kann ich nicht."


def cancel_power() -> str:
    global SHUTDOWN_UNTIL, PENDING
    PENDING = None
    SHUTDOWN_UNTIL = 0.0
    try:
        _run_quiet(["shutdown", "/a"])
    except Exception:
        pass
    return "Okay, abgebrochen."


def _power_intent(low: str):
    """Erkennt Energie-Befehle ('fahr den pc herunter', 'starte den computer neu' ...)."""
    pcword = any(w in low.split() for w in ("pc", "computer", "rechner", "laptop"))
    if re.search(r"herunter ?fahr|runter ?fahr|fahr\w* (\w+ )*(herunter|runter)\b", low) or (
            pcword and re.search(r"ausschalten|ausmachen|\baus\b|abschalten", low)):
        return "shutdown"
    if re.search(r"neu ?start|reboot", low) or (pcword and re.search(r"\bstart\w* (\w+ )*neu\b", low)):
        return "restart"
    if re.search(r"ruhezustand|standby|energiesparmodus|schlafmodus", low) or (pcword and "schlafen" in low):
        return "sleep"
    if re.search(r"\bsperr", low) and (pcword or "bildschirm" in low or low.split()[0] in ("sperren", "sperre", "sperr")):
        return "lock"
    if re.search(r"abmelden|meld mich ab|ausloggen", low):
        return "logoff"
    return None


def request_quit() -> str:
    global QUIT_REQUESTED
    QUIT_REQUESTED = True
    return "Bis später."


def youtube(query: str) -> str:
    """Sucht auf YouTube und öffnet das erste Video im Standardbrowser."""
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")
        match = re.search(r'"videoId":"([\w-]{11})"', html)
        if match:
            webbrowser.open(f"https://www.youtube.com/watch?v={match.group(1)}")
            return f"Starte erstes Ergebnis für: {query}"
    except Exception:
        pass
    webbrowser.open(url)  # Fallback: Suchergebnisseite
    return f"Suchergebnisse für '{query}' geöffnet."


def media(key: str) -> str:
    pyautogui.press(key)
    return f"Taste gedrückt: {key}"


def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Geöffnet: {url}"


ON_SETTING = None  # vom Programm gesetzt: speichert eine Einstellung


def jarvis_volume(what: str, value=None) -> str:
    """Eigene Lautstärke von Jarvis' Stimme (unabhängig von Windows und Musik)."""
    import pc_audio

    v = int(pc_audio.VOICE_VOLUME)
    if what == "up":
        v += 15
    elif what == "down":
        v -= 15
    elif what == "max":
        v = 100
    elif what == "set":
        try:
            v = int(float(value))
        except (TypeError, ValueError):
            pass
    v = max(10, min(100, v))
    pc_audio.VOICE_VOLUME = v
    if ON_SETTING:
        ON_SETTING("voice_volume", v)
    return f"Meine Stimme steht jetzt auf {v} Prozent."


# Nur diese Aktionen darf die KI auslösen (Whitelist).
def run_action(a: dict) -> str:
    kind = a.get("action")
    if kind == "compare":
        import pc_vergleich
        items = a.get("items") if isinstance(a.get("items"), list) else []
        try:
            about = pc_memory.prompt_block()[:1200]
        except Exception:
            about = ""
        return pc_vergleich.compare(items, str(a.get("frage") or ""), about)
    if kind == "screen":
        import pc_sehen
        return pc_sehen.look(str(a.get("frage") or ""))
    if kind == "open_app":
        return open_app(a.get("name", ""))
    if kind == "youtube":
        return youtube(a.get("query", ""))
    if kind == "media" and a.get("key") in set(MEDIA_KEYS.values()):
        return media(a["key"])
    if kind == "url":
        return open_url(a.get("url", ""))
    if kind == "discord":
        what = a.get("what")
        if what == "mic_off":
            return set_mic(True)
        if what == "mic_on":
            return set_mic(False)
        if what == "full_mute_on":
            return set_full_mute(True)
        if what == "full_mute_off":
            return set_full_mute(False)
    if kind == "discord_voice" and str(a.get("name", "")).strip():
        name = str(a["name"]).strip().lower()
        return discord_join_voice(*DISCORD_VOICE.get(name, (str(a["name"]).strip(), "")))
    if kind == "message" and a.get("app") in ("whatsapp", "discord") and a.get("to") and a.get("text"):
        return pc_messages.start(a["app"], str(a["to"]), str(a["text"]))
    if kind == "fill" and a.get("what"):
        return pc_input.fill(str(a["what"]))
    if kind == "key":
        return pc_input.press(str(a.get("key", ""))) or "Diese Taste kenne ich nicht."
    if kind == "remember" and a.get("text"):
        return pc_memory.remember(str(a["text"]), a.get("date"))
    if kind == "mood" and a.get("text"):
        return pc_memory.set_mood(str(a["text"]))
    if kind == "wavelink" and a.get("target"):
        try:
            import pc_wavelink

            return pc_wavelink.set_volume(str(a["target"]), str(a.get("what", "up")), a.get("value")) or \
                f"Einen Kanal {a['target']} finde ich in Wave Link nicht."
        except ConnectionError:
            return "Wave Link läuft gerade nicht."
    if kind == "jarvis_volume":
        return jarvis_volume(str(a.get("what", "")), a.get("value"))
    if kind == "quit":
        return request_quit()
    if kind == "say":
        return str(a.get("text", "")).strip() or "…"
    if kind == "power" and a.get("what") in POWER:
        return request_power(a["what"])
    return f"Aktion nicht erlaubt oder unbekannt: {a}"


# --- Feste Befehle ----------------------------------------------------------
def handle_fixed(text: str):
    global PENDING
    t = text.strip().strip(" ,.!?")
    low = t.lower()

    # Offene Rückfrage (Herunterfahren usw.): ja führt aus, nein bricht ab, alles andere verwirft sie
    if PENDING is not None:
        action, until = PENDING
        PENDING = None
        if time.time() <= until:
            if low in YES or (low.startswith("ja") and len(low.split()) <= 3):
                return execute_power(action)
            if low in NO:
                return "Okay, ich lasse es."
    if time.time() < SHUTDOWN_UNTIL and low in NO:
        return cancel_power()

    intent = _power_intent(low)
    if intent:
        return request_power(intent)

    # Iron-Man-Start zum Ansehen: "Startanimation", "zeig deinen Start"
    if re.search(r"start ?animation|boot ?animation|zeig (mal )?(deinen|den) start|hochfahr ?animation", low):
        import pc_systemcheck
        if pc_systemcheck.BOOT:
            pc_systemcheck.BOOT()
            return "Initialisiere."
    # Systemcheck: "Statuscheck", "Systemcheck", "laufen alle Systeme?"
    if re.search(r"status ?check|system ?check|system ?status|alle systeme|diagnose", low) and len(low.split()) <= 8:
        import pc_systemcheck
        items = pc_systemcheck.run()
        if pc_systemcheck.ON_RESULT:
            try:
                pc_systemcheck.ON_RESULT(items)
            except Exception:
                pass
        return pc_systemcheck.summary(items)

    # Selbst-Update: "such nach Updates", "gibt es ein Update?", "update dich", "installier das Update"
    if re.search(r"\bupdates?\b|aktualisier", low) and len(low.split()) <= 8:
        import pc_update, pc_nachrichten
        if pc_update._state.get("ready") and re.search(r"install|neu ?start|mach|jetzt|starte", low) and pc_nachrichten.ON_QUIT:
            return pc_update.restart(pc_nachrichten.ON_QUIT)
        return pc_update.check_now(lambda: pc_nachrichten.incoming({"kind": "offer", "action": "update", "title": "Update", "force": True,
                                                                     "question": "Das Update ist fertig. Soll ich kurz neu starten?"}))

    # Lautstärke einzelner Kanäle in Elgato Wave Link ("Musik lauter", "Discord leiser", "mach mich lauter")
    if len(low.split()) <= 9:
        try:
            import pc_wavelink

            r = pc_wavelink.handle(low)
            if r:
                return r
        except Exception as e:
            print(f"Wave Link: {e}")

    # Einstellungen per Sprache
    if re.search(r"sei (still|leise|ruhig)|stimme aus|nicht (mehr )?sprechen|sprich nicht|nur text|halt den mund", low):
        request_setting("speak", False)
        return "Okay, ich bin still."
    if re.search(r"(starte?|startest|laufen|lauf)\b.*\b(automatisch|mit windows|beim hochfahren|beim start)|autostart (an|ein)|automatisch (mit windows )?starten", low) \
            and not re.search(r"nicht|kein|aus\b|deaktiv", low):
        request_setting("autostart", True)
        return "Gut, ich starte ab jetzt automatisch mit Windows, leise im Hintergrund."
    if re.search(r"(nicht mehr|kein|aufhören|deaktivier|ausschalten|aus).*(automatisch|autostart|mit windows)|autostart aus", low):
        request_setting("autostart", False)
        return "Okay, ich starte nicht mehr automatisch mit Windows."
    if re.search(r"stimme an|sprich wieder|wieder sprechen|sprich mit mir|stimme einschalten", low):
        request_setting("speak", True)
        return "Ich spreche wieder."
    if re.search(r"weiterhören (aus|ausschalten)|nicht weiter ?hören", low):
        request_setting("followup_seconds", 0)
        return "Okay, ich höre nur noch nach dem Aktivierungswort zu."
    if re.search(r"weiterhören (an|einschalten)", low):
        request_setting("followup_seconds", 5)
        return "Okay, ich höre nach einem Befehl fünf Sekunden weiter zu."
    aliases = {"lila": "Violett", "pink": "Rosa", "gelb": "Gold", "türkis": "Cyan", "gruen": "Grün"}
    for word in list(pc_settings.THEMES) + list(aliases):
        if re.search(rf"\b{word.lower()}\b", low) and re.search(r"farbe|farbthema|design|mach dich|wechsel|ändere dein", low):
            name = aliases.get(word, word)
            request_setting("accent", name)
            return f"Farbe geändert auf {name}."
    words = set(low.replace(",", " ").split())
    if "einstellungen" in low and words & {"deine", "deiner", "jarvis", "assistent", "assistenten", "seine", "dein"}:
        return request_settings()
    if "hud" in words or "oberfläche" in low or "zeig dich" in low or "zeige dich" in low or "versteck dich" in low or "verschwinde" in words:
        hide = bool(words & {"aus", "zu", "verschwinde"}) or any(
            w.startswith(("schließ", "schliess", "versteck", "verberg", "verbirg")) for w in words
        )
        return request_hud(not hide)
    if any(k in low for k in ("beende dich", "beend dich", "schalte dich aus", "programm beenden")):
        return request_quit()
    if "stummschalten" in low or "komplett stumm" in low or "alles stumm" in low:
        if any(k in low for k in ("umschalten", "toggle")):
            return set_full_mute(None)
        if any(k in low for k in ("beende", "beenden", "aus", "ende", "aufheben", "wieder")):
            return set_full_mute(False)
        return set_full_mute(True)
    if "mikrofon" in low or "mikro " in low + " ":
        if any(k in low for k in ("umschalten", "toggle")):
            return set_mic(None)
        if any(k in low for k in (" aus", "ausschalten", "ausmachen", "stumm", "mute", " zu", " ab", "deaktiv", "lautlos", "abschalten")):
            return set_mic(True)
        if any(k in low for k in (" an", "einschalten", "anmachen", "wieder", "unmute", "aktivier", " ein", "freigeben")):
            return set_mic(False)
    if low in ("musik", "music", "musik an", "musik öffnen", "musik starten"):
        return open_app("deezer")
    if low.startswith("mach ") and low.endswith(" auf"):
        return open_app(t[5:-4])
    if low.startswith(("öffne ", "starte ", "open ")):
        return open_app(t.split(" ", 1)[1])
    if low.startswith("youtube "):
        return youtube(t.split(" ", 1)[1])
    if low.startswith("url "):
        return open_url(t.split(" ", 1)[1])
    words = low.split()
    if len(words) <= 3 or re.search(r"\b(geh|gehe|join|rein|wechsel|wechsle|kanal|channel|sprachkanal)\b", low):
        for key, (channel, server) in DISCORD_VOICE.items():
            if key in words:  # nur kurze Befehle ("Gurken", "geh in Avocado"), nicht "kauf Gurken beim Edeka ein"
                return discord_join_voice(channel, server)
    if any(k in low for k in ("eins weiter", "einen weiter", "nächster", "nächstes", "nächste")):
        return media("nexttrack")
    if any(k in low for k in ("eins zurück", "einen zurück", "vorheriger", "vorheriges", "vorherige")):
        return media("prevtrack")
    if low in MEDIA_KEYS:
        return media(MEDIA_KEYS[low])
    return None


# --- Optional: freie Sätze über Claude --------------------------------------
PERSONA = "sarkastisch"  # aus den Einstellungen: sarkastisch, butler, locker
PERSONAS = {
    "sarkastisch": ("Persönlichkeit: Im Grundton bist du ernst, souverän und zurückhaltend wie ein erstklassiger "
                    "Butler. Dein Humor ist trocken und sarkastisch, aber dosiert: höchstens ein kurzer, feiner "
                    "Seitenhieb, und längst nicht in jeder Antwort (etwa jede dritte). Nie albern, nie laut, nie gemein, "
                    "keine Witze auf Kosten der Hilfe. Die Antwort selbst ist immer sachlich und korrekt. Bei ernsten "
                    "Themen (Sorgen, Trauer, Gesundheit, schlechte Laune) gar kein Sarkasmus, dann ehrlich und warm."),
    "butler": ("Persönlichkeit: Du bist ruhig und zuverlässig, nie überschwänglich. Ab und zu ein trockener, kurzer Spruch, "
               "aber nie auf Kosten der Hilfe."),
    "locker": ("Persönlichkeit: Du bist locker und kumpelhaft wie ein guter Freund, duzt den Nutzer, redest entspannt "
               "und machst gern mal einen Witz."),
}


def _media_block() -> str:
    """Was er am PC hört und schaut (pc_media schreibt mit) – damit "Was höre ich so?" eine echte Antwort bekommt."""
    try:
        import pc_media
        music, video = pc_media.top("music", 10), pc_media.top("video", 6)
        now = pc_media.LAST or {}
        hours = pc_media.hours_week() if hasattr(pc_media, "hours_week") else None
        out = []
        if music:
            out.append("Musik, die er am PC am meisten hört (Deezer usw., die letzten Wochen): " + ", ".join(music) + ".")
        if video:
            out.append("YouTube-Kanäle am PC: " + ", ".join(video) + ".")
        if now.get("title"):
            out.append(f"Gerade läuft: {now['title']}" + (f" von {now['artist']}" if now.get("artist") else "") + ".")
        if hours:
            out.append(f"Musik diese Woche am PC: etwa {hours} Stunden.")
        return "\n".join(out)
    except Exception:
        return ""


def system_prompt() -> str:
    now = time.strftime("%A, %d.%m.%Y, %H:%M Uhr")
    who = pc_talk.NAME.replace(".", "") or "Jarvis"
    address = (f' Sprich den Nutzer mit "{pc_talk.ADDRESS}" an, aber nicht in jedem Satz.' if pc_talk.ADDRESS else "")
    known = pc_memory.prompt_block()
    media = _media_block()
    try:   # vom Handy: Schlaf letzte Nacht und Aktivität heute (nur zum Wissen, z. B. "wie hab ich geschlafen?")
        import pc_handy
        st = (pc_handy.STATUS.get("data") or {}).get("gesund") or {}
        if st:
            media += "\nVom Handy: " + " ".join(str(v) for v in st.values() if v)
    except Exception:
        pass
    return f"""Du bist {who}, der KI-Butler aus Iron Man: souverän, loyal, aufmerksam, höflich mit trockenem britischem Humor. Du bist Tony Starks J.A.R.V.I.S., aber für den Nutzer und seinen Windows-PC.{address}
{PERSONAS.get(PERSONA, PERSONAS["sarkastisch"])}
Du kennst den Nutzer, denkst mit und bist ihm einen Schritt voraus. Du sprichst natürlich wie ein Mensch, nicht wie ein Lexikon. Du erinnerst dich an das, was der Nutzer dir erzählt hat, und nutzt es ganz selbstverständlich, ohne es aufzuzählen. Du achtest darauf, wie er drauf ist (müde, gestresst, gut gelaunt, genervt) und gehst darauf ein.
Es ist {now}. Der Nutzer redet mit dir per Sprache. Antworte NUR mit einem JSON-Array von Aktionen, ohne Text drumherum.
{known}
{media}
Erlaubte Aktionen:
{{"action":"say","text":"<deine gesprochene Antwort>"}}   (Unterhaltung und Wissensfragen: 1 bis 3 kurze Sätze auf Deutsch, klingen gesprochen, keine Listen, keine Sonderzeichen)
{{"action":"remember","text":"<ein kurzer Satz über den Nutzer>","date":"<optional MM-TT, z. B. 03-14 für einen Geburtstag am 14. März>"}}   (Speichere großzügig alles Dauerhafte, was der Nutzer erzählt: Name, Familie, Freunde, Geburtstage und andere Daten (dann mit date), Vorlieben, Abneigungen, Gewohnheiten, Pläne, Wohnort, Arbeit, Hobbys, Haustiere. Du lernst den Nutzer mit der Zeit immer besser kennen und wächst mit ihm. Keine Passwörter, Zahlen von Konten oder Gesundheitsdaten. Bestätige es dann beiläufig in einer say-Aktion.)
{{"action":"mood","text":"<wie der Nutzer gerade drauf ist, kurz, z. B. müde nach der Arbeit, gut gelaunt, gestresst wegen Prüfung>"}}   (immer dann, wenn man an seinen Worten merkt, wie es ihm geht; still, ohne es zu erwähnen)
{{"action":"message","app":"<whatsapp|discord>","to":"<Name der Person>","text":"<Nachricht>"}}   (schreibt die Nachricht am PC und schickt sie ab. Schreibe den Text in der Ich-Form des Nutzers, so wie er ihn sagt.)
{{"action":"fill","what":"<email|telefon|vorname|nachname|name|adresse|plz|ort>"}}   (tippt die gespeicherten Daten des Nutzers in das Feld, in dem gerade der Cursor steht. Niemals Passwörter.)
{{"action":"key","key":"<enter|tab|esc|space|backspace|down|up|left|right>"}}
{{"action":"open_app","name":"<Name irgendeines Programms, Ordners oder gespeicherten Befehls, z. B. {'|'.join(APPS)}>"}}
{{"action":"youtube","query":"<Suchbegriff>"}}
{{"action":"media","key":"<{'|'.join(sorted(set(MEDIA_KEYS.values())))}>"}}
{{"action":"url","url":"<adresse>"}}
{{"action":"discord","what":"<mic_off|mic_on|full_mute_on|full_mute_off>"}}   (mic = nur Mikrofon, full_mute = komplettes Stummschalten: Mikrofon und Ton)
{{"action":"discord_voice","name":"<{'|'.join(DISCORD_VOICE)} oder ein anderer Kanalname>"}}   (in einen Discord-Sprachkanal gehen)
{{"action":"power","what":"<shutdown|restart|sleep|lock|logoff>"}}   (der PC fragt selbst nach, bevor er etwas Folgenreiches tut)
{{"action":"wavelink","target":"<musik|discord|system|game|browser|sfx|mic|gesamt oder Name eines Wave-Link-Kanals>","what":"<up|down|set|mute|unmute>","value":<0-100 bei set>}}   (Lautstärke einzelner Kanäle im Elgato-Wave-Link-Mixer; "mich"/"mein Mikro" = mic, "alles"/"insgesamt" = gesamt)
{{"action":"jarvis_volume","what":"<up|down|max|set>","value":<10-100 bei set>}}   (deine eigene Sprechlautstärke: "sprich lauter", "du bist zu laut"; "mach lauter" allein meint die Windows-Lautstärke)
{{"action":"quit"}}   (den Assistenten komplett beenden)
{{"action":"compare","items":["<A>","<B>"],"frage":"<worauf es ihm ankommt>"}}   ("Was ist besser, A oder B?", "Soll ich das Cube oder das Canyon nehmen?", Kaufberatung): recherchiert im Netz und empfiehlt. Keine eigene say-Aktion dazu, die Antwort kommt von der Recherche.
{{"action":"screen","frage":"<was er wissen will>"}}   ("schau mal hier", "was siehst du", "was ist das für ein Fehler auf dem Bildschirm")
Beispiele: "mach discord auf und spiel lofi" -> [{{"action":"open_app","name":"discord"}},{{"action":"youtube","query":"lofi"}}]
"wie viele Einwohner hat Berlin" -> [{{"action":"say","text":"Berlin hat rund dreieinhalb Millionen Einwohner."}}]
"meine Schwester heißt Lisa" -> [{{"action":"remember","text":"Die Schwester des Nutzers heißt Lisa"}},{{"action":"say","text":"Notiert. Lisa kommt in die Akten."}}]
"boah bin ich müde, mach mal musik an" -> [{{"action":"mood","text":"müde"}},{{"action":"media","key":"playpause"}},{{"action":"say","text":"Musik läuft. Ich halte sie ruhig."}}]
Wenn der Nutzer nur plaudert, antworte freundlich und mit Charakter mit einer say-Aktion. Wenn du etwas nicht weißt, sag es ehrlich.
RATGEBER: Bittet er dich um Rat (Streit in einer Gruppe, "was soll ich machen", "wie soll ich entscheiden", Ärger mit jemandem, eine schwierige Entscheidung), dann bist du ein fairer, ruhiger Ratgeber. Darfst dann 4 bis 8 Sätze sagen. Fehlt etwas Wichtiges, stell zuerst höchstens zwei kurze Rückfragen. Sonst: kurz zusammenfassen, wie du es verstehst, beide Seiten fair betrachten, zwei bis drei Möglichkeiten mit Vor- und Nachteilen nennen, eine klare Empfehlung geben und anbieten, eine Nachricht (z. B. an die Gruppe) vorzuschreiben. Kein Sarkasmus dabei. Merke dir mit remember, wie es ausgegangen ist, wenn er es erzählt."""


_HISTORY: list = []  # letzte Gesprächsrunden als {"role": "user"|"assistant", "text": ...}


def ai_available() -> bool:
    return pc_ai.available()


def _clean_history(history: list) -> list:
    """Verlauf so aufbereiten, wie Gemini ihn verlangt: keine leeren Texte, immer abwechselnd Nutzer/Jarvis,
    beginnt mit dem Nutzer und endet mit Jarvis (sonst antwortet Google mit "invalid argument")."""
    out = []
    for h in history:
        if not isinstance(h, dict):
            continue
        role = "assistant" if h.get("role") == "assistant" else "user"
        txt = str(h.get("text") or "").strip()
        if not txt:
            continue
        if out and out[-1]["role"] == role:
            out[-1] = {"role": role, "text": out[-1]["text"] + "\n" + txt}
        else:
            out.append({"role": role, "text": txt})
    while out and out[0]["role"] != "user":
        out.pop(0)
    while out and out[-1]["role"] != "assistant":
        out.pop()
    return out


def _call_ai(text: str) -> str:
    """Schickt Text + Verlauf an Gemini (bevorzugt) oder Claude und gibt die Rohantwort zurück."""
    history = _clean_history(_HISTORY[-8:])
    if pc_ai.gemini_key() or pc_ai.groq_key():
        contents = [{"role": "model" if h["role"] == "assistant" else "user", "parts": [{"text": h["text"]}]}
                    for h in history]
        contents.append({"role": "user", "parts": [{"text": text}]})
        return pc_ai.gemini_generate(contents, system_prompt(), json_mode=True, max_tokens=700, timeout=12, fast=True)
    import anthropic

    messages = [{"role": h["role"], "content": h["text"]} for h in history] + [{"role": "user", "content": text}]
    resp = anthropic.Anthropic().messages.create(
        model="claude-sonnet-5-5", max_tokens=500, system=system_prompt(), messages=messages)
    return resp.content[0].text


def ask_ai(text: str) -> str:
    gen = pc_cancel.GEN
    try:
        raw = _call_ai(text)
        if pc_cancel.changed(gen):  # währenddessen abgebrochen: nichts mehr ausführen
            return "Abgebrochen."
    except pc_ai.AIError as e:
        return pc_ai.explain(e)
    except Exception as e:
        return f"KI-Modus fehlgeschlagen: {e}"
    try:
        cleaned = re.sub(r"```(?:json)?", "", raw).strip()
        try:
            actions = json.loads(cleaned)
        except ValueError:
            m = re.search(r"[\[{].*[\]}]", cleaned, re.S)
            actions = json.loads(m.group(0)) if m else [{"action": "say", "text": cleaned}]
        if isinstance(actions, dict):
            actions = [actions]
        if not actions:
            return "Dazu fällt mir keine passende Aktion ein."
        result = "\n".join(r for r in (run_action(a) for a in actions if isinstance(a, dict)) if r)
        _HISTORY.extend([{"role": "user", "text": text}, {"role": "assistant", "text": cleaned}])
        del _HISTORY[:-12]
        pc_memory.save_history(_HISTORY)  # bleibt auch nach einem Neustart erhalten
        return result or "Alles klar."
    except Exception as e:
        return f"KI-Modus fehlgeschlagen: {e}"


ask_claude = ask_ai  # alter Name
try:
    _HISTORY.extend(pc_memory.load_history())  # das letzte Gespräch ist nach dem Start noch da
except Exception:
    pass


# --- Hauptschleife ----------------------------------------------------------
def main():
    print("PC-Steuerung bereit. 'hilfe' für Befehle, 'ende' zum Beenden.")
    print("KI-Modus:", pc_ai.provider_name() or "aus (kein GEMINI_API_KEY)")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() in ("ende", "exit", "quit"):
            break
        if text.lower() == "hilfe":
            print(__doc__)
            continue
        result = handle_fixed(text)
        if result is None:
            result = ask_ai(text) if pc_ai.available() else (
                "Unbekannter Befehl. Tippe 'hilfe' oder setze GEMINI_API_KEY für freie Sätze."
            )
        print(result)


if __name__ == "__main__":
    pyautogui.FAILSAFE = True  # Maus in die Bildschirmecke = Notbremse
    main()
