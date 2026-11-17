"""
Schreibstil am PC: WhatsApp-Chat-Exporte einlesen, die du in den Einstellungen selbst auswählst
(„Chat-Export wählen“). Die .zip von WhatsApp geht direkt (nicht entpacken), eine .txt auch.
Deine Nachrichten (und worauf du geantwortet hast) gehen ans Handy – dort sitzt das Stil-Training – und in den PC-Stil.
"""

import io
import json
import os
import re
import zipfile

from pc_apps import base_dir

LINE = re.compile(r"^\[?(\d{1,2}[./]\d{1,2}[./]\d{2,4}),? (\d{1,2}:\d{2})(?::\d{2})?\]?\s*[-–]?\s*([^:]{1,40}): (.*)$")
NAME = re.compile(r"(?:WhatsApp[- ]Chat mit|WhatsApp Chat with)\s+(.+?)(?:\s*\(\d+\))?$", re.I)
INVIS = re.compile("[‎‏‪-‮]")
SKIP = ("<Medien ausgeschlossen>", "Medien ausgeschlossen", "Diese Nachricht wurde gelöscht", "Du hast diese Nachricht gelöscht", "<Media omitted>", "null",
        "(Datei angehängt)", "(file attached)", ".jpg", ".webp", ".mp4", "Standort:", "location:")
AUDIO = re.compile(r"((?:PTT|AUD)-[\w-]+\.(?:opus|ogg|m4a|mp3))", re.I)
EDITED = re.compile(r"\s*<(?:Diese Nachricht wurde bearbeitet|This message was edited)>\s*$", re.I)
STATE = {"voice": 0}
MAX_VOICE = 120   # so viele Sprachnachrichten wandelt er pro Import höchstens um (Groq, kostenlos aber mit Limit)


def _hist_file():
    return os.path.join(base_dir(), "stil_importiert.json")


def history() -> dict:
    try:
        with open(_hist_file(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _hist_add(chat, n, voice, pairs):
    h = history()
    import time as _t
    old = h.get(chat) or {}
    h[chat] = {"n": max(n, old.get("n", 0)), "voice": max(voice, old.get("voice", 0)), "pairs": max(pairs, old.get("pairs", 0)), "t": int(_t.time())}
    try:
        with open(_hist_file(), "w", encoding="utf-8") as f:
            json.dump(h, f, ensure_ascii=False)
    except Exception:
        pass


def history_text() -> str:
    h = history()
    if not h:
        return "Noch keine Chats importiert."
    import time as _t
    rows = sorted(h.items(), key=lambda kv: -kv[1].get("t", 0))
    return "Importiert: " + " · ".join(f"{c} ({v.get('n', 0)} Nachrichten" + (f", {v['voice']} Sprachnachr." if v.get("voice") else "") +
                                       f", {_t.strftime('%d.%m.', _t.localtime(v.get('t', 0)))})" for c, v in rows[:40])


def _when(d: str, hm: str):
    import datetime as _dt
    try:
        dd, mm, yy = re.split(r"[./]", d)
        y = int(yy) + (2000 if len(yy) == 2 else 0)
        h, mi = hm.split(":")
        return _dt.datetime(y, int(mm), int(dd), int(h), int(mi)).timestamp()
    except Exception:
        return 0.0


def _me_file():
    return os.path.join(base_dir(), "stil_name.json")


def _me() -> str:
    try:
        import pc_settings
        n = str(pc_settings.load().get("wa_name") or "").strip()
        if n:
            return n
    except Exception:
        pass
    try:
        with open(_me_file(), encoding="utf-8") as f:
            return json.load(f).get("me", "")
    except Exception:
        return ""


def _set_me(n: str):
    try:
        with open(_me_file(), "w", encoding="utf-8") as f:
            json.dump({"me": n}, f, ensure_ascii=False)
    except Exception:
        pass


def _read(path: str):
    """(Chat-Name, Text, {Audiodatei: Bytes-Lader}) aus einer .zip (mit oder ohne Medien) oder .txt."""
    base = os.path.splitext(os.path.basename(path))[0]
    if path.lower().endswith(".zip"):
        z = zipfile.ZipFile(path)
        names = [n for n in z.namelist() if n.lower().endswith(".txt")]
        audio = {os.path.basename(n): (lambda n=n: z.read(n)) for n in z.namelist() if AUDIO.search(os.path.basename(n))}
        if not names:
            return base, "", audio
        n = sorted(names, key=lambda x: z.getinfo(x).file_size)[-1]
        return base, io.TextIOWrapper(z.open(n), encoding="utf-8", errors="replace").read(), audio
    with open(path, encoding="utf-8", errors="replace") as f:
        return base, f.read(), {}


def _voice_text(data: bytes) -> str:
    import base64
    import pc_nachrichten
    return pc_nachrichten._transcribe({"audio": base64.b64encode(data).decode()})


def parse(path: str):
    """-> (chat, eigene Nachrichten, Paare [{q, a, ctx}]) oder Fehlertext."""
    base, text, audio = _read(path)
    m = NAME.search(base)
    partner = m.group(1).strip() if m else ""
    msgs = []
    for raw in text.splitlines():
        line = INVIS.sub("", raw)
        x = LINE.match(line)
        if x:
            msgs.append([x.group(3).strip(), EDITED.sub("", x.group(4).strip()), _when(x.group(1), x.group(2)), False])
        elif msgs and line.strip():
            msgs[-1][1] += "\n" + line.strip()
    if not msgs:
        return "In der Datei finde ich keinen WhatsApp-Chat."
    senders = {}
    for mm in msgs:
        senders[mm[0]] = senders.get(mm[0], 0) + 1
    me = _me()
    if me and me not in senders:   # Name aus den Einstellungen etwas anders geschrieben?
        me = next((x for x in senders if x.lower().startswith(me.lower()) or me.lower().startswith(x.lower())), me)
    if (not me or me not in senders) and GUESS.get("me") in senders:
        me = GUESS["me"]
    if not me or me not in senders:
        others = [s for s in senders if partner and s.lower() != partner.lower()]
        if partner and len(senders) == 2 and others:
            me = others[0]
            _set_me(me)
        else:
            return ("Bei dieser Gruppe weiß ich nicht, welcher Name du bist. Trag in den Einstellungen unter Leute → Schreibstil „Dein Name in WhatsApp-Exporten“ ein "
                    "(so, wie du in der Datei stehst) – oder wähl zusammen mit der Gruppe einen Einzelchat aus.")
    chat = partner or next((s for s in senders if s != me), base)
    # Sprachnachrichten (nur bei „Mit Medien“-Export): anhören und als Text einsetzen
    nv = 0
    for mm in msgs:
        a = AUDIO.search(mm[1])
        if a and a.group(1) in audio and nv < MAX_VOICE:
            try:
                t = _voice_text(audio[a.group(1)]())
            except Exception:
                t = ""
            if t:
                mm[1] = t; mm[3] = True; nv += 1
    good = lambda t: 2 <= len(t) <= 300 and not t.startswith("(") and not any(k in t for k in SKIP) and not t.startswith("http")  # noqa: E731
    mine, pairs = [], []
    last = msgs[-4000:]
    for i, (s, t, ts, voice) in enumerate(last):
        if s != me or not good(t):
            continue
        if not voice:
            mine.append(t)   # gesprochene Nachrichten sind kein Schreibstil
        p = last[i - 1] if i > 0 else None
        # nur echte Antworten: direkt davor von der anderen Person und höchstens 6 Stunden später
        if p and p[0] != me and good(p[1]) and (not ts or not p[2] or 0 <= ts - p[2] <= 6 * 3600):
            cx = "\n".join(f"{'ICH' if v == me else v}: {('🎤 ' if vo else '') + w[:150]}" for v, w, tt, vo in last[max(0, i - 4):i - 1]
                           if not ts or not tt or ts - tt <= 12 * 3600)
            pairs.append({"q": f"{p[0]}: {('🎤 ' if p[3] else '') + p[1][:300]}", "a": t, "ctx": cx[:500]})
    STATE["voice"] = nv
    return chat, mine, pairs


GUESS = {"me": ""}


def _senders(path: str) -> set:
    try:
        _, text, _ = _read(path)
        return {m.group(3).strip() for m in (LINE.match(INVIS.sub("", l)) for l in text.splitlines()) if m}
    except Exception:
        return set()


def import_files(paths) -> str:
    import pc_handy
    import pc_nachrichten
    # Wer bist du? Der Name, der in ALLEN gewählten Chats vorkommt (bei 2+ Dateien eindeutig)
    if len(paths) >= 2 and not _me():
        common = None
        for p in paths:
            s = _senders(p)
            common = s if common is None else (common & s)
        if common and len(common) == 1:
            GUESS["me"] = next(iter(common)); _set_me(GUESS["me"])
    # Einzelchats zuerst – daraus lernt er deinen Namen für die Gruppen
    paths = sorted(paths, key=lambda p: 0 if NAME.search(os.path.splitext(os.path.basename(p))[0]) else 1)
    done, errs, sent_ok = 0, [], True
    for p in paths:
        try:
            r = parse(p)
        except Exception as e:
            errs.append(f"{os.path.basename(p)}: {e}")
            continue
        if isinstance(r, str):
            errs.append(f"{os.path.basename(p)}: {r}")
            continue
        chat, mine, pairs = r
        _hist_add(chat, len(mine), STATE.get("voice", 0), len(pairs))
        for t in mine[-300:]:
            pc_nachrichten.stil_lernen(t)
        done += len(mine)
        if pc_handy.paired():   # in Stücken ans Handy (Stil-Training, Ton pro Person)
            mine2, pairs2 = mine[-300:], pairs[-150:]
            chunks = max(1, (len(mine2) + 24) // 25)
            for k in range(chunks):
                part = dict(chat=chat, mine=mine2[k * 25:(k + 1) * 25], pairs=pairs2[k * 12:(k + 1) * 12], last=(k == chunks - 1))
                r2 = pc_handy.ask("ctl", wait=20, what="stil_paket", **part)
                if not r2:
                    sent_ok = False
                    break
    out = (f"Gelernt: {done} Nachrichten von dir" + (f", {STATE.get('voice', 0)} Sprachnachrichten angehört" if STATE.get("voice") else "") + ".") if done else "Nichts gelernt."
    if done and not sent_ok:
        out += " Das Handy hat nicht geantwortet – am PC ist es gelernt, ans Handy schick ich es beim nächsten Mal."
    if errs:
        out += " " + " ".join(errs[:3])
    return out


def pick_files() -> list:
    """Windows-Dialog „Öffnen“ (mehrere Dateien), nur .zip und .txt."""
    import ctypes
    from ctypes import wintypes

    class OFN(ctypes.Structure):
        _fields_ = [("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND), ("hInstance", wintypes.HINSTANCE),
                    ("lpstrFilter", wintypes.LPCWSTR), ("lpstrCustomFilter", wintypes.LPWSTR), ("nMaxCustFilter", wintypes.DWORD),
                    ("nFilterIndex", wintypes.DWORD), ("lpstrFile", wintypes.LPWSTR), ("nMaxFile", wintypes.DWORD),
                    ("lpstrFileTitle", wintypes.LPWSTR), ("nMaxFileTitle", wintypes.DWORD), ("lpstrInitialDir", wintypes.LPCWSTR),
                    ("lpstrTitle", wintypes.LPCWSTR), ("Flags", wintypes.DWORD), ("nFileOffset", wintypes.WORD),
                    ("nFileExtension", wintypes.WORD), ("lpstrDefExt", wintypes.LPCWSTR), ("lCustData", wintypes.LPARAM),
                    ("lpfnHook", ctypes.c_void_p), ("lpTemplateName", wintypes.LPCWSTR), ("pvReserved", ctypes.c_void_p),
                    ("dwReserved", wintypes.DWORD), ("FlagsEx", wintypes.DWORD)]
    buf = ctypes.create_unicode_buffer(65536)
    o = OFN()
    o.lStructSize = ctypes.sizeof(OFN)
    o.lpstrFilter = "WhatsApp-Export (*.zip;*.txt)\0*.zip;*.txt\0\0"
    o.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    o.nMaxFile = 65536
    o.lpstrTitle = "WhatsApp-Chat-Exporte wählen"
    o.Flags = 0x00080000 | 0x00000200 | 0x00001000 | 0x00000800   # EXPLORER | ALLOWMULTISELECT | FILEMUSTEXIST | PATHMUSTEXIST
    if not ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(o)):
        return []
    parts = ctypes.wstring_at(ctypes.addressof(buf), 65536).split("\0")
    parts = [p for p in parts if p]
    if len(parts) == 1:
        return parts
    return [os.path.join(parts[0], p) for p in parts[1:]]
