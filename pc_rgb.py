"""Beleuchtung: Vectors Farbe und Zustand auf der RGB-Hardware (Tastatur, Maus, Mainboard, RAM, Grafikkarte).

Läuft über OpenRGB: ein kleines Programm, das die Geräte herstellerübergreifend ansteuert und dafür einen
Netzwerk-Anschluss anbietet (Standard 127.0.0.1:6742, in OpenRGB unter „SDK Server“ einschalten). Wir sprechen
dieses Protokoll hier direkt – kein Zusatzpaket, keine Treiber von uns, und wenn OpenRGB nicht läuft, passiert
einfach nichts.

Was es kann:
    pc_rgb.start()                  einmalig beim Programmstart – verbindet im Hintergrund und merkt sich
                                    vorher deinen aktuellen Stand als Profil „Vector-vorher“
    pc_rgb.set_state("thinking")    Zustand von Vector: bereit / hört zu / denkt nach / spricht
    pc_rgb.set_level(0.0..1.0)      Lautstärke seiner Stimme, damit die Beleuchtung mitatmet
    pc_rgb.set_mode("schule")       Modus (Schule, Gaming, Kino, Nacht …) hat Vorrang vor dem Zustand
    pc_rgb.set_accent("#C45CFF")    Akzentfarbe aus den Einstellungen
    pc_rgb.standard()               Hände weg: dein eigenes Profil zurückladen, Vector lässt die Finger davon
    pc_rgb.spiel("welle")           kurz etwas vorführen (welle, puls, regenbogen, blitz)
    pc_rgb.status()                 was gefunden wurde – für Einstellungen und Systemcheck
"""
from __future__ import annotations

import colorsys
import math
import socket
import struct
import threading
import time

HOST, PORT = "127.0.0.1", 6742
MAGIC = b"ORGB"
MY_PROTOCOL = 3

# Pakettypen des OpenRGB-Protokolls
P_COUNT, P_DATA, P_VERSION = 0, 1, 40
P_NAME = 50
P_PROFILE_LIST, P_PROFILE_SAVE, P_PROFILE_LOAD = 150, 151, 152
P_UPDATE_LEDS, P_CUSTOM_MODE = 1050, 1100

TEAL = (29, 158, 117)
TEAL_HELL = (159, 225, 203)
ALARM = (239, 159, 39)
MEIN_PROFIL = "Vector-vorher"

SETTINGS = lambda: {}           # wird von pc_overlay gesetzt
LOG = lambda t: None


# ---------------------------------------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------------------------------------
class _Leser:
    """Liest der Reihe nach aus dem Datenblock, das OpenRGB schickt."""

    def __init__(self, b: bytes):
        self.b, self.i = b, 0

    def rest(self) -> int:
        return len(self.b) - self.i

    def u8(self) -> int:
        v = self.b[self.i]; self.i += 1; return v

    def u16(self) -> int:
        v = struct.unpack_from("<H", self.b, self.i)[0]; self.i += 2; return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.b, self.i)[0]; self.i += 4; return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.b, self.i)[0]; self.i += 4; return v

    def text(self) -> str:
        n = self.u16()
        s = self.b[self.i:self.i + n]; self.i += n
        return s.split(b"\x00")[0].decode("utf-8", "replace")

    def skip(self, n: int):
        self.i += n


class OpenRGB:
    """Dünner Draht zu OpenRGB. Alles, was schiefgehen kann, wirft – der Aufrufer fängt es ab."""

    def __init__(self, host: str = HOST, port: int = PORT):
        self.s = socket.create_connection((host, port), timeout=3)
        self.s.settimeout(3)
        self.protocol = 0
        self._send(0, P_NAME, b"Vector\x00")
        try:
            self._send(0, P_VERSION, struct.pack("<I", MY_PROTOCOL))
            self.protocol = min(MY_PROTOCOL, struct.unpack("<I", self._recv(P_VERSION))[0])
        except Exception:
            self.protocol = 0          # ganz alte OpenRGB-Versionen kennen die Abfrage nicht
        self.geraete = self._lesen()

    # --- Rohes Senden/Empfangen ---------------------------------------------------------------------------
    def _send(self, dev: int, typ: int, data: bytes = b""):
        self.s.sendall(MAGIC + struct.pack("<III", dev, typ, len(data)) + data)

    def _recv(self, erwartet: int) -> bytes:
        while True:
            kopf = self._genau(16)
            if kopf[:4] != MAGIC:
                raise OSError("fremde Antwort")
            dev, typ, n = struct.unpack("<III", kopf[4:])
            data = self._genau(n) if n else b""
            if typ == erwartet:
                return data                # alles andere (z. B. „Geräteliste geändert“) überspringen wir

    def _genau(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            teil = self.s.recv(n - len(out))
            if not teil:
                raise OSError("Verbindung zu")
            out += teil
        return out

    # --- Geräte lesen -------------------------------------------------------------------------------------
    def _lesen(self) -> list:
        self._send(0, P_COUNT)
        anzahl = struct.unpack("<I", self._recv(P_COUNT))[0]
        out = []
        for i in range(min(anzahl, 64)):
            try:
                self._send(i, P_DATA, struct.pack("<I", self.protocol) if self.protocol else b"")
                out.append(self._geraet(i, self._recv(P_DATA)))
            except Exception as e:
                LOG(f"RGB: Gerät {i} nicht lesbar ({e})")
        return [g for g in out if g and g["leds"] > 0]

    def _geraet(self, idx: int, blob: bytes) -> dict:
        r = _Leser(blob)
        r.u32()                                   # Gesamtlänge
        typ = r.u32()
        name = r.text(); r.text(); r.text(); r.text(); r.text()   # Beschreibung, Version, Seriennummer, Ort
        modi = r.u16(); r.i32()                   # Anzahl Modi, aktiver Modus
        for _ in range(modi):
            r.text(); r.i32(); r.u32(); r.u32(); r.u32()          # Name, Wert, Flags, Tempo min/max
            if self.protocol >= 3:
                r.u32(); r.u32()                                  # Helligkeit min/max
            r.u32(); r.u32()                                      # Farben min/max
            r.u32()                                               # Tempo
            if self.protocol >= 3:
                r.u32()                                           # Helligkeit
            r.u32(); r.u32()                                      # Richtung, Farbmodus
            for _ in range(r.u16()):
                r.u32()                                           # Modusfarben
        zonen = []
        for _ in range(r.u16()):
            zname = r.text(); r.u32(); r.u32(); r.u32()
            zleds = r.u32()
            mlen = r.u16()
            if mlen:
                r.skip(mlen)
            if self.protocol >= 4:
                for _ in range(r.u16()):
                    r.text(); r.u32(); r.u32()
            zonen.append({"name": zname, "leds": zleds})
        leds = r.u16()
        return {"id": idx, "name": name, "typ": typ, "leds": leds, "zonen": zonen}

    # --- Setzen -------------------------------------------------------------------------------------------
    def direkt(self, dev: int):
        """Gerät auf seinen Direkt-/Eigenmodus stellen, damit unsere Farben überhaupt ankommen."""
        self._send(dev, P_CUSTOM_MODE)

    def farben(self, dev: int, farben: list):
        data = struct.pack("<H", len(farben)) + b"".join(
            struct.pack("<BBBB", max(0, min(255, int(c[0]))), max(0, min(255, int(c[1]))),
                        max(0, min(255, int(c[2]))), 0) for c in farben)
        self._send(dev, P_UPDATE_LEDS, struct.pack("<I", len(data)) + data)

    def profil_speichern(self, name: str):
        self._send(0, P_PROFILE_SAVE, name.encode("utf-8") + b"\x00")

    def profil_laden(self, name: str):
        self._send(0, P_PROFILE_LOAD, name.encode("utf-8") + b"\x00")

    def zu(self):
        try:
            self.s.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------------------------------------
# Zustand und Effektschleife
# ---------------------------------------------------------------------------------------------------------
_lock = threading.Lock()
_rgb: OpenRGB | None = None
_an = False                  # läuft die Schleife?
_wir_steuern = True          # False = „mein Standard“, Vector fasst nichts an
_zustand = "idle"
_modus = ""
_level = 0.0
_akzent = (196, 92, 255)
_spiel_bis = 0.0
_spiel_art = ""
_letzter_fehler = ""
_gefunden: list = []


def _hex2rgb(h: str) -> tuple:
    h = (h or "").strip().lstrip("#")
    if len(h) != 6:
        return _akzent
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def set_accent(hexfarbe: str):
    global _akzent
    _akzent = _hex2rgb(hexfarbe)


def set_state(state: str):
    global _zustand
    _zustand = state or "idle"


def set_level(v: float):
    global _level
    try:
        _level = max(0.0, min(1.0, float(v)))
    except Exception:
        _level = 0.0


def set_mode(mid: str):
    global _modus, _wir_steuern
    _modus = (mid or "").lower()
    if _modus:
        _wir_steuern = True       # ein Modus holt die Steuerung zurück


def spiel(art: str = "welle", sekunden: float = 6.0):
    """Kurz etwas vorführen – danach geht es automatisch zurück auf den Zustand."""
    global _spiel_art, _spiel_bis, _wir_steuern
    _spiel_art = (art or "welle").lower()
    _spiel_bis = time.time() + max(1.0, min(60.0, sekunden))
    _wir_steuern = True
    return f"Mach ich – {_spiel_art} für {int(sekunden)} Sekunden."


def standard() -> str:
    """Finger weg: dein eigenes Profil zurück, Vector steuert nichts mehr."""
    global _wir_steuern
    _wir_steuern = False
    name = str((SETTINGS() or {}).get("rgb_profil") or "").strip() or MEIN_PROFIL
    with _lock:
        if _rgb:
            try:
                _rgb.profil_laden(name)
                return f"Beleuchtung zurück auf „{name}“."
            except Exception as e:
                return f"Konnte „{name}“ nicht laden ({e}). Ich fasse die Beleuchtung trotzdem nicht mehr an."
    return "Ich fasse die Beleuchtung nicht mehr an. (OpenRGB ist gerade nicht verbunden.)"


def uebernehmen() -> str:
    global _wir_steuern
    _wir_steuern = True
    return "Alles klar, ich übernehme die Beleuchtung wieder."


def status() -> dict:
    return {
        "verbunden": _rgb is not None,
        "steuert": _wir_steuern,
        "fehler": _letzter_fehler,
        "geraete": [{"name": g["name"], "leds": g["leds"]} for g in _gefunden],
    }


# --- Farbrechnerei ----------------------------------------------------------------------------------------
def _dim(c, f):
    return (c[0] * f, c[1] * f, c[2] * f)


def _misch(a, b, k):
    return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k)


def _bild(n: int, t: float) -> list:
    """Welche Farbe bekommt welche LED? n = Anzahl, t = Sekunden seit Start."""
    akz, jetzt = _akzent, time.time()

    if jetzt < _spiel_bis:                                   # Vorführung
        if _spiel_art == "regenbogen":
            return [tuple(255 * x for x in colorsys.hsv_to_rgb(((i / max(1, n)) + t * .15) % 1, .85, 1)) for i in range(n)]
        if _spiel_art == "blitz":
            k = max(0.0, 1 - (t * 3 % 1) * 3)
            return [_misch(TEAL, (255, 255, 255), k)] * n
        if _spiel_art == "puls":
            return [_dim(akz, .25 + .75 * (math.sin(t * 3) * .5 + .5))] * n
        return [_dim(akz if (i + int(t * 14)) % 7 < 3 else TEAL,
                     .35 + .65 * (math.sin(t * 3 - i * .35) * .5 + .5)) for i in range(n)]

    if _modus in ("schule", "kino", "nacht"):                # still heißt auch dunkel
        return [_dim(TEAL, .05 if _modus != "nacht" else .02)] * n
    if _modus == "gaming":
        return [_dim(_misch(akz, TEAL, (math.sin(t * 1.6 - i * .22) * .5 + .5)), .75 + .25 * math.sin(t * 2)) for i in range(n)]
    if _modus == "fokus":
        return [_dim(TEAL, .3 + .08 * math.sin(t * .8))] * n

    if _zustand == "listening":                               # er hört zu: ruhiges Atmen im Akzent
        return [_dim(akz, .3 + .55 * (math.sin(t * 2.4) * .5 + .5) + _level * .3)] * n
    if _zustand == "thinking":                                # er denkt: Welle läuft durch
        return [_dim(akz, .18 + .8 * (math.sin(t * 5 - i * .45) * .5 + .5)) for i in range(n)]
    if _zustand == "speaking":                                # er redet: Helligkeit folgt der Stimme
        h = .25 + .75 * _level
        return [_misch(_dim(TEAL, h * .5), _dim(akz, h), .6)] * n
    return [_dim(TEAL, .22 + .05 * math.sin(t * .7))] * n     # bereit


def _schleife():
    global _rgb, _letzter_fehler, _gefunden
    t0 = time.time()
    naechster_versuch = 0.0
    while _an:
        s = SETTINGS() or {}
        if not s.get("rgb_on", False):
            with _lock:
                if _rgb:
                    _rgb.zu(); _rgb = None; _gefunden = []
            time.sleep(2)
            continue

        if _rgb is None:                                      # verbinden (höchstens alle 20 Sekunden probieren)
            if time.time() < naechster_versuch:
                time.sleep(1); continue
            naechster_versuch = time.time() + 20
            try:
                host = str(s.get("rgb_host") or HOST).strip() or HOST
                port = int(s.get("rgb_port") or PORT)
                v = OpenRGB(host, port)
                with _lock:
                    _rgb, _gefunden, _letzter_fehler = v, v.geraete, ""
                try:
                    v.profil_speichern(MEIN_PROFIL)           # deinen Stand sichern, bevor wir etwas ändern
                except Exception:
                    pass
                for g in v.geraete:
                    try:
                        v.direkt(g["id"])
                    except Exception:
                        pass
                LOG("RGB: " + ", ".join(f"{g['name']} ({g['leds']})" for g in v.geraete) or "RGB: nichts gefunden")
            except Exception as e:
                _letzter_fehler = str(e)
                time.sleep(2)
                continue

        if not _wir_steuern:                                  # „mein Standard“: nichts senden
            time.sleep(.5)
            continue

        t = time.time() - t0
        try:
            with _lock:
                v = _rgb
                if v:
                    for g in v.geraete:
                        v.farben(g["id"], _bild(g["leds"], t))
        except Exception as e:
            _letzter_fehler = str(e)
            with _lock:
                if _rgb:
                    _rgb.zu()
                _rgb = None; _gefunden = []
        time.sleep(1 / 25)


def start():
    global _an
    if _an:
        return
    _an = True
    threading.Thread(target=_schleife, name="vector-rgb", daemon=True).start()


def stop():
    global _an, _rgb
    _an = False
    with _lock:
        if _rgb:
            _rgb.zu(); _rgb = None
