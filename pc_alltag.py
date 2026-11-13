"""
Zuhause und weg (Befehle kommen vom Handy, das dein Heim-WLAN kennt):

  "weg":  Du bist seit ein paar Minuten aus dem Haus und hast am Handy nicht abgebrochen.
          Sitzt gerade jemand am PC (Maus/Tastatur in den letzten 2 Minuten), fragt Jarvis laut, ob er herunterfahren soll.
          Sonst: Musik pausieren, ETS2 schnell speichern, Programme schließen, PC in einer Minute herunterfahren
          ("Friday, abbrechen" stoppt es).
  "heim": "Willkommen zurück" (falls der PC läuft).
"""

import time

QUICKSAVE_KEY = "f5"          # ETS2/ATS: Taste fürs Schnellspeichern (Einstellung "ets2_quicksave")
KEEP = {"pc-assistent.exe", "explorer.exe", "msedgewebview2.exe", "textinputhost.exe", "shellexperiencehost.exe",
        "searchhost.exe", "startmenuexperiencehost.exe", "applicationframehost.exe", "systemsettings.exe",
        "lockapp.exe", "python.exe", "pythonw.exe", "wavelink.exe", "elgato wave link.exe", "nvcontainer.exe",
        "steamwebhelper.exe"}


def _idle() -> float:
    import pc_nachrichten
    return pc_nachrichten._idle_seconds()


def _pause_music():
    try:
        import pc_media
        r = pc_media.now()
        if r and r.get("playing"):
            import pyautogui
            pyautogui.press("playpause")
            return True
    except Exception as e:
        print(f"Weg: Musik pausieren ging nicht: {e}")
    return False


def _save_game():
    try:
        import pyautogui
        import pc_windows
        hwnd = pc_windows.find_main_window(["eurotrucks2.exe", "amtrucks.exe"])
        if not hwnd:
            return False
        pc_windows.bring_to_front(hwnd)
        time.sleep(1.5)
        pyautogui.press(QUICKSAVE_KEY)
        time.sleep(4)   # speichern lassen
        print("Weg: ETS2 schnell gespeichert")
        return True
    except Exception as e:
        print(f"Weg: Spiel speichern ging nicht: {e}")
    return False


def _close_programs() -> int:
    """Allen sichtbaren Programmfenstern "schließen" schicken (wie auf das X klicken; fragt ein Programm nach dem
    Speichern, bleibt es offen)."""
    import ctypes
    from ctypes import wintypes
    import pc_windows
    user32 = ctypes.windll.user32
    hwnds = []

    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            if user32.GetWindowLongW(hwnd, -20) & 0x80 or user32.GetWindow(hwnd, 4):   # Tool-Fenster / hat Besitzer
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pc_windows._process_name(pid.value) not in KEEP:
                hwnds.append(hwnd)
        except Exception:
            pass
        return True
    proc = pc_windows.WNDENUMPROC(cb)
    user32.EnumWindows(proc, 0)
    for h in hwnds:
        try:
            user32.PostMessageW(wintypes.HWND(h), 0x0010, 0, 0)   # WM_CLOSE
        except Exception:
            pass
    return len(hwnds)


def shutdown_sequence() -> str:
    import pc_steuerung
    music = _pause_music()
    game = _save_game()
    n = _close_programs()
    time.sleep(3)
    r = pc_steuerung.execute_power("shutdown")
    print(f"Weg: Musik {'pausiert' if music else '-'}, Spiel {'gespeichert' if game else '-'}, {n} Fenster geschlossen")
    return ("Ich habe " + ("die Musik pausiert, " if music else "") + ("ETS2 gespeichert, " if game else "")
            + "die Programme geschlossen. " + r)


def away(settings: dict = None) -> str:
    """Vom Handy: Skyler ist aus dem Haus."""
    global QUICKSAVE_KEY
    if settings and settings.get("ets2_quicksave"):
        QUICKSAVE_KEY = str(settings["ets2_quicksave"]).strip().lower() or QUICKSAVE_KEY
    import pc_nachrichten
    if _idle() < 120:   # da sitzt jemand
        pc_nachrichten.incoming({"kind": "offer", "force": True, "action": "shutdown",
                                 "question": "Skyler ist gerade unterwegs. Soll ich den PC herunterfahren?"})
        return "Am PC ist gerade jemand, ich frage nach."
    return shutdown_sequence()


def home() -> str:
    import pc_nachrichten
    pc_nachrichten.incoming({"kind": "say", "force": True, "text": "Willkommen zurück, Skyler."})
    return "Begrüßt."
