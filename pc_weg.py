"""
Selbstzerstörung – nur in der Ausgabe für alle (Jarvis Konto von der Website).

Was passiert:
  1. Dieser PC wird abgemeldet (das Konto und seine Sicherung bleiben – neu laden + anmelden = alles wieder da)
  2. Autostart-Eintrag und Startmenü-Verknüpfung werden entfernt
  3. Jarvis beendet sich; ein kleines Aufräum-Skript wartet, bis er wirklich zu ist, und löscht dann
     das Programm, alle seine Dateien (Einstellungen, Gedächtnis, Protokolle, Stimmen) und seinen Ordner
Es wird nur gelöscht, was Jarvis gehört; der Ordner selbst nur, wenn danach nichts anderes mehr drin liegt.
Liegt Jarvis direkt in einem fremden Ordner (z. B. „Dokumente“), bleiben alle anderen Dateien dort unangetastet.
"""

import base64
import os
import subprocess
import sys

FILES = ["Jarvis-Konto.exe", "Jarvis-Konto-Debug.exe", "LIESMICH.txt",
         "einstellungen.json", "erinnerungen.json", "ets2_orte.json", "gaming.json", "gassi_log.json", "gedaechtnis.json",
         "handy_app.json", "handy_themen.json", "ideen.json", "interessen_pc.json", "konto.json", "lernen.json",
         "meine_befehle.json", "meldungen.json", "orte_genau.json", "schreibstil.json", "schule_eintraege.json",
         "stil_importiert.json", "stil_name.json", "stundenplan.json", "sync_state.json", "themen_pc.json", "update.json",
         "weltlage.json", "jarvis_log.txt", "update_log.txt", "live_agent.txt", "neu.txt", "w.db"]
DIRS = ["hud_profil", "hud_fenster", "piper", "_neu", "sticker", "__pycache__"]


def allowed() -> bool:
    return bool(__import__("pc_variante").KONTO)


def _private_jarvis_here() -> bool:
    """Ist auf diesem PC auch der normale (private) Jarvis eingerichtet? Dann bleiben gemeinsam genutzte Ordner."""
    sm = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Jarvis.lnk")
    if os.path.exists(sm):
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, "Jarvis PC-Assistent")
            return True
    except Exception:
        return False


def _ps_quote(p: str) -> str:
    return "'" + p.replace("'", "''") + "'"


def destroy(quit_cb=None) -> dict:
    if not allowed():
        return {"ok": False, "text": "Gibt es nur in der Ausgabe von der Website."}
    from pc_apps import base_dir
    import pc_autostart
    import pc_konto

    steps = []
    try:
        pc_konto.forget_device()
        steps.append("abgemeldet")
    except Exception as e:
        print("Selbstzerstörung – Konto:", e)
    try:
        pc_autostart.set_enabled(False)
        steps.append("Autostart entfernt")
    except Exception as e:
        print("Selbstzerstörung – Autostart:", e)

    folder = base_dir()
    targets = [os.path.join(folder, n) for n in FILES + DIRS]
    sm = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Jarvis Konto.lnk")
    targets.append(sm)
    la = os.environ.get("LOCALAPPDATA") or ""
    if la and not _private_jarvis_here():   # gemeinsam mit dem privaten Jarvis genutzt – nur löschen, wenn es den hier nicht gibt
        targets += [os.path.join(la, "JarvisPiper"), os.path.join(la, "JarvisPair")]
    # eigener Jarvis-Ordner: dort auch übrige Jarvis-Dateien (.json/.txt) weg; der Ordner selbst nur, wenn er danach leer ist
    whole = "jarvis" in os.path.basename(folder.rstrip("\\/")).lower()

    script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$pidJ = {os.getpid()}
for ($i = 0; $i -lt 60; $i++) {{ if (-not (Get-Process -Id $pidJ -ErrorAction SilentlyContinue)) {{ break }}; Start-Sleep -Milliseconds 500 }}
Stop-Process -Id $pidJ -Force -ErrorAction SilentlyContinue
Get-Process -Name 'Jarvis-Konto','Jarvis-Konto-Debug' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
$t = @({', '.join(_ps_quote(p) for p in targets)})
foreach ($p in $t) {{ for ($k = 0; $k -lt 5; $k++) {{ if (Test-Path -LiteralPath $p) {{ Remove-Item -LiteralPath $p -Recurse -Force; Start-Sleep -Milliseconds 400 }} }} }}
$f = {_ps_quote(folder)}
if ({'$true' if whole else '$false'}) {{ Get-ChildItem -LiteralPath $f -File -Force | Where-Object {{ $_.Extension -in '.json','.txt','.log','.db','.bak' }} | Remove-Item -Force }}
if ((Test-Path -LiteralPath $f) -and -not (Get-ChildItem -LiteralPath $f -Force)) {{ Remove-Item -LiteralPath $f -Force }}
"""
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                          "-EncodedCommand", enc],
                         cwd=os.environ.get("TEMP") or None, close_fds=True,
                         creationflags=0x00000008 | 0x00000200 | 0x08000000)   # losgelöst, eigene Gruppe, ohne Fenster
    except Exception as e:
        return {"ok": False, "text": f"Aufräumen ließ sich nicht starten: {e}"}

    def _bye():
        import threading
        import time

        def run():
            time.sleep(1.5)
            try:
                if quit_cb:
                    quit_cb()
            finally:
                time.sleep(2)
                os._exit(0)
        threading.Thread(target=run, daemon=True).start()
    _bye()
    return {"ok": True, "text": "Jarvis löscht sich jetzt von diesem PC" + (" (" + ", ".join(steps) + ")" if steps else "") + ". Tschüss."}
