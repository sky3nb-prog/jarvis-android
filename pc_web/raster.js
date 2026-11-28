// Modulares HUD: Widgets liegen in einem Raster, lassen sich schieben, in der Größe ziehen, rauswerfen
// und wieder dazuholen. Jeder Modus (normal, gaming, schule, ets2 …) hat seine eigene Anordnung pro Seite.
// Dieselbe Datei läuft am PC (pc_web) und am Handy (assets/web) – bitte synchron halten.
//
// Wichtig: Ein Widget baut seinen Inhalt normalerweise NICHT neu, sondern übernimmt das vorhandene Element
// aus dem HUD (Angabe "holt"). Dadurch bleiben alle IDs erhalten und alles, was das HUD dort hineinschreibt,
// funktioniert unverändert weiter. Beim Abschalten wandern die Elemente an ihren alten Platz zurück.
//
//   JRaster.registriere(id, { t:"Wetter", w:4, h:2, min:[2,2], holt:["#k-wetter"] })
//   JRaster.registriere(id, { t:"Eigen",  w:4, h:2, bau(el){ el.innerHTML = "…" } })
//   JRaster.start({ board, raster, ghost, geraet, seite, modus, onChange })
//   JRaster.an(true/false)      Raster an- oder abschalten (Elemente zurückgeben)
//   JRaster.edit(true/false)    Bearbeiten
(function () {
  "use strict";
  const KEY = "vector_raster";
  const TEILE = {};
  let brett = null, raster = null, geist = null, lager = null;
  let GERAET = "pc", SEITE = "fokus", MODUS = "normal", EDIT = false, AN = false;
  let plan = {}, standard = {}, beimAendern = null;

  const SPALTEN = () => (GERAET === "pc" ? 16 : 6);
  const ZEILEN = () => (GERAET === "pc" ? 9 : 14);

  // --- Anordnung -------------------------------------------------------------------------------
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

  // --- Übernommene Elemente zwischenlagern -------------------------------------------------------
  function lagerBox() {
    if (!lager) {
      lager = document.createElement("div");
      lager.id = "jw-lager";
      lager.style.cssText = "position:absolute;left:-99999px;top:0;width:1px;height:1px;overflow:hidden";
      document.body.appendChild(lager);
    }
    return lager;
  }
  // Merkt sich, wo ein Element herkam, damit es beim Abschalten zurückkann
  const heimat = new Map();
  function holeElement(sel) {
    const el = document.querySelector(sel) || lagerBox().querySelector(sel);
    if (!el) return null;
    if (!heimat.has(el) && el.parentElement && el.parentElement !== lager) {
      heimat.set(el, { eltern: el.parentElement, vor: el.nextSibling });
    }
    return el;
  }
  function allesEinlagern() {
    while (wacht.length) { try { wacht.pop().disconnect(); } catch (e) {} }
    [...brett.querySelectorAll(".jw")].forEach((w) => {
      [...w.querySelectorAll(".jw-holt > *")].forEach((k) => lagerBox().appendChild(k));
      w.remove();
    });
  }
  function allesHeim() {
    heimat.forEach((h, el) => {
      try { h.eltern.insertBefore(el, h.vor && h.vor.parentElement === h.eltern ? h.vor : null); } catch (e) {}
      el.classList.remove("jw-adopt");
    });
    heimat.clear();
  }

  // --- Zeichnen ---------------------------------------------------------------------------------
  function zelle() {
    const r = brett.getBoundingClientRect();
    return { w: r.width / SPALTEN(), h: r.height / ZEILEN() };
  }
  function kasten(el, x, y, w, h, c) {
    el.style.left = x * c.w + 3 + "px"; el.style.top = y * c.h + 3 + "px";
    el.style.width = w * c.w - 6 + "px"; el.style.height = h * c.h - 6 + "px";
  }
  function male(vorschau) {
    if (!brett || !AN) return;
    allesEinlagern();
    const c = zelle();
    if (raster) raster.style.backgroundSize = c.w + "px " + c.h + "px";
    (vorschau || liste()).forEach((it, i) => {
      const [id, x, y, w, h] = it, d = TEILE[id];
      if (!d) return;
      const el = document.createElement("div");
      el.className = "jw" + (d.klasse ? " " + d.klasse : "");
      el.dataset.i = i; el.dataset.id = id;
      kasten(el, x, y, w, h, c);
      if (d.t && !d.ohneTitel) el.innerHTML = '<div class="jw-t">' + d.t + "<s></s></div>";
      const inhalt = document.createElement("div");
      inhalt.className = "jw-holt";
      el.appendChild(inhalt);
      brett.appendChild(el);
      (d.holt || []).forEach((sel) => {
        const k = holeElement(sel);
        if (k) { k.classList.add("jw-adopt"); inhalt.appendChild(k); }
      });
      if (d.bau) try { d.bau(inhalt, { w, h }); } catch (e) {}
      if (d.klasse && d.klasse.indexOf("jw-kugel") >= 0) quadrat(inhalt);
      leerPruefen(el, inhalt);
      el.insertAdjacentHTML("beforeend",
        '<div class="jw-x" title="Entfernen">✕</div><div class="jw-gr">' + w + "×" + h + "</div>" +
        ["n", "s", "w", "e", "nw", "ne", "sw", "se"].map((k) => '<div class="jw-g ' + k + '" data-k="' + k + '"></div>').join(""));
    });
    if (window.JRasterNachMalen) try { window.JRasterNachMalen(); } catch (e) {}
  }

  // Kugeln bleiben rund: das übernommene Element bekommt die größte quadratische Fläche im Widget
  function quadrat(inhalt) {
    const r = inhalt.getBoundingClientRect();
    const k = inhalt.firstElementChild;
    if (!k) return;
    let rest = 0;
    [...inhalt.children].slice(1).forEach((e) => { rest += e.offsetHeight || 0; });
    const s = Math.max(40, Math.min(r.width, r.height - rest));
    k.style.setProperty("width", s + "px", "important");
    k.style.setProperty("height", s + "px", "important");
  }

  // Ein Widget, dessen Inhalt das HUD gerade ausgeblendet hat, verschwindet mit – außer beim Anordnen
  const wacht = [];
  function leerPruefen(el, inhalt) {
    const kinder = [...inhalt.children];
    if (!kinder.length) return;
    const schau = () => el.classList.toggle("jw-leer",
      kinder.every((k) => getComputedStyle(k).display === "none"));
    schau();
    const o = new MutationObserver(schau);
    kinder.forEach((k) => o.observe(k, { attributes: true, attributeFilter: ["style", "class"] }));
    wacht.push(o);
  }

  // --- Live ausweichen ---------------------------------------------------------------------------
  // Das gezogene Widget bekommt seinen Platz, alles andere rückt nach unten und zieht sich danach
  // wieder hoch. Läuft schon WÄHREND des Ziehens, damit man sieht, wie es aussehen wird.
  function ausweichen(arr, iFest, fest) {
    const stoesst = (a, ax, ay, b) => ax < b[1] + b[3] && ax + a[3] > b[1] && ay < b[2] + b[4] && ay + a[4] > b[2];
    const gesetzt = [fest];
    const rest = arr.map((a, i) => ({ a: a.slice(), i })).filter((o) => o.i !== iFest)
      .sort((p, q) => p.a[2] - q.a[2] || p.a[1] - q.a[1]);
    for (const o of rest) {
      const it = o.a; let y = it[2], schutz = 0;
      while (schutz++ < 300) {
        const k = gesetzt.find((p) => stoesst(it, it[1], y, p));
        if (!k) break;
        y = k[2] + k[4];
      }
      it[2] = y; gesetzt.push(it);
    }
    for (let runde = 0; runde < 3; runde++) {
      gesetzt.slice(1).sort((a, b) => a[2] - b[2]).forEach((it) => {
        while (it[2] > 0) {
          const probe = it[2] - 1;
          if (gesetzt.some((p) => p !== it && stoesst(it, it[1], probe, p))) break;
          it[2] = probe;
        }
      });
    }
    if (gesetzt.some((p) => p[2] + p[4] > ZEILEN())) return null;
    const out = arr.map((a) => a.slice());
    out[iFest] = fest;
    rest.forEach((o, idx) => { out[o.i] = gesetzt[idx + 1]; });
    return out;
  }
  function ersterPlatz(w, h) {
    const frei = (x, y) => !liste().some((it) =>
      x < it[1] + it[3] && x + w > it[1] && y < it[2] + it[4] && y + h > it[2]);
    for (let y = 0; y <= ZEILEN() - h; y++) for (let x = 0; x <= SPALTEN() - w; x++) if (frei(x, y)) return [x, y];
    return null;
  }

  // --- Schieben und Größe ziehen ------------------------------------------------------------------
  let akt = null;
  function runter(e) {
    if (!EDIT || !AN) return;
    const el = e.target.closest ? e.target.closest(".jw") : e.target; if (!el) return;
    if (e.target.closest && e.target.closest(".jw-x")) {
      const a = liste().slice(); a.splice(+el.dataset.i, 1); setze(a); male(); return;
    }
    e.preventDefault();
    const it = liste()[+el.dataset.i]; if (!it) return;
    const g = e.target.closest ? e.target.closest(".jw-g") : null;
    akt = { el, i: +el.dataset.i, c: zelle(), art: g ? "groesse" : "schieben", kante: g ? g.dataset.k : "",
            x: it[1], y: it[2], w: it[3], h: it[4], sx: e.clientX, sy: e.clientY,
            vorher: JSON.parse(JSON.stringify(liste())) };
    el.classList.add("jw-zieht");
    document.body.classList.add("jw-zieht-an");
    try { el.setPointerCapture(e.pointerId); } catch (x) {}
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
    } else {
      const px = akt.x * akt.c.w + (e.clientX - akt.sx), py = akt.y * akt.c.h + (e.clientY - akt.sy);
      akt.px = px; akt.py = py;
      akt.nw = akt.w; akt.nh = akt.h;
      akt.nx = Math.max(0, Math.min(SPALTEN() - akt.w, Math.round(px / akt.c.w)));
      akt.ny = Math.max(0, Math.min(ZEILEN() - akt.h, Math.round(py / akt.c.h)));
    }
    // Live: alle anderen schon jetzt dorthin rücken, wo sie beim Loslassen landen würden
    const fest = [akt.vorher[akt.i][0], akt.nx, akt.ny, akt.nw, akt.nh];
    const neu = ausweichen(akt.vorher, akt.i, fest);
    if (neu) {
      akt.vorschau = neu;
      const c = akt.c;
      [...brett.querySelectorAll(".jw")].forEach((w) => {
        const i = +w.dataset.i; if (i === akt.i) return;
        const it = neu[i]; if (!it) return;
        kasten(w, it[1], it[2], it[3], it[4], c);
      });
    }
    // das gezogene Widget hängt am Finger, nicht am Raster
    if (akt.art === "groesse") kasten(akt.el, akt.nx, akt.ny, akt.nw, akt.nh, akt.c);
    else { akt.el.style.left = akt.px + 3 + "px"; akt.el.style.top = akt.py + 3 + "px"; }
    const gr = akt.el.querySelector(".jw-gr"); if (gr) gr.textContent = akt.nw + "×" + akt.nh;
    if (geist) {
      geist.style.display = "block";
      geist.style.left = akt.nx * akt.c.w + 3 + "px"; geist.style.top = akt.ny * akt.c.h + 3 + "px";
      geist.style.width = akt.nw * akt.c.w - 6 + "px"; geist.style.height = akt.nh * akt.c.h - 6 + "px";
      geist.classList.toggle("jw-nein", !neu);
    }
  }
  function hoch(abbruch) {
    if (!akt) return;
    const a = akt; akt = null;
    a.el.classList.remove("jw-zieht");
    document.body.classList.remove("jw-zieht-an");
    if (geist) geist.style.display = "none";
    if (!abbruch && a.vorschau) setze(a.vorschau);
    else plan[GERAET][MODUS][SEITE] = a.vorher;     // zurück auf Anfang
    male();
  }
  addEventListener("keydown", (e) => { if (e.key === "Escape" && akt) hoch(true); });

  // Lange draufbleiben schaltet das Bearbeiten an und nimmt das Widget gleich mit (wie am Startbildschirm)
  let lang = null;
  function langAn(e) {
    if (!AN || EDIT || akt) return;
    const el = e.target.closest(".jw"); if (!el) return;
    const id = el.dataset.id, i = +el.dataset.i, sx = e.clientX, sy = e.clientY, pid = e.pointerId;
    lang = { sx, sy, t: setTimeout(() => {
      lang = null;
      api.edit(true);                                  // male() baut die Widgets neu auf
      const neuEl = brett.querySelector('.jw[data-i="' + i + '"]');
      if (!neuEl || neuEl.dataset.id !== id) return;
      try { navigator.vibrate && navigator.vibrate(15); } catch (x) {}
      runter({ target: neuEl, clientX: sx, clientY: sy, pointerId: pid,
               preventDefault() {}, closest: null });
    }, 420) };
  }
  function langWeg(e) {
    if (!lang) return;
    if (e && e.clientX != null && Math.abs(e.clientX - lang.sx) < 12 && Math.abs(e.clientY - lang.sy) < 12) return;
    clearTimeout(lang.t); lang = null;
  }

  // --- Katalog -------------------------------------------------------------------------------------
  function katalogHtml() {
    const drin = new Set(liste().map((a) => a[0]));
    const offen = Object.keys(TEILE).filter((k) => !drin.has(k) && !TEILE[k].versteckt
      && (!TEILE[k].seiten || TEILE[k].seiten.indexOf(SEITE) >= 0));
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
    if (!p) {                                      // kein Loch frei: oben rein, der Rest rückt
      const a = liste().slice(); a.push([id, 0, 0, w, h]);
      const neu = ausweichen(a, a.length - 1, [id, 0, 0, w, h]);
      if (!neu) return false;
      setze(neu); male(); return true;
    }
    const a = liste().slice(); a.push([id, p[0], p[1], w, h]); setze(a); male();
    return true;
  }

  const api = {
    registriere(id, d) { TEILE[id] = Object.assign({ t: "", w: 4, h: 2, min: [2, 2] }, d); },
    teile: () => TEILE,
    standard(s) { standard = s || {}; },
    start(o) {
      brett = o.board; raster = o.raster || null; geist = o.ghost || null;
      GERAET = o.geraet || "pc"; SEITE = o.seite || "fokus"; MODUS = o.modus || "normal";
      beimAendern = o.onChange || null;
      laden();
      brett.addEventListener("pointerdown", (e) => { runter(e); langAn(e); });
      brett.addEventListener("pointermove", (e) => { bewegt(e); langWeg(e); });
      brett.addEventListener("pointerup", () => { langWeg(); hoch(false); });
      brett.addEventListener("pointercancel", () => { langWeg(); hoch(true); });
      brett.addEventListener("scroll", () => langWeg(), true);
      addEventListener("resize", () => { if (AN) male(); });
    },
    an(v) {
      if (v === undefined) return AN;
      if (!!v === AN) return AN;
      AN = !!v;
      document.body.classList.toggle("jw-on", AN);
      if (AN) male();
      else { allesEinlagern(); allesHeim(); }
      return AN;
    },
    seite(v) { if (v && v !== SEITE) { SEITE = v; if (AN) male(); } return SEITE; },
    modus(v) { if (v != null && v !== MODUS) { MODUS = v || "normal"; if (AN) male(); } return MODUS; },
    geraet(v) { if (v && v !== GERAET) { GERAET = v; if (AN) male(); } return GERAET; },
    edit(an) { EDIT = !!an; document.body.classList.toggle("jw-edit", EDIT); if (AN) male(); return EDIT; },
    editAn: () => EDIT,
    katalog: katalogHtml,
    dazu,
    anordnung: () => plan,
    setzeAnordnung(p) { if (p && typeof p === "object") { plan = p; sichern(); if (AN) male(); } },
    zuruecksetzen() {
      if (plan[GERAET] && plan[GERAET][MODUS]) delete plan[GERAET][MODUS][SEITE];
      sichern(); if (AN) male();
    },
    neu: () => male(),
    mitte() {
      const el = brett && brett.querySelector(".jw.jw-kugel");
      if (!el) return null;
      const r = el.getBoundingClientRect(), b = brett.getBoundingClientRect();
      return { x: r.left - b.left + r.width / 2, y: r.top - b.top + r.height / 2, r: Math.min(r.width, r.height) / 2 };
    },
  };
  window.JRaster = api;
})();
