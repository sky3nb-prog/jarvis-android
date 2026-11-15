// Jarvis-Konto am Haupt-PC: einmal verbinden (Anmelden oder neues Konto), danach sichert er still im Hintergrund.
// Kein Abmelden, kein eigener Bereich. „Später“ = fragt beim nächsten Start noch einmal.
(function () {
  if (!window.PC) return;
  const i = window.PC.get("konto") || {};
  if (!i.configured || i.loggedIn) return;
  const $ = (id) => document.getElementById(id);
  const css = document.createElement("style");
  css.textContent = `
  #konto-ov{position:fixed;inset:0;z-index:9000;background:rgba(2,5,8,.82);backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;color:#f3e6c8}
  #konto-ov .ko-card{width:430px;max-width:92vw;padding:30px 30px 22px;border-radius:24px;border:1px solid rgba(255,180,60,.45);background:radial-gradient(120% 90% at 50% 0%,#2a1c06 0%,#070b0f 65%);display:flex;flex-direction:column;align-items:center}
  #konto-ov .ko-orb{width:72px;height:72px;border-radius:50%;background:radial-gradient(circle at 50% 45%,#fff6d8 0%,#ffcf6a 30%,#d68a10 60%,rgba(120,60,0,0) 72%);box-shadow:0 0 50px rgba(255,180,60,.5);margin-bottom:14px}
  #konto-ov h1{margin:0;font-size:19px;letter-spacing:4px;color:#ffd678}
  #konto-ov p{margin:8px 0 18px;color:#b9a77f;font-size:13.5px;text-align:center;line-height:1.45}
  #konto-ov input{width:100%;box-sizing:border-box;padding:12px 14px;border-radius:12px;border:1px solid #5a4318;background:#0d1217;color:#f3e6c8;font-size:15px;margin-bottom:10px}
  #konto-ov .ko-row{display:flex;gap:10px;width:100%}
  #konto-ov button{flex:1;padding:12px;border-radius:12px;border:1px solid #ffb43c;background:linear-gradient(#3a2608,#1d1405);color:#ffd678;font-weight:700;font-size:14px;cursor:pointer}
  #konto-ov button.alt{border-color:#3a4a55;background:#0d1217;color:#cfd8dd;font-weight:600}
  #konto-ov .ko-msg{min-height:20px;font-size:13px;color:#ff9a8a;text-align:center;margin:2px 0 8px}
  #konto-ov .ko-msg.ok{color:#6effcd}
  #konto-ov .ko-skip{margin-top:14px;color:#7f8b92;font-size:12.5px;text-decoration:underline;cursor:pointer}
  #konto-ov.busy button{opacity:.5;pointer-events:none}`;
  document.head.appendChild(css);
  const ov = document.createElement("div");
  ov.id = "konto-ov";
  ov.innerHTML = `<div class="ko-card"><div class="ko-orb"></div><h1>JARVIS-KONTO</h1>
    <p>Einmal verbinden: Dann ist dein Jarvis in deinem Konto gesichert und du kannst ihn auf jedem anderen PC mit deinem Konto laden. Hier musst du dich danach nie wieder anmelden.</p>
    <input id="ko-mail" type="email" placeholder="E-Mail"><input id="ko-pw" type="password" placeholder="Passwort (mind. 6 Zeichen)">
    <div class="ko-msg" id="ko-msg"></div><div class="ko-row"><button id="ko-in">Anmelden</button><button class="alt" id="ko-neu">Neues Konto</button></div>
    <div class="ko-skip" id="ko-skip">Später</div></div>`;
  const msg = (t, ok) => { $("ko-msg").textContent = t || ""; $("ko-msg").classList.toggle("ok", !!ok); };
  async function go(neu) {
    const m = $("ko-mail").value.trim(), p = $("ko-pw").value;
    if (!m.includes("@")) return msg("Bitte deine E-Mail eintragen.");
    if (p.length < 6) return msg("Passwort: mindestens 6 Zeichen.");
    ov.classList.add("busy"); msg(neu ? "Lege dein Konto an …" : "Verbinde …", true);
    let r = {}; try { const x = await window.PC.post("konto_login", { email: m, pw: p, neu: !!neu }); r = x ? await x.json() : {}; } catch (e) {}
    ov.classList.remove("busy"); msg(r.text || "Keine Antwort.", r.ok);
    if (r.ok) { $("ko-pw").value = ""; setTimeout(() => ov.remove(), 2200); }
  }
  setTimeout(() => {
    document.body.appendChild(ov);
    $("ko-in").onclick = () => go(false); $("ko-neu").onclick = () => go(true);
    $("ko-pw").addEventListener("keydown", (e) => { if (e.key === "Enter") go(false); });
    $("ko-skip").onclick = () => ov.remove();
  }, 2500);
})();
