// Der Jarvis-Strang: ein großes, durchgehendes Leiterbahn-Bild hinter allen Seiten. Beim Wischen wandert es mit,
// wie ein Panorama. Lichtimpulse laufen ständig daran entlang; redet Jarvis, werden es mehr und sie werden schneller.
//   const s = new Strand(canvas, pages); s.offset = seite + wischanteil; s.level = 0..1; s.power = true/false; s.draw(dt)
(function () {
  function rnd(seed) { let s = seed; return () => (s = (s * 16807) % 2147483647) / 2147483647; }

  class Strand {
    constructor(canvas, pages, opts) {
      this.opts = opts || {};
      this.c = canvas; this.g = canvas.getContext("2d"); this.pages = pages || 4;
      this.offset = 0; this.level = 0; this.power = true; this.pw = 1; this.t = 0; this.W = 0;
      this.pulses = []; this.grabs = []; this.flow = 0;
      this.target = null;   // () => {x, y, r} der Kugel auf dem Bildschirm (CSS-Pixel)
    }
    /** Jarvis greift nach einer Quelle (videos, musik, web, kalender, lage, wetter): Ranke wächst hin, holt das Symbol in die Kugel. */
    reach(kind) {
      const ANG = { videos: -40, musik: 20, web: -140, kalender: 160, lage: -95, wetter: -10 };
      const LBL = { videos: "VIDEOS", musik: "MUSIK", web: "WEB", kalender: "KALENDER", lage: "LAGE", wetter: "WETTER" };
      this.grabs.push({ kind, a: (ANG[kind] ?? -40) * Math.PI / 180, label: LBL[kind] || kind.toUpperCase(), t: 0, seed: Math.random() * 10 });
    }
    icon(g, kind, x, y, s, a) {   // eigene Symbole im Jarvis-Gold (keine Firmenlogos)
      g.save(); g.translate(x, y); g.globalAlpha = a; g.strokeStyle = "#ffd678"; g.fillStyle = "#ffd678"; g.lineWidth = s * .09; g.lineJoin = "round"; g.lineCap = "round";
      if (kind === "videos") { g.beginPath(); g.arc(0, 0, s * .5, 0, 7); g.stroke(); g.beginPath(); g.moveTo(-s * .14, -s * .22); g.lineTo(s * .26, 0); g.lineTo(-s * .14, s * .22); g.closePath(); g.fill(); }
      else if (kind === "musik") { g.beginPath(); g.moveTo(-s * .18, s * .25); g.lineTo(-s * .18, -s * .32); g.lineTo(s * .3, -s * .42); g.lineTo(s * .3, s * .15); g.stroke();
        g.beginPath(); g.ellipse(-s * .28, s * .27, s * .13, s * .1, -.4, 0, 7); g.fill(); g.beginPath(); g.ellipse(s * .2, s * .17, s * .13, s * .1, -.4, 0, 7); g.fill(); }
      else if (kind === "web") { g.beginPath(); g.arc(0, 0, s * .45, 0, 7); g.stroke(); g.beginPath(); g.ellipse(0, 0, s * .18, s * .45, 0, 0, 7); g.stroke();
        g.beginPath(); g.moveTo(-s * .45, 0); g.lineTo(s * .45, 0); g.moveTo(-s * .38, -s * .22); g.lineTo(s * .38, -s * .22); g.moveTo(-s * .38, s * .22); g.lineTo(s * .38, s * .22); g.stroke(); }
      else if (kind === "kalender") { g.strokeRect(-s * .4, -s * .32, s * .8, s * .72); g.beginPath(); g.moveTo(-s * .4, -s * .1); g.lineTo(s * .4, -s * .1); g.moveTo(-s * .2, -s * .44); g.lineTo(-s * .2, -s * .24); g.moveTo(s * .2, -s * .44); g.lineTo(s * .2, -s * .24); g.stroke();
        for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) g.fillRect(-s * .28 + i * s * .22, s * .02 + j * s * .16, s * .1, s * .08); }
      else { g.beginPath(); g.arc(0, 0, s * .42, 0, 7); g.stroke(); g.beginPath(); g.moveTo(0, -s * .55); g.lineTo(0, s * .55); g.moveTo(-s * .55, 0); g.lineTo(s * .55, 0); g.stroke(); g.beginPath(); g.arc(0, 0, s * .1, 0, 7); g.fill(); }
      g.restore();
    }
    grab(g, gr, dt, W, H) {
      gr.t += dt;
      const T = this.target ? this.target() : null; if (!T) return;
      const d = Math.min(2, window.devicePixelRatio || 1), cx = T.x * d, cy = T.y * d, R = T.r * d;
      const t = gr.t, ease = (x) => x < 0 ? 0 : x > 1 ? 1 : 1 - Math.pow(1 - x, 3);
      // Ziel: außerhalb der Kugel, aber im Bild
      const dist = R * 1.32, nx = Math.max(40 * d, Math.min(W - 40 * d, cx + Math.cos(gr.a) * dist)), ny = Math.max(60 * d, cy + Math.sin(gr.a) * dist);
      const sx = cx + Math.cos(gr.a) * R * .62, sy = cy + Math.sin(gr.a) * R * .62;   // Ansatz am Kugelrand
      const grow = ease(t / .55), back = ease((t - 1.35) / .8);                        // Ranke wächst hin / zieht sich mit der Beute zurück
      const tip = (u) => { // Punkt auf der Ranke (u 0..1), leicht geschwungen
        const mx = (sx + nx) / 2 + Math.sin(gr.a) * R * .18 * Math.sin(gr.seed), my = (sy + ny) / 2 - Math.cos(gr.a) * R * .18 * Math.sin(gr.seed);
        const k = 1 - u; return [k * k * sx + 2 * k * u * mx + u * u * nx, k * k * sy + 2 * k * u * my + u * u * ny]; };
      const end = Math.max(0, grow - back);   // wie weit die Ranke gerade reicht
      g.save(); g.globalCompositeOperation = "lighter"; g.lineCap = "round";
      if (end > 0) {
        for (const [w, a] of [[6, .12], [2.4, .5], [1, .95]]) {
          g.beginPath(); for (let u = 0; u <= end + 1e-3; u += .04) { const [x, y] = tip(Math.min(u, end)); u === 0 ? g.moveTo(x, y) : g.lineTo(x, y); }
          g.strokeStyle = `rgba(255,200,110,${a})`; g.lineWidth = w * d; g.stroke();
        }
        // Datenfunken laufen die Ranke entlang
        for (let k = 0; k < 3; k++) { const u = ((t * 1.6 + k / 3) % 1) * end; const [x, y] = tip(u);
          const gg = g.createRadialGradient(x, y, 0, x, y, 7 * d); gg.addColorStop(0, "rgba(255,240,200,.9)"); gg.addColorStop(1, "rgba(255,200,110,0)"); g.fillStyle = gg; g.fillRect(x - 7 * d, y - 7 * d, 14 * d, 14 * d); }
      }
      // Symbol: erscheint an der Spitze, wird gepackt, fliegt mit der Ranke in die Kugel und schrumpft
      const appear = ease((t - .3) / .4), [ix, iy] = t < 1.35 ? [nx, ny] : tip(Math.max(0, 1 - back));
      const fly = Math.max(0, Math.min(1, (t - 1.35) / .8)), size = (30 * d) * (1 - .75 * fly) * (t < 1.35 ? (1 + .12 * Math.sin(Math.max(0, t - .9) * 18) * (t > .9 ? 1 : 0)) : 1);
      const alpha = appear * (t > 2.15 ? 0 : 1);
      if (alpha > 0) {
        const halo = g.createRadialGradient(ix, iy, 0, ix, iy, size * 1.4); halo.addColorStop(0, `rgba(255,180,60,${.35 * alpha})`); halo.addColorStop(1, "rgba(255,150,30,0)");
        g.fillStyle = halo; g.fillRect(ix - size * 1.4, iy - size * 1.4, size * 2.8, size * 2.8);
        g.beginPath(); g.arc(ix, iy, size * .78, 0, 7); g.strokeStyle = `rgba(255,210,120,${.7 * alpha})`; g.lineWidth = 1.4 * d; g.stroke();
        if (t > .9 && t < 1.35) { g.beginPath(); g.arc(ix, iy, size * (0.78 + (t - .9) * .8), 0, 7); g.strokeStyle = `rgba(255,230,170,${.6 * (1 - (t - .9) / .45)})`; g.stroke(); }
        g.globalCompositeOperation = "source-over";
        g.fillStyle = `rgba(20,12,2,${.75 * alpha})`; g.beginPath(); g.arc(ix, iy, size * .74, 0, 7); g.fill();
        this.icon(g, gr.kind, ix, iy, size * .9, alpha);
        if (fly < .3) { g.font = `700 ${9 * d}px monospace`; g.textAlign = "center"; g.fillStyle = `rgba(255,214,140,${alpha * (1 - fly / .3)})`; g.fillText(gr.label, ix, iy + size * 1.15); }
        g.globalCompositeOperation = "lighter";
      }
      // Ankunft: Lichtring in der Kugel
      if (t > 2.1 && t < 2.8) { const k = (t - 2.1) / .7; g.beginPath(); g.arc(cx, cy, R * (.25 + .5 * k), 0, 7);
        g.strokeStyle = `rgba(255,220,150,${.7 * (1 - k)})`; g.lineWidth = (4 - 3 * k) * d; g.stroke(); }
      g.restore();
    }
    // Aufbau der Bahnen in Seiten-Koordinaten (x: 0..pages, y: 0..1 der Höhe)
    build(W, H) {
      this.sc = this.opts.S ? this.opts.S(W, H) : W / 400;
      const r = rnd(42), P = this.pages, paths = [], S = this.sc;
      // Nervenbahn: weiche Kurve über alle Seiten, geht hinter den Kugeln durch (Fokus, Info, Lage, Steuern)
      const key = (this.opts.key || [[-.3, .34], [.15, .31], [.5, .29], [.85, .24], [1.2, .17], [1.5, .2], [1.8, .3], [2.15, .42], [2.5, .22], [2.85, .12], [3.2, .1], [3.5, .1], [3.8, .2], [4.3, .3]])
        .map(([x, y]) => [x * W, y * H]);
      const spline = [];   // Catmull-Rom: schöne runde Kurve durch die Punkte
      for (let i = 0; i < key.length - 1; i++) {
        const p0 = key[Math.max(0, i - 1)], p1 = key[i], p2 = key[i + 1], p3 = key[Math.min(key.length - 1, i + 2)];
        const n = Math.ceil(Math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / (6 * S));
        for (let j = 0; j < n; j++) { const t = j / n, t2 = t * t, t3 = t2 * t;
          spline.push([.5 * (2 * p1[0] + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
                       .5 * (2 * p1[1] + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)]); }
      }
      // drei Fasern, die sich umeinander winden (wie ein Nervenstrang)
      for (let k = 0; k < 3; k++) {
        const pts = spline.map(([x, y], i) => {
          const a = spline[Math.min(i + 1, spline.length - 1)], b2 = spline[Math.max(i - 1, 0)], dx = a[0] - b2[0], dy = a[1] - b2[1], L = Math.hypot(dx, dy) || 1;
          const o = Math.sin(i * .045 + k * 2.094) * 7 * S;
          return [x - dy / L * o, y + dx / L * o];
        });
        paths.push({ pts, w: k === 0 ? 1.4 : 1, a: k === 0 ? .55 : .38, main: true });
      }
      // Dendriten: verzweigte Ausläufer mit Nervenzellen (Punkten) am Ende
      const twig = (x, y, ang, len, depth, a) => {
        const pts = [[x, y]]; let cx = x, cy = y, an = ang; const n = 7, curl = (r() - .5) * .5;
        for (let j = 0; j < n; j++) { an += curl + (r() - .5) * .25; cx += Math.cos(an) * len / n; cy += Math.sin(an) * len / n; pts.push([cx, cy]); }
        paths.push({ pts, w: .9 - depth * .25, a, dot: depth > 0 || r() < .7 });
        if (depth < 2) { const m = 2 + (r() * 3 | 0); for (let q = 0; q < 2; q++) if (r() < .65) { const [bx, by] = pts[m + q * 2] || pts[pts.length - 1];
          twig(bx, by, an + (q ? .7 : -.7) + (r() - .5) * .4, len * (.45 + r() * .2), depth + 1, a * .75); } }
      };
      for (let i = 0; i < (this.opts.twigs || 26); i++) {
        const idx = 10 + (r() * (spline.length - 20) | 0), [x, y] = spline[idx], nx = spline[idx + 1][0] - spline[idx - 1][0], ny = spline[idx + 1][1] - spline[idx - 1][1];
        const side = r() < .5 ? 1 : -1, ang = Math.atan2(ny, nx) + side * (Math.PI / 2 + (r() - .5) * .9);
        twig(x, y, ang, (40 + r() * 90) * S, 0, .22 + r() * .14);
      }
      // feine Ringe um die Kugeln (Fokus, Info, Steuern)
      const rings = (this.opts.rings || [[.5, .29, .41], [1.5, .2, .3], [3.5, .1, .17]]).map(([x, y, rad]) => ({ x: x * W, y: y * H, r: rad * W }));
      // Synapsen: kleine Knoten entlang des Strangs
      this.nodes = []; for (let i = 20; i < spline.length - 20; i += 18 + (r() * 30 | 0)) this.nodes.push(spline[i]);
      this.paths = paths; this.rings = rings;
      // Länge je Pfad für die Lichtimpulse
      for (const p of paths) { let L = 0; p.cum = [0]; for (let i = 1; i < p.pts.length; i++) { L += Math.hypot(p.pts[i][0] - p.pts[i - 1][0], p.pts[i][1] - p.pts[i - 1][1]); p.cum.push(L); } p.len = L; }
      // Statisches Bild einmal vorzeichnen (spart Akku)
      const off = document.createElement("canvas"); off.width = Math.ceil(W * P); off.height = H;
      const g = off.getContext("2d"); g.lineCap = "round"; g.lineJoin = "round";
      const stroke = (p, col, wmul, blur) => { g.beginPath(); p.pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y));
        g.strokeStyle = col; g.lineWidth = p.w * wmul * this.sc; g.shadowBlur = blur; g.shadowColor = "rgba(255,150,30,.9)"; g.stroke(); };
      for (const p of paths) stroke(p, `rgba(255,150,40,${p.a * .18})`, 3, 6 * this.sc);
      for (const p of paths) stroke(p, `rgba(255,190,90,${p.a * .7})`, 1, 0);
      g.shadowBlur = 0;
      for (const p of paths) if (p.dot) { const [x, y] = p.pts[p.pts.length - 1];
        g.beginPath(); g.arc(x, y, 2 * this.sc, 0, 7); g.fillStyle = `rgba(255,205,120,${p.a + .25})`; g.fill(); }
      for (const R of rings) { g.beginPath(); g.arc(R.x, R.y, R.r, 0, 7); g.strokeStyle = "rgba(255,170,60,.08)"; g.lineWidth = 1.2 * this.sc; g.stroke(); }
      for (const [x, y] of this.nodes) { const rr = 9 * this.sc, gg = g.createRadialGradient(x, y, 0, x, y, rr);
        gg.addColorStop(0, "rgba(255,225,160,.75)"); gg.addColorStop(.25, "rgba(255,180,80,.3)"); gg.addColorStop(1, "rgba(255,150,40,0)");
        g.fillStyle = gg; g.fillRect(x - rr, y - rr, rr * 2, rr * 2); }
      this.img = off;
    }
    at(p, d) { let i = 1; while (i < p.cum.length - 1 && p.cum[i] < d) i++;
      const f = (d - p.cum[i - 1]) / Math.max(1e-6, p.cum[i] - p.cum[i - 1]), a = p.pts[i - 1], b = p.pts[i];
      return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]; }
    draw(dt) {
      const dpr = Math.min(2, window.devicePixelRatio || 1), W = Math.round(this.c.clientWidth * dpr), H = Math.round(this.c.clientHeight * dpr);
      if (!W || !H) return;
      if (W !== this.W || H !== this.H) { this.c.width = this.W = W; this.c.height = this.H = H; this.build(W, H); }
      this.t += dt;
      this.pw += ((this.power ? 1 : 0) - this.pw) * Math.min(1, dt * 3);
      const g = this.g, ox = this.offset * W, busy = this.level;
      g.clearRect(0, 0, W, H);
      // aus: grau, dunkel, steht still · an: leuchtet und atmet leicht
      g.globalAlpha = .28 + .62 * this.pw * (.9 + .1 * Math.sin(this.t * 1.3));
      g.filter = this.pw < .99 ? `grayscale(${1 - this.pw})` : "none";
      g.drawImage(this.img, ox, 0, W, H, 0, 0, W, H);
      if (this.pw > .05) { g.globalAlpha = .35 * this.pw; g.globalCompositeOperation = "lighter"; g.filter = `blur(${4 * this.sc}px)`;
        g.drawImage(this.img, ox, 0, W, H, 0, 0, W, H); g.globalCompositeOperation = "source-over"; }
      g.filter = "none"; g.globalAlpha = 1;
      this.flow += dt * this.pw * (18 + busy * 60);
      // Lichtimpulse
      const rate = this.power ? (.6 + busy * 4) : 0;
      if (Math.random() < rate * dt * 6) {
        const mains = this.paths.filter((p) => p.main || Math.random() < .15);
        const p = mains[(Math.random() * mains.length) | 0];
        const back = Math.random() < .45;   // Daten fließen hin und her
        this.pulses.push({ p, d: back ? p.len : 0, v: (back ? -1 : 1) * (260 + Math.random() * 300) * this.sc * (1 + busy * 1.5) });
      }
      g.globalCompositeOperation = "lighter";
      for (const q of this.pulses) {
        q.d += q.v * dt;
        const [x, y] = this.at(q.p, q.d), sx = x - ox;
        if (sx < -60 || sx > W + 60) continue;
        const rad = 11 * this.sc;
        const grd = g.createRadialGradient(sx, y, 0, sx, y, rad);
        const c = this.pw > .5 ? "255,210,130" : "200,205,215";
        grd.addColorStop(0, `rgba(${c},.6)`); grd.addColorStop(.3, `rgba(${c},.18)`); grd.addColorStop(1, `rgba(${c},0)`);
        g.fillStyle = grd; g.fillRect(sx - rad, y - rad, rad * 2, rad * 2);
        // kurzer Schweif
        const [tx, ty] = this.at(q.p, Math.max(0, Math.min(q.p.len, q.d - Math.sign(q.v) * 60 * this.sc)));
        g.strokeStyle = `rgba(${c},.32)`; g.lineWidth = 1.2 * this.sc; g.beginPath(); g.moveTo(tx - ox, ty); g.lineTo(sx, y); g.stroke();
      }
      g.globalCompositeOperation = "source-over";
      this.pulses = this.pulses.filter((q) => q.d < q.p.len && q.d > 0 || (q.v > 0 && q.d === 0));
      this.grabs.forEach((gr) => this.grab(g, gr, dt, W, H));
      this.grabs = this.grabs.filter((gr) => gr.t < 2.8);
    }
  }
  window.Strand = Strand;
})();
