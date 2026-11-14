// PC-HUD: Fokus, Info und Lage – gleiche Bausteine wie die Handy-App.
(function () {
  const $ = (id) => document.getElementById(id);
  const S = window.PC.get("settings") || {};
  const name = (S.assistant_name || "J.A.R.V.I.S.");
  $("aname").textContent = name; $("f-name").textContent = name; $("i-name").textContent = name; $("s-name").textContent = name;
  document.body.classList.toggle("handy", S.hud_layout === "handy");   // Aufbau wie die Handy-App (Leiste unten)
  let mode = ["fokus", "info", "lage", "steuern"].includes(S.hud_mode) ? S.hud_mode : "info";
  let level = 0, target = 0, state = "idle";

  // Kugeln (jede Seite hat ihre eigene, gezeichnet wird nur die sichtbare)
  function mk(id, seed, scale) {
    const w = $(id); let s = null, b = null;
    try { s = new Sphere3D(w.querySelector("canvas.sphere"), seed); b = new JarvisBrain(w.querySelector("canvas.brain"), s); b.scale = scale; } catch (e) {}
    return { w, s, b };
  }
  const sph = { fokus: mk("f-sph", 3, .72), info: mk("i-sph", 5, .8), lage: mk("l-sph", 7, .9), steuern: mk("s-sph", 9, .85) };
  // Nervenstrang als großes Panorama über alle Seiten (Info, Fokus, Lage, Steuern) – beim Umschalten gleitet er weiter, wie am Handy
  const PORDER = ["info", "fokus", "lage", "steuern"];
  const strand = new Strand($("strand"), 4, { key: [[-.2, .6], [.2, .5], [.5, .48], [.85, .42], [1.2, .5], [1.5, .47], [1.85, .36], [2.2, .26], [2.5, .3], [2.85, .22], [3.2, .4], [3.5, .5], [3.85, .44], [4.3, .3]],
    rings: [], twigs: 46, S: (w, h) => h / 520 });
  let strandTarget = Math.max(0, PORDER.indexOf(mode)), pageDir = 1; strand.offset = strandTarget;

  // Größe und Lage der Kugeln je nach Fenstergröße
  function layout() {
    const W = innerWidth, H = innerHeight - 46 - (document.body.classList.contains("handy") ? 92 : 0) - 70;   // 70 = Schreibfeld
    const fs = Math.min(W * .4, H * .62), is = Math.min(W * .3, H * .5);
    Object.assign($("f-sph").style, { width: fs + "px", height: fs + "px", left: (W - fs) / 2 + "px", top: H * .06 + "px" });
    $("f-name").style.top = H * .06 + fs - 6 + "px"; $("f-state").style.top = H * .06 + fs + 36 + "px"; $("f-talk").style.top = H * .06 + fs + 70 + "px";
    Object.assign($("i-sph").style, { width: is + "px", height: is + "px", left: (W - is) / 2 + "px", top: H * .14 + "px" });
    $("i-name").style.top = H * .14 + is + 8 + "px"; $("i-state").style.top = H * .14 + is + 50 + "px";
    strand.opts.rings = [[1.5, (46 + H * .06 + fs / 2) / innerHeight, fs * .55 / W], [.5, (46 + H * .14 + is / 2) / innerHeight, is * .55 / W]]; strand.W = 0;
  }
  addEventListener("resize", layout); layout();

  // Seiten umschalten
  function setMode(m, save) {
    if (m === "flug") { window.PC.post("mode", { mode: "flug" }); return; }
    const from = PORDER.indexOf(mode), to = PORDER.indexOf(m);
    pageDir = to >= from ? 1 : -1; if (to >= 0) strandTarget = to;
    document.body.style.setProperty("--pdir", pageDir);
    mode = m;
    document.querySelectorAll(".pv").forEach((e) => { const on = e.id === "pv-" + m || (m === "lage" && e.id === "v-lage");
      if (on && !e.classList.contains("on")) { e.classList.remove("slidein"); void e.offsetWidth; e.classList.add("slidein"); }
      e.classList.toggle("on", on); });
    document.querySelectorAll("#modes span, #pnav div").forEach((e) => e.classList.toggle("on", e.dataset.m === m));
    if (m === "steuern" && window.JHandy) window.JHandy.shown();
    $("strand").style.display = "";
    $("typebar").style.display = m === "lage" ? "none" : "";
    $("tb-reply").classList.remove("on");
    if (m === "lage" && window.JLage) window.JLage.shown();
    if (m === "info") info(true);
    if (save) window.PC.post("mode", { mode: m });
  }
  document.querySelectorAll("#modes span, #pnav div").forEach((e) => e.addEventListener("click", () => setMode(e.dataset.m, true)));
  $("gear").addEventListener("click", () => window.JSettings && window.JSettings.open());
  try { if ((window.PC.get("settings_new") || []).length) $("gear").classList.add("hasnew"); } catch (e) {}
  if (window.JLage) window.JLage.prefs(S);

  // An/Aus wie am Handy: aus = Jarvis schläft (hört nicht aufs Aktivierungswort), Kugel und Strang werden grau und still
  let power = true;
  function showPower(on) {
    power = on; $("pwr").classList.toggle("on", on);
    document.body.classList.toggle("asleep", !on);
    for (const k in sph) if (sph[k].s) sph[k].s.power = on;
    strand.power = on;
    ["f-state", "i-state", "s-state"].forEach((id) => { if (!on) $(id).textContent = "schläft"; else if ($(id).textContent === "schläft") $(id).textContent = "bereit"; });
  }
  $("pwr").addEventListener("click", () => { const on = !power; showPower(on); window.PC.post("power", { on }); });
  try { showPower(!!(window.PC.get("power") || { on: true }).on); } catch (e) {}

  // Schnellstart-Knöpfe (wie im alten HUD)
  const QB = S.hud_buttons || [["♪", "Musik", "musik an"], ["▶", "YouTube", "öffne youtube"], ["D", "Discord", "öffne discord"], ["S", "Steam", "öffne steam"], ["◍", "Lage", "wie ist die lage"], ["☾", "Sperren", "sperre den pc"]];
  $("qb").innerHTML = QB.slice(0, 12).map((b, i) => `<span title="${(b[1] || "").replace(/"/g, "")}" data-i="${i}">${b[0] || "•"}</span>`).join("");
  $("qb").querySelectorAll("span").forEach((e) => e.addEventListener("click", () => { const b = QB[+e.dataset.i]; if (b && b[2]) window.PC.post("cmd", { text: b[2] }); }));

  // Info-Seite: Uhr, Wetter, System, Termine
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function clock() { const d = new Date(); $("i-clock").textContent = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }); $("i-date").textContent = d.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" }); }
  clock(); setInterval(clock, 10000);
  function weather() {
    const h = window.PC.get("home") || { lat: 48.8, lon: 9.01 };
    $("i-city").textContent = (window.PC.get("city") || "WETTER").toUpperCase();
    fetch(`https://api.open-meteo.com/v1/forecast?latitude=${h.lat}&longitude=${h.lon}&current=temperature_2m,apparent_temperature&daily=precipitation_probability_max&timezone=Europe%2FBerlin&forecast_days=1`)
      .then((r) => r.json()).then((j) => { $("i-temp").textContent = Math.round(j.current.temperature_2m) + "°"; $("i-feel").textContent = Math.round(j.current.apparent_temperature) + "°";
        const p = (j.daily.precipitation_probability_max || [null])[0]; $("i-rain").textContent = p == null ? "–" : p + " %"; }).catch(() => {});
  }
  let lastInfo = 0;
  function info(force) {
    if (!force && Date.now() - lastInfo < 4000) return; lastInfo = Date.now();
    const s = window.PC.get("sys") || {};
    $("i-cpu").textContent = s.cpu != null ? s.cpu + " %" : "–";
    $("i-gpu").textContent = s.gpu ? `${s.gpu.util} % · ${s.gpu.temp} °C` : "–";
    $("i-ram").textContent = s.ram_used != null ? `${s.ram_used} / ${s.ram_total} GB` : "–";
    $("i-handy").textContent = s.handy || "Kopplung aktiv – Stand kommt alle paar Minuten.";
    ets2();
    if (force) {
      const t = window.PC.get("termine") || [];
      $("i-termine").innerHTML = t.length ? t.map((e) => `<div class="row"><span>${esc(e.when)}</span><b>${esc(e.title)}</b></div>`).join("") : "Keine Termine in den nächsten 7 Tagen.";
      weather();
    }
  }
  // Fahrtenseite ETS2 (nur sichtbar, wenn das Spiel läuft)
  function ets2() {
    let e = {}; try { e = window.PC.get("ets2") || {}; } catch (x) {}
    const card = $("i-ets2"); if (!card) return;
    card.style.display = e.aktiv ? "" : "none";
    if (!e.aktiv) return;
    const hm = (m) => m > 0 ? (m >= 60 ? Math.floor(m / 60) + " h " + (m % 60) + " min" : m + " min") : "–";
    $("e-head").textContent = "FAHRT · " + (e.spiel || "ETS2") + (e.pause ? " · PAUSE" : "");
    $("e-kmh").textContent = e.kmh + " km/h" + (e.limit ? "  ·  max " + e.limit : "");
    $("e-job").textContent = e.ladung ? `${e.ladung}: ${e.von} → ${e.nach}${e.nach_firma ? " (" + e.nach_firma + ")" : ""}` : (e.lkw || "kein Auftrag");
    $("e-tank").textContent = `${e.tank_pct} % · ${e.reichweite_km} km`;
    $("e-tank").style.color = e.tank_pct <= 15 ? "#ff6b5a" : "";
    $("e-ziel").textContent = e.rest_km ? `${e.rest_km} km · ${hm(e.rest_min)}` : "–";
    $("e-ruhe").textContent = hm(e.ruhe_min);
    $("e-lohn").textContent = e.lohn ? e.lohn.toLocaleString("de-DE") + " €" : "–";
  }
  setInterval(() => { if (mode === "info") ets2(); }, 2000);
  // Handy-Kamera (kommt über den Fernzugriff, nur solange die Jarvis-App am Handy sendet)
  let camOn = false;
  setInterval(() => {
    let live = false; try { live = !!(window.PC.get("phonecam") || {}).live; } catch (x) {}
    if (live !== camOn) { camOn = live; $("phcam").style.display = live ? "" : "none"; }
  }, 2000);
  setInterval(() => { if (camOn) $("phcam-img").src = "/phonecam.jpg?t=" + Date.now(); }, 300);
  setInterval(() => { if (mode === "info") info(false); }, 5000);
  setInterval(() => { if (mode === "info") info(true); }, 10 * 60000);
  const log = [];
  function addLog(t) { log.unshift(t); log.length = Math.min(log.length, 6); $("i-log").innerHTML = log.map((x) => `<div>„${esc(x)}“</div>`).join(""); }

  // Zustände vom PC-Jarvis
  const STATES = { idle: "bereit", listening: "hört zu …", thinking: "denkt nach …", speaking: "spricht …" };
  function setState(st) {
    state = st;
    for (const k in sph) if (sph[k].s) sph[k].s.state = st === "idle" ? "idle" : st;
    $("f-state").textContent = $("i-state").textContent = $("s-state").textContent = !power && st === "idle" ? "schläft" : (STATES[st] || st);
    if (st === "idle") target = 0;
  }
  function onEvent(type, d) {
    if (type === "state") setState(d.state);
    else if (type === "msg" && typedAt && Date.now() - typedAt < 120000 && d.role === "Assistent" && d.text && !/^(Denke nach|Einen Moment)/.test(d.text)) {
      tbShow(d.text); if (d.text) { $("f-jar").textContent = $("s-jar").textContent = d.text; }
    }
    else if (type === "msg") {
      if (d.role === "Du" && d.text) { $("f-you").textContent = $("s-you").textContent = d.text; addLog(d.text); }
      else if (d.role === "Assistent" && d.text) $("f-jar").textContent = $("s-jar").textContent = d.text;
    }
    else if (type === "level") target = d.value || 0;
    else if (type === "think") { for (const k in sph) if (sph[k].b) sph[k].b.think(d.kinds || [], d.ms || 4500); }
    else if (type === "mode") setMode(d.mode, false);
    else if (type === "power") showPower(!!d.on);
    else if (type === "phone") { if (window.JHandy) window.JHandy.onStatus(d); }
    else if (type === "phone_reply") { if (window.JHandy) window.JHandy.onReply(d); }
    else if (type === "lage") {
      if (d.tour) setMode("lage", false);
      if (window.JLage) window.JLage.onData(d.data, !!d.tour);
      if (d.data && d.data.ort !== "Für dich") { $("l-brief").textContent = d.data.briefing || "–"; tourList(d.data); }
    }
    else if (type === "lage_focus") { if (window.JLage) window.JLage.onFocus(d.i, d.n, d.of); markTour(d.i); }
    else if (type === "lage_error") { if (window.JLage) window.JLage.onError(d.text, d.ort); }
    else if (type === "settings") { if (window.JSettings && window.JSettings.isOpen()) window.__reload = true; else location.reload(); }
    else if (type === "open_settings") { if (window.JSettings && !window.JSettings.isOpen()) window.JSettings.open(); }
  }
  window.jarvis = { onEvent };
  // Schreiben statt reden
  let typedAt = 0;
  function tbShow(t) { if (mode === "fokus") return;   // auf Fokus steht die Antwort im Gesprächsfeld
 const r = $("tb-reply"); r.innerHTML = '<span class="who jar">JARVIS</span>' + esc(t); r.classList.add("on"); clearTimeout(tbShow.j); tbShow.j = setTimeout(() => r.classList.remove("on"), 60000); }
  function tbSend() {
    const t = $("tb-in").value.trim(); if (!t) return;
    $("tb-in").value = ""; typedAt = Date.now();
    $("f-you").textContent = $("s-you").textContent = t;
    if (mode === "fokus") $("f-jar").textContent = "denkt nach …";
    else { const r = $("tb-reply"); r.innerHTML = '<span class="who jar">JARVIS</span>denkt nach …'; r.classList.add("on"); }
    window.PC.post("ask", { text: t });
  }
  $("tb-send").addEventListener("click", tbSend);
  $("tb-in").addEventListener("keydown", (e) => { if (e.key === "Enter") tbSend(); if (e.key === "Escape") { $("tb-reply").classList.remove("on"); $("tb-in").blur(); } });
  function tourList(data) {
    const pts = data.brennpunkte || [];
    const idx = pts.map((p, i) => i).filter((i) => pts[i].im_briefing).slice(0, 6);
    $("l-tour").innerHTML = idx.map((i, n) => `<div data-i="${i}">${n + 1} · ${esc(pts[i].ort || "")} – ${esc(pts[i].titel || "")}</div>`).join("");
    $("l-tour").querySelectorAll("div").forEach((e) => e.addEventListener("click", () => { const c = document.querySelector(`.lcd[data-i="${e.dataset.i}"]`); if (c) c.click(); }));
  }
  function markTour(i) { document.querySelectorAll("#l-tour div").forEach((e) => e.classList.toggle("on", +e.dataset.i === i)); }
  const ev = new EventSource("/events");
  ev.onmessage = (m) => { try { const o = JSON.parse(m.data); onEvent(o.type, o.data); } catch (e) { console.error("HUD-Ereignis:", e && e.message); } };

  // Animation
  let last = performance.now();
  function frame(now) {
    const dt = Math.min(.1, (now - last) / 1000); last = now;
    level += (target - level) * .25; target *= .94;
    const v = sph[mode];
    if (v && v.s) { v.s.level = level; v.s.draw(dt); v.b && v.b.draw(dt); }
    if (mode === "info") rings(dt);
    if (mode === "lage") { if (window.JLage) window.JLage.draw(dt); }
    strand.offset += (strandTarget - strand.offset) * Math.min(1, dt * 7);
    if (mode !== "lage" || Math.abs(strand.offset - strandTarget) > .01) { strand.level = level; strand.power = power; strand.draw(dt); }
    $("strand").style.opacity = mode === "lage" ? Math.max(0, Math.min(1, Math.abs(strand.offset - strandTarget) * 2)) : 1;
    requestAnimationFrame(frame);
  }
  const rc = document.querySelector("#i-sph canvas.rings"), rg = rc.getContext("2d"); let rt = 0;
  function rings(dt) {
    const w = Math.round(rc.clientWidth * (devicePixelRatio || 1)); if (!w) return; if (rc.width !== w) rc.width = rc.height = w; rt += dt;
    rg.clearRect(0, 0, w, w);
    [[.49, 4, "#3cc8ff", 12], [.47, 2, "#145a82", -18]].forEach(([r, lw, c, sp]) => { rg.strokeStyle = c; rg.lineWidth = lw * w / 400;
      for (let k = 0; k < 3; k++) { const a = (k * 120 + rt * sp) * Math.PI / 180; rg.beginPath(); rg.arc(w / 2, w / 2, w * r, a, a + 70 * Math.PI / 180); rg.stroke(); } });
  }
  setMode(mode, false);
  requestAnimationFrame(frame);
  // "Für dich" einmal im Hintergrund holen (für die Info-Seite)
  setTimeout(() => window.PC.post("getLage", { place: "@fuerdich" }), 5000);
})();
