"""
Herunterladen für Jarvis.

- "Jarvis, lade das herunter" / "download das": nimmt den Link aus dem Satz oder aus der Zwischenablage (z. B. vorher
  im Browser kopiert) und speichert die Datei im Ordner Downloads. Wenn sie fertig ist, sagt er Bescheid.
- "Jarvis, lade Spotify herunter" / "installiere VLC": sucht das Programm bei winget (Windows-Paketverwaltung,
  ist in Windows 10/11 eingebaut), fragt nach ("Soll ich ... installieren?") und installiert es nach einem "Ja".
- "Jarvis, öffne meine Downloads": öffnet den Ordner.
"""

import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request

NOTIFY = None  # wird vom Programm gesetzt: NOTIFY(text) sagt etwas an, wenn ein Download fertig ist
_pending = {"what": None, "until": 0.0}
NO_WINDOW = 0x08000000

URL_RE = re.compile(r"https?://\S+", re.I)
WANTS = [
    re.compile(r"\b(?:lade?|lad)\s+(?:mir\s+|dir\s+|bitte\s+|mal\s+)*(.+?)\s+(?:her)?(?:r)?unter\b", re.I),
    re.compile(r"(?:kannst du|könntest du|bitte)?\s*(?:mir\s+)?(.+?)\s+(?:her)?(?:r)?unterladen\b", re.I),
    re.compile(r"\bdownload(?:e|en)?\b\s*(.*)", re.I),
    re.compile(r"\binstallier(?:e|en)?\s+(?:mir\s+|bitte\s+|mal\s+)*(.+)", re.I),
]
THIS = re.compile(r"^(?:das|des|die datei|den link|diese datei|diesen link|es|den download|das hier|die)$", re.I)
YES = {"ja", "jo", "jap", "klar", "mach", "mach das", "ja bitte", "bitte", "okay", "ok", "genau", "los"}
NO = {"nein", "nö", "ne", "lass", "lass es", "abbrechen", "stopp", "nicht"}


def downloads_dir() -> str:
    try:  # echter Downloads-Ordner (kann verschoben sein, z. B. auf D:)
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            path = winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
            path = os.path.expandvars(path)
            if os.path.isdir(path):
                return path
    except Exception:
        pass
    path = os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(path, exist_ok=True)
    return path


def _clipboard() -> str:
    """Text aus der Zwischenablage (direkt über Windows, ohne ein zweites Tk-Fenster)."""
    try:
        import ctypes
        from ctypes import wintypes

        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        u.GetClipboardData.restype = wintypes.HANDLE
        k.GlobalLock.restype = ctypes.c_void_p
        k.GlobalLock.argtypes = [wintypes.HANDLE]
        k.GlobalUnlock.argtypes = [wintypes.HANDLE]
        if not u.OpenClipboard(None):
            return ""
        try:
            h = u.GetClipboardData(13)  # CF_UNICODETEXT
            if not h:
                return ""
            ptr = k.GlobalLock(h)
            try:
                return ctypes.wstring_at(ptr) if ptr else ""
            finally:
                k.GlobalUnlock(h)
        finally:
            u.CloseClipboard()
    except Exception:
        return ""


def _say(text: str):
    print(text)
    if NOTIFY:
        try:
            NOTIFY(text)
        except Exception as e:
            print(f"Ansage fehlgeschlagen: {e}")


def _filename(url: str, resp) -> str:
    cd = resp.headers.get("Content-Disposition", "") or ""
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd, re.I)
    name = urllib.parse.unquote(m.group(1)) if m else urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(resp.url).path))
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip(" .") or "download"
    if "." not in name:
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0]
        ext = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "application/zip": ".zip",
               "text/html": ".html", "video/mp4": ".mp4", "audio/mpeg": ".mp3"}.get(ctype, "")
        name += ext
    return name


def download(url: str):
    """Lädt im Hintergrund in den Downloads-Ordner und sagt Bescheid, wenn es fertig ist."""
    def run():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Jarvis"})
            with urllib.request.urlopen(req, timeout=30) as r:
                name = _filename(url, r)
                folder = downloads_dir()
                path = os.path.join(folder, name)
                base, ext = os.path.splitext(path)
                n = 1
                while os.path.exists(path):
                    path = f"{base} ({n}){ext}"
                    n += 1
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk)
                os.replace(tmp, path)
            mb = os.path.getsize(path) / 1e6
            _say(f"Fertig: {os.path.basename(path)} liegt in deinen Downloads ({mb:.1f} MB).")
        except Exception as e:
            _say(f"Der Download hat nicht geklappt: {e}")
    threading.Thread(target=run, daemon=True).start()


# --- Programme über winget -------------------------------------------------------------
def winget_search(name: str):
    """Erster Treffer bei winget: (Name, Id) oder None."""
    try:
        out = subprocess.run(["winget", "search", name, "--accept-source-agreements", "--disable-interactivity"],
                             capture_output=True, timeout=40, creationflags=NO_WINDOW)
        text = out.stdout.decode("utf-8", "ignore")
    except FileNotFoundError:
        return "kein-winget"
    except Exception:
        return None
    lines = [l.rstrip() for l in text.splitlines()]
    for i, line in enumerate(lines):
        if re.match(r"^-{5,}", line.strip()):
            for row in lines[i + 1:]:
                parts = re.split(r"\s{2,}", row.strip())
                if len(parts) >= 2 and "." in parts[1]:
                    return parts[0], parts[1]
            break
    return None


def install(name: str, pkg_id: str):
    def run():
        try:
            out = subprocess.run(["winget", "install", "--id", pkg_id, "-e", "--silent", "--accept-package-agreements",
                                  "--accept-source-agreements", "--disable-interactivity"],
                                 capture_output=True, timeout=1800, creationflags=NO_WINDOW)
            if out.returncode == 0:
                _say(f"{name} ist installiert.")
            else:
                msg = out.stdout.decode("utf-8", "ignore").strip().splitlines()[-1:] or [""]
                _say(f"{name} konnte ich nicht installieren. {msg[0][:120]}")
        except Exception as e:
            _say(f"Die Installation von {name} hat nicht geklappt: {e}")
    threading.Thread(target=run, daemon=True).start()


def awaiting() -> bool:
    return _pending["what"] is not None and time.time() < _pending["until"]


def handle(text: str):
    low = text.lower().strip(" .,!?")
    # Antwort auf die Rückfrage "Soll ich ... installieren?"
    if awaiting():
        name, pkg = _pending["what"]
        _pending["what"] = None
        if low in YES or (low.startswith("ja") and len(low.split()) <= 3):
            install(name, pkg)
            return f"Okay, ich installiere {name}. Das kann ein paar Minuten dauern, ich sag Bescheid."
        if low in NO or low.startswith("nein"):
            return "Okay, ich lasse es."
    if re.search(r"(öffne|zeig).*(download|herunterladen)", low):
        os.startfile(downloads_dir())  # noqa: S606 (nur Windows)
        return "Hier sind deine Downloads."
    m = next((r.search(text) for r in WANTS if r.search(text)), None)
    if not m:
        return None
    what = (m.group(1) or "").strip(" .,!?")
    what = re.sub(r"^(?:kannst du|könntest du|jarvis,?)\s+", "", what, flags=re.I)
    url = URL_RE.search(text)
    if url or not what or THIS.match(what):
        link = url.group(0) if url else ""
        if not link:
            clip = _clipboard().strip()
            hit = URL_RE.search(clip)
            link = hit.group(0) if hit else ""
        if not link:
            return ("Ich habe keinen Link gefunden. Kopier den Download-Link im Browser (Rechtsklick, Link-Adresse "
                    "kopieren) und sag dann nochmal: lade das herunter.")
        download(link)
        host = urllib.parse.urlparse(link).netloc.replace("www.", "")
        return f"Ich lade das von {host} in deine Downloads und sag Bescheid, wenn es fertig ist."
    # ein Programm
    what = re.sub(r"^(?:das programm|die app|das spiel|mir|bitte)\s+", "", what, flags=re.I)
    hit = winget_search(what)
    if hit == "kein-winget":
        return "Auf deinem PC fehlt winget, die Windows-Paketverwaltung. Installier im Microsoft Store den App-Installer."
    if not hit:
        return f"Ich habe {what} bei winget nicht gefunden. Sag mir den genauen Namen oder kopier den Download-Link."
    name, pkg = hit
    _pending.update(what=(name, pkg), until=time.time() + 25)
    return f"Ich habe {name} gefunden ({pkg}). Soll ich es installieren? Sag ja oder nein."
