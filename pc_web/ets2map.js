// FAHRT-Seite im HUD: sobald ETS2/ATS läuft, erscheint oben „FAHRT“ (und das HUD springt einmal dorthin).
// Links die Karte (dein Truck, Spur, Tankstellen ⛽, Rastplätze P, Städte, Tankstopp-Vorschlag, Zielrichtung),
// rechts Tempo, Tank, Ruhezeit, Auftrag, nächste Tankstelle/Schlafplatz.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const modes = $("modes"); if (!modes) return;
  const tab = document.createElement("span"); tab.dataset.m = "fahrt"; tab.textContent = "FAHRT"; tab.style.display = "none";
  modes.insertBefore(tab, modes.firstChild);
  tab.addEventListener("click", () => window.JHudMode && window.JHudMode("fahrt", false));

  const sec = document.createElement("section"); sec.className = "pv"; sec.id = "pv-fahrt";
  sec.innerHTML = `<div class="fz">
    <div class="fz-map"><canvas id="fz-c"></canvas><div class="fz-zoom"><span data-z="-1">−</span><span data-z="1">+</span></div><div class="fz-leg">⛽ Tankstelle · P Rastplatz · ◆ Tankstopp</div></div>
    <div class="fz-side">
      <div class="fz-card"><div class="fz-ct" id="fz-head">FAHRT</div><div class="fz-big" id="fz-kmh">–</div><div class="fz-mut" id="fz-hier">–</div></div>
      <div class="fz-card"><div class="fz-ct">TANK</div><div class="fz-bar"><i id="fz-tankbar"></i></div><div class="fz-row"><span>Stand</span><b id="fz-tank">–</b></div><div class="fz-row"><span>Nächste Tankstelle</span><b id="fz-nt">–</b></div><div class="fz-plan" id="fz-plan">–</div></div>
      <div class="fz-card"><div class="fz-ct">AUFTRAG</div><div class="fz-mut" id="fz-job">–</div><div class="fz-row"><span>Ziel</span><b id="fz-ziel">–</b></div><div class="fz-row"><span>Lohn</span><b id="fz-lohn">–</b></div></div>
      <div class="fz-card"><div class="fz-ct">RUHEZEIT</div><div class="fz-row"><span>Schlafen in</span><b id="fz-ruhe">–</b></div><div class="fz-row"><span>Nächster Schlafplatz</span><b id="fz-ns">–</b></div></div>
    </div></div>`;
  (document.querySelector("#pv-info") || document.body).parentNode.appendChild(sec);

  const css = document.createElement("style");
  css.textContent = `
#pv-fahrt .fz{position:absolute;inset:14px 18px 70px 18px;display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:14px}
.fz-map{position:relative;border:1px solid rgba(29, 158, 117,.35);border-radius:18px;overflow:hidden;background:radial-gradient(circle at 50% 50%,#0f1c22,#050b0e 75%)}
.fz-map canvas{position:absolute;inset:0;width:100%;height:100%}
.fz-zoom{position:absolute;right:12px;top:12px;display:flex;flex-direction:column;gap:6px}
.fz-zoom span{width:32px;height:32px;border-radius:10px;border:1px solid rgba(159, 225, 203,.4);background:rgba(4,16,26,.85);color:#9fe1cb;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:18px}
.fz-leg{position:absolute;left:12px;bottom:10px;font-size:11px;color:#5ac89b;letter-spacing:.06em;background:rgba(4,10,12,.7);padding:4px 8px;border-radius:8px}
.fz-side{display:flex;flex-direction:column;gap:10px;min-width:0;overflow-y:auto}
.fz-card{border:1px solid rgba(255,160,60,.35);border-radius:14px;padding:10px 12px;background:rgba(4, 10, 8,.7)}
.fz-ct{font-size:11px;letter-spacing:.18em;color:#ffa03c;margin-bottom:6px}
.fz-big{font-size:30px;font-weight:700;color:#9fe1cb;font-variant-numeric:tabular-nums}
.fz-mut{font-size:13px;color:#a0d9c6;line-height:1.35}
.fz-row{display:flex;justify-content:space-between;gap:10px;font-size:13px;color:#8ab9a9;margin-top:4px}
.fz-row b{color:#b4ffe5;font-weight:600;text-align:right;font-variant-numeric:tabular-nums}
.fz-bar{height:8px;border-radius:999px;background:#142a21;overflow:hidden;margin:2px 0 4px}
.fz-bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#1d9e75,#9fe1cb);border-radius:999px;transition:width .6s}
.fz-bar i.low{background:linear-gradient(90deg,#ff5a3c,#ff9a5a)}
.fz-plan{margin-top:8px;font-size:12.5px;color:#6effcd;line-height:1.4}
@media (max-width:900px){#pv-fahrt .fz{grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(260px,1fr) auto}}`;
  document.head.appendChild(css);

  let zoom = 1, data = null, autoDone = false, seenStart = 0;
  sec.querySelectorAll(".fz-zoom span").forEach((b) => b.addEventListener("click", () => { zoom = Math.max(.35, Math.min(4, zoom * (b.dataset.z > 0 ? 1.5 : 1 / 1.5))); draw(); }));
  const hm = (m) => m > 0 ? (m >= 60 ? Math.floor(m / 60) + " h " + (m % 60) + " min" : m + " min") : "–";

  function draw() {
    const c = $("fz-c"); if (!c || !data || !data.aktiv) return;
    const dpr = Math.min(2, devicePixelRatio || 1), W = c.clientWidth, H = c.clientHeight;
    if (!W || !H) return;
    if (c.width !== Math.round(W * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
    const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const f = data.faktor || 19, sc = Math.min(W, H) / 2 / (60000 / f / zoom);   // Pixel pro Weltmeter (60 Spiel-km Radius bei Zoom 1)
    const cx = W / 2, cy = H / 2, P = (x, z) => [cx + x * sc, cy + z * sc];
    // Raster
    g.strokeStyle = "rgba(60,200,255,.06)"; g.lineWidth = 1;
    const step = 20000 / f * sc; for (let x = cx % step; x < W; x += step) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
    for (let y = cy % step; y < H; y += step) { g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
    // Ringe 5/10/20 km
    g.setLineDash([3, 6]); g.strokeStyle = "rgba(90, 255, 198,.18)";
    g.fillStyle = "rgba(90, 255, 198,.45)"; g.font = "10px system-ui"; g.textAlign = "left";
    [20, 40, 60, 120].forEach((km) => { const r = km * 1000 / f * sc; if (r > Math.max(W, H)) return; g.beginPath(); g.arc(cx, cy, r, 0, 7); g.stroke(); g.fillText(km + " km", cx + r * .71 + 3, cy - r * .71 - 3); });
    g.setLineDash([]);
    // Ziel-Richtung
    if (data.dest) {
      const [dx, dz] = [data.dest[1], data.dest[2]], d = Math.hypot(dx, dz);
      if (d > 1) {
        const inside = d * sc < Math.min(W, H) / 2 - 20, [tx, ty] = inside ? P(dx, dz) : [cx + dx / d * (Math.min(W, H) / 2 - 24), cy + dz / d * (Math.min(W, H) / 2 - 24)];
        g.strokeStyle = "rgba(110,255,205,.35)"; g.setLineDash([8, 8]); g.beginPath(); g.moveTo(cx, cy); g.lineTo(tx, ty); g.stroke(); g.setLineDash([]);
        g.fillStyle = "#6effcd"; g.font = "600 12px system-ui"; g.textAlign = "center"; g.fillText("Ziel: " + data.dest[0] + (inside ? "" : " →"), tx, ty - 10);
      }
    }
    // Städte
    g.font = "600 12px system-ui"; g.textAlign = "center";
    (data.cities || []).forEach(([n, x, z]) => { const [px, py] = P(x, z); if (px < -50 || py < -20 || px > W + 50 || py > H + 20) return;
      g.fillStyle = "rgba(200,230,245,.55)"; g.beginPath(); g.arc(px, py, 3, 0, 7); g.fill(); g.fillStyle = "rgba(200,230,245,.75)"; g.fillText(n, px, py - 7); });
    // Tankstellen / Rastplätze
    (data.pois || []).forEach(([a, x, z]) => { const [px, py] = P(x, z); if (px < -10 || py < -10 || px > W + 10 || py > H + 10) return;
      if (a === "t") { g.fillStyle = "#1d9e75"; g.font = "13px system-ui"; g.fillText("⛽", px, py + 4); }
      else { g.fillStyle = "rgba(60,200,255,.85)"; g.font = "700 11px system-ui"; g.fillText("P", px, py + 4); } });
    // Tankstopp
    const pl = data.plan || {};
    if (pl.x != null && data.me) { const [px, py] = P(pl.x - data.me[0], pl.z - data.me[1]);
      g.strokeStyle = "#6effcd"; g.lineWidth = 2; g.beginPath(); g.moveTo(px, py - 10); g.lineTo(px + 10, py); g.lineTo(px, py + 10); g.lineTo(px - 10, py); g.closePath(); g.stroke(); }
    // Spur
    const tr = data.trail || []; if (tr.length > 1) { g.strokeStyle = "rgba(159, 225, 203,.5)"; g.lineWidth = 2.5; g.beginPath(); tr.forEach(([x, z], i) => { const [px, py] = P(x, z); i ? g.lineTo(px, py) : g.moveTo(px, py); }); g.stroke(); }
    // Truck
    const h = data.h || [0, -1], ang = Math.atan2(h[1], h[0]);
    g.save(); g.translate(cx, cy); g.rotate(ang + Math.PI / 2);
    g.shadowColor = "#1d9e75"; g.shadowBlur = 14; g.fillStyle = "#9fe1cb";
    g.beginPath(); g.moveTo(0, -13); g.lineTo(9, 10); g.lineTo(0, 5); g.lineTo(-9, 10); g.closePath(); g.fill(); g.restore();
  }

  function side(e, m) {
    $("fz-head").textContent = "FAHRT · " + (e.spiel || "ETS2") + (e.pause ? " · PAUSE" : "");
    $("fz-kmh").textContent = (e.kmh || 0) + " km/h" + (e.limit ? "  ·  max " + e.limit : "");
    $("fz-hier").textContent = (m && m.hier ? "bei " + m.hier + " · " : "") + (e.lkw || "");
    $("fz-tank").textContent = `${e.tank_pct} % · ${e.tank_l} l · ${e.reichweite_km} km`;
    const b = $("fz-tankbar"); b.style.width = Math.max(2, Math.min(100, e.tank_pct || 0)) + "%"; b.classList.toggle("low", (e.tank_pct || 0) <= 15);
    const near = (n) => n ? `${n.km} km${n.way ? ", " + n.way : ""}${n.bei ? " · " + n.bei : ""}` : "–";
    $("fz-nt").textContent = near(m && m.tank); $("fz-ns").textContent = near(m && m.schlaf);
    $("fz-plan").textContent = (m && m.plan && m.plan.text) || "";
    $("fz-job").textContent = e.ladung ? `${e.ladung}${e.masse_t ? " (" + e.masse_t + " t)" : ""}: ${e.von} → ${e.nach}${e.nach_firma ? " · " + e.nach_firma : ""}` : "Kein Auftrag";
    $("fz-ziel").textContent = e.rest_km ? `${e.rest_km} km · ${hm(e.rest_min)}` : "–";
    $("fz-lohn").textContent = e.lohn ? e.lohn.toLocaleString("de-DE") + " €" : "–";
    $("fz-ruhe").textContent = hm(e.ruhe_min);
  }

  function poll() {
    let e = {}; try { e = window.PC.get("ets2") || {}; } catch (x) {}
    tab.style.display = e.aktiv ? "" : "none";
    if (!e.aktiv) { autoDone = false; if (window.JHudCur && window.JHudCur() === "fahrt") window.JHudMode("info", false); return; }
    if (e.start && e.start !== seenStart) { seenStart = e.start; autoDone = false; }
    if (!autoDone && window.JHudMode) { autoDone = true; window.JHudMode("fahrt", false); }   // Spiel gestartet: einmal hinspringen
    if (window.JHudCur && window.JHudCur() !== "fahrt") return;
    let m = null; try { m = window.PC.get("ets2_map"); } catch (x) {}
    data = m; side(e, m); draw();
  }
  setInterval(poll, 2000); setTimeout(poll, 800);
  addEventListener("resize", draw);
  window.JFahrt = { poll, _set: (e, m) => { data = m; side(e, m); draw(); } };
})();
