"""
Weg-Wächter: läuft nur im Weg-Modus („Jarvis, ich bin jetzt weg“).

Jede Minute schaut er nach:
  - Hängt ein Programm (Windows meldet „reagiert nicht“) länger als 3 Minuten -> beenden.
  - Ist der Arbeitsspeicher länger als 3 Minuten über 90 % -> die größten Programme speichern (wo das geht) und schließen.
  - Lässt sich das Problem so nicht lösen (Speicher bleibt voll, Programm lässt sich nicht beenden)
    -> alles speichern, Programme schließen und den PC herunterfahren.
Jede Aktion kommt als Nachricht aufs Handy. Sobald jemand Maus/Tastatur benutzt, ist der Weg-Modus vorbei.
"""

import threading
import time

CHECK = 60
HUNG_AFTER = 3 * 60
RAM_HIGH = 90.0
RAM_CRIT = 95.0
RAM_AFTER = 3            # so viele Prüfungen hintereinander zu voll
# Programme, die beim Schließen gespeichert werden können (Strg+S vorher)
SAVE_FIRST = {"winword.exe", "excel.exe", "powerpnt.exe", "notepad.exe", "notepad++.exe", "code.exe", "wordpad.exe",
              "soffice.bin", "photoshop.exe", "obs64.exe"}
GAMES = {"eurotrucks2.exe", "amtrucks.exe"}

_hung_since = {}         # pid -> Zeitpunkt
_ram_bad = [0]
_log = []


def _say(text: str):
    print("Weg-Wächter:", text)
    _log.append((time.time(), text))
    del _log[:-30]
    try:
        import pc_phone
        pc_phone.push("PC (Weg-Modus)", text, tags="shield")
    except Exception as e:
        print("Weg-Wächter Handy:", e)


def recent() -> list:
    return [t for ts, t in _log if time.time() - ts < 12 * 3600]


def _windows():
    """Sichtbare Programmfenster: (hwnd, pid, exe, titel, hängt)."""
    import ctypes
    from ctypes import wintypes
    import pc_windows
    import pc_alltag
    user32 = ctypes.windll.user32
    out = []

    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            if user32.GetWindowLongW(hwnd, -20) & 0x80 or user32.GetWindow(hwnd, 4):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            name = pc_windows._process_name(pid.value)
            if name in pc_alltag.KEEP:
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            out.append((hwnd, pid.value, name, buf.value, bool(user32.IsHungAppWindow(hwnd))))
        except Exception:
            pass
        return True
    user32.EnumWindows(pc_windows.WNDENUMPROC(cb), 0)
    return out


def _nice(name: str, title: str) -> str:
    t = (title or "").split(" - ")[-1].strip()
    return t if 2 < len(t) < 40 else name.replace(".exe", "")


def _kill(pid: int) -> bool:
    try:
        import psutil
        p = psutil.Process(pid)
        p.kill()
        p.wait(10)
        return True
    except Exception:
        try:
            import subprocess
            subprocess.run(["taskkill", "/f", "/pid", str(pid)], capture_output=True, creationflags=0x08000000)
            return True
        except Exception:
            return False


def _alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != "zombie"
    except Exception:
        return False


def _save_and_close(hwnd: int, pid: int, name: str) -> bool:
    """Erst speichern (Spiel: Schnellspeichern, Office/Editor: Strg+S), dann normal schließen; hilft das nicht: beenden."""
    import ctypes
    from ctypes import wintypes
    import pc_windows
    try:
        if name in GAMES:
            import pc_alltag
            pc_alltag._save_game()
        elif name in SAVE_FIRST:
            import pyautogui
            pc_windows.bring_to_front(hwnd)
            time.sleep(1.0)
            pyautogui.hotkey("ctrl", "s")
            time.sleep(3)
        ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0)   # WM_CLOSE
    except Exception as e:
        print("Weg-Wächter schließen:", e)
    for _ in range(15):
        time.sleep(1)
        if not _alive(pid):
            return True
    return _kill(pid)


def _shutdown(why: str):
    _say(f"{why} Ich speichere, schließe alles und fahre den PC herunter.")
    try:
        import pc_update
        pc_update.AWAY["on"] = False
        import pc_alltag
        pc_alltag.shutdown_sequence()
    except Exception as e:
        print("Weg-Wächter herunterfahren:", e)


def check():
    import psutil
    wins = _windows()
    now = time.time()
    # 1) Hängende Programme
    hung_pids = {pid for _, pid, _, _, h in wins if h}
    for pid in list(_hung_since):
        if pid not in hung_pids:
            _hung_since.pop(pid, None)
    for hwnd, pid, name, title, h in wins:
        if not h:
            continue
        since = _hung_since.setdefault(pid, now)
        if now - since >= HUNG_AFTER:
            _hung_since.pop(pid, None)
            if name in GAMES:
                pass   # Spiel hängt: Speichern geht nicht mehr
            ok = _kill(pid)
            if ok:
                _say(f"{_nice(name, title)} hat nicht mehr reagiert – ich hab's beendet.")
            else:
                _shutdown(f"{_nice(name, title)} hängt und lässt sich nicht beenden.")
                return
    # 2) Arbeitsspeicher
    ram = psutil.virtual_memory().percent
    if ram < RAM_HIGH:
        _ram_bad[0] = 0
        return
    _ram_bad[0] += 1
    if _ram_bad[0] < RAM_AFTER:
        return
    _ram_bad[0] = 0
    by_pid = {}
    for hwnd, pid, name, title, h in wins:
        by_pid.setdefault(pid, (hwnd, name, title))
    big = []
    for pid, (hwnd, name, title) in by_pid.items():
        try:
            big.append((psutil.Process(pid).memory_info().rss, pid, hwnd, name, title))
        except Exception:
            pass
    big.sort(reverse=True)
    closed = []
    for rss, pid, hwnd, name, title in big[:3]:
        if _save_and_close(hwnd, pid, name):
            closed.append(_nice(name, title))
        if psutil.virtual_memory().percent < RAM_HIGH - 10:
            break
    ram2 = psutil.virtual_memory().percent
    if closed:
        _say(f"Arbeitsspeicher war voll ({ram:.0f} %). Gespeichert und geschlossen: {', '.join(closed)}. Jetzt {ram2:.0f} %.")
    if ram2 >= RAM_CRIT:
        _shutdown(f"Der Arbeitsspeicher bleibt voll ({ram2:.0f} %).")


def start():
    def loop():
        while True:
            time.sleep(CHECK)
            try:
                import pc_update
                if pc_update.AWAY["on"]:
                    import pc_nachrichten
                    if pc_nachrichten._idle_seconds() < 60:   # doch jemand da
                        continue
                    check()
                else:
                    _hung_since.clear(); _ram_bad[0] = 0
            except Exception as e:
                print("Weg-Wächter:", e)
    threading.Thread(target=loop, daemon=True, name="weg-waechter").start()
