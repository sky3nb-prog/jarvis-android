// Vector OAuth2/OIDC-Login für fremde Websites ("Mit Vector anmelden") + Device/Code-Login für die Vector-App.
//
// Braucht den Firebase-Bezahltarif "Blaze" (Cloud Functions laufen nicht auf dem Gratis-Tarif "Spark").
// Deploy: in diesem Ordner `npm install`, dann im Projekt-Wurzelverzeichnis `firebase deploy --only functions,firestore:rules`.
// Region: europe-west3 (Frankfurt) - bewusst EU, wegen DSGVO.
//
// Feste Basis-URL nach dem Deploy (Projekt-ID "jarvis-konto", v1-Functions sind vorhersagbar):
//   https://europe-west3-jarvis-konto.cloudfunctions.net/api
//
// Endpunkte:
//   GET  /authorize              - zeigt die Login-Seite (E-Mail+Passwort), danach Weiterleitung zur Freundesseite
//   POST /token                  - tauscht einen Code (Browser-Login ODER Device/QR) gegen ein Access-Token
//   GET  /userinfo               - liefert Profil (nur: hat ein echtes Vector-Konto, E-Mail, Name, Bild)
//   POST /device_authorization   - startet den Code/QR-Login (für den Button auf der Freundesseite)
//   GET  /device                 - Bestätigungsseite im Browser/der App-WebView (Code eintippen oder per Link aus der App)
//   POST /device/decide          - die App ruft das auf, wenn der Nutzer "Ja"/"Nein" tippt

const { onRequest } = require("firebase-functions/v1").https;
const functionsV1 = require("firebase-functions/v1");
const admin = require("firebase-admin");
const express = require("express");
const crypto = require("crypto");

admin.initializeApp();
const db = admin.firestore();
const auth = admin.auth();

const REGION = "europe-west3";
const API_KEY = "AIzaSyDOrIuFUqWaDnKNMDFClCNnmpw8nZ31zm0"; // dieselbe öffentliche Web-API-Key wie auf der Website (konto_config.json)

const CODE_TTL_MS = 2 * 60 * 1000;          // Authorization Code: 2 Minuten gültig, nur einmal einlösbar
const TOKEN_TTL_MS = 60 * 60 * 1000;        // Access Token: 1 Stunde gültig
const DEVICE_TTL_MS = 10 * 60 * 1000;       // Device/User Code: 10 Minuten gültig
const DEVICE_POLL_INTERVAL = 4;             // Sekunden, die die Freundesseite zwischen zwei /token-Anfragen warten soll

function randomToken(bytes = 32) {
  return crypto.randomBytes(bytes).toString("base64url");
}
function randomUserCode() {
  // gut vorlesbar/eintippbar: keine 0/O, 1/I, keine Sonderzeichen außer dem Bindestrich
  const abc = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
  let s = "";
  for (let i = 0; i < 8; i++) s += abc[Math.floor(Math.random() * abc.length)];
  return s.slice(0, 4) + "-" + s.slice(4);
}

async function getClient(clientId) {
  if (!clientId) return null;
  const doc = await db.collection("oauth_clients").doc(clientId).get();
  return doc.exists ? { id: doc.id, ...doc.data() } : null;
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Gemeinsames Grundgerüst für die beiden Seiten, die wir ausliefern (Login + Geräte-Bestätigung).
// Bewusst sehr einfach gehalten (kein Build-Schritt nötig, läuft direkt aus der Cloud Function).
function page(title, bodyHtml) {
  return `<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>${escapeHtml(title)} – Vector</title>
<style>
  :root{color-scheme:dark light}
  body{font-family:system-ui,sans-serif;background:#07090b;color:#f1f1ef;max-width:380px;margin:12vh auto 0;padding:0 20px}
  h1{font-size:20px;margin:0 0 4px}
  p.sub{color:#9c9a92;font-size:14px;margin:0 0 24px}
  input{width:100%;box-sizing:border-box;padding:11px 12px;margin:0 0 10px;border-radius:8px;border:1px solid #333;background:#15171a;color:#f1f1ef;font-size:15px}
  button{width:100%;padding:11px;border-radius:8px;border:0;background:#1D9E75;color:#04342C;font-weight:600;font-size:15px;cursor:pointer}
  button:disabled{opacity:.5;cursor:default}
  .msg{min-height:20px;color:#E24B4A;font-size:13px;margin-top:10px}
  .ok{color:#5DCAA5}
  .app{color:#9c9a92;font-size:13px;margin-bottom:18px}
</style></head><body>${bodyHtml}</body></html>`;
}

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ---------- 1. Browser-Login (E-Mail + Passwort) ----------

app.get("/authorize", async (req, res) => {
  const { client_id, redirect_uri, state } = req.query;
  const client = await getClient(client_id);
  if (!client) return res.status(400).send(page("Fehler", `<h1>Unbekannte App</h1><p class="sub">Diese Seite ist nicht bei Vector registriert.</p>`));
  if (!client.redirect_uris || !client.redirect_uris.includes(redirect_uri)) {
    return res.status(400).send(page("Fehler", `<h1>Falsche Rücksprung-Adresse</h1><p class="sub">Diese redirect_uri ist für diese App nicht hinterlegt.</p>`));
  }
  const html = `
    <div class="app">Anmelden bei <b>${escapeHtml(client.name || client.id)}</b> mit deinem Vector-Konto</div>
    <h1>Anmelden</h1>
    <p class="sub">E-Mail und Passwort, wie am Handy/PC.</p>
    <input id="mail" type="email" placeholder="E-Mail" autocomplete="username">
    <input id="pw" type="password" placeholder="Passwort" autocomplete="current-password">
    <button id="go">Anmelden</button>
    <div class="msg" id="msg"></div>
    <script>
      const qs = ${JSON.stringify({ client_id, redirect_uri, state: state || "" })};
      document.getElementById("go").onclick = async () => {
        const mail = document.getElementById("mail").value.trim();
        const pw = document.getElementById("pw").value;
        const msg = document.getElementById("msg");
        if (!mail.includes("@") || pw.length < 6) { msg.textContent = "E-Mail oder Passwort fehlt."; return; }
        msg.textContent = "Melde an …"; msg.className = "msg";
        try {
          const r = await fetch("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${API_KEY}", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: mail, password: pw, returnSecureToken: true })
          });
          const d = await r.json();
          if (!r.ok) { msg.textContent = "E-Mail oder Passwort stimmt nicht."; return; }
          const c = await fetch("/authorize/complete", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ idToken: d.idToken, ...qs })
          });
          const cd = await c.json();
          if (!c.ok) { msg.textContent = cd.error || "Anmeldung fehlgeschlagen."; return; }
          location.href = cd.redirect;
        } catch (e) { msg.textContent = "Keine Verbindung."; }
      };
    </script>`;
  res.send(page("Anmelden", html));
});

app.post("/authorize/complete", async (req, res) => {
  const { idToken, client_id, redirect_uri, state } = req.body || {};
  const client = await getClient(client_id);
  if (!client || !client.redirect_uris || !client.redirect_uris.includes(redirect_uri)) {
    return res.status(400).json({ error: "Unbekannte App oder falsche Rücksprung-Adresse." });
  }
  let decoded;
  try { decoded = await auth.verifyIdToken(idToken); } catch (e) { return res.status(401).json({ error: "Anmeldung ungültig." }); }
  const code = randomToken(24);
  await db.collection("oauth_codes").doc(code).set({
    uid: decoded.uid, client_id, redirect_uri,
    created: Date.now(), expires: Date.now() + CODE_TTL_MS, used: false,
  });
  const url = new URL(redirect_uri);
  url.searchParams.set("code", code);
  if (state) url.searchParams.set("state", state);
  res.json({ redirect: url.toString() });
});

// ---------- 2. Token-Tausch (für beide Wege: Browser-Code UND Device/QR-Code) ----------

app.post("/token", async (req, res) => {
  const { grant_type, code, client_id, redirect_uri, device_code } = req.body || {};
  const client = await getClient(client_id);
  if (!client) return res.status(400).json({ error: "invalid_client" });

  if (grant_type === "authorization_code") {
    if (!code) return res.status(400).json({ error: "invalid_request" });
    const ref = db.collection("oauth_codes").doc(code);
    const snap = await ref.get();
    if (!snap.exists) return res.status(400).json({ error: "invalid_grant" });
    const data = snap.data();
    if (data.used || data.expires < Date.now() || data.client_id !== client_id || data.redirect_uri !== redirect_uri) {
      return res.status(400).json({ error: "invalid_grant" });
    }
    await ref.update({ used: true });
    return res.json(await issueToken(data.uid, client_id));
  }

  if (grant_type === "urn:ietf:params:oauth:grant-type:device_code") {
    if (!device_code) return res.status(400).json({ error: "invalid_request" });
    const ref = db.collection("device_codes").doc(device_code);
    const snap = await ref.get();
    if (!snap.exists) return res.status(400).json({ error: "expired_token" });
    const data = snap.data();
    if (data.expires < Date.now()) return res.status(400).json({ error: "expired_token" });
    if (data.status === "denied") return res.status(400).json({ error: "access_denied" });
    if (data.status === "pending") return res.status(400).json({ error: "authorization_pending" });
    if (data.status === "approved") {
      await ref.delete();
      return res.json(await issueToken(data.uid, client_id));
    }
    return res.status(400).json({ error: "invalid_grant" });
  }

  res.status(400).json({ error: "unsupported_grant_type" });
});

async function issueToken(uid, clientId) {
  const token = randomToken(32);
  await db.collection("oauth_tokens").doc(token).set({
    uid, client_id: clientId, created: Date.now(), expires: Date.now() + TOKEN_TTL_MS,
  });
  return { access_token: token, token_type: "Bearer", expires_in: Math.floor(TOKEN_TTL_MS / 1000) };
}

// ---------- 3. Profil abrufen ----------

app.get("/userinfo", async (req, res) => {
  const authz = req.headers.authorization || "";
  const token = authz.startsWith("Bearer ") ? authz.slice(7) : null;
  if (!token) return res.status(401).json({ error: "invalid_token" });
  const snap = await db.collection("oauth_tokens").doc(token).get();
  if (!snap.exists || snap.data().expires < Date.now()) return res.status(401).json({ error: "invalid_token" });
  const { uid } = snap.data();
  const userDoc = await db.collection("users").doc(uid).get();
  const f = userDoc.exists ? userDoc.data() : {};
  let email = null;
  try { email = (await auth.getUser(uid)).email; } catch (e) { /* ignore */ }
  res.json({
    sub: uid,
    email: email || undefined,
    name: f.name || undefined,
    picture: f.photo || undefined,
    vector_id: f.jid || undefined,
  });
});

// ---------- 4. Device/Code-Login (QR oder Code eintippen, bestätigt in der App) ----------

app.post("/device_authorization", async (req, res) => {
  const { client_id } = req.body || {};
  const client = await getClient(client_id);
  if (!client) return res.status(400).json({ error: "invalid_client" });
  const deviceCode = randomToken(32);
  const userCode = randomUserCode();
  await db.collection("device_codes").doc(deviceCode).set({
    user_code: userCode, client_id, status: "pending",
    created: Date.now(), expires: Date.now() + DEVICE_TTL_MS,
  });
  const verificationUri = `https://europe-west3-jarvis-konto.cloudfunctions.net/api/device`;
  res.json({
    device_code: deviceCode,
    user_code: userCode,
    verification_uri: verificationUri,
    verification_uri_complete: `${verificationUri}?code=${userCode}`,
    expires_in: Math.floor(DEVICE_TTL_MS / 1000),
    interval: DEVICE_POLL_INTERVAL,
  });
});

// Seite, die die App über einen QR-Link öffnet bzw. in der man den Code eintippen kann.
// Die eigentliche Bestätigung passiert über /device/decide, aufgerufen von der App (mit idToken).
app.get("/device", async (req, res) => {
  const presetCode = (req.query.code || "").toString().toUpperCase();
  const html = `
    <h1>Gerät verbinden</h1>
    <p class="sub">Öffne diese Seite in der Vector-App (oder scanne den QR-Code dort), um einen Login zu bestätigen.</p>
    <input id="code" placeholder="XXXX-XXXX" value="${escapeHtml(presetCode)}" style="text-transform:uppercase">
    <p class="sub">Dieser Schritt läuft normalerweise automatisch in der App ab, wenn du den QR-Code scannst oder den Code dort eingibst.</p>
  `;
  res.send(page("Gerät verbinden", html));
});

// Von der VECTOR-APP aufgerufen (dort ist der Nutzer schon eingeloggt): idToken + user_code + decision ("approve"/"deny").
app.post("/device/decide", async (req, res) => {
  const { idToken, user_code, decision } = req.body || {};
  let decoded;
  try { decoded = await auth.verifyIdToken(idToken); } catch (e) { return res.status(401).json({ error: "invalid_token" }); }
  const q = await db.collection("device_codes").where("user_code", "==", (user_code || "").toUpperCase()).limit(1).get();
  if (q.empty) return res.status(404).json({ error: "not_found" });
  const docRef = q.docs[0].ref;
  const data = q.docs[0].data();
  if (data.expires < Date.now()) return res.status(400).json({ error: "expired_token" });
  await docRef.update({
    status: decision === "approve" ? "approved" : "denied",
    uid: decision === "approve" ? decoded.uid : null,
  });
  res.json({ ok: true });
});

exports.api = functionsV1.region(REGION).https.onRequest(app);
