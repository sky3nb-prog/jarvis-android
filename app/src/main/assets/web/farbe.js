// Eigene Farbe für Vector: Farbkreis (Farbton) + Schieber für Helligkeit und Kräftigkeit.
// Alles, was Teal (Vector-Grundfarbe) ist, nimmt die gewählte Farbe an – auch die Kugel. Gleiche Datei in App und PC-HUD.
//   JFarbe.open()  -> Fenster mit Farbkreis
//   JFarbe.apply() -> gespeicherte Farbe anwenden (passiert beim Laden von selbst)
(function () {
  const BASE = 161;           // Farbton des Vector-Teal (Grad) - vorher 38 (Gold), seit der Umstellung auf Teal
  const KEY = "jarvis_farbe";
  const PV = 2;                // Paletten-Version: bei Wechsel der Grundfarbe (wie Gold->Teal) hochzählen,
                                // damit alte gespeicherte Werte (die sich auf die alte Grundfarbe beziehen) automatisch verworfen werden
  const DEF = { h: BASE, b: 1, s: 1 };
  let cur = load();

  function load() {
    try { const v = JSON.parse(localStorage.getItem(KEY) || "null"); if (v && typeof v.h === "number" && v.pv === PV) return v; } catch (e) {}
    return Object.assign({}, DEF);
  }
  function save(v) { v = Object.assign({}, v, { pv: PV }); try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) {} }

  let styleEl = null;
  function apply(v) {
    v = v || cur;
    const rot = ((v.h - BASE) % 360 + 360) % 360;
    const plain = rot === 0 && v.b === 1 && v.s === 1;
    if (!styleEl) { styleEl = document.createElement("style"); styleEl.id = "jfarbe-style"; document.head.appendChild(styleEl); }
    if (plain) { styleEl.textContent = ""; return; }
    // Ganze Oberfläche umfärben, Fotos/Karten/Videos zurückdrehen, damit sie echt aussehen
    styleEl.textContent =
      `html{filter:hue-rotate(${rot}deg) saturate(${v.s}) brightness(${v.b})}` +
      `img,video,.maplibregl-canvas,.no-tint,#jfarbe{filter:brightness(${(1 / v.b).toFixed(3)}) saturate(${(1 / Math.max(v.s, 0.05)).toFixed(3)}) hue-rotate(${-rot}deg)}`;
  }

  function hsl(h, s, l) { return `hsl(${h},${Math.round(s * 100)}%,${Math.round(l * 100)}%)`; }

  function open() {
    if (document.getElementById("jfarbe")) return;
    const start = Object.assign({}, cur);
    const ov = document.createElement("div");
    ov.id = "jfarbe";
    ov.innerHTML = `
      <style>
        #jfarbe{position:fixed;inset:0;z-index:99990;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center;font-family:inherit}
        #jfarbe .box{width:320px;max-width:92vw;padding:22px 20px 18px;border-radius:22px;background:#0b0f13;border:1px solid rgba(255,255,255,.12);color:#e8e4da;text-align:center}
        #jfarbe h3{margin:0 0 14px;font-size:14px;letter-spacing:3px;font-weight:600}
        #jfarbe .wheel{position:relative;width:220px;height:220px;margin:0 auto;border-radius:50%;touch-action:none;cursor:pointer;
          background:radial-gradient(circle,#0b0f13 0 34%,transparent 35%),conic-gradient(from 90deg,red,#ff0,lime,cyan,blue,#f0f,red)}
        #jfarbe .knob{position:absolute;width:26px;height:26px;margin:-13px 0 0 -13px;border-radius:50%;border:3px solid #fff;box-shadow:0 0 0 2px rgba(0,0,0,.5),0 2px 8px rgba(0,0,0,.6);pointer-events:none}
        #jfarbe .prev{position:absolute;left:50%;top:50%;width:64px;height:64px;margin:-32px 0 0 -32px;border-radius:50%;box-shadow:0 0 30px currentColor}
        #jfarbe label{display:block;text-align:left;font-size:12.5px;color:#94a8a3;margin:16px 0 4px}
        #jfarbe input[type=range]{width:100%;accent-color:#fff}
        #jfarbe .row{display:flex;gap:10px;margin-top:18px}
        #jfarbe button{flex:1;padding:11px;border-radius:12px;border:1px solid rgba(255,255,255,.18);background:#141a20;color:#e8e4da;font:inherit;font-size:14px;cursor:pointer}
        #jfarbe button.ok{background:#e8e4da;color:#0b0f13;font-weight:600}
      </style>
      <div class="box">
        <h3>DEINE FARBE</h3>
        <div class="wheel" id="jf-wheel"><div class="prev" id="jf-prev"></div><div class="knob" id="jf-knob"></div></div>
        <label>Helligkeit</label><input type="range" id="jf-b" min="0.6" max="1.4" step="0.01">
        <label>Kräftigkeit</label><input type="range" id="jf-s" min="0" max="1.6" step="0.01">
        <div class="row"><button id="jf-reset">Teal</button><button id="jf-no">Abbrechen</button><button class="ok" id="jf-ok">Fertig</button></div>
      </div>`;
    document.body.appendChild(ov);
    const $ = (id) => ov.querySelector("#" + id);
    const wheel = $("jf-wheel"), knob = $("jf-knob");
    const paint = () => {
      const a = cur.h * Math.PI / 180, r = 92;   // Rot rechts, dann im Uhrzeigersinn (wie der Farbkreis)
      knob.style.left = (110 + Math.cos(a) * r) + "px";
      knob.style.top = (110 + Math.sin(a) * r) + "px";
      knob.style.background = hsl(cur.h, 1, 0.5);
      const c = hsl(cur.h, Math.min(1, 0.85 * cur.s), Math.min(0.75, 0.55 * cur.b));
      $("jf-prev").style.background = c; $("jf-prev").style.color = c;
      $("jf-b").value = cur.b; $("jf-s").value = cur.s;
      apply(cur);
    };
    const pick = (e) => {
      const r = wheel.getBoundingClientRect();
      const x = (e.clientX - r.left) - r.width / 2, y = (e.clientY - r.top) - r.height / 2;
      cur.h = Math.round(((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360);
      paint();
    };
    let down = false;
    wheel.addEventListener("pointerdown", (e) => { down = true; wheel.setPointerCapture(e.pointerId); pick(e); });
    wheel.addEventListener("pointermove", (e) => { if (down) pick(e); });
    wheel.addEventListener("pointerup", () => { down = false; });
    $("jf-b").addEventListener("input", (e) => { cur.b = +e.target.value; paint(); });
    $("jf-s").addEventListener("input", (e) => { cur.s = +e.target.value; paint(); });
    $("jf-reset").addEventListener("click", () => { cur = Object.assign({}, DEF); paint(); });
    $("jf-no").addEventListener("click", () => { cur = start; apply(cur); ov.remove(); });
    $("jf-ok").addEventListener("click", () => { save(cur); ov.remove(); try { if (window.JFarbe.onSave) window.JFarbe.onSave(cur); } catch (e) {} });
    ov.addEventListener("click", (e) => { if (e.target === ov) { cur = start; apply(cur); ov.remove(); } });
    paint();
  }

  window.JFarbe = { open, apply: () => apply(cur), get: () => Object.assign({}, cur), set: (v) => { cur = Object.assign({}, DEF, v || {}); save(cur); apply(cur); } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => apply(cur)); else apply(cur);
})();
