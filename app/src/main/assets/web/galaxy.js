// Hinter dem Globus: Sternenhimmel und ganz weit hinten ein goldener Nervenstrang wie ein Band durch die Galaxie.
// Dreht man den Globus, wandert der Hintergrund langsam mit (Parallaxe). Läuft nur, wenn die Lage-Seite sichtbar ist.
(function () {
  const page = document.getElementById("v-lage"), mapEl = document.getElementById("lmap");
  if (!page || !mapEl) return;
  const cv = document.createElement("canvas");
  cv.id = "lgal"; cv.style.cssText = "position:absolute;inset:0;width:100%;height:100%;z-index:-1;pointer-events:none";
  page.style.isolation = "isolate";   // eigene Ebene: Sterne liegen über dem schwarzen Hintergrund, aber unter Globus und Karten
  page.insertBefore(cv, page.firstChild);
  const g = cv.getContext("2d");
  let W = 0, H = 0, d = 1, stars = [], fibers = [], t = 0, last = performance.now();
  function rnd(seed) { let s = seed; return () => (s = (s * 16807) % 2147483647) / 2147483647; }
  function build() {
    d = Math.min(2, devicePixelRatio || 1); W = cv.clientWidth; H = cv.clientHeight;
    if (!W || !H) return;
    cv.width = W * d; cv.height = H * d; g.setTransform(d, 0, 0, d, 0, 0);
    const r = rnd(7);
    stars = Array.from({ length: Math.round(W * H / 2600) }, () => ({ x: r() * 2, y: r(), s: r() * 1.2 + .2, a: .25 + r() * .6, tw: r() * 6 }));
    // Band: weite S-Kurve quer durchs Bild (in Breite 2 W, damit es beim Drehen weiterläuft), viele feine Fasern
    fibers = Array.from({ length: 9 }, (_, k) => ({ off: (k - 4) * 9 + (r() - .5) * 6, ph: r() * 6, w: k === 4 ? 1.6 : .5 + r() * .8, a: k === 4 ? .5 : .12 + r() * .2, sp: .3 + r() * .5 }));
  }
  function bandY(u, f) {   // u: 0..2 (zwei Bildbreiten), Mittellinie des Bandes
    return H * (.78 - .55 * u / 2) + Math.sin(u * 3.1 + 1.2) * H * .09 + Math.sin(u * 7 + f.ph + t * f.sp * .2) * 6 + f.off;
  }
  function frame(now) {
    const dt = Math.min(.1, (now - last) / 1000); last = now;
    requestAnimationFrame(frame);
    if (!page.offsetParent && getComputedStyle(page).display === "none") return;   // Seite nicht sichtbar
    if (cv.clientWidth !== W || cv.clientHeight !== H) build();
    if (!W) return;
    t += dt;
    let lon = 0;
    try { const m = window.JLage && window.JLage.map ? window.JLage.map() : null; if (m) lon = m.getCenter().lng + m.getBearing(); } catch (e) {}
    const shift = ((lon / 360) % 1 + 1) % 1;   // 0..1 – eine volle Umdrehung = eine Bildbreite
    g.clearRect(0, 0, W, H);
    // Nebel hinter dem Band
    const neb = g.createLinearGradient(0, H * .9, W, H * .1);
    neb.addColorStop(0, "rgba(20,10,2,0)"); neb.addColorStop(.5, "rgba(60,32,6,.18)"); neb.addColorStop(1, "rgba(20,10,2,0)");
    g.fillStyle = neb; g.fillRect(0, 0, W, H);
    // Sterne (langsamer als das Band -> Tiefe)
    for (const s of stars) {
      let x = ((s.x - shift * .5) % 2 + 2) % 2 * W; if (x > W) continue;
      const a = s.a * (.7 + .3 * Math.sin(t * 1.3 + s.tw));
      g.fillStyle = `rgba(255,${230 - s.s * 20},${200 - s.s * 40},${a})`; g.fillRect(x, s.y * H, s.s, s.s);
    }
    // goldenes Band (Nervenstrang ganz weit hinten)
    g.globalCompositeOperation = "lighter"; g.lineCap = "round";
    for (const f of fibers) {
      g.beginPath();
      for (let x = -10; x <= W + 10; x += 8) { const u = ((x / W + shift) % 2 + 2) % 2; const y = bandY(u, f); x === -10 ? g.moveTo(x, y) : g.lineTo(x, y); }
      g.strokeStyle = `rgba(255,190,90,${f.a * .35})`; g.lineWidth = f.w * 5; g.stroke();
      g.strokeStyle = `rgba(255,214,140,${f.a})`; g.lineWidth = f.w; g.stroke();
    }
    // Lichtimpulse entlang des Bandes
    for (let i = 0; i < 6; i++) {
      const x = ((t * 40 * (1 + i * .15) + i * 230) % (W + 200)) - 100, u = ((x / W + shift) % 2 + 2) % 2, y = bandY(u, fibers[4] || { off: 0, ph: 0, sp: 0 });
      const gr = g.createRadialGradient(x, y, 0, x, y, 10); gr.addColorStop(0, "rgba(255,240,200,.8)"); gr.addColorStop(1, "rgba(255,190,90,0)");
      g.fillStyle = gr; g.fillRect(x - 10, y - 10, 20, 20);
    }
    g.globalCompositeOperation = "source-over";
  }
  requestAnimationFrame(frame);
})();
