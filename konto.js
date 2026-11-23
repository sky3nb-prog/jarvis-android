(function () {
  const $ = (id) => document.getElementById(id);
  let C = null;
  const S = { get: () => { try { return JSON.parse(localStorage.getItem("jk") || "null"); } catch (e) { return null; } },
              set: (v) => { try { v ? localStorage.setItem("jk", JSON.stringify(v)) : localStorage.removeItem("jk"); } catch (e) {} } };
  const err = (m) => {
    m = m || "";
    if (m.startsWith("EMAIL_EXISTS")) return "Die E-Mail hat schon ein Konto – nimm „Anmelden“.";
    if (/^(EMAIL_NOT_FOUND|INVALID_LOGIN_CREDENTIALS|INVALID_PASSWORD)/.test(m)) return "E-Mail oder Passwort stimmt nicht.";
    if (m.startsWith("WEAK_PASSWORD")) return "Passwort zu kurz – mindestens 6 Zeichen.";
    if (m.startsWith("INVALID_EMAIL")) return "Das ist keine gültige E-Mail.";
    if (m.startsWith("TOO_MANY_ATTEMPTS")) return "Zu viele Versuche – kurz warten.";
    if (m.startsWith("OPERATION_NOT_ALLOWED")) return "Anmeldung mit E-Mail ist noch nicht eingeschaltet.";
    if (/PERMISSION_DENIED/i.test(m)) return "Zugriff verweigert (Regeln).";
    return m;
  };
  const msg = (id, t, ok) => { $(id).textContent = t || ""; $(id).classList.toggle("ok", !!ok); };
  async function j(url, body, token, method) {
    const h = { "Content-Type": "application/json" }; if (token) h.Authorization = "Bearer " + token;
    const r = await fetch(url, { method: method || (body ? "POST" : "GET"), headers: h, body: body ? JSON.stringify(body) : undefined });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(err((d.error || {}).message || ("HTTP " + r.status))); e.code = r.status; throw e; }
    return d;
  }
  async function token() {
    const s = S.get(); if (!s) throw new Error("Nicht angemeldet.");
    if (Date.now() < s.exp) return s.id;
    const r = await fetch("https://securetoken.googleapis.com/v1/token?key=" + C.apiKey, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "grant_type=refresh_token&refresh_token=" + encodeURIComponent(s.refresh) });
    const d = await r.json(); if (!r.ok) { S.set(null); throw new Error("Anmeldung abgelaufen."); }
    s.id = d.id_token; s.refresh = d.refresh_token; s.exp = Date.now() + (+d.expires_in - 60) * 1000; S.set(s); return s.id;
  }
  const docUrl = (uid) => `https://firestore.googleapis.com/v1/projects/${C.projectId}/databases/(default)/documents/users/${uid}`;
  const when = (t) => t ? new Date(+t).toLocaleString("de-DE", { weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }) : null;
  // Firestore REST: PATCH mit updateMask setzt genau die Felder, die man mitschickt (fehlende Felder im updateMask würden gelöscht -
  // darum immer alle Felder mitgeben, die man kennt, auch wenn sie sich nicht geändert haben).
  async function patchDoc(uid, fields) {
    const mask = Object.keys(fields).map((k) => "updateMask.fieldPaths=" + encodeURIComponent(k)).join("&");
    const body = { fields: {} };
    for (const k in fields) body.fields[k] = { stringValue: String(fields[k] == null ? "" : fields[k]) };
    return j(docUrl(uid) + "?" + mask, body, await token(), "PATCH");
  }
  function newJid() {   // kurzer, gut vorlesbarer Code ohne verwechselbare Zeichen (0/O, 1/I)
    const abc = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
    let s = "";
    for (let i = 0; i < 8; i++) s += abc[Math.floor(Math.random() * abc.length)];
    return s.slice(0, 4) + "-" + s.slice(4);
  }
  let curFields = {};   // zuletzt vom Server gelesene Profil-Felder (für den Vergleich beim Speichern)
  let stagedPhoto = null;   // neu gewähltes, noch nicht gespeichertes Profilbild (Data-URL)
  async function show() {
    const s = S.get();
    $("c-login").hidden = !!s; $("c-acc").hidden = !s;
    if (!s) return;
    $("acc-mail").textContent = s.email;
    $("acc-mail2").value = s.email;
    $("st-and").textContent = $("st-pc").textContent = $("st-link").textContent = "…";
    $("acc-id").textContent = "Vector-ID: …";
    try {
      let f = {};
      try { f = (await j(docUrl(s.uid), null, await token())).fields || {}; } catch (e) { if (e.code !== 404) throw e; }
      const t = (k) => f[k] && f[k].integerValue;
      const sv = (k) => (f[k] && f[k].stringValue) || "";
      $("st-and").textContent = when(t("android_t")) ? "zuletzt " + when(t("android_t")) : "noch nicht angemeldet";
      $("st-pc").textContent = when(t("pc_t")) ? "zuletzt " + when(t("pc_t")) : "noch nicht angemeldet";
      $("st-link").textContent = f.link ? "PC und Handy finden sich automatisch" : "kommt, sobald sich der PC anmeldet";
      curFields = { name: sv("name"), photo: sv("photo"), jid: sv("jid") };
      $("acc-name").value = curFields.name;
      paintAvatar(curFields.photo, curFields.name || s.email);
      if (curFields.jid) {
        $("acc-id").textContent = "Vector-ID: " + curFields.jid;
      } else {   // einmalig anlegen, danach bleibt sie fest
        curFields.jid = newJid();
        $("acc-id").textContent = "Vector-ID: " + curFields.jid;
        patchDoc(s.uid, { jid: curFields.jid }).catch(() => {});
      }
      msg("msg2", "");
    } catch (e) { msg("msg2", e.message); }
  }
  function paintAvatar(photo, nameOrMail) {
    $("acc-photo").src = photo || "";
    $("acc-initial").textContent = photo ? "" : (nameOrMail || "?").trim().charAt(0).toUpperCase();
  }
  async function login(neu) {
    if (!C) return msg("msg", "Die Seite ist noch nicht fertig eingerichtet.");
    const email = $("mail").value.trim(), pw = $("pw").value;
    if (!email.includes("@")) return msg("msg", "Bitte deine E-Mail eintragen.");
    if (pw.length < 6) return msg("msg", "Passwort: mindestens 6 Zeichen.");
    msg("msg", neu ? "Lege dein Konto an …" : "Melde an …", true);
    try {
      const d = await j(`https://identitytoolkit.googleapis.com/v1/accounts:${neu ? "signUp" : "signInWithPassword"}?key=${C.apiKey}`, { email, password: pw, returnSecureToken: true });
      S.set({ email, uid: d.localId, id: d.idToken, refresh: d.refreshToken, exp: Date.now() + (+d.expiresIn - 60) * 1000 });
      $("pw").value = ""; msg("msg", "");
      await show();
      if (neu) msg("msg2", "Konto angelegt. Jetzt App bzw. PC-Programm herunterladen und dort mit derselben E-Mail anmelden.", true);
    } catch (e) { msg("msg", e.message); }
  }
  $("b-reset").onclick = async (e) => {
    e.preventDefault();
    if (!C) return msg("msg", "Die Seite ist noch nicht fertig eingerichtet.");
    const email = $("mail").value.trim();
    if (!email.includes("@")) return msg("msg", "Trag oben deine E-Mail ein und klick dann nochmal auf „Passwort vergessen?“.");
    msg("msg", "Schicke dir eine Mail …", true);
    try {
      await j("https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key=" + C.apiKey, { requestType: "PASSWORD_RESET", email });
      msg("msg", "Mail ist unterwegs – schau auch im Spam-Ordner. Wichtig: Alte Sicherungen waren mit dem alten Passwort verschlüsselt. Nach dem Zurücksetzen lädt das erste Gerät, auf dem du dich neu anmeldest, seinen Stand neu hoch.", true);
    } catch (err) { msg("msg", err.message); }
  };
  $("b-in").onclick = () => login(false);
  $("b-neu").onclick = () => login(true);
  $("pw").addEventListener("keydown", (e) => { if (e.key === "Enter") login(false); });
  $("b-out").onclick = () => { S.set(null); show(); };
  $("b-pwr").onclick = async () => {
    const s = S.get(); if (!s || !C) return;
    msg("msg2", "Schicke dir eine Mail …", true);
    try { await j("https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key=" + C.apiKey, { requestType: "PASSWORD_RESET", email: s.email });
      msg("msg2", "Mail an " + s.email + " ist unterwegs (auch im Spam schauen). Danach auf deinen Geräten mit dem neuen Passwort anmelden.", true);
    } catch (e) { msg("msg2", e.message); }
  };
  $("avatar-pick").addEventListener("click", (e) => {
    if (e.target && e.target.id === "photo-file") return;   // Klick aufs Input selbst nicht doppelt behandeln
    $("photo-file").click();
  });
  $("photo-file").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    msg("msg2", "Verarbeite Bild …", true);
    const img = new Image();
    const reader = new FileReader();
    reader.onload = () => { img.onload = () => {
      const size = 160;   // klein genug, um bequem als Base64-String im Firestore-Dokument zu liegen
      const c = document.createElement("canvas"); c.width = size; c.height = size;
      const ctx = c.getContext("2d");
      const side = Math.min(img.width, img.height);
      ctx.drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, size, size);
      stagedPhoto = c.toDataURL("image/jpeg", 0.72);
      paintAvatar(stagedPhoto, $("acc-name").value);
      msg("msg2", "Bild gewählt – nicht vergessen, unten auf „Speichern“ zu klicken.", true);
    }; img.onerror = () => msg("msg2", "Das Bild konnte nicht gelesen werden."); img.src = reader.result; };
    reader.onerror = () => msg("msg2", "Das Bild konnte nicht gelesen werden.");
    reader.readAsDataURL(file);
  });
  $("b-save").onclick = async () => {
    const s = S.get(); if (!s || !C) return;
    const name = $("acc-name").value.trim();
    const newMail = $("acc-mail2").value.trim();
    msg("msg2", "Speichere …", true);
    try {
      if (newMail && newMail !== s.email) {
        if (!newMail.includes("@")) { msg("msg2", "Das ist keine gültige E-Mail."); return; }
        const t = await token();
        const d = await j("https://identitytoolkit.googleapis.com/v1/accounts:update?key=" + C.apiKey, { idToken: t, email: newMail, returnSecureToken: true });
        s.email = newMail; s.id = d.idToken; s.refresh = d.refreshToken; s.exp = Date.now() + (+d.expiresIn - 60) * 1000;
        S.set(s);
        $("acc-mail").textContent = newMail;
      }
      await patchDoc(s.uid, { name, photo: stagedPhoto != null ? stagedPhoto : curFields.photo, jid: curFields.jid });
      curFields.name = name; if (stagedPhoto != null) curFields.photo = stagedPhoto; stagedPhoto = null;
      msg("msg2", "Gespeichert.", true);
    } catch (e) { msg("msg2", e.message); }
  };
  $("b-del").onclick = () => { $("del-ask").hidden = !$("del-ask").hidden; };
  $("b-del-ok").onclick = async () => {
    const s = S.get(); if (!s) return;
    try {
      const t = await token();
      await fetch(docUrl(s.uid), { method: "DELETE", headers: { Authorization: "Bearer " + t } });
      await j("https://identitytoolkit.googleapis.com/v1/accounts:delete?key=" + C.apiKey, { idToken: t });
      S.set(null); show(); msg("msg", "Konto und Daten sind gelöscht.", true);
    } catch (e) { msg("msg2", e.message); }
  };
  fetch("konto_config.json", { cache: "no-store" }).then((r) => r.json()).then((c) => { if (c.apiKey) C = c; else msg("msg", "Die Seite ist noch nicht fertig eingerichtet."); show(); })
    .catch(() => { msg("msg", "Die Seite ist noch nicht fertig eingerichtet."); show(); });
})();
