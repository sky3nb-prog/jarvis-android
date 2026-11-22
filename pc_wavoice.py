"""
Sprachnachrichten direkt vom PC (WhatsApp am PC, kein Handy nötig):

  „Nimm eine Sprachnachricht auf und sag Jannis Hallo“ -> spricht WORTWÖRTLICH nur „Hallo“, sonst nichts.
  „Kannst du eine Sprachnachricht schicken?“ -> „An wen?“ -> „An Jannis, und zwar: …“ (auch wortwörtlich)
  „Antworte Jannis als Sprachnachricht“ (einzige Ausnahme) -> Jarvis überlegt sich selbst eine kurze Antwort

Normalfall = Diktat: genau das sagen, was gesagt wird, keine „Hey X, hier ist Jarvis“-Umrahmung, nichts dazuerfunden.
Nur bei „Antworte …“ formuliert Jarvis selbst etwas. Spricht mit der schnellen Stimme (Piper/Thorsten), wandelt sie
in Ogg/Opus um (das Format, das WhatsApp als echte Sprachnachricht mit Wellenform/Play-Knopf anzeigt statt als
Audio-Dateianhang) und schickt sie über WhatsApp am PC (Chat öffnen, Datei einfügen, Enter). Fehlt etwas, fragt er nach.
"""

import json
import os
import re
import shutil
import time

PENDING = {"t": 0.0, "an": "", "inhalt": "", "raw": True, "modus": "antwort"}
VOICE = re.compile(r"\bsprach ?nachricht\w*\b", re.I)
VERB = re.compile(r"\b(schick|send|nimm|nehm|aufnehm|mach|antworte|kannst du|könntest du|würdest du)\w*", re.I)
# "Antworte ..." / "frag ..., ob ..." = Jarvis soll selbst formulieren (einzige Ausnahmen, z. B. "frag, ob Ben
# Jarvis hat" -> "Ben, hast du Jarvis?"). Alles andere (vor allem "sag/sage …") wird WORTWÖRTLICH gesprochen –
# keine „Hey X, hier ist Jarvis“-Umrahmung, kein Dazuerfinden.
REPLY = re.compile(r"\bantworte\w*\b|\bfrag\w*\b", re.I)


def _extract(text: str) -> dict:
    """KI liest heraus: an wen, was soll drinstehen (oder leer)."""
    import pc_ai
    try:
        out = pc_ai.gemini_generate([{"role": "user", "parts": [{"text": text}]}],
                                    "Der Nutzer will per Sprachbefehl eine WhatsApp-Sprachnachricht verschicken. Lies heraus, AN WEN sie geht "
                                    "(nur der Name, z. B. \"Jannis\") und WAS gesagt werden soll (der Inhalt, ohne Füllwörter wie "
                                    "\"und zwar\", \"mit dem Inhalt\", \"sag ihm\"). Fehlt etwas, leer lassen. Antworte NUR als JSON: "
                                    "{\"an\":\"…\",\"inhalt\":\"…\"}", json_mode=True, max_tokens=200, timeout=12, fast=True)
        d = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
        return {"an": str(d.get("an") or "").strip(), "inhalt": str(d.get("inhalt") or "").strip()}
    except Exception:
        m = re.search(r"\ban\s+([A-Za-zÄÖÜäöüß-]+)", text)
        c = re.search(r"(?:inhalt|und zwar|sag(?:e)?|dass|:)\s*(.+)$", text, re.I)
        return {"an": m.group(1) if m else "", "inhalt": c.group(1).strip() if c else ""}


def _spoken(an: str, inhalt: str, modus: str = "antwort") -> str:
    """Was Jarvis sagt (kurz, locker, als Jarvis). modus="frage": direkte kurze Frage an `an` formulieren
    (z. B. Inhalt "ob Ben Jarvis hat" -> "Ben, hast du Jarvis?"), kein Jarvis-Gerede drumherum.
    modus="antwort": wie bisher, 3rd-Person-Ausrichtung mit kurzer Jarvis-Anmoderation."""
    import pc_ai
    if modus == "frage":
        try:
            t = pc_ai.gemini_generate([{"role": "user", "parts": [{"text": inhalt}]}],
                                      f"Formuliere daraus EINE kurze, direkte WhatsApp-Sprachnachricht an {an}, die genau das fragt – als ob "
                                      f"der Nutzer selbst fragt, nicht Jarvis. Nur die Frage, 1 Satz, keine Anmoderation, keine Emojis, kein "
                                      f"„Jarvis hier“. Beispiel: Eingabe „ob Ben Jarvis hat“ -> „Ben, hast du Jarvis?“",
                                      json_mode=False, max_tokens=60, timeout=12, fast=True).strip().strip('"')
            return t or inhalt
        except Exception:
            return inhalt
    try:
        t = pc_ai.gemini_generate([{"role": "user", "parts": [{"text": inhalt}]}],
                                  f"Du bist Jarvis, der KI-Assistent des Nutzers, und sprichst eine kurze WhatsApp-Sprachnachricht an {an}. "
                                  f"Fang locker an (z. B. „Hey {an}, hier ist Jarvis“), dann der Inhalt in 1–3 kurzen Sätzen, über den Nutzer "
                                  f"in der dritten Person („er“). Nur der gesprochene Text, keine Emojis.",
                                  json_mode=False, max_tokens=200, timeout=12, fast=True).strip().strip('"')
        return t or f"Hey {an}, hier ist Jarvis. Ich soll dir ausrichten: {inhalt}"
    except Exception:
        return f"Hey {an}, hier ist Jarvis. Ich soll dir ausrichten: {inhalt}"


def _audio(text: str) -> str:
    """Audiodatei mit der schnellen Stimme. Gibt den Pfad zurück."""
    import pc_piper
    if not pc_piper.ready():
        pc_piper.install()
    parts = [p for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip()] or [text]
    import wave
    out = os.path.join(pc_piper.folder(), "out", f"Jarvis-Sprachnachricht-{time.strftime('%H%M%S')}.wav")
    frames, params = [], None
    for p in parts:
        w = pc_piper.synth(p, 0, 20)
        with wave.open(w, "rb") as r:
            params = params or r.getparams()
            frames.append(r.readframes(r.getnframes()))
            frames.append(b"\0\0" * int(params.framerate * 0.2))
    with wave.open(out, "wb") as o:
        o.setparams(params)
        for f in frames:
            o.writeframes(f)
    import pc_ffmpeg
    return pc_ffmpeg.to_voice_note(out)   # .ogg/Opus, sonst erkennt WhatsApp es nicht als Sprachnachricht


def _clip_file(path: str):
    """Datei in die Zwischenablage legen (wie im Explorer kopiert)."""
    import ctypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    files = (os.path.abspath(path) + "\0\0").encode("utf-16-le")
    header = (20).to_bytes(4, "little") + b"\0" * 12 + (1).to_bytes(4, "little")   # DROPFILES: pFiles=20, fWide=1
    data = header + files
    h = k.GlobalAlloc(0x42, len(data))
    p = k.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    k.GlobalUnlock(h)
    for _ in range(20):
        if u.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Zwischenablage ist gerade belegt")
    try:
        u.EmptyClipboard()
        u.SetClipboardData(15, h)   # CF_HDROP
    finally:
        u.CloseClipboard()


def _open_chat(to: str) -> bool:
    import pyautogui
    import pc_memory
    import pc_messages
    import pc_windows
    names, hint = ["whatsapp.exe", "whatsapp.root.exe"], "whatsapp"
    number = pc_memory.contact(to)
    if number:
        try:
            os.startfile(f"whatsapp://send?phone={number.lstrip('+')}")  # type: ignore[attr-defined]
        except Exception:
            number = ""
    if number:
        hwnd = pc_windows.wait_for_window(names, timeout=25, title_contains=hint)
        if not hwnd:
            return False
        time.sleep(2.5)
        pc_windows.bring_to_front(hwnd)
        time.sleep(0.5)
        return True
    hwnd, _ = pc_messages._front(names, hint, pc_messages._launch_whatsapp)
    if not hwnd:
        return False
    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.6)
    pc_messages._paste(to)
    time.sleep(1.4)
    pyautogui.press("enter")
    time.sleep(1.0)
    return True


def send(to: str, inhalt: str, raw: bool = True, modus: str = "antwort") -> str:
    """Sprachnachricht über WhatsApp am PC.
    raw=True (Normalfall/Diktat): spricht GENAU diesen Text, Wort für Wort – keine „Hey X, hier ist Jarvis“-Umrahmung.
    raw=False: Jarvis formuliert selbst – modus="antwort" (bei „Antworte …“) oder modus="frage" (bei „frag, ob …“)."""
    import pyautogui
    try:
        import pc_gruppe
        to = pc_gruppe.resolve(to)
    except Exception:
        pass
    if not to:
        return "An wen soll die Sprachnachricht gehen?"
    spoken = inhalt.strip() if raw else _spoken(to, inhalt, modus)
    try:
        path = _audio(spoken)
    except Exception as e:
        return f"Die Sprachnachricht konnte ich nicht aufnehmen ({e})."
    if not _open_chat(to):
        return "WhatsApp am PC ging nicht auf."
    try:
        _clip_file(path)
        time.sleep(0.3)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(2.5)          # Vorschau abwarten
        pyautogui.press("enter")
    except Exception as e:
        return f"Einfügen in WhatsApp ging nicht ({e})."
    return f"Sprachnachricht an {to} ist raus: „{spoken}“"


def handle(text: str):
    """None = nicht für mich."""
    low = text.lower().strip(" .!?")
    if time.time() - PENDING["t"] < 90 and not VOICE.search(low):   # Antwort auf meine Rückfrage
        if re.match(r"^(nein|nee|abbrechen|stopp|lass|egal)\b", low):
            PENDING["t"] = 0
            return "Okay, keine Sprachnachricht."
        d = _extract(("An " + PENDING["an"] + ": " if PENDING["an"] else "") + text)
        an, inhalt = PENDING["an"] or d["an"], PENDING["inhalt"] or d["inhalt"]
        return _next(an, inhalt, PENDING["raw"], PENDING["modus"])
    if not (VOICE.search(low) and VERB.search(low)):
        return None
    raw = not REPLY.search(low)   # "antworte"/"frag ... ob" = Jarvis formuliert selbst; sonst wortwörtlich
    modus = "frage" if re.search(r"\bfrag\w*\b", low) and not re.search(r"\bantworte\w*\b", low) else "antwort"
    d = _extract(text)
    return _next(d["an"], d["inhalt"], raw, modus)


def _next(an: str, inhalt: str, raw: bool = True, modus: str = "antwort") -> str:
    if not an:
        PENDING.update(t=time.time(), an="", inhalt=inhalt, raw=raw, modus=modus)
        return "Klar. An wen soll die Sprachnachricht gehen?" + ("" if inhalt else " Und was soll ich sagen?")
    if not inhalt:
        PENDING.update(t=time.time(), an=an, inhalt="", raw=raw, modus=modus)
        if raw:
            return f"Was soll ich {an} sagen?"
        return f"Was soll ich {an} fragen?" if modus == "frage" else f"Worauf soll ich {an} antworten – was ist das Thema?"
    PENDING["t"] = 0
    return send(an, inhalt, raw=raw, modus=modus)


def test() -> str:
    """Test-Knopf: Sprachnachricht an den Test-Chat."""
    import pc_settings
    t = str(pc_settings.load().get("test_chat") or "").strip()
    if not t:
        return "Trag zuerst einen Test-Chat ein (Leute & Anrufe → Schreibstil & Antworten)."
    return send(t, "Das ist ein Test. Wenn du das hörst, klappen Sprachnachrichten vom PC.", raw=True)
