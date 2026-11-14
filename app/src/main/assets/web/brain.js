// Jarvis' Gehirn: winzige goldene Symbole in der Kugel (Videos, Musik, Web, Kalender, Lage, Wetter, Gedächtnis, Nachrichten).
// Sie drehen sich in 3D mit der Kugel. Nutzt Jarvis eine Quelle, leuchtet ihr Symbol auf und Impulse laufen zum Kern.
//   const b = new JarvisBrain(canvas2d, sphere3d); b.think(["videos"]); b.draw(dt)
(function () {
  const KINDS = ["videos", "musik", "web", "kalender", "lage", "wetter", "gedaechtnis", "nachrichten"];

  // eigene Symbole (keine Firmenlogos), Mitte 0/0, Größe s
  function icon(g, kind, s) {
    g.lineWidth = Math.max(1, s * .1); g.lineJoin = "round"; g.lineCap = "round";
    const L = (pts) => { g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(x * s, y * s) : g.moveTo(x * s, y * s)); g.stroke(); };
    switch (kind) {
      case "videos": g.beginPath(); g.arc(0, 0, s * .5, 0, 7); g.stroke(); g.beginPath(); g.moveTo(-s * .15, -s * .23); g.lineTo(s * .27, 0); g.lineTo(-s * .15, s * .23); g.closePath(); g.fill(); break;
      case "musik": L([[-.18, .25], [-.18, -.32], [.3, -.42], [.3, .15]]);
        g.beginPath(); g.ellipse(-s * .28, s * .27, s * .14, s * .1, -.4, 0, 7); g.fill(); g.beginPath(); g.ellipse(s * .2, s * .17, s * .14, s * .1, -.4, 0, 7); g.fill(); break;
      case "web": g.beginPath(); g.arc(0, 0, s * .46, 0, 7); g.stroke(); g.beginPath(); g.ellipse(0, 0, s * .19, s * .46, 0, 0, 7); g.stroke(); L([[-.46, 0], [.46, 0]]); break;
      case "kalender": g.strokeRect(-s * .4, -s * .32, s * .8, s * .72); L([[-.4, -.1], [.4, -.1]]); L([[-.2, -.45], [-.2, -.25]]); L([[.2, -.45], [.2, -.25]]);
        for (let i = 0; i < 3; i++) g.fillRect(-s * .28 + i * s * .22, s * .06, s * .1, s * .1); break;
      case "lage": g.beginPath(); g.arc(0, 0, s * .38, 0, 7); g.stroke(); L([[0, -.55], [0, -.2]]); L([[0, .2], [0, .55]]); L([[-.55, 0], [-.2, 0]]); L([[.2, 0], [.55, 0]]);
        g.beginPath(); g.arc(0, 0, s * .09, 0, 7); g.fill(); break;
      case "wetter": g.beginPath(); g.arc(-s * .1, -s * .08, s * .24, 0, 7); g.stroke();
        for (let k = 0; k < 8; k++) { const a = k * Math.PI / 4; L([[-.1 + Math.cos(a) * .34, -.08 + Math.sin(a) * .34], [-.1 + Math.cos(a) * .46, -.08 + Math.sin(a) * .46]]); } break;
      case "gedaechtnis": g.beginPath(); g.arc(-s * .14, -s * .05, s * .26, Math.PI * .6, Math.PI * 1.9); g.arc(s * .14, -s * .05, s * .26, Math.PI * 1.1, Math.PI * 2.4); g.stroke();
        L([[0, -.3], [0, .35]]); L([[-.2, .1], [-.05, .1]]); L([[.05, -.1], [.2, -.1]]); break;
      // gelernte Skills – im gleichen Strich-Stil
      case "person": g.beginPath(); g.arc(0, -s * .17, s * .17, 0, 7); g.stroke(); g.beginPath(); g.arc(0, s * .42, s * .32, Math.PI * 1.1, Math.PI * 1.9); g.stroke(); break;
      case "datum": g.strokeRect(-s * .34, -s * .02, s * .68, s * .4); L([[-.34, .14], [.34, .14]]); L([[-.16, -.02], [-.16, -.18]]); L([[0, -.02], [0, -.22]]); L([[.16, -.02], [.16, -.18]]);
        g.beginPath(); g.arc(0, -s * .3, s * .05, 0, 7); g.fill(); break;
      case "vorliebe": g.beginPath(); g.moveTo(0, s * .34); g.bezierCurveTo(-s * .55, -s * .02, -s * .3, -s * .48, 0, -s * .18); g.bezierCurveTo(s * .3, -s * .48, s * .55, -s * .02, 0, s * .34); g.stroke(); break;
      case "ort": g.beginPath(); g.arc(0, -s * .12, s * .26, Math.PI * .85, Math.PI * 2.15); g.lineTo(0, s * .42); g.closePath(); g.stroke(); g.beginPath(); g.arc(0, -s * .12, s * .08, 0, 7); g.fill(); break;
      case "spiel": g.beginPath(); g.ellipse(0, 0, s * .45, s * .26, 0, 0, 7); g.stroke(); L([[-.3, 0], [-.14, 0]]); L([[-.22, -.08], [-.22, .08]]);
        g.beginPath(); g.arc(s * .18, -s * .04, s * .04, 0, 7); g.fill(); g.beginPath(); g.arc(s * .28, s * .06, s * .04, 0, 7); g.fill(); break;
      case "funktion": g.beginPath(); g.moveTo(s * .08, -s * .46); g.lineTo(-s * .22, s * .06); g.lineTo(0, s * .06); g.lineTo(-s * .08, s * .46); g.lineTo(s * .24, -s * .08); g.lineTo(s * .02, -s * .08); g.closePath(); g.stroke(); break;
      case "wissen": g.beginPath(); g.arc(0, -s * .1, s * .26, Math.PI * .8, Math.PI * 2.2); g.stroke(); L([[-.12, .2], [.12, .2]]); L([[-.09, .32], [.09, .32]]); L([[-.07, .1], [-.1, .2]]); L([[.07, .1], [.1, .2]]); break;
      default: g.strokeRect(-s * .38, -s * .4, s * .76, s * .8); L([[-.24, -.22], [.24, -.22]]); L([[-.24, -.04], [.24, -.04]]); L([[-.24, .14], [.1, .14]]);   // nachrichten
    }
  }

  // Gelernte Skills: kleine Symbole, die nach "Neuer Skill freigeschaltet" in die Kugel fliegen und dort bleiben
  const LKEY = "jarvis_skills";
  let learned = [];
  try { learned = JSON.parse(localStorage.getItem(LKEY) || "[]") || []; } catch (e) { learned = []; }
  const saveLearned = () => { try { localStorage.setItem(LKEY, JSON.stringify(learned.slice(-40).map((x) => ({ kind: x.kind, emoji: x.emoji, title: x.title, text: x.text, type: x.type, ts: x.ts, arriving: x.arriving })))); } catch (e) {} };
  // Ab und zu leuchtet eins der gelernten Symbole auf, damit man sie sieht (und antippen kann)
  setInterval(() => {
    const vis = learned.map((x, i) => [x, i]).filter(([x]) => !x.arriving);
    if (!vis.length || document.hidden) return;
    const [x] = vis[Math.floor(Math.random() * vis.length)];
    x.flash = performance.now() + 1800;
  }, document.body && document.body.classList.contains("clean") ? 3000 : 5000);
  const instances = [];

  class JarvisBrain {
    /** Neuen Skill anlegen (erst unsichtbar, "arriving"), gibt seine Nummer zurück */
    static addSkill(sk) {
      learned.push({ kind: sk.kind || "wissen", title: sk.title || "", text: sk.text || "", type: sk.type || (sk.kind === "funktion" ? "skill" : "erinnerung"), ts: Date.now(), arriving: true });
      if (learned.length > 40) learned.shift();
      saveLearned();
      return learned.length - 1;
    }
    /** Skill ist angekommen: sichtbar machen und kurz aufleuchten lassen */
    static landSkill(i) {
      if (!learned[i]) return;
      delete learned[i].arriving; learned[i].flash = performance.now() + 2600; saveLearned();
    }
    /** Bildschirm-Position (CSS-Pixel), wo Skill i in der größten sichtbaren Kugel sitzt */
    static skillPos(i) {
      let best = null;
      for (const b of instances) { const p = b.pos && b.pos["L" + i]; if (p && (!best || b.c.clientWidth > best.w)) best = { x: p.x, y: p.y, w: b.c.clientWidth }; }
      return best;
    }
    static clearSkills() { learned = []; saveLearned(); }
    /** Welches gelernte Symbol liegt an dieser Bildschirmstelle (CSS-Pixel)? -> Nummer oder -1 */
    static hit(x, y, rad = 26) {
      let best = -1, bd = rad * rad;
      for (const b of instances) {
        const r = b.c.getBoundingClientRect(); if (r.width < 60) continue;
        for (const k in b.pos) { const p = b.pos[k], i = +k.slice(1); if (!learned[i] || learned[i].arriving) continue;
          const d = (p.x - x) ** 2 + (p.y - y) ** 2; if (d < bd) { bd = d; best = i; } }
      }
      return best;
    }
    static update(i, f) { if (learned[i]) { Object.assign(learned[i], f); saveLearned(); } }
    static hide(i, on) { if (learned[i]) learned[i].arriving = !!on; }
    static removeSkill(i) { if (learned[i]) { learned.splice(i, 1); saveLearned(); } }
    static get learned() { return learned; }
    static drawIcon(g, kind, s) { icon(g, kind, s); }

    constructor(canvas, sphere) {
      instances.push(this); this.pos = {};
      this.c = canvas; this.g = canvas.getContext("2d"); this.s = sphere; this.W = 0;
      // Plätze gleichmäßig in der Kugel verteilt (Fibonacci), leicht unterschiedlich tief
      this.regions = KINDS.map((k, i) => {
        const y = 1 - (i + .5) / KINDS.length * 2, r = Math.sqrt(1 - y * y), a = i * 2.399963;
        return { kind: k, v: [Math.cos(a) * r, y * .85, Math.sin(a) * r], rad: .64 + (i % 3) * .07, hot: 0, until: 0 };
      });
      this.sparks = [];
    }
    /** Diese Quellen leuchten auf (z. B. ["kalender", "wetter"]); ms = wie lange mindestens */
    think(kinds, ms = 2500) {
      const now = performance.now();
      for (const r of this.regions) if (kinds.includes(r.kind)) r.until = now + ms;
    }
    draw(dt) {
      const cleanK = document.body.classList.contains("clean") ? 1.35 : 1;   // Nur-Kugel: Symbole größer
      const d = Math.min(2.5, window.devicePixelRatio || 1), W = Math.round(this.c.clientWidth * d), H = Math.round(this.c.clientHeight * d);
      if (!W || !H) return;
      // gelernte Skills als zusätzliche Plätze (weiter innen, eigene Spirale)
      if (this._ln !== learned.length) {
        this._ln = learned.length;
        this.regions = this.regions.filter((r) => !r.learned);
        const n = Math.max(8, learned.length);
        learned.forEach((sk, i) => {
          const y = 1 - (i + .5) / n * 2, r = Math.sqrt(Math.max(0, 1 - y * y)), a = i * 2.399963 + 1.3;
          this.regions.push({ kind: sk.kind || ({ "👤": "person", "🎂": "datum", "❤️": "vorliebe", "📍": "ort", "🎵": "musik", "🎮": "spiel", "⚡": "funktion" }[sk.emoji] || "wissen"), li: i, learned: true, v: [Math.cos(a) * r, y * .8, Math.sin(a) * r], rad: .42 + (i % 3) * .07, hot: 0, until: 0 });
        });
      }
      if (W !== this.W || H !== this.H) { this.c.width = this.W = W; this.c.height = this.H = H; }
      const g = this.g, s = this.s, now = performance.now();
      g.clearRect(0, 0, W, H);
      const pw = s ? s.pw : 1, t = s ? s.t : now / 1000, asp = W / H;
      const breath = (1 + .03 * Math.sin(t * 1.5)) * (.92 + .08 * pw), tilt = .32 + .08 * Math.sin(t * .37), spin = t * .35;
      // wie im 3D-Bild der Kugel: drehen, kippen, Perspektive
      const proj = (v, rad) => {
        let x = v[0] * Math.cos(spin) + v[2] * Math.sin(spin), y = v[1], z = -v[0] * Math.sin(spin) + v[2] * Math.cos(spin);
        x *= rad * breath; y *= rad * breath; z *= rad * breath;
        const c = Math.cos(tilt), sn = Math.sin(tilt), y2 = y * c - z * sn, z2 = y * sn + z * c, zc = 3.2 - z2;
        return { x: (x * 1.88 / zc / asp + 1) / 2 * W, y: (1 - y2 * 1.88 / zc) / 2 * H, z: z2, k: 1.88 / zc };
      };
      const core = proj([0, 0, 0], 0), base = Math.min(W, H) * .062 * (this.scale || 1) * cleanK;
      g.save();
      const rect = this.c.getBoundingClientRect();
      const pts = this.regions.map((r) => {
        if (r.learned) { const sk = learned[r.li]; if (sk && sk.flash && now < sk.flash) r.until = sk.flash; }
        r.hot += ((now < r.until ? 1 : 0) - r.hot) * Math.min(1, dt * (now < r.until ? 6 : 1.5));
        const p = proj(r.v, r.rad);
        if (r.learned) this.pos["L" + r.li] = { x: rect.left + p.x / W * rect.width, y: rect.top + p.y / H * rect.height };
        return { r, p };
      }).filter((q) => !(q.r.learned && learned[q.r.li] && learned[q.r.li].arriving)).sort((a, b) => a.p.z - b.p.z);   // hinten zuerst
      // Nervenbahnen zwischen gleichzeitig aktiven Regionen
      const hot = pts.filter((q) => q.r.hot > .05);
      g.globalCompositeOperation = "lighter";
      for (let i = 0; i < hot.length; i++) for (let j = i + 1; j < hot.length; j++) {
        const a = hot[i].p, b = hot[j].p, al = Math.min(hot[i].r.hot, hot[j].r.hot) * .5 * pw;
        g.strokeStyle = `rgba(255,210,130,${al})`; g.lineWidth = 1.2 * d; g.beginPath(); g.moveTo(a.x, a.y);
        g.quadraticCurveTo(core.x + (a.y - b.y) * .2, core.y + (b.x - a.x) * .2, b.x, b.y); g.stroke();
      }
      // Impulse von aktiven Regionen zum Kern
      for (const q of hot) if (Math.random() < dt * 9 * q.r.hot) this.sparks.push({ r: q.r, u: 0, bend: (Math.random() - .5) * .6 });
      for (const sp of this.sparks) {
        sp.u += dt * 1.6;
        const a = proj(sp.r.v, sp.r.rad), u = sp.u, mx = (a.x + core.x) / 2 + (core.y - a.y) * sp.bend, my = (a.y + core.y) / 2 + (a.x - core.x) * sp.bend;
        const k = 1 - u, x = k * k * a.x + 2 * k * u * mx + u * u * core.x, y = k * k * a.y + 2 * k * u * my + u * u * core.y;
        const rr = 6 * d, gr = g.createRadialGradient(x, y, 0, x, y, rr);
        gr.addColorStop(0, `rgba(255,245,215,${.9 * pw})`); gr.addColorStop(1, "rgba(255,190,90,0)");
        g.fillStyle = gr; g.fillRect(x - rr, y - rr, rr * 2, rr * 2);
      }
      this.sparks = this.sparks.filter((sp) => sp.u < 1);
      // die Symbole selbst
      for (const { r, p } of pts) {
        const depth = (p.z / .65 + 1) / 2, h = r.hot, size = base * p.k * 1.6 * (1 + .35 * h);
        const alpha = (.3 + .32 * depth) * (.35 + .65 * pw) + h * .8;
        if (h > .02) {
          const gl = g.createRadialGradient(p.x, p.y, 0, p.x, p.y, size * 1.8);
          gl.addColorStop(0, `rgba(255,190,80,${.55 * h * pw})`); gl.addColorStop(1, "rgba(255,150,30,0)");
          g.globalCompositeOperation = "lighter"; g.fillStyle = gl; g.fillRect(p.x - size * 1.8, p.y - size * 1.8, size * 3.6, size * 3.6);
        }
        g.globalCompositeOperation = "source-over";
        // dunkle Scheibe dahinter, damit man das Symbol vor dem hellen Kern erkennt
        g.fillStyle = `rgba(14,8,2,${(.35 + .45 * h) * Math.min(1, alpha)})`; g.beginPath(); g.arc(p.x, p.y, size * .72, 0, 7); g.fill();
        if (h > .05) { g.strokeStyle = `rgba(255,214,140,${.8 * h})`; g.lineWidth = 1.2 * d; g.beginPath(); g.arc(p.x, p.y, size * .72, 0, 7); g.stroke(); }
        const col = pw > .5 ? (h > .05 ? "255,236,190" : "255,200,110") : "190,195,205";
        g.strokeStyle = g.fillStyle = `rgba(${col},${Math.min(1, alpha)})`;
        g.save(); g.translate(p.x, p.y);
        icon(g, r.kind, size);
        g.restore();
      }
      g.restore();
    }
  }
  window.JarvisBrain = JarvisBrain;
})();
