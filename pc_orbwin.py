"""
Neues kleines Overlay am PC: 3D-Kugel mit Nervenstrang (pc_web/orb.html).

Läuft als eigener Prozess derselben PC-Assistent.exe:  PC-Assistent.exe --orb <port> <ecke>
Ein randloses, durchsichtiges Fenster im Bildschirm-Eck, immer im Vordergrund, nicht in der Taskleiste,
nimmt keinen Fokus und lässt Mausklicks durch (man klickt also "durch" das Overlay hindurch).
Die Seite hört dieselben Ereignisse wie das HUD (/events): state, msg, level.
Klappt das Fenster nicht (pywebview/WebView2 fehlt), nimmt pc_overlay wieder das alte Tk-Overlay.
"""

import ctypes
import os
import subprocess
import sys
import threading
import time

TITLE = "Jarvis Overlay"
W, H = 640, 250            # Fenstergröße in logischen Pixeln (Strang + Kugel + Sprechblase)
CORNER = {"oben links": "tl", "oben rechts": "tr", "unten links": "bl", "unten rechts": "br"}
NO_WINDOW = 0x08000000


# --- im Kindprozess -------------------------------------------------------------------------------------
def _hwnd():
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    pid, found = os.getpid(), []

    def cb(h, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            n = user32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, buf, n + 1)
            if buf.value == TITLE:
                found.append(h)
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    return found[0] if found else None


def _place(corner: str):
    """Ins Eck der Arbeitsfläche (ohne Taskleiste) legen, Klicks durchlassen, nicht in die Taskleiste."""
    h = None
    for _ in range(100):
        h = _hwnd()
        if h:
            break
        time.sleep(0.1)
    if not h:
        return
    u = ctypes.windll.user32
    try:
        from ctypes import wintypes
        r = wintypes.RECT()
        u.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)      # SPI_GETWORKAREA (physische Pixel)
        try:
            k = u.GetDpiForWindow(h) / 96.0
        except Exception:
            k = 1.0
        w, hh = int(W * k), int(H * k)
        x = r.right - w if "r" in corner else r.left
        y = r.bottom - hh if "b" in corner else r.top
        GWL_EXSTYLE = -20
        ex = u.GetWindowLongW(h, GWL_EXSTYLE)
        ex |= 0x80 | 0x20 | 0x08000000 | 0x80000      # TOOLWINDOW | TRANSPARENT (Klicks durch) | NOACTIVATE | LAYERED
        ex &= ~0x40000                                 # kein APPWINDOW
        u.SetWindowLongW(h, GWL_EXSTYLE, ex)
        u.SetWindowPos(h, -1, x, y, w, hh, 0x0010 | 0x0020)   # TOPMOST, NOACTIVATE | FRAMECHANGED
    except Exception as e:
        print("Overlay-Fenster platzieren ging nicht:", e)

    def keep_top():   # Spiele/Vollbild-Fenster schieben sich gern davor
        while True:
            time.sleep(4)
            try:
                u.SetWindowPos(h, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            except Exception:
                return
    threading.Thread(target=keep_top, daemon=True).start()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    a = sys.argv[sys.argv.index("--orb") + 1:]
    port = int(a[0])
    corner = a[1] if len(a) > 1 else "tl"
    import webview
    kw = dict(width=W, height=H, frameless=True, on_top=True, transparent=True, easy_drag=False,
              text_select=False, background_color="#000000", focus=False)
    try:
        win = webview.create_window(TITLE, f"http://127.0.0.1:{port}/orb.html?corner={corner}", **kw)
    except TypeError:          # ältere pywebview-Version ohne focus=
        kw.pop("focus", None)
        win = webview.create_window(TITLE, f"http://127.0.0.1:{port}/orb.html?corner={corner}", **kw)
    win.events.shown += lambda: threading.Thread(target=_place, args=(corner,), daemon=True).start()
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    webview.start(gui="edgechromium", private_mode=False, storage_path=os.path.join(base, "hud_fenster"))


# --- im Hauptprogramm -----------------------------------------------------------------------------------
class OrbWin:
    """Startet/stoppt das Overlay-Fenster. ok() = läuft (sonst nimmt pc_overlay das alte Tk-Overlay)."""

    def __init__(self, port: int, corner: str):
        self.port, self.corner, self.proc, self.failed = port, CORNER.get(corner, "tl"), None, False
        self.start()

    def start(self):
        try:
            import pc_hudwin
            if not pc_hudwin.available():
                self.failed = True
                return
            me = [sys.executable] if getattr(sys, "frozen", False) else \
                [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pc_overlay.py")]
            self.proc = subprocess.Popen(me + ["--orb", str(self.port), self.corner], creationflags=NO_WINDOW)
            threading.Thread(target=self._watch, daemon=True).start()
        except Exception as e:
            print("Neues Overlay ging nicht:", e)
            self.failed = True

    def _watch(self):
        p, t0 = self.proc, time.time()
        while p.poll() is None:
            time.sleep(1)
        if p is not self.proc:         # absichtlich beendet (Ecke geändert, Programmende)
            return
        if time.time() - t0 < 20:      # gleich wieder weg: kaputt, altes Overlay nehmen
            print(f"Neues Overlay beendet sich sofort (Code {p.returncode}), nehme das alte.")
            self.failed = True
        elif p is self.proc and not self.failed:
            self.start()               # später abgestürzt: einmal neu starten

    def ok(self) -> bool:
        return not self.failed and self.proc is not None and self.proc.poll() is None

    def set_corner(self, corner: str):
        c = CORNER.get(corner, "tl")
        if c != self.corner:
            self.corner = c
            self.stop()
            self.failed = False
            self.start()

    def stop(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
