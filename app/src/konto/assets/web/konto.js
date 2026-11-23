// Jarvis-Konto (Test-App): Anmeldebildschirm beim ersten Start + Bereich „Konto“ in den Einstellungen.
(function () {
  const A = window.Android;
  if (!A || !A.kontoInfo) return;
  const $ = (id) => document.getElementById(id);
  const info = () => { try { return JSON.parse(A.kontoInfo()); } catch (e) { return {}; } };
  const esc = (s) => String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const css = document.createElement("style");
  css.textContent = `
  #konto-ov{position:fixed;inset:0;z-index:9000;background:radial-gradient(120% 80% at 50% 0%,#062a1e 0%,#05080b 60%);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:28px 22px;color:#c8f3e8;font-family:inherit}
  #konto-ov[hidden]{display:none}
  #konto-ov .ko-orb{width:96px;height:96px;border-radius:50%;background:radial-gradient(circle at 50% 45%,#d8fff8 0%,#9fe1cb 30%,#10d694 60%,rgba(0, 120, 66,0) 72%);box-shadow:0 0 60px rgba(60, 255, 190,.55);margin-bottom:18px}
  #konto-ov h1{margin:0;font-size:22px;letter-spacing:5px;color:#9fe1cb}
  #konto-ov p{margin:8px 0 20px;color:#7fb9aa;font-size:14px;text-align:center;line-height:1.45;max-width:320px}
  #konto-ov .ko-box{width:100%;max-width:340px;display:flex;flex-direction:column;gap:10px}
  #konto-ov input{width:100%;box-sizing:border-box;padding:14px;border-radius:14px;border:1px solid #185a46;background:#0d1217;color:#c8f3e8;font-size:16px}
  #konto-ov .ko-btn{padding:14px;border-radius:14px;border:1px solid #1d9e75;background:linear-gradient(#083a28,#051d15);color:#9fe1cb;font-weight:700;font-size:16px;text-align:center}
  #konto-ov .ko-btn.alt{border-color:#3a4a55;background:#0d1217;color:#cfd8dd;font-weight:600}
  #konto-ov .ko-msg{min-height:20px;font-size:13px;color:#ff9a8a;text-align:center}
  #konto-ov .ko-msg.ok{color:#6effcd}
  #konto-ov .ko-skip{margin-top:16px;color:#7f8b92;font-size:13px;text-decoration:underline}
  #konto-ov .ko-warn{margin:0 0 14px;padding:10px 12px;border-radius:12px;border:1px solid #126b4e;background:#061a13;color:#8ae8ce;font-size:12.5px;max-width:316px;line-height:1.4}
  #konto-ov.busy .ko-btn{opacity:.5;pointer-events:none}`;
  document.head.appendChild(css);

  const ov = document.createElement("div");
  ov.id = "konto-ov"; ov.hidden = true;
  ov.innerHTML = `<div class="ko-orb"></div><h1>VECTOR</h1>
    <p>Melde dich mit deinem Vector-Konto an – dann ist alles so wie auf deinen anderen Geräten.</p>
    <div class="ko-warn" id="ko-warn" hidden>Auf diesem Handy ist auch die normale Vector-App. Die Konto-App hört deshalb nicht von selbst im Hintergrund zu (sonst antworten beide).</div>
    <div class="ko-box">
      <input id="ko-mail" type="email" placeholder="E-Mail" autocomplete="email" autocapitalize="none">
      <input id="ko-pw" type="password" placeholder="Passwort (mind. 6 Zeichen)" autocomplete="current-password">
      <div class="ko-msg" id="ko-msg"></div>
      <div class="ko-btn" id="ko-in">Anmelden</div>
      <div class="ko-btn alt" id="ko-neu">Neues Konto anlegen</div>
    </div>
    <div class="ko-skip" id="ko-skip">Erst mal ohne Konto</div>`;
  document.body.appendChild(ov);

  const msg = (t, ok) => { $("ko-msg").textContent = t || ""; $("ko-msg").classList.toggle("ok", !!ok); };
  function go(neu) {
    const m = $("ko-mail").value.trim(), p = $("ko-pw").value;
    if (!m.includes("@")) return msg("Bitte deine E-Mail eintragen.");
    if (p.length < 6) return msg("Passwort: mindestens 6 Zeichen.");
    ov.classList.add("busy"); msg(neu ? "Lege dein Konto an …" : "Melde an …", true);
    A.kontoLogin(m, p, !!neu);
  }
  $("ko-in").onclick = () => go(false);
  $("ko-neu").onclick = () => go(true);
  $("ko-pw").addEventListener("keydown", (e) => { if (e.key === "Enter") go(false); });
  $("ko-skip").onclick = () => { try { localStorage.setItem("konto_skip", "1"); } catch (e) {} ov.hidden = true; };

  // Ergebnis vom Handy
  const prev = window.jarvis && window.jarvis.onEvent;
  if (window.jarvis) window.jarvis.onEvent = function (type, data) {
    if (type === "konto") {
      const d = typeof data === "string" ? JSON.parse(data) : (data || {});
      ov.classList.remove("busy");
      if (!ov.hidden) {
        msg(d.text, d.ok);
        if (d.ok) setTimeout(() => { ov.hidden = true; A.kontoRestart(); }, 1200);   // neu laden, damit alle geladenen Einstellungen gelten
      }
      paint(d.text);
      return;
    }
    return prev && prev.call(window.jarvis, type, data);
  };

  // Bereich „Konto“ in den Einstellungen (ganz oben)
  function addPane() {
    const home = $("sp-home"); if (!home || $("sp-konto")) return;
    const grp = document.createElement("div");
    grp.innerHTML = `<div class="sgrp">KONTO</div><div class="slist"><div class="sitem" data-go="konto"><i style="background:#062a1e">👤</i><div><b>Vector-Konto</b><small id="ko-sub">…</small></div><span>›</span></div></div>`;
    home.insertBefore(grp, home.firstChild);
    const pane = document.createElement("div");
    pane.className = "spane"; pane.id = "sp-konto";
    pane.innerHTML = `<div class="sec" style="--c:#9fe1cb"><h3>DEIN KONTO</h3><div id="ko-state" class="note"></div>
      <div class="srow"><div>Jetzt abgleichen<small>Passiert sonst alle 5 Minuten von selbst</small></div><div class="sbtn" id="ko-sync">Abgleichen</div></div>
      <div class="srow"><div>Abmelden<small>Die Daten auf diesem Handy bleiben</small></div><div class="sbtn" id="ko-out">Abmelden</div></div>
      <div class="note">Alles wird mit deinem Passwort verschlüsselt, bevor es ins Konto geht. Ohne Passwort kann es niemand lesen – auch der Server nicht. Passwort vergessen heißt: neu anfangen.</div></div>`;
    home.parentElement.appendChild(pane);
    const stabs = $("stabs"); if (stabs) stabs.insertAdjacentHTML("afterbegin", '<span data-p="konto">Konto</span>');
    grp.querySelector(".sitem").addEventListener("click", () => {
      document.querySelectorAll(".spane").forEach((x) => x.classList.toggle("on", x.id === "sp-konto"));
      const t = document.querySelector("#settings .sttl"); if (t) t.textContent = "VECTOR-KONTO";
      $("settings").classList.add("ssub"); paint();
    });
    $("ko-sync").onclick = () => { $("ko-state").textContent = "Gleiche ab …"; A.kontoSync(); };
    $("ko-out").onclick = () => { A.kontoLogout(); paint(); try { localStorage.removeItem("konto_skip"); } catch (e) {} showLogin(); };
    // ‹ zurück aus dem Konto-Bereich
    const back = window.jSettingsBack;
    window.jSettingsBack = () => { if ($("sp-konto").classList.contains("on")) { const h = document.querySelector('.sitem[data-go="allg"]'); document.querySelectorAll(".spane").forEach((x) => x.classList.toggle("on", x.id === "sp-home")); const t = document.querySelector("#settings .sttl"); if (t) t.textContent = "EINSTELLUNGEN"; $("settings").classList.remove("ssub"); return true; } return back ? back() : false; };
    paint();
  }
  const when = (t) => t ? new Date(t).toLocaleString("de-DE", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }) : "noch nie";
  function paint(extra) {
    const i = info(), sub = $("ko-sub"), st = $("ko-state");
    if (sub) sub.textContent = i.loggedIn ? i.email : (i.configured ? "Nicht angemeldet – antippen" : "Noch nicht eingerichtet");
    if (st) st.innerHTML = i.loggedIn
      ? `Angemeldet als <b>${esc(i.email)}</b><br>Hochgeladen: ${when(i.lastPush)} · Geholt: ${when(i.lastPull)}${i.err ? `<br><span style="color:#ff9a8a">${esc(i.err)}</span>` : ""}${extra ? `<br>${esc(extra)}` : ""}`
      : `Nicht angemeldet. <span class="sbtn" id="ko-login2" style="display:inline-block;margin-top:8px">Anmelden</span>`;
    const l2 = $("ko-login2"); if (l2) l2.onclick = showLogin;
  }
  function showLogin() { const i = info(); $("ko-warn").hidden = !i.parallel; msg(""); ov.hidden = false; }

  addPane();
  const i = info();
  let skip = false; try { skip = localStorage.getItem("konto_skip") === "1"; } catch (e) {}
  if (!i.configured) { msg("Das Konto ist in dieser Version noch nicht eingerichtet."); }
  if (!i.loggedIn && !skip) setTimeout(showLogin, 300);
})();
