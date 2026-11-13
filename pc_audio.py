"""
Klang und Stimme für den PC-Assistenten (Windows).

- play_chime(): kurzer, angenehmer Aktivierungs-Sound (wird selbst erzeugt, keine Datei nötig)
- Ausgabegerät: Stimme und Wecksound können auf ein bestimmtes Gerät gehen, z. B. einen Kanal
  von Elgato Wave Link (OUTPUT_DEVICE). Online-Stimmen brauchen dafür zusätzlich: pip install soundfile
- speak(text): spricht Text. Zwei Stimmen-Arten:
    * Online-Stimme (Paket "edge-tts", kostenlos, kein Schlüssel): natürliche neuronale Stimmen,
      z. B. ruhig und männlich im Stil eines Butlers. Der Text geht dafür an Microsofts
      Sprachdienst. Fertige Sätze werden zwischengespeichert, so wird es schneller.
    * Windows-Stimme (offline, immer vorhanden): bevorzugt eine deutsche Männerstimme.
  Im Modus "auto" nimmt er die Online-Stimme und fällt bei Problemen auf Windows zurück.
"""

import hashlib
import io
import re
import os
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np

import pc_cancel

# --- Einstellungen (werden aus einstellungen.json gesetzt) ---------------------
CHIME_VOLUME = 0.45  # 0.0 bis 1.0
VOICE_ENGINE = "auto"  # "eleven" (ElevenLabs), "auto", "edge" oder "windows"
EDGE_VOICE = "de-DE-KillianNeural"
WINDOWS_VOICE = ""  # leer = automatisch
VOICE_PITCH = -3  # -10 (tiefer) bis 10 (höher)
VOICE_RATE = 0  # -10 (langsam) bis 10 (schnell)
ON_CHUNK = None  # vom Programm gesetzt: bekommt jeden Satz, kurz bevor er gesprochen wird (Globus fliegt passend)
VOICE_VOLUME = 100  # eigene Lautstärke von Jarvis' Stimme in Prozent (unabhängig von der Windows-Lautstärke)
OUTPUT_DEVICE = None  # None = Windows-Standard, sonst der Name des Ausgabegeräts

# Auswahl für die Einstellungen: (Anzeigename, Stimmen-Kennung)
EDGE_VOICES = [
    ("Killian – ruhig, männlich (Deutsch)", "de-DE-KillianNeural"),
    ("Conrad – warm, männlich (Deutsch)", "de-DE-ConradNeural"),
    ("Florian – mehrsprachig, männlich", "de-DE-FlorianMultilingualNeural"),
    ("Ryan – britisch, männlich (Jarvis-Stil, spricht Deutsch mit Akzent)", "en-GB-RyanNeural"),
    ("Thomas – britisch, männlich (spricht Deutsch mit Akzent)", "en-GB-ThomasNeural"),
    ("Andrew – mehrsprachig, tief, ruhig (Deutsch mit leichtem Akzent)", "en-US-AndrewMultilingualNeural"),
    ("Brian – mehrsprachig, sachlich (Deutsch mit leichtem Akzent)", "en-US-BrianMultilingualNeural"),
    ("Guy – tief, männlich (englisch)", "en-US-GuyNeural"),
    ("Sonia – britisch, weiblich (englisch)", "en-GB-SoniaNeural"),
    ("Katja – weiblich (Deutsch)", "de-DE-KatjaNeural"),
    ("Amala – weiblich (Deutsch)", "de-DE-AmalaNeural"),
]

SAMPLE_RATE = 44100
NO_WINDOW = 0x08000000
_warned = False
_warned_sf = False
_UNSET = object()

# Einträge, die nur Dubletten des Standardgeräts sind
_SKIP = ("soundmapper", "sound mapper", "primärer sound", "primary sound")


# --- Audio-Geräte ----------------------------------------------------------------------
def _devices():
    import sounddevice as sd

    return sd, list(sd.query_devices())


def _default_hostapi(sd, devs, kind: str):
    try:
        idx = sd.default.device[1 if kind == "output" else 0]
        if idx is not None and int(idx) >= 0:
            return devs[int(idx)]["hostapi"]
    except Exception:
        pass
    return None


def list_devices(kind: str) -> list:
    """Namen der Geräte ('input' = Mikrofone, 'output' = Ausgaben), ohne Dubletten anderer Audio-Schnittstellen."""
    try:
        sd, devs = _devices()
    except Exception:
        return []
    chan = "max_input_channels" if kind == "input" else "max_output_channels"
    host = _default_hostapi(sd, devs, kind)
    names = []
    for d in devs:
        if d[chan] <= 0 or (host is not None and d["hostapi"] != host):
            continue
        if any(x in d["name"].lower() for x in _SKIP):
            continue
        if d["name"] not in names:
            names.append(d["name"])
    return names


def device_name(index) -> str:
    """Name zu einer Gerätenummer (für ältere Einstellungen, die eine Nummer gespeichert haben)."""
    try:
        sd, devs = _devices()
        return devs[int(index)]["name"]
    except Exception:
        return ""


def resolve_device(name, kind: str):
    """Gerätenummer zu einem gespeicherten Namen. None = Windows-Standard."""
    if name is None or name == "":
        return None
    if isinstance(name, int):
        return name
    try:
        sd, devs = _devices()
    except Exception:
        return None
    chan = "max_input_channels" if kind == "input" else "max_output_channels"
    host = _default_hostapi(sd, devs, kind)
    cands = [(i, d) for i, d in enumerate(devs) if d[chan] > 0]
    low = str(name).lower()
    tests = (
        lambda n: n == name,
        lambda n: n.lower().startswith(low) or low.startswith(n.lower()),
        lambda n: low in n.lower(),
    )
    for test in tests:
        hits = [(i, d) for i, d in cands if test(d["name"])]
        if hits:
            hits.sort(key=lambda t: t[1]["hostapi"] != host)  # Standard-Schnittstelle zuerst
            return hits[0][0]
    return None


def read_wav(src):
    """16-Bit-WAV (Pfad oder Datei-Objekt) -> (float32-Array, Abtastrate)."""
    with wave.open(src, "rb") as w:
        ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("nur 16-Bit-WAV wird unterstützt")
    arr = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    return (arr.reshape(-1, ch) if ch > 1 else arr), rate


def _play_array(data, rate, device, blocking: bool):
    import sounddevice as sd

    vol = max(0.05, min(1.0, VOICE_VOLUME / 100.0))
    if vol < 0.999:
        data = data * vol
    sd.play(data, rate, device=device, blocking=blocking)


# --- Wecksound -----------------------------------------------------------------
def make_chime() -> bytes:
    """Steigender Dreiklang (E5 - H5 - E6) mit weichem Ausklang, ca. 0,6 s."""
    notes = [(659.25, 0.00), (987.77, 0.08), (1318.51, 0.16)]
    t = np.arange(int(SAMPLE_RATE * 0.6)) / SAMPLE_RATE
    y = np.zeros_like(t)
    for freq, start in notes:
        mask = t >= start
        tt = t[mask] - start
        env = np.exp(-tt * 8.0) * (1.0 - np.exp(-tt * 500.0))  # schnell ein, weich aus
        tone = (
            np.sin(2 * np.pi * freq * tt)
            + 0.30 * np.sin(2 * np.pi * 2 * freq * tt)
            + 0.10 * np.sin(2 * np.pi * 3 * freq * tt)
        )
        y[mask] += tone * env
    y = y / max(1e-9, float(np.max(np.abs(y)))) * CHIME_VOLUME
    fade = int(SAMPLE_RATE * 0.02)  # kurzes Ausblenden am Ende gegen Knacken
    y[-fade:] *= np.linspace(1.0, 0.0, fade)
    pcm = (y * 32767).astype("<i2").tobytes()

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


_CHIME = None
_CHIME_ARR = None


def reset_chime():
    """Wecksound beim nächsten Mal neu erzeugen (z. B. nach geänderter Lautstärke)."""
    global _CHIME, _CHIME_ARR
    _CHIME = _CHIME_ARR = None


def play_chime(device=_UNSET):
    """Spielt den Sound im Hintergrund ab (blockiert nicht)."""
    global _CHIME, _CHIME_ARR
    name = OUTPUT_DEVICE if device is _UNSET else device
    idx = resolve_device(name, "output") if name else None
    try:
        if _CHIME is None:
            _CHIME = make_chime()
        if idx is not None:
            if _CHIME_ARR is None:
                _CHIME_ARR = read_wav(io.BytesIO(_CHIME))
            _play_array(_CHIME_ARR[0], _CHIME_ARR[1], idx, False)
            return
        import winsound

        winsound.PlaySound(_CHIME, winsound.SND_MEMORY | winsound.SND_ASYNC)
    except Exception:
        pass


# --- Online-Stimme (edge-tts) ---------------------------------------------------------
def _cache_dir() -> str:
    folder = os.path.join(tempfile.gettempdir(), "jarvis_tts")
    os.makedirs(folder, exist_ok=True)
    return folder


def _trim_cache(folder: str, keep: int = 150):
    try:
        files = sorted((os.path.join(folder, f) for f in os.listdir(folder)), key=os.path.getmtime)
        for old in files[: max(0, len(files) - keep)]:
            os.remove(old)
    except Exception:
        pass


def _edge_file(text: str, voice: str, pitch: int, rate: int):
    """Erzeugt (oder holt aus dem Zwischenspeicher) eine mp3-Datei mit dem gesprochenen Text."""
    import asyncio

    import edge_tts

    folder = _cache_dir()
    key = hashlib.sha1(f"{voice}|{pitch}|{rate}|{text}".encode("utf-8")).hexdigest()[:24]
    path = os.path.join(folder, key + ".mp3")
    if os.path.exists(path) and os.path.getsize(path) > 500:
        return path

    async def generate():
        try:
            communicate = edge_tts.Communicate(text, voice, rate=f"{int(rate) * 5:+d}%", pitch=f"{int(pitch) * 3:+d}Hz",
                                               connect_timeout=5, receive_timeout=20)
        except TypeError:  # ältere edge-tts-Version
            communicate = edge_tts.Communicate(text, voice, rate=f"{int(rate) * 5:+d}%", pitch=f"{int(pitch) * 3:+d}Hz")
        await communicate.save(path)

    asyncio.run(generate())
    _trim_cache(folder)
    return path if os.path.exists(path) and os.path.getsize(path) > 500 else None


MCI_ALIAS = f"jarvis{os.getpid()}"
_PS_PROC = None


def _play_mp3(path: str) -> bool:
    """Spielt eine mp3 über die Windows-Medienfunktion ab und wartet, bis sie fertig ist."""
    import ctypes

    winmm = ctypes.windll.winmm
    alias = MCI_ALIAS
    if winmm.mciSendStringW(f'open "{path}" type mpegvideo alias {alias}', None, 0, None) != 0:
        return False
    try:
        winmm.mciSendStringW(f"setaudio {alias} volume to {int(max(5, min(100, VOICE_VOLUME)) * 10)}", None, 0, None)
        return winmm.mciSendStringW(f"play {alias} wait", None, 0, None) == 0
    finally:
        winmm.mciSendStringW(f"close {alias}", None, 0, None)


def _play_mp3_device(path: str, idx: int):
    import soundfile as sf

    data, rate = sf.read(path, dtype="float32")
    _play_array(data, rate, idx, True)


def _chunks(text: str, first_max: int = 70) -> list:
    """Teilt den Text in Sätze. Der erste Teil ist kurz, damit das Sprechen schnell losgeht, der Rest wird währenddessen erzeugt."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?:;])\s+|\n+", text.strip()) if p.strip()]
    out = []
    for p in parts:
        if out and len(out[-1]) < 40:  # sehr kurze Stücke zusammenhängen
            out[-1] += " " + p
        else:
            out.append(p)
    if out and len(out[0]) > first_max:  # langen ersten Satz am Komma teilen
        m = re.search(r",\s", out[0][40:first_max + 40])
        if m:
            cut = 40 + m.end()
            out[0:1] = [out[0][:cut].strip(), out[0][cut:].strip()]
    return out or [text]


def _speak_edge(text: str, voice: str, pitch: int, rate: int, idx=None) -> bool:
    """Erzeugt die Sprache satzweise im Hintergrund und spielt sie ab, sobald der erste Satz fertig ist."""
    global _warned, _warned_sf
    import queue

    gen = pc_cancel.GEN
    chunks = _chunks(text)
    results: "queue.Queue" = queue.Queue()
    t0 = time.time()

    def producer():
        # bis zu drei Sätze gleichzeitig erzeugen (in der richtigen Reihenfolge abspielen) -> keine Pausen dazwischen
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = [ex.submit(_edge_file, c, voice, pitch, rate) for c in chunks]
            for f in futs:
                if pc_cancel.changed(gen):
                    for g in futs:
                        g.cancel()
                    break
                try:
                    results.put(("ok", (chunks[futs.index(f)], f.result())))
                except BaseException as e:  # ImportError, Netzwerk ...
                    for g in futs:
                        g.cancel()
                    results.put(("err", e))
                    return
        results.put(("end", None))

    threading.Thread(target=producer, daemon=True).start()
    played = False
    try:
        while True:
            kind, val = results.get()
            if kind == "end":
                return True
            if kind == "err":
                raise val
            ctext, val = val
            if not val:
                return played
            if pc_cancel.changed(gen):
                return True
            if ON_CHUNK:
                try:
                    ON_CHUNK(ctext)
                except Exception:
                    pass
            if not played:
                print(f"Zeit: Stimme für den ersten Satz nach {time.time() - t0:.1f} s bereit")
            played = True
            if idx is not None:
                try:
                    _play_mp3_device(val, idx)
                    continue
                except ImportError:
                    if not _warned_sf:
                        print("Für die Ausgabe-Auswahl bei Online-Stimmen fehlt: pip install soundfile (spiele auf dem Standardgerät)")
                        _warned_sf = True
                except Exception as e:
                    print(f"Ausgabegerät nicht nutzbar ({e}), spiele auf dem Standardgerät")
                    idx = None
            _play_mp3(val)
    except ImportError:
        if not _warned:
            print("Online-Stimme nicht installiert (pip install edge-tts), nehme die Windows-Stimme.")
            _warned = True
    except Exception as e:
        if not _warned:
            print(f"Online-Stimme nicht erreichbar ({e}), nehme die Windows-Stimme.")
            _warned = True
    return played  # schon etwas gesprochen: nicht noch einmal mit der Windows-Stimme von vorn


# --- Windows-Stimme (offline) ----------------------------------------------------------
_PS_SCRIPT = ";".join([
    "Add-Type -AssemblyName System.Speech",
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
    "$all = @($s.GetInstalledVoices() | Where-Object { $_.Enabled })",
    "$v = $null",
    "if ($env:JARVIS_VOICE) { $v = $all | Where-Object { $_.VoiceInfo.Name -eq $env:JARVIS_VOICE } | Select-Object -First 1 }",
    "if (-not $v) { $v = $all | Where-Object { $_.VoiceInfo.Culture.Name -like 'de*' -and $_.VoiceInfo.Gender -eq 'Male' } | Select-Object -First 1 }",
    "if (-not $v) { $v = $all | Where-Object { $_.VoiceInfo.Culture.Name -like 'de*' } | Select-Object -First 1 }",
    "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }",
    "if ($env:JARVIS_WAV) { $s.SetOutputToWaveFile($env:JARVIS_WAV) }",
    "$s.Rate = [int]$env:JARVIS_RATE",
    "if ($env:JARVIS_VOL) { $s.Volume = [int]$env:JARVIS_VOL }",
    "$t = [System.Security.SecurityElement]::Escape($env:JARVIS_TEXT)",
    "$ssml = '<speak version=\"1.0\" xml:lang=\"de-DE\"><prosody pitch=\"' + $env:JARVIS_PITCH + '\">' + $t + '</prosody></speak>'",
    "try { $s.SpeakSsml($ssml) } catch { $s.Speak($env:JARVIS_TEXT) }",
    "$s.Dispose()",
])


def _speak_windows(text: str, voice: str, pitch: int, rate: int, idx=None):
    gen = pc_cancel.GEN
    env = dict(os.environ, JARVIS_TEXT=text, JARVIS_RATE=str(int(rate)),
               JARVIS_VOICE=voice or "", JARVIS_PITCH=f"{int(pitch) * 4:+d}%",
               JARVIS_VOL=str(int(max(5, min(100, VOICE_VOLUME)))))
    wav = None
    if idx is not None:  # erst in eine Datei sprechen, dann auf dem gewählten Gerät abspielen
        wav = os.path.join(_cache_dir(), f"win_{os.getpid()}.wav")
        env["JARVIS_WAV"] = wav
    global _PS_PROC
    try:
        _PS_PROC = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
                                    env=env, creationflags=NO_WINDOW)
        _PS_PROC.wait(timeout=60)
    except Exception:
        pass
    if wav and not pc_cancel.changed(gen):
        try:
            data, rate_hz = read_wav(wav)
            _play_array(data, rate_hz, idx, True)
        except Exception as e:
            print(f"Ausgabegerät nicht nutzbar ({e})")
        finally:
            try:
                os.remove(wav)
            except Exception:
                pass


_VOICES = None


def windows_voices() -> list:
    """Namen der installierten Windows-Stimmen (wird einmal abgefragt und gemerkt)."""
    global _VOICES
    if _VOICES is None:
        try:
            ps = ("Add-Type -AssemblyName System.Speech; "
                  "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() "
                  "| Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name }")
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                               capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
            _VOICES = [line.strip() for line in r.stdout.splitlines() if line.strip()]
        except Exception:
            _VOICES = []
    return _VOICES


# --- Sprechen -------------------------------------------------------------------------------
_SPEAK_LOCK = threading.Lock()
_speaking = False
_last_end = 0.0


def busy_recently(grace: float = 1.2) -> bool:
    """True, solange gesprochen wird oder gerade erst gesprochen wurde (dann hört das Mikrofon sich selbst)."""
    return _speaking or (time.time() - _last_end) < grace


def speak(*args, **kwargs):
    """Spricht den Text und wartet, bis er fertig ist. Mehrere Aufrufe laufen nacheinander, nicht übereinander.
    Parameter: text, engine, edge_voice, windows_voice, pitch, rate, output (überschreiben die Einstellungen,
    z. B. für "Stimme testen"; output = Name des Ausgabegeräts, None = Windows-Standard)."""
    global _speaking, _last_end
    with _SPEAK_LOCK:
        _speaking = True
        try:
            _speak_impl(*args, **kwargs)
        finally:
            _speaking = False
            _last_end = time.time()


_eleven_warned = ""


_eleven_off_until = 0.0  # Guthaben leer / Schlüssel ungültig: ElevenLabs eine Weile gar nicht erst versuchen


def _speak_eleven(text, idx, rate, key, voice, model) -> bool:
    """ElevenLabs. False = hat nicht geklappt, dann übernimmt die Online-Stimme."""
    global _eleven_warned, _eleven_off_until
    import pc_eleven

    if time.time() < _eleven_off_until and not key:  # spart bei jedem Satz die Sekunden für den Fehlversuch
        return False
    try:
        return pc_eleven.speak(text, idx, key=key, voice=voice, model=model, rate=rate)
    except Exception as e:
        msg = str(e)
        if re.search(r"guthaben|aufgebraucht|quota|credits|ungültig|bezahlt|erlaubnis|401|402", msg, re.I):
            _eleven_off_until = time.time() + 3 * 3600
            print("ElevenLabs pausiert für 3 Stunden (Guthaben leer oder Schlüssel ungültig) – nehme die Online-Stimme.")
        if msg != _eleven_warned:  # dieselbe Meldung nicht bei jedem Satz wiederholen
            print(f"ElevenLabs: {msg} Nehme die Online-Stimme.")
            _eleven_warned = msg
        pc_eleven.LAST_ERROR = msg
        return False


def _speak_impl(text: str, engine=None, edge_voice=None, windows_voice=None, pitch=None, rate=None, output=_UNSET,
                eleven_key=None, eleven_voice=None, eleven_model=None):
    if not text or not text.strip():
        return
    engine = engine or VOICE_ENGINE
    edge_voice = edge_voice or EDGE_VOICE
    windows_voice = WINDOWS_VOICE if windows_voice is None else windows_voice
    pitch = VOICE_PITCH if pitch is None else pitch
    rate = VOICE_RATE if rate is None else rate
    out_name = OUTPUT_DEVICE if output is _UNSET else output
    idx = resolve_device(out_name, "output") if out_name else None
    gen = pc_cancel.GEN
    if engine == "eleven":
        if _speak_eleven(text, idx, rate, eleven_key, eleven_voice, eleven_model):
            return
        if pc_cancel.changed(gen):
            return
        engine = "auto"  # Ersatz: Online-Stimme, sonst Windows
    if engine in ("auto", "edge") and _speak_edge(text, edge_voice, pitch, rate, idx):
        return
    if pc_cancel.changed(gen):  # abgebrochen: nicht mit der anderen Stimme von vorn anfangen
        return
    _speak_windows(text, windows_voice, pitch, rate, idx)


def stop_playback():
    """Stoppt sofort alles, was gerade gesprochen oder abgespielt wird (Abbrechen per X)."""
    try:
        import sounddevice as sd

        sd.stop()
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.winmm.mciSendStringW(f"stop {MCI_ALIAS}", None, 0, None)
    except Exception:
        pass
    try:
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
    proc = _PS_PROC
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass


pc_cancel.HOOKS.append(stop_playback)
