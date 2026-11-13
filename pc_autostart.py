"""
Automatischer Start mit Windows (Eintrag im Autostart des eigenen Benutzers, braucht keine Administratorrechte).
Beim Start per Autostart öffnet sich das HUD nicht; Jarvis wartet still im Tray auf das Aktivierungswort.
"""

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "Jarvis PC-Assistent"


def command() -> str:
    if getattr(sys, "frozen", False):  # die gebaute .exe
        return f'"{sys.executable}" --autostart'
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")  # ohne schwarzes Fenster
    if os.path.exists(pythonw):
        exe = pythonw
    from pc_apps import base_dir

    return f'"{exe}" "{os.path.join(base_dir(), "pc_overlay.py")}" --autostart'


def is_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return bool(winreg.QueryValueEx(key, NAME)[0])
    except Exception:
        return False


def set_enabled(on: bool) -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if on:
                winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
            else:
                try:
                    winreg.DeleteValue(key, NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        print(f"Autostart konnte nicht geändert werden: {e}")
        return False
