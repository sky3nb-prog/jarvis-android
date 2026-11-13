"""
TimeTree-Termine in Jarvis (inoffiziell!). TimeTree hat keine offizielle Schnittstelle. Jarvis nutzt dafür das
Community-Tool "timetree-exporter" (nicht von TimeTree), das sich mit deiner TimeTree-E-Mail und deinem Passwort anmeldet,
den Kalender als Datei timetree.ics neben dem Programm ablegt und von dort liest Jarvis die Termine.

- Das Tool nutzt nachgebaute Schnittstellen. Es kann jederzeit aufhören zu funktionieren, und zu viele Abrufe können
  zu einer zeitweisen Sperre führen. Deshalb holt Jarvis nur alle paar Stunden.
- Dein Passwort wird mit Windows verschlüsselt (nur dein Benutzer kann es lesen) und nur an TimeTree gesendet.
- Einrichten: Zahnrad, Tab "Infos", Abschnitt TimeTree. Dort auf "TimeTree einrichten" klicken (installiert das Tool),
  E-Mail und Passwort eintragen, dann "Jetzt synchronisieren".
- Sprachbefehl: "Synchronisiere TimeTree".
"""

import glob
import os
import re
import shutil
import subprocess
import threading
import time

from pc_apps import base_dir

NO_WINDOW = 0x08000000
ENABLED = False
EMAIL = ""
PASSWORD = ""  # nur im Arbeitsspeicher
CODE = ""  # optional: Kalender-Code (steht in der Adresse deiner TimeTree-Kalenderseite im Browser)
INTERVAL_H = 3
last_sync = 0.0
FIRST = threading.Event()  # gesetzt, sobald der erste Abgleich nach dem Start durch ist
last_message = ""
_started = False
_lock = threading.Lock()


def out_path() -> str:
    return os.path.join(base_dir(), "timetree.ics")


def active_file():
    """Die Datei, die Jarvis als Kalender mitlesen soll (oder None)."""
    return out_path() if ENABLED and os.path.exists(out_path()) else None


def _tool_command():
    exe = shutil.which("timetree-exporter")
    if exe:
        return [exe]
    patterns = [os.path.expandvars(r"%APPDATA%\Python\Python*\Scripts\timetree-exporter.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python*\Scripts\timetree-exporter.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Packages\PythonSoftwareFoundation*\LocalCache\local-packages\Python*\Scripts\timetree-exporter.exe")]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern), reverse=True)
        if hits:
            return [hits[0]]
    return None


def _run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore",
                          creationflags=NO_WINDOW, **kwargs)


def install() -> str:
    """Installiert das Tool für den Benutzer (braucht Python 3.11 oder neuer auf dem PC)."""
    for launcher in (["py", "-m"], ["python", "-m"]):
        try:
            r = _run(launcher + ["pip", "install", "--user", "-U", "timetree-exporter"], timeout=300)
        except Exception:
            continue
        if r.returncode == 0:
            return "✔ Das Tool ist installiert." if _tool_command() else \
                "✔ Installiert, aber ich finde das Programm noch nicht. Starte Jarvis einmal neu."
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["unbekannter Fehler"]
        return f"✘ Installation fehlgeschlagen: {tail[0][:160]}"
    return "✘ Python wurde nicht gefunden (py oder python)."


def sync(email: str = None, password: str = None, code: str = None):
    """Holt den TimeTree-Kalender. Gibt (ok, Meldung) zurück."""
    global last_sync, last_message
    email, password, code = (email or EMAIL).strip(), password if password is not None else PASSWORD, (code if code is not None else CODE).strip()
    if not email or not password:
        return False, "Es fehlen E-Mail oder Passwort für TimeTree."
    tool = _tool_command()
    if not tool:
        return False, "Das Tool ist noch nicht installiert. Klicke auf „TimeTree einrichten“."
    with _lock:
        tmp = out_path() + ".neu"
        cmd = tool + ["-o", tmp, "-e", email] + (["-c", code] if code else [])
        env = dict(os.environ, TIMETREE_EMAIL=email, TIMETREE_PASSWORD=password, PYTHONIOENCODING="utf-8")
        try:
            r = _run(cmd, env=env, input="1\n", timeout=240)
        except subprocess.TimeoutExpired:
            return False, "TimeTree hat zu lange gebraucht."
        except Exception as e:
            return False, f"Das Tool lässt sich nicht starten: {e}"
        text = ""
        if os.path.exists(tmp):
            with open(tmp, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        if r.returncode != 0 or "BEGIN:VCALENDAR" not in text:
            if os.path.exists(tmp):
                os.remove(tmp)
            err = re.sub(r"\s+", " ", (r.stderr or r.stdout or "").strip())[-200:]
            return False, f"TimeTree hat nicht geantwortet ({err or 'keine Meldung'}). Stimmen E-Mail und Passwort? Bei mehreren Kalendern hilft der Kalender-Code."
        os.replace(tmp, out_path())
    n = text.count("BEGIN:VEVENT")
    last_sync, last_message = time.time(), f"{n} Termine geholt"
    try:
        import pc_calendar

        pc_calendar.reset_cache()
    except Exception:
        pass
    return True, f"✔ Fertig. {n} Termine aus TimeTree geholt."


def sync_all(email: str = None, password: str = None, code: str = None):
    """TimeTree holen und danach (falls eingerichtet) in den Google-Kalender eintragen."""
    ok, msg = sync(email, password, code)
    if ok:
        try:
            import pc_gcal

            if pc_gcal.ENABLED and pc_gcal.configured():
                ok2, msg2 = pc_gcal.sync_timetree()
                msg = msg + " " + (msg2 if ok2 else "✘ " + msg2)
        except Exception as e:
            msg += f" ✘ Google-Abgleich: {e}"
    return ok, msg


def wait_first_sync(timeout: float = 25.0):
    """Wartet beim Start kurz, bis die neuesten Termine geholt sind (damit Jarvis aktuelle Termine ansagt)."""
    if ENABLED and EMAIL and PASSWORD:
        FIRST.wait(timeout)


def configure(enabled: bool, email: str, password: str, code: str):
    global ENABLED, EMAIL, PASSWORD, CODE, _started
    ENABLED, EMAIL, PASSWORD, CODE = bool(enabled), (email or "").strip(), password or "", (code or "").strip()
    if ENABLED and not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True).start()


def _loop():
    while True:
        try:
            if ENABLED and EMAIL and PASSWORD and time.time() - last_sync > INTERVAL_H * 3600 and _tool_command():
                ok, msg = sync_all()
                print("TimeTree:", msg)
                if not ok:
                    globals()["last_sync"] = time.time() - (INTERVAL_H * 3600 - 1800)  # nach einem Fehler in 30 Min. erneut
        except Exception as e:
            print(f"TimeTree-Abgleich fehlgeschlagen: {e}")
        FIRST.set()
        time.sleep(300)


def handle(text: str):
    low = text.lower()
    if "timetree" not in low.replace(" ", "").replace("-", "") and "time tree" not in low:
        return None
    if re.search(r"synchronisier|aktualisier|hol|abgleich|neu laden|update", low):
        if not ENABLED:
            return "TimeTree ist noch nicht eingerichtet. Das geht im Zahnrad im Tab Infos."
        ok, msg = sync_all()
        return msg.replace("✔ ", "").replace("✘ ", "")
    return None
