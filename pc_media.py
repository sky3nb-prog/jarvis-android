"""
Was läuft gerade am PC? (Deezer, Spotify, YouTube im Browser ...) – über die Windows-Medienanzeige
(dieselbe, die Windows bei den Lautstärketasten zeigt). Nur lesend und lokal.

- now(): {"title", "artist", "app", "playing"} oder None
- Ein Hintergrund-Thread schreibt mit, was du hörst und schaust (interessen_pc.json, 21 Tage).
  Daraus lernt Jarvis deine Interessen; die Handy-App bekommt die Liste über die Kopplung mit.

Braucht eines der Pakete "winsdk" oder "winrt-Windows.Media.Control" (build.bat installiert sie). Fehlt beides,
geht einfach nichts davon – der Rest von Jarvis läuft normal.
"""

import asyncio
import json
import os
import threading
import time

from pc_apps import base_dir

FILE = "interessen_pc.json"
DAYS = 21
_lock = threading.Lock()
_last = {"key": "", "t": 0.0}
LAST = None  # zuletzt gesehen (für den Status ans Handy)


def _manager_class():
    try:
        from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M  # noqa: N814
        return M
    except Exception:
        pass
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M  # noqa: N814
        return M
    except Exception:
        return None


async def _read():
    M = _manager_class()
    if M is None:
        return None
    mgr = await M.request_async()
    s = mgr.get_current_session()
    if s is None:
        return None
    props = await s.try_get_media_properties_async()
    info = s.get_playback_info()
    status = int(getattr(info, "playback_status", 0) or 0)   # 4 = spielt, 5 = pausiert
    return {"title": str(props.title or ""), "artist": str(props.artist or ""),
            "app": str(s.source_app_user_model_id or ""), "playing": status == 4}


def now():
    """Was gerade läuft (oder None)."""
    global LAST
    try:
        r = asyncio.run(_read())
    except Exception:
        r = None
    LAST = r
    return r


def app_name(app_id: str) -> str:
    a = (app_id or "").lower()
    for key, name in (("deezer", "Deezer"), ("spotify", "Spotify"), ("chrome", "Chrome"), ("msedge", "Edge"),
                      ("firefox", "Firefox"), ("opera", "Opera"), ("vlc", "VLC"), ("zune", "Medienwiedergabe")):
        if key in a:
            return name
    return app_id.split("!")[0].split("\\")[-1].replace(".exe", "") if app_id else ""


def _kind(r) -> str:
    a = (r.get("app") or "").lower()
    browser = any(b in a for b in ("chrome", "msedge", "firefox", "opera", "brave"))
    if browser:
        return "video"   # im Browser fast immer YouTube (Künstler = Kanal)
    return "music"


def _load() -> list:
    try:
        with open(os.path.join(base_dir(), FILE), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(items: list):
    try:
        with open(os.path.join(base_dir(), FILE), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
    except Exception:
        pass


def record(r):
    """Merkt sich einen laufenden Titel (dasselbe innerhalb von 20 Minuten nur einmal)."""
    if not r or not r.get("playing") or not (r.get("title") or "").strip():
        return
    key = f"{r.get('app')}|{r.get('title')}|{r.get('artist')}"
    if key == _last["key"] and time.time() - _last["t"] < 20 * 60:
        return
    _last.update(key=key, t=time.time())
    with _lock:
        items = _load()
        cut = time.time() - DAYS * 86400
        items = [i for i in items if i.get("ts", 0) >= cut][-1500:]
        items.append({"ts": int(time.time()), "k": _kind(r), "t": r["title"][:140], "a": (r.get("artist") or "")[:80],
                      "app": app_name(r.get("app", ""))})
        _save(items)


def top(kind: str, n: int = 8) -> list:
    """Häufigste Künstler bzw. Kanäle der letzten Wochen (neuere zählen mehr)."""
    import math
    score = {}
    for i in _load():
        if i.get("k") != kind:
            continue
        name = (i.get("a") or "").replace(" - Topic", "").strip()
        if not name:
            continue
        age = (time.time() - i.get("ts", 0)) / 86400
        score[name] = score.get(name, 0.0) + math.exp(-age / 7)
    return [k for k, _ in sorted(score.items(), key=lambda kv: -kv[1])[:n]]


def hours_week() -> float:
    """Ungefähre Musik-Hörzeit der letzten 7 Tage (jeder Eintrag ~ ein Lied, im Schnitt gut 3 Minuten)."""
    week = [i for i in _load() if i.get("k") == "music" and time.time() - i.get("ts", 0) < 7 * 86400]
    seen, n = set(), 0
    for i in week:   # dasselbe Lied innerhalb von 3 Minuten nur einmal zählen
        k = (i.get("t"), int(i.get("ts", 0) // 180))
        if k not in seen:
            seen.add(k)
            n += 1
    return round(n * 3.3 / 60, 1)


def summary() -> dict:
    """Für die Handy-App: was du am PC hörst und schaust."""
    return {"music": top("music", 8), "video": top("video", 8)}


def _loop(stop: threading.Event):
    time.sleep(15)
    while not stop.is_set():
        try:
            record(now())
        except Exception:
            pass
        stop.wait(30)


def start(stop: threading.Event):
    if _manager_class() is None:
        print("Hinweis: Medien-Erkennung nicht verfügbar (Paket winsdk bzw. winrt fehlt).")
        return
    threading.Thread(target=_loop, args=(stop,), daemon=True).start()
