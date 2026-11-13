"""
Sprachassistent mit Weckwort (Windows). Baut auf pc_steuerung.py auf.

Beide Dateien müssen im selben Ordner liegen.
Setup:  pip install pyautogui sounddevice numpy SpeechRecognition
Start:  python pc_assistent.py

Ablauf: Sag das Weckwort, gleich danach den Befehl ("Jarvis, öffne Discord")
oder erst das Weckwort, auf den Piepton warten und dann den Befehl sagen.
Für freie Sätze ("mach mir was Entspanntes an") brauchst du GEMINI_API_KEY.

HINWEIS: Die Spracherkennung läuft über den kostenlosen Google-Dienst.
Dabei wird alles, was das Mikrofon als Sprache erkennt, zur Texterkennung
an Google gesendet, auch Sätze ohne Weckwort. Wer das nicht möchte, nutzt
besser eine Offline-Erkennung (kann ich dir einbauen).
"""

import collections
import os
import queue
import sys
import time

import numpy as np
import sounddevice as sd
import speech_recognition as sr

import pc_cancel
import pc_steuerung
from pc_steuerung import ask_ai, handle_fixed
import pc_ai

# --- Einstellungen ----------------------------------------------------------
WAKE_WORDS = ["jarvis"]  # hier dein Weckwort (auch mehrere Schreibweisen) eintragen
LANGUAGE = "de-DE"
RATE = 16000
BLOCK = 1600  # 0,1 Sekunden pro Block
SILENCE_BLOCKS = 7  # 0,7 s Stille beendet einen Satz
MAX_BLOCKS = 150  # maximal 15 s pro Satz
MIN_THRESHOLD = 300  # Mindestlautstärke, ab der Sprache erkannt wird
INPUT_DEVICE = None  # None = Standardmikrofon; sonst Nummer aus "py pc_assistent.py --geraete"


# --- Hilfsfunktionen --------------------------------------------------------
def rms(block: bytes) -> float:
    a = np.frombuffer(block, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def beep():
    try:
        import winsound

        winsound.Beep(880, 150)
    except Exception:
        print("\a", end="")


def drain(q: queue.Queue):
    while not q.empty():
        try:
            q.get_nowait()
        except queue.Empty:
            break


def calibrate(q: queue.Queue) -> float:
    print("Messe Umgebungslautstärke, bitte kurz ruhig sein ...")
    levels = []
    end = time.time() + 1.5
    while time.time() < end:
        try:
            levels.append(rms(q.get(timeout=1)))
        except queue.Empty:
            pass
    ambient = sum(levels) / len(levels) if levels else 0
    threshold = max(MIN_THRESHOLD, ambient * 2.5)
    print(f"Grundrauschen: {ambient:.0f}, Schwelle: {threshold:.0f}")
    return threshold


def listen_utterance(
    q: queue.Queue,
    threshold: float,
    max_wait: float | None = None,
    on_progress=None,
    progress_every: int = 8,
):
    """Wartet auf Sprache und gibt die Rohdaten eines Satzes zurück.

    on_progress(rohdaten) wird während des Sprechens etwa alle 0,8 s mit dem
    bisher Aufgenommenen aufgerufen (für die Live-Anzeige)."""
    pre = collections.deque(maxlen=3)
    frames: list[bytes] = []
    speaking = False
    silence = 0
    since_progress = 0
    start = time.time()
    gen = pc_cancel.GEN
    while True:
        if pc_cancel.changed(gen):  # per X abgebrochen: Aufnahme verwerfen
            return None
        try:
            block = q.get(timeout=1)
        except queue.Empty:
            if max_wait and not speaking and time.time() - start > max_wait:
                return None
            continue
        loud = rms(block) > threshold
        if not speaking:
            pre.append(block)
            if loud:
                speaking = True
                frames = list(pre)
                silence = 0
            elif max_wait and time.time() - start > max_wait:
                return None
        else:
            frames.append(block)
            since_progress += 1
            if on_progress and since_progress >= progress_every:
                since_progress = 0
                on_progress(b"".join(frames))
            silence = 0 if loud else silence + 1
            if silence >= SILENCE_BLOCKS or len(frames) >= MAX_BLOCKS:
                return b"".join(frames)


def transcribe(recognizer: sr.Recognizer, raw: bytes, quiet: bool = False) -> str:
    audio = sr.AudioData(raw, RATE, 2)
    t0 = time.time()
    try:
        text = recognizer.recognize_google(audio, language=LANGUAGE)
        if not quiet:
            print(f"Zeit: Spracherkennung {time.time() - t0:.1f} s")
        return text
    except sr.UnknownValueError:
        if not quiet:
            print("(Sprache erkannt, aber nicht verstanden)")
        return ""
    except sr.RequestError as e:
        if not quiet:
            print(f"Spracherkennung nicht erreichbar: {e}")
        return ""


def execute(command: str, ai_available: bool):
    print(f"Befehl: {command}")
    result = handle_fixed(command)
    if result is None:
        result = (
            ask_ai(command)
            if ai_available
            else "Das verstehe ich nur mit Gemini-Schlüssel (freie Sätze)."
        )
    print(result)


# --- Hauptschleife ----------------------------------------------------------
def main():
    if "--geraete" in sys.argv:
        print(sd.query_devices())
        return
    ai_available = pc_ai.available()
    recognizer = sr.Recognizer()
    q: queue.Queue = queue.Queue()

    def callback(indata, frames, t, status):
        q.put(bytes(indata))

    with sd.RawInputStream(
        samplerate=RATE,
        blocksize=BLOCK,
        dtype="int16",
        channels=1,
        device=INPUT_DEVICE,
        callback=callback,
    ):
        try:
            print("Mikrofon:", sd.query_devices(INPUT_DEVICE, "input")["name"])
        except Exception:
            pass
        threshold = calibrate(q)
        print(f"Bereit. Weckwort: {', '.join(WAKE_WORDS)}. KI-Modus: {'an' if ai_available else 'aus'}. Beenden mit Strg+C.")
        try:
            while True:
                raw = listen_utterance(q, threshold)
                text = transcribe(recognizer, raw).lower()
                if not text:
                    continue
                print(f"Gehört: {text}")
                wake = next((w for w in WAKE_WORDS if w in text), None)
                if not wake:
                    continue
                command = text.split(wake, 1)[1].strip(" ,.!?")
                if not command:
                    beep()
                    print("Ich höre ...")
                    raw = listen_utterance(q, threshold, max_wait=6)
                    if raw is None:
                        continue
                    command = transcribe(recognizer, raw).strip()
                    if not command:
                        continue
                execute(command, ai_available)
                drain(q)
                if pc_steuerung.QUIT_REQUESTED:
                    print("Beendet.")
                    break
        except KeyboardInterrupt:
            print("Beendet.")


if __name__ == "__main__":
    main()
