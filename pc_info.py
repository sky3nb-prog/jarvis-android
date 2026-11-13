"""
Datenquellen für das HUD (alles nur lesend, nichts verlässt den PC außer der Wetterabfrage):

- Wetter: kostenloser Dienst Open-Meteo (kein Schlüssel nötig), Ort aus den Einstellungen
- Benachrichtigungen: Windows legt angezeigte Benachrichtigungen in einer Datenbank im
  eigenen Benutzerordner ab (wpndatabase.db). Das HUD liest dort nur die letzten Einträge,
  schreibt nichts und sendet nichts. Abschaltbar in den Einstellungen.
- Temperaturen: NVIDIA-Grafikkarte (nvidia-smi) und, falls Windows sie freigibt, die CPU.
"""

import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

WMO = {
    0: "Klar", 1: "Überwiegend klar", 2: "Teils bewölkt", 3: "Bedeckt", 45: "Nebel", 48: "Reifnebel",
    51: "Leichter Nieselregen", 53: "Nieselregen", 55: "Starker Nieselregen",
    56: "Gefrierender Nieselregen", 57: "Gefrierender Nieselregen",
    61: "Leichter Regen", 63: "Regen", 65: "Starker Regen", 66: "Gefrierender Regen", 67: "Gefrierender Regen",
    71: "Leichter Schneefall", 73: "Schneefall", 75: "Starker Schneefall", 77: "Schneegriesel",
    80: "Leichte Schauer", 81: "Schauer", 82: "Starke Schauer", 85: "Schneeschauer", 86: "Starke Schneeschauer",
    95: "Gewitter", 96: "Gewitter mit Hagel", 99: "Gewitter mit starkem Hagel",
}
WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
NO_WINDOW = 0x08000000


# --- Wetter ----------------------------------------------------------------
def _get_json(url: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "JarvisHUD/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def geocode(city: str):
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": city, "count": 1, "language": "de", "format": "json"}
    )
    results = _get_json(url).get("results") or []
    if not results:
        raise ValueError(f"Ort '{city}' nicht gefunden")
    r = results[0]
    return r["latitude"], r["longitude"], r.get("name", city)


def parse_weather(name: str, data: dict) -> dict:
    cur, daily = data["current"], data["daily"]
    days, full = [], []
    rain = daily.get("precipitation_probability_max") or [None] * len(daily["time"])
    for i, date in enumerate(daily["time"]):
        d = datetime.date.fromisoformat(date)
        text = WMO.get(daily["weather_code"][i], "")
        days.append((WEEKDAYS_SHORT[d.weekday()], daily["temperature_2m_min"][i], daily["temperature_2m_max"][i], text))
        full.append({"date": date, "weekday": d.weekday(), "min": daily["temperature_2m_min"][i],
                     "max": daily["temperature_2m_max"][i], "text": text, "rain": rain[i]})
    return {
        "city": name,
        "temp": cur["temperature_2m"],
        "feels": cur["apparent_temperature"],
        "humidity": cur["relative_humidity_2m"],
        "wind": cur["wind_speed_10m"],
        "text": WMO.get(cur["weather_code"], ""),
        "days": days[1:8],  # die nächsten sieben Tage
        "full": full,  # alle Tage ab heute mit Regenwahrscheinlichkeit (für Sprachfragen)
    }


def fetch_weather(city: str) -> dict:
    lat, lon, name = geocode(city)
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 8,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    })
    return parse_weather(name, _get_json(url))


# --- Benachrichtigungen ---------------------------------------------------------
def _app_name(primary_id) -> str:
    name = str(primary_id or "")
    name = name.split("!")[0].split("_")[0]
    name = name.split(".")[-1] or name
    return name or "System"


def parse_toast(payload) -> tuple:
    """(Titel, Text) aus dem XML einer Windows-Benachrichtigung."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="ignore")
    payload = re.sub(r"^\s*<\?xml[^>]*\?>", "", payload or "").strip().lstrip("\ufeff")
    root = ET.fromstring(payload)
    texts = [t.text.strip() for t in root.iter() if t.tag.split("}")[-1] == "text" and t.text and t.text.strip()]
    return (texts[0] if texts else ""), " ".join(texts[1:])


def _query_notifications(con, limit: int) -> list:
    rows = con.execute(
        "SELECT n.Payload, n.ArrivalTime, h.PrimaryId FROM Notification n "
        "LEFT JOIN NotificationHandler h ON n.HandlerId = h.RecordId "
        "WHERE n.Type = 'toast' ORDER BY n.ArrivalTime DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    for payload, arrival, pid in rows:
        try:
            title, body = parse_toast(payload)
            ts = (int(arrival) - 116444736000000000) / 1e7  # Windows-Zeit -> Unix-Zeit
        except Exception:
            continue
        out.append({"app": _app_name(pid), "title": title, "body": body, "ts": ts})
    return out


def read_notifications(limit: int = 6):
    """Letzte Benachrichtigungen oder None, wenn Windows sie nicht lesbar macht."""
    db = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Notifications", "wpndatabase.db")
    if not os.path.exists(db):
        return None
    try:  # direkt, nur lesend
        con = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True, timeout=2)
        try:
            return _query_notifications(con, limit)
        finally:
            con.close()
    except Exception:
        pass
    tmp = tempfile.mkdtemp()  # Ersatzweg: Kopie lesen
    try:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db + suffix):
                shutil.copy2(db + suffix, os.path.join(tmp, "w.db" + suffix))
        con = sqlite3.connect(os.path.join(tmp, "w.db"))
        try:
            return _query_notifications(con, limit)
        finally:
            con.close()
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- Temperaturen ------------------------------------------------------------------
def read_temps() -> dict:
    out = {}
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW,
        )
        line = r.stdout.strip().splitlines()[0]
        out["GPU"] = float(line)
    except Exception:
        pass
    try:
        ps = ("(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
              "-ErrorAction Stop | Select-Object -First 1).CurrentTemperature")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        value = float(r.stdout.strip())
        celsius = value / 10.0 - 273.15
        if 0 < celsius < 120:
            out["CPU"] = celsius
    except Exception:
        pass
    return out


# --- Hintergrund-Abfragen für das HUD --------------------------------------------------
class InfoWorker(threading.Thread):
    """Holt Wetter, Benachrichtigungen und Temperaturen, solange das HUD sichtbar ist."""

    def __init__(self, get_settings, is_active):
        super().__init__(daemon=True)
        self.get_settings, self.is_active = get_settings, is_active
        self.lock = threading.Lock()
        self.data = {"weather": None, "weather_err": None, "notes": None, "temps": None}
        self._due = {"weather": 0.0, "notes": 0.0, "temps": 0.0}
        self._wake = threading.Event()
        self.started_at = time.time()

    def refresh_weather(self):
        self._due["weather"] = 0.0
        self._wake.set()

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.data)

    def _set(self, **kw):
        with self.lock:
            self.data.update(kw)

    def run(self):
        while True:
            self._wake.wait(2.0)
            self._wake.clear()
            try:
                if not self.is_active():
                    continue
                s, now = self.get_settings(), time.time()
                if s.get("show_weather") and now >= self._due["weather"]:
                    try:
                        self._set(weather=fetch_weather(s.get("weather_city", "")), weather_err=None)
                        self._due["weather"] = now + 900
                    except Exception as e:
                        self._set(weather_err=str(e))
                        self._due["weather"] = now + 120
                if s.get("show_notifications") and now >= self._due["notes"]:
                    self._set(notes=read_notifications(12))
                    self._due["notes"] = now + 10
                if s.get("show_pc_temps") and now >= self._due["temps"]:
                    self._set(temps=read_temps())
                    self._due["temps"] = now + 30
            except Exception as e:
                print(f"HUD-Daten: {e}")
