// Jarvis-Konto (Test) im PC-HUD: Anmeldefenster beim ersten Start, „Konto“ in den Einstellungen öffnet es wieder.
(function () {
  if (!window.PC) return;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const css = document.createElement("style");
  css.textContent = `
  #konto-ov{position:fixed;inset:0;z-index:9000;background:rgba(2,5,8,.82);backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;color:#c8f3e8}
  #konto-ov[hidden]{display:none}
  #konto-ov .ko-card{width:420px;max-width:92vw;padding:30px 30px 22px;border-radius:24px;border:1px solid rgba(60, 255, 190,.45);background:radial-gradient(120% 90% at 50% 0%,#062a1e 0%,#070b0f 65%);box-shadow:0 0 60px rgba(29, 158, 117,.18);display:flex;flex-direction:column;align-items:center}
  #konto-ov .ko-orb{width:80px;height:80px;border-radius:50%;background:radial-gradient(circle at 50% 45%,#d8fff8 0%,#9fe1cb 30%,#10d694 60%,rgba(0, 120, 66,0) 72%);box-shadow:0 0 50px rgba(60, 255, 190,.5);margin-bottom:14px}
  #konto-ov h1{margin:0;font-size:20px;letter-spacing:5px;color:#9fe1cb}
  #konto-ov p{margin:8px 0 18px;color:#7fb9aa;font-size:13.5px;text-align:center;line-height:1.45}
  #konto-ov input{width:100%;box-sizing:border-box;padding:12px 14px;border-radius:12px;border:1px solid #185a46;background:#0d1217;color:#c8f3e8;font-size:15px;margin-bottom:10px}
  #konto-ov .ko-row{display:flex;gap:10px;width:100%;margin-top:4px}
  #konto-ov button{flex:1;padding:12px;border-radius:12px;border:1px solid #1d9e75;background:linear-gradient(#083a28,#051d15);color:#9fe1cb;font-weight:700;font-size:14px;cursor:pointer}
  #konto-ov button.alt{border-color:#3a4a55;background:#0d1217;color:#cfd8dd;font-weight:600}
  #konto-ov .ko-msg{min-height:20px;font-size:13px;color:#ff9a8a;text-align:center;margin:2px 0 8px}
  #konto-ov .ko-msg.ok{color:#6effcd}
  #konto-ov .ko-skip{margin-top:14px;color:#7f8b92;font-size:12.5px;text-decoration:underline;cursor:pointer}
  #konto-ov .ko-in{width:100%}
  #konto-ov.busy button{opacity:.5;pointer-events:none}`;
  document.head.appendChild(css);
  const ov = document.createElement("div");
  ov.id = "konto-ov"; ov.hidden = true;
  ov.innerHTML = `<div class="ko-card"><div class="ko-orb"></div><h1>VECTOR-KONTO</h1>
    <p id="ko-p">Melde dich an – dann ist dein Vector auf jedem PC und Handy gleich.</p>
    <div class="ko-in" id="ko-form"><input id="ko-mail" type="email" placeholder="E-Mail"><input id="ko-pw" type="password" placeholder="Passwort (mind. 6 Zeichen)">
    <div class="ko-msg" id="ko-msg"></div><div class="ko-row"><button id="ko-in">Anmelden</button><button class="alt" id="ko-neu">Neues Konto</button></div></div>
    <div class="ko-in" id="ko-acc" hidden><div class="ko-msg ok" id="ko-st"></div><div class="ko-row"><button id="ko-sync">Jetzt abgleichen</button><button class="alt" id="ko-out">Abmelden</button></div>
    <div class="ko-skip" id="ko-pwreset">Passwort zurücksetzen</div></div>
    <div class="ko-skip" id="ko-forgot">Passwort vergessen?</div>
    <div class="ko-skip" id="ko-skip" style="margin-top:8px">Schließen</div></div>`;
  document.body.appendChild(ov);
  const msg = (t, ok) => { $("ko-msg").textContent = t || ""; $("ko-msg").classList.toggle("ok", !!ok); };
  const when = (t) => t ? new Date(t).toLocaleString("de-DE", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }) : "noch nie";
  function paint(i, extra) {
    i = i || window.PC.get("konto") || {};
    $("ko-form").hidden = !!i.loggedIn; $("ko-acc").hidden = !i.loggedIn;
    $("ko-p").textContent = i.loggedIn ? "Dein Vector ist im Konto." : (i.configured ? "Melde dich an – dann ist dein Vector auf jedem PC und Handy gleich." : "Das Konto ist in dieser Version noch nicht eingerichtet.");
    $("ko-st").innerHTML = i.loggedIn ? `Angemeldet als <b>${esc(i.email)}</b><br>Hochgeladen: ${when(i.lastPush)} · Geholt: ${when(i.lastPull)}${i.err ? `<br><span style="color:#ff9a8a">${esc(i.err)}</span>` : ""}${extra ? "<br>" + esc(extra) : ""}` : "";
  }
  async function call(name, body) {
    ov.classList.add("busy");
    try { const r = await window.PC.post(name, body); return r ? await r.json() : { ok: false, text: "Keine Antwort." }; }
    catch (e) { return { ok: false, text: "Keine Antwort." }; } finally { ov.classList.remove("busy"); }
  }
  async function go(neu) {
    const m = $("ko-mail").value.trim(), p = $("ko-pw").value;
    if (!m.includes("@")) return msg("Bitte deine E-Mail eintragen.");
    if (p.length < 6) return msg("Passwort: mindestens 6 Zeichen.");
    msg(neu ? "Lege dein Konto an …" : "Melde an …", true);
    const r = await call("konto_login", { email: m, pw: p, neu: !!neu });
    msg(r.text, r.ok);
    if (r.ok) { $("ko-pw").value = ""; setTimeout(() => paint(r.info, r.text), 900); }
  }
  $("ko-pwreset").onclick = async () => {
    const i = await call("konto_info", {}).catch(() => ({}));
    const m = (i && i.email) || "";
    $("ko-st").textContent = "Schicke dir eine Mail …";
    const r = await call("konto_reset", { email: m || ($("ko-mail").value || "").trim() });
    $("ko-st").textContent = r.text || "";
  };
  $("ko-forgot").onclick = async () => {
    const m = $("ko-mail").value.trim();
    if (!m.includes("@")) return msg("Trag oben deine E-Mail ein, dann klick nochmal auf „Passwort vergessen?“.");
    msg("Schicke dir eine Mail …", true);
    const r = await call("konto_reset", { email: m }); msg(r.text, r.ok);
  };
  $("ko-in").onclick = () => go(false);
  $("ko-neu").onclick = () => go(true);
  $("ko-pw").addEventListener("keydown", (e) => { if (e.key === "Enter") go(false); });
  $("ko-sync").onclick = async () => { $("ko-st").textContent = "Gleiche ab …"; const r = await call("konto_sync", {}); paint(r.info, r.text); };
  $("ko-out").onclick = async () => { const i = await call("konto_logout", {}); paint(i); msg(""); };
  $("ko-skip").onclick = () => { try { localStorage.setItem("konto_skip", "1"); } catch (e) {} ov.hidden = true; };
  window.JKonto = { open: () => { paint(); ov.hidden = false; } };
  const i = window.PC.get("konto") || {};
  let skip = false; try { skip = localStorage.getItem("konto_skip") === "1"; } catch (e) {}
  if (!i.loggedIn && !skip) setTimeout(() => window.JKonto.open(), 1500);
})();
