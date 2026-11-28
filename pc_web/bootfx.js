// Vector-Start (PC-HUD und App) – mehrstufige HUD-Choreografie:
//   Phase 1 Hex-Gitter   – Sechseck-Raster blendet von der Mitte nach außen gestaffelt ein (Hintergrundtextur)
//   Phase 2 Doppel-Ring  – zwei konzentrische Ringe drehen sich gegenläufig
//   Phase 3 Er selbst    – seine echte Kugel (Sphere3D) wächst in der Mitte auf, der Kern zündet
//   Phase 4 Text-Reveal  – "VECTOR" baut sich buchstabenweise auf, darunter wofür der Name steht
//   Phase 5 Infos        – Uhrzeit, Datum, Wetter, Skills fliegen einzeln ein und rasten in eine Reihe
// Dazwischen läuft wie bisher der echte Systemcheck (grüne/rote Punkte) und am Ende fliegen die Ringe in die Kugel.
// Klick oder Esc überspringt. Einstiegspunkt bleibt unverändert:  JBoot.play()
(function () {
  const A = window.Android || null;
  const VC = window.VectorColors || {   // Fallback, falls sphere3d.js aus irgendeinem Grund noch nicht geladen ist
    tealLight: "#9FE1CB", tealMid: "#1D9E75", tealDark: "#085041", tealDarkest: "#04342C",
    blueLight: "#85B7EB", blueMid: "#378ADD", blueDark: "#0C447C", alarm: "#EF9F27",
  };
  // Hex->"r,g,b" für Canvas-rgba()-Strings
  function rgb(hex) { const n = parseInt(hex.slice(1), 16); return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`; }
  const RGB = { tealLight: rgb(VC.tealLight), tealMid: rgb(VC.tealMid), tealDark: rgb(VC.tealDark), blueMid: rgb(VC.blueMid) };

  const css = document.createElement("style");
  css.textContent = `
  #bootfx{position:fixed;inset:0;z-index:200;background:#000;transition:opacity .9s ease;overflow:hidden;font-family:"Segoe UI",system-ui,sans-serif}
  #bootfx.out{opacity:0;pointer-events:none}
  #bootfx canvas.bg{position:absolute;inset:0;width:100%;height:100%}
  #bootfx canvas.him{position:absolute;transform:translate(-50%,-50%);opacity:0;transition:opacity .8s ease}
  #bootfx canvas.him.v{opacity:1}
  #bootfx .rings{position:absolute;transform:translate(-50%,-50%);pointer-events:none;transition:all .9s cubic-bezier(.5,0,.3,1)}
  #bootfx .ring{position:absolute;border-radius:50%;opacity:0;transform:scale(.2)}
  #bootfx.rg .ring{animation:bfin 1s forwards, bfspin var(--sp) linear infinite}
  /* Doppel-Ring (Phase 2): r1 = innerer Ring, gestrichelt, dreht sich schneller im Uhrzeigersinn;
     r2 = äußerer Ring, durchgehend, dreht sich langsamer gegen den Uhrzeigersinn. r3/r4 sind dezente Zusatzringe. */
  #bootfx .r1{inset:-6%;border:1px dashed rgba(${RGB.tealLight},.6);--sp:9s}
  #bootfx .r2{inset:-16%;border:2px solid rgba(${RGB.tealMid},.18);border-top-color:rgba(${RGB.tealLight},.9);border-bottom-color:rgba(${RGB.tealLight},.5);--sp:22s;animation-direction:normal,reverse!important}
  #bootfx .r3{inset:-27%;border:1px dotted rgba(${RGB.blueMid},.45);--sp:40s}
  #bootfx .r4{inset:-36%;border:1px solid rgba(${RGB.tealMid},.12);border-left-color:rgba(${RGB.tealLight},.6);--sp:13s;animation-direction:normal,reverse!important}
  #bootfx.rg .r2{animation-delay:.15s,0s}#bootfx.rg .r3{animation-delay:.3s,0s}#bootfx.rg .r4{animation-delay:.45s,0s}
  @keyframes bfin{to{opacity:1;transform:scale(1)}}
  @keyframes bfspin{to{rotate:360deg}}
  #bootfx .rings.away{opacity:0;transform:translate(-50%,-50%) scale(.35)}
  #bootfx .bt{position:absolute;left:0;right:0;text-align:center}
  #bootfx .title{font-size:min(4.6vh,7vw);letter-spacing:.55em;font-weight:600;color:${VC.tealLight};text-shadow:0 0 22px rgba(${RGB.tealMid},.7);padding-left:.55em}
  #bootfx .title span{display:inline-block;opacity:0;transform:translateY(10px) scale(.9);filter:blur(4px);transition:all .35s cubic-bezier(.2,1.4,.4,1)}
  #bootfx .title span.v{opacity:1;transform:none;filter:none}
  #bootfx .sub{font-size:min(1.9vh,3vw);letter-spacing:.32em;color:#5ab7a0;opacity:0;transition:opacity .6s}
  #bootfx .sub.v{opacity:1}
  /* wofür der Name steht – Anfangsbuchstaben hell, Rest gedämpft */
  #bootfx .mean{font:600 min(1.45vh,2.4vw)/1 Consolas,monospace;letter-spacing:.3em;color:${VC.tealMid};opacity:0;transition:opacity .7s}
  #bootfx .mean.v{opacity:1}
  #bootfx .mean b{color:${VC.tealLight};font-weight:700}
  #bootfx .sys{position:absolute;font-size:min(1.8vh,3.2vw)}
  #bootfx .sys h4{margin:0 0 8px;font-size:.78em;letter-spacing:.3em;color:${VC.blueLight};font-weight:700;opacity:0;transition:opacity .5s}
  #bootfx .sys h4.v{opacity:1}
  #bootfx .row{display:flex;align-items:center;gap:10px;padding:4px 0;border-bottom:1px solid rgba(${RGB.tealMid},.12);opacity:0;transform:translateX(26px);transition:opacity .3s,transform .3s}
  #bootfx .row.v{opacity:1;transform:none}
  #bootfx .row i{flex:0 0 9px;height:9px;border-radius:50%;background:#2e4a44;transition:background .3s,box-shadow .3s}
  #bootfx .row.g i{background:#6effcd;box-shadow:0 0 10px #6effcd}#bootfx .row.r i{background:${VC.alarm};box-shadow:0 0 10px ${VC.alarm}}
  #bootfx .row b{font-weight:600;color:#cdeedf;flex:1}#bootfx .row small{color:${VC.blueLight};font-size:.85em}
  #bootfx .log{position:absolute;left:4vw;top:16vh;font:min(1.5vh,1.1vw)/1.7 Consolas,monospace;color:rgba(${RGB.blueMid},.75);white-space:pre}
  #bootfx .skip{position:absolute;right:16px;bottom:12px;font-size:11px;color:#2a4a42;letter-spacing:.1em}
  /* Infos fliegen aus dem Bild herein und rasten unten in eine Reihe ein */
  #bootfx .rail{position:absolute;left:50%;bottom:7%;transform:translateX(-50%);display:flex;gap:min(1.2vw,14px)}
  #bootfx .inf{min-width:min(13vw,150px);padding:8px 12px 9px;border-radius:10px;background:rgba(6,20,17,.86);
    border:1px solid rgba(${RGB.tealMid},.4);border-left:2px solid var(--akzent,${VC.tealLight});
    opacity:0;transform:translate(var(--fx,0),var(--fy,-60px)) scale(.6);
    transition:opacity .25s ease,transform .7s cubic-bezier(.16,.9,.25,1)}
  #bootfx .inf.v{opacity:1;transform:none}
  #bootfx .inf small{display:block;font:700 9px Consolas,monospace;letter-spacing:.18em;color:${VC.blueLight}}
  #bootfx .inf b{display:block;margin-top:3px;font-size:min(2.3vh,4.2vw);font-weight:600;color:${VC.tealLight}}
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

  // ---------- Phase 1: Hex-Gitter ------------------------------------------------------------------------------
  // Baut ein axiales Hex-Raster über den ganzen Bildschirm und merkt sich für jede Zelle ihren Abstand zur Mitte,
  // damit sie beim Zeichnen gestaffelt von innen nach außen einblenden kann (näher = früher sichtbar).
  function buildHexGrid(W, H, C) {
    const cells = []; const hs = Math.max(26, Math.min(W, H) / 22);
    for (let yy = -hs; yy < H + hs; yy += hs * .866) for (let xx = -hs; xx < W + hs; xx += hs * 1.5) {
      const ox = (Math.round(yy / (hs * .866)) % 2) * hs * .75, px = xx + ox;
      cells.push({ x: px, y: yy, dd: Math.hypot(px - C.x, yy - C.y) });
    }
    return { cells, hs, maxD: Math.hypot(W, H) };
  }
  function drawHexGrid(g, grid, t, narrow) {
    const front = t * grid.maxD * .55;
    g.lineWidth = 1;
    for (const h of grid.cells) {
      if (h.dd > front) continue;
      const age = (front - h.dd) / grid.maxD, al = (Math.max(0, .12 - age * .3) + (h.dd > front - 26 ? .22 : 0)) * (narrow ? .7 : 1);
      if (al <= .01) continue;
      g.strokeStyle = `rgba(${RGB.tealMid},${al * (t > 3.6 ? Math.max(0, 1 - (t - 3.6)) : 1)})`;
      g.beginPath(); for (let k = 0; k < 6; k++) { const an = k * Math.PI / 3; const px = h.x + Math.cos(an) * grid.hs * .48, py = h.y + Math.sin(an) * grid.hs * .48; k ? g.lineTo(px, py) : g.moveTo(px, py); } g.closePath(); g.stroke();
    }
  }

  // ---------- aufsteigende Energiepunkte, ziehen sich zur Kugel zusammen (Übergang in Phase 2/3) ---------------
  function buildEnergyParticles(W, H, C) {
    const N = Math.round(Math.min(900, W * H / 1800));
    return Array.from({ length: N }, () => ({ x: Math.random() * W, y: H + Math.random() * H * .6, vy: -(1.2 + Math.random() * 2.4), s: .6 + Math.random() * 1.6,
      a: Math.random() * 6.28, rr: C.r * (.25 + Math.random() * .8), delay: .15 + Math.random() * .7 }));
  }
  function drawEnergyParticles(g, P, C, t, dt) {
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
      g.fillStyle = `rgba(${150 + p.s * 10},${220 + p.s * 10},${190 + p.s * 10},${al * .9})`; g.beginPath(); g.arc(p.x, p.y, p.s, 0, 7); g.fill();
    }
    g.globalCompositeOperation = "source-over";
  }

  // ---------- Phase 3: Kern-Puls + Strahlen-Ausbruch -----------------------------------------------------------
  // Ab t>2s: ein heller Lichtblitz läuft über den Schirm, in der Mitte bleibt ein pulsierender Kern stehen
  // ("Aufwachen"), von außen schießen kurze Teal/Blau-Leitungen auf den Kern zu (Strahlen-Ausbruch nach innen/außen).
  function drawCorePulse(g, box, rg, C, now, flashStart) {
    const k = (now - flashStart) / 1000;
    const gr = g.createRadialGradient(C.x, C.y, 0, C.x, C.y, C.r * (.7 + k * 1.1));
    gr.addColorStop(0, `rgba(210,245,230,${Math.max(0, .7 - k * .9)})`); gr.addColorStop(.4, `rgba(${RGB.tealMid},${Math.max(0, .28 - k * .4)})`); gr.addColorStop(1, "rgba(8,80,65,0)");
    g.fillStyle = gr; g.fillRect(0, 0, g.canvas.width, g.canvas.height);
    // Kern bleibt als pulsierende Teal-Kugel stehen (Übergang zur echten Kugel)
    const pr = C.r * (.42 + .04 * Math.sin(k * 5)) * Math.min(1, k * 2.5);
    const cg = g.createRadialGradient(C.x, C.y - pr * .2, pr * .1, C.x, C.y, pr);
    cg.addColorStop(0, "rgba(159,225,203,.55)"); cg.addColorStop(.6, `rgba(${RGB.tealMid},.22)`); cg.addColorStop(1, "rgba(8,80,65,0)");
    g.fillStyle = cg; g.beginPath(); g.arc(C.x, C.y, pr, 0, 7); g.fill();
    g.strokeStyle = `rgba(159,225,203,${.5 * Math.min(1, k * 2)})`; g.lineWidth = 1.2; g.beginPath(); g.arc(C.x, C.y, pr * .92, 0, 7); g.stroke();
    // kurzer Ring-Flash, der einmalig vom Kern nach außen ausläuft (Glanz-Ausbruch)
    if (k < 1.1) {
      const fr = C.r * .25 + k * C.r * 2.1, fa = Math.max(0, .55 - k * .55);
      g.strokeStyle = `rgba(159,225,203,${fa})`; g.lineWidth = 2.5 * Math.max(0, 1 - k); g.beginPath(); g.arc(C.x, C.y, fr, 0, 7); g.stroke();
    }
    // Teal/Blau-Leitungen von außen zur Kugel
    for (let i = 0; i < 14; i++) { const an = i / 14 * 6.283 + k * .3, r0 = Math.max(g.canvas.width, g.canvas.height) * .6, u = (k * .9 + i * .07) % 1;
      const x0 = C.x + Math.cos(an) * r0, y0 = C.y + Math.sin(an) * r0, x = x0 + (C.x - x0) * u, y = y0 + (C.y - y0) * u;
      g.strokeStyle = `rgba(${RGB.blueMid},${.12 * Math.max(0, 1 - k / 3)})`; g.beginPath(); g.moveTo(x0, y0); g.lineTo(C.x, C.y); g.stroke();
      g.fillStyle = `rgba(159,225,203,${.8 * Math.max(0, 1 - k / 3)})`; g.beginPath(); g.arc(x, y, 1.8, 0, 7); g.fill(); }
  }

  // ---------- Phase 4: Text-Reveal -----------------------------------------------------------------------------
  // "VECTOR" liegt schon als <span> pro Buchstabe im DOM; hier nur noch gestaffelt einblenden (Fade+Blur+Versatz).
  function revealTitle(title, startDelay) {
    [...title.children].forEach((sp, i) => setTimeout(() => sp.classList.add("v"), startDelay + i * 70));
  }

  // ---------- Phase 5: Infos fliegen einzeln ein und rasten in eine Reihe --------------------------------------
  // Jede Kachel kommt aus einer anderen Richtung aus dem Bild geflogen und bremst in ihre Position ab.
  // Welche Infos einfliegen, steht in den Einstellungen (Anzeige -> Infos beim Start).
  // Gespeichert als Liste: bekannte Kennungen ("uhrzeit") oder eigene Einträge {l:"ÜBERSCHRIFT", v:"Text"}.
  const BOOT_INFOS = "vector_boot_infos";
  function infoWerte() {
    const now = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return {
      uhrzeit:   ["UHRZEIT", p(now.getHours()) + ":" + p(now.getMinutes())],
      datum:     ["DATUM", now.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })],
      wochentag: ["TAG", now.toLocaleDateString("de-DE", { weekday: "long" })],
      skills:    ["SKILLS", String((window.JarvisBrain && window.JarvisBrain.learned && window.JarvisBrain.learned.length) || 0)],
      status:    ["STATUS", "BEREIT"],
      kalenderwoche: ["WOCHE", "KW " + Math.ceil((((now - new Date(now.getFullYear(), 0, 1)) / 86400000) + 1) / 7)],
    };
  }
  function infoListe(narrow) {
    const werte = infoWerte();
    let wahl = null;
    try { wahl = JSON.parse(localStorage.getItem(BOOT_INFOS) || "null"); } catch (e) {}
    if (!Array.isArray(wahl) || !wahl.length) wahl = ["uhrzeit", "datum", "skills", "status"];
    const out = [];
    wahl.forEach((e) => {
      if (typeof e === "string") { if (werte[e]) out.push(werte[e]); return; }
      if (e && e.l) out.push([String(e.l).toUpperCase(), String(e.v == null ? "" : e.v)]);
    });
    return out.slice(0, narrow ? 2 : 4);
  }
  function launchInfoRow(box, startDelay, narrow) {
    const rail = document.createElement("div"); rail.className = "rail";
    const use = infoListe(narrow);
    if (!use.length) return rail;
    use.forEach((d, i) => {
      const el = document.createElement("div"); el.className = "inf";
      el.innerHTML = "<small></small><b></b>";
      el.querySelector("small").textContent = d[0]; el.querySelector("b").textContent = d[1];
      const side = i % 4;      // aus allen vier Richtungen herein
      el.style.setProperty("--fx", side === 0 ? "-60vw" : side === 1 ? "60vw" : (i % 2 ? "22vw" : "-22vw"));
      el.style.setProperty("--fy", side === 2 ? "-60vh" : side === 3 ? "60vh" : "-20vh");
      rail.appendChild(el);
      setTimeout(() => el.classList.add("v"), startDelay + i * 170);
    });
    box.appendChild(rail);
    return rail;
  }

  function play() {
    if (api.running) return; api.running = true;
    const narrow = innerWidth < 700;
    const box = document.createElement("div"); box.id = "bootfx";
    box.innerHTML = '<canvas class="bg"></canvas><canvas class="him"></canvas>' +
      '<div class="rings"><div class="ring r1"></div><div class="ring r2"></div><div class="ring r3"></div><div class="ring r4"></div></div>' +
      '<div class="bt title"></div><div class="bt sub">PERSÖNLICHER ASSISTENT · ONLINE</div>' +
      '<div class="bt mean"></div>' + (narrow ? "" : '<div class="log"></div>') +
      '<div class="sys"><h4>SYSTEMSTATUS</h4><div class="rows"></div></div><div class="skip">Tippen = überspringen</div>';
    document.body.appendChild(box);
    const cv = box.querySelector("canvas"), g = cv.getContext("2d"), d = Math.min(2, devicePixelRatio || 1);
    const W = innerWidth, H = innerHeight; cv.width = W * d; cv.height = H * d; g.setTransform(d, 0, 0, d, 0, 0);
    const C = sphereCenter();
    // Ringe um die Kugel, Titel darunter, Status rechts (PC) bzw. unten (Handy)
    const rg = box.querySelector(".rings"); Object.assign(rg.style, { left: C.x + "px", top: C.y + "px", width: C.r * 1.5 + "px", height: C.r * 1.5 + "px" });
    // Er selbst: dieselbe Kugel wie im HUD, mitten in der Animation
    const himCv = box.querySelector("canvas.him"), himS = Math.round(C.r * 3.1);
    Object.assign(himCv.style, { left: C.x + "px", top: C.y + "px", width: himS + "px", height: himS + "px" });
    let him = null;
    try { him = new Sphere3D(himCv, 3); him.state = "thinking"; him.power = true; him.level = .25; } catch (e) {}
    const ty = Math.min(H - 150, C.y + C.r * 1.25);
    box.querySelector(".title").style.top = ty + "px"; box.querySelector(".sub").style.top = (ty + Math.min(H * .06, 44)) + "px";
    const sys = box.querySelector(".sys");
    if (narrow) Object.assign(sys.style, { left: "8vw", right: "8vw", top: (ty + 80) + "px" }); else Object.assign(sys.style, { right: "4vw", top: "16vh", width: "min(28vw,400px)" });

    // Phase 1 + aufsteigende Partikel vorbereiten
    const grid = buildHexGrid(W, H, C);
    const P = buildEnergyParticles(W, H, C);
    // Phase 4 vorbereiten: Buchstaben-Spans anlegen (Einblenden erfolgt zeitversetzt weiter unten)
    const T = "V.E.C.T.O.R."; const title = box.querySelector(".title"); title.innerHTML = [...T].map((c) => `<span>${c}</span>`).join("");
    const meanEl = box.querySelector(".mean");
    meanEl.innerHTML = ["Very", "Efficient", "Companion", "That", "Organizes", "Reality"]
      .map((w) => `<b>${w[0]}</b>${w.slice(1).toUpperCase()}`).join(" ");
    meanEl.style.top = (ty + Math.min(H * .105, 76)) + "px";

    const t0 = performance.now(); let flash = 0, done = false, last = t0;
    const logEl = box.querySelector(".log");
    if (logEl) ["> Kern wird geladen …", "> Gedächtnis synchronisiert", "> Sprachmodul „Vector“", "> Neuronales Netz online", "> Gelernte Skills: " + ((window.JarvisBrain && JarvisBrain.learned.length) || 0), "> Oberfläche wird aufgebaut …"]
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
      drawHexGrid(g, grid, t, narrow);                 // Phase 1
      drawEnergyParticles(g, P, C, t, dt);              // Zulauf zum Kern (Übergang zu Phase 2/3)
      if (t > 2.0 && !flash) { flash = now; box.classList.add("rg"); himCv.classList.add("v"); }   // Phase 2/3: Ringe + er selbst
      if (flash) drawCorePulse(g, box, rg, C, now, flash);                // Zündung (dezent, die Kugel macht den Rest)
      if (him) { him.state = t > 4.2 ? "idle" : "thinking"; him.level = Math.max(0, .45 - Math.abs(t - 2.6) * .25);
                 try { him.draw(dt); } catch (e) {} }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    revealTitle(title, 2150);                                          // Phase 4
    setTimeout(() => box.querySelector(".sub").classList.add("v"), 2900);
    setTimeout(() => meanEl.classList.add("v"), 3250);                 // wofür der Name steht
    const rail = launchInfoRow(box, 3200, narrow);                     // Phase 5: Infos fliegen ein

    const finish = () => {
      if (done) return; done = true;
      rg.classList.add("away");   // Ringe fliegen in die Kugel
      setTimeout(() => box.classList.add("out"), 250);
      if (rail) { rail.style.transition = "opacity .4s"; rail.style.opacity = "0"; }   // Info-Reihe mit abräumen
      const top = document.querySelector(".top, .view.active .topbar"); if (top) { top.classList.remove("bootin-top"); void top.offsetWidth; top.classList.add("bootin-top"); }
      const parts = [...document.querySelectorAll(
        document.body.classList.contains("jw-on") ? "#jbrett .jw, #typebar, .tabs"
                                                  : ".pv.on > *, #typebar, .view.active > *, .tabs")]
        .filter((e) => e.offsetParent !== null);
      parts.forEach((e, i) => { e.style.animationDelay = (.25 + i * .06) + "s"; e.classList.remove("bootin"); void e.offsetWidth; e.classList.add("bootin");
        setTimeout(() => { e.classList.remove("bootin"); e.style.animationDelay = ""; }, 1700 + i * 60); });
      if (!A) try { fetch("/api/boot_done", { method: "POST", body: JSON.stringify({ bad: box.querySelectorAll(".row.r").length }) }); } catch (e) {}
      setTimeout(() => { box.remove(); api.running = false; api.pending = false; }, 1200);
      removeEventListener("keydown", key);
    };
    const key = (e) => { if (e.key === "Escape" || e.key === " " || e.key === "Enter") finish(); };
    addEventListener("keydown", key); box.addEventListener("click", finish);
    setTimeout(finish, 6800);
  }
  api.play = play;
  window.JBoot = api;
  // Baustein 1 "Hochfahren": gleicher Aufruf, nur unter dem Bausteine-Namen, falls von dort gerufen.
  if (window.VectorFX) window.VectorFX.playBootSequence = play;
  if (A) {   // App: bei jedem Start (abschaltbar unter Einstellungen → Anzeige)
    let on = true; try { on = localStorage.getItem("boot_anim") !== "0"; } catch (e) {}
    if (on) { api.pending = true; setTimeout(play, 60); }
  } else {   // PC: Server sagt einmal "boot", sonst auf Zuruf/Test
    try { fetch("/api/boot_pending").then((r) => r.json()).then((dd) => { if (dd && dd.boot) play(); }).catch(() => {}); } catch (e) {}
    try { const es = new EventSource("/events"); es.onmessage = (e) => { try { if (JSON.parse(e.data).type === "boot") play(); } catch (x) {} }; } catch (e) {}
  }
})();
