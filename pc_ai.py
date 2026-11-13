"""
KI-Anbindung: Google Gemini (Standard) und optional Anthropic Claude. Nur Standardbibliothek,
es muss nichts zusätzlich installiert werden.

Den Gemini-Schlüssel trägst du in den Jarvis-Einstellungen unter "KI" ein (Zahnrad im HUD)
oder als Umgebungsvariable GEMINI_API_KEY. Schlüssel gibt es kostenlos auf aistudio.google.com/apikey.

Das Modell wählt Jarvis selbst: Er fragt bei Google, welche Modelle dein Schlüssel nutzen kann, und nimmt
ein schnelles Flash-Modell. Fällt eines aus (Modellnamen ändern sich bei Google häufig), probiert er das nächste.
"""

import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Reihenfolge, in der automatisch gewählt wird, wenn das Modell verfügbar ist
# Zuerst ein Modell, bei dem sich das Nachdenken sicher ganz abschalten lässt (am schnellsten)
PREFERRED = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-flash-lite-latest"]
# Namensbestandteile, die für einen schnellen Sprachassistenten nicht passen
_SKIP = ("image", "tts", "live", "audio", "embedding", "thinking", "exp", "vision", "robotics",
         "computer", "veo", "imagen", "native", "pro", "gemma", "learnlm", "aqa")

KEY = ""  # wird aus den Einstellungen gesetzt
GROQ_KEY = ""  # kostenloser Ersatz (console.groq.com), wird aus den Einstellungen gesetzt
GROQ_MODELS = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "llama-3.1-8b-instant"]  # Startliste
_groq_live = {"key": None, "models": None, "t": 0.0}
# Reihenfolge, in der Jarvis die Groq-Modelle bevorzugt (Teile des Namens); Sprach-/Wächter-Modelle fallen raus
GROQ_PREF = ["llama-3.3-70b", "gpt-oss-120b", "llama-4-maverick", "kimi-k2", "llama-4-scout", "qwen3", "gpt-oss-20b",
             "llama", "gpt-oss", ""]
GROQ_SKIP = ("whisper", "guard", "tts", "playai", "orpheus", "distil", "compound", "embed", "vision", "speech")
_gemini_pause_until = 0.0  # nach "Kontingent aufgebraucht" eine Weile direkt den Ersatz nehmen
MODEL = "auto"  # "auto" oder ein fester Modellname
_model_cache = None  # (Schlüssel, Modell)


class AIError(Exception):
    """Fehler der KI-Schnittstelle. code = HTTP-Status (0 = keine Verbindung)."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def gemini_key() -> str:
    return (KEY or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def anthropic_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def groq_key() -> str:
    return (GROQ_KEY or os.environ.get("GROQ_API_KEY") or "").strip()


def available() -> bool:
    return bool(gemini_key() or groq_key() or anthropic_key())


def provider_name() -> str:
    if gemini_key():
        return "Gemini" + (" + Groq" if groq_key() else "")
    return "Groq" if groq_key() else "Claude" if anthropic_key() else ""


def reset_cache():
    global _model_cache
    _model_cache = None


def explain(e: AIError) -> str:
    """Verständliche Meldung für Fehler."""
    msg = (e.message or "").lower()
    if e.code == 0:
        return "Ich komme gerade nicht ins Internet zu Gemini."
    if e.code in (400, 401) and ("api key" in msg or "api_key" in msg):
        return "Der Gemini-Schlüssel ist ungültig. Prüfe ihn in den Einstellungen unter KI."
    if e.code == 403:
        return "Der Gemini-Schlüssel hat keine Erlaubnis. Prüfe in Google AI Studio, ob der Schlüssel aktiv ist."
    if e.code == 429:
        return ("Das kostenlose Gemini-Kontingent ist gerade aufgebraucht. Mit einem kostenlosen Groq-Schlüssel "
                "(Einstellungen, KI) springe ich dann automatisch ein.")
    if e.code in (500, 502, 503, 504):
        return "Gemini ist gerade überlastet. Versuch es gleich nochmal."
    return f"Gemini-Fehler {e.code}: {e.message[:120]}"


# --- HTTP ---------------------------------------------------------------------------
_local = threading.local()


def _err_text(body: str) -> str:
    """Fehlermeldung von Google, bei "invalid argument" mit dem Feld, das Google bemängelt."""
    err = json.loads(body)["error"]
    msg = err.get("message", "")
    for d in err.get("details") or []:
        for v in d.get("fieldViolations") or []:
            msg += f" [{v.get('field', '')}: {v.get('description', '')}]"
    return msg


def _http(url: str, payload=None, headers=None, timeout: float = 25.0) -> dict:
    """Wie _http_simple, hält aber die Verbindung zu Google offen. Das spart bei jeder Frage den
    Verbindungsaufbau (rund eine halbe Sekunde)."""
    parts = urllib.parse.urlsplit(url)
    if True:  # einfache Verbindung: die offen gehaltene Verbindung brach bei manchen Anschlüssen ab
        return _http_simple(url, payload, headers, timeout)
    try:
        return _http_keepalive(url, parts, payload, headers, timeout)
    except AIError as e:
        if e.code != 0 or "timed out" in e.message.lower():
            raise
        _local.simple = True  # Dauerverbindung klappt hier nicht: ab jetzt wie früher
        return _http_simple(url, payload, headers, timeout)


def _http_keepalive(url, parts, payload, headers, timeout) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    for attempt in range(2):
        conns = getattr(_local, "conns", None)
        if conns is None:
            conns = _local.conns = {}
        conn = conns.get(parts.netloc)
        if conn is None:
            conn = conns[parts.netloc] = http.client.HTTPSConnection(parts.netloc, timeout=timeout)
        conn.timeout = timeout
        try:
            conn.request("POST" if data is not None else "GET", path, body=data, headers=hdrs)
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", "ignore")
        except (http.client.HTTPException, OSError) as e:
            conn.close()
            conns.pop(parts.netloc, None)
            if attempt == 0 and not isinstance(e, TimeoutError):
                continue  # alte Verbindung war schon zu: einmal neu verbinden
            raise AIError(0, str(e)) from None
        if resp.status >= 400:
            try:
                message = _err_text(body)
            except Exception:
                message = body[:200]
            raise AIError(resp.status, message)
        return json.loads(body)
    raise AIError(0, "Keine Verbindung")


def _http_simple(url: str, payload=None, headers=None, timeout: float = 25.0) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if payload is not None else "GET",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        try:
            message = _err_text(body)
        except Exception:
            message = body[:200]
        raise AIError(e.code, message) from None
    except urllib.error.URLError as e:
        raise AIError(0, str(e.reason)) from None
    except (TimeoutError, OSError) as e:
        raise AIError(0, str(e)) from None


# --- Modelle ----------------------------------------------------------------------------
def list_models(key: str = None) -> list:
    """Namen aller Modelle, die dieser Schlüssel zum Antworten nutzen kann."""
    key = key or gemini_key()
    names, token = [], None
    for _ in range(5):
        url = f"{GEMINI_BASE}/models?pageSize=200" + (f"&pageToken={token}" if token else "")
        data = _http(url, headers={"x-goog-api-key": key}, timeout=15)
        for m in data.get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                names.append(m["name"].split("/", 1)[-1])
        token = data.get("nextPageToken")
        if not token:
            break
    return names


def _version_key(name: str):
    nums = tuple(int(x) for x in re.findall(r"\d+", name))
    return (0 if "preview" in name else 1, nums)


def choose_model(names: list) -> str:
    """Wählt aus der Liste verfügbarer Modelle das beste für einen schnellen Assistenten."""
    for pref in PREFERRED:
        if pref in names:
            return pref
    flash = [n for n in names if "flash" in n and not any(b in n for b in _SKIP)]
    if flash:
        full = [n for n in flash if "lite" not in n] or flash
        return sorted(full, key=_version_key, reverse=True)[0]
    return names[0] if names else PREFERRED[1]


def pick_model(key: str, avoid=()) -> str:
    global _model_cache
    if MODEL and MODEL != "auto" and MODEL not in avoid:
        return MODEL
    if _model_cache and _model_cache[0] == key and _model_cache[1] not in avoid:
        return _model_cache[1]
    try:
        names = [n for n in list_models(key) if n not in avoid]
    except AIError as e:
        if e.code in (400, 401, 403):
            raise
        names = []
    choice = choose_model(names) if names else next((p for p in PREFERRED if p not in avoid), PREFERRED[1])
    _model_cache = (key, choice)
    return choice


# --- Antworten ----------------------------------------------------------------------------
def _extract_text(data: dict) -> str:
    cands = data.get("candidates") or []
    if not cands:
        reason = (data.get("promptFeedback") or {}).get("blockReason")
        raise AIError(0, "Die Anfrage wurde von Gemini blockiert" + (f" ({reason})" if reason else ""))
    parts = (cands[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


def _gemini_generate(contents: list, system: str, key: str = None, json_mode: bool = True,
                     max_tokens: int = 1024, timeout: float = 30, prefer: str = None) -> str:
    """Eine Anfrage an Gemini. contents = Verlauf als [{"role": "user"|"model", "parts": [{"text": ...}]}]."""
    key = key or gemini_key()
    tried: list = []
    retried_empty = False
    t_all = time.time()
    try:
        first = pick_model(key)
    except AIError:
        first = None
    gone = set()  # Modelle, die es nicht (mehr) gibt
    for _ in range(10):
        model = prefer if (prefer and prefer not in tried) else pick_model(key, avoid=tuple(tried))
        options = _think_options(model)
        idx = min(_THINK_OK.get(model, 0), len(options) - 1)
        think = options[idx]
        config = {"temperature": 0.7, "maxOutputTokens": max_tokens}
        if json_mode:
            config["responseMimeType"] = "application/json"
        if think:
            config["thinkingConfig"] = think
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents, "generationConfig": config}
        t0 = time.time()
        try:
            data = _http(f"{GEMINI_BASE}/models/{model}:generateContent", body,
                         {"x-goog-api-key": key}, timeout=timeout)
        except AIError as e:
            if e.code == 404:  # Modell gibt es nicht (mehr): das nächste probieren
                tried.append(model)
                gone.add(model)
                reset_cache()
                continue
            key_problem = "api key" in e.message.lower() or "api_key" in e.message.lower()
            if e.code == 400 and not key_problem:
                print(f"Gemini 400 bei {model} mit {think}: {e.message[:150]}")
                if idx + 1 < len(options):
                    # Dieses Modell kennt die Einstellung wohl nicht: die nächste "wenig nachdenken"-Variante probieren.
                    # (Google sagt dann oft nur "invalid argument", ohne das Wort "think".)
                    _THINK_OK[model] = idx + 1
                    continue
                if len(tried) < 3:  # mit keiner Einstellung: anderes Modell probieren
                    tried.append(model)
                    reset_cache()
                    continue
            if e.code == 429 and len(tried) < 1:  # Kontingent dieses Modells leer: ein anderes hat ein eigenes
                tried.append(model)
                reset_cache()
                continue
            if e.code in (500, 502, 503, 504) and len(tried) < 2:
                time.sleep(0.3)
                tried.append(model)  # andere Modelle sind oft nicht überlastet
                continue
            raise
        print(f"Zeit: Gemini ({model}, {think or 'Standard'}) {time.time() - t0:.1f} s, gesamt {time.time() - t_all:.1f} s")
        text = _extract_text(data)
        if text:
            # Wegen kurzer Überlastung ausgewichen? Beim nächsten Mal wieder das eigentliche Modell nehmen.
            if first and model != first and first not in gone and MODEL in ("", "auto"):
                global _model_cache
                _model_cache = (key, first)
            return text
        if not retried_empty:  # leer, weil das "Nachdenken" alle Zeichen verbraucht hat: mit mehr Platz nochmal
            retried_empty = True
            max_tokens = max(max_tokens * 2, 2048)
            continue
        raise AIError(0, "Gemini hat nichts geantwortet")
    raise AIError(404, "Kein passendes Gemini-Modell gefunden")


def _groq_models() -> list:
    """Fragt Groq einmal pro Tag, welche Modelle es gerade gibt (Groq tauscht Modelle immer wieder aus)."""
    k = groq_key()
    if _groq_live["models"] and _groq_live["key"] == k and time.time() - _groq_live["t"] < 86400:
        return _groq_live["models"]
    try:
        data = _http_simple("https://api.groq.com/openai/v1/models", None,
                            {"Authorization": f"Bearer {k}", "User-Agent": "Jarvis"}, timeout=10)
        ids = [m.get("id", "") for m in data.get("data") or [] if m.get("active", True)]
        ids = [i for i in ids if i and not any(x in i.lower() for x in GROQ_SKIP)]
        ranked = []
        for pref in GROQ_PREF:
            for i in sorted(ids):
                if pref in i.lower() and i not in ranked:
                    ranked.append(i)
        if ranked:
            print("Groq-Modelle:", ", ".join(ranked[:4]))
            _groq_live.update(key=k, models=ranked[:4], t=time.time())
            return ranked[:4]
    except AIError as e:
        if e.code == 401:
            raise
        print(f"Groq-Modellliste nicht geladen: {e}")
    return GROQ_MODELS


def _groq_generate(contents: list, system: str, json_mode: bool = True, max_tokens: int = 1024,
                   timeout: float = 30) -> str:
    """Kostenloser Ersatz über Groq (Llama-Modelle). Gleiche Eingabe wie bei Gemini."""
    msgs = [{"role": "system", "content": system + ("\nAntworte ausschließlich mit gültigem JSON." if json_mode else "")}]
    for c in contents:
        msgs.append({"role": "assistant" if c.get("role") == "model" else "user",
                     "content": "".join(p.get("text", "") for p in c.get("parts", []))})
    last = None
    for model in _groq_models():
        body = {"model": model, "messages": msgs, "max_tokens": min(max_tokens, 8000), "temperature": 0.7}
        t0 = time.time()
        try:
            data = _http_simple("https://api.groq.com/openai/v1/chat/completions", body,
                                {"Authorization": f"Bearer {groq_key()}", "User-Agent": "Jarvis"}, timeout=timeout)
        except AIError as e:
            last = e
            if e.code in (404, 429, 500, 502, 503, 400):
                continue
            raise
        print(f"Zeit: Groq ({model}) {time.time() - t0:.1f} s")
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
        text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()  # Denk-Text mancher Modelle weg
        if json_mode:  # nur den JSON-Teil behalten (Llama schreibt manchmal Text drumherum)
            text = re.sub(r"```(?:json)?", "", text).strip()
            m = re.search(r"[\[{].*[\]}]", text, re.S)
            if m:
                text = m.group(0)
        if text:
            return text
    raise last or AIError(0, "Groq hat nichts geantwortet")


def gemini_generate(contents: list, system: str, key: str = None, json_mode: bool = True,
                    max_tokens: int = 1024, timeout: float = 30, prefer: str = None, fast: bool = False) -> str:
    """Fragt Gemini. Ist Gemini aufgebraucht, überlastet oder nicht erreichbar, springt Groq ein (falls eingetragen).
    fast=True (Gespräche): zuerst Groq – antwortet meist in unter einer Sekunde –, Gemini nur als Ersatz."""
    global _gemini_pause_until
    if fast and groq_key():
        try:
            return _groq_generate(contents, system, json_mode, max_tokens, min(timeout, 12))
        except AIError as e:
            if e.code == 401 or not (key or gemini_key()):
                raise
            print(f"Groq nicht verfügbar ({e.code}), nehme Gemini.")
            timeout = min(timeout, 15)
    has_gemini = bool(key or gemini_key())
    if has_gemini and time.time() >= _gemini_pause_until:
        try:
            return _gemini_generate(contents, system, key, json_mode, max_tokens, timeout, prefer)
        except AIError as e:
            if not groq_key() or e.code in (400, 401, 403):
                raise
            if e.code in (0, 429, 500, 502, 503, 504):  # aufgebraucht, überlastet oder Zeitüberschreitung
                _gemini_pause_until = time.time() + 15 * 60  # eine Viertelstunde Gemini schonen
            print(f"Gemini nicht verfügbar ({e.code}), nehme Groq.")
    if groq_key():
        return _groq_generate(contents, system, json_mode, max_tokens, timeout)
    if has_gemini:
        raise AIError(429, "Kontingent aufgebraucht")
    raise AIError(401, "Kein Schlüssel eingetragen")


def test_groq(key: str) -> tuple:
    global GROQ_KEY
    old, GROQ_KEY = GROQ_KEY, key.strip()
    try:
        reply = _groq_generate([{"role": "user", "parts": [{"text": "Antworte nur mit dem Wort: bereit"}]}],
                               "Du bist ein Test.", json_mode=False, max_tokens=300)
        return True, f"Groq antwortet ({(_groq_live['models'] or GROQ_MODELS)[0]}): {reply[:30]}"
    except AIError as e:
        msg = "Der Groq-Schlüssel ist ungültig." if e.code == 401 else f"Groq-Fehler {e.code}: {e.message[:100]}"
        return False, msg
    finally:
        GROQ_KEY = old


_THINK_OK: dict = {}  # Modell -> Nummer der Nachdenk-Einstellung, die es versteht


def _think_options(model: str) -> list:
    """Einstellungen für möglichst wenig "Nachdenken" (= schnelle Antwort), in der Reihenfolge, wie sie probiert werden.
    Gemini 2.5 versteht thinkingBudget 0, neuere Modelle (Gemini 3 ...) thinkingLevel."""
    m = model.lower()
    if m.endswith("-latest"):  # Kurzname: "Nachdenken aus" klappt dort (getestet), "minimal" nicht bei jedem
        return [{"thinkingBudget": 0}, {"thinkingLevel": "low"}, {"thinkingLevel": "minimal"}, None]
    newer = "gemini-3" in m or re.search(r"gemini-[4-9]", m)
    if newer:
        return [{"thinkingLevel": "minimal"}, {"thinkingLevel": "low"}, {"thinkingBudget": 0}, None]
    return [{"thinkingBudget": 0}, {"thinkingLevel": "minimal"}, {"thinkingLevel": "low"}, None]


def test(key: str = None) -> tuple:
    """Prüft den Schlüssel. Gibt (ok, Meldung, Modellliste) zurück."""
    key = (key or gemini_key()).strip()
    if not key:
        return False, "Es ist noch kein Schlüssel eingetragen.", []
    try:
        names = list_models(key)
    except AIError as e:
        return False, explain(e), []
    try:
        reset_cache()
        reply = _gemini_generate([{"role": "user", "parts": [{"text": "Antworte nur mit dem Wort: bereit"}]}],
                                 "Du bist ein Test.", key, json_mode=False, max_tokens=64)
        model = pick_model(key)
        return True, f"Verbindung steht. Modell: {model}. Antwort: {reply[:40]}", names
    except AIError as e:
        return False, explain(e), names
