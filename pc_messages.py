"""
Nachrichten schreiben und abschicken, per Sprache:

  "Schreib eine WhatsApp an Mama mit ich komme später"
  "Schreib Max auf Discord: wollen wir zocken?"
  "Schick Anna auf WhatsApp, dass ich gleich da bin"

Jarvis bedient dafür die Programme wie du mit der Tastatur: WhatsApp Desktop und Discord müssen auf dem PC
installiert und angemeldet sein. Er holt das Fenster nach vorn, sucht die Person, tippt den Text und drückt Enter.
Während das läuft, bitte Maus und Tastatur nicht anfassen (ein paar Sekunden).

Bei WhatsApp ist es am zuverlässigsten, wenn die Handynummer bekannt ist:
"Die Nummer von Mama ist 0170 1234567" (Jarvis merkt sie sich nur auf diesem PC, in gedaechtnis.json).
Ohne Nummer sucht er den Namen in der WhatsApp-Suche.
"""

import os
import re
import threading
import time
import urllib.parse

import pc_memory

CONFIRM = False  # aus den Einstellungen: vor dem Senden zurückfragen
PENDING = None  # (app, to, text, gültig bis)

APP_WORDS = r"(?P<app>whats\s?app|watsapp|whatsup|wazap|discord|diskord)"
LEAD = r"(?:schreib|schreibe|schick|schicke|sende|send|sag|sage|texte)\w*"
FILLER = r"(?:(?:mal|bitte|doch|gleich|jetzt|noch)\s+)*"
SEP = r"(?:\s*[:,]\s*|\s+(?:und zwar(?: soll)?(?: da| drin| darin)?(?: stehen)?(?: dass)?|soll (?:da |drin |darin )?stehen|mit folgendem text|folgendes|mit dem text|mit der nachricht|mit dem inhalt|und sag(?:e)?(?: ihm| ihr| ihnen)?(?: dass)?|dass|mit|text|nachricht)\s+)"

PATTERNS = [
    # schreib eine WhatsApp an Mama mit ...
    re.compile(rf"^{LEAD}\s+{FILLER}(?:(?:eine?|ne|der|dem)\s+)?{APP_WORDS}(?:[- ]?(?:nachricht|message|dm))?\s+(?:an|für|bei)\s+(?P<to>.+?){SEP}(?P<text>.+)$", re.I),
    # schreib Mama auf WhatsApp: ...
    re.compile(rf"^{LEAD}\s+{FILLER}(?:(?:eine?|ne)\s+(?:nachricht|message|dm)\s+)?(?:an\s+)?(?P<to>.+?)\s+(?:auf|per|über|bei|in|mit)\s+{APP_WORDS}{SEP}(?P<text>.+)$", re.I),
    re.compile(rf"^{LEAD}\s+{FILLER}(?:(?:eine?|ne)\s+(?:nachricht|message|dm)\s+)?(?:an\s+)?(?P<to>.+?)\s+(?:auf|per|über|bei|in|mit)\s+{APP_WORDS}\s+(?P<text>.+)$", re.I),
    # schick eine Nachricht an Mama: ...  (ohne App = WhatsApp)
    re.compile(rf"^{LEAD}\s+{FILLER}(?:(?:eine?|ne)\s+)?(?:nachricht|sms|message)\s+(?:an|für)\s+(?P<to>.+?){SEP}(?P<text>.+)$", re.I),
    # schick Opa eine WhatsApp: ...  /  schreib Opa eine Nachricht, dass ...
    re.compile(rf"^{LEAD}\s+{FILLER}(?:an\s+)?(?P<to>(?!mir\b|uns\b|das\b|es\b)[\wäöüß-]+(?:\s+[\wäöüß-]+)?)\s+(?:eine?|ne)\s+(?:{APP_WORDS}(?:[- ]?nachricht)?|nachricht|message)(?:{SEP}|\s+)(?P<text>.+)$", re.I),
    # schreib Opa, dass ...  /  schreib Opa: ...  (ohne App = WhatsApp)
    re.compile(r"^(?:schreib|schreibe|schick|schicke)\s+(?:mal\s+|bitte\s+)*(?:an\s+)?(?P<to>(?!mir\b|uns\b|das\b|es\b|was\b|ein\b|eine\b|mal\b)[\wäöüß-]+(?:\s+[\wäöüß-]+)?)(?:\s*,?\s+dass\s+|\s*:\s*)(?P<text>.+)$", re.I),
]
TRAILING = re.compile(r"\s+(?:und\s+)?(?:schick|schicke|sende|send)\w*\s+(?:sie|es|ihn|das)?\s*(?:auch\s+)?(?:gleich\s+)?(?:ab|los|weg)\s*$", re.I)


MARKERS = re.compile(
    r"\b(ah\s*nee|ach\s*nee|nee\s+doch|nein\s+doch|ne\s+doch|äh+m?|doch\s+(?:keine?n?|nicht|lieber)|streich\w*|vergiss\s+(?:das|die|den)|"
    r"lieber\s+doch|oder\s+besser|halt\s+nee|nein\s+warte|ich\s+meine|oder\s+nee|stopp\s+nicht)\b", re.I)


def polish(text: str) -> str:
    """Macht aus gesprochenem Hin und Her (\"Eier, Milch, Butter. Ah nee, doch keine Butter\") die fertige Nachricht."""
    if not MARKERS.search(text):
        return text
    try:
        import pc_ai

        if not pc_ai.gemini_key():
            return text
        system = ("Du formulierst Nachrichten für den Nutzer. Er hat sie gesprochen und sich dabei verbessert. "
                  "Gib NUR den endgültigen Nachrichtentext zurück, in der Ich-Form des Nutzers, natürlich und kurz, "
                  "Korrekturen eingearbeitet (Gestrichenes weglassen). Keine Erklärung, keine Anführungszeichen, nichts erfinden.")
        out = pc_ai.gemini_generate([{"role": "user", "parts": [{"text": text}]}], system, json_mode=False, max_tokens=400)
        out = out.strip().strip('"„“').strip()
        if 1 <= len(out) <= 800:
            return out
    except Exception as e:
        print(f"Nachricht konnte nicht überarbeitet werden: {e}")
    return text


def _rephrase(text: str, to: str, as_jarvis: bool) -> str:
    """Aus indirekter Rede („dass er heute anrufen soll“) eine richtige Nachricht machen."""
    try:
        import pc_ai
        if not (pc_ai.gemini_key() or pc_ai.groq_key()):
            return text
        who = ("Die Nachricht schreibt Jarvis, der Assistent des Nutzers Skyler, und spricht über Skyler in der dritten Person "
               "(z. B. „Skyler bittet dich, …“). Beginne NICHT mit „Hier ist Jarvis“.") if as_jarvis else \
              "Die Nachricht ist in der Ich-Form des Nutzers, locker, wie man an Familie und Freunde schreibt."
        system = ("Der Nutzer hat in indirekter Rede gesagt, was in einer WhatsApp an " + to + " stehen soll. Mach daraus die fertige, "
                  "kurze Nachricht in direkter Rede (Empfänger mit du ansprechen). " + who +
                  " Nichts hinzuerfinden. Gib NUR den Nachrichtentext zurück, ohne Anführungszeichen.")
        out = pc_ai.gemini_generate([{"role": "user", "parts": [{"text": "dass " + text}]}], system, json_mode=False,
                                    max_tokens=200, timeout=12, fast=True)
        out = (out or "").strip().strip('"„“').strip()
        if 1 <= len(out) <= 500:
            return out
    except Exception as e:
        print(f"Nachricht konnte nicht umformuliert werden: {e}")
    return text


def _norm_app(word: str) -> str:
    return "discord" if word.lower().startswith(("disc", "disk")) else "whatsapp"


def parse(command: str):
    """Gibt (app, empfänger, text) zurück oder None."""
    t = " ".join(command.strip().strip(" .!?").split())
    for pat in PATTERNS:
        m = pat.match(t)
        if not m:
            continue
        groups = m.groupdict()
        app = _norm_app(groups.get("app") or "whatsapp")
        to = re.sub(r"^(?:an|bei|für)\s+", "", groups["to"].strip(" ,:"), flags=re.I)
        text = TRAILING.sub("", groups["text"]).strip(" ,:")
        text = re.sub(r"^dass\s+", "", text, flags=re.I)
        to = to[0].upper() + to[1:]
        if to and text and len(to.split()) <= 4:
            return app, to, text[0].upper() + text[1:]
    return None


# --- Bedienen der Programme ---------------------------------------------------------------
def _set_clipboard(text: str):
    import ctypes

    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    data = text.encode("utf-16-le") + b"\0\0"
    handle = k.GlobalAlloc(0x42, len(data))  # GMEM_MOVEABLE | GMEM_ZEROINIT
    ptr = k.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    k.GlobalUnlock(handle)
    for _ in range(20):
        if u.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Zwischenablage ist gerade belegt")
    try:
        u.EmptyClipboard()
        u.SetClipboardData(13, handle)  # CF_UNICODETEXT
    finally:
        u.CloseClipboard()


def _paste(text: str):
    import pyautogui

    _set_clipboard(text)
    time.sleep(0.15)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)


def _front(names, hint, launch):
    """Holt das Fenster nach vorn, startet das Programm bei Bedarf. Gibt das Fensterhandle oder None zurück."""
    import pc_windows

    hwnd = pc_windows.find_main_window(names, hint)
    started = False
    if not hwnd:
        launch()
        started = True
        hwnd = pc_windows.wait_for_window(names, timeout=25, title_contains=hint)
    if not hwnd:
        return None, started
    pc_windows.bring_to_front(hwnd)
    time.sleep(2.5 if started else 0.6)
    return hwnd, started


def _launch_whatsapp():
    try:
        os.startfile("whatsapp:")  # type: ignore[attr-defined]
    except Exception:
        import pc_steuerung

        pc_steuerung.open_app("whatsapp")


def send_whatsapp(to: str, text: str) -> str:
    import pyautogui

    names, hint = ["whatsapp.exe", "whatsapp.root.exe"], "whatsapp"
    number = pc_memory.contact(to)
    if number:
        url = f"whatsapp://send?phone={number.lstrip('+')}&text={urllib.parse.quote(text)}"
        try:
            os.startfile(url)  # type: ignore[attr-defined]
        except Exception as e:
            return f"Ich konnte WhatsApp nicht öffnen: {e}"
        import pc_windows

        hwnd = pc_windows.wait_for_window(names, timeout=25, title_contains=hint)
        if not hwnd:
            return "WhatsApp hat sich nicht geöffnet."
        time.sleep(2.5)
        pc_windows.bring_to_front(hwnd)
        time.sleep(0.5)
        pyautogui.press("enter")
        return f"Erledigt, die WhatsApp an {to} ist raus: {text}"
    hwnd, _ = _front(names, hint, _launch_whatsapp)
    if not hwnd:
        return "WhatsApp läuft nicht und ich konnte es nicht öffnen."
    pyautogui.hotkey("ctrl", "f")  # Suche
    time.sleep(0.6)
    _paste(to)
    time.sleep(1.4)
    pyautogui.press("enter")  # erster Treffer
    time.sleep(1.0)
    _paste(text)
    time.sleep(0.3)
    pyautogui.press("enter")
    return f"Erledigt, ich habe {to} auf WhatsApp geschrieben: {text}"


def send_to_number(number: str, text: str) -> bool:
    """WhatsApp direkt an eine Nummer (auch an dich selbst: dann landet es in deinem Chat "Du")."""
    import pyautogui

    number = pc_memory.normalize_number(number)
    if not number:
        return False
    try:
        os.startfile(f"whatsapp://send?phone={number.lstrip('+')}&text={urllib.parse.quote(text)}")  # type: ignore
    except Exception as e:
        print(f"WhatsApp: {e}")
        return False
    import pc_windows

    hwnd = pc_windows.wait_for_window(["whatsapp.exe", "whatsapp.root.exe"], timeout=25, title_contains="whatsapp")
    if not hwnd:
        return False
    time.sleep(2.5)
    pc_windows.bring_to_front(hwnd)
    time.sleep(0.5)
    pyautogui.press("enter")
    return True


def send_discord(to: str, text: str) -> str:
    import pyautogui

    import pc_steuerung

    names = pc_steuerung.PROCESS_NAMES["discord"]
    hwnd, _ = _front(names, None, lambda: pc_steuerung.open_app("discord"))
    if not hwnd:
        return "Discord läuft nicht und ich konnte es nicht öffnen."
    pyautogui.hotkey("ctrl", "k")  # Schnellwechsler
    time.sleep(0.7)
    target = to.strip()
    m = re.match(r"^(?:kanal|channel)\s+(.+)$", target, re.I)
    target = "#" + m.group(1) if m else "@" + target
    _paste(target)
    time.sleep(1.2)
    pyautogui.press("enter")
    time.sleep(1.2)
    _paste(text)
    time.sleep(0.3)
    pyautogui.press("enter")
    return f"Erledigt, ich habe {to} auf Discord geschrieben: {text}"


def send(app: str, to: str, text: str) -> str:
    try:
        return send_discord(to, text) if app == "discord" else send_whatsapp(to, text)
    except Exception as e:
        return f"Das Senden hat nicht geklappt: {e}"


# --- Sprachbefehl --------------------------------------------------------------------------
YES = {"ja", "jawohl", "ja bitte", "sende", "sende sie", "schick", "schick sie", "schick es", "schick sie ab", "abschicken",
       "senden", "ja schick", "ja sende", "klar", "mach", "mach das", "bitte", "okay", "ok", "genau", "ja mach"}
NO = {"nein", "nee", "abbrechen", "stopp", "stop", "nicht", "lass es", "lieber nicht", "doch nicht", "brich ab"}


def awaiting() -> bool:
    return bool(PENDING and time.time() < PENDING[3])


def start(app: str, to: str, text: str) -> str:
    """Schickt die Nachricht ab oder fragt vorher nach (wenn eingestellt)."""
    global PENDING
    label = "WhatsApp" if app == "whatsapp" else "Discord"
    text = polish(text)
    if CONFIRM:
        PENDING = (app, to, text, time.time() + 25)
        return f"Ich schreibe {to} auf {label}: {text}. Soll ich das abschicken?"
    return send(app, to, text)


def handle(command: str):
    """Antwort auf einen Nachrichtenbefehl (oder auf die Rückfrage), sonst None."""
    global PENDING
    low = command.strip(" .!?,").lower()
    if PENDING is not None:
        app, to, text, until = PENDING
        PENDING = None
        if time.time() <= until:
            if low in YES or (low.startswith("ja") and len(low.split()) <= 3):
                return send(app, to, text)
            if low in NO:
                return "Okay, ich schicke nichts."
    as_jarvis = re.search(r"\b(?:unter|in|mit)\s+deinem\s+namen\b|\bals\s+jarvis\b|\bvon\s+dir\s+aus\b|\bals\s+du\b", low)
    cmd = re.sub(r",?\s*(?:unter|in|mit)\s+deinem\s+namen\b|,?\s*als\s+jarvis\b|,?\s*von\s+dir\s+aus\b|,?\s*als\s+du\b", "", command, flags=re.I) if as_jarvis else command
    parsed = parse(cmd)
    if not parsed:
        return None
    if re.search(r"\bdass\b", cmd, re.I):   # „dass er anrufen soll“ -> richtige Nachricht formulieren
        parsed = (parsed[0], parsed[1], _rephrase(parsed[2], parsed[1], bool(as_jarvis)))
    if as_jarvis:   # „Schreib Opa unter deinem Namen …“ -> „Hier ist Jarvis. …“; Antworten in dem Chat sagt er an
        app, to, text = parsed
        text = re.sub(r"^(?:hier ist jarvis[.,!]?\s*)", "", text, flags=re.I)
        parsed = (app, to, "Hier ist Jarvis. " + text[0].upper() + text[1:])
        try:
            import pc_handy
            if pc_handy.paired():   # das Handy meldet Antworten aus diesem Chat (24 Stunden lang)
                threading.Thread(target=lambda: pc_handy._send({"kind": "watch", "from": "pc", "name": to, "hours": 24,
                                                                "ts": int(time.time()), "id": "w"}), daemon=True).start()
        except Exception:
            pass
    return start(*parsed)
