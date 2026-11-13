"""
Fernzugriff über Tailscale (privates Netz zwischen deinem Handy und deinem PC, auch von der Schule aus):

  http://<Tailscale-IP des PCs>:8765/?k=<Schlüssel>        -> dein PC-HUD im Handy-Browser
  http://<Tailscale-IP des PCs>:8765/cam?k=<Schlüssel>     -> Webcam live (nur wenn "Webcam von unterwegs" an ist)
  POST /phonecam?k=<Schlüssel>                             -> Bilder der Handy-Kamera (HUD zeigt sie, solange sie kommen)

Sicherheit: Der Server antwortet nur Geräten aus deinem Tailscale-Netz (100.64.0.0/10) und nur mit dem Schlüssel,
der aus deinem Kopplungscode berechnet wird (die Handy-App kennt ihn, sonst niemand). Solange jemand die Webcam
anschaut, steht das groß am PC-Bildschirm.
"""

import hashlib
import http.client
import ipaddress
import os
import re
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765
TS_NET = ipaddress.ip_network("100.64.0.0/10")
HUD_PORT = None          # vom Programm gesetzt: Port des lokalen HUD-Servers (Funktion)
SETTINGS = None          # vom Programm gesetzt: aktuelle Einstellungen (Funktion)
ON_WATCH = None          # vom Programm gesetzt: Hinweis am Bildschirm (an/aus)
PHONE_FRAME = {"jpg": b"", "t": 0.0}
_viewers = [0]
_lock = threading.Lock()
STATUS = ""


def token() -> str:
    import pc_link
    return hashlib.sha256(("jarvis-fern:" + pc_link._norm(pc_link.code())).encode()).hexdigest()[:24]


def tailscale_ip() -> str:
    """IPv4-Adresse des PCs im Tailscale-Netz (leer, wenn Tailscale nicht läuft)."""
    try:
        import psutil
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                try:
                    if ":" not in a.address and ipaddress.ip_address(a.address) in TS_NET:
                        return a.address
                except ValueError:
                    pass
    except Exception:
        pass
    for exe in (r"C:\Program Files\Tailscale\tailscale.exe", "tailscale"):
        try:
            out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5, creationflags=0x08000000).stdout
            ip = out.strip().splitlines()[0].strip() if out.strip() else ""
            if ip:
                return ip
        except Exception:
            pass
    return ""


def _cam_allowed() -> bool:
    try:
        return bool((SETTINGS() if SETTINGS else {}).get("webcam_fern", False))
    except Exception:
        return False


def _watch(delta: int):
    with _lock:
        _viewers[0] = max(0, _viewers[0] + delta)
        n = _viewers[0]
    if ON_WATCH:
        try:
            ON_WATCH(n > 0)
        except Exception:
            pass


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _ok_client(self) -> bool:
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        if ip not in TS_NET and not ip.is_loopback:
            return False
        u = urllib.parse.urlparse(self.path)
        k = dict(urllib.parse.parse_qsl(u.query)).get("k") or ""
        if not k:
            m = re.search(r"(?:^|;\s*)jt=([0-9a-f]+)", self.headers.get("Cookie") or "")
            k = m.group(1) if m else ""
        return bool(k) and k == token()

    def _deny(self):
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Kein Zugriff. Öffne den Link aus der Jarvis-App.".encode())

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if not self._ok_client():
            return self._deny()
        u = urllib.parse.urlparse(self.path)
        if u.path == "/cam":
            return self._cam()
        if u.path == "/phonecam.jpg":
            return self._send(200, PHONE_FRAME["jpg"], "image/jpeg")
        return self._proxy("GET")

    def do_POST(self):
        if not self._ok_client():
            return self._deny()
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        if u.path == "/phonecam":
            PHONE_FRAME.update(jpg=body, t=time.time())
            self.send_response(204)
            self._cors()
            self.end_headers()
            return
        return self._proxy("POST", body)

    def _send(self, code, data: bytes, ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self, method: str, body: bytes = b""):
        """HUD von unterwegs: alles an den lokalen HUD-Server weiterreichen (Schlüssel als Cookie merken)."""
        port = HUD_PORT() if HUD_PORT else 0
        if not port:
            return self._send(503, "Das HUD läuft gerade nicht.".encode())
        u = urllib.parse.urlparse(self.path)
        q = [(a, b) for a, b in urllib.parse.parse_qsl(u.query) if a != "k"]
        path = (u.path if u.path != "/" else "/hud.html") + ("?" + urllib.parse.urlencode(q) if q else "")
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
            c.request(method, path, body=body or None, headers={"Content-Type": self.headers.get("Content-Type") or "application/json"})
            r = c.getresponse()
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() not in ("content-length", "transfer-encoding", "connection"):
                    self.send_header(k, v)
            if "k=" in (u.query or ""):
                self.send_header("Set-Cookie", f"jt={token()}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax")
            if u.path == "/events":   # Ereignis-Strom durchreichen
                self.end_headers()
                while True:
                    chunk = r.read1(4096) if hasattr(r, "read1") else r.read(1)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                return
            data = r.read()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            pass

    def _cam(self):
        if not _cam_allowed():
            return self._send(403, "Die Webcam ist für unterwegs ausgeschaltet (Einstellungen am PC: Fernzugriff).".encode())
        try:
            import cv2
        except Exception:
            return self._send(503, "Für die Webcam fehlt noch ein Paket. Führe build.bat noch einmal aus.".encode())
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            return self._send(503, "Keine Webcam gefunden.".encode())
        _watch(+1)
        print("Fernzugriff: Webcam wird angesehen")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            until = time.time() + 30 * 60   # höchstens 30 Minuten am Stück
            while time.time() < until:
                ok, frame = cap.read()
                if not ok:
                    break
                h, w = frame.shape[:2]
                if w > 960:
                    frame = cv2.resize(frame, (960, int(h * 960 / w)))
                ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if not ok:
                    continue
                b = jpg.tobytes()
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(b)).encode() + b"\r\n\r\n" + b + b"\r\n")
                self.wfile.flush()
                time.sleep(0.08)
        except Exception:
            pass
        finally:
            cap.release()
            _watch(-1)
            print("Fernzugriff: Webcam aus")


def start(stop: threading.Event):
    global STATUS

    def run():
        global STATUS
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
            srv.daemon_threads = True
        except OSError as e:
            STATUS = f"Fernzugriff nicht möglich: {e}"
            print(STATUS)
            return
        STATUS = "Fernzugriff bereit"
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        stop.wait()
        srv.shutdown()
    threading.Thread(target=run, daemon=True, name="fern").start()


def info() -> dict:
    """Für den Status ans Handy: Tailscale-IP und Port."""
    ip = tailscale_ip()
    return {"ip": ip, "port": PORT, "cam": _cam_allowed(), "phonecam": time.time() - PHONE_FRAME["t"] < 5} if ip else {}
