// Der Jarvis-Strang: ein großes, durchgehendes Leiterbahn-Bild hinter allen Seiten. Beim Wischen wandert es mit,
// wie ein Panorama. Lichtimpulse laufen ständig daran entlang; redet Jarvis, werden es mehr und sie werden schneller.
//   const s = new Strand(canvas, pages); s.offset = seite + wischanteil; s.level = 0..1; s.power = true/false; s.draw(dt)
(function () {
  function rnd(seed) { let s = seed; return () => (s = (s * 16807) % 2147483647) / 2147483647; }

  class Strand {
    constructor(canvas, pages) {
      this.c = canvas; this.g = canvas.getContext("2d"); this.pages = pages || 4;
      this.offset = 0; this.level = 0; this.power = true; this.pw = 1; this.t = 0; this.W = 0;
      this.pulses = [];
    }
    // Aufbau der Bahnen in Seiten-Koordinaten (x: 0..pages, y: 0..1 der Höhe)
    build(W, H) {
      const r = rnd(42), P = this.pages, paths = [];
      // Hauptstrang: wandert über alle Seiten, macht 45°-Knicke und geht hinter den Kugeln durch
      const key = [[-.3, .29], [.72, .29], [.82, .2], [1.66, .2], [1.8, .42], [2.2, .42], [2.36, .1], [3.72, .1], [3.86, .3], [4.3, .3]];
      const main = key.map(([x, y]) => [x * W, y * H]);
      for (let k = -2; k <= 2; k++) {   // mehrere parallele Leitungen = ein "Bündel"
        const off = k * 7 * (W / 400);
        paths.push({ pts: main.map(([x, y], i) => [x, y + off]), w: k === 0 ? 1.3 : .7, a: k === 0 ? .5 : .28 - Math.abs(k) * .06, main: true });
      }
      // Abzweige vom Bündel weg, mit Lötpunkt am Ende
      for (let i = 0; i < 30; i++) {
        const seg = (r() * (main.length - 1)) | 0, f = r();
        const [x0, y0] = main[seg], [x1, y1] = main[seg + 1];
        let x = x0 + (x1 - x0) * f, y = y0 + (y1 - y0) * f;
        const up = r() < .5 ? -1 : 1, pts = [[x, y]], n = 2 + (r() * 2 | 0), y0b = y;
        for (let j = 0; j < n; j++) {
          const len = (20 + r() * 60) * (W / 400);
          if (j % 2 === 0) { x += len * (r() < .5 ? .7 : 1) * (r() < .5 ? 1 : -1); y += len * .7 * up; }
          else x += len * (r() < .5 ? 1 : -1);
          y = Math.max(y0b - H * .1, Math.min(y0b + H * .1, y)); pts.push([x, y]);
        }
        paths.push({ pts, w: .6, a: .14 + r() * .14, dot: true });
      }
      // Kreise um die Kugeln (Fokus: groß, Info: mittel, Steuern: klein) – der Strang "speist" sie
      const rings = [[.5, .29, .41], [1.5, .2, .3], [3.5, .1, .17]].map(([x, y, rad]) => ({ x: x * W, y: y * H, r: rad * W }));
      this.paths = paths; this.rings = rings;
      // Länge je Pfad für die Lichtimpulse
      for (const p of paths) { let L = 0; p.cum = [0]; for (let i = 1; i < p.pts.length; i++) { L += Math.hypot(p.pts[i][0] - p.pts[i - 1][0], p.pts[i][1] - p.pts[i - 1][1]); p.cum.push(L); } p.len = L; }
      // Statisches Bild einmal vorzeichnen (spart Akku)
      const off = document.createElement("canvas"); off.width = Math.ceil(W * P); off.height = H;
      const g = off.getContext("2d"); g.lineCap = "round"; g.lineJoin = "round";
      const stroke = (p, col, wmul, blur) => { g.beginPath(); p.pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y));
        g.strokeStyle = col; g.lineWidth = p.w * wmul * (W / 400); g.shadowBlur = blur; g.shadowColor = "rgba(255,150,30,.9)"; g.stroke(); };
      for (const p of paths) stroke(p, `rgba(255,150,40,${p.a * .18})`, 3, 6 * (W / 400));
      for (const p of paths) stroke(p, `rgba(255,190,90,${p.a * .7})`, 1, 0);
      g.shadowBlur = 0;
      for (const p of paths) if (p.dot) { const [x, y] = p.pts[p.pts.length - 1];
        g.beginPath(); g.arc(x, y, 3 * (W / 400), 0, 7); g.strokeStyle = `rgba(255,200,110,${p.a + .2})`; g.lineWidth = 1.2 * (W / 400); g.stroke(); }
      for (const R of rings) for (let k = 0; k < 3; k++) {
        g.beginPath(); g.setLineDash(k === 1 ? [4 * (W / 400), 6 * (W / 400)] : []);
        g.arc(R.x, R.y, R.r * (1 + k * .06), 0, 7); g.strokeStyle = `rgba(255,170,60,${.14 - k * .04})`; g.lineWidth = (k ? 1 : 1.6) * (W / 400); g.stroke();
      }
      g.setLineDash([]);
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
      g.globalAlpha = .55 + .3 * this.pw;
      g.filter = this.pw < .99 ? `grayscale(${1 - this.pw})` : "none";
      g.drawImage(this.img, ox, 0, W, H, 0, 0, W, H);
      g.filter = "none"; g.globalAlpha = 1;
      // fließender Datenstrom: feine Strichel wandern ganz langsam die Hauptleitungen entlang
      g.save(); g.lineCap = "round";
      g.setLineDash([1.5 * (W / 400), 13 * (W / 400)]); g.lineDashOffset = -this.t * (18 + busy * 60) * (W / 400);
      g.strokeStyle = this.pw > .5 ? "rgba(255,215,150,.38)" : "rgba(200,205,215,.25)"; g.lineWidth = 1.6 * (W / 400);
      for (const p of this.paths) { if (!p.main) continue; g.beginPath(); p.pts.forEach(([x, y], i) => i ? g.lineTo(x - ox, y) : g.moveTo(x - ox, y)); g.stroke(); }
      g.restore();
      // Lichtimpulse
      const rate = (.35 + busy * 4) * (.15 + .85 * this.pw);
      if (Math.random() < rate * dt * 6) {
        const mains = this.paths.filter((p) => p.main || Math.random() < .15);
        const p = mains[(Math.random() * mains.length) | 0];
        this.pulses.push({ p, d: 0, v: (260 + Math.random() * 300) * (W / 400) * (1 + busy * 1.5) });
      }
      g.globalCompositeOperation = "lighter";
      for (const q of this.pulses) {
        q.d += q.v * dt;
        const [x, y] = this.at(q.p, q.d), sx = x - ox;
        if (sx < -60 || sx > W + 60) continue;
        const rad = 11 * (W / 400);
        const grd = g.createRadialGradient(sx, y, 0, sx, y, rad);
        const c = this.pw > .5 ? "255,210,130" : "200,205,215";
        grd.addColorStop(0, `rgba(${c},.6)`); grd.addColorStop(.3, `rgba(${c},.18)`); grd.addColorStop(1, `rgba(${c},0)`);
        g.fillStyle = grd; g.fillRect(sx - rad, y - rad, rad * 2, rad * 2);
        // kurzer Schweif
        const [tx, ty] = this.at(q.p, Math.max(0, q.d - 60 * (W / 400)));
        g.strokeStyle = `rgba(${c},.32)`; g.lineWidth = 1.2 * (W / 400); g.beginPath(); g.moveTo(tx - ox, ty); g.lineTo(sx, y); g.stroke();
      }
      g.globalCompositeOperation = "source-over";
      this.pulses = this.pulses.filter((q) => q.d < q.p.len);
    }
  }
  window.Strand = Strand;
})();
