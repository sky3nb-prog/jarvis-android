"""
"Schau mal hier": Jarvis sieht sich auf Kommando den Bildschirm an (PC) oder bittet das Handy darum.

- "Friday, schau mal hier – was ist das für ein Fehler?"      -> Bildschirmfoto vom PC, Gemini schaut es sich an
- "Schau mal auf mein Handy, was steht da?"                   -> das Handy macht das Foto und antwortet
Nur wenn du es sagst; das Bild geht zur Auswertung an Google (Gemini) und wird nicht gespeichert.
"""

import base64
import io
import re

ASK = re.compile(r"\bschau\w*\s+(?:mal\s+|dir\s+|doch\s+)*(?:hier|her|da|drauf|auf\s+(?:den|meinen|mein|das)\s+\w+)|\bguck\w*\s+(?:mal\s+|dir\s+)*(?:hier|da|drauf|auf)\b|"
                 r"\bwas\s+siehst\s+du\b|\bwas\s+ist\s+das\s+(?:hier|da)\b|\bsiehst\s+du\s+(?:das|hier)\b|\bbildschirm\s+an\b|"
                 r"\bauf\s+(?:meinem|meinen|dem)\s+bildschirm\b", re.I)
PHONE = re.compile(r"\b(?:handy|telefon|smartphone)\b", re.I)

SYSTEM = ("Du bist Jarvis, der persönliche Assistent des Nutzers. Du siehst ein Bildschirmfoto von seinem PC. Beantworte seine Frage "
          "dazu auf Deutsch, gesprochen klingend, kurz (2 bis 5 Sätze), konkret auf das bezogen, was zu sehen ist. Wenn er nichts "
          "Bestimmtes fragt, sag knapp, was zu sehen ist und was daran wichtig sein könnte. Lies keine Passwörter, Kontonummern "
          "oder Codes vor, auch wenn sie zu sehen sind. Keine Sonderzeichen, keine Listen.")


def screenshot_b64() -> str:
    from PIL import ImageGrab
    img = ImageGrab.grab()   # Hauptbildschirm
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def look(question: str) -> str:
    """Bildschirm vom PC ansehen und die Frage beantworten."""
    import pc_ai
    if not pc_ai.gemini_key():
        return "Zum Anschauen brauche ich den Gemini-Schlüssel. Trag ihn in den Einstellungen unter KI ein."
    try:
        img = screenshot_b64()
    except Exception as e:
        return f"Das Bildschirmfoto hat nicht geklappt: {e}"
    contents = [{"role": "user", "parts": [{"inline_data": {"mime_type": "image/jpeg", "data": img}},
                                           {"text": question or "Was siehst du hier?"}]}]
    try:
        text = pc_ai._gemini_generate(contents, SYSTEM, json_mode=False, max_tokens=900, timeout=40)
    except Exception as e:
        try:
            return pc_ai.explain(e)
        except Exception:
            return f"Das Anschauen ging nicht: {e}"
    return re.sub(r"[*#`]", "", text or "").strip() or "Ich sehe gerade nichts Auffälliges."


def handle(text: str):
    """Gibt die Antwort zurück, wenn er etwas angeschaut haben will, sonst None."""
    if not ASK.search(text or ""):
        return None
    if PHONE.search(text):   # "schau mal auf mein Handy"
        import pc_handy
        if not pc_handy.paired():
            return "Dein Handy ist noch nicht gekoppelt."
        r = pc_handy.ask("screen", wait=40, frage=text)
        return (r or {}).get("text") or "Dein Handy antwortet gerade nicht. Ist die Jarvis-App dort an?"
    return look(text)
