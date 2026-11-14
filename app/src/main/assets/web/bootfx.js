// Iron-Man-Start (PC-HUD und App) – Mischung aus altem und neuem Start:
// Hex-Gitter baut sich von der Mitte auf, goldene Lichtpunkte steigen auf und ziehen sich zur Kugel zusammen, Lichtblitz,
// drehende Hologramm-Ringe, "J.A.R.V.I.S." baut sich auf, Systemstatus tickt Punkt für Punkt ein (grüne/rote Punkte),
// dann fliegen die Ringe in die Kugel und die Oberfläche baut sich Stück für Stück auf. Klick oder Esc überspringt.
//   JBoot.play()   – auch per Test-Knopf / "Friday, Startanimation"
(function () {
  const A = window.Android || null;
  const css = document.createElement("style");
  css.textContent = `
  #bootfx{position:fixed;inset:0;z-index:200;background:#000;transition:opacity .9s ease;overflow:hidden;font-family:"Segoe UI",system-ui,sans-serif}
  #bootfx.out{opacity:0;pointer-events:none}
  #bootfx canvas.bg{position:absolute;inset:0;width:100%;height:100%}
  #bootfx .rings{position:absolute;transform:translate(-50%,-50%);pointer-events:none;transition:all .9s cubic-bezier(.5,0,.3,1)}
  #bootfx .ring{position:absolute;border-radius:50%;opacity:0;transform:scale(.2)}
  #bootfx.rg .ring{animation:bfin 1s forwards, bfspin var(--sp) linear infinite}
  #bootfx .r1{inset:-6%;border:1px dashed rgba(255,190,90,.55);--sp:26s}
  #bootfx .r2{inset:-16%;border:2px solid rgba(255,170,40,.15);border-top-color:rgba(255,214,120,.9);border-bottom-color:rgba(255,214,120,.5);--sp:7s;animation-direction:normal,reverse!important}
  #bootfx .r3{inset:-27%;border:1px dotted rgba(60,200,255,.4);--sp:40s}
  #bootfx .r4{inset:-36%;border:1px solid rgba(255,170,40,.1);border-left-color:rgba(255,214,120,.6);--sp:13s}
  #bootfx.rg .r2{animation-delay:.15s,0s}#bootfx.rg .r3{animation-delay:.3s,0s}#bootfx.rg .r4{animation-delay:.45s,0s}
  @keyframes bfin{to{opacity:1;transform:scale(1)}}
  @keyframes bfspin{to{rotate:360deg}}
  #bootfx .rings.away{opacity:0;transform:translate(-50%,-50%) scale(.35)}
  #bootfx .bt{position:absolute;left:0;right:0;text-align:center}
  #bootfx .title{font-size:min(4.6vh,7vw);letter-spacing:.55em;font-weight:600;color:#ffd678;text-shadow:0 0 22px rgba(255,170,40,.7);padding-left:.55em}
  #bootfx .title span{display:inline-block;opacity:0;transform:translateY(10px) scale(.9);filter:blur(4px);transition:all .35s cubic-bezier(.2,1.4,.4,1)}
  #bootfx .title span.v{opacity:1;transform:none;filter:none}
  #bootfx .sub{font-size:min(1.9vh,3vw);letter-spacing:.32em;color:#c8965a;opacity:0;transition:opacity .6s}
  #bootfx .sub.v{opacity:1}
  #bootfx .sys{position:absolute;font-size:min(1.8vh,3.2vw)}
  #bootfx .sys h4{margin:0 0 8px;font-size:.78em;letter-spacing:.3em;color:#c8965a;font-weight:700;opacity:0;transition:opacity .5s}
  #bootfx .sys h4.v{opacity:1}
  #bootfx .row{display:flex;align-items:center;gap:10px;padding:4px 0;border-bottom:1px solid rgba(255,170,40,.1);opacity:0;transform:translateX(26px);transition:opacity .3s,transform .3s}
  #bootfx .row.v{opacity:1;transform:none}
  #bootfx .row i{flex:0 0 9px;height:9px;border-radius:50%;background:#554a30;transition:background .3s,box-shadow .3s}
  #bootfx .row.g i{background:#6effcd;box-shadow:0 0 10px #6effcd}#bootfx .row.r i{background:#ff6a4a;box-shadow:0 0 10px #ff6a4a}
  #bootfx .row b{font-weight:600;color:#ffe1b4;flex:1}#bootfx .row small{color:#78a0b4;font-size:.85em}
  #bootfx .log{position:absolute;left:4vw;top:16vh;font:min(1.5vh,1.1vw)/1.7 Consolas,monospace;color:rgba(110,200,255,.7);white-space:pre}
  #bootfx .skip{position:absolute;right:16px;bottom:12px;font-size:11px;color:#4a3a20;letter-spacing:.1em}
  .bootin{animation:bootin .7s cubic-bezier(.2,.9,.3,1) both}
  @keyframes bootin{from{opacity:0;transform:translateY(18px) scale(.98);filter:blur(3px)}to{opacity:1;transform:none;filter:none}}
  .bootin-top{animation:bootintop .6s cubic-bezier(.2,.9,.3,1) both}
  @keyframes bootintop{from{opacity:0;transform:translateY(-46px)}to{opacity:1;transform:none}}`;
  document.head.appendChild(css);

  const api = { running: false };
  function sphereCenter() {
    for (const sel of ["#f-sph", "#sphere-fokus", ".pv.on .sph", ".view.active .sphere-wrap"]) {
      const s = document.querySelector(sel);
      if (s) { const r = s.getBoundingClientRect(); if (r.width > 20) return { x: r.left + r.width / 2, y: r.top + r.height / 2, r: r.width / 2 }; }
    }
    return { x: innerWidth / 2, y: innerHeight * .42, r: Math.min(innerWidth, innerHeight) * .22 };
  }
  async function status() {
    try {
      if (A && A.sysCheck) return (JSON.parse(A.sysCheck(false)).items || []);
      const r = await fetch("/api/syscheck"); return ((await r.json()).items || []);
    } catch (e) { return []; }
  }

  function play() {
    if (api.running) return; api.running = true;
    const narrow = innerWidth < 700;
    const box = document.createElement("div"); box.id = "bootfx";
    box.innerHTML = '<canvas class="bg"></canvas><div class="rings"><div class="ring r1"></div><div class="ring r2"></div><div class="ring r3"></div><div class="ring r4"></div></div>' +
      '<div class="bt title"></div><div class="bt sub">PERSÖNLICHER ASSISTENT · ONLINE</div>' + (narrow ? "" : '<div class="log"></div>') +
      '<div class="sys"><h4>SYSTEMSTATUS</h4><div class="rows"></div></div><div class="skip">Tippen = überspringen</div>';
    document.body.appendChild(box);
    const cv = box.querySelector("canvas"), g = cv.getContext("2d"), d = Math.min(2, devicePixelRatio || 1);
    const W = innerWidth, H = innerHeight; cv.width = W * d; cv.height = H * d; g.setTransform(d, 0, 0, d, 0, 0);
    const C = sphereCenter();
    // Ringe um die Kugel, Titel darunter, Status rechts (PC) bzw. unten (Handy)
    const rg = box.querySelector(".rings"); Object.assign(rg.style, { left: C.x + "px", top: C.y + "px", width: C.r * 1.5 + "px", height: C.r * 1.5 + "px" });
    const ty = Math.min(H - 150, C.y + C.r * 1.25);
    box.querySelector(".title").style.top = ty + "px"; box.querySelector(".sub").style.top = (ty + Math.min(H * .06, 44)) + "px";
    const sys = box.querySelector(".sys");
    if (narrow) Object.assign(sys.style, { left: "8vw", right: "8vw", top: (ty + 80) + "px" }); else Object.assign(sys.style, { right: "4vw", top: "16vh", width: "min(28vw,400px)" });
    // Lichtpunkte
    const N = Math.round(Math.min(900, W * H / 1800));
    const P = Array.from({ length: N }, () => ({ x: Math.random() * W, y: H + Math.random() * H * .6, vy: -(1.2 + Math.random() * 2.4), s: .6 + Math.random() * 1.6,
      a: Math.random() * 6.28, rr: C.r * (.25 + Math.random() * .8), delay: .15 + Math.random() * .7 }));
    // Hex-Gitter (alt): Zellen leuchten von der Mitte nach außen auf
    const hx = []; const hs = Math.max(26, Math.min(W, H) / 22);
    for (let yy = -hs; yy < H + hs; yy += hs * .866) for (let xx = -hs; xx < W + hs; xx += hs * 1.5) {
      const ox = (Math.round(yy / (hs * .866)) % 2) * hs * .75, px = xx + ox;
      hx.push({ x: px, y: yy, dd: Math.hypot(px - C.x, yy - C.y) });
    }
    const maxD = Math.hypot(W, H);
    const T = "J.A.R.V.I.S."; const title = box.querySelector(".title"); title.innerHTML = [...T].map((c) => `<span>${c}</span>`).join("");
    const t0 = performance.now(); let flash = 0, done = false, last = t0;
    const logEl = box.querySelector(".log");
    if (logEl) ["> Kern wird geladen …", "> Gedächtnis synchronisiert", "> Sprachmodul „Friday“", "> Neuronales Netz online", "> Gelernte Skills: " + ((window.JarvisBrain && JarvisBrain.learned.length) || 0), "> Oberfläche wird aufgebaut …"]
      .forEach((l, i) => setTimeout(() => { logEl.textContent += l + "\n"; }, 250 + i * 320));
    // Systemstatus: Punkte laufen durch (erst grau, dann grün/rot)
    status().then((items) => {
      items = items.filter((i) => i.ok !== null).slice(0, narrow ? 5 : 9);
      if (!items.length) items = [{ name: "Kern", ok: true }, { name: "Gedächtnis", ok: true }, { name: "Sprache", ok: true }];
      const rows = sys.querySelector(".rows");
      setTimeout(() => sys.querySelector("h4").classList.add("v"), 1100);
      items.forEach((it, k) => setTimeout(() => {
        const e = document.createElement("div"); e.className = "row";
        e.innerHTML = `<i></i><b></b><small>prüfe …</small>`; e.querySelector("b").textContent = it.name;
        rows.appendChild(e); requestAnimationFrame(() => e.classList.add("v"));
        setTimeout(() => { e.classList.add(it.ok ? "g" : "r"); e.querySelector("small").textContent = it.ok ? "OK" : "prüfen"; }, 260);
      }, 1250 + k * (narrow ? 200 : 150)));
    });
    function frame(now) {
      if (done) return;
      const t = (now - t0) / 1000, dt = Math.min(.05, (now - last) / 1000); last = now;
      g.fillStyle = "rgba(0,0,0,.28)"; g.fillRect(0, 0, W, H);
      // Hex-Gitter
      const front = t * maxD * .55;
      g.lineWidth = 1;
      for (const h of hx) {
        if (h.dd > front) continue;
        const age = (front - h.dd) / maxD, al = Math.max(0, .22 - age * .35) + (h.dd > front - 30 ? .35 : 0);
        if (al <= .01) continue;
        g.strokeStyle = `rgba(255,170,40,${al * (t > 3.6 ? Math.max(0, 1 - (t - 3.6)) : 1)})`;
        g.beginPath(); for (let k = 0; k < 6; k++) { const an = k * Math.PI / 3; const px = h.x + Math.cos(an) * hs * .48, py = h.y + Math.sin(an) * hs * .48; k ? g.lineTo(px, py) : g.moveTo(px, py); } g.closePath(); g.stroke();
      }
      g.globalCompositeOperation = "lighter";
      const pull = Math.max(0, Math.min(1, (t - .9) / 1.1));
      for (const p of P) {
        if (t < p.delay) continue;
        if (pull < 1) {
          p.vy -= dt * 2.2; p.y += p.vy * 60 * dt * (1 - pull * .6); p.x += Math.sin(t * 2 + p.a) * .4;
          const tx = C.x + Math.cos(p.a + t * 2.4) * p.rr * (1 - pull * .7), ty2 = C.y + Math.sin(p.a + t * 2.4) * p.rr * .55 * (1 - pull * .7);
          p.x += (tx - p.x) * pull * .12; p.y += (ty2 - p.y) * pull * .12;
        } else { p.x = C.x + Math.cos(p.a + t * 2.8) * p.rr * .32; p.y = C.y + Math.sin(p.a + t * 2.8) * p.rr * .2; }
        const al = Math.min(1, (t - p.delay) * 2) * (1 - Math.max(0, t - 2.6) * 1.2);
        if (al <= 0) continue;
        g.fillStyle = `rgba(255,${190 + p.s * 30},${90 + p.s * 40},${al * .9})`; g.beginPath(); g.arc(p.x, p.y, p.s, 0, 7); g.fill();
      }
      if (t > 2.0 && !flash) { flash = now; box.classList.add("rg"); }
      if (flash) {
        const k = (now - flash) / 1000;
        const gr = g.createRadialGradient(C.x, C.y, 0, C.x, C.y, C.r * (1.2 + k * 2));
        gr.addColorStop(0, `rgba(255,240,200,${Math.max(0, .85 - k * .9)})`); gr.addColorStop(.4, `rgba(255,180,60,${Math.max(0, .35 - k * .4)})`); gr.addColorStop(1, "rgba(255,150,30,0)");
        g.fillStyle = gr; g.fillRect(0, 0, W, H);
        // goldene Leitungen von außen zur Kugel (alt)
        for (let i = 0; i < 14; i++) { const an = i / 14 * 6.283 + k * .3, r0 = Math.max(W, H) * .6, u = (k * .9 + i * .07) % 1;
          const x0 = C.x + Math.cos(an) * r0, y0 = C.y + Math.sin(an) * r0, x = x0 + (C.x - x0) * u, y = y0 + (C.y - y0) * u;
          g.strokeStyle = `rgba(255,200,110,${.12 * Math.max(0, 1 - k / 3)})`; g.beginPath(); g.moveTo(x0, y0); g.lineTo(C.x, C.y); g.stroke();
          g.fillStyle = `rgba(255,236,190,${.8 * Math.max(0, 1 - k / 3)})`; g.beginPath(); g.arc(x, y, 1.8, 0, 7); g.fill(); }
      }
      g.globalCompositeOperation = "source-over";
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    [...title.children].forEach((sp, i) => setTimeout(() => sp.classList.add("v"), 2150 + i * 70));
    setTimeout(() => box.querySelector(".sub").classList.add("v"), 2900);
    const finish = () => {
      if (done) return; done = true;
      rg.classList.add("away");   // Ringe fliegen in die Kugel
      setTimeout(() => box.classList.add("out"), 250);
      const top = document.querySelector(".top, .view.active .topbar"); if (top) { top.classList.remove("bootin-top"); void top.offsetWidth; top.classList.add("bootin-top"); }
      const parts = [...document.querySelectorAll(".pv.on > *, #typebar, .view.active > *, .tabs")].filter((e) => e.offsetParent !== null);
      parts.forEach((e, i) => { e.style.animationDelay = (.25 + i * .06) + "s"; e.classList.remove("bootin"); void e.offsetWidth; e.classList.add("bootin");
        setTimeout(() => { e.classList.remove("bootin"); e.style.animationDelay = ""; }, 1700 + i * 60); });
      if (!A) try { fetch("/api/boot_done", { method: "POST", body: JSON.stringify({ bad: box.querySelectorAll(".row.r").length }) }); } catch (e) {}
      setTimeout(() => { box.remove(); api.running = false; api.pending = false; }, 1200);
      removeEventListener("keydown", key);
    };
    const key = (e) => { if (e.key === "Escape" || e.key === " " || e.key === "Enter") finish(); };
    addEventListener("keydown", key); box.addEventListener("click", finish);
    setTimeout(finish, 4900);
  }
  api.play = play;
  window.JBoot = api;
  if (A) {   // App: bei jedem Start (abschaltbar unter Einstellungen → Anzeige)
    let on = true; try { on = localStorage.getItem("boot_anim") !== "0"; } catch (e) {}
    if (on) { api.pending = true; setTimeout(play, 60); }
  } else {   // PC: Server sagt einmal "boot", sonst auf Zuruf/Test
    try { fetch("/api/boot_pending").then((r) => r.json()).then((dd) => { if (dd && dd.boot) play(); }).catch(() => {}); } catch (e) {}
    try { const es = new EventSource("/events"); es.onmessage = (e) => { try { if (JSON.parse(e.data).type === "boot") play(); } catch (x) {} }; } catch (e) {}
  }
})();
