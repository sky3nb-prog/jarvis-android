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


def latest() -> str:
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "Jarvis-PC"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))["sha"]


def possible() -> bool:
    return getattr(sys, "frozen", False) and os.path.exists(os.path.join(_src(), "build.bat"))


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
        return "Selbst-Update geht nur mit der fertigen PC-Assistent.exe und build.bat im Ordner darüber."
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
    threading.Thread(target=_build, args=(sha, ask), daemon=True).start()
    return "Es gibt ein Update. Ich baue es im Hintergrund und sag Bescheid, wenn es fertig ist."


def restart(quit_app) -> str:
    """Neue .exe einsetzen: Tausch-Skript starten, Jarvis beenden."""
    sha = _state.get("ready")
    if not sha:
        return "Es liegt kein fertiges Update bereit."
    src = _src()
    bat = os.path.join(src, "_update_tausch.bat")
    try:
        with open(bat, "w", encoding="utf-8") as f:
            f.write(SWAP.replace("\n", "\r\n"))
        d = _load(); d["sha"] = sha; d.pop("failed", None); _save(d)
        subprocess.Popen(["cmd", "/c", bat], cwd=src, creationflags=NO_WINDOW | DETACHED, close_fds=True)
        threading.Timer(1.5, quit_app).start()
        return "Ich starte kurz neu – bin gleich wieder da."
    except Exception as e:
        return f"Neustart ging nicht ({e})."


def start(ask):
    """Hintergrund-Schleife: alle 30 Minuten nachsehen (erstes Mal nach 2 Minuten)."""
    def loop():
        time.sleep(120)
        while True:
            try:
                r = check_now(ask)
                if "Update" in r:
                    print(r)
            except Exception as e:
                print("Update-Prüfung:", e)
            time.sleep(CHECK_EVERY)
    if possible():
        threading.Thread(target=loop, daemon=True).start()
