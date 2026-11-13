"""
Deine Interessen – gemeinsam mit der Handy-App.

- Der PC merkt sich, was du ihn fragst (themen_pc.json) und was du am PC hörst/schaust (pc_media).
- Beides geht über die Kopplung ans Handy. Dort leitet Jarvis daraus (zusammen mit dem, was du am Handy fragst,
  antippst, hörst und schaust) deine Themen ab und schickt die Liste zurück (handy_themen.json).
- "Für dich": Nachrichten zu diesen Themen, auch am PC (fuer_dich()).
"""

import json
import os
import threading
import time
import urllib.parse
import urllib.request

from pc_apps import base_dir

FILE = "themen_pc.json"
PHONE_FILE = "handy_themen.json"
_lock = threading.Lock()
_cache = {"t": 0.0, "data": None}


def _read(name, default):
    try:
        with open(os.path.join(base_dir(), name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write(name, obj):
    try:
        with open(os.path.join(base_dir(), name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception:
        pass


def note(text: str):
    """Eine Frage/einen Befehl am PC merken (nur die letzten 80, 60 Tage)."""
    t = (text or "").strip()
    if len(t) < 4:
        return
    with _lock:
        items = [i for i in _read(FILE, []) if i.get("ts", 0) > time.time() - 60 * 86400][-79:]
        items.append({"ts": int(time.time()), "t": t[:200]})
        _write(FILE, items)


def recent(n: int = 40) -> list:
    return [i["t"] for i in _read(FILE, [])[-n:]]


def set_from_phone(themen: list):
    """Gelernte Themen vom Handy übernehmen."""
    clean = [t for t in themen if isinstance(t, dict) and str(t.get("name", "")).strip()][:12]
    _write(PHONE_FILE, {"ts": int(time.time()), "themen": clean})


def learned() -> list:
    return (_read(PHONE_FILE, {}) or {}).get("themen", [])


def all_topics(settings: dict = None) -> list:
    """Eigene (aus den Einstellungen) + gelernte, ohne Doppelte: [{name, suche}]"""
    if settings is None:
        try:
            import pc_settings
            settings = pc_settings.load()
        except Exception:
            settings = {}
    out, seen = [], set()
    for m in settings.get("themen_selbst") or []:
        if str(m).strip() and m.lower() not in seen:
            seen.add(m.lower())
            out.append({"name": m, "suche": m})
    for t in learned():
        n = str(t.get("name", "")).strip()
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append({"name": n, "suche": t.get("suche") or n})
    return out


def summary() -> str:
    return ", ".join(t["name"] for t in all_topics()[:10])


# --- "Für dich" am PC ---------------------------------------------------------------------------------
PROMPT = """Du bist der persönliche Nachrichten-Butler von J.A.R.V.I.S. Der Nutzer interessiert sich für: {names}.
Unten stehen nummerierte Meldungen zu diesen Themen (#Nummer [Thema: ...] Titel: Text). Erstelle:
1. "briefing": 1 bis 2 gesprochene Sätze auf Deutsch, persönlich ("Passend zu deinen Interessen: ..."), was es Neues gibt.
2. "brennpunkte": die 6 bis 12 interessantesten neuen Meldungen (keine Werbung, keine Dopplungen), höchstens 3 pro Thema,
   die 3 bis 5 besten mit "im_briefing": true zuerst. Für jede: "nr", "titel" (höchstens 6 Wörter), "thema", "warum" (ganz kurz,
   z. B. "weil du ETS2 spielst"), "ort" (wo es passiert oder wo die Firma sitzt), "lat", "lon", "art" (gesellschaft, sport,
   wissenschaft, wirtschaft, politik, lokal), "wichtig" (1 bis 3), "im_briefing", "text" (2 bis 3 gesprochene Sätze),
   "genau" ("punkt", "stadt", "land"), "suche" (Ort für die Karte)
Antworte NUR mit JSON: {{"briefing": "...", "brennpunkte": [ ... ]}}"""


def fuer_dich(max_age: float = 30 * 60):
    """Nachrichten zu deinen Themen (30 Minuten zwischengespeichert). None, wenn keine Themen bekannt sind."""
    if _cache["data"] and time.time() - _cache["t"] < max_age:
        return _cache["data"]
    topics = all_topics()[:7]
    if not topics:
        return None
    import pc_ai
    import pc_news
    items, seen = [], set()

    def load(t):
        q = urllib.parse.quote(t["suche"] + " when:4d")
        try:
            req = urllib.request.Request(f"https://news.google.com/rss/search?q={q}&hl=de&gl=DE&ceid=DE:de",
                                         headers={"User-Agent": "Mozilla/5.0 Jarvis"})
            with urllib.request.urlopen(req, timeout=8) as r:
                for it in pc_news.parse_feed(r.read(), "Thema: " + t["name"], limit=6):
                    k = it["titel"].lower()[:60]
                    if k not in seen:
                        seen.add(k)
                        items.append(it)
        except Exception:
            pass
    th = [threading.Thread(target=load, args=(t,), daemon=True) for t in topics]
    for t in th:
        t.start()
    for t in th:
        t.join(12)
    if not items or not pc_ai.available():
        return None
    use = items[:40]
    lines = "\n".join(f"#{i} [{it['quelle']}] {it['titel']}: {it['text'][:130]}" for i, it in enumerate(use))
    raw = pc_ai.gemini_generate([{"role": "user", "parts": [{"text": lines}]}],
                                PROMPT.format(names=", ".join(t["name"] for t in topics)),
                                json_mode=True, max_tokens=3500, timeout=45, prefer="gemini-flash-lite-latest")
    data = pc_news._parse(raw, use)
    for p in data.get("brennpunkte") or []:
        p["fuer_dich"] = True
    try:
        import re
        obj = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        extra = {i: p for i, p in enumerate(obj.get("brennpunkte") or [])}
        for i, p in enumerate(data.get("brennpunkte") or []):   # Thema und "warum" mitnehmen
            p["thema"] = str((extra.get(i) or {}).get("thema", ""))
            p["warum"] = str((extra.get(i) or {}).get("warum", ""))
    except Exception:
        pass
    data.update(ort="Für dich", themen=[t["name"] for t in topics], zeit=time.time())
    _cache.update(t=time.time(), data=data)
    return data
