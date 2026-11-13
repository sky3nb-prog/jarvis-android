"""
Beliebige Programme, Ordner und eigene Befehle per Sprache öffnen (Windows).

Quellen, in dieser Reihenfolge bei gleichem Treffer:
1. meine_befehle.json (liegt neben dem Programm): eigene Namen für Dateien, Ordner,
   Webseiten, Spiele, alles was sich per Doppelklick öffnen lässt
2. Wichtige Ordner (Downloads, Dokumente, Bilder, Desktop ...)
3. ALLE installierten Programme aus dem Startmenü, auch Store-Apps (per Windows-Abfrage
   "Get-StartApps"). Neue Programme findet er automatisch.

Der gesprochene Name wird unscharf verglichen, kleine Erkennungsfehler sind also okay.
"""

import difflib
import json
import os
import subprocess
import sys
import threading
import time

CUSTOM_FILE = "meine_befehle.json"
INDEX_MAX_AGE = 600  # Programmliste alle 10 Minuten auffrischen
MIN_SCORE = 65.0

# Füllwörter, die beim Sprechen davor stehen ("öffne den Task-Manager")
FILLER = {"den", "die", "das", "dem", "mal", "bitte", "programm", "app", "anwendung",
          "ordner", "mir", "doch", "einmal", "kurz"}

# Wichtige Ordner (Windows-Kurzbefehle, funktionieren auch bei OneDrive-Ordnern)
FOLDERS = {
    "downloads": "shell:Downloads",
    "download": "shell:Downloads",
    "dokumente": "shell:Personal",
    "bilder": "shell:My Pictures",
    "videos": "shell:My Video",
    "desktop": "shell:Desktop",
    "papierkorb": "shell:RecycleBinFolder",
    "dieser pc": "shell:MyComputerFolder",
}

_index: list = []  # (Name, AppID, normalisierter Name)
_index_time = 0.0
_lock = threading.Lock()


# --- Hilfsfunktionen --------------------------------------------------------
def base_dir() -> str:
    """Ordner des Programms (bei der .exe: der Ordner, in dem die .exe liegt)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def norm(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def clean_spoken(name: str) -> str:
    words = [w for w in name.lower().replace("-", " ").split() if w not in FILLER]
    return " ".join(words)


def score(q: str, n: str) -> float:
    """Wie gut passt der gesprochene Name q zum Namen n (beide normalisiert)? 0 = gar nicht."""
    if not q or not n:
        return 0.0
    if q == n:
        return 100.0
    if len(q) >= 3 and n.startswith(q):
        return 90.0 - min(10.0, (len(n) - len(q)) * 0.5)
    if len(q) >= 3 and q in n:
        return 80.0 - min(10.0, (len(n) - len(q)) * 0.3)
    if len(n) >= 4 and n in q:
        return 70.0
    ratio = difflib.SequenceMatcher(None, q, n).ratio()
    return 50.0 + ratio * 20.0 if ratio >= 0.78 else 0.0


# --- Eigene Befehle ----------------------------------------------------------
def ensure_custom_file():
    path = os.path.join(base_dir(), CUSTOM_FILE)
    if os.path.exists(path):
        return
    example = {
        "_hinweis": "Eigene Befehle: \"name\": \"Pfad, Ordner oder Webadresse\". "
        "Sag dann: Jarvis, öffne name. Doppelte Rückstriche im Pfad schreiben (\\\\). "
        "Zeilen die mit _ oder beispiel beginnen werden ignoriert.",
        "beispiel spiel": "C:\\\\Spiele\\\\MeinSpiel\\\\spiel.exe",
        "beispiel ordner": "C:\\\\Users\\\\DEINNAME\\\\Documents\\\\Projekte",
        "beispiel webseite": "https://www.youtube.com",
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(example, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_custom() -> dict:
    path = os.path.join(base_dir(), CUSTOM_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    result = {}
    for key, value in data.items():
        if key.startswith("_") or key.lower().startswith("beispiel"):
            continue
        if isinstance(value, str) and value.strip():
            result[norm(key)] = (key, value.strip())
    return result


# --- Programmliste (alle Startmenü-Programme und Store-Apps) -------------------
_PS = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
    "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
)


def load_index(force: bool = False) -> list:
    global _index, _index_time
    with _lock:
        if not force and _index and time.time() - _index_time < INDEX_MAX_AGE:
            return _index
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
                capture_output=True,
                creationflags=0x08000000,  # kein Konsolenfenster
                timeout=60,
            )
            text = out.stdout.decode("utf-8", errors="replace").strip()
            data = json.loads(text) if text else []
            if isinstance(data, dict):
                data = [data]
            seen, entries = set(), []
            for item in data:
                name, appid = item.get("Name"), item.get("AppID")
                if not name or not appid or name in seen:
                    continue
                low = name.lower()
                if "uninstall" in low or "deinstall" in low:
                    continue
                seen.add(name)
                entries.append((name, appid, norm(name)))
            if entries:
                _index, _index_time = entries, time.time()
        except Exception as e:
            print(f"Programmliste konnte nicht geladen werden: {e}")
        return _index


def preload():
    ensure_custom_file()
    load_index()


# --- Öffnen --------------------------------------------------------------------
def _best(q: str):
    """Bester Treffer über alle Quellen: (Punkte, Anzeigename, Öffnen-Funktion)."""
    candidates = []  # (Punkte, Priorität, Name, Ziel, Art)

    for key, (label, target) in load_custom().items():
        s = score(q, key)
        if s:
            candidates.append((s, 3, label, target, "path"))
    for key, shell in FOLDERS.items():
        s = score(q, norm(key))
        if s:
            candidates.append((s, 2, key.capitalize(), shell, "path"))
    for name, appid, n in _index:
        s = score(q, n)
        if s:
            candidates.append((s, 1, name, "shell:AppsFolder\\" + appid, "path"))

    if not candidates:
        return None
    # beste Punkte, dann Priorität, dann kürzester Name
    best = max(candidates, key=lambda c: (c[0], c[1], -len(c[2])))
    return best if best[0] >= MIN_SCORE else None


def _launch_and_focus(label: str, target: str) -> str:
    import pc_windows

    before = set(pc_windows.visible_windows())
    try:
        os.startfile(target)
    except Exception as e:
        return f"Konnte {label} nicht öffnen: {e}"
    hwnd = pc_windows.wait_for_new_window(before)
    if hwnd:
        time.sleep(0.3)
        pc_windows.bring_to_front(hwnd)
        return f"{label} ist offen."
    return f"{label} wird geöffnet."


def open_by_name(spoken: str) -> str:
    q = norm(clean_spoken(spoken))
    if len(q) < 2:
        return "Welches Programm soll ich öffnen?"
    load_index()
    hit = _best(q)
    if not hit:  # vielleicht ist es ein neu installiertes Programm
        load_index(force=True)
        hit = _best(q)
    if not hit:
        return f"Ich finde nichts mit dem Namen {spoken.strip()}."
    _, _, label, target, _ = hit
    return _launch_and_focus(label, target)
