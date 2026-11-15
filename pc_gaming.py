"""
Gaming-Wochenrückblick: Jarvis merkt sich, welches Spiel vorne läuft und wie lange (jede Minute, nur wenn du wirklich dran bist).
Erkennt Steam-Spiele (Ordner steamapps\\common + Name aus dem Steam-Manifest), Epic-Spiele und ein paar bekannte Spiele.
Sonntags um 19 Uhr (oder auf Frage: "wie viel hab ich diese Woche gezockt?", "Gaming-Rückblick") sagt er:
Stunden gesamt (und im Vergleich zur Vorwoche), Lieblingsspiel, Top 3, längste Session – ohne Vorwürfe.
Mit Steam-Schlüssel (Einstellungen → Gaming, freiwillig) auch deine neuen Steam-Erfolge der Woche.
Daten: gaming.json neben den Einstellungen.
"""
import ctypes
import json
import os
import re
import threading
import time

SAY = None
SETTINGS = None
_lock = threading.Lock()
_names = {}   # Ordner -> (Name, appid)
KNOWN = {"eurotrucks2.exe": "Euro Truck Simulator 2", "amtrucks.exe": "American Truck Simulator", "minecraft.exe": "Minecraft",
         "javaw.exe": None, "fortniteclient-win64-shipping.exe": "Fortnite", "valorant-win64-shipping.exe": "Valorant",
         "rocketleague.exe": "Rocket League", "gta5.exe": "GTA V", "cs2.exe": "Counter-Strike 2", "robloxplayerbeta.exe": "Roblox"}


def _file() -> str:
    import pc_settings
    return os.path.join(os.path.dirname(pc_settings.path()), "gaming.json")


def _load() -> dict:
    try:
        with open(_file(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"days": {}, "sessions": [], "said": ""}


def _save(d: dict):
    try:
        with open(_file(), "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
    except Exception as e:
        print("Gaming-Statistik speichern ging nicht:", e)


def _foreground():
    """(exe-Pfad, Fenstertitel) des Fensters vorne."""
    try:
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        if not h:
            return None, ""
        n = u.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, buf, n + 1)
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        k = ctypes.windll.kernel32
        hp = k.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not hp:
            return None, buf.value
        try:
            size = ctypes.c_ulong(1024)
            pb = ctypes.create_unicode_buffer(1024)
            if k.QueryFullProcessImageNameW(hp, 0, pb, ctypes.byref(size)):
                return pb.value, buf.value
        finally:
            k.CloseHandle(hp)
        return None, buf.value
    except Exception:
        return None, ""


def _steam_name(path: str):
    m = re.search(r"(.*\\steamapps)\\common\\([^\\]+)", path, re.I)
    if not m:
        return None
    lib, folder = m.group(1), m.group(2)
    if folder in _names:
        return _names[folder]
    name, appid = folder, None
    try:
        for f in os.listdir(lib):
            if f.startswith("appmanifest_") and f.endswith(".acf"):
                txt = open(os.path.join(lib, f), encoding="utf-8", errors="ignore").read()
                if re.search(r'"installdir"\s+"' + re.escape(folder) + '"', txt, re.I):
                    nm = re.search(r'"name"\s+"([^"]+)"', txt)
                    name = nm.group(1) if nm else folder
                    appid = re.search(r'"appid"\s+"(\d+)"', txt).group(1)
                    break
    except Exception:
        pass
    _names[folder] = (name, appid)
    return _names[folder]


def current_game():
    path, title = _foreground()
    if not path:
        return None
    exe = os.path.basename(path).lower()
    if exe in ("steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe"):
        return None
    st = _steam_name(path)
    if st:
        return {"name": st[0], "appid": st[1]}
    if exe == "javaw.exe":
        return {"name": "Minecraft", "appid": None} if "minecraft" in title.lower() else None
    if exe in KNOWN and KNOWN[exe]:
        return {"name": KNOWN[exe], "appid": None}
    m = re.search(r"\\Epic Games\\([^\\]+)\\", path, re.I)
    if m:
        return {"name": m.group(1), "appid": None}
    return None


def _idle() -> float:
    try:
        import pc_nachrichten
        return pc_nachrichten._idle_seconds()
    except Exception:
        return 0.0


def _loop(stop: threading.Event):
    cur = {"name": None, "start": 0.0, "last": 0.0, "appid": None}
    while not stop.wait(60):
        try:
            g = current_game()
            now = time.time()
            active = g and _idle() < 300
            with _lock:
                d = _load()
                if active:
                    day = time.strftime("%Y-%m-%d")
                    dd = d["days"].setdefault(day, {})
                    dd[g["name"]] = dd.get(g["name"], 0) + 1
                    if g.get("appid"):
                        d.setdefault("appids", {})[g["name"]] = g["appid"]
                    if cur["name"] != g["name"] or now - cur["last"] > 600:
                        _close(d, cur)
                        cur.update(name=g["name"], start=now, appid=g.get("appid"))
                    cur["last"] = now
                elif cur["name"] and now - cur["last"] > 600:
                    _close(d, cur)
                    cur.update(name=None)
                # alte Tage aufräumen (nur 60 Tage)
                cut = time.strftime("%Y-%m-%d", time.localtime(now - 60 * 86400))
                for k in [k for k in d["days"] if k < cut]:
                    d["days"].pop(k)
                _save(d)
                lt = time.localtime()
                key = time.strftime("%Y-%W")
                if lt.tm_wday == 6 and lt.tm_hour == 19 and d.get("said") != key and _week_minutes(d, 0) >= 30:
                    d["said"] = key
                    _save(d)
                    if SAY:
                        threading.Thread(target=lambda: SAY(review()), daemon=True).start()
        except Exception as e:
            print("Gaming-Statistik:", e)


def _close(d: dict, cur: dict):
    if cur.get("name") and cur["last"] - cur["start"] >= 300:
        d["sessions"].append({"game": cur["name"], "start": cur["start"], "end": cur["last"]})
        d["sessions"] = d["sessions"][-300:]


def _week_days(back: int):
    """Tage (yyyy-mm-dd) der Woche Mo–So; back=0 diese Woche, 1 letzte."""
    now = time.time()
    lt = time.localtime(now)
    monday = now - lt.tm_wday * 86400 - back * 7 * 86400
    return [time.strftime("%Y-%m-%d", time.localtime(monday + i * 86400)) for i in range(7)]


def _week_minutes(d: dict, back: int, per_game=False):
    tot, games = 0, {}
    for day in _week_days(back):
        for g, m in (d["days"].get(day) or {}).items():
            tot += m
            games[g] = games.get(g, 0) + m
    return (tot, games) if per_game else tot


def _hm(m: int) -> str:
    h, mm = divmod(int(m), 60)
    if not h:
        return f"{mm} Minuten"
    return f"{h} Stunde{'n' if h != 1 else ''}" + (f" {mm}" if mm >= 5 else "")


def _achievements(d: dict, games: dict) -> list:
    """Neue Steam-Erfolge dieser Woche (nur mit eigenem Steam-Schlüssel)."""
    try:
        st = SETTINGS() if SETTINGS else {}
        import pc_secret
        import pc_watch
        import urllib.request
        key = pc_secret.unprotect(st.get("steam_api_key_enc", ""))
        sid = st.get("steam_id") or pc_watch._steam_id()
        if not key or not sid:
            return []
        since = time.mktime(time.strptime(_week_days(0)[0], "%Y-%m-%d"))
        out = []
        for g in sorted(games, key=games.get, reverse=True)[:5]:
            appid = (d.get("appids") or {}).get(g)
            if not appid:
                continue
            u = f"https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v1/?appid={appid}&key={key}&steamid={sid}&l=german"
            js = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Jarvis"}), timeout=15).read())
            for a in (js.get("playerstats") or {}).get("achievements") or []:
                if a.get("achieved") and a.get("unlocktime", 0) >= since:
                    out.append(f"{a.get('name') or a.get('apiname')} ({g})")
        return out[:5]
    except Exception as e:
        print("Steam-Erfolge:", e)
        return []


def review(back: int = 0) -> str:
    with _lock:
        d = _load()
    tot, games = _week_minutes(d, back, True)
    prev = _week_minutes(d, back + 1)
    if tot < 10:
        return "Diese Woche hast du kaum gezockt." if back == 0 else "Letzte Woche hast du kaum gezockt."
    top = sorted(games.items(), key=lambda x: x[1], reverse=True)
    p = [f"{'Diese' if back == 0 else 'Letzte'} Woche hast du {_hm(tot)} gezockt"]
    if prev >= 10:
        diff = tot - prev
        p[0] += f" – {_hm(abs(diff))} {'mehr' if diff > 0 else 'weniger'} als die Woche davor." if abs(diff) >= 30 else ", etwa so viel wie die Woche davor."
    else:
        p[0] += "."
    p.append(f"Dein Lieblingsspiel: {top[0][0]} mit {_hm(top[0][1])}.")
    if len(top) > 1:
        p.append("Top 3: " + ", ".join(f"{g} ({_hm(m)})" for g, m in top[:3]) + ".")
    days = _week_days(back)
    ses = [s for s in d.get("sessions", []) if time.strftime("%Y-%m-%d", time.localtime(s["start"])) in days]
    if ses:
        lng = max(ses, key=lambda s: s["end"] - s["start"])
        wd = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][time.localtime(lng["start"]).tm_wday]
        p.append(f"Längste Session: {_hm((lng['end'] - lng['start']) / 60)} {lng['game']} am {wd}.")
    busiest = max(days, key=lambda dd: sum((d["days"].get(dd) or {}).values()))
    p.append(f"Am meisten am {['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'][days.index(busiest)]}.")
    ach = _achievements(d, games) if back == 0 else []
    if ach:
        p.append("Neue Erfolge: " + ", ".join(ach) + ". Stark.")
    return " ".join(p)


def handle(text: str):
    low = text.lower()
    if re.search(r"wie (viel|lange) hab ich (diese woche |heute |letzte woche )?gezockt|gaming[- ]?(rückblick|statistik|woche)|was hab ich (diese woche )?(am meisten )?gezockt|meine spielzeit", low):
        if "heute" in low:
            with _lock:
                d = _load()
            dd = d["days"].get(time.strftime("%Y-%m-%d")) or {}
            if not dd:
                return "Heute hast du noch nichts gezockt."
            return f"Heute {_hm(sum(dd.values()))}: " + ", ".join(f"{g} {_hm(m)}" for g, m in sorted(dd.items(), key=lambda x: -x[1])) + "."
        return review(1 if "letzte woche" in low else 0)
    return None


def start(stop: threading.Event):
    threading.Thread(target=_loop, args=(stop,), daemon=True, name="gaming").start()
