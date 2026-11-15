"""
Stundenplan am PC eintragen – er landet sofort auf dem Handy (dort nutzt Jarvis ihn: still in der Stunde, melden in der Pause).
Das Handy ist die Hauptquelle. Der PC holt sich beim Öffnen den aktuellen Stand und merkt sich eine Kopie
(stundenplan.json), damit man auch eintragen kann, wenn das Handy gerade nicht erreichbar ist –
dann schickt er den Plan nach, sobald es wieder antwortet.
"""
import json
import os
import threading
import time

_lock = threading.Lock()
_retry = {"on": False}


def _file() -> str:
    import pc_settings
    return os.path.join(os.path.dirname(pc_settings.path()), "stundenplan.json")


def _default() -> dict:
    l = lambda v, b: {"von": v, "bis": b, "fach": ""}  # noqa: E731
    voll = [l("08:00", "08:45"), l("08:45", "09:30"), l("09:50", "10:35"), l("10:40", "11:25"), l("11:40", "12:25"),
            l("12:25", "13:10"), l("14:10", "14:55"), l("14:55", "15:40")]
    fr = voll[:5]
    cp = lambda x: [dict(i) for i in x]  # noqa: E731
    return {"v": 2, "mo": cp(voll), "di": cp(voll), "mi": cp(voll), "do": cp(voll), "fr": cp(fr)}


def _load() -> dict:
    try:
        with open(_file(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _store(d: dict):
    try:
        with open(_file(), "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
    except Exception as e:
        print("Stundenplan speichern ging nicht:", e)


def _clean(plan: dict) -> dict:
    out = {"v": 2}
    for k in ("mo", "di", "mi", "do", "fr"):
        out[k] = [{"von": str(x.get("von", ""))[:5], "bis": str(x.get("bis", ""))[:5], "fach": str(x.get("fach", "")).strip()[:40]}
                  for x in (plan.get(k) or []) if isinstance(x, dict)][:12]
    return out


def get() -> dict:
    import pc_handy
    local = _load()
    if pc_handy.paired():
        r = pc_handy.ask("ctl", wait=12, what="plan_get")
        if r and r.get("text", "").startswith("{"):
            try:
                plan = _clean(json.loads(r["text"]))
                if local.get("pending"):   # am PC geändert, aber noch nicht drüben -> PC-Stand gewinnt
                    return {"ok": True, "plan": local["plan"], "text": "Deine letzte Änderung ist noch nicht auf dem Handy – ich schicke sie nach."}
                _store({"plan": plan, "t": time.time()})
                return {"ok": True, "plan": plan, "text": "Stand vom Handy."}
            except Exception:
                pass
    if local.get("plan"):
        return {"ok": True, "plan": local["plan"], "text": "Das Handy antwortet gerade nicht – das ist der zuletzt bekannte Stand."}
    return {"ok": True, "plan": _default(), "text": "Das Handy antwortet gerade nicht – ich zeige die Standardzeiten."}


def _push(plan: dict) -> bool:
    import pc_handy
    if not pc_handy.paired():
        return False
    r = pc_handy.ask("ctl", wait=15, what="plan_set", plan=plan)
    return bool(r and r.get("ok"))


def _retry_loop():
    for _ in range(90):   # bis zu 3 Stunden alle 2 Minuten
        time.sleep(120)
        d = _load()
        if not d.get("pending"):
            break
        if _push(d["plan"]):
            d["pending"] = False
            _store(d)
            print("Stundenplan nachträglich aufs Handy geschickt.")
            break
    _retry["on"] = False


def set_plan(plan: dict) -> dict:
    plan = _clean(plan or {})
    with _lock:
        ok = _push(plan)
        _store({"plan": plan, "t": time.time(), "pending": not ok})
    if ok:
        return {"ok": True, "text": "✓ Ist auf dem Handy."}
    if not _retry["on"]:
        _retry["on"] = True
        threading.Thread(target=_retry_loop, daemon=True, name="stundenplan").start()
    return {"ok": True, "text": "Am PC gespeichert – das Handy antwortet gerade nicht, ich schicke es nach."}


def handle(body: dict) -> dict:
    if body.get("op") == "set":
        return set_plan(body.get("plan") or {})
    return get()

