"""
Leistungswerte wie im Task-Manager (Reiter "Leistung"): Datenträger, Netzwerk und Grafikkarte.
CPU und RAM liest das HUD selbst. Alles nur lesend und lokal.

Die Werte kommen aus den Windows-Leistungsindikatoren (WMI-Klassen mit englischen Namen, deshalb
geht das auch auf deutschem Windows). Dafür läuft im Hintergrund ein einziges PowerShell-Fenster ohne
Anzeige, das alle 2 Sekunden eine Zeile ausgibt. Wird das HUD nicht angezeigt, pausiert die Abfrage.
"""

import json
import subprocess
import threading
import time

NO_WINDOW = 0x08000000

SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
while ($true) {
  $d = Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -Filter "Name='_Total'"
  $g = @(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine | ForEach-Object { @{ n = $_.Name; u = $_.UtilizationPercentage } })
  $n = @(Get-CimInstance Win32_PerfFormattedData_Tcpip_NetworkInterface)
  $rx = ($n | Measure-Object BytesReceivedPersec -Sum).Sum
  $tx = ($n | Measure-Object BytesSentPersec -Sum).Sum
  $o = @{ disk = $d.PercentDiskTime; rd = $d.DiskReadBytesPersec; wr = $d.DiskWriteBytesPersec; gpu = $g; rx = $rx; tx = $tx }
  [Console]::Out.WriteLine(($o | ConvertTo-Json -Compress -Depth 4))
  [Console]::Out.Flush()
  Start-Sleep -Seconds 2
}
"""


def parse_sample(line: str) -> dict:
    """Macht aus einer Ausgabezeile die Werte fürs HUD. Fehlende Werte bleiben None."""
    data = json.loads(line)
    num = lambda v: float(v) if isinstance(v, (int, float)) else None  # noqa: E731

    gpu = None
    engines = data.get("gpu") or []
    if isinstance(engines, dict):
        engines = [engines]
    if engines:
        per_type: dict = {}
        for e in engines:
            name, util = str(e.get("n", "")), num(e.get("u"))
            if util is None:
                continue
            kind = name.split("engtype_", 1)[-1] if "engtype_" in name else "?"
            per_type[kind] = per_type.get(kind, 0.0) + util
        if per_type:
            gpu = min(100.0, max(per_type.values()))  # wie im Task-Manager: die ausgelastetste Engine
    disk = num(data.get("disk"))
    return {
        "gpu": gpu,
        "disk": None if disk is None else min(100.0, disk),
        "disk_read": num(data.get("rd")),
        "disk_write": num(data.get("wr")),
        "net_down": num(data.get("rx")),
        "net_up": num(data.get("tx")),
    }


class PerfWorker(threading.Thread):
    def __init__(self, get_settings, is_active):
        super().__init__(daemon=True)
        self.get_settings, self.is_active = get_settings, is_active
        self.lock = threading.Lock()
        self.data: dict = {}
        self.ok = None  # None = noch kein Ergebnis, True/False = Daten da / nicht verfügbar
        self.proc = None

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.data, _ok=self.ok)

    def _stop_proc(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None

    def _wanted(self) -> bool:
        try:
            return bool(self.get_settings().get("show_performance", True)) and bool(self.is_active())
        except Exception:
            return False

    def _start_proc(self):
        self.proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", SCRIPT],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            creationflags=NO_WINDOW, text=True, encoding="utf-8", errors="ignore",
        )
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc):
        got = False
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                sample = parse_sample(line)
            except Exception:
                continue
            got = True
            with self.lock:
                self.data, self.ok = sample, True
        if not got:
            with self.lock:
                self.ok = False  # PowerShell fehlt oder liefert nichts

    def run(self):
        while True:
            time.sleep(1.0)
            try:
                if self._wanted():
                    if self.proc is None or self.proc.poll() is not None:
                        if self.ok is False:  # hat schon nicht funktioniert: nicht ständig neu versuchen
                            time.sleep(30)
                            self.ok = None
                        self._start_proc()
                else:
                    self._stop_proc()  # HUD zu: keine Abfrage, kein Stromverbrauch
            except Exception:
                with self.lock:
                    self.ok = False
                time.sleep(30)
