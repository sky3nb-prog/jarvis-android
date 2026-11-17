"""
Schnelle Stimme am PC – läuft komplett auf dem PC (Piper, kostenlos, kein Internet nötig, ein Satz in ~0,2 s).
Wie die Stimme am Handy: keine Wartezeit auf einen Online-Dienst. Beim ersten Start lädt Jarvis Piper (≈ 25 MB) und
die deutsche Stimme „Thorsten“ (≈ 65 MB) einmal in den Ordner „piper“ neben dem Programm; danach geht alles offline.
Ein Piper-Prozess bleibt im Hintergrund geladen, damit jeder Satz sofort kommt.
"""
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
import zipfile

from pc_apps import base_dir

PIPER_ZIP = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
VOICE = "de_DE-thorsten-medium"
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/de/de_DE/thorsten/medium/"
NO_WINDOW = 0x08000000
STATE = {"status": "", "busy": False}
_proc = {"p": None, "lock": threading.Lock()}


def folder() -> str:
    return os.path.join(base_dir(), "piper")


def exe() -> str:
    return os.path.join(folder(), "piper", "piper.exe")


def model() -> str:
    return os.path.join(folder(), VOICE + ".onnx")


def ready() -> bool:
    return os.path.exists(exe()) and os.path.exists(model()) and os.path.exists(model() + ".json")


def _get(url: str, dst: str):
    tmp = dst + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-PC"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    os.replace(tmp, dst)


def install():
    """Einmal herunterladen (im Hintergrund beim Start). Ohne Erfolg bleibt die Online-Stimme."""
    if ready() or STATE["busy"]:
        return
    STATE["busy"] = True
    try:
        os.makedirs(folder(), exist_ok=True)
        if not os.path.exists(exe()):
            STATE["status"] = "lade Piper …"
            z = os.path.join(folder(), "piper.zip")
            _get(PIPER_ZIP, z)
            with zipfile.ZipFile(z) as zf:
                zf.extractall(folder())
            os.remove(z)
        for ext in (".onnx", ".onnx.json"):
            p = os.path.join(folder(), VOICE + ext)
            if not os.path.exists(p):
                STATE["status"] = "lade Stimme …"
                _get(VOICE_URL + VOICE + ext + "?download=true", p)
        STATE["status"] = "bereit" if ready() else "unvollständig"
        print("Schnelle Stimme (Piper):", STATE["status"])
    except Exception as e:
        STATE["status"] = f"Download ging nicht: {e}"
        print("Schnelle Stimme (Piper):", e)
    finally:
        STATE["busy"] = False


def install_async():
    threading.Thread(target=install, daemon=True, name="piper-install").start()


def _start(length_scale: float):
    p = _proc["p"]
    if p and p.poll() is None and getattr(p, "_ls", None) == length_scale:
        return p
    if p:
        try:
            p.kill()
        except Exception:
            pass
    out = os.path.join(folder(), "out")
    os.makedirs(out, exist_ok=True)
    p = subprocess.Popen([exe(), "--model", model(), "--json-input", "--output_dir", out, "--length_scale", f"{length_scale:.2f}",
                          "--sentence_silence", "0.15"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         cwd=os.path.dirname(exe()), creationflags=NO_WINDOW, text=True, encoding="utf-8", bufsize=1)
    p._ls = length_scale
    _proc["p"] = p
    return p


def synth(text: str, rate: int = 0, timeout: float = 8.0) -> str:
    """Text -> Pfad zu einer WAV. rate -10..10 (Sprechtempo wie in den Einstellungen)."""
    if not ready():
        raise RuntimeError("Piper ist noch nicht da")
    ls = max(0.6, min(1.4, 1.0 - rate * 0.035))
    out = os.path.join(folder(), "out", f"s{int(time.time() * 1000)}_{threading.get_ident() % 1000}.wav")
    with _proc["lock"]:
        p = _start(ls)
        p.stdin.write(json.dumps({"text": text, "output_file": out}, ensure_ascii=False) + "\n")
        p.stdin.flush()
        res = {}

        def rd():
            try:
                res["line"] = p.stdout.readline()
            except Exception as e:
                res["err"] = e
        t = threading.Thread(target=rd, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive() or not os.path.exists(out):
            try:
                p.kill()
            except Exception:
                pass
            _proc["p"] = None
            raise RuntimeError("Piper hat nicht geantwortet")
    _cleanup()
    return out


def _cleanup():
    d = os.path.join(folder(), "out")
    try:
        fs = sorted((os.path.join(d, f) for f in os.listdir(d)), key=os.path.getmtime)
        for f in fs[:-40]:
            os.remove(f)
    except Exception:
        pass


def warm():
    """Beim Start einmal laden, damit der erste Satz sofort kommt."""
    if ready():
        try:
            synth("Bereit.", 0, 20)
        except Exception as e:
            print("Piper-Start:", e)
