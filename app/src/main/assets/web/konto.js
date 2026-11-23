// Jarvis-Konto in deiner normalen App: einmal verbinden (Anmelden oder neues Konto), danach sichert er still.
// Kein Abmelden, kein eigener Bereich. „Später“ = fragt beim nächsten Öffnen noch einmal.
(function () {
  const A = window.Android;
  if (!A || !A.kontoInfo) return;
  let i = {}; try { i = JSON.parse(A.kontoInfo()); } catch (e) {}
  if (!i.configured || i.loggedIn) return;
  const $ = (id) => document.getElementById(id);
  const css = document.createElement("style");
  css.textContent = `
  #konto-ov{position:fixed;inset:0;z-index:9000;background:radial-gradient(120% 80% at 50% 0%,#2a1c06 0%,#05080b 60%);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:28px 22px;color:#f3e6c8}
  #konto-ov .ko-orb{width:84px;height:84px;border-radius:50%;background:radial-gradient(circle at 50% 45%,#fff6d8 0%,#ffcf6a 30%,#d68a10 60%,rgba(120,60,0,0) 72%);box-shadow:0 0 60px rgba(255,180,60,.55);margin-bottom:16px}
  #konto-ov h1{margin:0;font-size:20px;letter-spacing:4px;color:#ffd678}
  #konto-ov p{margin:8px 0 18px;color:#b9a77f;font-size:14px;text-align:center;line-height:1.45;max-width:330px}
  #konto-ov .ko-box{width:100%;max-width:340px;display:flex;flex-direction:column;gap:10px}
  #konto-ov input{width:100%;box-sizing:border-box;padding:14px;border-radius:14px;border:1px solid #5a4318;background:#0d1217;color:#f3e6c8;font-size:16px}
  #konto-ov .ko-btn{padding:14px;border-radius:14px;border:1px solid #ffb43c;background:linear-gradient(#3a2608,#1d1405);color:#ffd678;font-weight:700;font-size:16px;text-align:center}
  #konto-ov .ko-btn.alt{border-color:#3a4a55;background:#0d1217;color:#cfd8dd;font-weight:600}
  #konto-ov .ko-msg{min-height:20px;font-size:13px;color:#ff9a8a;text-align:center}
  #konto-ov .ko-msg.ok{color:#6effcd}
  #konto-ov .ko-skip{margin-top:16px;color:#7f8b92;font-size:13px;text-decoration:underline}
  #konto-ov.busy .ko-btn{opacity:.5;pointer-events:none}`;
  document.head.appendChild(css);
  const ov = document.createElement("div");
  ov.id = "konto-ov";
  ov.innerHTML = `<div class="ko-orb"></div><h1>VECTOR-KONTO</h1>
    <p>Einmal verbinden: Dann ist dein Vector in deinem Konto gesichert. Hier musst du dich danach nie wieder anmelden.</p>
    <div class="ko-box"><input id="ko-mail" type="email" placeholder="E-Mail" autocapitalize="none"><input id="ko-pw" type="password" placeholder="Passwort (mind. 6 Zeichen)">
    <div class="ko-msg" id="ko-msg"></div><div class="ko-btn" id="ko-in">Anmelden</div><div class="ko-btn alt" id="ko-neu">Neues Konto anlegen</div></div>
    <div class="ko-skip" id="ko-forgot">Passwort vergessen?</div>
    <div class="ko-skip" id="ko-skip" style="margin-top:8px">Später</div>`;
  const msg = (t, ok) => { $("ko-msg").textContent = t || ""; $("ko-msg").classList.toggle("ok", !!ok); };
  function go(neu) {
    const m = $("ko-mail").value.trim(), p = $("ko-pw").value;
    if (!m.includes("@")) return msg("Bitte deine E-Mail eintragen.");
    if (p.length < 6) return msg("Passwort: mindestens 6 Zeichen.");
    ov.classList.add("busy"); msg(neu ? "Lege dein Konto an …" : "Verbinde …", true);
    A.kontoLogin(m, p, !!neu);
  }
  const prev = window.jarvis && window.jarvis.onEvent;
  if (window.jarvis) window.jarvis.onEvent = function (type, data) {
    if (type === "konto") {
      const d = typeof data === "string" ? JSON.parse(data) : (data || {});
      ov.classList.remove("busy"); msg(d.text, d.ok);
      if (d.ok && !d.reset) { $("ko-pw").value = ""; setTimeout(() => ov.remove(), 2500); }
      return;
    }
    return prev && prev.call(window.jarvis, type, data);
  };
  setTimeout(() => {
    document.body.appendChild(ov);
    $("ko-in").onclick = () => go(false); $("ko-neu").onclick = () => go(true);
    $("ko-skip").onclick = () => ov.remove();
    $("ko-forgot").onclick = () => {
      const m = $("ko-mail").value.trim();
      if (!m.includes("@")) return msg("Trag oben deine E-Mail ein, dann tipp nochmal auf „Passwort vergessen?“.");
      if (!A.kontoReset) return msg("Geht in dieser Version noch nicht.");
      ov.classList.add("busy"); msg("Schicke dir eine Mail …", true); A.kontoReset(m);
    };
  }, 1500);
})();
