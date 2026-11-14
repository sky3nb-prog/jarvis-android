"""
Iron-Man-Start: Vollbild-Hologramm nach dem Anmelden (pc_web/boot.html) – Kugel baut sich auf, Systemstatus läuft ein,
"Willkommen zurück, Sir. Alle Systeme bereit." Eigener Prozess:  PC-Assistent.exe --boot <port> <anrede>
Klick oder Esc überspringt. Schließt sich selbst nach dem Gruß.
"""

import os
import sys
import threading
import time


class Api:
    def __init__(self):
        self.win = None

    def close(self):
        threading.Thread(target=lambda: (time.sleep(.1), self.win.destroy()), daemon=True).start()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    a = sys.argv[sys.argv.index("--boot") + 1:]
    port = int(a[0])
    name = a[1] if len(a) > 1 else "Sir"
    import urllib.parse
    import webview
    api = Api()
    win = webview.create_window("Jarvis Start", f"http://127.0.0.1:{port}/boot.html?name={urllib.parse.quote(name)}", js_api=api,
                                fullscreen=True, frameless=True, on_top=True, background_color="#000000", text_select=False)
    api.win = win
    threading.Timer(25, lambda: win.destroy()).start()   # Sicherheitsnetz
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    webview.start(gui="edgechromium", private_mode=False, storage_path=os.path.join(base, "boot_fenster"))


def launch(port: int, name: str = "Sir"):
    import subprocess
    try:
        import pc_hudwin
        if not pc_hudwin.available() or not port:
            return False
        me = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pc_overlay.py")]
        subprocess.Popen(me + ["--boot", str(port), name or "Sir"], creationflags=0x08000000)
        return True
    except Exception as e:
        print("Start-Animation ging nicht:", e)
        return False
