"""
Abgleich der Einstellungen zwischen PC und Handy über das Internet.

Einrichten (einmalig):   py pc_sync.py
Danach läuft der Abgleich automatisch im Hintergrund, solange der Assistent läuft (alle ~20 Sekunden).

Was wird abgeglichen: Weckwörter, Stimme (Name, Tonhöhe, Tempo), Lautstärke des Wecksounds,
Weiterhören-Zeit, Sprechen an/aus, Farbthema, Name des Assistenten, Anrede, Wetter-Stadt.
NICHT abgeglichen: Gemini-Schlüssel und alles andere (Geräte, Fenstergrößen usw.).
Pro Einstellung gilt: wer sie zuletzt geändert hat, gewinnt - egal ob PC oder Handy.

Die Sync-Adresse ist geheim (wer sie kennt, kann die Einstellungen lesen/ändern). Nicht weitergeben.
"""

import json
import os
import secrets
import threading
import time
import urllib.request

import pc_settings
from pc_apps import base_dir

BASE_URL = "https://ntfy.sh/"  # offener Gratis-Dienst, kein Konto nötig; die geheime Adresse ist der Zugang
KEEPALIVE = 6 * 3600 * 1000  # alle 6 Stunden neu senden (der Dienst merkt sich Nachrichten ca. 12 Stunden)
INTERVAL = 20  # Sekunden zwischen zwei Abgleichen

# Schlüssel in einstellungen.json -> Art ("list" = Weckwörter, mit Komma getrennt übertragen)
KEYS = {
    "wake_words": "list",
    "followup_seconds": "int",
    "speak": "bool",
    "edge_voice": "str",
    "voice_pitch": "int",
    "voice_rate": "int",
    "chime_volume": "int",
    "accent": "str",
    "assistant_name": "str",
    "address_as": "str",
    "weather_city": "str",
}

_lock = threading.Lock()


def _state_path() -> str:
    return os.path.join(base_dir(), "sync_state.json")


def _load_state() -> dict:
    try:
        with open(_state_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict):
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception:
        pass


def _http(url: str, method: str = "GET", body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.headers, r.read().decode("utf-8", "replace")


def _enc(key: str, value):
    if KEYS[key] == "list":
        return ", ".join(str(w).strip().lower() for w in (value or []) if str(w).strip())
    if KEYS[key] == "int":
        return int(value)
    if KEYS[key] == "bool":
        return bool(value)
    return str(value if value is not None else "")


def _dec(key: str, value):
    kind = KEYS[key]
    if kind == "list":
        words = [w.strip().lower() for w in str(value).replace(";", ",").split(",") if w.strip()]
        return words or None
    if kind == "int":
        return int(float(value))
    if kind == "bool":
        return value if isinstance(value, bool) else str(value).lower() == "true"
    return str(value)


def create() -> str:
    """Erzeugt eine neue, geheime Sync-Adresse (rein lokal, nichts wird angefragt)."""
    return BASE_URL + "jarvis-" + secrets.token_hex(10)


def _fetch(url: str) -> dict:
    """Liest alle Nachrichten der letzten Stunden und setzt daraus den neuesten Stand zusammen."""
    _, _, text = _http(url.rstrip("/") + "/json?poll=1&since=12h")
    merged = {}
    for line in text.splitlines():
        try:
            ev = json.loads(line)
            if ev.get("event") != "message":
                continue
            doc = json.loads(ev.get("message", ""))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        for k, v in doc.items():
            if k.startswith("_"):
                merged[k] = v
            elif isinstance(v, dict) and "v" in v:
                old = merged.get(k)
                if old is None or int(v.get("t", 0)) >= int(old.get("t", 0)):
                    merged[k] = v
    return merged


def _publish(url: str, doc: dict):
    _http(url.rstrip("/"), "POST", doc)


def sync_once(get_settings, apply_changes) -> str:
    with _lock:
        settings = get_settings()
        url = (settings.get("sync_url") or "").strip()
        if not url:
            return "nicht eingerichtet"
        remote = _fetch(url)
        state = _load_state()
        now = int(time.time() * 1000)
        if now - int(state.get("_pub", 0)) > KEEPALIVE:
            push_forced = True
        else:
            push_forced = False
        changes, push = {}, push_forced

        for key in KEYS:
            try:
                local = _enc(key, settings.get(key, pc_settings.DEFAULTS.get(key)))
            except Exception:
                continue
            st = state.get(key)
            r = remote.get(key)
            r_ok = isinstance(r, dict) and "v" in r
            if st is None:
                if r_ok:  # erstes Mal: den vorhandenen Stand übernehmen
                    dec = _dec(key, r["v"])
                    if dec is not None:
                        if _enc(key, dec) != local:
                            changes[key] = dec
                        state[key] = {"v": _enc(key, dec), "t": int(r.get("t", 0))}
                else:
                    state[key] = {"v": local, "t": now}
                    remote[key] = state[key]
                    push = True
                continue
            if st["v"] != local:  # hier geändert
                state[key] = {"v": local, "t": now}
                remote[key] = state[key]
                push = True
                continue
            if r_ok and int(r.get("t", 0)) > int(st.get("t", 0)) and r["v"] != st["v"]:  # am Handy geändert
                dec = _dec(key, r["v"])
                if dec is not None:
                    changes[key] = dec
                    state[key] = {"v": _enc(key, dec), "t": int(r["t"])}
            elif not r_ok or int(r.get("t", 0)) < int(st.get("t", 0)):
                remote[key] = st
                push = True

        # Version des Sprachdienstes mitgeben: Das Handy nutzt dieselbe wie dein PC
        try:
            from edge_tts.constants import CHROMIUM_FULL_VERSION
            if remote.get("_edge_ver") != CHROMIUM_FULL_VERSION:
                remote["_edge_ver"] = CHROMIUM_FULL_VERSION
                push = True
        except Exception:
            pass

        if push:
            _publish(url, remote)
            state["_pub"] = now
        _save_state(state)
        if changes:
            apply_changes(changes)
        return f"{len(changes)} Änderung(en) vom Handy übernommen" if changes else ("gesendet" if push else "aktuell")


def start(get_settings, apply_changes):
    """Startet den Abgleich im Hintergrund (macht nichts, solange keine Sync-Adresse eingetragen ist)."""
    def loop():
        time.sleep(6)
        while True:
            try:
                sync_once(get_settings, apply_changes)
            except Exception as e:  # kein Internet o. ä.: später nochmal
                print(f"Abgleich: {e}")
            time.sleep(INTERVAL)

    threading.Thread(target=loop, daemon=True).start()


def _copy(text: str):
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        print("(Die Adresse wurde in die Zwischenablage kopiert.)")
    except Exception:
        pass


def setup():
    s = pc_settings.load()
    print("Abgleich mit dem Handy einrichten")
    print("---------------------------------")
    if s.get("sync_url"):
        print("Aktuelle Sync-Adresse:\n  " + s["sync_url"] + "\n")
    print("  1 = neue Sync-Adresse erstellen (dann am Handy einfügen)")
    print("  2 = Adresse vom Handy eintragen (am Handy 'Adresse kopieren')")
    print("  Enter = abbrechen")
    choice = input("Auswahl: ").strip()
    url = ""
    if choice == "1":
        try:
            url = create()
        except Exception as e:
            print(f"Das hat nicht geklappt: {e}")
            return
    elif choice == "2":
        url = input("Adresse einfügen: ").strip()
        if not url.startswith("http"):
            print("Das sieht nicht wie eine Adresse aus.")
            return
    else:
        return
    s["sync_url"] = url
    if pc_settings.save(s):
        print("\nFertig. Deine Sync-Adresse:\n  " + url)
        _copy(url)
        print("\nAm Handy: Einstellungen > Abgleich mit dem PC > 'Aus Zwischenablage einfügen' > 'Jetzt abgleichen'.")
        print("Starte den Assistenten danach neu (py pc_overlay.py).")


if __name__ == "__main__":
    setup()
