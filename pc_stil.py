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
SKIP = ("<Medien ausgeschlossen>", "Medien ausgeschlossen", "Diese Nachricht wurde gelöscht", "<Media omitted>", "null")


def _me_file():
    return os.path.join(base_dir(), "stil_name.json")


def _me() -> str:
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
    """(Chat-Name, Text) aus einer .zip oder .txt."""
    base = os.path.splitext(os.path.basename(path))[0]
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".txt")]
            if not names:
                return base, ""
            n = sorted(names, key=lambda x: z.getinfo(x).file_size)[-1]
            return base, io.TextIOWrapper(z.open(n), encoding="utf-8", errors="replace").read()
    with open(path, encoding="utf-8", errors="replace") as f:
        return base, f.read()


def parse(path: str):
    """-> (chat, eigene Nachrichten, Paare [{q, a, ctx}]) oder Fehlertext."""
    base, text = _read(path)
    m = NAME.search(base)
    partner = m.group(1).strip() if m else ""
    msgs = []
    for raw in text.splitlines():
        line = INVIS.sub("", raw)
        x = LINE.match(line)
        if x:
            msgs.append([x.group(3).strip(), x.group(4).strip()])
        elif msgs and line.strip():
            msgs[-1][1] += "\n" + line.strip()
    if not msgs:
        return "In der Datei finde ich keinen WhatsApp-Chat."
    senders = {}
    for s, _ in msgs:
        senders[s] = senders.get(s, 0) + 1
    me = _me()
    if not me or me not in senders:
        others = [s for s in senders if partner and s.lower() != partner.lower()]
        if partner and len(senders) == 2 and others:
            me = others[0]
            _set_me(me)
        else:
            return "Bei Gruppen weiß ich noch nicht, welcher Name du bist – lade zuerst einen Einzelchat."
    chat = partner or next((s for s in senders if s != me), base)
    good = lambda t: 2 <= len(t) <= 300 and not t.startswith("(") and not any(k in t for k in SKIP) and not t.startswith("http")  # noqa: E731
    mine, pairs = [], []
    last = msgs[-4000:]
    for i, (s, t) in enumerate(last):
        if s != me or not good(t):
            continue
        mine.append(t)
        if i > 0 and last[i - 1][0] != me and good(last[i - 1][1]):
            cx = "\n".join(f"{'ICH' if v == me else v}: {w[:150]}" for v, w in last[max(0, i - 4):i - 1])
            pairs.append({"q": f"{last[i - 1][0]}: {last[i - 1][1][:300]}", "a": t, "ctx": cx[:500]})
    return chat, mine, pairs


def import_files(paths) -> str:
    import pc_handy
    import pc_nachrichten
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
    out = f"Gelernt: {done} Nachrichten von dir." if done else "Nichts gelernt."
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
