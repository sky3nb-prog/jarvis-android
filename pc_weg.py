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

FILES = ["Jarvis-Konto.exe", "Jarvis-Konto-Debug.exe", "LIESMICH.txt", "README.html",
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
    sm = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Vector.lnk")
    if os.path.exists(sm):
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, "Vector PC-Assistent")
            return True
    except Exception:
        return False


def _ps_quote(p: str) -> str:
    return "'" + p.replace("'", "''") + "'"


UNINST_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\JarvisKonto"


def _spawn_cleanup(script: str):
    """Startet das Aufräum-Skript so, dass es weiterläuft, wenn Jarvis beendet wird.
    Wichtig: Das fertige Programm läuft in einer Prozess-Gruppe, die beim Beenden alle Kinder mitreißt.
    Deshalb lässt Windows selbst (WMI) das Skript starten – dann gehört es nicht mehr zu Jarvis."""
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    cmd = f"powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand {enc}"
    starter = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=" + _ps_quote(cmd)
               + "; CurrentDirectory=$env:TEMP}; exit [int]$r.ReturnValue")
    enc2 = base64.b64encode(starter.encode("utf-16-le")).decode("ascii")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc2],
                       capture_output=True, timeout=30, creationflags=0x08000000)
    if r.returncode != 0:   # Notlösung: direkt starten und versuchen, aus der Gruppe auszubrechen
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                          "-EncodedCommand", enc], cwd=os.environ.get("TEMP") or None, close_fds=True,
                         creationflags=0x01000000 | 0x00000008 | 0x00000200 | 0x08000000)


def hide_data_files():
    """Download-Version: Hilfsordner und die Debug-Version im Programmordner verstecken. Die Daten selbst liegen
    im versteckten Ordner „Jarvis-Daten“ (pc_apps.base_dir). Dateien selbst nie verstecken – sonst lässt Windows
    sie nicht mehr überschreiben."""
    if not allowed() or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes
        exe_dir = os.path.dirname(sys.executable)
        for n in ("Jarvis-Daten", "hud_fenster", "hud_profil", "piper", "sticker", "_neu"):
            p = os.path.join(exe_dir, n)
            if os.path.isdir(p):
                a = ctypes.windll.kernel32.GetFileAttributesW(p)
                if a != -1 and not a & 0x2:
                    ctypes.windll.kernel32.SetFileAttributesW(p, a | 0x2)
    except Exception as e:
        print("Ordner verstecken ging nicht:", e)


def register_uninstall():
    """Eintrag unter Einstellungen → Apps, damit man Jarvis ganz normal deinstallieren kann (nur fertige .exe, nur Konto-Ausgabe)."""
    if not allowed() or not getattr(sys, "frozen", False):
        return
    try:
        import winreg
        exe = sys.executable
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINST_KEY) as k:
            for name, val in (("DisplayName", "Vector"), ("DisplayIcon", exe + ",0"), ("Publisher", "Vector"),
                              ("UninstallString", f'"{exe}" --uninstall'), ("QuietUninstallString", f'"{exe}" --uninstall --quiet'),
                              ("InstallLocation", os.path.dirname(exe)), ("DisplayVersion", _version())):
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
    except Exception as e:
        print("Deinstallieren-Eintrag ging nicht:", e)


def _version() -> str:
    try:
        import pc_overlay
        return str(getattr(pc_overlay, "VERSION", ""))
    except Exception:
        return ""


def uninstall_main():
    """Aufruf aus Windows (Apps → Deinstallieren): kurz nachfragen, dann alles löschen."""
    quiet = "--quiet" in sys.argv
    if not quiet:
        try:
            import ctypes
            r = ctypes.windll.user32.MessageBoxW(None, "Vector komplett von diesem PC entfernen?\n\nDein Konto bleibt – "
                                                 "lädst du Vector neu und meldest dich an, ist alles wieder da.",
                                                 "Vector deinstallieren", 0x4 | 0x30 | 0x40000)   # Ja/Nein, Warnung, im Vordergrund
            if r != 6:
                return
        except Exception:
            pass
    destroy(None, wait=False)
    import time
    time.sleep(1)


def destroy(quit_cb=None, wait: bool = True) -> dict:
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

    data = base_dir()
    folder = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else data
    targets = [os.path.join(folder, n) for n in FILES + DIRS] + [os.path.join(data, n) for n in FILES + DIRS]
    targets += [os.path.join(folder, n) for n in ("Jarvis-Daten", "hud_fenster")]
    sm = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Vector Konto.lnk")
    targets.append(sm)
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINST_KEY)
    except Exception:
        pass
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
    try:
        _spawn_cleanup(script)
    except Exception as e:
        return {"ok": False, "text": f"Aufräumen ließ sich nicht starten: {e}"}

    if not wait:
        return {"ok": True, "text": "Vector wird entfernt."}

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
    return {"ok": True, "text": "Vector löscht sich jetzt von diesem PC" + (" (" + ", ".join(steps) + ")" if steps else "") + ". Tschüss."}
