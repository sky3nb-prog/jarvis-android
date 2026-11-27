// Kleines Overlay am PC: neue 3D-Kugel im Bildschirm-Eck. Beim Aufwachen wächst ein goldener Nervenstrang (wie der
// Jarvis-Strang im Hintergrund) aus dem Eck an den Kanten entlang, Lichtimpulse laufen darin, und an seinem Knoten baut
// sich die Kugel auf. Daneben: "Hört zu" mit deinen Worten, dann die Antwort. Danach zieht sich alles zurück.
(function () {
  const q = new URLSearchParams(location.search);
  const corner = q.get("corner") || "tl";              // tl, tr, bl, br
  const R = corner.includes("r"), B = corner.includes("b");
  if (R) document.body.classList.add("r");
  const cv = document.getElementById("nerv"), g = cv.getContext("2d");
  const orb = document.getElementById("orb"), pill = document.getElementById("pill"), who = document.getElementById("who"), txt = document.getElementById("txt");
  let W = 0, H = 0, dpr = 1;
  const M = 26, OS = 86;                                // Rand, Kugelgröße
  function size() {
    dpr = devicePixelRatio || 1; W = innerWidth; H = innerHeight;
    cv.width = W * dpr; cv.height = H * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const ox = R ? W - M - OS : M, oy = B ? H - M - OS : M;
    Object.assign(orb.style, { left: ox + "px", top: oy + "px" });
    const py = B ? H - M - OS / 2 : M + OS / 2;
    Object.assign(pill.style, R ? { right: OS + M + 14 + "px", left: "auto" } : { left: OS + M + 14 + "px", right: "auto" });
    pill.style.top = py - 26 + "px";
  }
  addEventListener("resize", () => { size(); build(); });

  // --- Nervenstrang: Leiterbahnen in 45°-Schritten, vom Eck aus an den Kanten entlang, mit Abzweigen ---------
  function rnd(seed) { let s = seed; return () => (s = (s * 16807) % 2147483647) / 2147483647; }
  let traces = [];
  function build() {
    const r = rnd(4242); traces = [];
    const cx = R ? W - 4 : 4, cy = B ? H - 4 : 4, sx = R ? -1 : 1, sy = B ? -1 : 1;
    const main = (horiz, len, off, w) => {
      const pts = [[cx + (horiz ? 0 : sx * off), cy + (horiz ? sy * off : 0)]];
      let x = pts[0][0], y = pts[0][1], d = 0;
      while (d < len) {
        const st = 14 + r() * 26; d += st;
        if (horiz) { x += sx * st; if (r() < .28) { const j = (r() < .5 ? 1 : -1) * (4 + r() * 6); x += sx * Math.abs(j); y += sy * j * .7; } }
        else { y += sy * st; if (r() < .28) { const j = (r() < .5 ? 1 : -1) * (4 + r() * 6); y += sy * Math.abs(j); x += sx * j * .7; } }
        pts.push([x, y]);
      }
      traces.push({ pts, w, len: pathLen(pts), ph: r() * 6.283 });
      // Abzweige
      for (let i = 2; i < pts.length - 1; i += 2 + ((r() * 3) | 0)) {
        if (r() < .55) {
          const [bx, by] = pts[i], bl = 10 + r() * 22;
          const dx = horiz ? sx * bl * .7 : sx * bl, dy = horiz ? sy * bl : sy * bl * .7;
          traces.push({ pts: [[bx, by], [bx + dx * .6, by + dy * .6], [bx + dx, by + dy]], w: w * .6, len: bl, branch: true, at: i / pts.length, ph: r() * 6.283 });
        }
      }
    };
    main(true, Math.min(W * .55, 420), 6, 1.6); main(true, Math.min(W * .4, 300), 15, 1.0);
    main(false, Math.min(H * .7, 150), 6, 1.6); main(false, Math.min(H * .55, 110), 15, 1.0);
  }
  function pathLen(p) { let l = 0; for (let i = 1; i < p.length; i++) l += Math.hypot(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1]); return l; }
  function drawPath(p, upto) {
    g.beginPath(); g.moveTo(p[0][0], p[0][1]); let l = 0;
    for (let i = 1; i < p.length; i++) {
      const s = Math.hypot(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1]);
      if (l + s >= upto) { const f = (upto - l) / s; g.lineTo(p[i - 1][0] + (p[i][0] - p[i - 1][0]) * f, p[i - 1][1] + (p[i][1] - p[i - 1][1]) * f); return [p[i - 1][0] + (p[i][0] - p[i - 1][0]) * f, p[i - 1][1] + (p[i][1] - p[i - 1][1]) * f]; }
      g.lineTo(p[i][0], p[i][1]); l += s;
    }
    return p[p.length - 1];
  }
  function pointAt(p, at) {
    let l = 0;
    for (let i = 1; i < p.length; i++) {
      const s = Math.hypot(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1]);
      if (l + s >= at) { const f = (at - l) / s; return [p[i - 1][0] + (p[i][0] - p[i - 1][0]) * f, p[i - 1][1] + (p[i][1] - p[i - 1][1]) * f]; }
      l += s;
    }
    return p[p.length - 1];
  }

  // --- Bewegung: der Gedankenschweif schwingt, statt starr zu liegen --------------------------------------
  // Jeder Punkt wird quer zur Laufrichtung ausgelenkt. Die Welle wandert am Strang entlang, außen stärker als
  // am Knoten, und wird schneller/größer, je nachdem was er gerade tut (zuhören, denken, sprechen).
  function waved(t, now) {
    const sp = state === "thinking" ? 3.2 : state === "speaking" ? 2.4 : state === "listening" ? 1.9 : 1.1;
    const base = t.branch ? 2.2 : 3.4;
    const k = base * (state === "idle" ? .5 : .8 + level * .9);
    const pts = t.pts, n = pts.length, out = new Array(n);
    for (let i = 0; i < n; i++) {
      const a = pts[i], b = pts[Math.min(i + 1, n - 1)];
      let dx = b[0] - a[0], dy = b[1] - a[1];
      const L = Math.hypot(dx, dy) || 1; dx /= L; dy /= L;
      const u = n > 1 ? i / (n - 1) : 0;                       // am Eck ruhig, zur Spitze hin mehr Ausschlag
      const w = Math.sin(now / 1000 * sp + i * .38 + t.ph) * k * (.18 + u * 1.1)
              + Math.sin(now / 1000 * sp * .43 + t.ph * 2) * k * .25 * u;
      out[i] = [a[0] - dy * w, a[1] + dx * w];
    }
    return out;
  }

  // --- Zustand ---------------------------------------------------------------------------------------------
  let grow = 0, want = 0, state = "idle", level = 0, lvT = 0, idleTimer = 0, show = true, pulses = [];
  let sphere = null, brain = null;
  try { sphere = new Sphere3D(document.getElementById("sph"), 3); brain = new JarvisBrain(document.getElementById("brn"), sphere); brain.scale = .8; } catch (e) {}
  const LABEL = { listening: "VECTOR · HÖRT ZU", thinking: "VECTOR · DENKT NACH", speaking: "VECTOR · SPRICHT", idle: "VECTOR" };
  function bars() { return '<span class="bars">' + "<i></i>".repeat(5) + "</span>"; }
  function setLabel() { who.innerHTML = (LABEL[state] || "VECTOR") + (state === "listening" || state === "speaking" ? bars() : ""); }
  function wake() { want = 1; clearTimeout(idleTimer); }
  function sleep(ms) { clearTimeout(idleTimer); idleTimer = setTimeout(() => { want = 0; pill.classList.remove("on"); }, ms); }

  function onEvent(type, d) {
    if (type === "state") {
      state = d.state || "idle"; setLabel();
      if (sphere) sphere.state = state;
      if (state !== "idle") { wake(); } else sleep(2500);
    } else if (type === "msg") {
      txt.textContent = d.text || ""; txt.className = d.role === "Du" ? "you" : "";
      if (d.role === "Du") txt.textContent = "„" + d.text + "“";
      wake(); pill.classList.add("on"); if (state === "idle") sleep(Math.min(12000, 3500 + (d.text || "").length * 55));
    } else if (type === "level") { level = d.value || 0; lvT = performance.now(); }
    else if (type === "orb") { show = !!d.show; if (!show) { want = 0; pill.classList.remove("on"); } }
    else if (type === "power" && d.on === false) { want = 0; pill.classList.remove("on"); }
  }
  try {
    const es = new EventSource("/events");
    es.onmessage = (e) => { try { const m = JSON.parse(e.data); onEvent(m.type, m.data || {}); } catch (x) {} };
  } catch (e) {}

  // --- Zeichnen --------------------------------------------------------------------------------------------
  let last = performance.now();
  function frame(now) {
    const dt = Math.min(50, now - last); last = now;
    const target = show ? want : 0;
    grow += (target - grow) * (target > grow ? .06 : .09);
    if (Math.abs(grow - target) < .002) grow = target;
    g.clearRect(0, 0, W, H);
    if (grow > .01) {
      g.lineCap = "round"; g.lineJoin = "round";
      const WV = new Map();
      for (const t of traces) WV.set(t, waved(t, now));
      for (const t of traces) {
        const tg = t.branch ? Math.max(0, (grow - t.at * .8) / .3) : grow;   // Abzweige wachsen nach dem Hauptstrang
        if (tg <= 0) continue;
        const upto = t.len * Math.min(1, tg), pts = WV.get(t);
        g.strokeStyle = "rgba(29, 158, 117,.18)"; g.lineWidth = t.w * 4; drawPath(pts, upto); g.stroke();
        g.strokeStyle = "rgba(159, 225, 203,.85)"; g.lineWidth = t.w; const tip = drawPath(pts, upto); g.stroke();
        if (tg < 1 && !t.branch) {   // glühende Spitze, solange er wächst
          g.fillStyle = "#c8fff6"; g.shadowColor = "#1d9e75"; g.shadowBlur = 14; g.beginPath(); g.arc(tip[0], tip[1], 2.6, 0, 7); g.fill(); g.shadowBlur = 0;
        }
      }
      // Gedanken, die durch den Strang laufen: in der Akzentfarbe, mit kurzem Schweif, dichter beim Denken
      const AK = (window.VectorColors && window.VectorColors.akzent) || "#C45CFF";
      const rate = state === "thinking" ? .34 : state === "speaking" ? .25 : state === "listening" ? .14 : .07;
      if (grow > .9 && Math.random() < rate) {
        const t = traces[(Math.random() * traces.length) | 0];
        pulses.push({ t, at: 0, v: (state === "thinking" ? .42 : state === "speaking" ? .35 : .18) * (1 + Math.random()) });
      }
      for (const p of pulses) {
        p.at += p.v * dt;
        const pts = WV.get(p.t) || p.t.pts;
        for (let k = 0; k < 4; k++) {                      // Schweif: vier Punkte, nach hinten schwächer
          const at = p.at - k * 7; if (at < 0) break;
          const [x, y] = pointAt(pts, Math.min(at, p.t.len));
          const a = grow * (.9 - k * .2);
          g.fillStyle = k ? AK : "rgba(255,255,255,.95)";
          g.globalAlpha = a; g.shadowColor = AK; g.shadowBlur = k ? 8 : 14;
          g.beginPath(); g.arc(x, y, 2.2 - k * .4, 0, 7); g.fill();
        }
        g.globalAlpha = 1; g.shadowBlur = 0;
      }
      pulses = pulses.filter((p) => p.at < p.t.len);
      // Knoten im Eck
      const cx = R ? W - 4 : 4, cy = B ? H - 4 : 4;
      g.fillStyle = "rgba(159, 225, 203," + grow + ")"; g.beginPath(); g.arc(cx + (R ? -6 : 6), cy + (B ? -6 : 6), 3, 0, 7); g.fill();
    }
    orb.classList.toggle("on", grow > .45);
    if (grow < .2) pill.classList.remove("on"); else if (grow > .8 && (state !== "idle" || txt.textContent)) pill.classList.add("on");
    if (sphere && grow > .3) { if (now - lvT > 400) level *= .9; sphere.level = level; try { sphere.draw(dt); if (brain && brain.draw) brain.draw(dt); } catch (e) {} }
    const bs = document.querySelectorAll(".bars i"); bs.forEach((b, i) => (b.style.height = 3 + Math.abs(Math.sin(now / 140 + i * 1.3)) * 8 * (state === "speaking" || state === "listening" ? Math.max(.25, level) : .2) + "px"));
    requestAnimationFrame(frame);
  }
  size(); build(); setLabel(); requestAnimationFrame(frame);
  window.orbDemo = (s, text, role) => { onEvent("state", { state: s }); if (text) onEvent("msg", { role: role || "Assistent", text }); };
})();
