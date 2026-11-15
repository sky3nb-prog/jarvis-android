"""
Jarvis-Konto (Test): Anmelden mit E-Mail und Passwort (Firebase). Danach liegen die PC-Einstellungen, das Gedächtnis
und der Kopplungscode im Konto. Auf einem neuen PC: Jarvis Konto starten, anmelden – alles ist da.
Die Handy-App „Jarvis Konto“ holt sich den Kopplungscode aus dem Konto und ist damit sofort mit diesem PC gekoppelt.

Alles wird VOR dem Hochladen mit deinem Passwort verschlüsselt (gleiches Verfahren wie die Handy-Kopplung,
Schlüssel per PBKDF2 aus Passwort + E-Mail). Der Server sieht nur Kauderwelsch. Passwort vergessen = Daten weg.
Firebase-Zugang: pc_web/konto_config.json (apiKey und projectId sind bei Firebase öffentlich gedacht; geschützt wird
über die Firestore-Regeln: jeder darf nur sein eigenes Dokument users/<uid>).
"""
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from pc_apps import base_dir

FILE = "konto.json"
SKIP = {FILE, "jarvis_log.txt"}
_lock = threading.Lock()
STATUS = {"err": ""}


def _res(*p):
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, *p)


def cfg() -> dict:
    for p in (os.path.join(base_dir(), "konto_config.json"), _res("pc_web", "konto_config.json")):
        try:
            with open(p, encoding="utf-8") as f:
                c = json.load(f)
            if c.get("apiKey"):
                return c
        except Exception:
            pass
    return {}


def configured() -> bool:
    c = cfg()
    return bool(c.get("apiKey") and c.get("projectId"))


def _st() -> dict:
    try:
        with open(os.path.join(base_dir(), FILE), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(st: dict):
    with open(os.path.join(base_dir(), FILE), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def _prot(t: str) -> str:
    try:
        import pc_secret
        return pc_secret.protect(t)
    except Exception:
        return t


def _unprot(t: str) -> str:
    try:
        import pc_secret
        return pc_secret.unprotect(t) or ""
    except Exception:
        return t


def logged_in() -> bool:
    st = _st()
    return bool(st.get("uid") and st.get("secret"))


def info() -> dict:
    st = _st()
    return {"configured": configured(), "loggedIn": logged_in(), "email": st.get("email", ""),
            "lastPush": st.get("last_push", 0), "lastPull": st.get("last_pull", 0), "err": STATUS.get("err", "")}


def _secret(email: str, pw: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), ("jarvis-konto:" + email.strip().lower()).encode("utf-8"), 60000).hex()


def _fb_error(m: str) -> str:
    m = m or ""
    if m.startswith("EMAIL_EXISTS"):
        return "Die E-Mail hat schon ein Konto – nimm „Anmelden“."
    if m.startswith(("EMAIL_NOT_FOUND", "INVALID_LOGIN_CREDENTIALS", "INVALID_PASSWORD")):
        return "E-Mail oder Passwort stimmt nicht."
    if m.startswith("WEAK_PASSWORD"):
        return "Passwort zu kurz – mindestens 6 Zeichen."
    if m.startswith("INVALID_EMAIL"):
        return "Das ist keine gültige E-Mail."
    if m.startswith("OPERATION_NOT_ALLOWED"):
        return "In Firebase ist E-Mail/Passwort noch nicht eingeschaltet."
    if "PERMISSION_DENIED" in m or "permission" in m.lower():
        return "Firebase-Regeln fehlen noch (Firestore → Regeln)."
    return m


def _http(url: str, body=None, method: str = None, token: str = None, form: bool = False):
    data = None
    h = {}
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=h, method=method or ("POST" if data is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            j = {}
        return e.code, j


def _token() -> str:
    st = _st()
    if time.time() < st.get("exp", 0):
        return _unprot(st.get("id", ""))
    code, j = _http(f"https://securetoken.googleapis.com/v1/token?key={cfg()['apiKey']}",
                    {"grant_type": "refresh_token", "refresh_token": _unprot(st.get("refresh", ""))}, form=True)
    if code != 200:
        raise RuntimeError("Anmeldung abgelaufen – bitte neu anmelden.")
    st.update(id=_prot(j["id_token"]), refresh=_prot(j["refresh_token"]), exp=time.time() + int(j.get("expires_in", 3600)) - 60)
    _save(st)
    return j["id_token"]


def _doc_url() -> str:
    return f"https://firestore.googleapis.com/v1/projects/{cfg()['projectId']}/databases/(default)/documents/users/{_st().get('uid', '')}"


def _get_doc():
    code, j = _http(_doc_url(), token=_token())
    if code == 404:
        return None
    if code != 200:
        raise RuntimeError(_fb_error((j.get("error") or {}).get("message", f"HTTP {code}")))
    out = {}
    for k, v in (j.get("fields") or {}).items():
        out[k] = int(v["integerValue"]) if "integerValue" in v else v.get("stringValue", "")
    return out


def _patch(fields: dict):
    f = {k: ({"integerValue": str(v)} if isinstance(v, int) else {"stringValue": str(v)}) for k, v in fields.items()}
    mask = "&".join("updateMask.fieldPaths=" + k for k in fields)
    code, j = _http(_doc_url() + "?" + mask, {"fields": f}, method="PATCH", token=_token())
    if code != 200:
        raise RuntimeError(_fb_error((j.get("error") or {}).get("message", f"HTTP {code}")))


def _secret_now() -> str:
    return _unprot(_st().get("secret", ""))


# --- was ins Konto kommt: alle Jarvis-Dateien (.json) im Programmordner -------------------------------------------
def _snapshot() -> dict:
    files = {}
    d = base_dir()
    for n in sorted(os.listdir(d)):
        p = os.path.join(d, n)
        if n in SKIP or not n.endswith(".json") or not os.path.isfile(p) or os.path.getsize(p) > 600_000:
            continue
        try:
            with open(p, encoding="utf-8") as f:
                files[n] = f.read()
        except Exception:
            pass
    return {"v": 1, "files": files, "pc": os.environ.get("COMPUTERNAME", "")}


def _hash(snap: dict) -> str:
    return hashlib.sha256(json.dumps(snap.get("files", {}), sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _apply(o: dict):
    d = base_dir()
    for n, txt in (o.get("files") or {}).items():
        if "/" in n or "\\" in n or n in SKIP or not n.endswith(".json"):
            continue
        with open(os.path.join(d, n), "w", encoding="utf-8") as f:
            f.write(txt)


def push(force: bool = False) -> bool:
    if not logged_in():
        return False
    import pc_link
    with _lock:
        snap = _snapshot()
        h = _hash(snap)
        st = _st()
        if not force and h == st.get("hash"):
            return False
        now = int(time.time() * 1000)
        sec = _secret_now()
        fields = {"pc": pc_link.encrypt(snap, sec), "pc_t": now}
        try:
            c = pc_link.code()
            if c:
                fields.update(link=pc_link.encrypt({"code": c}, sec), link_t=now)
        except Exception:
            pass
        _patch(fields)
        st = _st()
        st.update(hash=h, last_push=now, remote_t=now)
        _save(st)
        STATUS["err"] = ""
        return True


def pull(force: bool = False, doc=None) -> bool:
    """Neueren Stand aus dem Konto holen. True = Dateien wurden ersetzt (Jarvis sollte neu starten)."""
    if not logged_in():
        return False
    import pc_link
    doc = doc if doc is not None else _get_doc()
    if not doc or not doc.get("pc"):
        return False
    st = _st()
    t = int(doc.get("pc_t") or 0)
    if not force and t <= st.get("remote_t", 0):
        return False
    o = pc_link.decrypt(doc["pc"], _secret_now())
    if not o:
        raise RuntimeError("Die Daten im Konto ließen sich nicht entschlüsseln (anderes Passwort?).")
    with _lock:
        _apply(o)
        st = _st()
        st.update(remote_t=t, last_pull=int(time.time() * 1000), hash=_hash(_snapshot()))
        _save(st)
    return True


def login(email: str, pw: str, neu: bool) -> dict:
    """Anmelden (neu = Konto anlegen). restart=True heißt: Daten aus dem Konto geladen, Jarvis startet neu."""
    if not configured():
        return {"ok": False, "text": "Das Konto ist noch nicht eingerichtet (Firebase fehlt)."}
    email = (email or "").strip()
    ep = "signUp" if neu else "signInWithPassword"
    code, j = _http(f"https://identitytoolkit.googleapis.com/v1/accounts:{ep}?key={cfg()['apiKey']}",
                    {"email": email, "password": pw, "returnSecureToken": True})
    if code != 200:
        return {"ok": False, "text": _fb_error((j.get("error") or {}).get("message", f"HTTP {code}"))}
    _save({"email": email, "uid": j.get("localId", ""), "id": _prot(j.get("idToken", "")), "refresh": _prot(j.get("refreshToken", "")),
           "exp": time.time() + int(j.get("expiresIn", 3600)) - 60, "secret": _prot(_secret(email, pw))})
    try:
        doc = _get_doc()
        if doc and doc.get("pc"):
            pull(force=True, doc=doc)
            return {"ok": True, "restart": True, "text": "Angemeldet – deine Sachen sind geladen. Jarvis startet neu."}
        push(force=True)
        return {"ok": True, "text": "Konto angelegt – dieser PC ist jetzt im Konto." if neu else "Angemeldet – dieser PC ist jetzt im Konto."}
    except Exception as e:
        STATUS["err"] = str(e)
        return {"ok": False, "text": str(e)}


def logout():
    try:
        os.remove(os.path.join(base_dir(), FILE))
    except Exception:
        pass


def sync_now() -> dict:
    try:
        a = pull()
        b = push(force=True)
        return {"ok": True, "restart": a, "text": ("Neuen Stand geholt – Jarvis startet neu. " if a else "") + ("Hochgeladen." if b else "Alles aktuell.")}
    except Exception as e:
        STATUS["err"] = str(e)
        return {"ok": False, "text": str(e)}


def pull_at_start():
    """Beim Start (vor dem Laden der Einstellungen): neueren Stand aus dem Konto holen – höchstens ein paar Sekunden."""
    if not logged_in() or not configured():
        return
    done = threading.Event()

    def go():
        try:
            if pull():
                print("Konto: neuer Stand geladen.")
        except Exception as e:
            STATUS["err"] = str(e)
            print("Konto:", e)
        done.set()
    threading.Thread(target=go, daemon=True).start()
    done.wait(8)


def start_loop():
    """Alle 5 Minuten: eigene Änderungen hochladen."""
    def loop():
        time.sleep(60)
        while True:
            try:
                if push():
                    print("Konto: hochgeladen.")
            except Exception as e:
                STATUS["err"] = str(e)
                print("Konto:", e)
            time.sleep(300)
    threading.Thread(target=loop, daemon=True).start()


def restart_self():
    """Jarvis neu starten (nach dem Laden aus dem Konto)."""
    import subprocess
    try:
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable, "--restart"], close_fds=True, creationflags=0x00000008)
        else:
            subprocess.Popen([sys.executable] + sys.argv + ["--restart"], close_fds=True)
    except Exception as e:
        print("Neustart ging nicht:", e)
    os._exit(0)
