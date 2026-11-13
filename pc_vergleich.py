"""
"Was ist besser, A oder B?" – Jarvis recherchiert im Netz (Tests, Daten, Preise) und gibt eine klare Empfehlung.

Suche: Groq "compound" (hat eine eingebaute Websuche) oder Gemini mit Google-Suche. Bezieht ein, was Jarvis über
dich weiß (z. B. dass du viel Feldwege fährst).
"""

import re

PROMPT = ("Du bist Jarvis, der persönliche Assistent des Nutzers, und hilfst ihm bei einer Kaufentscheidung oder einem Vergleich. "
          "Suche im Internet nach aktuellen Tests, Daten und Preisen zu den Dingen, die er vergleicht. Antworte auf Deutsch, gesprochen "
          "klingend, ohne Listen und ohne Sonderzeichen, in 5 bis 8 Sätzen: zuerst die wichtigsten Unterschiede (Preis, Qualität, "
          "Ausstattung, was für ihn zählt), dann eine klare Empfehlung mit Begründung (\"Ich würde … nehmen, weil …\"). Wenn es auf "
          "etwas ankommt, das du nicht weißt (z. B. Budget), sag kurz, wovon es abhängt. Erfinde keine Zahlen.")


def compare(items: list, frage: str = "", about: str = "") -> str:
    import pc_ai
    things = " oder ".join(str(i) for i in items if str(i).strip()) or frage
    q = f"Vergleich: {things}. {frage}".strip() + (f"\nWas ich über den Nutzer weiß: {about}" if about else "")
    # 1) Groq compound (Websuche eingebaut)
    if pc_ai.groq_key():
        for model in ("groq/compound", "groq/compound-mini", "compound-beta"):
            try:
                data = pc_ai._http_simple("https://api.groq.com/openai/v1/chat/completions",
                                          {"model": model, "max_tokens": 1200, "messages": [
                                              {"role": "system", "content": PROMPT}, {"role": "user", "content": q}]},
                                          {"Authorization": f"Bearer {pc_ai.groq_key()}", "User-Agent": "Jarvis"}, timeout=45)
                text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
                text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
                text = re.sub(r"[*#`]|\[\d+\]", "", text).strip()
                if text:
                    return text
            except Exception as e:
                print(f"Vergleich über {model} ging nicht: {e}")
    # 2) Gemini mit Google-Suche
    if pc_ai.gemini_key():
        try:
            body = {"systemInstruction": {"parts": [{"text": PROMPT}]},
                    "contents": [{"role": "user", "parts": [{"text": q}]}],
                    "tools": [{"google_search": {}}],
                    "generationConfig": {"maxOutputTokens": 2000, "temperature": 0.5}}
            for model in ("gemini-flash-latest", "gemini-2.5-flash"):
                try:
                    data = pc_ai._http(f"{pc_ai.GEMINI_BASE}/models/{model}:generateContent", body,
                                       {"x-goog-api-key": pc_ai.gemini_key()}, timeout=45)
                    text = pc_ai._extract_text(data)
                    if text:
                        return re.sub(r"[*#`]", "", text).strip()
                except Exception as e:
                    print(f"Vergleich über {model} ging nicht: {e}")
        except Exception:
            pass
    return "Die Recherche klappt gerade nicht. Versuch es gleich nochmal."
