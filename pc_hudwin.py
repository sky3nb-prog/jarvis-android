"""
Eigenes HUD-Fenster von Jarvis (statt Edge).

Läuft als zweiter Prozess derselben PC-Assistent.exe:  PC-Assistent.exe --hud <port> <breite> <höhe>
und zeigt die HUD-Seite vom lokalen Jarvis-Server mit pywebview an. Das Fenster gehört damit zu
PC-Assistent.exe: Jarvis-Symbol in der Taskleiste, Anheften startet Jarvis, Titelleiste in den HUD-Farben.
Im Hintergrund nutzt pywebview die in Windows eingebaute Anzeige (WebView2), Edge selbst geht nicht auf.
"""

import ctypes
import os
import sys
import threading
import time

TITLE = "Jarvis HUD"
APP_ID = "Jarvis.PCAssistent"


def _hwnd():
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    pid, found = os.getpid(), []

    def cb(h, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(h):
            n = user32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, buf, n + 1)
            if buf.value.startswith(TITLE):
                found.append(h)
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    return found[0] if found else None


def _style_window():
    """Titelleiste dunkel mit goldener Schrift, Taskleisten-Kennung von Jarvis."""
    h = None
    for _ in range(80):
        h = _hwnd()
        if h:
            break
        time.sleep(0.1)
    if not h:
        return
    try:
        import pc_webhud
        pc_webhud.set_app_id(h)
    except Exception:
        pass
    try:
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(h, 20, ctypes.byref(dark), 4)   # dunkler Modus (Windows 10/11)
        for attr, rgb in ((35, (0x0a, 0x06, 0x02)), (36, (0xff, 0xd6, 0x78)), (34, (0x5a, 0x3e, 0x14))):
            v = ctypes.c_uint(rgb[0] | (rgb[1] << 8) | (rgb[2] << 16))   # 35 Leiste, 36 Schrift, 34 Rand (Windows 11)
            dwm.DwmSetWindowAttribute(h, attr, ctypes.byref(v), 4)
        # neu zeichnen, damit die Farbe sofort sichtbar ist
        ctypes.windll.user32.SetWindowPos(h, 0, 0, 0, 0, 0, 0x0027)   # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
    except Exception:
        pass


def main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    a = sys.argv[sys.argv.index("--hud") + 1:]
    port = int(a[0])
    w = int(a[1]) if len(a) > 1 else 1280
    h = int(a[2]) if len(a) > 2 else 800
    import webview
    win = webview.create_window(TITLE, f"http://127.0.0.1:{port}/hud.html", width=w, height=h, min_size=(900, 560),
                                background_color="#000000", text_select=False)
    win.events.shown += lambda: threading.Thread(target=_style_window, daemon=True).start()
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    webview.start(gui="edgechromium", private_mode=False, storage_path=os.path.join(base, "hud_fenster"))


def available() -> bool:
    """pywebview da? (Die eigentliche Anzeige WebView2 ist in Windows 10/11 eingebaut.)"""
    try:
        import importlib.util
        return importlib.util.find_spec("webview") is not None
    except Exception:
        return False
