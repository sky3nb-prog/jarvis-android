"""
Handy als Fernbedienung: die Jarvis-App schickt Befehle (Musik, Discord, Stumm, Sperren, Aus, Wave-Link-Regler,
"Befehl an den PC"), der PC führt sie aus und schickt seinen Status zurück (online, was läuft, Spiel, Leistung,
Wave-Link-Regler).

Läuft verschlüsselt über ntfy.sh, auf einem eigenen Kanal (aus demselben Kopplungscode abgeleitet wie das Gedächtnis).
Der PC hört den Kanal dauerhaft ab, deshalb kommen Befehle sofort an. ntfy.sh erlaubt etwa 250 Nachrichten am Tag,
darum schickt der PC seinen Status nur auf Anfrage, nach jedem Befehl und sonst alle 30 Minuten als Lebenszeichen.
"""

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.request

import pc_link

SERVER = pc_link.SERVER
HEARTBEAT = 30 * 60
ON_TEXT = None   # vom Programm gesetzt: führt einen Text aus, als hättest du ihn gesagt
SETTINGS = None  # vom Programm gesetzt: aktuelle Einstellungen
ON_HUD = None    # vom Programm gesetzt: HUD ein/aus
STARTED_AT = time.time()
STATUS = ""
_last_sent = {"t": 0.0}
NO_WINDOW = 0x08000000


def topic() -> str:
    n = pc_link._norm(pc_link.code()).encode()
    return "jr" + hashlib.sha256(b"jarvis-remote:" + n).hexdigest()[:30]


# --- Status -------------------------------------------------------------------------------------------
def _gpu():
    """Auslastung und Temperatur der Grafikkarte (nur NVIDIA, sonst None)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=4, creationflags=NO_WINDOW).stdout
        u, t = [x.strip() for x in out.splitlines()[0].split(",")[:2]]
        return {"util": int(float(u)), "temp": int(float(t))}
    except Exception:
        return None


def _procs():
    """Läuft Discord / Steam, und welches Spiel aus Steam gerade?"""
    res = {"discord": False, "steam": False, "game": ""}
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            n = (p.info.get("name") or "").lower()
            exe = p.info.get("exe") or ""
            if n.startswith("discord"):
                res["discord"] = True
            elif n == "steam.exe":
                res["steam"] = True
            m = re.search(r"steamapps[\\/]common[\\/]([^\\/]+)", exe, re.I)
            if m and not res["game"] and "steamwebhelper" not in n:
                res["game"] = m.group(1)
    except Exception:
        pass
    return res


def status() -> dict:
    st = {"online": True, "since": int(STARTED_AT), "ts": int(time.time())}
    try:
        import psutil
        st["cpu"] = int(psutil.cpu_percent(interval=0.4))
        st["ram"] = int(psutil.virtual_memory().percent)
        st["boot"] = int(psutil.boot_time())
    except Exception:
        pass
    g = _gpu()
    if g:
        st["gpu"] = g
    try:
        import pc_fern
        f = pc_fern.info()
        if f:
            st["fern"] = f
    except Exception:
        pass
    st.update(_procs())
    try:
        import pc_steuerung
        st["mic_muted"] = bool(getattr(pc_steuerung, "MIC_MUTED", False))
        st["deaf"] = bool(getattr(pc_steuerung, "FULL_MUTE_ON", False))
    except Exception:
        pass
    try:
        import pc_media
        r = pc_media.now()
        if r and r.get("title"):
            st["playing"] = {"title": r["title"], "artist": r.get("artist", ""), "app": pc_media.app_name(r.get("app", "")),
                             "on": bool(r.get("playing"))}
    except Exception:
        pass
    try:
        import pc_wavelink
        wl = pc_wavelink.snapshot()
        if wl:
            st["wl"] = wl
    except Exception:
        pass
    return st


# --- Befehle ------------------------------------------------------------------------------------------
def execute(cmd: dict) -> str:
    import pc_steuerung as S
    t = cmd.get("type")
    if t == "status":
        return ""
    if t == "gassi_log":   # Protokoll der Hunderunde vom Handy: zum Nachsehen speichern
        import json, os, sys, time as _t
        base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base, "gassi_log.json"), "w", encoding="utf-8") as f:
            json.dump({"empfangen": _t.strftime("%Y-%m-%d %H:%M:%S"), "log": cmd.get("log", []), "runden": cmd.get("runden", []), "home": cmd.get("home", [])}, f, ensure_ascii=False, indent=1)
        return "Protokoll gespeichert."
    if t == "media" and cmd.get("key") in ("playpause", "nexttrack", "prevtrack", "volumemute"):
        S.media(cmd["key"])
        return {"playpause": "Play/Pause gedrückt.", "nexttrack": "Nächster Titel.", "prevtrack": "Vorheriger Titel.",
                "volumemute": "PC stumm geschaltet (oder wieder an)."}[cmd["key"]]
    if t == "app" and cmd.get("name") in ("discord", "steam", "deezer", "spotify", "chrome"):
        return S.open_app(cmd["name"])
    if t == "discord":
        if cmd.get("what") == "mic":
            return S.set_mic(None)
        if cmd.get("what") == "deaf":
            return S.set_full_mute(None)
    if t == "power" and cmd.get("what") in ("lock", "shutdown", "sleep", "restart"):
        return S.execute_power(cmd["what"])   # die Rückfrage hat schon das Handy gestellt
    if t == "power" and cmd.get("what") == "cancel":
        return S.cancel_power()
    if t == "wl":
        import pc_wavelink
        try:
            return pc_wavelink.remote_set(str(cmd.get("ch")), cmd.get("mix"), cmd.get("level"), cmd.get("mute"))
        except ConnectionError:
            return "Wave Link läuft gerade nicht."
    if t == "youtube":
        q = str(cmd.get("query") or "").strip()
        return S.youtube(q) if q else S.open_url("https://www.youtube.com")
    if t == "hud" and ON_HUD:
        ON_HUD()
        return "HUD umgeschaltet."
    if t == "screen":   # vom Handy: "schau mal auf meinen PC"
        import pc_sehen
        return pc_sehen.look(str(cmd.get("frage") or ""))
    if t in ("say", "offer"):   # vom Handy: Briefing, "jetzt los", Wochenrückblick
        import pc_nachrichten
        if cmd.get("need_active") and pc_nachrichten._idle_seconds() > 20 * 60:
            raise RuntimeError("niemand am PC")
        pc_nachrichten.incoming({"kind": t, "force": True, "text": str(cmd.get("text") or ""),
                                 "question": str(cmd.get("question") or ""), "title": str(cmd.get("title") or "")})
        return "Wird angesagt."
    if t == "weg":    # Handy hat das Heim-WLAN verlassen
        import pc_alltag
        return pc_alltag.away(SETTINGS() if SETTINGS else None)
    if t == "heim":
        import pc_alltag
        return pc_alltag.home()
    if t == "wa_send":   # vom Handy (Anruf-Butler): "Kann gerade nicht …" per WhatsApp am PC
        import pc_messages
        r = pc_messages.send_whatsapp(str(cmd.get("to") or ""), str(cmd.get("text") or ""))
        if not r.startswith("Erledigt"):
            raise RuntimeError(r)
        return r
    if t == "remind":   # Termin am Handy eingetragen: der PC erinnert dich auch
        import pc_handy
        pc_handy.remind_here(str(cmd.get("text") or ""), float(cmd.get("at") or 0))
        return ""
    if t == "text" and str(cmd.get("text") or "").strip():
        if ON_TEXT:
            ON_TEXT(str(cmd["text"]).strip()[:300])
            return "An Jarvis am PC geschickt."
        return "Jarvis am PC ist gerade nicht bereit."
    return "Diesen Befehl kenne ich nicht."


# --- Senden und Empfangen -------------------------------------------------------------------------------
def send(obj: dict):
    c = pc_link.code()
    r = urllib.request.Request(SERVER + topic(), data=pc_link.encrypt(obj, c).encode(), method="POST")
    r.add_header("User-Agent", "Jarvis-PC")
    urllib.request.urlopen(r, timeout=20).read()
    _last_sent["t"] = time.time()


def reply(re_id: str = "", ok: bool = True, text: str = ""):
    send({"kind": "status", "from": "pc", "re": re_id, "ok": ok, "text": text, "ts": int(time.time()), "status": status()})


def _handle(msg: dict):
    global STATUS
    cmd = msg.get("cmd") or {}
    try:
        text = execute(cmd)
        ok = True
    except Exception as e:
        text, ok = f"Das ging nicht: {e}", False
    STATUS = time.strftime("Handy-Befehl um %H:%M: ") + (cmd.get("type") or "?")
    print(f"Handy-Fernbedienung: {cmd} -> {text}")
    if cmd.get("type") in ("wl", "media", "discord"):
        time.sleep(0.4)   # Wave Link / Discord kurz nachziehen lassen, damit der Status stimmt
    if cmd.get("type") == "remind":
        return   # keine Antwort nötig (spart Nachrichten)
    try:
        reply(msg.get("id", ""), ok, text)
    except Exception as e:
        print(f"Handy-Fernbedienung: Antwort nicht gesendet ({e})")


def _listen(stop: threading.Event):
    """Hört den Kanal dauerhaft ab (ntfy schickt alle 45 Sekunden ein Lebenszeichen)."""
    global STATUS
    wait = 5
    while not stop.is_set():
        c = pc_link.code()
        try:
            req = urllib.request.Request(f"{SERVER}{topic()}/json", headers={"User-Agent": "Jarvis-PC"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                wait = 5
                STATUS = "Fernbedienung bereit."
                for raw in resp:
                    if stop.is_set():
                        return
                    try:
                        ev = json.loads(raw.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if ev.get("event") != "message":
                        continue
                    body = ev.get("message") or ""
                    att = ev.get("attachment") or {}
                    if not body.startswith("J1.") and att.get("url"):   # große Nachricht (z. B. mit Sprachnachricht) kommt als Anhang
                        try:
                            body = urllib.request.urlopen(urllib.request.Request(att["url"], headers={"User-Agent": "Jarvis-PC"}),
                                                          timeout=30).read().decode("utf-8", "replace")
                        except Exception:
                            body = ""
                    try:
                        msg = pc_link.decrypt(body, c)
                    except Exception:
                        msg = None
                    if msg and msg.get("from") == "phone" and msg.get("kind") == "wa_msg":
                        if abs(time.time() - float(msg.get("ts", 0))) < 600:
                            try:
                                import pc_nachrichten
                                pc_nachrichten.incoming(msg)
                            except Exception as e:
                                print(f"Nachricht vom Handy: {e}")
                        continue
                    if msg and msg.get("from") == "phone" and msg.get("kind") == "phone_reply":
                        try:
                            import pc_handy
                            pc_handy.on_reply(msg)   # Antwort auf einen Auftrag vom PC ans Handy
                        except Exception:
                            pass
                        continue
                    if not msg or msg.get("from") != "phone" or msg.get("kind") != "cmd":
                        continue
                    if abs(time.time() - float(msg.get("ts", 0))) > 120:
                        continue   # alter Befehl (z. B. nach einem Neustart) – nicht mehr ausführen
                    threading.Thread(target=_handle, args=(msg,), daemon=True).start()
        except Exception as e:
            STATUS = f"Fernbedienung: Verbindung weg ({type(e).__name__}), versuche es gleich wieder."
            stop.wait(wait)
            wait = min(120, wait * 2)


def _heartbeat(stop: threading.Event):
    stop.wait(20)
    while not stop.is_set():
        if time.time() - _last_sent["t"] > HEARTBEAT - 30:
            try:
                reply("", True, "")
            except Exception:
                pass
        stop.wait(60)


def start(stop: threading.Event):
    threading.Thread(target=_listen, args=(stop,), daemon=True).start()
    threading.Thread(target=_heartbeat, args=(stop,), daemon=True).start()


if __name__ == "__main__":
    print(json.dumps(status(), ensure_ascii=False, indent=1))
