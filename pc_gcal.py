"""
Termine in einen Google-Kalender EINTRAGEN (offizielle Google-Calendar-Schnittstelle, Anmeldung mit OAuth).

Damit trägt Jarvis die TimeTree-Termine in einen Google-Kalender deiner Wahl ein: gleicher Tag, gleiche Uhrzeit.
Was er einträgt, markiert er unsichtbar als "von Jarvis", so wird nichts doppelt eingetragen, Änderungen aus TimeTree
werden übernommen, und gelöschte TimeTree-Termine verschwinden wieder. Deine eigenen Google-Termine fasst er nicht an.

Einmalig einrichten (siehe Hilfe im Tab "Infos"): In der Google Cloud Console ein Projekt anlegen, die "Google Calendar API"
aktivieren, einen OAuth-Client vom Typ "Desktop-App" erstellen und dessen Client-ID und Client-Secret in Jarvis eintragen.
Dann "Bei Google anmelden" klicken und den Kalender auswählen.
"""

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
SCOPES = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.calendarlist.readonly"
MARK = "jarvisSource"
MARK_VALUE = "timetree"

CLIENT_ID = ""
CLIENT_SECRET = ""
REFRESH_TOKEN = ""
CALENDAR_ID = ""
ENABLED = False

_token = {"access": "", "until": 0.0}
last_message = ""


class GError(Exception):
    pass


def configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET and REFRESH_TOKEN and CALENDAR_ID)


def configure(enabled, client_id, client_secret, refresh_token, calendar_id):
    global ENABLED, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, CALENDAR_ID
    changed = (client_id, refresh_token) != (CLIENT_ID, REFRESH_TOKEN)
    ENABLED, CLIENT_ID, CLIENT_SECRET = bool(enabled), (client_id or "").strip(), (client_secret or "").strip()
    REFRESH_TOKEN, CALENDAR_ID = refresh_token or "", (calendar_id or "").strip()
    if changed:
        _token.update(access="", until=0.0)


# --- HTTP -----------------------------------------------------------------------------------
def _request(method, url, data=None, headers=None, form=False, timeout=30):
    body = None
    hdrs = dict(headers or {})
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8") or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            msg = json.loads(raw).get("error_description") or json.loads(raw)["error"]
            msg = msg["message"] if isinstance(msg, dict) else msg
        except Exception:
            msg = raw[:200]
        raise GError(f"{e.code}: {msg}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GError(f"keine Verbindung ({getattr(e, 'reason', e)})") from None


# --- Anmeldung ---------------------------------------------------------------------------------
def login(client_id: str, client_secret: str, open_browser=webbrowser.open, timeout: float = 240.0):
    """Öffnet die Google-Anmeldung im Browser. Gibt das Refresh-Token zurück (dauerhafte Erlaubnis)."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q or "error" in q:
                result["code"] = (q.get("code") or [""])[0]
                result["error"] = (q.get("error") or [""])[0]
                result["state"] = (q.get("state") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<html><body style='font-family:sans-serif;background:#031018;color:#cdeffc;text-align:center;padding-top:80px'>"
                             "<h2>Fertig.</h2><p>Du kannst dieses Fenster schließen und zu Jarvis zurückgehen.</p></body></html>".encode("utf-8"))

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1.0
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    open_browser(url)
    end = time.time() + timeout
    try:
        while time.time() < end and "code" not in result:
            server.handle_request()
    finally:
        server.server_close()
    if result.get("error"):
        raise GError(f"Anmeldung abgelehnt ({result['error']})")
    if not result.get("code") or result.get("state") != state:
        raise GError("Die Anmeldung wurde nicht abgeschlossen")
    tok = _request("POST", TOKEN_URL, {
        "code": result["code"], "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect,
        "grant_type": "authorization_code", "code_verifier": verifier}, form=True)
    if not tok.get("refresh_token"):
        raise GError("Google hat keine dauerhafte Erlaubnis geschickt. Entferne Jarvis unter myaccount.google.com/permissions und versuche es nochmal")
    return tok["refresh_token"]


def access_token() -> str:
    if _token["access"] and time.time() < _token["until"] - 60:
        return _token["access"]
    if not (CLIENT_ID and CLIENT_SECRET and REFRESH_TOKEN):
        raise GError("Google ist noch nicht eingerichtet")
    tok = _request("POST", TOKEN_URL, {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                                       "refresh_token": REFRESH_TOKEN, "grant_type": "refresh_token"}, form=True)
    _token["access"], _token["until"] = tok["access_token"], time.time() + int(tok.get("expires_in", 3600))
    return _token["access"]


def _api(method, path, data=None, params=None):
    url = API + path + (("?" + urllib.parse.urlencode(params, doseq=True)) if params else "")
    return _request(method, url, data, {"Authorization": "Bearer " + access_token()})


def list_calendars() -> list:
    """Kalender, in die man schreiben darf: [(Name, ID)]."""
    data = _api("GET", "/users/me/calendarList", params={"minAccessRole": "writer", "maxResults": 250})
    return [(c.get("summaryOverride") or c.get("summary", c["id"]), c["id"]) for c in data.get("items", [])]


# --- Termine übertragen -----------------------------------------------------------------------
def _when(dt, allday):
    import datetime

    if allday:
        return {"date": dt.strftime("%Y-%m-%d")}
    return {"dateTime": dt.astimezone().isoformat(timespec="seconds")}  # naive Ortszeit -> mit Zeitzonen-Versatz


def to_google(ev: dict) -> dict:
    import datetime

    start, end = ev["start"], ev["end"]
    if ev["allday"] and end <= start:
        end = start + datetime.timedelta(days=1)
    if not ev["allday"] and end <= start:
        end = start + datetime.timedelta(hours=1)
    return {
        "summary": ev["summary"],
        "start": _when(start, ev["allday"]),
        "end": _when(end, ev["allday"]),
        "extendedProperties": {"private": {MARK: MARK_VALUE, "jarvisId": ev["id"]}},
        "reminders": {"useDefault": True},
    }


def _same(old: dict, new: dict) -> bool:
    def norm(x):
        return (x.get("summary"), x.get("start", {}).get("date") or x.get("start", {}).get("dateTime", "")[:19],
                x.get("end", {}).get("date") or x.get("end", {}).get("dateTime", "")[:19])
    return norm(old) == norm(new)


def push(events: list, begin, end):
    """Gleicht die Termine (aus pc_calendar.expand, jeweils mit "id") im Zeitraum mit dem Zielkalender ab.
    Gibt (neu, geändert, gelöscht) zurück."""
    cal = urllib.parse.quote(CALENDAR_ID, safe="")
    existing, token = {}, None
    while True:
        params = {"privateExtendedProperty": f"{MARK}={MARK_VALUE}", "timeMin": begin.astimezone().isoformat(),
                  "timeMax": end.astimezone().isoformat(), "singleEvents": "true", "maxResults": 2500}
        if token:
            params["pageToken"] = token
        page = _api("GET", f"/calendars/{cal}/events", params=params)
        for item in page.get("items", []):
            jid = item.get("extendedProperties", {}).get("private", {}).get("jarvisId")
            if jid and item.get("status") != "cancelled":
                existing[jid] = item
        token = page.get("nextPageToken")
        if not token:
            break
    new = changed = deleted = 0
    wanted = {}
    for ev in events:
        body = to_google(ev)
        wanted[ev["id"]] = body
    for jid, body in wanted.items():
        old = existing.get(jid)
        if old is None:
            _api("POST", f"/calendars/{cal}/events", body)
            new += 1
        elif not _same(old, body):
            _api("PATCH", f"/calendars/{cal}/events/{urllib.parse.quote(old['id'], safe='')}", body)
            changed += 1
    stale = [item for jid, item in existing.items() if jid not in wanted]
    if events and len(stale) <= max(5, len(existing) // 3):  # Sicherung: bei auffällig vielen Löschungen nichts löschen
        for item in stale:
            _api("DELETE", f"/calendars/{cal}/events/{urllib.parse.quote(item['id'], safe='')}")
            deleted += 1
    return new, changed, deleted


def sync_timetree(days_back: int = 14, days_ahead: int = 365):
    """Liest die TimeTree-Datei und trägt die Termine in den Google-Kalender ein. Gibt (ok, Meldung) zurück."""
    global last_message
    import datetime

    import pc_calendar
    import pc_timetree

    path = pc_timetree.active_file() or pc_timetree.out_path()
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            events = pc_calendar.parse_ics(f.read())
    except OSError:
        return False, "Es gibt noch keine TimeTree-Termine. Erst mit TimeTree synchronisieren."
    if not configured():
        return False, "Google ist noch nicht fertig eingerichtet (Anmeldung und Kalender wählen)."
    now = datetime.datetime.now()
    begin = (now - datetime.timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now + datetime.timedelta(days=days_ahead)
    inst = pc_calendar.expand(events, begin, end)
    seen = {}
    for e in inst:  # eindeutige Kennung je Termin und Startzeit
        base = f"{e['uid']}|{e['start']:%Y%m%dT%H%M}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        e["id"] = base if n == 0 else f"{base}#{n}"
    try:
        new, changed, deleted = push(inst, begin, end)
    except GError as e:
        last_message = f"Google-Abgleich fehlgeschlagen: {e}"
        return False, last_message
    last_message = f"Google Kalender: {new} neu, {changed} geändert, {deleted} entfernt (von {len(inst)} Terminen)"
    return True, last_message
