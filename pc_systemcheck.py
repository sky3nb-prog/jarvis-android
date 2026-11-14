"""
Systemcheck: "Friday, Statuscheck" – prüft alles, was Jarvis braucht, und sagt gezielt, was kaputt ist und was zu tun ist.

run() -> Liste von {"id", "name", "ok": True/False/None, "detail", "fix"}   (None = nicht eingerichtet, kein Fehler)
Einmal am Tag läuft er still im Hintergrund und meldet sich nur bei Problemen.
Das Ergebnis nutzen auch der Iron-Man-Start (Boot-Animation) und die Statusseite im HUD.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request

LAST = {"t": 0.0, "items": []}
SETTINGS = None   # vom Programm gesetzt: () -> Einstellungen
ON_RESULT = None  # vom Programm gesetzt: Ergebnis im HUD zeigen (Statusseite)
BOOT = None       # vom Programm gesetzt: Iron-Man-Start zeigen


def _get(url, headers=None, timeout=8):
    req = urllib.request.Request(url, headers=dict({"User-Agent": "Jarvis-PC"}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def _item(id_, name, ok, detail="", fix=""):
    return {"id": id_, "name": name, "ok": ok, "detail": detail, "fix": fix}


def _internet():
    try:
        _get("https://www.google.com/generate_204", timeout=5)
        return _item("net", "Internet", True, "verbunden")
    except Exception:
        return _item("net", "Internet", False, "keine Verbindung", "WLAN oder Router prüfen.")


def _ai():
    import pc_ai
    out = []
    g, q = pc_ai.gemini_key(), pc_ai.groq_key()
    if not g and not q:
        return [_item("ai", "KI-Schlüssel", False, "kein Schlüssel", "In den Einstellungen unter KI einen Gemini- oder Groq-Schlüssel eintragen.")]
    if g:
        try:
            _get(f"https://generativelanguage.googleapis.com/v1beta/models?key={g}&pageSize=1")
            out.append(_item("gemini", "Gemini", True, "Schlüssel gültig"))
        except urllib.error.HTTPError as e:
            out.append(_item("gemini", "Gemini", False, f"Fehler {e.code}", "Gemini-Schlüssel abgelaufen oder falsch – neuen bei Google AI Studio holen."))
        except Exception:
            out.append(_item("gemini", "Gemini", False, "nicht erreichbar", "Internet prüfen."))
    if q:
        try:
            _get("https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {q}"})
            out.append(_item("groq", "Groq", True, "Schlüssel gültig"))
        except urllib.error.HTTPError as e:
            out.append(_item("groq", "Groq", False, f"Fehler {e.code}", "Groq-Schlüssel abgelaufen oder falsch – neuen auf console.groq.com holen."))
        except Exception:
            out.append(_item("groq", "Groq", False, "nicht erreichbar", "Internet prüfen."))
    return out


def _mic():
    try:
        import sounddevice as sd
        d = sd.query_devices(kind="input")
        return _item("mic", "Mikrofon", True, str(d.get("name", "da"))[:40])
    except Exception:
        return _item("mic", "Mikrofon", False, "kein Mikrofon gefunden", "Mikrofon einstecken bzw. in Windows als Standard-Eingabe wählen.")


def _voice():
    try:
        import edge_tts  # noqa: F401
        return _item("voice", "Stimme", True, "Online-Stimme bereit")
    except Exception:
        return _item("voice", "Stimme", True, "Windows-Stimme")


def _phone():
    try:
        import pc_handy
        t = pc_handy.STATUS.get("t") or 0
        if not t:
            return _item("phone", "Handy-Kopplung", None, "noch nicht gemeldet", "Handy-App öffnen – sie meldet sich dann.")
        age = time.time() - t
        if age < 45 * 60:
            akku = (pc_handy.STATUS.get("data") or {}).get("akku")
            return _item("phone", "Handy-Kopplung", True, f"verbunden" + (f" · Akku {akku} %" if akku is not None else ""))
        return _item("phone", "Handy-Kopplung", False, f"seit {int(age // 60)} Min. still",
                     "Handy-App öffnen; in den Akku-Einstellungen 'Nicht einschränken' für Jarvis wählen.")
    except Exception:
        return _item("phone", "Handy-Kopplung", None, "–")


def _tailscale():
    try:
        import pc_fern
        ip = pc_fern.tailscale_ip()
        return _item("tail", "Tailscale", True, ip) if ip else _item("tail", "Tailscale", False, "nicht verbunden", "Tailscale öffnen und anmelden.")
    except Exception:
        return _item("tail", "Tailscale", None, "nicht installiert")


def _weather():
    try:
        _get("https://api.open-meteo.com/v1/forecast?latitude=48.8&longitude=9.0&current=temperature_2m", timeout=8)
        return _item("wx", "Wetter", True, "Open-Meteo erreichbar")
    except Exception:
        return _item("wx", "Wetter", False, "nicht erreichbar", "Internet prüfen – Open-Meteo antwortet nicht.")


def _calendar():
    try:
        import pc_gcal
        if not pc_gcal.configured():
            return _item("cal", "Google-Kalender", None, "nicht eingerichtet")
        pc_gcal.access_token()
        return _item("cal", "Google-Kalender", True, "verbunden")
    except Exception:
        return _item("cal", "Google-Kalender", False, "Anmeldung abgelaufen", "In den Einstellungen unter Kalender neu mit Google anmelden.")


def _telegram():
    s = SETTINGS() if SETTINGS else {}
    if not s.get("telegram_token_enc"):
        return _item("tg", "Telegram", None, "nicht eingerichtet")
    try:
        import pc_telegram
        r = pc_telegram._api("getMe", {}, timeout=8)
        return _item("tg", "Telegram", bool(r and r.get("ok")), "Bot erreichbar" if r and r.get("ok") else "Bot antwortet nicht",
                     "" if r and r.get("ok") else "Telegram-Schlüssel in den Einstellungen prüfen.")
    except Exception:
        return _item("tg", "Telegram", False, "Bot antwortet nicht", "Telegram-Schlüssel in den Einstellungen prüfen.")


def _ets2():
    try:
        import pc_ets2
        dirs = pc_ets2._game_dirs()
        if not dirs:
            return _item("ets2", "ETS2-Plugin", None, "ETS2 nicht installiert")
        ok = all(os.path.isfile(os.path.join(d, "plugins", "scs-telemetry.dll")) for d in dirs)
        return _item("ets2", "ETS2-Plugin", ok, "installiert" if ok else "fehlt", "" if ok else "Jarvis neu starten – er legt es selbst hinein.")
    except Exception:
        return _item("ets2", "ETS2-Plugin", None, "–")


def _wavelink():
    try:
        import pc_wavelink
        return _item("wl", "Wave Link", True, "verbunden") if pc_wavelink.available() else _item("wl", "Wave Link", None, "läuft nicht")
    except Exception:
        return _item("wl", "Wave Link", None, "läuft nicht")


def _update():
    try:
        import pc_update
        if not pc_update.possible():
            return _item("upd", "Selbst-Update", None, "nur mit der fertigen .exe")
        d = pc_update._load()
        if pc_update._state.get("ready"):
            return _item("upd", "Selbst-Update", True, "Update fertig – wartet auf Neustart")
        if d.get("failed"):
            return _item("upd", "Selbst-Update", False, "letzter Bau ging nicht", "update_log.txt ansehen oder build.bat einmal ausführen.")
        return _item("upd", "Selbst-Update", True, "aktiv")
    except Exception:
        return _item("upd", "Selbst-Update", None, "–")


CHECKS = [_internet, _ai, _mic, _voice, _phone, _tailscale, _weather, _calendar, _telegram, _ets2, _wavelink, _update]


def run() -> list:
    items, lock = [], threading.Lock()

    def one(f):
        try:
            r = f()
        except Exception as e:
            r = _item(f.__name__.strip("_"), f.__name__.strip("_"), False, str(e)[:60])
        with lock:
            items.extend(r if isinstance(r, list) else [r])
    ths = [threading.Thread(target=one, args=(f,), daemon=True) for f in CHECKS]
    for t in ths:
        t.start()
    for t in ths:
        t.join(15)
    order = {f.__name__: i for i, f in enumerate(CHECKS)}
    ids = ["net", "ai", "gemini", "groq", "mic", "voice", "phone", "tail", "wx", "cal", "tg", "ets2", "wl", "upd"]
    items.sort(key=lambda x: ids.index(x["id"]) if x["id"] in ids else 99)
    LAST.update(t=time.time(), items=items)
    return items


def summary(items=None) -> str:
    items = items if items is not None else LAST["items"]
    bad = [i for i in items if i["ok"] is False]
    if not bad:
        n = sum(1 for i in items if i["ok"])
        return f"Alle Systeme laufen, Sir. {n} von {n} Prüfungen grün."
    parts = [f"{i['name']}: {i['detail']}. {i['fix']}".strip() for i in bad]
    return ("Ein Problem: " if len(bad) == 1 else f"{len(bad)} Probleme: ") + " ".join(parts)


def start_daily(report):
    """Einmal am Tag still prüfen (erstes Mal 5 Min. nach dem Start); bei Problemen report(text)."""
    def loop():
        time.sleep(300)
        while True:
            try:
                items = run()
                if any(i["ok"] is False for i in items):
                    report(summary(items))
            except Exception as e:
                print("Systemcheck:", e)
            time.sleep(24 * 3600)
    threading.Thread(target=loop, daemon=True).start()


# --- Test-Knöpfe neben jedem Punkt der Statusseite -----------------------------------------------------
def test(id_: str) -> str:
    """Probiert einen Punkt wirklich aus und sagt, was dabei herauskam."""
    try:
        if id_ == "net":
            t0 = time.time(); _get("https://www.google.com/generate_204", timeout=6)
            return f"Internet antwortet in {int((time.time() - t0) * 1000)} ms."
        if id_ in ("ai", "groq", "gemini"):
            import pc_ai
            if id_ != "gemini" and pc_ai.groq_key():
                req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", method="POST",
                                             data=json.dumps({"model": "llama-3.1-8b-instant", "max_tokens": 30, "messages": [
                                                 {"role": "user", "content": "Sag in höchstens 8 Wörtern auf Deutsch hallo, als Jarvis."}]}).encode(),
                                             headers={"Authorization": f"Bearer {pc_ai.groq_key()}", "Content-Type": "application/json", "User-Agent": "Jarvis-PC"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    return "Groq sagt: " + json.loads(r.read())["choices"][0]["message"]["content"].strip()
            if pc_ai.gemini_key():
                st, body = _get(f"https://generativelanguage.googleapis.com/v1beta/models?key={pc_ai.gemini_key()}&pageSize=50")
                return f"Gemini antwortet – {len(json.loads(body).get('models', []))} Modelle verfügbar."
            return "Kein KI-Schlüssel eingetragen."
        if id_ == "mic":
            import numpy as np
            import sounddevice as sd
            rec = sd.rec(int(1.5 * 16000), samplerate=16000, channels=1, dtype="float32"); sd.wait()
            lvl = float(np.sqrt(np.mean(rec ** 2))) * 400
            return f"Mikrofon-Pegel in 1,5 Sekunden: {min(100, int(lvl))} % " + ("– ich höre dich." if lvl > 3 else "– sehr leise, sag beim Test etwas.")
        if id_ == "voice":
            import pc_nachrichten
            pc_nachrichten.incoming({"kind": "say", "force": True, "text": "Test, eins, zwei. So klinge ich gerade."})
            return "Ich spreche gleich einen Testsatz."
        if id_ == "phone":
            import pc_handy
            r = pc_handy.ask("status", wait=20)
            if not r:
                return "Das Handy antwortet nicht – ist die Jarvis-App an?"
            s = r.get("status") or {}
            return f"Handy antwortet: Akku {s.get('akku', '?')} %, Klingelton {s.get('ringer', '?')}."
        if id_ == "tail":
            import pc_fern
            ip = pc_fern.tailscale_ip()
            return f"Tailscale-Adresse: {ip} – am Handy unter Fernzugriff öffnen." if ip else "Tailscale ist nicht verbunden."
        if id_ == "wx":
            st, body = _get("https://api.open-meteo.com/v1/forecast?latitude=48.8&longitude=9.0&current=temperature_2m,apparent_temperature")
            c = json.loads(body).get("current", {})
            return f"Leonberg gerade {c.get('temperature_2m')} °C, gefühlt {c.get('apparent_temperature')} °C."
        if id_ == "cal":
            import pc_calendar
            return pc_calendar.today_text() or "Heute keine Termine."
        if id_ == "tg":
            import pc_telegram
            return "Testnachricht an dich in Telegram geschickt." if pc_telegram.send("Test von Jarvis – Telegram läuft.") else "Telegram-Nachricht ging nicht."
        if id_ == "ets2":
            import pc_ets2
            dirs = pc_ets2._game_dirs()
            return ("Plugin liegt in: " + "; ".join(dirs)) if dirs else "ETS2 nicht gefunden."
        if id_ == "wl":
            import pc_wavelink
            return "Wave Link verbunden." if pc_wavelink.available() else "Wave Link läuft nicht."
        if id_ == "upd":
            import pc_update, pc_nachrichten
            return pc_update.check_now(lambda: pc_nachrichten.incoming({"kind": "offer", "action": "update", "title": "Update", "force": True,
                                                                         "question": "Das Update ist fertig. Soll ich kurz neu starten?"}))
        return "Für diesen Punkt gibt es keinen Test."
    except Exception as e:
        return f"Test ging nicht: {e}"
