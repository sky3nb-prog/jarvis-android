"""
Google-Kalender (nur lesen, ohne Anmeldung und ohne Google-Cloud-Konto) und Termine vorbereiten.

So gibst du Jarvis Zugriff:
  1. Google Kalender im Browser öffnen, links beim Kalender auf die drei Punkte, "Einstellungen und Freigabe".
  2. Ganz unten "Privatadresse im iCal-Format" kopieren (beginnt mit https://calendar.google.com/calendar/ical/ ...).
  3. In Jarvis: Zahnrad, Tab "Infos", Feld "Kalender-Adresse" einfügen, Speichern.

Achtung: Wer diese Adresse kennt, kann deinen Kalender lesen. Sie liegt nur in einstellungen.json auf diesem PC.
Neue Termine legt Jarvis nicht selbst an: Er öffnet Google Kalender mit ausgefülltem Termin, du klickst auf Speichern.

  "Was habe ich heute / morgen / am Freitag / diese Woche?"
  "Wann ist mein nächster Termin?"
  "Trag einen Termin ein: Zahnarzt morgen um 15 Uhr"
"""

import datetime
import re
import threading
import time
import urllib.parse
import urllib.request

URL = ""  # aus den Einstellungen
_cache = {"url": None, "ts": 0.0, "events": []}
_lock = threading.Lock()
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
DAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def sources() -> list:
    """Kalender-Quellen aus den Einstellungen: Internetadressen (iCal) oder .ics-Dateien auf diesem PC, mit Semikolon
    getrennt."""
    parts = [p.strip().strip('"') for p in re.split(r"[;\n]+", URL.strip())]
    found = [p for p in parts if p.lower().startswith(("http", "webcal")) or p.lower().endswith(".ics")]
    # TimeTree liest Jarvis NICHT mehr extra mit: die Termine landen über den Abgleich ohnehin im Google-Kalender,
    # sonst würde er jeden Termin doppelt vorlesen.
    return found


def configured() -> bool:
    return bool(sources())


def reset_cache():
    with _lock:
        _cache.update(url=None, ts=0.0, events=[])


# --- iCal lesen ---------------------------------------------------------------------------------
def _unfold(text: str):
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _unescape(v: str) -> str:
    return v.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _split(line: str):
    head, _, value = line.partition(":")
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def _parse_dt(value: str, params: dict):
    """Gibt (lokales datetime ohne Zeitzone, ganztägig) zurück."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
        return datetime.datetime.strptime(value[:8], "%Y%m%d"), True
    if value.endswith("Z"):
        dt = datetime.datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone().replace(tzinfo=None), False
    dt = datetime.datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    tzid = params.get("TZID")
    if tzid:
        try:
            from zoneinfo import ZoneInfo

            return dt.replace(tzinfo=ZoneInfo(tzid)).astimezone().replace(tzinfo=None), False
        except Exception:
            pass  # ohne Zeitzonen-Datenbank: Uhrzeit so nehmen, wie sie ist
    return dt, False


def parse_ics(text: str) -> list:
    events, cur = [], None
    for line in _unfold(text):
        name, params, value = _split(line)
        if name == "BEGIN" and value.strip().upper() == "VEVENT":
            cur = {"exdates": set(), "rrule": None, "rid": None, "summary": "(ohne Titel)", "uid": "", "end": None}
        elif name == "END" and value.strip().upper() == "VEVENT":
            if cur and cur.get("start"):
                if cur["end"] is None:
                    cur["end"] = cur["start"] + (datetime.timedelta(days=1) if cur["allday"] else datetime.timedelta())
                events.append(cur)
            cur = None
        elif cur is not None:
            try:
                if name == "SUMMARY":
                    cur["summary"] = _unescape(value) or "(ohne Titel)"
                elif name == "UID":
                    cur["uid"] = value.strip()
                elif name == "DTSTART":
                    cur["start"], cur["allday"] = _parse_dt(value, params)
                elif name == "DTEND":
                    cur["end"], _ = _parse_dt(value, params)
                elif name == "RRULE":
                    cur["rrule"] = dict(p.split("=", 1) for p in value.split(";") if "=" in p)
                elif name == "EXDATE":
                    for v in value.split(","):
                        cur["exdates"].add(_parse_dt(v, params)[0])
                elif name == "RECURRENCE-ID":
                    cur["rid"] = _parse_dt(value, params)[0]
                elif name == "STATUS" and value.strip().upper() == "CANCELLED":
                    cur["cancelled"] = True
            except Exception:
                continue
    return [e for e in events if not e.get("cancelled")]


def _until(rule: dict):
    u = rule.get("UNTIL")
    if not u:
        return None
    try:
        return _parse_dt(u, {})[0] + (datetime.timedelta(days=1) if len(u) == 8 else datetime.timedelta())
    except Exception:
        return None


def _nth_weekday(year: int, month: int, weekday: int, n: int):
    if n > 0:
        first = datetime.date(year, month, 1)
        day = 1 + (weekday - first.weekday()) % 7 + 7 * (n - 1)
    else:
        nxt = datetime.date(year + (month == 12), month % 12 + 1, 1)
        last = nxt - datetime.timedelta(days=1)
        day = last.day - (last.weekday() - weekday) % 7 + 7 * (n + 1)
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _occurrences(ev: dict, limit: datetime.datetime):
    """Alle Startzeiten einer (ggf. wiederkehrenden) Serie bis limit."""
    start, rule = ev["start"], ev["rrule"]
    if not rule:
        yield start
        return
    freq, interval = rule.get("FREQ", ""), max(1, int(rule.get("INTERVAL", 1)))
    count = int(rule["COUNT"]) if rule.get("COUNT") else None
    until, t = _until(rule), start.time()
    byday = [d for d in rule.get("BYDAY", "").split(",") if d]
    bymonthday = [int(x) for x in rule.get("BYMONTHDAY", "").split(",") if x]
    produced = 0

    def gen():
        k = 0
        while k < 20000:
            if freq == "DAILY":
                yield start + datetime.timedelta(days=k * interval)
            elif freq == "WEEKLY":
                monday = start.date() - datetime.timedelta(days=start.weekday()) + datetime.timedelta(weeks=k * interval)
                days = sorted(DAY_CODES.index(d[-2:]) for d in byday) if byday else [start.weekday()]
                for wd in days:
                    yield datetime.datetime.combine(monday + datetime.timedelta(days=wd), t)
            elif freq == "MONTHLY":
                month0 = start.month - 1 + k * interval
                y, m = start.year + month0 // 12, month0 % 12 + 1
                if byday:
                    for d in byday:
                        n = int(d[:-2]) if d[:-2] else 1
                        day = _nth_weekday(y, m, DAY_CODES.index(d[-2:]), n)
                        if day:
                            yield datetime.datetime.combine(day, t)
                else:
                    for md in (bymonthday or [start.day]):
                        try:
                            yield datetime.datetime.combine(datetime.date(y, m, md), t)
                        except ValueError:
                            pass
            elif freq == "YEARLY":
                try:
                    yield start.replace(year=start.year + k * interval)
                except ValueError:
                    pass
            else:
                return
            k += 1
            if k * (1 if freq == "DAILY" else 7 if freq == "WEEKLY" else 28 if freq == "MONTHLY" else 365) * interval > 36500:
                return

    for occ in gen():
        if occ < start:
            continue
        if until and occ >= until:
            return
        if occ > limit:
            return
        produced += 1
        yield occ
        if count and produced >= count:
            return


def expand(events: list, begin: datetime.datetime, end: datetime.datetime) -> list:
    overridden = {(e["uid"], e["rid"]) for e in events if e["rid"]}
    out = []
    for ev in events:
        dur = ev["end"] - ev["start"]
        if ev["rid"]:
            starts = [ev["start"]]
        else:
            starts = [s for s in _occurrences(ev, end) if s not in ev["exdates"] and (ev["uid"], s) not in overridden]
        for s in starts:
            e = s + dur
            if s < end and (e > begin or (e == s and s >= begin)):
                out.append({"start": s, "end": e, "summary": ev["summary"], "allday": ev["allday"], "uid": ev["uid"]})
    return sorted(out, key=lambda x: (x["start"], x["summary"]))


# --- Abrufen ---------------------------------------------------------------------------------
def _fetch_one(src: str) -> list:
    if src.lower().startswith("http") or src.lower().startswith("webcal"):
        req = urllib.request.Request(src.replace("webcal://", "https://", 1), headers={"User-Agent": "Jarvis"})
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read().decode("utf-8", "ignore")
    else:
        with open(src.strip('"'), encoding="utf-8", errors="ignore") as f:
            text = f.read()
    if "BEGIN:VCALENDAR" not in text:
        raise ValueError("Das ist keine Kalenderadresse oder -datei im iCal-Format")
    return parse_ics(text)


def fetch(url: str = None) -> list:
    global URL
    old, URL = URL, (url if url is not None else URL)
    try:
        events = []
        for src in sources():
            events += _fetch_one(src)
        return events
    finally:
        URL = old


def events_between(begin: datetime.datetime, end: datetime.datetime) -> list:
    with _lock:
        fresh = _cache["url"] == URL and time.time() - _cache["ts"] < 600
        events = _cache["events"]
    if not fresh:
        events = fetch()
        with _lock:
            _cache.update(url=URL, ts=time.time(), events=events)
    out, seen = [], set()
    for e in expand(events, begin, end):  # gleiche Termine (z. B. aus zwei Kalendern) nur einmal
        k = (" ".join(str(e.get("summary", "")).lower().split()), e["start"].strftime("%Y%m%d%H%M"))
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return out


def test(url: str) -> str:
    try:
        events = fetch(url)
        now = datetime.datetime.now()
        n = len(expand(events, now, now + datetime.timedelta(days=30)))
        return f"✔ Verbindung steht. In den nächsten 30 Tagen stehen {n} Termine an."
    except Exception as e:
        return f"✘ Das hat nicht geklappt: {e}"


# --- Sprache ---------------------------------------------------------------------------------
def _when(e: dict, today: datetime.date) -> str:
    d = e["start"].date()
    day = "heute" if d == today else "morgen" if d == today + datetime.timedelta(days=1) else \
        f"am {WEEKDAYS[d.weekday()]}, den {d.day}.{d.month}."
    if e["allday"]:
        return f"{day} ganztägig {e['summary']}"
    return f"{day} um {e['start'].strftime('%H:%M')} Uhr {e['summary']}"


def _ongoing(e: dict, first: datetime.date) -> str:
    """Termin über mehrere Tage, der schon vor dem gefragten Tag angefangen hat: "läuft noch bis ..."."""
    last = e["end"].date() - datetime.timedelta(days=1) if e["allday"] else e["end"].date()
    s = e["start"].date()
    until = f" bis {WEEKDAYS[last.weekday()]}, den {last.day}.{last.month}." if last > first else ""
    return f"{e['summary']} läuft noch (seit {WEEKDAYS[s.weekday()]}, den {s.day}.{s.month}.{until})"


def _list(events: list, today: datetime.date, first: datetime.date = None) -> str:
    """Erst die Termine, die im gefragten Zeitraum anfangen, dann die mehrtägigen, die noch laufen."""
    first = first or today
    new = [e for e in events if e["start"].date() >= first]
    old = [e for e in events if e["start"].date() < first]
    parts = [_when(e, today) for e in new[:8]] + [_ongoing(e, first) for e in old[:3]]
    return "; ".join(parts) + ("." if parts else "")


def _time_only(e: dict) -> str:
    return f"ganztägig {e['summary']}" if e["allday"] else f"um {e['start'].strftime('%H:%M')} Uhr {e['summary']}"


def today_text() -> str:
    """Für den Start: die Termine von heute mit Uhrzeit (ohne jedes Mal "heute" zu sagen).
    Leer, wenn kein Kalender eingerichtet ist."""
    if not configured():
        return ""
    try:
        now = datetime.datetime.now()
        events = [e for e in events_between(now.replace(hour=0, minute=0, second=0, microsecond=0),
                                            now.replace(hour=23, minute=59, second=59)) if e["end"] > now or e["allday"]]
        today = now.date()
        new = [e for e in events if e["start"].date() >= today]
        old = [e for e in events if e["start"].date() < today]
        if not new:
            return "Heute stehen keine Termine an." + (" Es läuft noch: " + _list(old, today, today) if old else "")
        return "Heute: " + ", ".join(_time_only(e) for e in new[:8]) + "." + \
            (" Außerdem läuft noch: " + _list(old, today, today) if old else "")
    except Exception:
        return ""


def _title(text: str) -> str:
    t = re.sub(r"^(?:trag|trage|erstell|erstelle|leg|lege|mach|mache|füg|füge|setz|setze)\w*\s+(?:mir\s+)?(?:bitte\s+|mal\s+)*", "", text.strip(), flags=re.I)
    t = re.sub(r"^(?:einen?\s+)?(?:neuen?\s+)?(?:termin|kalendereintrag|eintrag)\s*(?:in\s+(?:meinen\s+)?(?:den\s+)?kalender\s*)?(?:an|ein|auf)?\s*[:,]?\s*", "", t, flags=re.I)
    t = re.sub(r"\b(?:heute|morgen|übermorgen|am\s+\w+tag|am\s+(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|sonnabend))\b", " ", t, flags=re.I)
    t = re.sub(r"\bum\s+\d{1,2}(?:[:.]\d{2})?\s*(?:uhr)?\b", " ", t, flags=re.I)
    t = re.sub(r"\b(?:für|in)\s+(?:meinen\s+)?(?:den\s+)?kalender\b", " ", t, flags=re.I)
    return " ".join(t.split()).strip(" ,:.") or "Termin"


def create(text: str):
    """Öffnet Google Kalender mit ausgefülltem Termin."""
    import webbrowser

    import pc_talk

    low = pc_talk._norm(text)
    delta, _ = pc_talk._parse_day(low)
    day = datetime.date.today() + datetime.timedelta(days=delta if isinstance(delta, int) else 0)
    m = re.search(r"\bum (\d{1,2})(?: ?(?:uhr|:|\.) ?(\d{2}))?", low)
    if m:
        start = datetime.datetime.combine(day, datetime.time(int(m.group(1)) % 24, int(m.group(2) or 0)))
        dates = f"{start:%Y%m%dT%H%M%S}/{start + datetime.timedelta(hours=1):%Y%m%dT%H%M%S}"
        when = f"{start:%H:%M} Uhr"
    else:
        dates = f"{day:%Y%m%d}/{day + datetime.timedelta(days=1):%Y%m%d}"  # ganztägig
        when = "ganztägig"
    title = _title(text)
    title = title[0].upper() + title[1:]
    direct = _insert_google(title, day, start if m else None)
    if direct:
        return direct
    url = "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(
        {"action": "TEMPLATE", "text": title, "dates": dates}, quote_via=urllib.parse.quote)
    webbrowser.open(url)
    return f"Ich habe den Termin „{title}“ am {day.day}.{day.month}. ({when}) in Google Kalender vorbereitet. Du musst nur noch auf Speichern klicken."


def _insert_google(title: str, day: datetime.date, start, minutes: int = 60):
    """Direkt in den Google-Kalender eintragen (wenn Google unter Infos angemeldet ist). Sonst None."""
    try:
        import urllib.parse as up

        import pc_gcal

        if not (pc_gcal.CLIENT_ID and pc_gcal.CLIENT_SECRET and pc_gcal.REFRESH_TOKEN):
            return None
        if start is not None:
            body = {"summary": title, "start": {"dateTime": start.astimezone().isoformat(timespec="seconds")},
                    "end": {"dateTime": (start + datetime.timedelta(minutes=minutes)).astimezone().isoformat(timespec="seconds")},
                    "reminders": {"useDefault": True}}
            when = f"am {WEEKDAYS[day.weekday()]}, den {day.day}.{day.month}., um {start:%H:%M} Uhr"
        else:
            body = {"summary": title, "start": {"date": f"{day:%Y-%m-%d}"},
                    "end": {"date": f"{day + datetime.timedelta(days=1):%Y-%m-%d}"}}
            when = f"am {WEEKDAYS[day.weekday()]}, den {day.day}.{day.month}., ganztägig"
        pc_gcal._api("POST", "/calendars/" + up.quote("primary", safe="") + "/events", body)
        reset_cache()
        return f"Eingetragen: {title} {when}."
    except Exception as e:
        print(f"Google-Kalender: direkt eintragen ging nicht ({e}), öffne den Browser.")
        return None


def handle(text: str):
    """Fragen zum Kalender und neue Termine. Gibt die Antwort oder None zurück."""
    import pc_talk

    low = pc_talk._norm(text)
    if re.search(r"\b(trag|trage|erstell|erstelle|leg|lege|mach|mache|füg|füge|setz|setze)\w*\b.*\b(termin|kalendereintrag)\b", low) \
            or re.match(r"^neuer termin\b", low):
        return create(text)
    asking = re.search(r"\btermin\w*\b|\bkalender\b|was (habe|hab) ich\b.*\b(heute|morgen|übermorgen|woche|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b|"
                       r"\bsteht\b.*\ban\b|was liegt\b.*\ban\b", low)
    if not asking or re.search(r"geburtstag", low):
        return None
    if not configured():
        if not re.search(r"\btermin\w*\b|\bkalender\b", low):
            return None  # z. B. "was steht an" kann das Gedächtnis beantworten
        return ("Ich kenne deinen Kalender noch nicht. Öffne in Google Kalender die Einstellungen deines Kalenders, kopiere die "
                "Privatadresse im iCal-Format und füge sie in meinen Einstellungen im Tab Infos ein.")
    try:
        now = datetime.datetime.now()
        if re.search(r"\bnächste\w*\s+termin\b|\bwann ist mein nächster\b", low):
            events = [e for e in events_between(now, now + datetime.timedelta(days=60)) if e["end"] > now]
            return ("Dein nächster Termin: " + _when(events[0], now.date()) + ".") if events else "In den nächsten 60 Tagen steht nichts an."
        delta, label = pc_talk._parse_day(low)
        if delta == "woche":
            begin, end = now.replace(hour=0, minute=0, second=0, microsecond=0), now + datetime.timedelta(days=7)
            label = "In den nächsten sieben Tagen"
        else:
            day = datetime.date.today() + datetime.timedelta(days=delta)
            begin = datetime.datetime.combine(day, datetime.time())
            end = begin + datetime.timedelta(days=1)
        events = [e for e in events_between(begin, end) if delta != 0 or e["end"] > now or e["allday"]]
        first = begin.date()
        if not [e for e in events if e["start"].date() >= first]:
            none = f"{label} hast du keine Termine" if delta != "woche" else "Diese Woche steht nichts Neues an"
            old = [e for e in events if e["start"].date() < first]
            return none + ("." if not old else ". Es läuft nur: " + _list(old, datetime.date.today(), first))
        return "Das steht an: " + _list(events, datetime.date.today(), first)
    except Exception as e:
        return f"Ich komme nicht an deinen Kalender: {e}"
