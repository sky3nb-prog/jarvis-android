"""
Jarvis meldet sich selbst bei Wichtigem – kurz und jeweils nur einmal:
  - Festplatte fast voll (unter 10 % oder unter 15 GB frei), höchstens einmal am Tag pro Laufwerk
  - PC beim Zocken zu heiß (Grafikkarte über 85 °C, über nvidia-smi), höchstens einmal pro Stunde
  - Neues Video von deinen Lieblingskanälen (Einstellung "lieblingskanaele", Standard: Laser Luca) – über den YouTube-RSS-Feed
  - Spiel von deiner Steam-Wunschliste im Angebot (öffentliche Wunschliste, SteamID vom angemeldeten Steam)
Gesagt wird es wie eine Nachricht (nur wenn du am PC sitzt); das Handy bekommt es als Benachrichtigung über pc_handy, wenn möglich.
"""

import json
import os
import re
import shutil
import string
import subprocess
import threading
import time
import urllib.parse
import urllib.request

SAY = None        # vom Programm gesetzt: (text) -> ansagen
SETTINGS = None   # vom Programm gesetzt: () -> Einstellungen
NO_WINDOW = 0x08000000


def _dir():
    import sys
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))


def _state() -> dict:
    try:
        with open(os.path.join(_dir(), "meldungen.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d: dict):
    try:
        with open(os.path.join(_dir(), "meldungen.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


def _get(url, timeout=12) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Jarvis-PC)", "Accept-Language": "de-DE,de;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _say(text: str):
    print("Meldung:", text)
    if SAY:
        try:
            SAY(text)
        except Exception:
            pass


# --- Festplatte ---------------------------------------------------------------------------------------
def check_disks(st: dict):
    today = time.strftime("%Y-%m-%d")
    for L in string.ascii_uppercase[2:]:
        root = f"{L}:\\"
        if not os.path.exists(root):
            continue
        try:
            u = shutil.disk_usage(root)
        except Exception:
            continue
        if u.total < 20e9:
            continue
        free_gb, pct = u.free / 1e9, u.free / u.total * 100
        key = f"disk_{L}"
        if (pct < 10 or free_gb < 15) and st.get(key) != today:
            st[key] = today
            _say(f"Kurzer Hinweis: Auf Laufwerk {L} sind nur noch {free_gb:.0f} Gigabyte frei.")


# --- Temperatur (NVIDIA) ------------------------------------------------------------------------------
def gpu_temp():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW).stdout.strip().splitlines()
        if out:
            t, u = [int(x.strip()) for x in out[0].split(",")[:2]]
            return t, u
    except Exception:
        pass
    return None


def check_heat(st: dict):
    r = gpu_temp()
    if not r:
        return
    t, util = r
    if t >= 85 and util >= 50 and time.time() - st.get("heat_t", 0) > 3600:
        st["heat_t"] = time.time()
        _say(f"Achtung, deine Grafikkarte ist {t} Grad heiß. Vielleicht Lüfter oder Grafikeinstellungen prüfen.")


# --- Lieblingskanäle (YouTube) ------------------------------------------------------------------------
def _channel_id(name: str, st: dict):
    ids = st.setdefault("yt_ids", {})
    if name in ids:
        return ids[name]
    cid = None
    for handle in (re.sub(r"\s+", "", name), re.sub(r"\s+", "_", name)):
        try:
            html = _get(f"https://www.youtube.com/@{urllib.parse.quote(handle)}")
            m = re.search(r'"(?:externalId|channelId)":"(UC[\w-]{20,})"', html) or re.search(r'channel/(UC[\w-]{20,})', html)
            if m:
                cid = m.group(1)
                break
        except Exception:
            continue
    if not cid:
        try:
            html = _get("https://www.youtube.com/results?search_query=" + urllib.parse.quote(name) + "&sp=EgIQAg%253D%253D")
            m = re.search(r'"channelId":"(UC[\w-]{20,})"', html)
            cid = m.group(1) if m else None
        except Exception:
            pass
    if cid:
        ids[name] = cid
    return cid


def check_youtube(st: dict):
    s = SETTINGS() if SETTINGS else {}
    names = [n.strip() for n in str(s.get("lieblingskanaele") or "Laser Luca").split(",") if n.strip()]
    seen = st.setdefault("yt_seen", {})
    for n in names:
        cid = _channel_id(n, st)
        if not cid:
            continue
        try:
            xml = _get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}")
        except Exception:
            continue
        m = re.search(r"<entry>.*?<yt:videoId>([\w-]+)</yt:videoId>.*?<title>(.*?)</title>.*?<published>(.*?)</published>", xml, re.S)
        if not m:
            continue
        vid, title = m.group(1), re.sub(r"&amp;", "&", m.group(2))
        if seen.get(cid) is None:          # erster Blick: nur merken, nicht melden
            seen[cid] = vid
            continue
        if seen.get(cid) != vid:
            seen[cid] = vid
            _say(f"Neues Video von {n}: {title}")


# --- Steam-Wunschliste --------------------------------------------------------------------------------
def _steam_id():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess") as k:
            uid = int(winreg.QueryValueEx(k, "ActiveUser")[0])
            if uid > 0:
                return str(76561197960265728 + uid)
    except Exception:
        pass
    return None


def check_steam(st: dict):
    sid = (SETTINGS() or {}).get("steam_id") if SETTINGS else None
    sid = sid or _steam_id() or st.get("steam_id")
    if not sid:
        return
    st["steam_id"] = sid
    try:
        data = json.loads(_get(f"https://api.steampowered.com/IWishlistService/GetWishlist/v1/?steamid={sid}"))
        apps = [str(i.get("appid")) for i in (data.get("response") or {}).get("items", [])][:60]
    except Exception:
        return
    sale = st.setdefault("steam_sale", {})
    for i in range(0, len(apps), 20):
        chunk = apps[i:i + 20]
        try:
            d = json.loads(_get("https://store.steampowered.com/api/appdetails?filters=price_overview&cc=de&appids=" + ",".join(chunk)))
        except Exception:
            continue
        for a in chunk:
            po = ((d.get(a) or {}).get("data") or {}).get("price_overview") if isinstance(d.get(a), dict) else None
            if not po:
                continue
            disc = int(po.get("discount_percent") or 0)
            if disc >= 20 and sale.get(a) != disc:
                sale[a] = disc
                try:
                    name = json.loads(_get(f"https://store.steampowered.com/api/appdetails?appids={a}&filters=basic&cc=de")).get(a, {}).get("data", {}).get("name") or "Ein Spiel"
                except Exception:
                    name = "Ein Spiel"
                _say(f"Steam-Angebot: {name} von deiner Wunschliste ist {disc} Prozent günstiger, jetzt {po.get('final_formatted', '')}.")
            elif disc == 0 and a in sale:
                sale.pop(a, None)


def start(stop: threading.Event):
    def loop():
        time.sleep(180)
        n = 0
        while not stop.is_set():
            st = _state()
            for f, every in ((check_heat, 1), (check_disks, 30), (check_youtube, 15), (check_steam, 360)):
                if n % every == 0:
                    try:
                        f(st)
                    except Exception as e:
                        print("Meldungen:", f.__name__, e)
            _save(st)
            n += 1
            stop.wait(120)   # alle 2 Minuten (Temperatur), Rest seltener
    threading.Thread(target=loop, daemon=True).start()
