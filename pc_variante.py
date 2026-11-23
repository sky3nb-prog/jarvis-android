"""
Welche Ausgabe läuft? Aus demselben Code entstehen zwei PC-Programme:
  - „privat“: dein Jarvis (PC-Assistent.exe, baut sich bei Updates selbst aus dem Code)
  - „konto“:  Jarvis für alle von der Website (Jarvis-Konto.exe, mit Konto-Anmeldung, holt Updates als fertiges Paket)
Die Konto-Ausgabe erkennt man an pc_web/variante.txt (legt der automatische Bau hinein) oder am Programmnamen.
"""
import os
import sys


def _detect() -> bool:
    try:
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "pc_web", "variante.txt"), encoding="utf-8") as f:
            if f.read().strip().lower() == "konto":
                return True
    except Exception:
        pass
    return os.path.basename(sys.executable).lower().startswith("jarvis-konto")


KONTO = _detect()
NAME = "Vector Konto" if KONTO else "PC-Assistent"
EXE = "Jarvis-Konto.exe" if KONTO else "PC-Assistent.exe"
EXE_DEBUG = "Jarvis-Konto-Debug.exe" if KONTO else "PC-Assistent-Debug.exe"
APP_ID = "Jarvis.Konto" if KONTO else "Jarvis.PCAssistent"
# Fertige Pakete für die Konto-Ausgabe (Website-Downloads). Bei einem eigenen Download-Repo nur hier ändern.
DOWNLOAD_REPO = "sky3nb-prog/jarvis-android"
DOWNLOAD_TAG = "konto-neueste"
DOWNLOAD_ASSET = "Jarvis-Konto-PC.zip"
