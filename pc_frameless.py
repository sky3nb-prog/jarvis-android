"""
Randlose Fenster für Windows (ohne Titelleiste mit _ □ X und ohne den hellen Rand oben).

Das Fenster bleibt ein ganz normales Programm-Fenster: Es hat ein Symbol in der Taskleiste, lässt sich minimieren
und mit Alt+Tab wechseln. Verschieben, Größe ändern und Schließen übernehmen eigene Knöpfe im Fenster.
Unter Windows 11 bekommt es außerdem runde Ecken.
"""

import ctypes
from ctypes import wintypes

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_POPUP = 0x80000000
SWP_FLAGS = 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010  # FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER | NOACTIVATE
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUND = 2
DWMWA_COLOR_NONE = 0xFFFFFFFE


def hwnd_of(win) -> int:
    try:
        win.update_idletasks()
        return ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
    except Exception:
        return 0


def apply(win, rounded: bool = True) -> bool:
    """Nimmt dem Tk-Fenster Titelleiste und Rahmen. Nach jedem Wieder-Einblenden erneut aufrufen (macht nichts kaputt)."""
    try:
        user32 = ctypes.windll.user32
        hwnd = hwnd_of(win)
        if not hwnd:
            return False
        get = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        setl = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        get.restype = ctypes.c_ssize_t
        get.argtypes = [wintypes.HWND, ctypes.c_int]
        setl.restype = ctypes.c_ssize_t
        setl.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        style = get(hwnd, GWL_STYLE) & 0xFFFFFFFF
        new = (style & ~(WS_CAPTION | WS_THICKFRAME | WS_MAXIMIZEBOX)) | WS_POPUP | WS_MINIMIZEBOX | WS_SYSMENU
        if new != style:
            setl(hwnd, GWL_STYLE, ctypes.c_ssize_t(ctypes.c_int32(new & 0xFFFFFFFF).value).value)
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FLAGS)
        try:
            dwm = ctypes.windll.dwmapi
            if rounded:
                pref = ctypes.c_int(DWMWCP_ROUND)
                dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), 4)
            color = ctypes.c_uint(DWMWA_COLOR_NONE)
            dwm.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(color), 4)
        except Exception:
            pass  # Windows 10: keine runden Ecken, sonst alles gleich
        return True
    except Exception as e:
        print(f"Randloses Fenster nicht möglich: {e}")
        return False


def _colorref(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def color_titlebar(win, bg_hex: str, text_hex: str = "#cdeffc") -> bool:
    """Normale Windows-Titelleiste behalten, aber in der Farbe des Fensters einfärben (Windows 11).
    Unter Windows 10 wird sie zumindest dunkel."""
    try:
        hwnd = hwnd_of(win)
        if not hwnd:
            return False
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (neu und alt)
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(dark), 4) == 0:
                break
        for attr, value in ((35, _colorref(bg_hex)), (36, _colorref(text_hex)), (34, _colorref(bg_hex))):
            v = ctypes.c_uint(value)  # 35 = Leiste, 36 = Schrift, 34 = Rand
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4)
        return True
    except Exception:
        return False


def work_area():
    """Bildschirmfläche ohne Taskleiste: (x, y, Breite, Höhe)."""
    try:
        r = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    except Exception:
        return None


class Mover:
    """Verschieben mit gedrückter Maustaste, Doppelklick = maximieren/zurück."""

    def __init__(self, win, on_double=None):
        self.win, self.on_double = win, on_double
        self._start = None

    def bind(self, widget, tag=None):
        b = (lambda seq, fn: widget.tag_bind(tag, seq, fn)) if tag else (lambda seq, fn: widget.bind(seq, fn, add="+"))
        b("<ButtonPress-1>", self._press)
        b("<B1-Motion>", self._drag)
        if self.on_double:
            b("<Double-Button-1>", lambda e: self.on_double())

    def _press(self, e):
        self._start = (e.x_root - self.win.winfo_rootx(), e.y_root - self.win.winfo_rooty())

    def _drag(self, e):
        if self._start:
            self.win.geometry(f"+{e.x_root - self._start[0]}+{e.y_root - self._start[1]}")


class Resizer:
    """Größe ändern an einem Griff unten rechts."""

    def __init__(self, win, min_w=400, min_h=300):
        self.win, self.min_w, self.min_h = win, min_w, min_h
        self._start = None

    def bind(self, widget, tag=None):
        b = (lambda seq, fn: widget.tag_bind(tag, seq, fn)) if tag else (lambda seq, fn: widget.bind(seq, fn, add="+"))
        b("<ButtonPress-1>", self._press)
        b("<B1-Motion>", self._drag)

    def _press(self, e):
        self._start = (e.x_root, e.y_root, self.win.winfo_width(), self.win.winfo_height())
        return "break"

    def _drag(self, e):
        if self._start:
            x0, y0, w0, h0 = self._start
            w = max(self.min_w, w0 + e.x_root - x0)
            h = max(self.min_h, h0 + e.y_root - y0)
            self.win.geometry(f"{int(w)}x{int(h)}")
        return "break"
