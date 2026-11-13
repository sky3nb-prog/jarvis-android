"""
Verbindung zur Jarvis-Handy-App: gleiches Gedächtnis, gleiche Persönlichkeit.

Der PC schickt regelmäßig, was Jarvis über dich weiß (Fakten, Stimmungen, Art, Anrede, Adresse), verschlüsselt
über ntfy.sh (kostenlos, ohne Konto) an die App. Was du dem Handy erzählst ("merk dir ..."), kommt zurück auf den PC.

Zugang ist ein Kopplungscode (Einstellungen > Handy-App). Daraus werden Kanalname und Schlüssel abgeleitet;
ohne Code kann niemand mitlesen. Den Code nicht weitergeben.
Verschlüsselung nur mit Python-Bordmitteln: zlib + HMAC-SHA256-Stromverschlüsselung + HMAC-Prüfsumme.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.request
import zlib

import pc_memory
from pc_apps import base_dir

SERVER = "https://ntfy.sh/"
FILE = "handy_app.json"
POLL = 30            # Sekunden zwischen zwei Blicken nach Nachrichten vom Handy
RESEND = 2 * 3600    # spätestens so oft neu senden (ntfy hält große Nachrichten nur ca. 3 Stunden)
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

_lock = threading.Lock()
_started = False
STATUS = ""


# --- Code und Schlüssel ---------------------------------------------------------------------
def _state() -> dict:
    try:
        with open(os.path.join(base_dir(), FILE), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(st: dict):
    try:
        with open(os.path.join(base_dir(), FILE), "w", encoding="utf-8") as f:
            json.dump(st, f)
    except Exception:
        pass


def code(new: bool = False) -> str:
    """Kopplungscode wie ABCD-EFGH-JKLM-NPQR (wird beim ersten Mal erzeugt)."""
    with _lock:
        st = _state()
        if new or not st.get("code"):
            raw = "".join(secrets.choice(ALPHABET) for _ in range(16))
            st = {"code": "-".join(raw[i:i + 4] for i in range(0, 16, 4))}
            _save_state(st)
        return st["code"]


def _norm(c: str) -> str:
    return "".join(ch for ch in c.upper() if ch.isalnum())


def _keys(c: str):
    n = _norm(c).encode()
    topic = "jv" + hashlib.sha256(b"jarvis-topic:" + n).hexdigest()[:30]
    return topic, hashlib.sha256(b"jarvis-enc:" + n).digest(), hashlib.sha256(b"jarvis-mac:" + n).digest()


def _stream(k: bytes, nonce: bytes, n: int) -> bytes:
    out, i = bytearray(), 0
    while len(out) < n:
        out += hmac.new(k, nonce + i.to_bytes(4, "big"), hashlib.sha256).digest()
        i += 1
    return bytes(out[:n])


def encrypt(obj: dict, c: str) -> str:
    _, ke, km = _keys(c)
    pt = zlib.compress(json.dumps(obj, ensure_ascii=False).encode("utf-8"), 9)
    nonce = secrets.token_bytes(16)
    ct = bytes(a ^ b for a, b in zip(pt, _stream(ke, nonce, len(pt))))
    tag = hmac.new(km, nonce + ct, hashlib.sha256).digest()[:16]
    return "J1." + base64.urlsafe_b64encode(nonce + ct + tag).decode().rstrip("=")


def decrypt(text: str, c: str):
    if not text.startswith("J1."):
        return None
    _, ke, km = _keys(c)
    s = text[3:].strip()
    raw = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    nonce, ct, tag = raw[:16], raw[16:-16], raw[-16:]
    if not hmac.compare_digest(tag, hmac.new(km, nonce + ct, hashlib.sha256).digest()[:16]):
        return None
    pt = bytes(a ^ b for a, b in zip(ct, _stream(ke, nonce, len(ct))))
    return json.loads(zlib.decompress(pt).decode("utf-8"))


# --- Übertragung ------------------------------------------------------------------------------
def _req(url: str, data: bytes = None):
    r = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    r.add_header("User-Agent", "Jarvis-PC")
    with urllib.request.urlopen(r, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")


def snapshot() -> dict:
    """Alles, was die Handy-App über dich und über Jarvis wissen soll."""
    import pc_settings
    import pc_steuerung
    import pc_talk

    s = pc_settings.load()
    data = pc_memory._load()
    persona = getattr(pc_steuerung, "PERSONA", "sarkastisch")
    prof = {k: v for k, v in (data.get("profile") or {}).items() if k in ("vorname", "nachname", "name", "ort", "plz", "adresse")}
    return {
        "kind": "snap", "from": "pc", "ts": int(time.time()),
        "name": (pc_talk.NAME or "Jarvis").replace(".", ""),
        "address": pc_talk.ADDRESS or "",
        "persona": persona,
        "persona_text": pc_steuerung.PERSONAS.get(persona, ""),
        "facts": [f["text"] for f in data.get("facts", [])][-300:],
        "dates": [{"text": f["text"], "date": f["date"]} for f in data.get("facts", []) if f.get("date")][-60:],
        "moods": (data.get("moods") or [])[-10:],
        "profile": prof,
        "home": (s.get("home_address") or "").strip(),
        "city": (s.get("home_city") or "Leonberg").strip(),
        "places": s.get("lage_places") or [],
        "settings": shared_settings(s),
        "settings_ts": _settings_ts(s),
        "pc_media": _media_summary(),
        "fragen": _recent_questions(),
    }


# --- Gemeinsame Einstellungen (Handy <-> PC): wer zuletzt geändert hat, gewinnt -----------------------
# Handy-Name -> PC-Einstellung
SHARED = {"city": "home_city", "address": "home_address", "anrede": "address_as", "assistant_name": "assistant_name",
          "lage_orte": "lage_places", "themen_selbst": "themen_selbst", "lage_spin": "lage_spin",
          "lage_labels": "map_labels", "lage_jump": "globe_auto_open", "lage_zoom": "lage_sat_tour", "lage_orbits": "lage_orbits",
          "orte": "meine_orte", "wege": "meine_wege", "route_an": "route_an",
          "wichtig": "wichtige_leute", "absage": "absage_text"}
ON_SETTINGS = None   # vom Programm gesetzt: übernimmt geänderte Einstellungen (im Tk-Thread)


def shared_settings(s: dict) -> dict:
    out = {}
    for phone_key, pc_key in SHARED.items():
        v = s.get(pc_key)
        if pc_key in ("lage_places", "themen_selbst"):
            v = ", ".join(v or [])
        elif pc_key == "assistant_name":
            v = (v or "").replace(".", "")
        elif v is None:
            continue
        out[phone_key] = v
    return out


def _settings_ts(s: dict) -> int:
    """Zeitpunkt der letzten Änderung der gemeinsamen Einstellungen (merkt sich eine Prüfsumme)."""
    dig = hashlib.sha256(json.dumps(shared_settings(s), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    st = _state()
    if st.get("set_digest") != dig:
        st.update(set_digest=dig, set_ts=int(time.time()))
        _save_state(st)
    return int(st.get("set_ts") or 0)


def apply_phone_settings(msg: dict) -> bool:
    """Einstellungen vom Handy übernehmen, wenn sie neuer sind als die am PC."""
    import pc_settings
    ts = int(msg.get("ts") or 0)
    s = pc_settings.load()
    if ts <= _settings_ts(s):
        return False
    new = dict(s)
    for phone_key, val in (msg.get("settings") or {}).items():
        pc_key = SHARED.get(phone_key)
        if not pc_key:
            continue
        if pc_key in ("home_city",) and not str(val).strip():
            continue   # leerer Wohnort = nichts ändern
        if pc_key in ("lage_places", "themen_selbst"):
            val = [x.strip() for x in str(val).split(",") if x.strip()]
        elif pc_key == "assistant_name":
            val = str(val).strip() or s.get("assistant_name")
            if val and "." not in val and val.upper() == "JARVIS":
                val = "J.A.R.V.I.S."
        new[pc_key] = val
    if ON_SETTINGS:
        ON_SETTINGS(new)
    else:
        pc_settings.save(new)
    st = _state()   # die Änderung kommt vom Handy: ihren Zeitpunkt übernehmen (sonst schicken wir sie als "neu" zurück)
    st.update(set_digest=hashlib.sha256(json.dumps(shared_settings(new), sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
              set_ts=ts)
    _save_state(st)
    return True


def _media_summary():
    try:
        import pc_media
        return pc_media.summary()
    except Exception:
        return {}


def _recent_questions():
    try:
        import pc_themen
        return pc_themen.recent(40)
    except Exception:
        return []


def publish(force: bool = False) -> bool:
    """Schickt den aktuellen Stand ans Handy (nur wenn sich etwas geändert hat oder es Zeit wird)."""
    global STATUS
    c = code()
    snap = snapshot()
    # Wichtiges (Gedächtnis, Einstellungen) sofort; was du hörst und fragst, höchstens alle 30 Minuten (spart Nachrichten)
    soft = ("ts", "pc_media", "fragen")
    digest = hashlib.sha256(json.dumps({k: v for k, v in snap.items() if k not in soft}, sort_keys=True,
                                       ensure_ascii=False).encode()).hexdigest()
    soft_digest = hashlib.sha256(json.dumps({k: snap.get(k) for k in soft[1:]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    st = _state()
    age = time.time() - st.get("sent", 0)
    if not force and st.get("digest") == digest and age < RESEND and (st.get("soft") == soft_digest or age < 1800):
        return False
    topic, _, _ = _keys(c)
    _req(SERVER + topic, encrypt(snap, c).encode())
    st = _state()
    st.update({"digest": digest, "soft": soft_digest, "sent": time.time()})
    _save_state(st)
    STATUS = time.strftime("Zuletzt ans Handy geschickt: %H:%M Uhr")
    return True


def _known(text: str) -> bool:
    t = text.strip().lower().rstrip(".!")
    return any(f.strip().lower().rstrip(".!") == t for f in pc_memory.facts())


def _apply(msg: dict) -> bool:
    """Neues vom Handy übernehmen. True = etwas geändert."""
    changed = False
    for f in msg.get("facts") or []:
        text = str(f.get("text") if isinstance(f, dict) else f).strip()
        if text and not _known(text):
            pc_memory.remember(text, (f.get("date") if isinstance(f, dict) else None) or None)
            changed = True
    for m in msg.get("moods") or []:
        text = str(m.get("text") if isinstance(m, dict) else m).strip()
        if text:
            pc_memory.set_mood(text)
            changed = True
    for f in msg.get("forget") or []:
        if str(f).strip():
            changed = pc_memory.forget(str(f)) > 0 or changed
    return changed


def poll_once():
    c = code()
    topic, _, _ = _keys(c)
    st = _state()
    since = st.get("since") or "12h"
    body = _req(f"{SERVER}{topic}/json?poll=1&since={since}")
    last, changed = since, False
    for line in body.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") != "message":
            continue
        last = ev.get("id") or last
        text = ev.get("message") or ""
        if not text.startswith("J1."):
            continue  # große Nachrichten (Anhänge) schickt nur der PC selbst
        try:
            msg = decrypt(text, c)
        except Exception:
            msg = None
        if msg and msg.get("from") == "phone" and msg.get("kind") == "add":
            changed = _apply(msg) or changed
        elif msg and msg.get("from") == "phone" and msg.get("kind") == "settings":
            try:
                changed = apply_phone_settings(msg) or changed
            except Exception as e:
                print(f"Handy-Einstellungen nicht übernommen: {e}")
        elif msg and msg.get("from") == "phone" and msg.get("kind") == "themen":
            try:
                import pc_themen
                pc_themen.set_from_phone(msg.get("themen") or [])
            except Exception:
                pass
    st = _state()
    st["since"] = last
    _save_state(st)
    if changed:
        publish(force=True)


def _loop(stop):
    global STATUS
    time.sleep(8)
    while not stop.is_set():
        try:
            poll_once()
            publish()
        except Exception as e:
            STATUS = f"Handy-App gerade nicht erreichbar ({type(e).__name__})."
        stop.wait(POLL)


def start(stop: threading.Event):
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, args=(stop,), daemon=True).start()


if __name__ == "__main__":
    c = code()
    print("Kopplungscode:", c)
    t = encrypt({"x": "Grüße"}, c)
    print(decrypt(t, c))
