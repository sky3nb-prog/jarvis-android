// Modulares HUD: Widgets liegen in einem Raster, lassen sich schieben, in der Größe ziehen, rauswerfen
// und wieder dazuholen. Jeder Modus (normal, gaming, schule, ets2 …) hat seine eigene Anordnung pro Seite.
// Dieselbe Datei läuft am PC (pc_web) und am Handy (assets/web) – bitte synchron halten.
//
//   JRaster.start({ board, seite, geraet })   Brett übernehmen und zeichnen
//   JRaster.seite("info")                     Seite wechseln
//   JRaster.modus("gaming")                   Modus wechseln (eigene Anordnung)
//   JRaster.edit(true/false)                  Bearbeiten an/aus
//   JRaster.registriere(id, { ... })          Widget bekannt machen (siehe unten)
//   JRaster.anordnung()                       aktuelle Anordnung (zum Sichern)
//
// Ein Widget wird so angemeldet:
//   JRaster.registriere("wetter", { t:"Wetter", w:4, h:2, min:[2,2], bau(el){ el.innerHTML = "…" } })
// bau(el) bekommt den leeren Kasten und füllt ihn. Wird bei jeder Neuanordnung erneut gerufen.
(function () {
  "use strict";
  const KEY = "vector_raster";          // gespeicherte Anordnungen, wird auch mit dem Konto abgeglichen
  const TEILE = {};                     // angemeldete Widgets
  let brett = null, raster = null, geist = null;
  let GERAET = "pc", SEITE = "fokus", MODUS = "normal", EDIT = false;
  let plan = {};                        // plan[geraet][modus][seite] = [[id,x,y,w,h], …]
  let standard = {};                    // Auslieferungszustand, für „zurücksetzen“
  let beimAendern = null;               // Rückruf, wenn sich etwas geändert hat (zum Sichern)

  const SPALTEN = () => (GERAET === "pc" ? 16 : 6);
  const ZEILEN = () => (GERAET === "pc" ? 9 : 14);

  // --- Anordnung lesen und schreiben ---------------------------------------------------------
  function liste() {
    const g = plan[GERAET] || (plan[GERAET] = {});
    const m = g[MODUS] || (g[MODUS] = {});
    if (!m[SEITE]) {
      const s = ((standard[GERAET] || {})[MODUS] || {})[SEITE]
            || ((standard[GERAET] || {}).normal || {})[SEITE] || [];
      m[SEITE] = JSON.parse(JSON.stringify(s));
    }
    return m[SEITE];
  }
  function setze(v) { plan[GERAET][MODUS][SEITE] = v; sichern(); }
  function sichern() {
    try { localStorage.setItem(KEY, JSON.stringify(plan)); } catch (e) {}
    if (beimAendern) try { beimAendern(plan); } catch (e) {}
  }
  function laden() {
    try { const v = JSON.parse(localStorage.getItem(KEY) || "null"); if (v && typeof v === "object") plan = v; }
    catch (e) { plan = {}; }
  }

  // --- Zeichnen -------------------------------------------------------------------------------
  function zelle() {
    const r = brett.getBoundingClientRect();
    return { w: r.width / SPALTEN(), h: r.height / ZEILEN() };
  }
  function male() {
    if (!brett) return;
    [...brett.querySelectorAll(".jw")].forEach((e) => e.remove());
    const c = zelle();
    if (raster) raster.style.backgroundSize = c.w + "px " + c.h + "px";
    liste().forEach((it, i) => {
      const [id, x, y, w, h] = it, d = TEILE[id];
      if (!d) return;                                  // unbekanntes Widget (alte Anordnung) einfach auslassen
      const el = document.createElement("div");
      el.className = "jw" + (d.klasse ? " " + d.klasse : "");
      el.dataset.i = i; el.dataset.id = id;
      el.style.left = x * c.w + 3 + "px"; el.style.top = y * c.h + 3 + "px";
      el.style.width = w * c.w - 6 + "px"; el.style.height = h * c.h - 6 + "px";
      brett.appendChild(el);
      try { d.bau(el, { w, h }); } catch (e) {}
      el.insertAdjacentHTML("beforeend",
        '<div class="jw-x" title="Entfernen">✕</div><div class="jw-gr">' + w + "×" + h + "</div>" +
        ["n", "s", "w", "e", "nw", "ne", "sw", "se"].map((k) => '<div class="jw-g ' + k + '" data-k="' + k + '"></div>').join(""));
    });
    if (window.JRasterNachMalen) try { window.JRasterNachMalen(); } catch (e) {}
  }

  // --- Schieben und Größe ziehen ---------------------------------------------------------------
  let akt = null;
  function frei(x, y, w, h, ausser) {
    if (x < 0 || y < 0 || x + w > SPALTEN() || y + h > ZEILEN()) return false;
    return !liste().some((it, i) => i !== ausser &&
      x < it[1] + it[3] && x + w > it[1] && y < it[2] + it[4] && y + h > it[2]);
  }
  function ersterPlatz(w, h) {
    for (let y = 0; y <= ZEILEN() - h; y++) for (let x = 0; x <= SPALTEN() - w; x++)
      if (frei(x, y, w, h, -1)) return [x, y];
    return null;
  }
  function runter(e) {
    if (!EDIT) return;
    const el = e.target.closest(".jw"); if (!el) return;
    if (e.target.closest(".jw-x")) {
      const a = liste().slice(); a.splice(+el.dataset.i, 1); setze(a); male(); return;
    }
    e.preventDefault();
    const it = liste()[+el.dataset.i]; if (!it) return;
    const g = e.target.closest(".jw-g");
    akt = { el, i: +el.dataset.i, c: zelle(), art: g ? "groesse" : "schieben", kante: g ? g.dataset.k : "",
            x: it[1], y: it[2], w: it[3], h: it[4], sx: e.clientX, sy: e.clientY };
    el.classList.add("jw-zieht");
    try { el.setPointerCapture(e.pointerId); } catch (x) {}
    if (geist) geist.style.display = "block";
  }
  function bewegt(e) {
    if (!akt) return;
    const d = TEILE[akt.el.dataset.id] || {}, min = d.min || [2, 2];
    if (akt.art === "groesse") {
      const dx = Math.round((e.clientX - akt.sx) / akt.c.w), dy = Math.round((e.clientY - akt.sy) / akt.c.h);
      const k = akt.kante;
      let x = akt.x, y = akt.y, w = akt.w, h = akt.h;
      if (k.includes("e")) w = akt.w + dx;
      if (k.includes("w")) { x = akt.x + dx; w = akt.w - dx; }
      if (k.includes("s")) h = akt.h + dy;
      if (k.includes("n")) { y = akt.y + dy; h = akt.h - dy; }
      if (w < min[0]) { if (k.includes("w")) x = akt.x + akt.w - min[0]; w = min[0]; }
      if (h < min[1]) { if (k.includes("n")) y = akt.y + akt.h - min[1]; h = min[1]; }
      x = Math.max(0, Math.min(SPALTEN() - w, x)); y = Math.max(0, Math.min(ZEILEN() - h, y));
      akt.nx = x; akt.ny = y; akt.nw = Math.min(w, SPALTEN() - x); akt.nh = Math.min(h, ZEILEN() - y);
      akt.el.style.left = x * akt.c.w + 3 + "px"; akt.el.style.top = y * akt.c.h + 3 + "px";
      akt.el.style.width = akt.nw * akt.c.w - 6 + "px"; akt.el.style.height = akt.nh * akt.c.h - 6 + "px";
    } else {
      const px = akt.x * akt.c.w + (e.clientX - akt.sx), py = akt.y * akt.c.h + (e.clientY - akt.sy);
      akt.el.style.left = px + 3 + "px"; akt.el.style.top = py + 3 + "px";
      akt.nw = akt.w; akt.nh = akt.h;
      akt.nx = Math.max(0, Math.min(SPALTEN() - akt.w, Math.round(px / akt.c.w)));
      akt.ny = Math.max(0, Math.min(ZEILEN() - akt.h, Math.round(py / akt.c.h)));
    }
    const gr = akt.el.querySelector(".jw-gr"); if (gr) gr.textContent = akt.nw + "×" + akt.nh;
    if (!geist) return;
    const ok = frei(akt.nx, akt.ny, akt.nw, akt.nh, akt.i);
    geist.style.left = akt.nx * akt.c.w + 3 + "px"; geist.style.top = akt.ny * akt.c.h + 3 + "px";
    geist.style.width = akt.nw * akt.c.w - 6 + "px"; geist.style.height = akt.nh * akt.c.h - 6 + "px";
    geist.classList.toggle("jw-nein", !ok);
  }
  function hoch() {
    if (!akt) return;
    if (akt.nx != null && frei(akt.nx, akt.ny, akt.nw, akt.nh, akt.i)) {
      const a = liste().slice();
      a[akt.i] = [a[akt.i][0], akt.nx, akt.ny, akt.nw, akt.nh];
      setze(a);
    }
    akt.el.classList.remove("jw-zieht");
    if (geist) geist.style.display = "none";
    akt = null; male();
  }

  // --- Katalog ---------------------------------------------------------------------------------
  function katalogHtml() {
    const drin = new Set(liste().map((a) => a[0]));
    const offen = Object.keys(TEILE).filter((k) => !drin.has(k) && !TEILE[k].versteckt);
    if (!offen.length) return '<div class="jk-leer">Alles schon auf dem Brett. Wirf etwas raus, dann taucht es hier wieder auf.</div>';
    return offen.map((k) => {
      const w = Math.min(TEILE[k].w, SPALTEN()), h = Math.min(TEILE[k].h, ZEILEN());
      return '<div class="jk-i" data-add="' + k + '">' + TEILE[k].t + "<small>" + w + "×" + h + "</small></div>";
    }).join("");
  }
  function dazu(id) {
    const d = TEILE[id]; if (!d) return false;
    let w = Math.min(d.w, SPALTEN()), h = Math.min(d.h, ZEILEN());
    let p = ersterPlatz(w, h);
    if (!p && d.min) { w = d.min[0]; h = d.min[1]; p = ersterPlatz(w, h); }
    if (!p) return false;
    const a = liste().slice(); a.push([id, p[0], p[1], w, h]); setze(a); male();
    return true;
  }

  // --- Öffentlich ------------------------------------------------------------------------------
  const api = {
    registriere(id, d) { TEILE[id] = Object.assign({ t: id, w: 4, h: 2, min: [2, 2], bau() {} }, d); },
    standard(s) { standard = s || {}; },
    start(o) {
      brett = o.board; raster = o.raster || null; geist = o.ghost || null;
      GERAET = o.geraet || "pc"; SEITE = o.seite || "fokus"; MODUS = o.modus || "normal";
      beimAendern = o.onChange || null;
      laden();
      brett.addEventListener("pointerdown", runter);
      brett.addEventListener("pointermove", bewegt);
      brett.addEventListener("pointerup", hoch);
      brett.addEventListener("pointercancel", hoch);
      addEventListener("resize", male);
      male();
    },
    seite(v) { if (v && v !== SEITE) { SEITE = v; male(); } return SEITE; },
    modus(v) { if (v != null && v !== MODUS) { MODUS = v || "normal"; male(); } return MODUS; },
    geraet(v) { if (v && v !== GERAET) { GERAET = v; male(); } return GERAET; },
    edit(an) {
      EDIT = !!an;
      document.body.classList.toggle("jw-edit", EDIT);
      male();
      return EDIT;
    },
    editAn: () => EDIT,
    katalog: katalogHtml,
    dazu,
    anordnung: () => plan,
    setzeAnordnung(p) { if (p && typeof p === "object") { plan = p; sichern(); male(); } },
    zuruecksetzen() {
      if (plan[GERAET] && plan[GERAET][MODUS]) delete plan[GERAET][MODUS][SEITE];
      sichern(); male();
    },
    neu: male,
    mitte() {                                   // wo sitzt er gerade? (für den Datenstrang)
      const el = brett && brett.querySelector(".jw.jw-kugel");
      if (!el) return null;
      const r = el.getBoundingClientRect(), b = brett.getBoundingClientRect();
      return { x: r.left - b.left + r.width / 2, y: r.top - b.top + r.height / 2, r: Math.min(r.width, r.height) / 2 };
    },
  };
  window.JRaster = api;
})();
