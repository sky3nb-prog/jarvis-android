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
ON_SHOW = None
ASK_FIRST = True   # Nachrichten wichtiger Leute: erst nur fragen ("weiter" oder "egal")
ON_QUIT = None   # vom Programm gesetzt: Programm beenden (Neustart nach einem Update)
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
    for k in ("sender", "chat", "text", "transcript"):
        if isinstance(msg.get(k), str):
            msg[k] = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", msg[k]).strip()
    if not msg.get("force") and _idle_seconds() > 20 * 60:   # niemand am PC: nicht in den leeren Raum reden
        print(f"Nachricht von {msg.get('sender')}: PC unbenutzt, keine Ansage")
        return
    with _lock:
        _announce.append(dict(msg, t=time.time()))
        del _announce[:-5]
    if msg.get("kind") in ("say", "offer"):
        print(f"Ansage vom Handy: {msg.get('question') or msg.get('text')}")
    else:
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
    if m.get("kind") == "say":   # Briefing, Begrüßung, "jetzt los" …
        PENDING = None
        return m.get("text") or "…"
    PENDING = m
    if m.get("kind") == "offer":   # "Dein Wochenrückblick ist da. Soll ich ihn vorlesen?"
        m["stage"] = "offer"
        return m.get("question") or "Soll ich?"
    if ASK_FIRST and m.get("kind") not in ("say", "offer"):   # erst nur fragen – "egal" verwirft sie (bleibt in WhatsApp ungelesen)
        m["stage"] = "ask"
        art = "Sprachnachricht" if m.get("voice") else "Nachricht"
        return f"Neue {art} von {_who(m)} – soll ich weitermachen, oder ist sie egal?"
    return _content(m)


def _content(m: dict) -> str:
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


def _transcribe(m: dict) -> str:
    """Sprachnachricht am PC in Text umwandeln (Groq Whisper), falls das Handy keinen Text mitgeschickt hat."""
    if m.get("transcript") or not m.get("audio"):
        return m.get("transcript") or ""
    try:
        import json
        import urllib.request
        import uuid
        import pc_ai
        key = pc_ai.groq_key()
        if not key:
            return ""
        audio = base64.b64decode(m["audio"])
        for model in ("whisper-large-v3-turbo", "whisper-large-v3"):
            b = "----jarvis" + uuid.uuid4().hex
            parts = []
            for k, v in (("model", model), ("language", "de"), ("response_format", "json")):
                parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="sprachnachricht.ogg"\r\n'
                         f'Content-Type: audio/ogg\r\n\r\n'.encode() + audio + b"\r\n")
            parts.append(f"--{b}--\r\n".encode())
            req = urllib.request.Request("https://api.groq.com/openai/v1/audio/transcriptions", data=b"".join(parts),
                                         headers={"Authorization": f"Bearer {key}", "User-Agent": "Jarvis",
                                                  "Content-Type": f"multipart/form-data; boundary={b}"})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    t = json.loads(r.read().decode("utf-8")).get("text", "").strip()
                    if t:
                        m["transcript"] = t
                        return t
            except Exception as e:
                print(f"Sprachnachricht umwandeln mit {model} ging nicht: {e}")
    except Exception as e:
        print(f"Sprachnachricht umwandeln ging nicht: {e}")
    return ""


def _draft(m: dict, wish: str = "") -> str:
    """Antwortvorschlag in seinem Namen. wish = Wunsch dazu ("auf Altdeutsch", "kürzer", "sag dass ich gleich komme")."""
    import pc_ai
    content = (_transcribe(m) if m.get("voice") else "") or m.get("text") or ""
    if m.get("voice") and not m.get("transcript"):
        content = "(eine Sprachnachricht, deren Inhalt ich nicht kenne)"
    sys_ = ("Du schreibst für den Nutzer (Skyler) eine kurze WhatsApp-Antwort in seinem Namen: Ich-Form, locker, wie ein "
            "Jugendlicher an Familie und Freunde schreibt, höchstens ein Emoji, meist 1 bis 2 Sätze. Geh NUR auf die Nachricht "
            "ein. Erfinde nichts über ihn (keine Pläne, Orte, Gefühle oder Erlebnisse), was nicht in der Nachricht oder im "
            "Wunsch steht. Wenn ein Wunsch angegeben ist, setze ihn genau um (Sprache, Stil, Länge, Inhalt). "
            "Gib nur den Antworttext zurück, sonst nichts.")
    prompt = f"Nachricht von {_who(m)}: {content}"
    if m.get("draft"):
        prompt += f"\nBisheriger Vorschlag: {m['draft']}"
    if wish:
        prompt += f"\nWunsch des Nutzers für die Antwort: {wish}"
    try:
        out = pc_ai.gemini_generate([{"role": "user", "parts": [{"text": prompt}]}],
                                    sys_, json_mode=False, max_tokens=300, timeout=15, fast=True)
        return re.sub(r'^["„“]|["“”]$', "", (out or "").strip())
    except Exception as e:
        print(f"Antwortvorschlag ging nicht: {e}")
        return ""


# "antworte auf Altdeutsch", "mach's kürzer", "netter", "sag noch, dass …" = Wunsch an den Vorschlag, kein Nachrichtentext
WISH = re.compile(r"^(?:auf|in|im|mit|ohne|als|so|kurz|kürzer|länger|netter|nett|freundlich\w*|lustig\w*|locker\w*|förmlich\w*|"
                  r"ernst\w*|höflich\w*|cooler|anders|nochmal|noch mal|neu|besser|mehr|weniger|englisch|deutsch|\w+deutsch|"
                  r"frag\w*|sag noch|schreib noch|und noch|aber)\b", re.I)
CHANGE = re.compile(r"^(?:mach(?:'s| es| das| sie)?|formulier\w*(?: es| das)?|änder\w*(?: es| das)?|schreib(?:'s| es| das| sie) |"
                    r"nimm|lieber|eher)\b", re.I)


def _propose(m: dict, wish: str = ""):
    if ON_STATUS:
        try:
            ON_STATUS("Einen Moment, ich formuliere …")
        except Exception:
            pass
    d = _draft(m, wish)
    if not d:
        m["stage"] = "dictate"
        return "Mir fällt gerade nichts Gutes ein. Was soll ich schreiben?"
    m.update(stage="confirm", draft=d)
    return f"Ich würde schreiben: {_end(d)} Passt das?"


def _literal(text: str, m: dict) -> str:
    """Diktierter Text; "dass er anrufen soll" wird zu einer richtigen Nachricht."""
    if re.match(r"^dass\b", text, re.I) or re.search(r"\bdass\b", text[:12], re.I):
        try:
            import pc_messages
            return pc_messages._rephrase(re.sub(r"^dass\s+", "", text, flags=re.I), str(m.get("sender") or ""), False)
        except Exception:
            pass
    return text


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
    print(f"Nachrichten-Dialog ({m.get('stage')}): {text}")
    if m.get("stage") == "ask":
        if re.search(r"\begal\b|ignorier|vergiss|unwichtig|nicht wichtig|später|nein|nö|nee|lass", low):
            PENDING = None
            return "Okay, ignoriert."
        if YES.match(low) or re.search(r"weiter|lies|vorlesen|was schreibt|zeig|sag|abspiel|anhör|erzähl", low):
            if re.search(r"abspiel|anhör|spiel", low) and m.get("voice"):
                m["stage"] = "voice"
                return _play(m)
            if re.search(r"lies|vorlesen", low) and m.get("voice"):
                m["stage"] = "voice"
                return handle("vorlesen")
            return _content(m)
        return None
    if m.get("stage") == "offer":
        if YES.match(low) or re.search(r"\b(?:vorlesen|lies|zeig|öffne|mach)\b", low):
            PENDING = None
            if m.get("action") == "shutdown":
                import pc_alltag
                return pc_alltag.shutdown_sequence()
            if m.get("action") == "update" and ON_QUIT:
                import pc_update
                return pc_update.restart(ON_QUIT)
            if ON_SHOW and m.get("text"):
                try:
                    ON_SHOW(m.get("title") or "Jarvis", m["text"])
                except Exception:
                    pass
            return m.get("text") or "Okay."
        if NO.match(low):
            PENDING = None
            return "Okay, " + ("der PC bleibt an." if m.get("action") == "shutdown" else "dann beim nächsten Mal." if m.get("action") == "update" else "später.")
        return None
    # "antworte/schreib ihm: …" – Rest ist entweder der Text oder ein Wunsch ("auf Altdeutsch")
    direct = re.match(r"^(?:dann\s+|ok(?:ay)?\s+|ja\s+)?(?:antworte|antwort|schreib|schreibe|sag|sende)\w*\s*(?:ihm|ihr|ihnen|zurück)?\s*[:,]?\s+(.{2,})$",
                      text.strip(), re.I)
    rest = direct.group(1).strip() if direct else ""
    if direct and re.match(r"^du\b", rest, re.I):   # "antworte du (auf Englisch)"
        return _propose(m, re.sub(r"^du\b[,\s]*", "", rest, flags=re.I))
    if m.get("stage") == "voice":
        if re.search(r"abspiel|anmach|anhör|play|spiel", low):
            r = _play(m)
            m["stage"] = "after"
            return (r + " " if r else "") + "Willst du antworten, oder soll ich?"
        if re.search(r"vorles|lies|transkri|text", low):
            m["stage"] = "after"
            t = _transcribe(m) or "Ich konnte sie leider nicht in Text umwandeln."
            return f"{m.get('sender')} sagt: {_end(t)} Willst du antworten, oder soll ich?"
        if NO.match(low):
            PENDING = None
            return "Okay, später."
        m["stage"] = "after"   # gleich zur Antwort ("antworte du") – sonst unten weiter
    if m.get("stage") == "dictate":
        PENDING = None
        return send(m, _literal(rest or text.strip(), m))
    if m.get("stage") == "confirm":
        if YES.match(low) and not CHANGE.match(low):
            PENDING = None
            return send(m, m.get("draft", ""))
        nm = re.match(r"^(?:nein|nee|ne|nö)[,.!]?\s*(?:schreib|antworte|sag)\w*\s*(?:stattdessen\s+)?[:,]?\s*(.{2,})$", text.strip(), re.I)
        if nm and not WISH.match(nm.group(1)):
            PENDING = None
            return send(m, _literal(nm.group(1).strip(), m))
        if re.match(r"^(?:nein|nee|ne|nö)\W*$", low):
            m["stage"] = "dictate"
            return "Okay. Was soll ich stattdessen schreiben?"
        if NO.match(low) and len(low.split()) <= 3:
            PENDING = None
            return "Okay, ich schicke nichts."
        if direct and not WISH.match(rest) and not CHANGE.match(text.strip()):
            PENDING = None
            return send(m, _literal(rest, m))
        # alles andere ist ein Änderungswunsch: "auf Altdeutsch", "mach's kürzer", "sag noch, dass ich später komme"
        wish = re.sub(r"^(?:nein|nee|ne|nö)[,.!]?\s*", "", text.strip(), flags=re.I)
        return _propose(m, wish)
    # stage "after": antworten?
    if direct:
        if WISH.match(rest) or CHANGE.match(rest):
            return _propose(m, rest)
        PENDING = None
        return send(m, _literal(rest, m))
    if re.search(r"\b(?:antworte du|schreib du|mach du|du antwortest|antworte mal|antworte für mich|schlag was vor|du)\b", low) \
            and not re.search(r"\bich\b", low):
        return _propose(m, re.sub(r"^.*?\b(?:antworte du|schreib du|mach du|du antwortest|du)\b[,\s]*", "", text, flags=re.I).strip())
    if re.search(r"\b(?:ich antworte|ich schreib|ich sag dir|ich diktier)\w*", low) or YES.match(low):
        m["stage"] = "dictate"
        return "Was soll ich schreiben?"
    if NO.match(low):
        PENDING = None
        return "Okay, ich lass es."
    return None
