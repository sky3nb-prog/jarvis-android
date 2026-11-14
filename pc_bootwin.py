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
        # Fenster zu und Prozess sicher beenden (destroy allein blieb manchmal schwarz hängen)
        def bye():
            time.sleep(.1)
            try:
                self.win.destroy()
            except Exception:
                pass
            time.sleep(.6)
            os._exit(0)
        threading.Thread(target=bye, daemon=True).start()


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
    threading.Timer(22, lambda: os._exit(0)).start()   # Sicherheitsnetz: spätestens dann ist Schluss
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    webview.start(gui="edgechromium", private_mode=False, storage_path=os.path.join(base, "boot_fenster"))


PROC = {"p": None}


def kill():
    """Vom Hauptprogramm: Start-Animation sicher schließen (falls das Fenster hängt)."""
    p = PROC.get("p")
    if p and p.poll() is None:
        try:
            p.kill()
        except Exception:
            pass


def launch(port: int, name: str = "Sir"):
    import subprocess
    try:
        import pc_hudwin
        if not pc_hudwin.available() or not port:
            return False
        me = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pc_overlay.py")]
        PROC["p"] = subprocess.Popen(me + ["--boot", str(port), name or "Sir"], creationflags=0x08000000)
        threading.Timer(24, kill).start()
        return True
    except Exception as e:
        print("Start-Animation ging nicht:", e)
        return False
