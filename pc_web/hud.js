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
  const strand = new Strand($("strand"), 1, { key: [[-.1, .62], [.12, .55], [.3, .5], [.5, .47], [.7, .43], [.88, .36], [1.1, .3]], rings: [[.5, .47, .2]], twigs: 14, S: (w, h) => h / 520 });

  // Größe und Lage der Kugeln je nach Fenstergröße
  function layout() {
    const W = innerWidth, H = innerHeight - 46 - (document.body.classList.contains("handy") ? 92 : 0);
    const fs = Math.min(W * .4, H * .62), is = Math.min(W * .3, H * .5);
    Object.assign($("f-sph").style, { width: fs + "px", height: fs + "px", left: (W - fs) / 2 + "px", top: H * .06 + "px" });
    $("f-name").style.top = H * .06 + fs - 6 + "px"; $("f-state").style.top = H * .06 + fs + 36 + "px"; $("f-talk").style.top = H * .06 + fs + 70 + "px";
    Object.assign($("i-sph").style, { width: is + "px", height: is + "px", left: (W - is) / 2 + "px", top: H * .14 + "px" });
    $("i-name").style.top = H * .14 + is + 8 + "px"; $("i-state").style.top = H * .14 + is + 50 + "px";
    strand.opts.rings = [[.5, (46 + H * .06 + fs / 2) / innerHeight, fs * .55 / W]]; strand.W = 0;
  }
  addEventListener("resize", layout); layout();

  // Seiten umschalten
  function setMode(m, save) {
    if (m === "flug") { window.PC.post("mode", { mode: "flug" }); return; }
    mode = m;
    document.querySelectorAll(".pv").forEach((e) => e.classList.toggle("on", e.id === "pv-" + m || (m === "lage" && e.id === "v-lage")));
    document.querySelectorAll("#modes span, #pnav div").forEach((e) => e.classList.toggle("on", e.dataset.m === m));
    if (m === "steuern" && window.JHandy) window.JHandy.shown();
    $("strand").style.display = m === "lage" ? "none" : "";
    if (m === "lage" && window.JLage) window.JLage.shown();
    if (m === "info") info(true);
    if (save) window.PC.post("mode", { mode: m });
  }
  document.querySelectorAll("#modes span, #pnav div").forEach((e) => e.addEventListener("click", () => setMode(e.dataset.m, true)));
  $("gear").addEventListener("click", () => window.JSettings && window.JSettings.open());
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
    if (force) {
      const t = window.PC.get("termine") || [];
      $("i-termine").innerHTML = t.length ? t.map((e) => `<div class="row"><span>${esc(e.when)}</span><b>${esc(e.title)}</b></div>`).join("") : "Keine Termine in den nächsten 7 Tagen.";
      weather();
    }
  }
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
    else { strand.level = level; strand.power = power; strand.draw(dt); }
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
