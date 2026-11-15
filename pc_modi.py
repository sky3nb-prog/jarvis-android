"""
Modi – ein Knopf im HUD (und am Handy) öffnet ein Raster: Fokus, Gaming, Chill, Kino, Schule, Gute Nacht, Normal.
Jeder Modus stellt PC und Handy passend ein:
  Fokus   – Nachrichten werden gesammelt statt angesagt, keine Kommentare, Handy auf Nicht stören,
            auf Wunsch Lofi; Pomodoro: 25 Min. lernen, 5 Min. Pause (sagt Bescheid), am Ende kurzer Rückblick
  Gaming  – Discord-Sprachkanal (wie bisher), Handy Nicht stören (Anrufe werden mit „zockt gerade“ beantwortet)
  Chill   – Musik an (Deezer), Jarvis locker, alles normal erreichbar
  Kino    – alles leise: Ansagen gesammelt, Handy lautlos, keine Kommentare
  Schule  – Handy leise (wie bisher)
  Gute Nacht – wie bisher (PC fährt herunter)
  Normal  – alles zurück
Der aktuelle Modus steht in STATE und geht live ans HUD (ON_CHANGE).
"""
import threading
import time

ON_CHANGE = None     # vom HUD gesetzt: neuer Zustand -> anzeigen
SAY = None           # vom Programm gesetzt: etwas ansagen (auch wenn gerade gesammelt wird)

MODI = [
    {"id": "fokus", "n": "Fokus", "i": "◎", "h": 200, "d": "Lernen ohne Ablenkung – 25/5 Minuten"},
    {"id": "gaming", "n": "Gaming", "i": "▶", "h": 280, "d": "Discord an, Anrufe weg"},
    {"id": "chill", "n": "Chill", "i": "♪", "h": 160, "d": "Musik an, entspannt"},
    {"id": "kino", "n": "Kino", "i": "◐", "h": 320, "d": "Alles leise, nichts stört"},
    {"id": "schule", "n": "Schule", "i": "▦", "h": 45, "d": "Handy leise"},
    {"id": "nacht", "n": "Gute Nacht", "i": "☾", "h": 230, "d": "Handy still, PC aus"},
    {"id": "aus", "n": "Normal", "i": "○", "h": 30, "d": "Alles wieder normal"},
]
STATE = {"mode": "", "since": 0.0, "phase": "", "phase_end": 0.0, "runden": 0, "lofi": True}
_timer = {"t": None}
LERN, PAUSE = 25 * 60, 5 * 60


def current() -> str:
    return STATE["mode"]


def hold() -> bool:
    """Nachrichten sammeln statt ansagen? (Fokus in der Lernphase, Kino)"""
    m = STATE["mode"]
    return m == "kino" or (m == "fokus" and STATE["phase"] != "pause")


def quiet() -> bool:
    """Keine Kommentare/Vorschläge von selbst."""
    return STATE["mode"] in ("fokus", "kino", "nacht")


def snapshot() -> dict:
    return {"mode": STATE["mode"], "since": STATE["since"], "phase": STATE["phase"], "phase_end": STATE["phase_end"],
            "runden": STATE["runden"], "modi": MODI}


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


def _phone(name: str) -> str:
    try:
        import pc_handy
        if not pc_handy.paired():
            return ""
        return str((pc_handy.control("modus", name=name) or {}).get("text") or "")
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
    if STATE["mode"] != "fokus":
        return
    if STATE["phase"] == "lernen":
        STATE["runden"] += 1
        n = STATE["runden"]
        _say(f"{n * 25} Minuten geschafft. Fünf Minuten Pause – steh kurz auf, trink was." if n < 4
             else f"Stark, schon {n} Runden. Jetzt fünf Minuten Pause – oder hör für heute auf, wenn der Kopf voll ist.")
        _phase("pause", PAUSE)
        _release_held()
    else:
        _say("Pause vorbei. Weiter geht's – 25 Minuten.")
        _phase("lernen", LERN)


def _release_held():
    """Gesammelte Nachrichten jetzt sagen (Pause oder Modus vorbei)."""
    try:
        import pc_nachrichten
        pc_nachrichten.release_held()
    except Exception as e:
        print("Gesammelte Nachrichten:", e)


def set_mode(mode: str, from_phone: bool = False, lofi=None) -> str:
    """Modus umschalten. Gibt den Text für Jarvis zurück."""
    mode = (mode or "aus").lower()
    old = STATE["mode"]
    _cancel_timer()
    STATE.update(mode="" if mode == "aus" else mode, since=time.time(), phase="", phase_end=0.0)
    ph = (lambda n: "") if from_phone else _phone
    txt = ""
    if mode == "fokus":
        STATE["runden"] = 0
        if lofi is not None:
            STATE["lofi"] = bool(lofi)
        p = ph("fokus")
        if STATE["lofi"]:
            try:
                import pc_steuerung
                threading.Thread(target=pc_steuerung.youtube, args=("lofi hip hop radio beats to study",), daemon=True).start()
            except Exception:
                pass
        _phase("lernen", LERN)
        txt = ("Fokus-Modus an. 25 Minuten lernen, dann 5 Minuten Pause – Nachrichten sammle ich solange."
               + (" Lofi läuft." if STATE["lofi"] else "") + (" Handy ist auf Nicht stören." if p else ""))
    elif mode == "gaming":
        try:
            import pc_steuerung
            r = pc_steuerung.discord_join_voice("Gurken")
        except Exception:
            r = ""
        p = ph("gaming")
        txt = "Gaming-Modus an. " + (r if r and not str(r).startswith("Fehler") else "") + (" Handy: " + p if p else "")
    elif mode == "chill":
        try:
            import pc_steuerung
            pc_steuerung.open_app("deezer")
        except Exception:
            pass
        ph("chill")
        txt = "Chill-Modus. Musik ist an – lehn dich zurück."
    elif mode == "kino":
        ph("kino")
        txt = "Kino-Modus: Ich bin still und sammle alles für später. Viel Spaß."
    elif mode == "schule":
        txt = "Schulmodus." if from_phone else (ph("schule") or "Schulmodus ist am Handy – die Jarvis-App antwortet gerade nicht.")
    elif mode == "nacht":
        p = ph("nacht")
        import pc_alltag
        import pc_steuerung
        pc_steuerung._NIGHT = threading.Timer(14.0, pc_alltag.shutdown_sequence)
        pc_steuerung._NIGHT.start()
        txt = (p or "Gute Nacht.") + " Ich speichere alles und fahre den PC gleich herunter – sag „abbrechen“, wenn nicht."
    else:
        p = ph("aus")
        if old == "fokus" and STATE["runden"]:
            txt = f"Fokus beendet: {STATE['runden']} Runden geschafft. Gut gemacht. "
        txt += "Alles wieder normal." if not p else p
    if old in ("fokus", "kino") and not hold():
        _release_held()
    _push()
    return txt.strip()


def from_text(low: str):
    """Sprachbefehl erkennen: "fokus modus", "ich muss lernen", "chill modus", "kino modus" … -> Text oder None."""
    import re
    if re.search(r"\b(fokus|focus|konzentrations?|lern) ?-?modus\b|ich (muss|will) (jetzt )?lernen\b|pomodoro", low):
        return set_mode("fokus", from_phone="vom handy" in low, lofi=False if re.search(r"ohne (musik|lofi)", low) else None)
    if re.search(r"\b(chill|entspann\w*) ?-?modus\b|ich (will|möchte) chillen", low):
        return set_mode("chill", from_phone="vom handy" in low)
    if re.search(r"\b(kino|film|serien?) ?-?modus\b", low):
        return set_mode("kino", from_phone="vom handy" in low)
    if STATE["mode"] == "fokus" and re.search(r"wie lange noch|wie viel zeit", low) and STATE["phase_end"]:
        r = max(0, int((STATE["phase_end"] - time.time()) / 60))
        return f"Noch {r} Minuten {'Pause' if STATE['phase'] == 'pause' else 'Fokus'}."
    return None
