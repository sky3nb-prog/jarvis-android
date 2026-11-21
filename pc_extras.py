"""
Kleine Helfer am PC:

  „Räum den PC auf“ / „PC aufräumen“   -> Temp-Ordner und Jarvis-Reste leeren (nur Dateien älter als 2 Tage),
                                          sagt, wie viel frei wurde. Papierkorb nur nach „ja“ (endgültig weg).
  „Wer ist auf Discord online?“        -> über das Server-Widget (Einstellung „discord_server“, kein Bot, keine Anmeldung)
  „Öffne meinen Amazon-Warenkorb“      -> Warenkorb im Browser (kaufen tust du selbst)
  „Rewe letzte Bestellung“             -> deine letzten Rewe-Einkäufe
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

PENDING = {"bin": 0.0, "voice": 0.0}


def _size(p: str) -> int:
    try:
        return os.path.getsize(p)
    except Exception:
        return 0


def _clean_dir(d: str, older_days: float = 2.0) -> int:
    """Dateien älter als X Tage löschen (was gerade benutzt wird, bleibt einfach liegen). Gibt freie Bytes zurück."""
    freed = 0
    if not d or not os.path.isdir(d):
        return 0
    cut = time.time() - older_days * 86400
    for root, dirs, files in os.walk(d, topdown=False):
        for f in files:
            p = os.path.join(root, f)
            try:
                if os.path.getmtime(p) < cut:
                    s = _size(p)
                    os.remove(p)
                    freed += s
            except Exception:
                pass
        for sub in dirs:
            try:
                os.rmdir(os.path.join(root, sub))   # nur leere Ordner
            except Exception:
                pass
    return freed


def _mb(b: int) -> str:
    return f"{b / 1_073_741_824:.1f} GB" if b >= 1_073_741_824 else f"{b / 1_048_576:.0f} MB"


def clean() -> str:
    freed = 0
    dirs = [os.environ.get("TEMP"), os.environ.get("TMP"), os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp")]
    la = os.environ.get("LOCALAPPDATA") or ""
    if la:
        dirs += [os.path.join(la, "Temp"), os.path.join(la, "CrashDumps"), os.path.join(la, "JarvisPiper", "out"),
                 os.path.join(la, "D3DSCache"), os.path.join(la, "NVIDIA", "DXCache")]
    for d in dict.fromkeys(x for x in dirs if x):
        freed += _clean_dir(d)
    try:   # Reste vom Selbst-Update
        import pc_update
        import shutil
        old = os.path.join(pc_update._src(), "dist_neu")
        if os.path.isdir(old) and not pc_update._state.get("ready") and not pc_update._state.get("busy"):
            for root, _, files in os.walk(old):
                freed += sum(_size(os.path.join(root, f)) for f in files)
            shutil.rmtree(old, ignore_errors=True)
    except Exception:
        pass
    bin_mb = _recycle_size()
    PENDING["bin"] = time.time() if bin_mb > 50 * 1_048_576 else 0.0
    out = f"Aufgeräumt: {_mb(freed)} Temp-Dateien weg."
    if PENDING["bin"]:
        out += f" Im Papierkorb liegen noch {_mb(bin_mb)} – soll ich ihn leeren? Das ist dann endgültig weg."
    return out


def _recycle_size() -> int:
    try:
        import ctypes

        class SHQ(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]
        q = SHQ()
        q.cbSize = ctypes.sizeof(SHQ)
        if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(q)) == 0:
            return int(q.i64Size)
    except Exception:
        pass
    return 0


def empty_bin() -> str:
    try:
        import ctypes
        n = _recycle_size()
        r = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)   # ohne Rückfrage-Fenster, ohne Ton
        return f"Papierkorb geleert, {_mb(n)} frei." if r in (0, -2147418113) else "Den Papierkorb konnte ich nicht leeren."
    except Exception as e:
        return f"Papierkorb leeren ging nicht ({e})."


def discord_online() -> str:
    import pc_settings
    sid = re.sub(r"\D", "", str(pc_settings.load().get("discord_server") or ""))
    if not sid:
        return ("Dafür brauch ich deine Discord-Server-ID und das Server-Widget. Trag die ID in den Einstellungen unter Stimme → Discord ein "
                "und schalte in den Server-Einstellungen das Widget an.")
    try:
        req = urllib.request.Request(f"https://discord.com/api/guilds/{sid}/widget.json", headers={"User-Agent": "Jarvis-PC"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return "Das Server-Widget ist noch aus. In Discord: Server-Einstellungen → Widget → „Server-Widget aktivieren“."
        return f"Discord antwortet nicht ({e.code})."
    except Exception as e:
        return f"Ich komme gerade nicht an Discord ({e})."
    members = d.get("members") or []
    chans = {c.get("id"): c.get("name") for c in d.get("channels") or []}
    if not members:
        return f"Auf {d.get('name') or 'deinem Server'} ist gerade keiner online."
    in_voice = {}
    for m in members:
        if m.get("channel_id"):
            in_voice.setdefault(chans.get(m["channel_id"], "Sprachkanal"), []).append(m.get("username", "?"))
    names = [m.get("username", "?") for m in members]
    out = f"Online auf {d.get('name') or 'deinem Server'}: {', '.join(names[:12])}" + (f" und {len(names) - 12} weitere" if len(names) > 12 else "") + "."
    for ch, who in in_voice.items():
        out += f" Im Sprachkanal {ch}: {', '.join(who)}."
    return out


def _open(url: str):
    import webbrowser
    webbrowser.open(url)


def handle(text: str):
    low = text.lower().strip(" .!?")
    if PENDING["bin"] and time.time() - PENDING["bin"] < 120:
        if re.match(r"^(ja|jo|klar|mach|leer ihn|ja bitte|okay|ok)\b", low):
            PENDING["bin"] = 0.0
            return empty_bin()
        if re.match(r"^(nein|nö|ne|lass|nicht)\b", low):
            PENDING["bin"] = 0.0
            return "Okay, der Papierkorb bleibt."
    if len(low.split()) <= 9 and re.search(r"\b(räum\w*|aufräum\w*|säuber\w*|bereinig\w*|clean\w*)\b", low) and re.search(r"\b(pc|computer|rechner|festplatte|speicher|temp)\b", low):
        return clean()
    if re.search(r"\b(papierkorb)\b", low) and re.search(r"\b(leer|lösch)\w*", low):
        PENDING["bin"] = time.time()
        return "Den Papierkorb endgültig leeren? Sag ja."
    if re.search(r"\bdiscord\b", low) and re.search(r"\b(wer|online|on|da|drin|im call|im sprachkanal)\b", low) and len(low.split()) <= 10:
        return discord_online()
    # Sprachnachricht schicken: direkt über WhatsApp am PC (Jarvis-Stimme), fragt nach, wenn etwas fehlt
    try:
        import pc_wavoice
        r = pc_wavoice.handle(text)
        if r:
            return r
    except Exception as e:
        return f"Die Sprachnachricht ging nicht ({e})."
    # „Übernimm den Chat mit Alex“ / „ich übernehme wieder“ – Jarvis antwortet hier am PC selbst (WhatsApp am PC)
    m = re.match(r"^(?:übernimm|übernimmst du|übernehme du)\s+(?:mal\s+|jetzt\s+)?(?:den chat (?:mit|von)\s+|das gespräch mit\s+|für mich\s+)?([a-zäöüß-]+)$", low)
    if m and m.group(1) not in ("das", "den", "es", "du"):
        import pc_nachrichten
        return pc_nachrichten.takeover(m.group(1).capitalize())
    m = re.match(r"^(?:ich übernehm\w*|hör auf zu antworten)(?:\s+(?:wieder|selbst|jetzt))*(?:\s+(?:bei|mit)\s+([a-zäöüß-]+))?$", low)
    if m:
        import pc_nachrichten
        return pc_nachrichten.takeover(m.group(1) or "", on=False)
    # „Wo hab ich … hingelegt?“ / „… liegt in der Schublade“ – das merkt sich das Handy (eine Liste für beide)
    if len(low.split()) <= 14 and (re.match(r"^(wo (ist|sind|liegt|liegen|hab ich|habe ich) (mein|meine|meinen|die|der|das|den)\b)", low)
                                   or re.search(r"\b(liegt|liegen|steht|stehen|hängt|hängen)\b.*\b(in|im|auf|unter|neben|hinter|bei|beim|am|an)\b", low) and re.search(r"\b(mein\w*|schlüssel|kopfhörer|handy|geldbeutel|portemonnaie|brille|ausweis|fahrrad|controller|ladekabel)\b", low)
                                   or re.search(r"\bich (hab|habe) .+ (gelegt|hingelegt|abgestellt|gestellt|verstaut)$", low)):
        try:
            import pc_handy
            if pc_handy.paired():
                r = pc_handy.command(text)
                return r.get("text") or "Okay."
        except Exception:
            pass
    if re.search(r"\bwarenkorb\b", low) and re.search(r"\b(öffne|zeig|mach|auf|geh)\w*", low):
        _open("https://www.amazon.de/gp/cart/view.html")
        return "Ich mach dir den Amazon-Warenkorb auf – kaufen tippst du selbst."
    if re.search(r"\brewe\b", low) and re.search(r"\b(bestell|einkauf|einkäufe|letzte|öffne)\w*", low):
        _open("https://shop.rewe.de/mydata/meine-einkaeufe")
        return "Hier sind deine letzten Rewe-Einkäufe – bestellen machst du selbst."
    return None
