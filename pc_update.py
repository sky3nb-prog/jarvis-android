"""
Selbst-Update am PC (statt build.bat von Hand).

Alle 30 Minuten schaut Jarvis auf GitHub (Zweig "pc"), ob es eine neue Version gibt. Wenn ja, baut er sie still im
Hintergrund in einen eigenen Ordner (dist_neu) – Jarvis läuft dabei normal weiter. Ist der Bau fertig, fragt er:
"Update ist fertig. Soll ich kurz neu starten?" Bei "ja" tauscht ein kleines Skript die .exe aus, sobald Jarvis
beendet ist, und startet die neue Version (ein paar Sekunden Pause). Klappt etwas nicht, steht es in update_log.txt
und alles bleibt beim Alten – dann geht build.bat wie bisher.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

REPO = "sky3nb-prog/jarvis-android"
BRANCH = "pc"
CHECK_EVERY = 30 * 60
NO_WINDOW = 0x08000000
DETACHED = 0x00000008

_state = {"busy": False, "ready": None, "asked": 0.0}


def _dist() -> str:
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))


def _src() -> str:
    """Ordner mit build.bat und den .py-Dateien (bei der .exe: eins über dist)."""
    return os.path.dirname(_dist()) if getattr(sys, "frozen", False) else _dist()


def _file() -> str:
    return os.path.join(_dist(), "update.json")


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


def _neu_dir() -> str:
    """Wohin das fertige Update kommt (dein PC: dist_neu neben dem Code; Konto-Ausgabe: _neu neben dem Programm)."""
    import pc_variante
    return os.path.join(_dist(), "_neu") if pc_variante.KONTO else os.path.join(_src(), "dist_neu")


def _etag_get(url: str, cache_key: str):
    """GET mit ETag-Cache: Wenn sich auf GitHub nichts geändert hat, kommt 304 zurück – das zählt NICHT gegen
    das Ratenlimit (anders als eine normale 200er-Antwort). Dadurch verbraucht die automatische Prüfung alle
    30 Minuten praktisch nie mehr Kontingent, außer es gibt wirklich was Neues. Bei 403 (Ratenlimit erreicht)
    wird – wenn vorhanden – einfach der letzte bekannte Stand weiterverwendet, statt einen Fehler zu melden."""
    d = _load()
    etag = d.get(cache_key + "_etag")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Jarvis-PC"}
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode("utf-8"))
            new_etag = r.headers.get("ETag")
            if new_etag:
                d[cache_key + "_etag"] = new_etag
                d[cache_key + "_body"] = body
                _save(d)
            return body
    except urllib.error.HTTPError as e:
        if e.code == 304:
            cached = d.get(cache_key + "_body")
            if cached is not None:
                return cached
            raise RuntimeError("GitHub sagt '304' aber ich hab noch keinen alten Stand gespeichert.") from e
        if e.code == 403:
            cached = d.get(cache_key + "_body")
            if cached is not None:
                return cached
            raise RuntimeError("GitHub blockiert gerade kurz (zu oft gefragt) - bitte in einer Stunde nochmal") from e
        raise


def _asset():
    """Konto-Ausgabe: das fertige Paket auf der Download-Seite -> (Kennung, Download-Link)."""
    import pc_variante
    rel = _etag_get(f"https://api.github.com/repos/{pc_variante.DOWNLOAD_REPO}/releases/tags/{pc_variante.DOWNLOAD_TAG}", "rel")
    for a in rel.get("assets") or []:
        if a.get("name") == pc_variante.DOWNLOAD_ASSET:
            return f"{a.get('id')}:{a.get('updated_at')}", a.get("browser_download_url")
    raise RuntimeError("Paket nicht gefunden")


def latest() -> str:
    import pc_variante
    if pc_variante.KONTO:
        return _asset()[0]
    body = _etag_get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}", "commit")
    return body["sha"]


def possible() -> bool:
    import pc_variante
    if pc_variante.KONTO:   # Konto-Ausgabe: fertige Pakete von der Download-Seite, kein Bauen nötig
        return getattr(sys, "frozen", False)
    return getattr(sys, "frozen", False) and os.path.exists(os.path.join(_src(), "build.bat"))


def _download(sha: str, ask):
    """Konto-Ausgabe: fertiges Paket laden und auspacken (statt selbst zu bauen)."""
    import shutil
    import zipfile
    import pc_variante
    try:
        _, url = _asset()
        neu = _neu_dir()
        shutil.rmtree(neu, ignore_errors=True)
        os.makedirs(neu, exist_ok=True)
        z = os.path.join(neu, "paket.zip")
        req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-PC"})
        with urllib.request.urlopen(req, timeout=120) as r, open(z, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                b = os.path.basename(n)
                if b.lower() in (pc_variante.EXE.lower(), pc_variante.EXE_DEBUG.lower()):
                    with zf.open(n) as src, open(os.path.join(neu, b), "wb") as dst:
                        shutil.copyfileobj(src, dst)
        os.remove(z)
        if os.path.exists(os.path.join(neu, pc_variante.EXE)):
            _state["ready"] = sha
            print("Update geladen.")
            ask()
        else:
            raise RuntimeError("im Paket fehlt " + pc_variante.EXE)
    except Exception as e:
        print("Update laden ging nicht:", e)
        d = _load(); d["failed"] = sha; _save(d)
    finally:
        _state["busy"] = False


BUILD = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Update %DATE% %TIME% ===
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $here=(Get-Location).Path; $z=Join-Path $env:TEMP 'jarvis-pc-upd.zip'; $d=Join-Path $env:TEMP 'jarvis-pc-upd'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest 'https://github.com/__REPO__/archive/refs/heads/__BRANCH__.zip' -OutFile $z -UseBasicParsing; if (Test-Path $d) { Remove-Item $d -Recurse -Force }; Expand-Archive $z $d -Force; $src=(Get-ChildItem $d -Directory | Select-Object -First 1).FullName; $n=0; Get-ChildItem $src -Recurse -File | Where-Object { $_.Name -ne '.gitignore' } | ForEach-Object { $rel=$_.FullName.Substring($src.Length+1); $t=Join-Path $here $rel; New-Item -ItemType Directory -Force (Split-Path $t) | Out-Null; Copy-Item $_.FullName $t -Force; (Get-Item $t).LastWriteTime = Get-Date; $n++ }; Write-Host ([string]$n + ' Dateien aktualisiert.')"
if errorlevel 1 exit /b 2
py -m pip install -q pyinstaller pystray pillow pyautogui sounddevice numpy SpeechRecognition tzdata psutil edge-tts soundfile pywebview opencv-python-headless
set EXTRA=--add-data "pc_web;pc_web"
py -c "import webview" >nul 2>&1 && set EXTRA=%EXTRA% --collect-all webview --hidden-import clr
py -c "import clr_loader" >nul 2>&1 && set EXTRA=%EXTRA% --collect-all clr_loader
py -c "import pythonnet" >nul 2>&1 && set EXTRA=%EXTRA% --collect-all pythonnet
py -c "import edge_tts" >nul 2>&1 && set EXTRA=%EXTRA% --collect-all edge_tts
py -c "import winsdk" >nul 2>&1 && set EXTRA=%EXTRA% --collect-all winsdk
py -c "import winrt.windows.media.control" >nul 2>&1 && set EXTRA=%EXTRA% --collect-all winrt
if exist dist_neu rmdir /s /q dist_neu
py -m PyInstaller --noconfirm --onefile --noconsole --icon jarvis.ico --name PC-Assistent --distpath dist_neu --workpath build_neu --collect-all speech_recognition %EXTRA% pc_overlay.py
if errorlevel 1 exit /b 3
py -m PyInstaller --noconfirm --onefile --icon jarvis.ico --name PC-Assistent-Debug --distpath dist_neu --workpath build_neu --collect-all speech_recognition %EXTRA% pc_overlay.py
if not exist "dist_neu\PC-Assistent.exe" exit /b 4
echo FERTIG
exit /b 0
"""

SWAP = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
set /a n=0
:warten
set /a n+=1
if %n% gtr 12 goto weg
tasklist /fi "imagename eq PC-Assistent.exe" 2>nul | find /i "PC-Assistent.exe" >nul && ( timeout /t 1 /nobreak >nul & goto warten )
:weg
rem HUD-Fenster (zweiter Prozess derselben exe) und Reste beenden
taskkill /f /im PC-Assistent.exe >nul 2>&1
taskkill /f /im PC-Assistent-Debug.exe >nul 2>&1
timeout /t 2 /nobreak >nul
move /y "dist_neu\PC-Assistent.exe" "dist\PC-Assistent.exe" >nul
if exist "dist_neu\PC-Assistent-Debug.exe" move /y "dist_neu\PC-Assistent-Debug.exe" "dist\PC-Assistent-Debug.exe" >nul
start "" "dist\PC-Assistent.exe" --nach-update
rmdir /s /q dist_neu >nul 2>&1
del "%~f0"
"""


def _build(sha: str, ask):
    src = _src()
    bat = os.path.join(src, "_update_bau.bat")
    log = os.path.join(_dist(), "update_log.txt")
    try:
        with open(bat, "w", encoding="utf-8") as f:
            f.write(BUILD.replace("__REPO__", REPO).replace("__BRANCH__", BRANCH).replace("\n", "\r\n"))
        print("Update gefunden – baue still im Hintergrund …")
        with open(log, "w", encoding="utf-8", errors="replace") as out:
            p = subprocess.run(["cmd", "/c", bat], cwd=src, stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW, timeout=3600)
        if p.returncode == 0 and os.path.exists(os.path.join(src, "dist_neu", "PC-Assistent.exe")):
            _state["ready"] = sha
            print("Update fertig gebaut.")
            ask()
        else:
            print(f"Update-Bau ging nicht (Code {p.returncode}) – siehe update_log.txt. Alte Version läuft weiter.")
            d = _load(); d["failed"] = sha; _save(d)
    except Exception as e:
        print("Update ging nicht:", e)
    finally:
        _state["busy"] = False


def check_now(ask) -> str:
    """Einmal nachsehen (auch auf Zuruf). ask() wird aufgerufen, sobald ein Update fertig gebaut ist."""
    if not possible():
        return "Selbst-Update geht nur mit der fertigen .exe (bei deinem PC: und build.bat im Ordner darüber)."
    if _state["ready"]:
        ask()
        return "Das Update ist schon fertig."
    if _state["busy"]:
        return "Ich baue das Update gerade."
    try:
        sha = latest()
    except Exception as e:
        return f"Ich komme gerade nicht an GitHub ({e})."
    d = _load()
    if not d.get("sha"):          # erster Start mit dieser Funktion: aktueller Stand = installiert
        d["sha"] = sha; _save(d)
        return "Du hast die neueste Version."
    if sha == d.get("sha") or sha == d.get("failed"):
        return "Du hast die neueste Version."
    _state["busy"] = True
    threading.Thread(target=_download if __import__("pc_variante").KONTO else _build, args=(sha, ask), daemon=True).start()
    return "Es gibt ein Update. Ich baue es im Hintergrund und sag Bescheid, wenn es fertig ist."


def restart(quit_app) -> str:
    """Neue .exe einsetzen: Helfer (Kopie der neuen exe unter anderem Namen) tauscht sie aus, sobald Jarvis beendet ist."""
    sha = _state.get("ready")
    if not sha:
        return "Es liegt kein fertiges Update bereit."
    import pc_variante
    nd = _neu_dir()
    neu = os.path.join(nd, pc_variante.EXE)
    helper = os.path.join(nd, "Jarvis-Update.exe")
    try:
        import shutil
        shutil.copy2(neu, helper)   # anderer Name: der Helfer kann die alte .exe beenden, ohne sich selbst zu treffen
        d = _load(); d["sha"] = sha; d.pop("failed", None); _save(d)
        subprocess.Popen([helper, "--swap", _dist(), nd], cwd=_dist(),
                         creationflags=NO_WINDOW | 0x00000200, close_fds=True)   # NEW_PROCESS_GROUP: überlebt das Beenden
        threading.Timer(1.5, quit_app).start()
        return "Ich starte kurz neu – bin gleich wieder da."
    except Exception as e:
        return f"Neustart ging nicht ({e})."


def swap_main():
    """Läuft als Jarvis-Update.exe --swap <dist> <dist_neu>: warten, alte exe beenden, neue hineinkopieren, starten."""
    import shutil
    a = sys.argv[sys.argv.index("--swap") + 1:]
    dist, neu = a[0], a[1]
    # welche Ausgabe? (der Helfer heißt Jarvis-Update.exe – darum am Inhalt von dist erkennen)
    konto = os.path.exists(os.path.join(dist, "Jarvis-Konto.exe"))
    EXE, EXE_DEBUG = ("Jarvis-Konto.exe", "Jarvis-Konto-Debug.exe") if konto else ("PC-Assistent.exe", "PC-Assistent-Debug.exe")
    log = os.path.join(dist, "update_log.txt")

    def note(t):
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write(time.strftime("%H:%M:%S ") + t + "\n")
        except Exception:
            pass

    def running() -> bool:
        try:
            out = subprocess.run(["tasklist", "/fi", f"imagename eq {EXE}", "/fo", "csv", "/nh"], capture_output=True, text=True,
                                 creationflags=NO_WINDOW, timeout=10).stdout
            return EXE in out
        except Exception:
            return False
    note("Tausch startet")
    for _ in range(15):
        if not running():
            break
        time.sleep(1)
    for img in (EXE, EXE_DEBUG):   # HUD-Fenster, Start-Animation, Reste
        subprocess.run(["taskkill", "/f", "/im", img], capture_output=True, creationflags=NO_WINDOW)
    time.sleep(1.5)
    ok = False
    for _ in range(20):
        try:
            shutil.copy2(os.path.join(neu, EXE), os.path.join(dist, EXE))
            ok = True
            break
        except Exception as e:
            note(f"kopieren wartet: {e}")
            time.sleep(1)
    try:
        if os.path.exists(os.path.join(neu, EXE_DEBUG)):
            shutil.copy2(os.path.join(neu, EXE_DEBUG), os.path.join(dist, EXE_DEBUG))
    except Exception:
        pass
    note("neue Version eingesetzt" if ok else "Kopieren ging nicht – alte Version wird gestartet")
    subprocess.Popen([os.path.join(dist, EXE)] + (["--nach-update"] if ok else []), cwd=dist, close_fds=True,
                     creationflags=0x00000008 | 0x00000200)   # eigenständig weiterlaufen


IDLE_AUTO = 15 * 60   # so lange niemand an Maus/Tastatur: Update ohne Nachfrage einspielen
AWAY = {"on": False, "since": 0.0}   # „Jarvis, ich bin jetzt weg“: PC bleibt an, holt Updates öfter und spielt sie sofort ein
AWAY_EVERY = 5 * 60


def set_away(on: bool) -> str:
    AWAY["on"] = bool(on); AWAY["since"] = time.time() if on else 0.0
    if on:
        return "Alles klar, bis später. Ich bleibe an, spiele Updates gleich ein und passe auf: hängt ein Programm oder läuft der Speicher voll, speichere und schließe ich es – notfalls fahre ich runter. Was passiert, schreib ich dir aufs Handy."
    return "Willkommen zurück."


def _auto_install() -> bool:
    """Update fertig, aber keiner am PC (z. B. du bist weg): selbst neu starten und dem Handy Bescheid geben."""
    if not _state["ready"]:
        return False
    try:
        import pc_nachrichten
        idle = pc_nachrichten._idle_seconds()
        if AWAY["on"] and idle < 60:   # doch jemand da: Weg-Modus ist vorbei
            AWAY["on"] = False
        if idle < (60 if AWAY["on"] else IDLE_AUTO) or not pc_nachrichten.ON_QUIT:
            return False
        try:
            import pc_phone
            pc_phone.push("PC-Update", "Du warst nicht am PC – ich spiele das Update jetzt selbst ein und bin in einer Minute wieder da.", tags="arrows_counterclockwise")
        except Exception as e:
            print("Update-Meldung ans Handy:", e)
        print("Update: keiner am PC – starte selbst neu.")
        restart(pc_nachrichten.ON_QUIT)
        return True
    except Exception as e:
        print("Auto-Update:", e)
        return False


def start(ask):
    """Hintergrund-Schleife: alle 30 Minuten nachsehen (erstes Mal nach 2 Minuten). Ist ein Update fertig und
    keiner am PC, spielt er es selbst ein (sonst fragt er wie bisher)."""
    def loop():
        time.sleep(120)
        last = 0.0
        while True:
            try:
                if _auto_install():
                    return
                if time.time() - last >= (AWAY_EVERY if AWAY["on"] else CHECK_EVERY):
                    last = time.time()
                    r = check_now(ask)
                    if "Update" in r:
                        print(r)
            except Exception as e:
                print("Update-Prüfung:", e)
            time.sleep(60)
    if possible():
        threading.Thread(target=loop, daemon=True).start()
