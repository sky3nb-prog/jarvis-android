"""
Fenster finden und in den Vordergrund holen (nur Windows, ohne Zusatzpakete).

- find_main_window(["discord.exe"]) -> Fenster-Handle oder None
- bring_to_front(hwnd): holt das Fenster ganz nach vorn, auch wenn es
  minimiert ist oder andere Fenster davor liegen
- wait_for_window(...): wartet, bis ein frisch gestartetes Programm sein Fenster zeigt
"""

import ctypes
import os
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_size_t]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)


def _process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def find_main_window(process_names, title_contains=None):
    """Größtes sichtbares Fenster der angegebenen Programme (z. B. ['discord.exe']).

    Optional wird auch ein Fenster gefunden, dessen Titel den Text enthält
    (z. B. 'deezer' für den Web-Player im Browser)."""
    wanted = {n.lower() for n in process_names}
    hint = title_contains.lower() if title_contains else None
    found = []

    def callback(hwnd, lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            if user32.GetWindowLongW(hwnd, -20) & 0x80:  # Tool-Fenster überspringen
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            title_ok = False
            if hint:
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, buf, 512)
                title_ok = hint in buf.value.lower()
            if title_ok or _process_name(pid.value) in wanted:
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
                found.append((area, hwnd))
        except Exception:
            pass
        return True

    enum_proc = WNDENUMPROC(callback)  # Referenz halten, solange EnumWindows läuft
    user32.EnumWindows(enum_proc, 0)
    if not found:
        return None
    return max(found, key=lambda item: item[0])[1]


def foreground_window():
    return user32.GetForegroundWindow()


def bring_to_front(hwnd):
    """Holt das Fenster nach vorn, auch aus der Taskleiste oder hinter anderen Fenstern."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    else:
        user32.ShowWindow(hwnd, 5)  # SW_SHOW

    fg = user32.GetForegroundWindow()
    current = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = False
    if fg_thread and fg_thread != current:
        attached = bool(user32.AttachThreadInput(current, fg_thread, True))
    try:
        # Kurzer Alt-Tastendruck: erlaubt Windows, den Fokus zu wechseln
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current, fg_thread, False)

    # Sicherheitsnetz: kurz "immer oben", damit es garantiert sichtbar vorn liegt
    flags = 0x0001 | 0x0002 | 0x0040  # NOSIZE | NOMOVE | SHOWWINDOW
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)


def wait_for_window(process_names, timeout: float = 20.0, title_contains=None):
    end = time.time() + timeout
    while time.time() < end:
        hwnd = find_main_window(process_names, title_contains)
        if hwnd:
            return hwnd
        time.sleep(0.5)
    return None


def visible_windows() -> dict:
    """Alle sichtbaren Fenster mit Titel (ohne die des eigenen Programms): {Handle: Fläche}."""
    found = {}

    def callback(hwnd, lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            if user32.GetWindowLongW(hwnd, -20) & 0x80:  # Tool-Fenster überspringen
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == os.getpid():
                return True
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found[hwnd] = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
        except Exception:
            pass
        return True

    enum_proc = WNDENUMPROC(callback)
    user32.EnumWindows(enum_proc, 0)
    return found


def wait_for_new_window(before, timeout: float = 6.0):
    """Wartet, bis nach dem Start eines Programms ein neues Fenster erscheint (oder ein
    anderes Fenster den Fokus bekommt). Gibt das Fenster zurück oder None."""
    before_fg = foreground_window()
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(0.4)
        now = visible_windows()
        new = {h: a for h, a in now.items() if h not in before and a >= 100 * 100}
        if new:
            return max(new, key=new.get)
        fg = foreground_window()
        if fg and fg != before_fg and fg in now:
            return fg
    return None
