(function () {
  const q = new URLSearchParams(location.search), name = q.get("name") || "Sir";
  const $ = (id) => document.getElementById(id);
  const cv = $("bg"), g = cv.getContext("2d");
  let W, H; const dpr = Math.min(2, devicePixelRatio || 1);
  function size() { W = innerWidth; H = innerHeight; cv.width = W * dpr; cv.height = H * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0); }
  size(); addEventListener("resize", size);
  // Hintergrund: Hex-Gitter, das sich von der Mitte aus aufbaut, plus goldene Leitungen zur Kugel
  const t0 = performance.now();
  const lines = Array.from({ length: 16 }, (_, i) => ({ a: (i / 16) * Math.PI * 2 + Math.random() * .2, r0: .2 + Math.random() * .1, w: .5 + Math.random(), sp: .6 + Math.random() * .8, ph: Math.random() * 6 }));
  let sphere = null, brain = null;
  try { sphere = new Sphere3D($("sph"), 3); brain = new JarvisBrain($("brn"), sphere); brain.scale = .8; sphere.state = "thinking"; } catch (e) {}
  let last = t0;
  function frame(now) {
    const dt = Math.min(.05, (now - last) / 1000); last = now; const t = (now - t0) / 1000;
    g.clearRect(0, 0, W, H);
    const cx = W / 2, cy = H * .46, R = Math.min(W, H) * .23;
    // Hex-Gitter
    const s = 34, reveal = Math.min(1, t / 2.2) * Math.hypot(W, H) * .7;
    g.lineWidth = 1;
    for (let y = -s; y < H + s; y += s * .866) for (let x = (Math.round(y / (s * .866)) % 2) * s / 2 - s; x < W + s; x += s) {
      const d = Math.hypot(x - cx, y - cy); if (d > reveal) continue;
      const a = Math.max(0, .09 - d / Math.hypot(W, H) * .1) * (1 - Math.max(0, d - reveal + 120) / 120);
      if (a <= 0) continue; g.strokeStyle = `rgba(255,170,40,${a})`; g.beginPath();
      for (let k = 0; k < 6; k++) { const an = Math.PI / 3 * k + Math.PI / 6; const px = x + Math.cos(an) * s * .5, py = y + Math.sin(an) * s * .5; k ? g.lineTo(px, py) : g.moveTo(px, py); }
      g.closePath(); g.stroke();
    }
    // goldene Leitungen, die zur Kugel wachsen
    g.globalCompositeOperation = "lighter";
    for (const l of lines) {
      const grow = Math.min(1, Math.max(0, (t - .2) / 1.6)); const r1 = R * 1.6, r2 = R * (1.62 + 2.5 * (1 - grow));
      const x1 = cx + Math.cos(l.a) * (r1 + Math.max(W, H) * .5 * grow * .0), y1 = cy + Math.sin(l.a) * r1;
      const xe = cx + Math.cos(l.a) * Math.max(W, H), ye = cy + Math.sin(l.a) * Math.max(W, H);
      const bend = Math.sin(t * l.sp + l.ph) * 40;
      g.strokeStyle = `rgba(255,190,90,${.09 * grow})`; g.lineWidth = l.w * 3; g.beginPath(); g.moveTo(xe, ye);
      g.quadraticCurveTo((xe + x1) / 2 + bend, (ye + y1) / 2 - bend, cx + Math.cos(l.a) * r2, cy + Math.sin(l.a) * r2); g.stroke();
      g.strokeStyle = `rgba(255,214,120,${.38 * grow})`; g.lineWidth = l.w; g.stroke();
      const u = ((t * l.sp * .5 + l.ph) % 1); // Impuls Richtung Kugel
      const px = xe + (cx + Math.cos(l.a) * r2 - xe) * u, py = ye + (cy + Math.sin(l.a) * r2 - ye) * u;
      const gr = g.createRadialGradient(px, py, 0, px, py, 8); gr.addColorStop(0, `rgba(255,240,200,${.9 * grow})`); gr.addColorStop(1, "rgba(255,200,110,0)");
      g.fillStyle = gr; g.fillRect(px - 8, py - 8, 16, 16);
    }
    g.globalCompositeOperation = "source-over";
    if (sphere) { sphere.level = .15 + .1 * Math.sin(t * 3); try { sphere.draw(dt); brain && brain.draw(dt); } catch (e) {} }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  setTimeout(() => $("fade").classList.add("off"), 50);
  setTimeout(() => document.body.classList.add("on"), 600);
  // Titel Buchstabe für Buchstabe
  const T = "V.E.C.T.O.R."; $("title").innerHTML = [...T].map((c) => `<span>${c}</span>`).join("");
  [...$("title").children].forEach((sp, i) => setTimeout(() => sp.classList.add("v"), 1400 + i * 90));
  setTimeout(() => $("sub").classList.add("v"), 2600);
  // Konsole links
  const log = ["> Kern wird geladen …", "> Sprachmodul: Vector", "> Gedächtnis synchronisiert", "> Neuronales Netz online", "> Hologramm-Schnittstelle aktiv", "> Verbindung zum Handy …"];
  log.forEach((l, i) => setTimeout(() => { $("left").textContent += l + "\n"; }, 700 + i * 420));
  // Systemstatus rechts (echte Prüfung)
  let items = [];
  const shown = fetch("/api/syscheck?neu=1").then((r) => r.json()).then((d) => { items = d.items || []; }).catch(() => {});
  setTimeout(async () => {
    $("sysh").classList.add("v");
    await Promise.race([shown, new Promise((r) => setTimeout(r, 5000))]);
    const list = items.filter((i) => i.ok !== null).slice(0, 12);
    list.forEach((i, k) => setTimeout(() => {
      const d = document.createElement("div"); d.className = "row " + (i.ok ? "g" : "r");
      d.innerHTML = `<i></i><b>${i.name}</b><small>${i.ok ? "OK" : i.detail}</small>`; $("rows").appendChild(d);
      requestAnimationFrame(() => d.classList.add("v"));
    }, k * 160));
    const bad = list.filter((i) => !i.ok).length;
    setTimeout(() => {
      $("welcome").textContent = bad ? `Willkommen zurück, ${name}. ${bad} System${bad > 1 ? "e brauchen" : " braucht"} Aufmerksamkeit.` : `Willkommen zurück, ${name}. Alle Systeme bereit.`;
      $("welcome").classList.add("v");
      if (sphere) sphere.state = "speaking";
      try { fetch("/api/boot_done", { method: "POST", body: JSON.stringify({ bad }) }); } catch (e) {}
    }, list.length * 160 + 400);
    setTimeout(end, list.length * 160 + 4200);
  }, 1800);
  let ended = false;
  function end() {
    if (ended) return; ended = true;
    $("fade").classList.remove("off");
    setTimeout(() => { try { window.pywebview && window.pywebview.api.close(); } catch (e) {} ; try { fetch("/api/boot_close", { method: "POST", body: "{}" }); } catch (e) {} }, 1300);
  }
  addEventListener("keydown", (e) => { if (e.key === "Escape" || e.key === " " || e.key === "Enter") end(); });
  addEventListener("click", end);
  setTimeout(end, 16000);   // spätestens nach 16 s
})();
