"""
Dazulernen am PC: Angebote/Vorschläge, auf die du 5× hintereinander nicht eingehst, lässt Jarvis erst mal weg
(14 Tage, beim nächsten Mal 30). "Schlag wieder alles vor" setzt es zurück.
"""
import json
import os
import sys
import threading
import time

LIMIT = 5
_lock = threading.Lock()


def _file() -> str:
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "lernen.json")


def _load() -> dict:
    try:
        with open(_file(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d: dict):
    try:
        with open(_file(), "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass


def allowed(kind: str) -> bool:
    return _load().get(kind, {}).get("pause_bis", 0) < time.time()


def shown(kind: str) -> str:
    """Vorschlag wurde gemacht. Gibt einen Hinweis-Satz zurück, wenn er ab jetzt pausiert (sonst "")."""
    with _lock:
        d = _load(); e = d.setdefault(kind, {"log": []})
        e["log"] = (e.get("log", []) + [[time.time(), 0]])[-12:]
        recent = [x for x in e["log"] if x[0] >= e.get("since", 0)][-LIMIT:]
        msg = ""
        if len(recent) >= LIMIT and not any(x[1] for x in recent):
            n = e.get("pausen", 0) + 1
            until = time.time() + (30 if n >= 2 else 14) * 86400
            e.update(pause_bis=until, pausen=n, since=until)
            msg = "Das biete ich dir erstmal nicht mehr an – du nimmst es eh nie. „Schlag wieder alles vor“ holt es zurück."
        _save(d)
        return msg


def used(kind: str):
    with _lock:
        d = _load(); e = d.get(kind)
        if not e:
            return
        for x in reversed(e.get("log", [])):
            if not x[1]:
                x[1] = 1
                break
        e["pausen"] = 0
        _save(d)


def reset() -> str:
    with _lock:
        d = _load()
        for e in d.values():
            e.update(pause_bis=0, pausen=0, since=time.time())
        _save(d)
    return "Okay, ich schlage wieder alles vor."


def paused_text() -> str:
    now = time.time()
    p = [k for k, e in _load().items() if e.get("pause_bis", 0) > now]
    return ("Pausiert: " + ", ".join(p) + ".") if p else "Nichts pausiert."
