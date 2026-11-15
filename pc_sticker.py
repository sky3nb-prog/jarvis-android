"""
Sticker-Regen: „Schick 500 Sticker in die Gruppe TR9000“ / „… an Max“ – Jarvis fragt einmal nach und schickt dann
den ausgewählten Sticker so oft über WhatsApp Desktop (höchstens 1000 auf einmal).
Auswahl: HUD → Einstellungen → Leute & Anrufe → Sticker (Bilder liegen im Ordner „Sticker“ neben dem Programm;
eigene .png/.webp/.gif reinlegen – er macht daraus WhatsApp-Sticker 512×512).
Stopp: „Stopp“ / „hör auf mit den Stickern“ – oder einfach ein anderes Fenster anklicken: er schickt nur, solange
WhatsApp vorne ist (damit nie etwas in ein falsches Fenster eingefügt wird).
Vom Handy: kommt als Befehl {"type": "sticker", "to", "n"} (am Handy schon bestätigt).
"""
import base64
import ctypes
import io
import os
import re
import threading
import time

from pc_apps import base_dir

MAX = 1000
PAUSE = 0.55          # Sekunden zwischen zwei Stickern (schneller wirkt wie ein Bot)
EXT = (".png", ".webp", ".gif", ".jpg", ".jpeg")
SETTINGS = None       # vom Programm gesetzt: () -> Einstellungen
SAVE = None           # vom Programm gesetzt: (key, value)
SAY = None            # vom Programm gesetzt: Text ansagen
PENDING = None        # (to, n, bis)
RUN = {"on": False, "stop": False, "sent": 0, "n": 0, "to": ""}

_NUM = {"ein": 1, "einen": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "zehn": 10, "zwanzig": 20, "fünfzig": 50,
        "hundert": 100, "zweihundert": 200, "dreihundert": 300, "fünfhundert": 500, "tausend": 1000, "eintausend": 1000}


def folder() -> str:
    d = os.path.join(base_dir(), "Sticker")
    os.makedirs(d, exist_ok=True)
    return d


def files() -> list:
    """Bilder im Sticker-Ordner – auch gespeicherte WhatsApp-Sticker ohne Endung (das sind .webp)."""
    d = folder()
    out = []
    for f in os.listdir(d):
        p = os.path.join(d, f)
        if f.startswith(".") or not os.path.isfile(p):
            continue
        if f.lower().endswith(EXT) or "." not in f:
            out.append(f)
    # zuletzt hinzugefügte zuerst
    return sorted(out, key=lambda f: -os.path.getmtime(os.path.join(d, f)))


def chosen() -> str:
    s = (SETTINGS() or {}) if SETTINGS else {}
    c = s.get("sticker_wahl") or ""
    fs = files()
    return c if c in fs else (fs[0] if fs else "")


def listing(size: int = 96, limit: int = 60) -> dict:
    """Für die Auswahl im HUD (und kleiner fürs Handy): Name + Vorschaubild."""
    out = []
    for f in files()[:limit]:
        try:
            from PIL import Image
            im = Image.open(os.path.join(folder(), f))
            im.seek(0)
            im = im.convert("RGBA")
            im.thumbnail((size, size))
            b = io.BytesIO()
            im.save(b, "PNG")
            out.append({"name": f, "img": "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()})
        except Exception:
            out.append({"name": f, "img": ""})
    return {"items": out, "chosen": chosen(), "folder": folder(), "running": RUN.copy()}


def add_image(b64: str) -> dict:
    """Bild vom Handy (PNG, Base64) als neuen Sticker speichern und gleich auswählen."""
    raw = base64.b64decode(b64)
    if len(raw) > 3_000_000:
        return {"ok": False, "text": "Das Bild ist zu groß."}
    n = 1
    while os.path.exists(os.path.join(folder(), f"handy-{n}.png")):
        n += 1
    name = f"handy-{n}.png"
    with open(os.path.join(folder(), name), "wb") as f:
        f.write(raw)
    pick(name)
    return {"ok": True, "text": "Sticker ist am PC und ausgewählt."}


def pick(name: str) -> dict:
    if name not in files():
        return {"ok": False, "text": "Den Sticker gibt es nicht mehr."}
    if SAVE:
        SAVE("sticker_wahl", name)
    return {"ok": True, "text": f"Sticker „{os.path.splitext(name)[0]}“ ausgewählt."}


def open_folder() -> dict:
    os.startfile(folder())  # type: ignore[attr-defined]
    return {"ok": True, "text": "Ordner ist offen – leg Bilder (.png, .webp, .gif) rein und lade die Liste neu."}


def _sticker_file(name: str) -> str:
    """Als WhatsApp-Sticker vorbereiten: 512×512 .webp mit durchsichtigem Rand (wird einmal erzeugt)."""
    src = os.path.join(folder(), name)
    if name.lower().endswith(".webp"):
        return src
    d = os.path.join(folder(), ".fertig")
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, os.path.splitext(name)[0] + ".webp")
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return dst
    try:
        from PIL import Image
        im = Image.open(src)
        im.seek(0)
        im = im.convert("RGBA")
        im.thumbnail((512, 512))
        bg = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        bg.paste(im, ((512 - im.width) // 2, (512 - im.height) // 2), im)
        bg.save(dst, "WEBP")
        return dst
    except Exception:
        return src


def _clip_file(path: str):
    """Datei in die Zwischenablage legen (wie im Explorer „Kopieren“), damit Strg+V sie in WhatsApp einfügt."""
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    import struct
    names = (os.path.abspath(path) + "\0\0").encode("utf-16-le")
    head = struct.pack("Iiiii", 20, 0, 0, 0, 1)   # DROPFILES: pFiles=20, pt, fNC, fWide=1
    data = head + names
    h = k.GlobalAlloc(0x42, len(data))
    p = k.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    k.GlobalUnlock(h)
    for _ in range(20):
        if u.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Zwischenablage ist gerade belegt")
    try:
        u.EmptyClipboard()
        u.SetClipboardData(15, h)   # CF_HDROP
    finally:
        u.CloseClipboard()


def _wa_front() -> bool:
    try:
        import pc_windows
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pc_windows._process_name(pid.value).lower() in ("whatsapp.exe", "whatsapp.root.exe")
    except Exception:
        try:
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(ctypes.windll.user32.GetForegroundWindow(), buf, 256)
            return "whatsapp" in buf.value.lower()
        except Exception:
            return False


def _say(t: str):
    if SAY:
        try:
            SAY(t)
        except Exception:
            pass


def _open_chat(to: str) -> bool:
    import pyautogui
    import pc_messages
    names, hint = ["whatsapp.exe", "whatsapp.root.exe"], "whatsapp"
    hwnd, _ = pc_messages._front(names, hint, pc_messages._launch_whatsapp)
    if not hwnd:
        return False
    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.6)
    pc_messages._paste(to)
    time.sleep(1.5)
    pyautogui.press("enter")
    time.sleep(1.2)
    return True


def _run(to: str, n: int, name: str):
    import pyautogui
    RUN.update(on=True, stop=False, sent=0, n=n, to=to)
    try:
        path = _sticker_file(name)
        if not _open_chat(to):
            _say("WhatsApp ließ sich nicht öffnen – keine Sticker geschickt.")
            return
        for i in range(n):
            if RUN["stop"]:
                break
            if not _wa_front():   # anderes Fenster vorne: sofort aufhören, nie woanders einfügen
                _say(f"Du hast ein anderes Fenster geöffnet – ich höre auf. {RUN['sent']} Sticker sind raus.")
                return
            _clip_file(path)
            time.sleep(0.12)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.75 if i == 0 else 0.45)   # Vorschau abwarten
            if not _wa_front():
                continue
            pyautogui.press("enter")
            RUN["sent"] += 1
            time.sleep(PAUSE + (0.6 if (i + 1) % 25 == 0 else 0))
        _say(f"Fertig: {RUN['sent']} Sticker an {to}." if not RUN["stop"] else f"Gestoppt. {RUN['sent']} Sticker sind raus.")
    except Exception as e:
        _say(f"Sticker gingen nicht weiter: {e}")
    finally:
        RUN["on"] = False


def start(to: str, n: int) -> str:
    """Ohne Rückfrage loslegen (Handy hat schon gefragt)."""
    if RUN["on"]:
        return f"Ich schicke gerade schon Sticker an {RUN['to']} ({RUN['sent']} von {RUN['n']})."
    name = chosen()
    if not name:
        return "Du hast noch keinen Sticker. Leg einen in den Sticker-Ordner – Einstellungen → Leute & Anrufe → Sticker."
    n = max(1, min(MAX, int(n)))
    threading.Thread(target=_run, args=(to, n, name), daemon=True).start()
    return f"Los geht's: {n} Sticker an {to}. Sag „Stopp“, wenn ich aufhören soll – und bitte nicht wegklicken."


def _num(s: str):
    s = s.replace(".", "").strip()
    if s.isdigit():
        return int(s)
    return _NUM.get(s)


def handle(command: str):
    """Sprachbefehl -> Antwort oder None."""
    global PENDING
    low = command.strip(" .!?,").lower()
    if RUN["on"] and re.search(r"\b(stopp?|stop|hör auf|aufhören|abbrechen|genug)\b", low):
        RUN["stop"] = True
        return "Okay, ich höre auf."
    if PENDING:
        to, n, until = PENDING
        PENDING = None
        if time.time() < until and "sticker" not in low and len(low.split()) <= 7:
            if re.match(r"^(ja|jo|klar|mach|los|schick|sende|okay|ok|genau|bitte)\b", low):
                return start(to, n)
            if re.match(r"^(nein|nee|lass|abbrechen|stopp|doch nicht|lieber nicht)\b", low):
                return "Okay, keine Sticker."
    m = re.search(r"(?:schick|send|sende|spamm?)\w*\s+(?:(?:mal|bitte|doch|noch|jetzt|einfach|mir)\s+)*(\d[\d.]*|\w+)\s+sticker\s+"
                  r"(?:(?:in|an|zu)\s+(?:die|den|der)?\s*)?(?:whats\s?app[\s-]?)?(?:gruppe|chat)?\s*(.+)$", low)
    if not m:
        if "sticker" in low and re.search(r"\b(schick|send|spam)", low):
            return "Sag es so: „Schick 200 Sticker an TR9000“ – Zahl, dann „Sticker“, dann die Gruppe oder Person."
        return None
    n = _num(m.group(1))
    raw = command.strip(" .!?,")
    to = raw[m.start(2):m.end(2)] if len(raw) == len(low) else m.group(2)   # Groß-/Kleinschreibung wie gesagt
    to = re.sub(r"^(die|den|der)\s+", "", to, flags=re.I).strip(" .")
    to = re.sub(r"\s+(?:auf|über|per|bei)\s+whats\s?app$", "", to, flags=re.I)
    to = re.sub(r"\b([A-Za-zÄÖÜäöü]{1,4})\s+(\d{2,6})\b", r"\1\2", to)   # „TR 9000“ (so hört es die Spracherkennung) -> „TR9000“
    if not n or not to:
        return None
    from_phone = "vom handy" in low
    to = re.sub(r"^vom handy:?\s*", "", to, flags=re.I)
    if n > MAX:
        extra = f" Mehr als {MAX} auf einmal mache ich nicht – sonst sperrt WhatsApp deine Nummer."
        n = MAX
    else:
        extra = ""
    if not chosen():
        return "Du hast noch keinen Sticker ausgewählt. Einstellungen → Leute & Anrufe → Sticker."
    if from_phone:
        return start(to, n)
    PENDING = (to, n, time.time() + 120)
    return f"{n} Sticker „{os.path.splitext(chosen())[0]}“ an {to}?{extra} Soll ich?"
