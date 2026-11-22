"""
ffmpeg nur für eine Sache: aus der Piper-WAV-Datei eine echte WhatsApp-Sprachnachricht machen (.ogg/Opus statt .wav).
WhatsApp erkennt eine Datei nur dann als Sprachnachricht (Wellenform, Play-Knopf, Mikrofon-Symbol) wenn sie als
Ogg/Opus vorliegt - alles andere (wav, mp3) kommt als normaler Audio-Dateianhang an.

Wird genau wie Piper beim ersten Gebrauch einmal heruntergeladen (≈ 25 MB, offizieller ffmpeg-Build von GitHub)
und liegt danach im selben „piper“-Ordner. Kein Internet beim eigentlichen Umwandeln nötig.
"""
import os
import shutil
import subprocess
import threading
import time
import urllib.request
import zipfile

from pc_apps import base_dir

FFMPEG_ZIP = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip"
NO_WINDOW = 0x08000000
STATE = {"status": "", "busy": False}


def folder() -> str:
    la = os.environ.get("LOCALAPPDATA") or ""
    if la and la.isascii():
        return os.path.join(la, "JarvisFfmpeg")
    return os.path.join(base_dir(), "ffmpeg")


def exe() -> str:
    return os.path.join(folder(), "ffmpeg.exe")


def ready() -> bool:
    return os.path.exists(exe())


def install():
    """Einmalig laden (klein: nur die geteilten DLLs statt des großen „static“-Pakets)."""
    while STATE["busy"]:
        time.sleep(0.5)
    if ready():
        return
    STATE["busy"] = True
    try:
        os.makedirs(folder(), exist_ok=True)
        STATE["status"] = "lade ffmpeg …"
        z = os.path.join(folder(), "ffmpeg.zip")
        tmp = z + ".part"
        req = urllib.request.Request(FFMPEG_ZIP, headers={"User-Agent": "Jarvis-PC"})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        os.replace(tmp, z)
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                b = os.path.basename(n)
                if b.lower() in ("ffmpeg.exe",) or b.lower().endswith(".dll"):
                    with zf.open(n) as src, open(os.path.join(folder(), b), "wb") as dst:
                        shutil.copyfileobj(src, dst)
        os.remove(z)
        STATE["status"] = "fertig" if ready() else "ffmpeg.exe fehlte im Paket"
    except Exception as e:
        STATE["status"] = f"ging nicht ({e})"
    finally:
        STATE["busy"] = False


def to_voice_note(wav_path: str) -> str:
    """wav -> ogg/Opus (16kHz, mono, ~24kbit/s - genau das Format, das WhatsApp als Sprachnachricht anzeigt).
    Gibt bei Erfolg den .ogg-Pfad zurück, sonst (ffmpeg fehlt/Fehler) unverändert den .wav-Pfad."""
    if not ready():
        install()
    if not ready():
        return wav_path
    out = os.path.splitext(wav_path)[0] + ".ogg"
    try:
        subprocess.run([exe(), "-y", "-i", wav_path, "-c:a", "libopus", "-b:a", "24k", "-ar", "16000", "-ac", "1", out],
                       creationflags=NO_WINDOW, capture_output=True, timeout=30, check=True)
        return out if os.path.exists(out) else wav_path
    except Exception:
        return wav_path


def install_async():
    threading.Thread(target=install, daemon=True).start()
