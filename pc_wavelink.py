"""
Lautstärke in Elgato Wave Link steuern (statt der Windows-Lautstärke):

  "Musik lauter" / "Discord leiser" / "Game auf 40 Prozent" / "Browser stumm" / "System wieder an"
  "Mach mich lauter" / "mach mich leiser" / "Mikro stumm"   -> Verstärkung (Gain) deines Mikrofons
  "Insgesamt lauter" / "alles leiser"                       -> Hauptausgang (was du hörst)

Wave Link hat eine lokale Schnittstelle (WebSocket, JSON-RPC), die auch das Stream Deck benutzt. Sie ist nur auf
diesem PC erreichbar. Unterstützt werden Wave Link 3 (aktuell) und – so gut es geht – die alten Versionen 1/2.
Läuft Wave Link nicht, macht Jarvis wie bisher die Windows-Lautstärke.
"""

import glob
import json
import os
import re
import threading
import time

STEP = 0.10      # so viel pro "lauter"/"leiser" (10 %)
MIC_STEP = 0.06  # Mikrofon etwas feiner
WL3_PORTS = list(range(1884, 1894))
WL1_PORTS = list(range(1824, 1834))
ORIGIN = "streamdeck://"

# gesprochenes Wort -> Wörter, die im Namen des Wave-Link-Kanals (oder einer App darin) vorkommen können
TARGETS = {
    "musik": ["music", "musik", "deezer", "spotify", "apple music", "tidal"],
    "discord": ["discord", "voice", "chat", "teamspeak"],
    "system": ["system", "pc"],
    "game": ["game", "spiel", "gaming"],
    "browser": ["browser", "chrome", "edge", "firefox", "opera"],
    "sfx": ["sfx", "sound", "effekt"],
    "aux": ["aux"],
}
SPOKEN = {  # was der Nutzer sagt -> Ziel
    "musik": "musik", "music": "musik", "deezer": "musik", "spotify": "musik", "lied": "musik", "song": "musik",
    "discord": "discord", "chat": "discord", "voice": "discord", "teamspeak": "discord", "call": "discord",
    "system": "system", "pc": "system", "windows": "system", "systemsound": "system",
    "game": "game", "spiel": "game", "games": "game", "zocken": "game",
    "browser": "browser", "chrome": "browser", "youtube": "browser", "video": "browser",
    "sfx": "sfx", "effekte": "sfx", "soundboard": "sfx",
}

_lock = threading.Lock()
_conn = {"ws": None, "ver": 0, "id": 0, "fail": 0.0}


# --- Verbindung -------------------------------------------------------------------------------------
def _ws_info_ports():
    ports = []
    base = os.environ.get("LOCALAPPDATA", "")
    for path in glob.glob(os.path.join(base, "Packages", "Elgato.WaveLink*", "LocalState", "ws-info.json")):
        try:
            with open(path, encoding="utf-8") as f:
                p = int(json.load(f).get("port"))
            if p not in ports:
                ports.append(p)
        except Exception:
            pass
    return ports


def _open():
    import websocket  # Paket websocket-client (ist schon dabei)

    for ver, ports in ((3, _ws_info_ports() + WL3_PORTS), (1, WL1_PORTS)):
        for port in ports:
            try:
                ws = websocket.create_connection(f"ws://127.0.0.1:{port}", origin=ORIGIN, timeout=1.2)
            except Exception:
                continue
            try:
                _conn.update(ws=ws, ver=ver)
                info = _call_raw("getApplicationInfo", None if ver == 3 else {})
                text = json.dumps(info or {})
                if "EWL" in text or "Wave Link" in text or "WaveLink" in text:
                    ws.settimeout(3.0)
                    return True
            except Exception:
                pass
            try:
                ws.close()
            except Exception:
                pass
            _conn.update(ws=None, ver=0)
    return False


def _call_raw(method, params):
    ws = _conn["ws"]
    _conn["id"] += 1
    rid = _conn["id"]
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        msg["params"] = params
    ws.send(json.dumps(msg))
    t_end = time.time() + 3.0
    while time.time() < t_end:
        raw = ws.recv()
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if data.get("id") != rid:
            continue  # Benachrichtigungen (Pegel usw.) überspringen
        if "error" in data:
            raise RuntimeError(str(data["error"].get("message") or data["error"]))
        return data.get("result")
    raise TimeoutError(method)


def call(method, params=None):
    """Ein Aufruf an Wave Link (verbindet sich bei Bedarf). Wirft eine Ausnahme, wenn Wave Link nicht läuft."""
    with _lock:
        for attempt in range(2):
            if _conn["ws"] is None:
                if time.time() - _conn["fail"] < 20:
                    raise ConnectionError("Wave Link läuft nicht")
                if not _open():
                    _conn["fail"] = time.time()
                    raise ConnectionError("Wave Link läuft nicht")
            try:
                return _call_raw(method, params)
            except Exception:
                try:
                    _conn["ws"].close()
                except Exception:
                    pass
                _conn["ws"] = None
                if attempt:
                    raise


def available() -> bool:
    try:
        call("getApplicationInfo", None if _conn["ver"] == 3 else {})
        return True
    except Exception:
        return False


# --- Wave Link 3 ------------------------------------------------------------------------------------
def _match(target, name, apps=()):
    words = TARGETS.get(target, [target])
    hay = " ".join([str(name or "").lower()] + [str(a).lower() for a in apps])
    return any(w in hay for w in words)


def _channels3():
    res = call("getChannels") or {}
    return res.get("channels", res) if isinstance(res, dict) else res


def _find_channel3(target):
    best = None
    for ch in _channels3() or []:
        apps = [a.get("name", "") for a in (ch.get("apps") or []) if isinstance(a, dict)]
        if _match(target, ch.get("name"), []):
            return ch
        if best is None and _match(target, "", apps):
            best = ch
    return best


def _mic3():
    res = call("getInputDevices") or {}
    devs = res.get("inputDevices", []) if isinstance(res, dict) else res
    devs = sorted(devs, key=lambda d: not d.get("isWaveDevice"))
    for d in devs:
        for inp in d.get("inputs") or []:
            if inp.get("gain") is not None:
                return d, inp
    return None, None


def _main_output3():
    res = call("getOutputDevices") or {}
    main = res.get("mainOutput") or {}
    for d in res.get("outputDevices") or []:
        for o in d.get("outputs") or []:
            if d.get("id") == main.get("outputDeviceId") and o.get("id") == main.get("outputId"):
                return d, o
    for d in res.get("outputDevices") or []:
        for o in d.get("outputs") or []:
            return d, o
    return None, None


def _new_level(cur, what, value, step):
    cur = float(cur or 0.0)
    if what == "up":
        return min(1.0, cur + step)
    if what == "down":
        return max(0.0, cur - step)
    if what == "set" and value is not None:
        return max(0.0, min(1.0, float(value) / 100.0))
    return cur


def _pct(v):
    return f"{int(round(float(v) * 100))} Prozent"


def _do3(target, what, value):
    if target == "mic":
        d, inp = _mic3()
        if not inp:
            return "Ich finde in Wave Link kein Mikrofon."
        if what in ("mute", "unmute"):
            call("setInputDevice", {"id": d["id"], "inputs": [{"id": inp["id"], "isMuted": what == "mute"}]})
            return "Mikrofon stumm." if what == "mute" else "Mikrofon wieder an."
        if inp.get("isGainLockOn"):
            return "Die Verstärkung deines Mikrofons ist in Wave Link gesperrt (Gain Lock)."
        g = inp.get("gain") or {}
        lo, hi = float(g.get("min", 0.0) or 0.0), float(g.get("max", 1.0) or 1.0)
        cur = (float(g.get("value", 0.0)) - lo) / max(1e-9, hi - lo)
        new = _new_level(cur, what, value, MIC_STEP)
        call("setInputDevice", {"id": d["id"], "inputs": [{"id": inp["id"], "gain": {"value": lo + new * (hi - lo)}}]})
        return f"Dein Mikrofon steht jetzt auf {_pct(new)}."
    if target == "gesamt":
        d, o = _main_output3()
        if not o:
            return "Ich finde in Wave Link keinen Ausgang."
        if what in ("mute", "unmute"):
            upd = {"id": d["id"], "outputs": [{"id": o["id"], "isMuted": what == "mute"}]}
            text = "Alles stumm." if what == "mute" else "Ton wieder an."
        else:
            new = _new_level(o.get("level"), what, value, STEP)
            upd = {"id": d["id"], "outputs": [{"id": o["id"], "level": new}]}
            text = f"Gesamtlautstärke {_pct(new)}."
        try:
            call("setOutputDevice", {"outputDevice": upd})
        except RuntimeError:
            call("setOutputDevice", upd)
        return text
    ch = _find_channel3(target)
    if not ch:
        return None
    name = ch.get("name") or target.title()
    if what in ("mute", "unmute"):
        call("setChannel", {"id": ch["id"], "isMuted": what == "mute"})
        return f"{name} stumm." if what == "mute" else f"{name} wieder an."
    new = _new_level(ch.get("level"), what, value, STEP)
    call("setChannel", {"id": ch["id"], "level": new})
    return f"{name} auf {_pct(new)}."


# --- Wave Link 1/2 (alte Schnittstelle) ------------------------------------------------------------------
def _do1(target, what, value):
    mix = "com.elgato.mix.local"
    if target == "mic":
        cfgs = call("getMicrophoneConfig", {}) or []
        cfg = cfgs[0] if isinstance(cfgs, list) and cfgs else cfgs
        if not cfg:
            return "Ich finde in Wave Link kein Mikrofon."
        ident = cfg.get("identifier")
        if what in ("mute", "unmute"):
            call("setInputConfig", {"identifier": ident, "mixerID": mix, "property": "Mute", "value": what == "mute",
                                    "forceLink": False})
            return "Mikrofon stumm." if what == "mute" else "Mikrofon wieder an."
        cur = float(cfg.get("gain", 0)) / 100.0 if float(cfg.get("gain", 0)) > 1 else float(cfg.get("gain", 0))
        new = _new_level(cur, what, value, MIC_STEP)
        call("setMicrophoneConfig", {"identifier": ident, "property": "Microphone Gain", "value": int(round(new * 100))})
        return f"Dein Mikrofon steht jetzt auf {_pct(new)}."
    if target == "gesamt":
        out = call("getOutputConfig", {}) or {}
        cur = float(out.get("localVolumeOut", 50)) / 100.0
        new = _new_level(cur, what, value, STEP)
        call("setOutputConfig", {"property": "Output Level", "mixerID": mix, "value": int(round(new * 100)),
                                 "forceLink": False})
        return f"Gesamtlautstärke {_pct(new)}."
    for cfg in call("getInputConfigs", {}) or []:
        if _match(target, cfg.get("name"), [cfg.get("identifier", "")]):
            ident, name = cfg.get("identifier"), cfg.get("name") or target.title()
            if what in ("mute", "unmute"):
                call("setInputConfig", {"identifier": ident, "mixerID": mix, "property": "Mute", "value": what == "mute",
                                        "forceLink": False})
                return f"{name} stumm." if what == "mute" else f"{name} wieder an."
            new = _new_level(float(cfg.get("localVolumeIn", 50)) / 100.0, what, value, STEP)
            call("setInputConfig", {"identifier": ident, "mixerID": mix, "property": "Volume",
                                    "value": int(round(new * 100)), "forceLink": False})
            return f"{name} auf {_pct(new)}."
    return None


def set_volume(target: str, what: str, value=None):
    """target: musik, discord, system, game, browser, sfx, mic, gesamt (oder ein Kanalname aus Wave Link).
    what: up, down, set (value in Prozent), mute, unmute. Gibt eine Antwort zurück oder None (kein solcher Kanal)."""
    target = SPOKEN.get(target.lower().strip(), target.lower().strip())
    call("getApplicationInfo", None if _conn["ver"] == 3 else {})  # verbindet bei Bedarf
    return _do3(target, what, value) if _conn["ver"] == 3 else _do1(target, what, value)


# --- Sprache -------------------------------------------------------------------------------------------
def parse(text: str):
    """"Musik lauter" -> ("musik", "up", None); "mach mich leiser" -> ("mic", "down", None). Sonst None."""
    low = " " + re.sub(r"[^\wäöüß%]+", " ", text.lower()) + " "
    if re.search(r"\b(sprich|deine stimme|du bist zu)\b", low):
        return None  # Jarvis' eigene Stimme, nicht Wave Link
    what, value = None, None
    m = re.search(r"\bauf (\d{1,3}) ?(?:prozent|%)", low)
    if m:
        what, value = "set", int(m.group(1))
    elif re.search(r"\b(stumm|mute|muten)\b", low) and not re.search(r"\bnicht mehr stumm\b", low):
        what = "mute"
    elif re.search(r"\b(wieder an|nicht mehr stumm|unmute|ton an)\b", low):
        what = "unmute"
    elif re.search(r"\b(lauter|aufdrehen|hochdrehen)\b", low) or re.search(r"\b(musik|discord|game|spiel|browser|system|mikro\w*) hoch\b", low):
        what = "up"
    elif re.search(r"\b(leiser|runterdrehen|zu laut)\b", low) or re.search(r"\b(musik|discord|game|spiel|browser|system|mikro\w*) runter\b", low):
        what = "down"
    if not what:
        return None
    if re.search(r"\b(mich|mikro|mikrofon|mic|meine stimme|mein mikro)\b", low):
        return "mic", what, value
    for word, target in SPOKEN.items():
        if re.search(rf"\b{word}\b", low):
            return target, what, value
    if re.search(r"\b(insgesamt|alles|gesamt|gesamtlautstärke|kopfhörer|monitor)\b", low):
        return "gesamt", what, value
    if what in ("up", "down", "set") and len(low.split()) <= 3:  # nur "lauter" / "mach leiser": alles, was du hörst
        return "gesamt", what, value
    return None


# --- Mixe (z. B. "Ich", "Miku") und Kanäle mit Nummer ("Musik 2") ------------------------------------------
NUMS = {"eins": "1", "ein": "1", "erste": "1", "zwei": "2", "zweite": "2", "drei": "3", "dritte": "3", "vier": "4",
        "fünf": "5", "sechs": "6", "sieben": "7", "acht": "8", "neun": "9", "zehn": "10"}
WORD_ALIAS = {"music": "musik", "musics": "musik", "games": "game", "spiel": "game", "chat": "discord", "voice": "discord",
              "sounds": "sfx", "mikro": "mic", "mikrofon": "mic", "mich": "mic", "micro": "mic", "mein": "mein"}
MIC_WORDS = ("mic", "elgato", "wave", "xlr", "dji", "mikro", "mikrofon", "rode", "shure")
_cache = {"t": 0.0, "mixes": [], "channels": []}


def _tokens(text: str) -> list:
    out = []
    low = re.sub(r"[^\wäöüß]+", " ", text.lower())
    low = re.sub(r"\b(lu an|lu ann|luhan|louan|luann|luan's|luans)\b", "luan", low)  # so hört die Spracherkennung "Luan" oft
    for w in low.split():
        w = NUMS.get(w, w)
        out.append(WORD_ALIAS.get(w, w))
    return out


def _category(tokens) -> str:
    for t in tokens:
        for key, words in TARGETS.items():
            if t == key or t in words:
                return key
        if t in SPOKEN:
            return SPOKEN[t]
    return ""


DEFAULT_MIX = "Luan"  # dein eigener Mix: ohne Mix-Namen ändert Jarvis nur hier etwas


def _default_mix(mixes):
    """Dein Mix: der mit dem Namen aus DEFAULT_MIX, sonst der, der auf deinem Hauptausgang (Kopfhörer) liegt."""
    for m in mixes:
        if str(m.get("name") or "").strip().lower() == DEFAULT_MIX.lower():
            return m
    try:
        d, o = _main_output3()
        mid = (o or {}).get("mixId")
        for m in mixes:
            if m.get("id") == mid:
                return m
    except Exception:
        pass
    return None


def _live(force=False):
    """Mixe und Kanäle aus Wave Link 3 (30 Sekunden zwischengespeichert)."""
    if force or time.time() - _cache["t"] > 30:
        call("getApplicationInfo", None if _conn["ver"] == 3 else {})
        if _conn["ver"] != 3:
            return [], []
        res = call("getMixes") or {}
        _cache["mixes"] = res.get("mixes", []) if isinstance(res, dict) else res
        _cache["channels"] = _channels3() or []
        _cache["t"] = time.time()
    return _cache["mixes"], _cache["channels"]


def _find_mix(tokens, mixes):
    """Welcher Mix ist gemeint? "Ich" zählt nur am Anfang oder nach in/im/bei/auf/für (sonst ist es nur "ich")."""
    before = ("in", "im", "bei", "auf", "für", "mix", "meinem", "beim")
    try:
        import pc_settings

        wake = {w.lower() for w in (pc_settings.load().get("wake_words") or ["jarvis"])}
    except Exception:
        wake = {"jarvis"}
    for i, t in enumerate(tokens):  # "bei mir" / "in meinem Mix" = dein eigener Mix
        if (t == "mir" and i and tokens[i - 1] in ("bei", "für")) or (t == "mix" and i and tokens[i - 1] in ("meinem", "mein")):
            m = _default_mix(mixes)
            if m:
                return m, {i - 1, i}
    for m in mixes:
        mt = _tokens(m.get("name") or "")
        if not mt:
            continue
        n = len(mt)
        for i in range(len(tokens) - n + 1):
            if tokens[i:i + n] == mt:
                prev = tokens[i - 1] if i else ""
                if mt == ["ich"] and not (i == 0 or prev in before):
                    continue  # "ich will ..." ist kein Mix
                if " ".join(mt) in wake and prev not in before:
                    continue  # "Jarvis, ..." ist das Aktivierungswort, nicht der Mix "Jarvis"
                return m, set(range(i, i + n))
    return None, set()


def _find_channel(tokens, channels):
    """Bester Kanal zu den Wörtern; "Musik 2" trifft nur einen Kanal mit der 2 im Namen."""
    num = None
    for i, t in enumerate(tokens):
        if t.isdigit() and i > 0 and not tokens[i - 1] in ("auf",) and not (i + 1 < len(tokens) and tokens[i + 1] in ("prozent",)):
            num = t
    cat = _category([t for t in tokens if not t.isdigit()])
    want_mic = "mic" in tokens
    best, score = None, 0
    for ch in channels:
        ct = _tokens(ch.get("name") or "")
        apps = [str(a.get("name", "")).lower() for a in (ch.get("apps") or []) if isinstance(a, dict)]
        cnum = next((t for t in ct if t.isdigit()), None)
        words = [t for t in ct if not t.isdigit() and len(t) >= 2 and t not in ("die", "der", "das", "und")]
        sc = 10 * sum(1 for w in words if w in tokens)
        if want_mic and any(w in " ".join(ct) for w in MIC_WORDS) and "unavailable" not in str(ch).lower():
            sc += 30  # "mich" im Mix = dein Mikrofon-Kanal
        if cat and (_category(ct) == cat or any(w in " ".join(apps) for w in TARGETS.get(cat, []))):
            sc += 5
        if sc == 0:
            continue
        if num:
            if cnum != num:
                continue
            sc += 20
        elif cnum not in (None, "1"):
            sc -= 3  # ohne Nummer lieber den Kanal ohne Nummer
        if sc > score:
            best, score = ch, sc
    return best


def _pretty(ch):
    name = re.sub(r"^\d+\s*-\s*", "", str(ch.get("name") or "Kanal"))
    if any(w in name.lower() for w in MIC_WORDS[1:]):
        return "Dein Mikrofon"
    return name


def _set_in_mix(ch, mix, what, value):
    name, mname = _pretty(ch), mix.get("name") or "Mix"
    mname = mname.title() if mname.islower() and len(mname) > 3 else mname
    if mname.lower() == "ich":
        mname = "dir"
    entry = next((m for m in (ch.get("mixes") or []) if (m.get("id") or m.get("mixId")) == mix.get("id")), {})
    if what in ("mute", "unmute"):
        upd = {"isMuted": what == "mute"}
        text = f"{name} bei {mname} {'aus' if what == 'mute' else 'an'}."
    else:
        new = _new_level(entry.get("level", ch.get("level")), what, value, STEP)
        upd = {"level": new}
        text = f"{name} bei {mname} auf {_pct(new)}."
    try:
        call("setChannel", {"id": ch["id"], "mixes": [dict(id=mix["id"], **upd)]})
    except RuntimeError:
        call("setChannel", {"id": ch["id"], "mixes": [dict(mixId=mix["id"], **upd)]})
    _cache["t"] = 0.0
    return text


def _set_global(ch, what, value):
    name = _pretty(ch)
    if what in ("mute", "unmute"):
        call("setChannel", {"id": ch["id"], "isMuted": what == "mute"})
        text = f"{name} {'aus' if what == 'mute' else 'an'}."
    else:
        new = _new_level(ch.get("level"), what, value, STEP)
        call("setChannel", {"id": ch["id"], "level": new})
        text = f"{name} auf {_pct(new)}."
    _cache["t"] = 0.0
    return text


def handle_mix(text: str):
    """"Miku Musik an", "ich Musik 2 leiser", "Musik allgemein lauter" (nur Wave Link 3). None = passt nicht."""
    tokens = _tokens(text)
    if not tokens:
        return None
    mixes, channels = _live()
    if not channels:
        return None
    mix, used = _find_mix(tokens, mixes)
    rest = [t for i, t in enumerate(tokens) if i not in used]
    general = any(t in ("allgemein", "überall", "global", "beide", "alle") for t in rest)
    low = " " + " ".join(rest) + " "
    p = parse(" ".join(rest))
    what, value = (p[1], p[2]) if p else (None, None)
    if not what and (mix or general):  # "Miku Musik an" / "ich Musik aus"
        if re.search(r" (an|ein|anmachen|einschalten|unmuten) ", low):
            what = "unmute"
        elif re.search(r" (aus|ausmachen|ausschalten) ", low):
            what = "mute"
    if not what:
        return None
    ch = _find_channel(rest, channels)
    if ch is None:  # vielleicht gerade einen neuen Kanal oder Mix angelegt -> frisch holen
        mixes, channels = _live(force=True)
        if not mix:
            mix, used = _find_mix(tokens, mixes)
        ch = _find_channel(rest, channels)
    if ch is None:
        if mix or general:
            return "Diesen Kanal finde ich in Wave Link nicht."
        return None
    if general:  # nur wenn du es ausdrücklich sagst: "Musik allgemein lauter"
        return _set_global(ch, what, value)
    mix = mix or _default_mix(mixes)  # sonst immer nur dein eigener Mix (Luan)
    if mix:
        return _set_in_mix(ch, mix, what, value)
    return _set_global(ch, what, value)


def _names_a_mix(text: str) -> bool:
    try:
        mixes, _ = _live()
        return _find_mix(_tokens(text), mixes)[0] is not None
    except Exception:
        return False


def handle(text: str):
    """Antwort für Wave-Link-Befehle oder None (dann macht Jarvis wie bisher weiter)."""
    try:
        mic = re.search(r"\b(mich|mikro|mikrofon|mic)\b", text.lower())
        if not mic or re.search(r"\b(allgemein|überall)\b", text.lower()) or _names_a_mix(text):
            r = handle_mix(text)  # "Miku mich leiser" = dein Mikrofon-Kanal im Mix von Miku
            if r:
                return r
    except ConnectionError:
        return None
    except Exception as e:
        print(f"Wave Link (Mixe): {e}")
    p = parse(text)
    if not p:
        return None
    try:
        return set_volume(*p)
    except ConnectionError:
        return None  # Wave Link läuft nicht -> Windows-Lautstärke wie bisher
    except Exception as e:
        return f"Wave Link hat nicht mitgemacht: {e}"


if __name__ == "__main__":
    for t in ["Musik lauter", "mach Discord leiser", "Game auf 40 Prozent", "mach mich lauter", "Browser stumm",
              "alles leiser", "sprich lauter", "mach lauter"]:
        print(t, "->", parse(t))


# --- Für die Handy-Fernbedienung: alle Regler auf einmal lesen und einzeln setzen ---------------------
def snapshot():
    """{"mixes": [{id, name}], "mine": id, "channels": [{id, name, level, muted, mixes: {mixId: {level, muted}}}],
    "mic": {level, muted}, "gesamt": {level, muted}} – nur mit Wave Link 3, sonst None."""
    try:
        mixes, channels = _live(force=True)
    except Exception:
        return None
    if not channels:
        return None
    mine = _default_mix(mixes) or {}
    out = {"mixes": [{"id": m.get("id"), "name": m.get("name") or "Mix"} for m in mixes], "mine": mine.get("id"), "channels": []}
    for ch in channels:
        per = {}
        for m in ch.get("mixes") or []:
            mid = m.get("id") or m.get("mixId")
            if mid:
                per[mid] = {"level": round(float(m.get("level", 0) or 0), 3), "muted": bool(m.get("isMuted"))}
        out["channels"].append({"id": ch.get("id"), "name": _pretty(ch), "level": round(float(ch.get("level", 0) or 0), 3),
                                "muted": bool(ch.get("isMuted")), "mixes": per})
    try:
        d, inp = _mic3()
        if inp:
            g = inp.get("gain") or {}
            lo, hi = float(g.get("min", 0.0) or 0.0), float(g.get("max", 1.0) or 1.0)
            out["mic"] = {"level": round((float(g.get("value", 0.0)) - lo) / max(1e-9, hi - lo), 3), "muted": bool(inp.get("isMuted"))}
        d, o = _main_output3()
        if o:
            out["gesamt"] = {"level": round(float(o.get("level", 0) or 0), 3), "muted": bool(o.get("isMuted"))}
    except Exception:
        pass
    return out


def remote_set(ch_id: str, mix_id=None, level=None, mute=None) -> str:
    """Ein Regler vom Handy: level 0..1 oder mute True/False. ch_id "mic" / "gesamt" für Mikrofon und Gesamt."""
    what = ("mute" if mute else "unmute") if mute is not None else "set"
    value = None if level is None else max(0.0, min(100.0, float(level) * 100))
    if ch_id in ("mic", "gesamt"):
        return _do3(ch_id, what, value) or ""
    mixes, channels = _live(force=True)
    ch = next((c for c in channels if c.get("id") == ch_id), None)
    if not ch:
        return "Den Kanal finde ich in Wave Link nicht mehr."
    mix = next((m for m in mixes if m.get("id") == mix_id), None) if mix_id else None
    return _set_in_mix(ch, mix, what, value) if mix else _set_global(ch, what, value)

