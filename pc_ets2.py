"""
ETS2-Beifahrer: liest die Telemetrie aus dem Spiel (Plugin "scs-sdk-plugin" von RenCloud, liegt als
scs-telemetry.dll in ETS2\\bin\\win_x64\\plugins – build.bat legt es dort hin) über den gemeinsamen Speicher
"Local\\SCSTelemetry".

Dezent: Er sagt nur etwas, wenn es wichtig ist –
  - Tank bei 15 % (mit Reichweite und Restkilometern bis zum Ziel)
  - etwa 60 und 20 Minuten vor der Ruhezeit
  - Auftrag abgeliefert (Lohn, Kilometer), Strafzettel
Fragen gehen jederzeit: "wie weit noch?", "wie viel Sprit?", "wann muss ich schlafen?", "was verdiene ich?".
Die Fahrtenseite im HUD zeigt alles live (STATE).
"""

import ctypes
import re
import threading
import time

MMF = "Local\\SCSTelemetry"
SIZE = 32 * 1024
S = 64  # Länge der meisten Texte

b, ui, i32, f, d, ull, ll, c = (ctypes.c_bool, ctypes.c_uint32, ctypes.c_int32, ctypes.c_float, ctypes.c_double,
                                ctypes.c_uint64, ctypes.c_int64, ctypes.c_char)


def _st(name, fields):
    return type(name, (ctypes.Structure,), {"_fields_": fields})


# Spiegel des Speicher-Layouts aus scs-telemetry-common.hpp (Plugin-Version 1.12), Teil bis Zone 12
Map = _st("Map", [
    ("sdkActive", b), ("ph1", c * 3), ("paused", b), ("ph2", c * 3),
    ("time", ull), ("simulatedTime", ull), ("renderTime", ull), ("mpOffset", ll),
    # Zone 2 (40): unsigned int
    ("plugin_rev", ui), ("ver_major", ui), ("ver_minor", ui), ("game", ui), ("tel_major", ui), ("tel_minor", ui),
    ("time_abs", ui),
    ("gears", ui), ("gears_reverse", ui), ("retarderSteps", ui), ("wheelCount", ui), ("selectorCount", ui),
    ("time_abs_delivery", ui), ("maxTrailer", ui), ("unitCount", ui), ("plannedDistanceKm", ui),
    ("shifterSlot", ui), ("retarderBrake", ui), ("auxFront", ui), ("auxRoof", ui), ("wheelSubst", ui * 16),
    ("hsPos", ui * 32), ("hsMask", ui * 32),
    ("jobDeliveredDeliveryTime", ui), ("jobStartingTime", ui), ("jobFinishedTime", ui),
    ("buffer_ui", c * 48),
    # Zone 3 (500): int
    ("restStop", i32), ("gear", i32), ("gearDashboard", i32), ("hsResulting", i32 * 32), ("jobDeliveredXp", i32),
    ("buffer_i", c * 56),
    # Zone 4 (700): float
    ("scale", f),
    ("fuelCapacity", f), ("fuelWarningFactor", f), ("adblueCapacity", f), ("adblueWarningFactor", f),
    ("airPressureWarning", f), ("airPressureEmergency", f), ("oilPressureWarning", f), ("waterTempWarning", f),
    ("batteryWarning", f), ("engineRpmMax", f), ("gearDifferential", f), ("cargoMass", f), ("wheelRadius", f * 16),
    ("gearRatiosFwd", f * 24), ("gearRatiosRev", f * 8), ("unitMass", f),
    ("speed", f), ("engineRpm", f), ("userSteer", f), ("userThrottle", f), ("userBrake", f), ("userClutch", f),
    ("gameSteer", f), ("gameThrottle", f), ("gameBrake", f), ("gameClutch", f), ("cruiseControlSpeed", f),
    ("airPressure", f), ("brakeTemperature", f), ("fuel", f), ("fuelAvgConsumption", f), ("fuelRange", f),
    ("adblue", f), ("oilPressure", f), ("oilTemperature", f), ("waterTemperature", f), ("batteryVoltage", f),
    ("lightsDashboard", f), ("wearEngine", f), ("wearTransmission", f), ("wearCabin", f), ("wearChassis", f),
    ("wearWheels", f), ("odometer", f), ("routeDistance", f), ("routeTime", f), ("speedLimit", f),
    ("wSusp", f * 16), ("wVel", f * 16), ("wSteer", f * 16), ("wRot", f * 16), ("wLift", f * 16), ("wLiftOff", f * 16),
    ("jobDeliveredCargoDamage", f), ("jobDeliveredDistanceKm", f), ("refuelAmount", f),
    ("cargoDamage", f), ("buffer_f", c * 28),
    # Zone 5 (1500): bool
    ("wSteerable", b * 16), ("wSimulated", b * 16), ("wPowered", b * 16), ("wLiftable", b * 16),
    ("isCargoLoaded", b), ("specialJob", b),
    ("parkBrake", b), ("motorBrake", b), ("airWarn", b), ("airEmerg", b), ("fuelWarning", b), ("adblueWarning", b),
    ("oilWarn", b), ("waterWarn", b), ("batteryWarn", b), ("electricEnabled", b), ("engineEnabled", b), ("wipers", b),
    ("blLA", b), ("blRA", b), ("blLO", b), ("blRO", b), ("lPark", b), ("lLow", b), ("lHigh", b), ("lBeacon", b),
    ("lBrake", b), ("lReverse", b), ("lHazard", b), ("cruiseControl", b), ("wOnGround", b * 16), ("shifterToggle", b * 2),
    ("diffLock", b), ("liftAxle", b), ("liftAxleInd", b), ("trLiftAxle", b), ("trLiftAxleInd", b),
    ("autoparkUsed", b), ("autoloadUsed", b), ("buffer_b", c * 25),
    # Zone 6 (1640): fvector
    ("fv_config", f * (9 + 48)), ("fv_truck", f * 18), ("buffer_fv", c * 60),
    # Zone 7 (2000): fplacement
    ("fp", f * 12), ("buffer_fp", c * 152),
    # Zone 8 (2200): dplacement
    ("coordX", d), ("coordY", d), ("coordZ", d), ("rotX", d), ("rotY", d), ("rotZ", d), ("buffer_dp", c * 52),
    # Zone 9 (2300): Texte
    ("truckBrandId", c * S), ("truckBrand", c * S), ("truckId", c * S), ("truckName", c * S), ("cargoId", c * S),
    ("cargo", c * S), ("cityDstId", c * S), ("cityDst", c * S), ("compDstId", c * S), ("compDst", c * S),
    ("citySrcId", c * S), ("citySrc", c * S), ("compSrcId", c * S), ("compSrc", c * S), ("shifterType", c * 16),
    ("plate", c * S), ("plateCountryId", c * S), ("plateCountry", c * S), ("jobMarket", c * 32),
    ("fineOffence", c * 32), ("ferrySrc", c * S), ("ferryDst", c * S), ("ferrySrcId", c * S), ("ferryDstId", c * S),
    ("trainSrc", c * S), ("trainDst", c * S), ("trainSrcId", c * S), ("trainDstId", c * S), ("buffer_s", c * 20),
    # Zone 10 (4000)
    ("jobIncome", ull), ("buffer_ull", c * 192),
    # Zone 11 (4200)
    ("jobCancelledPenalty", ll), ("jobDeliveredRevenue", ll), ("fineAmount", ll), ("tollgatePay", ll), ("ferryPay", ll),
    ("trainPay", ll), ("buffer_ll", c * 52),
    # Zone 12 (4300): Ereignisse (werden bei jedem Ereignis umgeschaltet)
    ("onJob", b), ("jobFinished", b), ("jobCancelled", b), ("jobDelivered", b), ("fined", b), ("tollgate", b),
    ("ferry", b), ("train", b), ("refuel", b), ("refuelPayed", b),
])

STATE = {"aktiv": False}     # für HUD und Fragen
ON_SAY = None                 # vom Programm gesetzt: Ansage (dezent, wie eine Nachricht)
_lock = threading.Lock()


def _s(v: bytes) -> str:
    return v.split(b"\0", 1)[0].decode("utf-8", "replace").strip()


class _View:
    """Nur-Lese-Ansicht auf den Speicher des Plugins (OpenFileMapping: legt nichts an, wenn das Spiel nicht läuft)."""
    def __init__(self, ptr, handle):
        self.ptr, self.handle = ptr, handle

    def read(self):
        return Map.from_buffer_copy(ctypes.string_at(self.ptr, ctypes.sizeof(Map)))


def _open():
    try:
        k = ctypes.windll.kernel32
        k.OpenFileMappingW.restype = ctypes.c_void_p
        k.MapViewOfFile.restype = ctypes.c_void_p
        k.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
        h = k.OpenFileMappingW(0x0004, False, MMF)   # FILE_MAP_READ
        if not h:
            return None
        ptr = k.MapViewOfFile(h, 0x0004, 0, 0, 0)
        if not ptr:
            k.CloseHandle(ctypes.c_void_p(h))
            return None
        return _View(ptr, h)
    except Exception:
        return None


def _read(m):
    return m.read()


def _hm(minutes: float) -> str:
    minutes = max(0, int(round(minutes)))
    h, mi = divmod(minutes, 60)
    if h and mi:
        return f"{h} Stunde{'n' if h != 1 else ''} {mi} Minuten"
    return f"{h} Stunde{'n' if h != 1 else ''}" if h else f"{mi} Minuten"


def snapshot(t) -> dict:
    cap = t.fuelCapacity or 0
    pct = (t.fuel / cap * 100) if cap > 0 else 0
    return {
        "aktiv": bool(t.sdkActive), "pause": bool(t.paused), "spiel": "ATS" if t.game == 2 else "ETS2",
        "kmh": round(abs(t.speed) * 3.6), "limit": round(t.speedLimit * 3.6) if t.speedLimit > 0 else 0,
        "tank_l": round(t.fuel), "tank_pct": round(pct), "reichweite_km": round(t.fuelRange),
        "verbrauch": round(t.fuelAvgConsumption * 100, 1),
        "rest_km": round(t.routeDistance / 1000), "rest_min": round(t.routeTime / 60),
        "ruhe_min": int(t.restStop), "auftrag": bool(t.onJob) or bool(_s(t.cargo)),
        "ladung": _s(t.cargo), "von": _s(t.citySrc), "von_firma": _s(t.compSrc),
        "nach": _s(t.cityDst), "nach_firma": _s(t.compDst), "lohn": int(t.jobIncome),
        "masse_t": round(t.cargoMass / 1000, 1), "schaden": round(t.cargoDamage * 100),
        "lkw": (_s(t.truckBrand) + " " + _s(t.truckName)).strip(), "km_gesamt": round(t.odometer),
        "abgabe_min": int(t.time_abs_delivery) - int(t.time_abs) if t.time_abs_delivery else 0,
    }


def _say(text: str):
    print(f"ETS2: {text}")
    if ON_SAY:
        try:
            ON_SAY(text)
        except Exception as e:
            print(f"ETS2-Ansage ging nicht: {e}")


def _loop(stop: threading.Event):
    global STATE
    m = None
    last = None
    warned = {"fuel": False, "rest60": False, "rest20": False}
    while not stop.is_set():
        if m is None:
            m = _open()
            if m is None:
                STATE = {"aktiv": False}
                stop.wait(10)
                continue
        try:
            t = _read(m)
        except Exception:
            m = None
            continue
        if not t.sdkActive or t.time == 0:
            STATE = {"aktiv": False}
            stop.wait(5)
            continue
        s = snapshot(t)
        with _lock:
            STATE = s
        if last is not None:
            # Ereignisse (die Felder werden bei jedem Ereignis umgeschaltet)
            if t.jobDelivered != last.jobDelivered:
                km = round(t.jobDeliveredDistanceKm)
                _say(f"Auftrag abgeliefert. Du hast {int(t.jobDeliveredRevenue):,} Euro verdient".replace(",", ".")
                     + (f", {km} Kilometer gefahren." if km else "."))
            if t.fined != last.fined and t.fineAmount:
                why = _s(t.fineOffence).replace("_", " ")
                _say(f"Strafzettel: {int(t.fineAmount)} Euro" + (f" wegen {why}." if why else "."))
            if t.jobCancelled != last.jobCancelled and t.jobCancelledPenalty:
                _say(f"Auftrag abgebrochen, Strafe {int(t.jobCancelledPenalty)} Euro.")
        # Tank
        if s["tank_pct"] and s["tank_pct"] <= 15 and not warned["fuel"] and not t.paused and s["kmh"] > 5:
            warned["fuel"] = True
            msg = f"Tank bei {s['tank_pct']} Prozent, das reicht noch etwa {s['reichweite_km']} Kilometer"
            if s["rest_km"]:
                msg += f", bis zum Ziel sind es {s['rest_km']}." if s["rest_km"] > s["reichweite_km"] * 0.85 \
                    else f". Bis zum Ziel sind es {s['rest_km']}, das sollte reichen."
            else:
                msg += "."
            _say(msg + (" Such dir eine Tankstelle." if not s["rest_km"] or s["rest_km"] > s["reichweite_km"] * 0.85 else ""))
        if s["tank_pct"] >= 30:
            warned["fuel"] = False
        # Ruhezeit (restStop = Minuten Spielzeit bis zur nächsten Pause; 0/negativ = aus)
        r = s["ruhe_min"]
        if 0 < r <= 60 and not warned["rest60"] and not t.paused:
            warned["rest60"] = True
            _say(f"In etwa einer Stunde Spielzeit musst du schlafen.")
        if 0 < r <= 20 and not warned["rest20"] and not t.paused:
            warned["rest20"] = True
            _say(f"In {r} Minuten musst du schlafen. Such dir einen Rastplatz.")
        if r > 90:
            warned["rest60"] = warned["rest20"] = False
        last = t
        stop.wait(2)


def start(stop: threading.Event):
    threading.Thread(target=lambda: (install_plugin(), _loop(stop)), daemon=True, name="ets2").start()


ASK = re.compile(r"\b(wie weit (?:ist es |muss ich )?noch|wie lange (?:fahr ich |dauert es )?noch|wann bin ich da|wie viel sprit|wie viel diesel|wie voll|tank\b|reichweite|"
                 r"wann muss ich schlafen|muss ich (?:bald )?schlafen|ruhezeit|was verdien|mein lohn|den auftrag|mein auftrag|"
                 r"welche ladung|was hab ich geladen|wohin fahr|wo muss ich hin|wie schnell darf|tempolimit|wie viel darf ich)", re.I)


def handle(command: str):
    """Fragen zur Fahrt in ETS2. None = gehört nicht hierher (oder das Spiel läuft nicht)."""
    s = STATE
    if not s.get("aktiv"):
        return None
    low = command.lower()
    if not ASK.search(low):
        return None
    parts = []
    if re.search(r"wie weit|wie lange noch|wann bin ich da|wo muss ich hin|wohin", low):
        if s["rest_km"]:
            parts.append(f"Noch {s['rest_km']} Kilometer bis {s['nach'] or 'zum Ziel'}, etwa {_hm(s['rest_min'])} Fahrzeit.")
        else:
            parts.append("Gerade ist kein Ziel im Navi.")
    if re.search(r"sprit|diesel|tank|reichweite", low):
        parts.append(f"Der Tank ist bei {s['tank_pct']} Prozent, {s['tank_l']} Liter, das reicht etwa {s['reichweite_km']} Kilometer.")
    if re.search(r"schlafen|ruhezeit", low):
        r = s["ruhe_min"]
        parts.append(f"Du musst in {_hm(r)} schlafen." if r > 0 else "Die Ruhezeit ist gerade aus.")
    if re.search(r"verdien|lohn|auftrag|ladung", low):
        if s["auftrag"] and s["ladung"]:
            lohn = f"{s['lohn']:,}".replace(",", ".")
            mass = f" ({s['masse_t']} Tonnen)" if s["masse_t"] else ""
            firma = f", {s['nach_firma']}" if s["nach_firma"] else ""
            parts.append(f"Du fährst {s['ladung']}{mass} von {s['von']} nach {s['nach']}{firma}. Dafür gibt es {lohn} Euro.")
        else:
            parts.append("Du hast gerade keinen Auftrag.")
    if re.search(r"wie schnell|tempolimit|wie viel darf", low):
        parts.append(f"Du fährst {s['kmh']}" + (f", erlaubt sind {s['limit']}." if s["limit"] else ", ein Tempolimit sehe ich gerade nicht."))
    return " ".join(parts) or None


# --- Plugin einmalig installieren ------------------------------------------------------------------------
PLUGIN_URL = "https://github.com/RenCloud/scs-sdk-plugin/releases/download/V.1.12.1/release_v_1_12_1.zip"
PLUGIN_STATUS = ""


def _game_dirs() -> list:
    """Installationsordner von ETS2 und ATS über Steam (Registry + libraryfolders.vdf)."""
    import os
    roots = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"), (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            roots.append(os.path.normpath(winreg.QueryValueEx(k, name)[0]))
                        except OSError:
                            pass
            except OSError:
                pass
    except Exception:
        pass
    roots.append(r"C:\Program Files (x86)\Steam")
    libs = []
    for r in dict.fromkeys(roots):
        libs.append(r)
        try:
            with open(os.path.join(r, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="ignore") as fh:
                libs += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', fh.read())]
        except OSError:
            pass
    out = []
    for lib in dict.fromkeys(libs):
        for game in ("Euro Truck Simulator 2", "American Truck Simulator"):
            d = os.path.join(lib, "steamapps", "common", game, "bin", "win_x64")
            if os.path.isdir(d) and d not in out:
                out.append(d)
    return out


def install_plugin():
    """Legt scs-telemetry.dll in bin\\win_x64\\plugins von ETS2/ATS, falls sie fehlt."""
    global PLUGIN_STATUS
    import io
    import os
    import urllib.request
    import zipfile
    dirs = _game_dirs()
    if not dirs:
        PLUGIN_STATUS = "ETS2 nicht gefunden"
        return
    missing = [d for d in dirs if not os.path.isfile(os.path.join(d, "plugins", "scs-telemetry.dll"))]
    if not missing:
        PLUGIN_STATUS = "Plugin installiert"
        return
    try:
        data = urllib.request.urlopen(urllib.request.Request(PLUGIN_URL, headers={"User-Agent": "Jarvis-PC"}), timeout=60).read()
        z = zipfile.ZipFile(io.BytesIO(data))
        dlls = [n for n in z.namelist() if n.lower().endswith(".dll")]
        pick = next((n for n in dlls if re.search(r"64", n) and "scs-telemetry" in n.lower()), None) or \
            next((n for n in dlls if "scs-telemetry" in n.lower()), None) or (dlls[0] if dlls else None)
        if not pick:
            PLUGIN_STATUS = "Plugin-Download ohne DLL"
            print(f"ETS2-Plugin: keine DLL im Download ({z.namelist()})")
            return
        blob = z.read(pick)
        for d in missing:
            try:
                os.makedirs(os.path.join(d, "plugins"), exist_ok=True)
                with open(os.path.join(d, "plugins", "scs-telemetry.dll"), "wb") as fh:
                    fh.write(blob)
                print(f"ETS2-Plugin installiert: {d}\\plugins ({pick})")
            except OSError as e:
                print(f"ETS2-Plugin: kein Schreibrecht in {d} ({e})")
                PLUGIN_STATUS = "keine Schreibrechte im Spielordner"
                return
        PLUGIN_STATUS = "Plugin installiert"
    except Exception as e:
        PLUGIN_STATUS = f"Plugin-Download ging nicht: {e}"
        print(f"ETS2-Plugin: {PLUGIN_STATUS}")
