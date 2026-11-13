"""
Telegram-Verbindung für Jarvis (kostenlos, offiziell, ohne zweite SIM-Karte):

- Jarvis bekommt einen eigenen Telegram-Bot (in 1 Minute bei @BotFather erstellt) und schickt dir darüber Nachrichten,
  z. B. Routen mit Knopf "In Google Maps öffnen". Dafür muss am PC nichts nach vorn springen.
- Standort: Im Chat mit dem Bot auf 📎 > Standort > "Live-Standort teilen" > "bis ich es ausschalte".
  Telegram schickt Jarvis dann laufend deinen Standort.
- Nur der erste Chat, der dem Bot "Start" schreibt, wird angenommen (das bist du); alle anderen ignoriert er.
"""

import json
import threading
import time
import urllib.parse
import urllib.request

TOKEN = ""  # aus den Einstellungen (verschlüsselt gespeichert)
CHAT_ID = ""  # wird beim ersten "Start" gemerkt
ON_CHAT_ID = None  # Programm setzt das: speichert die Chat-ID in den Einstellungen
_offset = {"n": 0}
_thread = {"t": None, "token": None}


def _api(method: str, params: dict, timeout: float = 15):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    req = urllib.request.Request(url, data=json.dumps(params).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram-Fehler"))
    return data.get("result")


def send(text: str, button_text: str = "", button_url: str = "") -> bool:
    if not (TOKEN and CHAT_ID):
        return False
    params = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if button_url:
        params["reply_markup"] = {"inline_keyboard": [[{"text": button_text or "Öffnen", "url": button_url}]]}
    try:
        _api("sendMessage", params)
        return True
    except Exception as e:
        print(f"Telegram: {e}")
        return False


def check(token: str):
    """Test für die Einstellungen: (ok, Text)."""
    global TOKEN
    old, TOKEN = TOKEN, token.strip()
    try:
        me = _api("getMe", {})
        return True, f"Bot @{me.get('username')} ist bereit." + ("" if CHAT_ID else
                                                                  " Öffne ihn jetzt in Telegram und tippe auf Start.")
    except Exception as e:
        return False, f"Schlüssel stimmt nicht ({str(e)[:60]})."
    finally:
        TOKEN = old


def _handle(update: dict):
    global CHAT_ID
    msg = update.get("message") or update.get("edited_message") or {}
    chat = str((msg.get("chat") or {}).get("id", ""))
    if not chat:
        return
    if not CHAT_ID and (msg.get("text") or "").startswith("/start"):
        CHAT_ID = chat
        if ON_CHAT_ID:
            ON_CHAT_ID(chat)
        send("Verbunden. Ab jetzt schicke ich dir hier Routen und Nachrichten.\n\n"
             "Damit ich weiß, wo du bist: 📎 > Standort > <b>Live-Standort teilen</b> > <b>bis ich es ausschalte</b>.")
        return
    if chat != CHAT_ID:
        return  # fremde Chats ignorieren
    loc = msg.get("location")
    if loc:
        try:
            import pc_phone

            with pc_phone._lock:
                pc_phone._loc.update(lat=float(loc["latitude"]), lon=float(loc["longitude"]), ts=time.time())
        except Exception as e:
            print(f"Telegram-Standort: {e}")


def _loop(token):
    while _thread["token"] == token:
        try:
            res = _api("getUpdates", {"offset": _offset["n"], "timeout": 25,
                                      "allowed_updates": ["message", "edited_message"]}, timeout=35)
            for up in res or []:
                _offset["n"] = up["update_id"] + 1
                _handle(up)
        except Exception as e:
            print(f"Telegram: {e}")
            time.sleep(15)


def start():
    """Lauscht im Hintergrund auf Nachrichten an den Bot (Start, Live-Standort)."""
    if not TOKEN or _thread["token"] == TOKEN:
        return
    _thread["token"] = TOKEN
    _thread["t"] = threading.Thread(target=_loop, args=(TOKEN,), daemon=True)
    _thread["t"].start()


def stop():
    _thread["token"] = None
