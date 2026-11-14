// Iron-Man-Start direkt im HUD (kein eigenes Fenster mehr – nichts kann hängen bleiben):
// Schwarz -> goldene Lichtpunkte steigen von unten auf und ziehen sich in der Mitte zur Kugel zusammen, Lichtblitz,
// Ringe, "J.A.R.V.I.S." baut sich auf, Systemstatus tickt ein – dann löst sich der Vorhang auf und die Oberfläche
// baut sich Stück für Stück auf (Leiste, Karten, Kugel). Klick oder Esc überspringt.
//   JBoot.play()   – startet die Animation (auch per Test-Knopf / "Friday, Startanimation")
(function () {
  const css = document.createElement("style");
  css.textContent = `
  #bootfx{position:fixed;inset:0;z-index:200;background:#000;cursor:none;transition:opacity .9s ease}
  #bootfx.out{opacity:0;pointer-events:none}
  #bootfx canvas{position:absolute;inset:0;width:100%;height:100%}
  #bootfx .bt{position:absolute;left:0;right:0;text-align:center;font-family:"Segoe UI",system-ui,sans-serif}
  #bootfx .title{top:calc(50% + min(17vh,17vw));font-size:min(4.6vh,3.6vw);letter-spacing:.55em;font-weight:600;color:#ffd678;text-shadow:0 0 22px rgba(255,170,40,.7)}
  #bootfx .title span{display:inline-block;opacity:0;transform:translateY(10px) scale(.9);filter:blur(4px);transition:all .35s cubic-bezier(.2,1.4,.4,1)}
  #bootfx .title span.v{opacity:1;transform:none;filter:none}
  #bootfx .sub{top:calc(50% + min(17vh,17vw) + min(7vh,5.5vw));font-size:min(1.9vh,1.4vw);letter-spacing:.32em;color:#c8965a;opacity:0;transition:opacity .6s}
  #bootfx .sub.v{opacity:1}
  #bootfx .sys{position:absolute;right:4vw;bottom:8vh;font:min(1.6vh,1.2vw)/1.75 Consolas,monospace;color:rgba(255,214,140,.85);text-align:right}
  #bootfx .sys div{opacity:0;transform:translateX(16px);transition:all .3s}
  #bootfx .sys div.v{opacity:1;transform:none}
  #bootfx .sys b{color:#6effcd;font-weight:400}#bootfx .sys b.r{color:#ff7a5a}
  #bootfx .log{position:absolute;left:4vw;bottom:8vh;font:min(1.5vh,1.1vw)/1.75 Consolas,monospace;color:rgba(110,200,255,.7);white-space:pre}
  #bootfx .skip{position:absolute;right:16px;top:12px;font-size:11px;color:#4a3a20;letter-spacing:.1em}
  /* Oberfläche baut sich danach auf */
  .bootin{animation:bootin .7s cubic-bezier(.2,.9,.3,1) both}
  @keyframes bootin{from{opacity:0;transform:translateY(18px) scale(.98);filter:blur(3px)}to{opacity:1;transform:none;filter:none}}
  .bootin-top{animation:bootintop .6s cubic-bezier(.2,.9,.3,1) both}
  @keyframes bootintop{from{opacity:0;transform:translateY(-46px)}to{opacity:1;transform:none}}`;
  document.head.appendChild(css);

  let running = false;
  function sphereCenter() {
    const s = document.querySelector("#f-sph") || document.querySelector(".pv.on .sph");
    if (s) { const r = s.getBoundingClientRect(); if (r.width > 20) return { x: r.left + r.width / 2, y: r.top + r.height / 2, r: r.width / 2 }; }
    return { x: innerWidth / 2, y: innerHeight * .45, r: Math.min(innerWidth, innerHeight) * .2 };
  }

  function play() {
    if (running) return; running = true;
    const box = document.createElement("div"); box.id = "bootfx";
    box.innerHTML = '<canvas></canvas><div class="bt title"></div><div class="bt sub">PERSÖNLICHER ASSISTENT · ONLINE</div><div class="log"></div><div class="sys"></div><div class="skip">Klick oder Esc = überspringen</div>';
    document.body.appendChild(box);
    const cv = box.querySelector("canvas"), g = cv.getContext("2d"), d = Math.min(2, devicePixelRatio || 1);
    let W = innerWidth, H = innerHeight; cv.width = W * d; cv.height = H * d; g.setTransform(d, 0, 0, d, 0, 0);
    const C = sphereCenter();
    // Lichtpunkte: starten unten verteilt, steigen auf, ziehen dann spiralförmig zur Mitte
    const N = Math.round(Math.min(900, W * H / 1800));
    const P = Array.from({ length: N }, () => ({ x: Math.random() * W, y: H + Math.random() * H * .6, vx: 0, vy: -(1.2 + Math.random() * 2.4), s: .6 + Math.random() * 1.6,
      a: Math.random() * 6.28, rr: C.r * (.25 + Math.random() * .8), delay: Math.random() * .7 }));
    const T = "J.A.R.V.I.S."; const title = box.querySelector(".title"); title.innerHTML = [...T].map((c) => `<span>${c}</span>`).join("");
    const t0 = performance.now(); let flash = 0, done = false, last = t0;
    const log = ["> Kern wird geladen …", "> Gedächtnis synchronisiert", "> Sprachmodul „Friday“", "> Neuronales Netz online", "> Oberfläche wird aufgebaut …"];
    log.forEach((l, i) => setTimeout(() => { box.querySelector(".log").textContent += l + "\n"; }, 300 + i * 330));
    // Systemstatus (schnell, aus dem letzten Check)
    fetch("/api/syscheck").then((r) => r.json()).then((dd) => {
      const items = (dd.items || []).filter((i) => i.ok !== null).slice(0, 9);
      const sys = box.querySelector(".sys");
      items.forEach((i, k) => setTimeout(() => { const e = document.createElement("div"); e.innerHTML = `${i.name} <b class="${i.ok ? "" : "r"}">${i.ok ? "OK" : "!"}</b>`; sys.appendChild(e); requestAnimationFrame(() => e.classList.add("v")); }, 1300 + k * 110));
    }).catch(() => {});
    function frame(now) {
      if (done) return;
      const t = (now - t0) / 1000, dt = Math.min(.05, (now - last) / 1000); last = now;
      g.fillStyle = "rgba(0,0,0,.28)"; g.fillRect(0, 0, W, H);   // Nachleuchten (Schweife)
      g.globalCompositeOperation = "lighter";
      const pull = Math.max(0, Math.min(1, (t - .9) / 1.1));   // ab 0,9 s ziehen sie zur Mitte
      for (const p of P) {
        if (t < p.delay) continue;
        if (pull < 1) {
          p.vy -= dt * 2.2; p.y += p.vy * 60 * dt * (1 - pull * .6);
          p.x += Math.sin(t * 2 + p.a) * .4;
          const tx = C.x + Math.cos(p.a + t * 2.4) * p.rr * (1 - pull * .7), ty = C.y + Math.sin(p.a + t * 2.4) * p.rr * .55 * (1 - pull * .7);
          p.x += (tx - p.x) * pull * .12; p.y += (ty - p.y) * pull * .12;
        } else {   // kreisen als Hülle der Kugel
          p.x = C.x + Math.cos(p.a + t * 2.8) * p.rr * .32; p.y = C.y + Math.sin(p.a + t * 2.8) * p.rr * .2;
        }
        const al = Math.min(1, (t - p.delay) * 2) * (1 - Math.max(0, t - 2.6) * 1.2);
        if (al <= 0) continue;
        g.fillStyle = `rgba(255,${190 + p.s * 30},${90 + p.s * 40},${al * .9})`; g.beginPath(); g.arc(p.x, p.y, p.s, 0, 7); g.fill();
      }
      // Blitz + Ringe, wenn sie sich vereinen
      if (t > 2.0 && !flash) flash = now;
      if (flash) {
        const k = (now - flash) / 1000;
        const gr = g.createRadialGradient(C.x, C.y, 0, C.x, C.y, C.r * (1.2 + k * 2));
        gr.addColorStop(0, `rgba(255,240,200,${Math.max(0, .85 - k * .9)})`); gr.addColorStop(.4, `rgba(255,180,60,${Math.max(0, .35 - k * .4)})`); gr.addColorStop(1, "rgba(255,150,30,0)");
        g.fillStyle = gr; g.fillRect(0, 0, W, H);
        for (let i = 0; i < 3; i++) { const kk = k - i * .18; if (kk < 0 || kk > 1.4) continue;
          g.strokeStyle = `rgba(255,214,140,${Math.max(0, .7 - kk * .5)})`; g.lineWidth = 2 - i * .5; g.beginPath(); g.arc(C.x, C.y, C.r * (.6 + kk * 1.1), 0, 7); g.stroke(); }
      }
      g.globalCompositeOperation = "source-over";
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    [...title.children].forEach((sp, i) => setTimeout(() => sp.classList.add("v"), 2150 + i * 70));
    setTimeout(() => box.querySelector(".sub").classList.add("v"), 2900);
    const finish = () => {
      if (done) return; done = true;
      box.classList.add("out");
      // Oberfläche Stück für Stück aufbauen
      const top = document.querySelector(".top"); if (top) { top.classList.remove("bootin-top"); void top.offsetWidth; top.classList.add("bootin-top"); }
      const parts = [...document.querySelectorAll(".pv.on > *, #typebar")].filter((e) => e.offsetParent !== null);
      parts.forEach((e, i) => { e.style.animationDelay = (.08 + i * .07) + "s"; e.classList.remove("bootin"); void e.offsetWidth; e.classList.add("bootin");
        setTimeout(() => { e.classList.remove("bootin"); e.style.animationDelay = ""; }, 1600 + i * 70); });
      try { fetch("/api/boot_done", { method: "POST", body: JSON.stringify({ bad: box.querySelectorAll(".sys b.r").length }) }); } catch (e) {}
      setTimeout(() => { box.remove(); running = false; }, 1000);
      removeEventListener("keydown", key);
    };
    const key = (e) => { if (e.key === "Escape" || e.key === " " || e.key === "Enter") finish(); };
    addEventListener("keydown", key); box.addEventListener("click", finish);
    setTimeout(finish, 4300);
  }
  window.JBoot = { play };
  // Beim Start von Jarvis (Server sagt einmal "boot") und auf Zuruf/Test
  try { fetch("/api/boot_pending").then((r) => r.json()).then((d) => { if (d && d.boot) play(); }).catch(() => {}); } catch (e) {}
  try { const es = new EventSource("/events"); es.onmessage = (e) => { try { if (JSON.parse(e.data).type === "boot") play(); } catch (x) {} }; } catch (e) {}
})();
