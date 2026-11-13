"""
ElevenLabs-Stimme für Jarvis: sehr natürlich klingende Sprache.

Die Sprache wird "gestreamt": ElevenLabs schickt den Ton Stück für Stück, und Jarvis spielt das erste Stück
schon ab, während der Rest noch erzeugt wird. So fängt er meist nach weniger als einer Sekunde an zu sprechen.

Den Schlüssel bekommst du auf elevenlabs.io unter Entwickler -> API-Schlüssel. Er wird in den Jarvis-Einstellungen
(Tab "Stimme") eingetragen und mit Windows verschlüsselt gespeichert.
Klappt etwas nicht (kein Internet, Guthaben leer, Stimme nicht erlaubt), nimmt Jarvis automatisch die Online-Stimme.
"""

import json
import time
import urllib.error
import urllib.request

import numpy as np

import pc_cancel

API = "https://api.elevenlabs.io/v1"

# Werden aus den Einstellungen gesetzt
KEY = ""
VOICE_ID = "onwK4e9ZLuTAKqWW03F9"
MODEL = "eleven_flash_v2_5"

# Fertige Stimmen von ElevenLabs (funktionieren auch im kostenlosen Tarif). Mit "Stimmen laden" kommen alle dazu,
# die in deinem ElevenLabs-Konto unter "Meine Stimmen" liegen.
DEFAULT_VOICES = [
    ("Daniel – britisch, ruhig, souverän (Jarvis-Stil)", "onwK4e9ZLuTAKqWW03F9"),
    ("George – britisch, warm, erzählend", "JBFqnCBsd6RMkjVDRZzb"),
    ("Brian – tief, ruhig", "nPczCjzI2devNBz1zQrb"),
    ("Bill – älter, vertrauenswürdig", "pqHfZKP75CvOlQylNhV4"),
    ("Adam – tief, klar", "pNInz6obpgDQGcFmaJgB"),
    ("Charlie – locker, jung", "IKne3meq5aSn9XLyUdCD"),
    ("Alice – britisch, weiblich", "Xb7hH8MSUJpSbSDYk0k2"),
]
MODELS = [
    ("Flash v2.5 – am schnellsten, halber Verbrauch (empfohlen)", "eleven_flash_v2_5"),
    ("Multilingual v2 – beste Qualität, etwas langsamer", "eleven_multilingual_v2"),
]
RATE = 22050  # Abtastrate des Tons, den ElevenLabs schickt (16-Bit-PCM, mono)
LAST_ERROR = ""


class ElevenError(Exception):
    pass


def _speed(rate: int) -> float:
    """Sprechtempo aus den Einstellungen (-10 bis 10) -> ElevenLabs-Geschwindigkeit (0,7 bis 1,2)."""
    return max(0.7, min(1.2, 1.0 + int(rate) * 0.02))


def _request(text: str, key: str, voice: str, model: str, rate: int):
    body = {
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True,
                           "speed": _speed(rate)},
    }
    if "flash_v2_5" in model or "turbo_v2_5" in model:
        body["language_code"] = "de"  # sorgt für sauberes Deutsch
    url = f"{API}/text-to-speech/{voice}/stream?output_format=pcm_{RATE}&optimize_streaming_latency=2"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/pcm"})
    try:
        return urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            detail = json.loads(raw).get("detail")
            msg = detail.get("message") if isinstance(detail, dict) else str(detail)
        except Exception:
            msg = raw[:200]
        raise ElevenError(explain(e.code, msg or "")) from None
    except (urllib.error.URLError, OSError) as e:
        raise ElevenError(f"ElevenLabs nicht erreichbar ({getattr(e, 'reason', e)})") from None


def explain(code: int, msg: str) -> str:
    low = msg.lower()
    if code == 401:
        if "permission" in low or "missing" in low:
            return "Dem ElevenLabs-Schlüssel fehlt die Erlaubnis für Text zu Sprache."
        return "Der ElevenLabs-Schlüssel ist ungültig."
    if code == 402 or "paid" in low or "subscription" in low or "library" in low:
        return f"Diese Stimme gibt es nur im bezahlten ElevenLabs-Tarif. Nimm eine der fertigen Stimmen. ({msg[:100]})"
    if "quota" in low or "credits" in low:
        return "Das ElevenLabs-Guthaben für diesen Monat ist aufgebraucht."
    if code == 404 or "voice" in low and "not" in low:
        return "Diese ElevenLabs-Stimme gibt es nicht (mehr)."
    if code == 429:
        return "ElevenLabs ist gerade überlastet oder zu viele Anfragen."
    return f"ElevenLabs-Fehler {code}: {msg[:120]}"


def _open_stream(sd, idx):
    """Öffnet die Ausgabe. Kann das Gerät 22050 Hz nicht, wird auf seine eigene Rate umgerechnet."""
    try:
        return sd.RawOutputStream(samplerate=RATE, channels=1, dtype="int16", device=idx), RATE
    except Exception:
        dev_rate = int(sd.query_devices(idx if idx is not None else sd.default.device[1], "output")["default_samplerate"])
        return sd.RawOutputStream(samplerate=dev_rate, channels=1, dtype="int16", device=idx), dev_rate


def _convert(pcm: bytes, rate_to: int) -> bytes:
    if rate_to == RATE or not pcm:
        return pcm
    a = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    n = int(len(a) * rate_to / RATE)
    out = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a)
    return out.astype("<i2").tobytes()


def speak(text: str, idx=None, key=None, voice=None, model=None, rate: int = 0) -> bool:
    """Spricht den Text. Gibt True zurück, wenn etwas gesprochen wurde. Wirft ElevenError, wenn es nicht ging,
    bevor ein Ton kam (dann nimmt pc_audio eine andere Stimme)."""
    global LAST_ERROR
    import sounddevice as sd

    key = (key if key is not None else KEY).strip()
    if not key:
        raise ElevenError("Kein ElevenLabs-Schlüssel eingetragen.")
    gen = pc_cancel.GEN
    t0 = time.time()
    resp = _request(text, key, voice or VOICE_ID, model or MODEL, rate)
    played = False
    try:
        stream, dev_rate = _open_stream(sd, idx)
        with stream:
            rest = b""
            while True:
                chunk = resp.read(4096)
                if not chunk or pc_cancel.changed(gen):
                    break
                data = rest + chunk
                cut = len(data) - (len(data) % 2)
                data, rest = data[:cut], data[cut:]
                if not data:
                    continue
                if not played:
                    print(f"Zeit: ElevenLabs erster Ton nach {time.time() - t0:.1f} s")
                    played = True
                stream.write(_convert(data, dev_rate))
                try:  # Lautstärke der Stimme für die "atmende" Kugel
                    import pc_sphere

                    v = np.frombuffer(data, dtype="<i2").astype(np.float32)
                    pc_sphere.set_level("out", float(np.sqrt(np.mean(v * v))) / 6000 if v.size else 0.0)
                except Exception:
                    pass
            if played and not pc_cancel.changed(gen):
                stream.write(b"\x00\x00" * int(dev_rate * 0.15))
        try:
            import pc_sphere

            pc_sphere.set_level("out", 0.0)
            pc_sphere.LEVEL["out"] = 0.0
        except Exception:
            pass  # kurzes Ausklingen, damit nichts abgeschnitten wird
    finally:
        resp.close()
    LAST_ERROR = ""
    return played


def list_voices(key: str) -> list:
    """Alle Stimmen im ElevenLabs-Konto als [(Anzeigename, Stimmen-ID)]."""
    req = urllib.request.Request(f"{API}/voices", headers={"xi-api-key": key.strip()})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ElevenError(explain(e.code, e.read().decode("utf-8", "ignore"))) from None
    except (urllib.error.URLError, OSError) as e:
        raise ElevenError(f"ElevenLabs nicht erreichbar ({getattr(e, 'reason', e)})") from None
    out = []
    for v in data.get("voices", []):
        labels = v.get("labels") or {}
        extra = ", ".join(x for x in (labels.get("accent"), labels.get("gender"), labels.get("description")) if x)
        out.append((f"{v.get('name', '?')}" + (f" – {extra}" if extra else ""), v.get("voice_id", "")))
    return [o for o in out if o[1]]
