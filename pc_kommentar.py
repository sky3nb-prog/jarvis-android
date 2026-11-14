"""
Jarvis meldet sich am PC auch mal von selbst – persönlich, aber nicht nervig:
  - Du sitzt seit über 2 Stunden ohne Pause dran -> "Du bist seit 2½ Stunden dran – kurz raus, bewegen?"
    (wieder frühestens nach 90 Minuten; eine Pause = 10 Minuten ohne Maus/Tastatur)
  - spät abends noch am PC und morgen früh raus -> kurzer Hinweis (über die Aufsteh-Zeit vom Handy)
Formuliert per KI mit dem, was er über dich weiß, und passend zu deiner Stimmung (vom Handy).
Lernt mit (pc_lernen): Machst du nach dem Hinweis nie eine Pause, kommt er seltener.
"""
import random
import threading
import time

SAY = None        # vom Programm gesetzt: Text ansagen (dezent)
SETTINGS = None   # vom Programm gesetzt: Einstellungen (an/aus)
_state = {"since": 0.0, "last_hint": 0.0, "hint_wait": 0.0, "late": ""}


def _idle() -> float:
    try:
        import pc_nachrichten
        return pc_nachrichten._idle_seconds()
    except Exception:
        return 0.0


def _phrase(what: str, fallback: str) -> str:
    try:
        import pc_ai, pc_memory, pc_handy
        if not pc_ai.available():
            return fallback
        mood = ((pc_handy.STATUS.get("data") or {}).get("gesund") or {}).get("stimmung", "")
        sys_ = ("Du bist Jarvis, der persönliche KI-Butler des Nutzers, wie ein guter Freund. Du meldest dich von selbst. "
                "1 bis 2 kurze, persönliche Sätze auf Deutsch (du), locker, ohne Vorwurf, gern mit kleinem Augenzwinkern. Nur der Text.\n"
                + pc_memory.prompt_block() + ("\n" + mood if mood else ""))
        out = pc_ai.gemini_generate([{"role": "user", "parts": [{"text": f"Anlass: {what}"}]}], sys_, json_mode=False, max_tokens=160, fast=True)
        out = (out or "").strip().strip('"')
        return out if 8 < len(out) < 280 else fallback
    except Exception:
        return fallback


def _say(text: str):
    if SAY:
        try:
            SAY(text)
        except Exception as e:
            print("Kommentar ging nicht:", e)


def _loop(stop: threading.Event):
    import pc_lernen
    while not stop.wait(60):
        try:
            st = SETTINGS() if SETTINGS else {}
            if not st.get("kommentare", True):
                continue
            now = time.time()
            idle = _idle()
            if idle > 600:   # Pause gemacht
                if _state["hint_wait"] and now - _state["hint_wait"] < 25 * 60:
                    pc_lernen.used("pause")   # er hat auf den Hinweis gehört
                _state.update(since=0.0, hint_wait=0.0)
                continue
            if not _state["since"]:
                _state["since"] = now
            sat = (now - _state["since"]) / 60
            if sat >= 130 and now - _state["last_hint"] > 90 * 60 and pc_lernen.allowed("pause"):
                h, m = divmod(int(sat), 60)
                dauer = f"{h} Stunde{'n' if h != 1 else ''}" + (f" {m} Minuten" if m >= 10 else "")
                _state.update(last_hint=now, hint_wait=now)
                pc_lernen.shown("pause")
                _say(_phrase(f"Er sitzt seit {dauer} ohne Pause am PC. Schlag vor, kurz rauszugehen oder sich zu bewegen (mit dem Hund?).",
                             f"Du bist seit {dauer} am Stück dran. Kurz raus und bewegen? Ich pass solange auf alles auf."))
            # spät dran und morgen früh raus (Aufstehzeit kommt vom Handy über die Gesundheitsdaten nicht – daher nur Uhrzeit)
            lt = time.localtime()
            key = time.strftime("%Y-%m-%d")
            if lt.tm_hour == 23 and lt.tm_min >= 15 and _state["late"] != key and lt.tm_wday in (6, 0, 1, 2, 3) and pc_lernen.allowed("spaet"):
                _state["late"] = key
                pc_lernen.shown("spaet")
                _say(_phrase("Es ist nach 23 Uhr, morgen ist Schule. Ein kurzer, freundlicher Hinweis aufs Schlafen.",
                             "Schon nach elf – morgen ist Schule. Noch eine Runde, dann ab ins Bett?"))
        except Exception as e:
            print("Kommentare:", e)


def start(stop: threading.Event):
    threading.Thread(target=_loop, args=(stop,), daemon=True, name="kommentare").start()
