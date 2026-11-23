(function () {
  // Mit-Vector-anmelden ohne Cloud Functions/Blaze: läuft komplett statisch über GitHub Pages.
  // Validiert client_id + redirect_uri gegen diese fest hinterlegte Liste, loggt per Firebase-REST-API
  // ein und schickt den Nutzer mit id_token (+ state) zurück zur Seite des Freundes.
  // Der Freund prüft id_token danach selbst gegen die "accounts:lookup"-REST-API (siehe sein vector_callback.php).
  //
  // Wichtig: Das ist bewusst nur der Passwort-Weg. Der QR-/Code-Login braucht das Cloud-Functions-Backend
  // (Ordner functions/) und damit den Firebase-Tarif "Blaze" - kommt erst, sobald der aktiv ist.
  const CLIENTS = {
    kittysquiz: {
      name: "KittysRätsel",
      redirect_uris: [
        "https://kittysquiz.app/index.php",
        "https://kittysquiz.app/vector_callback.php",
        "https://kittysquiz.app/profile/vector_link.php",
      ],
    },
  };

  const API_KEY = "AIzaSyDOrIuFUqWaDnKNMDFClCNnmpw8nZ31zm0"; // dieselbe öffentliche Web-API-Key wie in konto_config.json

  const $ = (id) => document.getElementById(id);
  const msg = (t, ok) => { $("msg").textContent = t || ""; $("msg").classList.toggle("ok", !!ok); };

  const qs = new URLSearchParams(location.search);
  const clientId = qs.get("client_id") || "";
  const redirectUri = qs.get("redirect_uri") || "";
  const state = qs.get("state") || "";

  const client = CLIENTS[clientId];
  const validRedirect = !!client && Array.isArray(client.redirect_uris) && client.redirect_uris.includes(redirectUri);

  if (!client) {
    $("app-name").textContent = "Fehler";
    $("app-desc").textContent = "Unbekannte client_id – diese App ist bei Vector nicht hinterlegt.";
  } else if (!validRedirect) {
    $("app-name").textContent = "Fehler";
    $("app-desc").textContent = "Falsche redirect_uri – für " + client.name + " nicht hinterlegt.";
  } else {
    $("app-name").textContent = "Anmelden bei " + client.name;
    $("app-desc").textContent = "E-Mail und Passwort, wie am Handy/PC.";
    $("login-form").hidden = false;

    async function login() {
      const email = $("mail").value.trim();
      const pw = $("pw").value;
      if (!email.includes("@")) return msg("Bitte deine E-Mail eintragen.");
      if (pw.length < 6) return msg("Passwort: mindestens 6 Zeichen.");
      msg("Melde an …", true);
      try {
        const r = await fetch("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + API_KEY, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password: pw, returnSecureToken: true }),
        });
        const d = await r.json();
        if (!r.ok) {
          const code = (d.error || {}).message || "";
          if (/^(EMAIL_NOT_FOUND|INVALID_LOGIN_CREDENTIALS|INVALID_PASSWORD)/.test(code)) return msg("E-Mail oder Passwort stimmt nicht.");
          if (/^TOO_MANY_ATTEMPTS/.test(code)) return msg("Zu viele Versuche – kurz warten.");
          return msg("Anmeldung fehlgeschlagen.");
        }
        const url = new URL(redirectUri);
        url.searchParams.set("id_token", d.idToken);
        if (state) url.searchParams.set("state", state);
        location.href = url.toString();
      } catch (e) {
        msg("Keine Verbindung.");
      }
    }
    $("b-in").onclick = login;
    $("pw").addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });
  }
})();
