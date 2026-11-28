// Verbindet die Handy-Oberfläche mit dem Raster (raster.js). Wie am PC werden die vorhandenen
// Elemente übernommen, nicht nachgebaut – app.js schreibt also unverändert in dieselben IDs.
// An- und Abschalten: Einstellungen → Anzeige → "Modulares HUD".
// Verschieben: lange auf eine Kachel drücken und ziehen. Escape bzw. Finger weg vom Rand bricht ab.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const R = window.JRaster;
  if (!R || !$("jbrett")) return;

  // [id, Kopfzeile, holt, Breite, Höhe, [minB, minH], Klasse, fliess, Seiten]
  const T = [
    // Fokus
    ["h_kugel", "",            ["#sphere-fokus"],              6, 6, [3, 3], "jw-kugel", false, ["fokus"]],
    ["h_name",  "",            ["#f-name", "#fokus-state"],    6, 2, [3, 1], "jw-mitte", true,  ["fokus"]],
    ["h_talk",  "GESPRÄCH",    ["#talkbox"],                   6, 3, [3, 2], "", true,          ["fokus"]],
    ["h_call",  "",            ["#callbtn"],                   6, 1, [2, 1], "jw-mitte", true,  ["fokus"]],
    ["h_type",  "",            ["#v-fokus .typebar"],          6, 1, [3, 1], "jw-mitte", true,  ["fokus"]],
    // Info
    ["h_ikugel", "",           ["#sphere-info", "#i-sub"],     6, 4, [3, 3], "jw-kugel", true,  ["info"]],
    ["h_heute",  "",           ["#k-heute"],                   3, 3, [2, 2], "", false,         ["info", "fokus"]],
    ["h_wetter", "",           ["#k-wetter"],                  3, 3, [2, 2], "", false,         ["info", "fokus"]],
    ["h_pcinfo", "",           ["#info-pc"],                   3, 3, [2, 2], "", false,         ["info", "fokus"]],
    ["h_lage",   "",           ["#k-lage"],                    3, 3, [2, 2], "", false,         ["info", "fokus"]],
    ["h_fuer",   "",           ["#info-fuer-card"],            6, 3, [3, 2], "", false,         ["info", "fokus"]],
    // Lage
    ["h_karte",  "",           ["#lmap", "#lorb", ".lhud", "#ltgt"], 6, 7, [4, 4], "jw-karte", false, ["lage"]],
    ["h_ltop",   "",           ["#ltop"],                      6, 2, [3, 1], "", true,          ["lage"]],
    ["h_ljar",   "",           ["#ljar"],                      6, 2, [3, 1], "", true,          ["lage"]],
    ["h_lcards", "",           ["#lcards"],                    6, 3, [3, 2], "", true,          ["lage"]],
    ["h_lorte",  "",           ["#lorte"],                     6, 2, [3, 1], "", true,          ["lage"]],
    // Steuern
    ["h_skugel", "",           ["#sphere-steuern", "#st-sub"], 6, 3, [2, 2], "jw-kugel", true,  ["steuern"]],
    ["h_pcbar",  "",           ["#pcbar"],                     6, 2, [3, 1], "", true,          ["steuern"]],
    ["h_handy",  "",           ["#h-ghandy", "#h-tiles"],      6, 5, [3, 2], "", true,          ["steuern"]],
    ["h_now",    "",           ["#h-gpc", "#pc-now"],          6, 2, [3, 2], "", true,          ["steuern"]],
    ["h_pct",    "",           ["#h-pctiles"],                 6, 5, [3, 2], "", true,          ["steuern"]],
    ["h_wave",   "WAVE LINK",  ["#wl-head", "#wl"],            6, 3, [3, 2], "", true,          ["steuern"]],
    ["h_schnell", "",          ["#h-gschnell", "#h-stiles"],   6, 3, [3, 2], "", true,          ["steuern"]],
  ];
  const NAMEN = {
    h_kugel: "Vector", h_name: "Name und Zustand", h_talk: "Gespräch", h_call: "Gespräch starten",
    h_type: "Schreiben", h_ikugel: "Vector", h_heute: "Uhrzeit", h_wetter: "Wetter",
    h_pcinfo: "PC zuhause", h_lage: "Lage", h_fuer: "Für dich",
    h_karte: "Globus und Karte", h_ltop: "Überschrift und Filter", h_ljar: "Seine Einschätzung",
    h_lcards: "Meldungen", h_lorte: "Deine Orte",
    h_skugel: "Vector", h_pcbar: "PC-Leiste", h_handy: "Handy steuern", h_now: "Läuft am PC",
    h_pct: "PC steuern", h_wave: "Wave Link", h_schnell: "Schnell",
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

  const STD = {
    handy: {
      normal: {
        fokus:   [["h_kugel", 0, 0, 6, 6], ["h_name", 0, 6, 6, 1], ["h_talk", 0, 7, 6, 3],
                  ["h_call", 0, 10, 6, 1], ["h_type", 0, 11, 6, 1]],
        info:    [["h_ikugel", 0, 0, 6, 4], ["h_heute", 0, 4, 3, 3], ["h_wetter", 3, 4, 3, 3],
                  ["h_pcinfo", 0, 7, 3, 3], ["h_lage", 3, 7, 3, 3], ["h_fuer", 0, 10, 6, 3]],
        lage:    [["h_karte", 0, 0, 6, 7], ["h_ltop", 0, 7, 6, 2], ["h_ljar", 0, 9, 6, 2],
                  ["h_lcards", 0, 11, 6, 3]],
        steuern: [["h_pcbar", 0, 0, 6, 2], ["h_handy", 0, 2, 6, 5], ["h_now", 0, 7, 6, 2],
                  ["h_pct", 0, 9, 6, 5]],
      },
      schule: {
        fokus:   [["h_heute", 0, 0, 6, 2], ["h_kugel", 0, 2, 6, 5], ["h_name", 0, 7, 6, 1],
                  ["h_talk", 0, 8, 6, 3], ["h_type", 0, 11, 6, 1]],
      },
      gaming: {
        fokus:   [["h_kugel", 0, 0, 6, 6], ["h_name", 0, 6, 6, 1], ["h_pcinfo", 0, 7, 6, 3],
                  ["h_talk", 0, 10, 6, 3]],
      },
    },
  };
  R.standard(STD);

  // --- An- und Abschalten ------------------------------------------------------------------------
  let an = false;
  function seiteJetzt() {
    const v = document.querySelector(".view.active");
    return v ? (v.id || "").replace("v-", "") || "fokus" : "fokus";
  }
  function schalter(v) {
    an = !!v;
    R.an(an);
    if (!an) R.edit(false);
    if (an) {
      R.seite(seiteJetzt());
      R.modus((window.JModi && window.JModi.aktuell && window.JModi.aktuell()) || "normal");
    }
    try { localStorage.setItem("vector_raster_an", an ? "1" : "0"); } catch (e) {}
  }

  // Seitenwechsel mitnehmen
  const beob = new MutationObserver(() => { if (an) R.seite(seiteJetzt()); });
  document.querySelectorAll(".view").forEach((v) =>
    beob.observe(v, { attributes: true, attributeFilter: ["class"] }));

  // Katalog unten einblenden, solange angeordnet wird
  function kat() {
    const k = $("jkat"); if (!k) return;
    k.innerHTML = "<h4>KACHEL HINZUFÜGEN</h4>" + R.katalog() +
      '<div class="jk-i" data-fertig style="border-color:rgba(159,225,203,.5);color:#bfe3d6">Fertig<small>✓</small></div>' +
      '<div class="jk-i" data-reset style="border-color:rgba(255,160,60,.5);color:#ffc98a">Seite zurücksetzen<small>↺</small></div>';
  }
  const kbox = $("jkat");
  if (kbox) kbox.addEventListener("click", (e) => {
    if (e.target.closest("[data-fertig]")) { R.edit(false); return; }
    if (e.target.closest("[data-reset]")) { R.zuruecksetzen(); kat(); return; }
    const i = e.target.closest("[data-add]"); if (!i) return;
    if (!R.dazu(i.dataset.add)) { i.textContent = "kein Platz frei"; setTimeout(kat, 1300); return; }
    kat();
  });
  window.JRasterNachMalen = () => { if (R.editAn()) kat(); };

  // Alles, was kein Widget übernimmt, verschwindet solange – außer den Bedienknöpfen oben
  document.querySelectorAll("#v-fokus .roundbtn, #v-fokus .switch, #v-info .topbar")
    .forEach((e) => e.classList.add("jw-bleibt"));

  R.start({ board: $("jbrett"), raster: $("jraster"), ghost: $("jgeist"), geraet: "handy",
            seite: seiteJetzt(), modus: "normal" });

  let start = false;
  try { start = localStorage.getItem("vector_raster_an") === "1"; } catch (e) {}
  schalter(start);
  window.JHandyRaster = { an: schalter, ist: () => an, edit: (v) => R.edit(v) };
})();
