// Goldene Daten-Kugel (wie am PC) und Hologramm-Globus – gezeichnet auf <canvas>, atmet mit der Stimme.
(function () {
  const GOLD = [255, 170, 40], HOT = [255, 214, 120], CORE = [255, 240, 200];
  function rnd(seed) { let s = seed; return () => (s = (s * 16807) % 2147483647) / 2147483647; }

  function makeDesign(seed) {
    const r = rnd(seed), lines = [], dots = [], arcs = [];
    for (let k = 0; k < 22; k++) {          // Datenstränge auf der Kugel
      const lat = (r() - .5) * 150, lon0 = r() * 360, len = 20 + r() * 70, rad = .78 + r() * .2;
      const pts = [];
      for (let i = 0; i <= 14; i++) pts.push([lat + Math.sin(i / 2) * 3 * r(), lon0 + len * i / 14, rad]);
      lines.push({ pts, bright: r() < .35 });
    }
    for (let k = 0; k < 420; k++) dots.push([(Math.asin(r() * 2 - 1)) * 180 / Math.PI, r() * 360, .6 + r() * .4]);
    for (let k = 0; k < 4; k++) {           // große Ringe
      const segs = []; let a = r() * 360;
      for (let j = 0; j < 3; j++) { segs.push([a, a + 30 + r() * 60]); a += 120; }
      arcs.push({ tilt: (r() - .5) * 140, segs, rad: .9 + r() * .2 });
    }
    return { lines, dots, arcs };
  }

  function rot(lat, lon, rx, ry) {
    const la = lat * Math.PI / 180, lo = lon * Math.PI / 180 + ry;
    let x = Math.cos(la) * Math.sin(lo), y = Math.sin(la), z = Math.cos(la) * Math.cos(lo);
    const c = Math.cos(rx), s = Math.sin(rx);
    return [x, y * c - z * s, y * s + z * c];
  }
  const col = (z, rgb, k, a) => {
    const f = (0.08 + 0.92 * Math.pow((z + 1) / 2, 1.7)) * k;
    return `rgba(${Math.min(255, rgb[0] * f) | 0},${Math.min(255, rgb[1] * f) | 0},${Math.min(255, rgb[2] * f) | 0},${a})`;
  };

  class Sphere {
    constructor(canvas, seed) {
      this.c = canvas; this.g = canvas.getContext("2d"); this.d = makeDesign(seed || 7);
      this.t = Math.random() * 10; this.level = 0; this.state = "idle";
    }
    resize() {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = this.c.clientWidth, h = this.c.clientHeight;
      if (!w) return false;
      if (this.c.width !== Math.round(w * dpr) || this.c.height !== Math.round(h * dpr)) { this.c.width = Math.round(w * dpr); this.c.height = Math.round(h * dpr); }
      return true;
    }
    draw(dt) {
      if (!this.resize()) return;
      const g = this.g, W = this.c.width, H = this.c.height, cx = W / 2, cy = H / 2;
      const speed = this.state === "speaking" ? 2.2 : this.state === "listening" ? 1.5 : 1;
      this.t += dt * speed;
      const breathe = 1 + 0.025 * Math.sin(this.t * 1.6) + this.level * 0.07;
      const R = Math.min(W, H) * 0.38 * breathe, rx = 0.35, ry = this.t * 0.35;
      g.clearRect(0, 0, W, H);
      // Halo
      const halo = g.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 1.35);
      halo.addColorStop(0, `rgba(255,150,30,${0.22 + this.level * 0.25})`);
      halo.addColorStop(0.6, "rgba(120,50,0,0.12)"); halo.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = halo; g.fillRect(0, 0, W, H);
      g.globalCompositeOperation = "lighter";
      g.lineCap = "round";
      for (let rep = 0; rep < 3; rep++) {
        const off = rep * 120;
        for (const L of this.d.lines) {
          g.beginPath(); let zs = 0;
          L.pts.forEach((p, i) => {
            const [x, y, z] = rot(p[0], p[1] + off, rx, ry); zs += z;
            const X = cx + x * R * p[2], Y = cy - y * R * p[2];
            i ? g.lineTo(X, Y) : g.moveTo(X, Y);
          });
          const z = zs / L.pts.length;
          g.strokeStyle = col(z, L.bright ? HOT : GOLD, L.bright ? 1.2 : .8, .9);
          g.lineWidth = (L.bright ? 2.2 : 1.2) * (W / 500);
          g.stroke();
        }
      }
      for (const p of this.d.dots) {
        const [x, y, z] = rot(p[0], p[1], rx, ry);
        if (z < -0.2) continue;
        g.fillStyle = col(z, HOT, 1, .9);
        const s = 1.6 * (W / 500);
        g.fillRect(cx + x * R * p[2], cy - y * R * p[2], s, s);
      }
      this.d.arcs.forEach((a, k) => {
        for (const [a0, a1] of a.segs) {
          g.beginPath(); let first = true, zs = 0, n = 0;
          for (let t = a0; t <= a1; t += 4) {
            const [x, y, z] = rot(0, t + this.t * 20, a.tilt * Math.PI / 180, 0.3 * k);
            zs += z; n++;
            const X = cx + x * R * a.rad, Y = cy - y * R * a.rad;
            first ? g.moveTo(X, Y) : g.lineTo(X, Y); first = false;
          }
          g.strokeStyle = col(zs / n, HOT, k < 2 ? 1.1 : .7, .85);
          g.lineWidth = (k < 2 ? 3 : 2) * (W / 500);
          g.stroke();
        }
      });
      // leuchtender Kern
      const core = g.createRadialGradient(cx, cy, 0, cx, cy, R * (0.22 + this.level * 0.1));
      core.addColorStop(0, `rgba(${CORE},1)`); core.addColorStop(0.35, "rgba(255,200,90,0.6)");
      core.addColorStop(1, "rgba(255,140,20,0)");
      g.fillStyle = core; g.beginPath(); g.arc(cx, cy, R * 0.4, 0, Math.PI * 2); g.fill();
      g.globalCompositeOperation = "source-over";
    }
  }

  class Rings {   // drehende cyanfarbene Ringe (Info-Modus)
    constructor(canvas) { this.c = canvas; this.g = canvas.getContext("2d"); this.t = 0; }
    draw(dt) {
      const dpr = Math.min(2, window.devicePixelRatio || 1), w = this.c.clientWidth;
      if (!w) return;
      if (this.c.width !== Math.round(w * dpr)) { this.c.width = this.c.height = Math.round(w * dpr); }
      const g = this.g, W = this.c.width, cx = W / 2;
      this.t += dt; g.clearRect(0, 0, W, W);
      [[0.49, 4, "#3cc8ff", 12], [0.47, 2, "#145a82", -18]].forEach(([r, lw, c, sp]) => {
        g.strokeStyle = c; g.lineWidth = lw * W / 400;
        for (let k = 0; k < 3; k++) {
          const a = (k * 120 + this.t * sp) * Math.PI / 180;
          g.beginPath(); g.arc(cx, cx, W * r, a, a + 70 * Math.PI / 180); g.stroke();
        }
      });
    }
  }

  class Globe {   // goldener Hologramm-Globus (Platzhalter bis Etappe 5)
    constructor(canvas) { this.c = canvas; this.g = canvas.getContext("2d"); this.t = 0; const r = rnd(3);
      this.dots = []; for (let i = 0; i < 1600; i++) this.dots.push([Math.asin(r() * 2 - 1) * 180 / Math.PI, r() * 360]); }
    draw(dt) {
      const dpr = Math.min(2, window.devicePixelRatio || 1), w = this.c.clientWidth;
      if (!w) return;
      if (this.c.width !== Math.round(w * dpr)) { this.c.width = this.c.height = Math.round(w * dpr); }
      const g = this.g, W = this.c.width, c = W / 2, R = W * 0.42, ry = (this.t += dt) * 0.15, rx = 0.45;
      g.clearRect(0, 0, W, W);
      g.lineWidth = W / 700;
      for (let la = -75; la <= 75; la += 15) {
        g.beginPath(); let first = true;
        for (let lo = 0; lo <= 360; lo += 6) {
          const [x, y, z] = rot(la, lo, rx, ry);
          if (z < 0) { first = true; continue; }
          first ? g.moveTo(c + x * R, c - y * R) : g.lineTo(c + x * R, c - y * R); first = false;
        }
        g.strokeStyle = "rgba(255,170,40,0.28)"; g.stroke();
      }
      for (let lo = 0; lo < 360; lo += 15) {
        g.beginPath(); let first = true;
        for (let la = -90; la <= 90; la += 6) {
          const [x, y, z] = rot(la, lo, rx, ry);
          if (z < 0) { first = true; continue; }
          first ? g.moveTo(c + x * R, c - y * R) : g.lineTo(c + x * R, c - y * R); first = false;
        }
        g.strokeStyle = "rgba(255,170,40,0.22)"; g.stroke();
      }
      for (const [la, lo] of this.dots) {
        const [x, y, z] = rot(la, lo, rx, ry);
        if (z < 0) continue;
        g.fillStyle = `rgba(255,214,120,${0.2 + 0.8 * z})`;
        g.fillRect(c + x * R, c - y * R, 2, 2);
      }
      const halo = g.createRadialGradient(c, c, R * 0.98, c, c, R * 1.08);
      halo.addColorStop(0, "rgba(255,110,20,0.5)"); halo.addColorStop(1, "rgba(255,110,20,0)");
      g.fillStyle = halo; g.beginPath(); g.arc(c, c, R * 1.08, 0, Math.PI * 2); g.fill();
    }
  }

  window.JarvisGfx = { Sphere, Rings, Globe };
})();
