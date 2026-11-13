"""
Nachrichten von wichtigen Leuten am PC (kommen vom Handy, das die WhatsApp-Benachrichtigungen liest).

  "Mama hat dir eine Sprachnachricht geschickt. Soll ich sie vorlesen oder abspielen?"
  -> "abspielen": läuft über die PC-Lautsprecher, WhatsApp geht nicht auf (Spiel läuft weiter)
  -> "vorlesen": Text der Sprachnachricht (am Handy mit Groq Whisper umgewandelt)
  "Willst du antworten, oder soll ich?"
  -> "antworte du"  : Vorschlag -> "Passt das?" -> "ja" = senden / "nein, schreib …"
  -> "ich antworte" : nächster Satz wird genau so geschickt
  -> "antworte: …" / "schreib: …": direkt senden
  -> "nein" / "später": nichts tun
Gesendet wird über die Antworten-Funktion der WhatsApp-Benachrichtigung am Handy (WhatsApp geht nirgends auf);
klappt das nicht, über WhatsApp am PC.
"""

import base64
import os
import re
import tempfile
import threading
import time

PENDING = None            # aktuelle Nachricht + Gesprächsstand
ON_STATUS = None          # vom Programm gesetzt: kurze Zwischenmeldung ("Einen Moment …") anzeigen und sagen
_announce = []            # Nachrichten, die noch angesagt werden müssen
_lock = threading.Lock()
ACTIVE_FOR = 180          # so lange (s) gilt eine Antwort wie "abspielen" noch für diese Nachricht

YES = re.compile(r"^(?:ja|jo|jep|klar|passt|genau|ok|okay|gerne|mach|schick(?:'s| es| das| ab)?|abschicken|senden|perfekt|gut so)\b", re.I)
NO = re.compile(r"^(?:nein|nö|ne|nee|lass|später|nicht jetzt|egal|ignorier|vergiss)\b", re.I)


def _idle_seconds() -> float:
    """Wie lange niemand Maus/Tastatur benutzt hat (Windows)."""
    try:
        import ctypes

        class LII(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        lii = LII()
        lii.cbSize = ctypes.sizeof(LII)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0
    except Exception:
        pass
    return 0.0


def incoming(msg: dict):
    """Vom Handy: {sender, chat, text, voice, transcript, audio(b64 ogg), key}."""
    if _idle_seconds() > 20 * 60:   # niemand am PC: nicht in den leeren Raum reden
        print(f"Nachricht von {msg.get('sender')}: PC unbenutzt, keine Ansage")
        return
    with _lock:
        _announce.append(dict(msg, t=time.time()))
        del _announce[:-5]
    print(f"Nachricht von {msg.get('sender')} ({'Sprachnachricht' if msg.get('voice') else 'Text'}) – wird angesagt")


def take_announce() -> bool:
    """Für die Hörschleife: gibt es etwas anzusagen? Dann läuft "__nachricht__" wie ein Befehl."""
    with _lock:
        return bool(_announce)


def awaiting() -> bool:
    return PENDING is not None and time.time() - PENDING.get("t", 0) < ACTIVE_FOR


def _end(t: str) -> str:
    t = str(t or "").strip()
    return t if t.endswith((".", "!", "?", "…")) else t + "."


def _who(m: dict) -> str:
    s, c = str(m.get("sender") or "").strip(), str(m.get("chat") or "").strip()
    return f"{s} in {c}" if c and s and c.lower() != s.lower() else (s or c or "Jemand")


def announce_text() -> str:
    global PENDING
    with _lock:
        if not _announce:
            return "Keine neue Nachricht."
        m = _announce.pop(0)
    m["t"] = time.time()
    PENDING = m
    if m.get("voice"):
        m["stage"] = "voice"
        return f"{_who(m)} hat dir eine Sprachnachricht geschickt. Soll ich sie vorlesen oder abspielen?"
    m["stage"] = "after"
    return f"Nachricht von {_who(m)}: {_end(m.get('text', ''))} Willst du antworten, oder soll ich?"


def _play(m: dict) -> str:
    data = m.get("audio")
    if not data:
        return "Die Sprachnachricht selbst habe ich nicht bekommen. Soll ich sie vorlesen?"
    path = os.path.join(tempfile.gettempdir(), "jarvis_sprachnachricht.ogg")
    with open(path, "wb") as f:
        f.write(base64.b64decode(data))
    try:
        import sounddevice as sd
        import soundfile as sf
        audio, rate = sf.read(path, dtype="float32")
        sd.play(audio, rate)
        sd.wait()   # bis zum Ende, danach kommt die Frage
        return ""
    except Exception as e:
        print(f"Abspielen über soundfile ging nicht ({e}), nehme den Standard-Player")
        try:
            os.startfile(path)   # type: ignore[attr-defined]
            time.sleep(min(60, max(4, len(data) / 4000)))
        except Exception:
            return "Abspielen ging nicht. Soll ich sie vorlesen?"
        return ""


def _draft(m: dict) -> str:
    """Antwortvorschlag in seinem Namen (kurz, passend, wie er schreibt)."""
    import pc_ai
    import pc_memory
    content = m.get("transcript") or m.get("text") or ""
    sys_ = ("Du schreibst für den Nutzer eine kurze WhatsApp-Antwort in seinem Namen (Ich-Form, locker, wie ein Jugendlicher "
            "an Familie und Freunde schreibt, ohne Emojis-Flut, höchstens ein Emoji). Nur den Antworttext, sonst nichts.\n"
            + (pc_memory.prompt_block() or "")[:1500])
    try:
        out = pc_ai.gemini_generate([{"role": "user", "parts": [{"text": f"Nachricht von {_who(m)}: {content}"}]}],
                                    sys_, json_mode=False, max_tokens=200, timeout=15, fast=True)
        return re.sub(r'^["„“]|["“”]$', "", (out or "").strip())
    except Exception as e:
        print(f"Antwortvorschlag ging nicht: {e}")
        return ""


def send(m: dict, text: str) -> str:
    """Antwort senden: zuerst übers Handy (Benachrichtigung, nichts geht auf), sonst WhatsApp am PC."""
    import pc_handy
    if pc_handy.paired() and m.get("key"):
        r = pc_handy.ask("wa_reply", wait=20, key=m.get("key"), chat=m.get("chat"), text=text)
        if r and r.get("ok"):
            return f"Geschickt: {text}"
    try:
        import pc_messages
        return pc_messages.send_whatsapp(str(m.get("chat") or m.get("sender")), text)
    except Exception as e:
        return f"Senden ging nicht: {e}"


def handle(text: str):
    """Antworten auf eine Ansage. None = gehört nicht hierher."""
    global PENDING
    if text == "__nachricht__":
        return announce_text()
    if not awaiting():
        return None
    m, low = PENDING, (text or "").lower().strip(" .!?")
    m["t"] = time.time()
    direct = re.match(r"^(?:dann\s+)?(?:antworte|schreib|schreibe|sag|sende)\w*\s*(?:ihm|ihr|zurück|ihnen)?\s*[:,]?\s+(?:dass\s+)?(.{2,})$", text.strip(), re.I)
    if m.get("stage") == "voice":
        if re.search(r"abspiel|anmach|anhör|play|spiel", low):
            r = _play(m)
            m["stage"] = "after"
            return (r + " " if r else "") + "Willst du antworten, oder soll ich?"
        if re.search(r"vorles|lies|transkri|text", low):
            m["stage"] = "after"
            t = m.get("transcript") or "Ich konnte sie leider nicht in Text umwandeln."
            return f"{m.get('sender')} sagt: {_end(t)} Willst du antworten, oder soll ich?"
        if NO.match(low):
            PENDING = None
            return "Okay, später."
        return None
    if m.get("stage") == "dictate":
        PENDING = None
        return send(m, text.strip())
    if m.get("stage") == "confirm":
        if YES.match(low):
            PENDING = None
            return send(m, m.get("draft", ""))
        if direct:
            PENDING = None
            return send(m, direct.group(1).strip())
        nm = re.match(r"^(?:nein|nee|ne|nö)[,.!]?\s*(?:schreib|antworte|sag)\w*\s*[:,]?\s*(.{2,})$", text.strip(), re.I)
        if nm:
            PENDING = None
            return send(m, nm.group(1).strip())
        if NO.match(low):
            m["stage"] = "dictate"
            return "Okay. Was soll ich schreiben?"
        return None
    # stage "after": antworten?
    if direct and not re.match(r"^(?:antworte|schreib)\w*\s+du\b", low):
        PENDING = None
        return send(m, direct.group(1).strip())
    if re.search(r"\b(?:antworte du|schreib du|mach du|du antwortest|antworte mal|antworte für mich|schlag was vor)\b", low):
        if ON_STATUS:
            try:
                ON_STATUS("Einen Moment, ich formuliere …")
            except Exception:
                pass
        d = _draft(m)
        if not d:
            m["stage"] = "dictate"
            return "Mir fällt gerade nichts Gutes ein. Was soll ich schreiben?"
        m.update(stage="confirm", draft=d)
        return f"Ich würde schreiben: {_end(d)} Passt das?"
    if re.search(r"\b(?:ich antworte|ich schreib|ich sag dir|ich diktier)\w*", low) or YES.match(low):
        m["stage"] = "dictate"
        return "Was soll ich schreiben?"
    if NO.match(low):
        PENDING = None
        return "Okay, ich lass es."
    return None
