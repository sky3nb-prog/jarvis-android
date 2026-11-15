"""
Modi – ein Knopf im HUD (und am Handy) öffnet ein Raster: Fokus, Gaming, Chill, Kino, Schule, Gute Nacht, Normal
und eigene Modi. Was jeder Modus macht, stellst du selbst ein (im Raster auf „Bearbeiten“):
  Handy:        Nicht stören / lautlos / normal / nichts ändern
  Nachrichten:  sammeln statt ansagen (in Pausen bzw. danach gesagt)
  Still:        keine Kommentare/Vorschläge von selbst
  Musik:        Lofi, Deezer, eigene YouTube-Suche oder nichts
  Discord:      Sprachkanal betreten (Name)
  Programme:    öffnen (mit Komma)
  Pomodoro:     Lern-/Pausenminuten (z. B. Fokus 25/5), mit Ansage
  PC aus:       am Ende herunterfahren (Gute Nacht)
Einstellungen: modi_cfg in den Einstellungen (PC), das Handy bekommt eine Kopie.
"""
import copy
import re
import threading
import time

ON_CHANGE = None     # vom HUD gesetzt: neuer Zustand -> anzeigen
SAY = None           # vom Programm gesetzt: etwas ansagen (auch wenn gerade gesammelt wird)
SETTINGS = None      # vom Programm gesetzt: () -> Einstellungen
SAVE = None          # vom Programm gesetzt: (key, value) -> speichern

DEFAULT = [
    {"id": "fokus", "n": "Fokus", "i": "◎", "h": 200, "d": "Lernen ohne Ablenkung", "handy": "dnd", "sammeln": True, "still": True,
     "musik": "lofi", "discord": "", "apps": "", "pomo": True, "lern": 25, "pause": 5, "aus": False},
    {"id": "gaming", "n": "Gaming", "i": "▶", "h": 280, "d": "Discord an, Anrufe weg", "handy": "dnd", "sammeln": False, "still": False,
     "musik": "", "discord": "", "apps": "", "pomo": False, "lern": 25, "pause": 5, "aus": False},
    {"id": "chill", "n": "Chill", "i": "♪", "h": 160, "d": "Musik an, entspannt", "handy": "normal", "sammeln": False, "still": False,
     "musik": "deezer", "discord": "", "apps": "", "pomo": False, "lern": 25, "pause": 5, "aus": False},
    {"id": "kino", "n": "Kino", "i": "◐", "h": 320, "d": "Alles leise, nichts stört", "handy": "lautlos", "sammeln": True, "still": True,
     "musik": "", "discord": "", "apps": "", "pomo": False, "lern": 25, "pause": 5, "aus": False},
    {"id": "schule", "n": "Schule", "i": "▦", "h": 45, "d": "Handy leise", "handy": "lautlos", "sammeln": False, "still": False,
     "musik": "", "discord": "", "apps": "", "pomo": False, "lern": 25, "pause": 5, "aus": False},
    {"id": "nacht", "n": "Gute Nacht", "i": "☾", "h": 230, "d": "Handy still, PC aus", "handy": "dnd", "sammeln": True, "still": True,
     "musik": "", "discord": "", "apps": "", "pomo": False, "lern": 25, "pause": 5, "aus": True},
]
NORMAL = {"id": "aus", "n": "Normal", "i": "○", "h": 30, "d": "Alles wieder normal"}
STATE = {"mode": "", "since": 0.0, "phase": "", "phase_end": 0.0, "runden": 0}
_timer = {"t": None}


def modes(all_: bool = False) -> list:
    """Alle Modi mit deinen Einstellungen (Standard + Änderungen + eigene Modi). all_ = auch ausgeblendete."""
    cfg = (SETTINGS() or {}).get("modi_cfg") if SETTINGS else None
    out = copy.deepcopy(DEFAULT)
    if isinstance(cfg, list) and cfg:
        by = {m.get("id"): m for m in cfg if isinstance(m, dict) and m.get("id")}
        out = [dict(d, **by.pop(d["id"], {})) for d in out]
        out += [dict(DEFAULT[2], **m) for m in by.values()]   # eigene Modi
    return out if all_ else [m for m in out if not m.get("weg")]


def get(mid: str):
    return next((m for m in modes() if m["id"] == mid), None)


def save_cfg(cfg: list) -> dict:
    keys = ("id", "n", "i", "h", "d", "handy", "sammeln", "still", "musik", "discord", "apps", "pomo", "lern", "pause", "aus", "weg")
    clean = []
    for m in cfg or []:
        if not isinstance(m, dict) or not re.match(r"^[a-z0-9_]{1,20}$", str(m.get("id", ""))) or m.get("id") == "aus":
            continue
        c = {k: m[k] for k in keys if k in m}
        c["n"] = str(c.get("n", ""))[:20] or c["id"]
        c["lern"] = max(5, min(120, int(c.get("lern") or 25)))
        c["pause"] = max(1, min(60, int(c.get("pause") or 5)))
        clean.append(c)
    if SAVE:
        SAVE("modi_cfg", clean)
    threading.Thread(target=lambda: _send_phone_cfg(modes(True) if SETTINGS else clean), daemon=True).start()
    _push()
    return {"ok": True}


def _send_phone_cfg(cfg):
    try:
        import pc_handy
        if pc_handy.paired():
            pc_handy.control("modi_cfg", cfg=cfg)
    except Exception:
        pass


def current() -> str:
    return STATE["mode"]


def hold() -> bool:
    """Nachrichten sammeln statt ansagen?"""
    m = get(STATE["mode"]) if STATE["mode"] else None
    return bool(m and m.get("sammeln") and STATE["phase"] != "pause")


def quiet() -> bool:
    m = get(STATE["mode"]) if STATE["mode"] else None
    return bool(m and m.get("still"))


def snapshot() -> dict:
    return {"mode": STATE["mode"], "since": STATE["since"], "phase": STATE["phase"], "phase_end": STATE["phase_end"],
            "runden": STATE["runden"], "modi": modes() + [NORMAL], "alle": modes(True)}


def _push():
    if ON_CHANGE:
        try:
            ON_CHANGE(snapshot())
        except Exception:
            pass


def _say(t: str):
    if SAY:
        try:
            SAY(t)
        except Exception as e:
            print("Modus-Ansage ging nicht:", e)


def _phone(mid: str, m: dict) -> str:
    try:
        import pc_handy
        if not pc_handy.paired():
            return ""
        return str((pc_handy.control("modus", name=mid, handy=(m or {}).get("handy", "normal"), label=(m or {}).get("n", "")) or {}).get("text") or "")
    except Exception:
        return ""


def _cancel_timer():
    t = _timer["t"]
    if t:
        t.cancel()
    _timer["t"] = None


def _phase(name: str, secs: int):
    _cancel_timer()
    STATE["phase"], STATE["phase_end"] = name, time.time() + secs
    t = threading.Timer(secs, _next_phase)
    t.daemon = True
    t.start()
    _timer["t"] = t
    _push()


def _next_phase():
    m = get(STATE["mode"]) if STATE["mode"] else None
    if not m or not m.get("pomo"):
        return
    if STATE["phase"] == "lernen":
        STATE["runden"] += 1
        n = STATE["runden"]
        _say(f"{n * m['lern']} Minuten geschafft. {m['pause']} Minuten Pause – steh kurz auf, trink was." if n < 4
             else f"Stark, schon {n} Runden. Jetzt {m['pause']} Minuten Pause – oder hör für heute auf, wenn der Kopf voll ist.")
        _phase("pause", m["pause"] * 60)
        _release_held()
    else:
        _say(f"Pause vorbei. Weiter geht's – {m['lern']} Minuten.")
        _phase("lernen", m["lern"] * 60)


def _release_held():
    try:
        import pc_nachrichten
        pc_nachrichten.release_held()
    except Exception as e:
        print("Gesammelte Nachrichten:", e)


def _music(m: dict, no_music: bool):
    mu = (m.get("musik") or "").strip()
    if not mu or no_music:
        return ""
    try:
        import pc_steuerung
        if mu == "lofi":
            threading.Thread(target=pc_steuerung.youtube, args=("lofi hip hop radio beats to study",), daemon=True).start()
            return "Lofi läuft."
        if mu in ("deezer", "spotify"):
            pc_steuerung.open_app(mu)
            return "Musik ist an."
        if mu.startswith("youtube:"):
            threading.Thread(target=pc_steuerung.youtube, args=(mu[8:].strip(),), daemon=True).start()
            return ""
    except Exception:
        pass
    return ""


def set_mode(mode: str, from_phone: bool = False, lofi=None) -> str:
    """Modus umschalten. Gibt den Text für Jarvis zurück."""
    mode = (mode or "aus").lower()
    old = STATE["mode"]
    runden = STATE["runden"]
    _cancel_timer()
    m = get(mode)
    if not m:
        mode = "aus"
    STATE.update(mode="" if mode == "aus" else mode, since=time.time(), phase="", phase_end=0.0, runden=0 if mode != old else STATE["runden"])
    if mode == "aus":
        p = "" if from_phone else _phone("aus", NORMAL)
        txt = (f"{(get(old) or {}).get('n', 'Modus')} beendet: {runden} Runden geschafft. Gut gemacht. " if old and runden else "") + "Alles wieder normal."
        if old:
            _release_held()
        _push()
        return txt
    parts = [f"{m['n']}-Modus an."]
    p = "" if from_phone else _phone(mode, m)
    if p and m.get("handy") in ("dnd", "lautlos"):
        parts.append("Handy ist " + ("auf Nicht stören." if m["handy"] == "dnd" else "lautlos."))
    if m.get("discord"):
        try:
            import pc_steuerung
            r = pc_steuerung.discord_join_voice(m["discord"])
            if r and not str(r).startswith("Fehler"):
                parts.append(r)
        except Exception:
            pass
    for a in [x.strip() for x in (m.get("apps") or "").split(",") if x.strip()]:
        try:
            import pc_steuerung
            pc_steuerung.open_app(a)
        except Exception:
            pass
    mtxt = _music(m, lofi is False)
    if mtxt:
        parts.append(mtxt)
    if m.get("pomo"):
        _phase("lernen", m["lern"] * 60)
        parts.append(f"{m['lern']} Minuten {'lernen' if mode == 'fokus' else 'konzentriert'}, dann {m['pause']} Minuten Pause.")
    if m.get("sammeln"):
        parts.append("Nachrichten sammle ich solange.")
    if m.get("aus"):
        import pc_alltag
        import pc_steuerung
        pc_steuerung._NIGHT = threading.Timer(14.0, pc_alltag.shutdown_sequence)
        pc_steuerung._NIGHT.start()
        parts.append("Ich speichere alles und fahre den PC gleich herunter – sag „abbrechen“, wenn nicht.")
    if old and not hold():
        _release_held()
    _push()
    return " ".join(parts)


def from_text(low: str):
    """Sprachbefehl erkennen -> Text oder None. Auch eigene Modi über ihren Namen ("Lern-Modus", "Zeichnen-Modus")."""
    fp = "vom handy" in low
    nolofi = False if re.search(r"ohne (musik|lofi)", low) else None
    if re.search(r"\b(fokus|focus|konzentrations?) ?-?modus\b|ich (muss|will) (jetzt )?lernen\b|pomodoro", low):
        return set_mode("fokus", fp, nolofi)
    if re.search(r"\b(chill|entspann\w*) ?-?modus\b|ich (will|möchte) chillen", low):
        return set_mode("chill", fp)
    if re.search(r"\b(kino|film|serien?) ?-?modus\b", low):
        return set_mode("kino", fp)
    for m in modes():
        if m["id"] in ("fokus", "chill", "kino", "gaming", "schule", "nacht"):
            continue
        n = re.escape(m["n"].lower())
        if re.search(rf"\b{n} ?-?modus\b|\bmodus {n}\b", low):
            return set_mode(m["id"], fp, nolofi)
    if STATE["mode"] and re.search(r"wie lange noch|wie viel zeit", low) and STATE["phase_end"]:
        r = max(0, int((STATE["phase_end"] - time.time()) / 60))
        return f"Noch {r} Minuten {'Pause' if STATE['phase'] == 'pause' else 'konzentriert'}."
    return None
