// Verbindet das HUD mit dem Raster: jedes bekannte HUD-Element wird als Widget angemeldet und beim
// Einschalten aus seiner festen Position ins Raster geholt. Es wird nichts nachgebaut – dieselben
// Elemente, dieselben IDs, deshalb füllt hud.js sie unverändert weiter.
// Abschalten gibt alles an seinen alten Platz zurück (Einstellungen → Anzeige → Modulares HUD).
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const R = window.JRaster;
  if (!R || !$("jbrett")) return;

  // --- Welche Widgets es gibt ------------------------------------------------------------------
  // holt: die Elemente, die das Widget übernimmt. fliess: untereinander statt übereinander.
  const T = [
    // Fokus
    ["f_kugel",   "",            ["#f-sph"],                 6, 6, [3, 3], "jw-kugel", false, ["fokus"]],
    ["f_name",    "",            ["#f-name", "#f-state"],    4, 2, [3, 1], "jw-mitte", true,  ["fokus"]],
    ["f_talk",    "GESPRÄCH",    ["#f-talk"],                8, 3, [4, 2], "", true,          ["fokus"]],
    // Info
    ["i_kugel",   "",            ["#i-sph"],                 6, 5, [3, 3], "jw-kugel", false, ["info"]],
    ["i_name",    "",            ["#i-name", "#i-state"],    4, 2, [3, 1], "jw-mitte", true,  ["info"]],
    ["i_qb",      "SCHNELLSTART", ["#qb"],                   4, 2, [2, 1], "", true,          ["info"]],
    ["i_heute",   "",            ["#k-heute"],               4, 2, [2, 2], "", false,         ["info", "fokus"]],
    ["i_wetter",  "",            ["#k-wetter"],              4, 3, [2, 2], "", false,         ["info", "fokus"]],
    ["i_system",  "",            ["#k-system"],              4, 3, [2, 2], "", false,         ["info", "fokus"]],
    ["i_handy",   "",            ["#k-handy"],               4, 2, [2, 2], "", false,         ["info", "fokus", "steuern"]],
    ["i_ets2",    "",            ["#i-ets2"],                4, 4, [3, 3], "", false,         ["info", "fokus"]],
    ["i_termine", "",            ["#k-termine"],             4, 3, [2, 2], "", false,         ["info", "fokus"]],
    ["i_lage",    "",            ["#k-lage"],                4, 2, [2, 2], "", false,         ["info", "fokus"]],
    ["i_fuer",    "",            ["#info-fuer-card"],        4, 3, [2, 2], "", false,         ["info", "fokus"]],
    ["i_verlauf", "",            ["#k-verlauf"],             4, 3, [2, 2], "", false,         ["info", "fokus"]],
    // Steuern
    ["s_kugel",   "",            ["#s-sph"],                 4, 4, [3, 3], "jw-kugel", false, ["steuern"]],
    ["s_name",    "",            ["#s-name", "#s-state"],    4, 2, [3, 1], "jw-mitte", true,  ["steuern"]],
    ["s_talk",    "GESPRÄCH",    [".st-talk"],               4, 3, [3, 2], "", true,          ["steuern"]],
    ["s_bar",     "",            ["#ph-bar"],                8, 2, [3, 1], "", true,          ["steuern"]],
    ["s_now",     "LÄUFT AM HANDY", ["#ph-now"],             8, 2, [3, 2], "", true,          ["steuern"]],
    ["s_tiles",   "HANDY STEUERN", ["#ph-tiles"],            8, 5, [3, 2], "", true,          ["steuern"]],
    ["s_vol",     "LAUTSTÄRKE AM HANDY", ["#ph-vol"],        4, 3, [3, 2], "", true,          ["steuern"]],
    ["s_ter",     "NÄCHSTE TERMINE", ["#ph-ter"],            4, 3, [3, 2], "", true,          ["steuern"]],
    ["s_cmd",     "BEFEHL ANS HANDY", [".st-cmd"],           4, 2, [3, 1], "", true,          ["steuern"]],
    // Lage
    ["l_karte",   "",            ["#lmap", "#lorb", ".lhud"], 10, 7, [4, 3], "jw-karte", false, ["lage"]],
    ["l_top",     "",            ["#ltop"],                  6, 2, [3, 1], "", true,          ["lage"]],
    ["l_cards",   "",            ["#lcards"],                4, 7, [3, 2], "", true,          ["lage"]],
    ["l_jar",     "",            ["#ljar"],                  6, 2, [3, 1], "", true,          ["lage"]],
    ["l_side",    "",            [".side"],                  4, 9, [3, 3], "", true,          ["lage"]],
    ["l_orte",    "",            ["#lorte"],                 4, 2, [3, 1], "", true,          ["lage"]],
  ];
  const NAMEN = {
    f_kugel: "Vector", f_name: "Name und Zustand", f_talk: "Gespräch",
    i_kugel: "Vector", i_name: "Name und Zustand", i_qb: "Schnellstart", i_heute: "Uhrzeit",
    i_wetter: "Wetter", i_system: "PC-System", i_handy: "Dein Handy", i_ets2: "ETS2-Fahrt",
    i_termine: "Termine", i_lage: "Lage", i_fuer: "Für dich", i_verlauf: "Verlauf",
    s_kugel: "Vector", s_name: "Name und Zustand", s_talk: "Gespräch", s_bar: "Handy-Status",
    s_now: "Läuft am Handy", s_tiles: "Handy steuern", s_vol: "Lautstärke", s_ter: "Termine am Handy",
    s_cmd: "Befehl ans Handy",
    l_karte: "Globus und Karte", l_top: "Überschrift und Filter", l_cards: "Meldungen",
    l_jar: "Seine Einschätzung", l_side: "Vector und Briefing", l_orte: "Deine Orte",
  };
  T.forEach((w) => {
    const [id, titel, holt, bw, bh, min, klasse, fliess, seiten] = w;
    R.registriere(id, {
      t: NAMEN[id] || titel || id, kopf: titel, w: bw, h: bh, min, klasse, seiten,
      ohneTitel: !titel,
      bau(inhalt) { if (fliess) [...inhalt.children].forEach((k) => k.classList.add("jw-fliess")); },
      holt,
    });
  });

  // --- Auslieferungs-Anordnung -------------------------------------------------------------------
  const STD = {
    pc: {
      normal: {
        fokus: [["i_system", 0, 0, 4, 3], ["i_wetter", 0, 3, 4, 3], ["i_verlauf", 0, 6, 4, 3],
                ["f_kugel", 5, 0, 6, 6], ["f_name", 5, 6, 6, 1], ["f_talk", 4, 7, 8, 2],
                ["i_termine", 12, 0, 4, 3], ["i_handy", 12, 3, 4, 2], ["i_fuer", 12, 5, 4, 4]],
        info:  [["i_heute", 0, 0, 4, 2], ["i_wetter", 0, 2, 4, 3], ["i_system", 0, 5, 4, 3],
                ["i_kugel", 5, 0, 6, 5], ["i_name", 5, 5, 6, 1], ["i_qb", 4, 6, 8, 2],
                ["i_termine", 12, 0, 4, 3], ["i_fuer", 12, 3, 4, 3], ["i_lage", 12, 6, 4, 2]],
        steuern: [["s_kugel", 0, 0, 4, 4], ["s_name", 0, 4, 4, 1], ["s_talk", 0, 5, 4, 3],
                  ["s_bar", 4, 0, 8, 2], ["s_now", 4, 2, 8, 2], ["s_tiles", 4, 4, 8, 5],
                  ["s_vol", 12, 0, 4, 3], ["s_ter", 12, 3, 4, 3], ["s_cmd", 12, 6, 4, 2]],
        lage:  [["l_top", 0, 0, 7, 2], ["l_jar", 7, 0, 5, 2], ["l_side", 12, 0, 4, 9],
                ["l_karte", 0, 2, 8, 7], ["l_cards", 8, 2, 4, 7]],
      },
      gaming: {
        fokus: [["i_system", 0, 0, 4, 3], ["i_handy", 0, 3, 4, 2], ["i_verlauf", 0, 5, 4, 4],
                ["f_kugel", 5, 0, 6, 6], ["f_name", 5, 6, 6, 1], ["f_talk", 4, 7, 8, 2],
                ["i_fuer", 12, 0, 4, 4], ["i_lage", 12, 4, 4, 2], ["i_termine", 12, 6, 4, 3]],
      },
      ets2: {
        fokus: [["i_ets2", 0, 0, 5, 5], ["i_system", 0, 5, 5, 4],
                ["f_kugel", 6, 0, 5, 5], ["f_name", 6, 5, 5, 1], ["f_talk", 5, 6, 7, 3],
                ["i_lage", 12, 0, 4, 2], ["i_wetter", 12, 2, 4, 3], ["i_handy", 12, 5, 4, 2]],
      },
      schule: {
        fokus: [["i_heute", 0, 0, 4, 2], ["i_termine", 0, 2, 4, 3],
                ["f_kugel", 5, 1, 6, 5], ["f_name", 5, 6, 6, 1],
                ["i_handy", 12, 0, 4, 2], ["i_wetter", 12, 2, 4, 3]],
      },
    },
  };
  R.standard(STD);

  // --- An- und Abschalten --------------------------------------------------------------------------
  let an = false;
  function schalter(v) {
    an = !!v;
    R.an(an);
    const tb = $("typebar"); if (tb) tb.classList.toggle("jw-weg", false);
    if (!an) R.edit(false);
    const b = $("jedit"); if (b) b.style.display = an ? "" : "none";
    if (an) {
      R.seite(window.JHudCur ? window.JHudCur() : "fokus");
      R.modus((window.JModi && window.JModi.aktuell && window.JModi.aktuell()) || "normal");
    }
  }

  // Bearbeiten-Knopf oben in der Leiste
  const top = document.querySelector(".top");
  if (top) {
    const b = document.createElement("div");
    b.id = "jedit"; b.className = "jw-edit-btn"; b.title = "Widgets anordnen";
    b.textContent = "✎ ANORDNEN";
    b.style.display = "none";
    top.appendChild(b);
    b.addEventListener("click", () => {
      const e = R.edit(!R.editAn());
      b.classList.toggle("on", e);
      b.textContent = e ? "✓ FERTIG" : "✎ ANORDNEN";
      kat();
    });
  }
  function kat() {
    const k = $("jkat"); if (!k) return;
    k.innerHTML = "<h4>WIDGET HINZUFÜGEN</h4>" + R.katalog() +
      '<div class="jk-i" data-reset style="border-color:rgba(255,160,60,.5);color:#ffc98a">Diese Seite zurücksetzen<small>↺</small></div>';
  }
  const kbox = $("jkat");
  if (kbox) kbox.addEventListener("click", (e) => {
    if (e.target.closest("[data-reset]")) { R.zuruecksetzen(); kat(); return; }
    const i = e.target.closest("[data-add]"); if (!i) return;
    if (!R.dazu(i.dataset.add)) { i.textContent = "kein Platz frei"; setTimeout(kat, 1300); return; }
    kat();
  });
  window.JRasterNachMalen = () => { if (R.editAn()) kat(); };

  // Seite und Modus mitziehen
  const altMode = window.JHudMode;
  window.JHudMode = (m, save) => { const r = altMode ? altMode(m, save) : undefined; if (an) R.seite(m); return r; };
  const beobachter = new MutationObserver(() => { if (an) R.seite(document.body.dataset.mode || "fokus"); });
  beobachter.observe(document.body, { attributes: true, attributeFilter: ["data-mode"] });

  // Anordnung mit dem Konto abgleichen
  window.JRasterSync = (p) => { try { window.PC.post("settings_save", { values: { hud_raster_plan: JSON.stringify(p) } }); } catch (e) {} };
  R.start({ board: $("jbrett"), raster: $("jraster"), ghost: $("jgeist"), geraet: "pc",
            seite: "fokus", modus: "normal",
            onChange: (p) => { clearTimeout(window.__jrs); window.__jrs = setTimeout(() => window.JRasterSync(p), 1500); } });

  // Einstellung lesen (und auf Änderungen reagieren)
  let S = {}; try { S = window.PC.get("settings") || {}; } catch (e) {}
  if (S.hud_raster_plan) { try { R.setzeAnordnung(JSON.parse(S.hud_raster_plan)); } catch (e) {} }
  schalter(!!S.hud_raster);
  window.JHudRaster = { an: schalter, edit: (v) => R.edit(v) };
})();
