// Lage-Seite: echtes Satellitenbild (Esri) als 3D-Erdkugel, die beim Reinzoomen zur Karte wird (MapLibre),
// Tag und Nacht live mit weicher Dämmerung, Brennpunkte, Lieblingsorte und die Jarvis-Tour (fliegt von Punkt zu Punkt).
(function () {
  const $ = (id) => document.getElementById(id);
  // Fadenkreuz-Elemente merken (sie hängen später an der Karte und sind dann nicht immer im Dokument)
  const TGT = document.getElementById("ltgt"), TGK = document.getElementById("ltgk"), TGN = document.getElementById("ltgn");
  const A = window.Android || null;
  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  const COL = { konflikt: "#ff5a4a", politik: "#3cc8ff", wirtschaft: "#6effcd", katastrophe: "#ff9a3c", wetter: "#9ad8ff",
    gesellschaft: "#d7a8ff", sport: "#8cff8c", wissenschaft: "#7af0ff", lokal: "#ffd678" };
  const ZOOM = { punkt: 17, strasse: 16, stadtteil: 14.2, stadt: 11.5, region: 8, land: 5 };
  let P = {}, lastTouch = 0, touring = false, orb = null, cur = -1, homeMk = null, hereMk = null, cluster = null;
  let map = null, data = null, mode = "welt", markers = [], mini = null, place = "";

  // ---------- Tag und Nacht ----------
  function sun(d) {
    const r = Math.PI / 180, n = (d - Date.UTC(2000, 0, 1, 12)) / 864e5, L = (280.46 + .9856474 * n) % 360, g = (357.528 + .9856003 * n) * r;
    const lam = (L + 1.915 * Math.sin(g) + .02 * Math.sin(2 * g)) * r, eps = (23.439 - 4e-7 * n) * r;
    const dec = Math.asin(Math.sin(eps) * Math.sin(lam)), ra = Math.atan2(Math.cos(eps) * Math.sin(lam), Math.cos(lam));
    const gmst = (18.697374558 + 24.06570982441908 * n) % 24;
    let lon = (ra / r - gmst * 15) % 360; if (lon > 180) lon -= 360; if (lon < -180) lon += 360;
    return { lat: dec / r, lon };
  }
  // Fläche, in der die Sonne tiefer als -off Grad steht (off < 0: noch etwas Licht)
  function nightPoly(s, off) {
    const r = Math.PI / 180, dec = s.lat * r, h = -off * r, pts = [];
    const norm = (x) => ((x + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
    for (let lo = -180; lo <= 180; lo += 1) {
      const H = (lo - s.lon) * r, Aa = Math.sin(dec), B = Math.cos(dec) * Math.cos(H), R = Math.hypot(Aa, B), ph = Math.atan2(B, Aa);
      const as = Math.asin(Math.max(-1, Math.min(1, Math.sin(h) / R)));
      const c1 = norm(as - ph), c2 = norm(Math.PI - as - ph);
      const lat = (Math.abs(c1) <= Math.PI / 2 ? c1 : c2) / r;
      pts.push([lo, Math.max(-85, Math.min(85, lat))]);
    }
    const pole = s.lat > 0 ? -85 : 85;
    return { type: "Feature", properties: { off }, geometry: { type: "Polygon", coordinates: [[...pts, [180, pole], [-180, pole], pts[0]]] } };
  }
  // Viele dünne Stufen übereinander = weicher, genauer Übergang (Sonnenuntergang -> bürgerliche -> nautische -> astronomische Dämmerung)
  const STEPS = [-1.2, -0.4, 0.5, 1.5, 3, 4.5, 6, 8, 10, 12, 15];
  const nightData = () => { const s = sun(Date.now()); return { type: "FeatureCollection", features: STEPS.map((o) => nightPoly(s, o)) }; };

  // Beschriftungen als Vektor: stehen immer gerade zum Bildschirm, auf Deutsch
  const NAME = ["coalesce", ["get", "name:de"], ["get", "name"]];
  const HALO = { "text-halo-color": "rgba(0,0,0,.88)", "text-halo-width": 1.5 };
  const VP = { "text-pitch-alignment": "viewport", "text-rotation-alignment": "viewport" };
  const LABELS = [
    { id: "border", type: "line", source: "ofm", "source-layer": "boundary", filter: ["all", ["<=", ["get", "admin_level"], 4], ["!=", ["get", "maritime"], 1]],
      paint: { "line-color": "rgba(255,214,140,.5)", "line-width": ["interpolate", ["linear"], ["zoom"], 1, .6, 6, 1.2], "line-dasharray": [3, 2] } },
    { id: "roads", type: "line", source: "ofm", "source-layer": "transportation", minzoom: 10, filter: ["in", ["get", "class"], ["literal", ["motorway", "trunk", "primary", "secondary"]]],
      paint: { "line-color": ["match", ["get", "class"], "motorway", "rgba(255,190,90,.55)", "trunk", "rgba(255,200,110,.45)", "rgba(255,255,255,.28)"],
        "line-width": ["interpolate", ["exponential", 1.6], ["zoom"], 10, .6, 14, 2.2, 18, 8], "line-blur": .5 } },
    { id: "road-names", type: "symbol", source: "ofm", "source-layer": "transportation_name", minzoom: 14,
      layout: { "symbol-placement": "line", "text-field": NAME, "text-font": ["Noto Sans Regular"], "text-size": ["interpolate", ["linear"], ["zoom"], 14, 10, 18, 13],
        "text-keep-upright": true, "text-rotation-alignment": "map", "text-pitch-alignment": "viewport", "text-max-angle": 30 },
      paint: { "text-color": "#f4ecdc", ...HALO } },
    { id: "poi", type: "symbol", source: "ofm", "source-layer": "poi", minzoom: 15.5, filter: ["<=", ["get", "rank"], 12],
      layout: { "text-field": NAME, "text-font": ["Noto Sans Regular"], "text-size": 11, "text-anchor": "top", "text-offset": [0, .4], "text-max-width": 8, ...VP },
      paint: { "text-color": "#ffe2b0", ...HALO } },
    { id: "places", type: "symbol", source: "ofm", "source-layer": "place", filter: ["in", ["get", "class"], ["literal", ["city", "town", "village", "suburb", "neighbourhood"]]],
      layout: { "text-field": NAME, "text-font": ["match", ["get", "class"], ["city", "town"], ["literal", ["Noto Sans Bold"]], ["literal", ["Noto Sans Regular"]]],
        "text-size": ["interpolate", ["linear"], ["zoom"], 4, ["match", ["get", "class"], "city", 11, "town", 9, 8], 10, ["match", ["get", "class"], "city", 17, "town", 13, 10], 15, ["match", ["get", "class"], "city", 19, "town", 16, 13]],
        "text-transform": ["match", ["get", "class"], ["city", "town"], "uppercase", "none"], "text-letter-spacing": ["match", ["get", "class"], ["city", "town"], .12, 0],
        "text-max-width": 9, "symbol-sort-key": ["get", "rank"], ...VP },
      paint: { "text-color": ["match", ["get", "class"], ["city", "town"], "#ffd678", "#ffffff"], ...HALO, "text-halo-width": 1.6 } },
    { id: "countries", type: "symbol", source: "ofm", "source-layer": "place", maxzoom: 7, filter: ["all", ["==", ["get", "class"], "country"], ["<=", ["get", "rank"], ["step", ["zoom"], 1, 1.6, 2, 2.4, 3, 3.5, 6]]],
      layout: { "text-field": NAME, "text-font": ["Noto Sans Bold"], "text-size": ["interpolate", ["linear"], ["zoom"], 1, 9, 5, 14], "text-transform": "uppercase",
        "text-letter-spacing": .2, "text-max-width": 7, ...VP },
      paint: { "text-color": "rgba(255,236,200,.9)", ...HALO } },
  ];
  const LABEL_IDS = ["road-names", "poi", "places", "countries"];

  // Zoom, bei dem die ganze Erde schön ins Fenster passt (Handy: etwa 1, großer PC-Bildschirm: etwas mehr)
  function worldZoom() { const h = ($("lmap") && $("lmap").clientHeight) || 700; return Math.max(1, Math.log2(h * .36 * 2 * Math.PI / 512)); }

  function init() {
    if (map || !window.maplibregl) return;
    const h = home();
    map = new maplibregl.Map({
      container: "lmap", attributionControl: { compact: true }, maxPitch: 65, fadeDuration: 200, minZoom: .8,
      maxTileCacheSize: 600, cancelPendingTileRequestsWhileZooming: false,
      style: {
        version: 8, projection: { type: "globe" },
        glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
        sources: {
          sat: { type: "raster", tiles: [ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", ESRI.replace("server.", "services.") + "World_Imagery/MapServer/tile/{z}/{y}/{x}"],
            tileSize: 256, maxzoom: 19, attribution: "Esri, Maxar, Earthstar Geographics" },
          ofm: { type: "vector", url: "https://tiles.openfreemap.org/planet", attribution: "OpenFreeMap © OpenMapTiles © OpenStreetMap" },
          night: { type: "geojson", data: nightData() },
        },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#000" } },
          { id: "sat", type: "raster", source: "sat", paint: { "raster-saturation": .08, "raster-contrast": .12, "raster-brightness-max": .97 } },
          { id: "night", type: "fill", source: "night", paint: { "fill-color": "#01040d", "fill-antialias": false,
            "fill-opacity": ["interpolate", ["linear"], ["zoom"], 0, .075, 9, .06, 14, .035] } },
          ...LABELS,
        ],
      },
      center: [h ? h.lon : 10, 30], zoom: worldZoom(),
    });
    setInterval(() => { try { map.getSource("night").setData(nightData()); } catch (e) {} }, 60000);
    map.on("move", readout);
    ["touchstart", "mousedown", "wheel"].forEach((ev) => $("lmap").addEventListener(ev, () => { lastTouch = Date.now(); }, { passive: true }));
    map.on("load", () => { applyPrefs(); document.querySelectorAll("#v-lage .maplibregl-ctrl-attrib").forEach((e) => e.classList.remove("maplibregl-compact-show")); });
    // weit draußen immer gerade von oben (nie schräg auf die ganze Erde)
    map.on("zoomend", () => { if (map.getZoom() < 6 && map.getPitch() > 1 && !map.isMoving()) map.easeTo({ pitch: 0, bearing: 0, duration: 600 }); });
    map.on("zoom", () => { $("v-lage").classList.toggle("far", map.getZoom() < 8); cluster && cluster.getElement().classList.toggle("on", map.getZoom() < 8 && mode === "welt"); });
    orb = $("lorb");
    $("v-lage").classList.add("far");
    try { mini = new window.Sphere3D($("lmini"), 5); mini.state = "speaking"; } catch (e) {}
    loadTle();
    if (data) render(); else homeMarkers();
  }

  function readout() {
    const c = map.getCenter(), z = map.getZoom();
    const ns = c.lat >= 0 ? "N" : "S", ew = c.lng >= 0 ? "E" : "W";
    $("lread").innerHTML = `SAT · LIVE · TAG/NACHT ECHTZEIT<br><b>${Math.abs(c.lat).toFixed(4)} ${ns}  ${Math.abs(c.lng).toFixed(4)} ${ew}</b><br>ZOOM ${z.toFixed(1)}${map.getPitch() > 5 ? " · NEIGUNG " + map.getPitch().toFixed(0) + "°" : ""}`;
  }

  // ---------- Zuhause und "Du bist hier" (aus den Einstellungen, immer aktuell) ----------
  function home() { try { const h = JSON.parse(A && A.home ? A.home() : "null"); return h && h.lat != null ? h : null; } catch (e) { return null; } }
  function here() { try { const h = JSON.parse(A && A.here ? A.here() : "null"); return h && h.lat != null ? h : null; } catch (e) { return null; } }
  function homeMarkers() {
    if (!map) return;
    homeMk && homeMk.remove(); hereMk && hereMk.remove(); homeMk = hereMk = null;
    const h = home(), w = here();
    if (h) { const e = document.createElement("div"); e.className = "lfav"; e.innerHTML = `<span class="lb">Zuhause</span>`; homeMk = new maplibregl.Marker({ element: e }).setLngLat([h.lon, h.lat]).addTo(map); }
    if (w && (!h || km(w.lat, w.lon, h.lat, h.lon) > .3)) { const e = document.createElement("div"); e.className = "lhere"; e.innerHTML = `<span class="lb">Du bist hier</span>`; hereMk = new maplibregl.Marker({ element: e }).setLngLat([w.lon, w.lat]).addTo(map); }
  }
  const km = (a, b, c, d) => { const r = Math.PI / 180, x = (d - b) * r * Math.cos((a + c) / 2 * r), y = (c - a) * r; return Math.hypot(x, y) * 6371; };

  // ---------- Punkte und Karten ----------
  function center() { if (mode === "orte" && data && data.lat != null) return [data.lat, data.lon]; const h = home(); return h ? [h.lat, h.lon] : (data && data.lat != null ? [data.lat, data.lon] : null); }
  function shown() {
    const pts = ((data && data.brennpunkte) || []).map((p, i) => ({ ...p, i }));
    if (mode === "stadt") return pts.filter((p) => p.art === "lokal");
    if (mode === "orte") { const c = center(); return c ? pts.filter((p) => km(p.lat, p.lon, c[0], c[1]) < 150) : pts; }
    return pts;
  }
  function render() {
    if (!data) return;
    const city = (A && A.city && A.city()) || data.stadt || "Leonberg";
    $("seg-stadt").textContent = city.toUpperCase();
    const list = shown();
    $("lnum").textContent = list.length;
    $("lttl").textContent = mode === "stadt" ? city.toUpperCase() + " · LOKAL" : mode === "orte" ? ("LAGE · " + (data.ort || "").toUpperCase()) : mode === "fuer" ? "FÜR DICH · " + ((data.themen || []).slice(0, 3).join(" · ").toUpperCase() || "DEINE THEMEN") : "BRENNPUNKTE WELTWEIT";
    $("lcards").innerHTML = list.map((p) => `<div class="lcd" data-i="${p.i}" style="--c:${COL[p.art] || "#ffa03c"}">
      <div class="k">${p.fuer_dich && p.thema ? "★ " + esc(p.thema).toUpperCase() : (p.art || "").toUpperCase()} · ${esc(p.ort || "")}</div><div class="t">${esc(p.titel)}</div>
      ${p.warum ? `<div class="w">${esc(p.warum)}</div>` : ""}<div class="x">${esc(p.text)}</div>
      ${p.fuer_dich ? `<div class="fb"><span data-f="mehr">＋ mehr davon</span><span data-f="weniger">– weniger</span></div>` : ""}</div>`).join("")
      || `<div class="lcd"><div class="t">Gerade keine Meldungen</div></div>`;
    document.querySelectorAll(".lcd[data-i]").forEach((e) => e.addEventListener("click", () => {
      const p = data.brennpunkte[+e.dataset.i];
      if (cur !== +e.dataset.i && A && A.lageNote && p) A.lageNote("klick", p.titel + (p.thema ? " (" + p.thema + ")" : " (" + (p.art || "") + ", " + (p.ort || "") + ")"));
      toggle(+e.dataset.i);
    }));
    // "mehr davon" / "weniger": Jarvis lernt daraus, was dich interessiert
    document.querySelectorAll(".lcd .fb span").forEach((b) => b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const card = b.closest(".lcd"), p = data.brennpunkte[+card.dataset.i]; if (!p || !A || !A.lageNote) return;
      A.lageNote(b.dataset.f, (p.thema || "") + ": " + p.titel);
      card.querySelector(".fb").innerHTML = b.dataset.f === "mehr" ? "<em>✓ Merke ich mir – mehr davon.</em>" : "<em>✓ Verstanden – weniger davon.</em>";
    }));
    $("lcards").scrollLeft = 0; cur = -1; target(null);
    if (!map) return;
    markers.forEach((m) => m.remove()); markers = []; cluster && cluster.remove(); cluster = null;
    for (const p of list) {
      const e = document.createElement("div"); e.className = "lmk" + (p.art === "lokal" ? " lok" : ""); e.style.color = COL[p.art] || "#ffa03c";
      e.innerHTML = `<span class="lb">${esc(p.ort || p.titel)}</span>`;
      e.addEventListener("click", (ev) => { ev.stopPropagation(); toggle(p.i); });
      markers.push(new maplibregl.Marker({ element: e }).setLngLat([p.lon, p.lat]).addTo(map));
    }
    // weit draußen: alle lokalen Meldungen als ein Punkt "LEONBERG · 5"
    const lok = list.filter((p) => p.art === "lokal"), h = home();
    if (mode === "welt" && lok.length && h) {
      const e = document.createElement("div"); e.className = "lclu" + (map.getZoom() < 8 ? " on" : "");
      e.innerHTML = `<b>${lok.length}</b><span>${esc(city.toUpperCase())}</span>`;
      e.addEventListener("click", (ev) => { ev.stopPropagation(); setMode("stadt"); });
      cluster = new maplibregl.Marker({ element: e }).setLngLat([h.lon, h.lat]).addTo(map);
    }
    homeMarkers(); favorites();
  }
  function favorites() {
    const fav = favList();
    $("lorte").innerHTML = fav.map((f) => `<span class="chip${place.toLowerCase() === f.toLowerCase() ? " on" : ""}">${esc(f)}</span>`).join("");
    document.querySelectorAll("#lorte .chip").forEach((c) => c.addEventListener("click", () => loadPlace(c.textContent)));
  }
  function favList() { try { return JSON.parse(A ? A.lageFavorites() : '["Stuttgart","Seoul"]'); } catch (e) { return []; } }
  const esc = (s) => String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---------- Fliegen wie bei Google Earth: hoch, drehen, runter – erst am Ziel kippen ----------
  let flyId = 0;
  function fly(lon, lat, z, tilt, done) {
    const id = ++flyId;
    const c = map.getCenter(), d = km(c.lat, c.lng, lat, lon);
    map.flyTo({ center: [lon, lat], zoom: z, pitch: 0, bearing: 0, curve: d > 300 ? 1.9 : 1.3, speed: d > 300 ? 1.0 : 1.4, essential: true });
    map.once("moveend", () => {
      if (id !== flyId) return;
      const fin = () => { if (id !== flyId) return; let ok = false; const t = setTimeout(() => { if (!ok) { ok = true; done && done(); } }, 2500);
        map.once("idle", () => { if (!ok) { ok = true; clearTimeout(t); done && done(); } }); };
      if (tilt) { map.easeTo({ pitch: tilt, bearing: Math.random() * 50 - 25, duration: 1100 }); map.once("moveend", fin); } else fin();
    });
  }
  function overview() {
    if (!map) return;
    target(null); cur = -1;
    document.querySelectorAll(".lcd").forEach((e) => e.classList.remove("hi"));
    const c = center();
    if ((mode === "stadt" || mode === "orte") && c) fly(c[1], c[0], mode === "orte" ? 11.5 : 12.3, 0);
    else { const h = home(); fly(h ? h.lon : 10, 30, worldZoom(), 0); }
  }

  // Erster Tipp auf eine Meldung: hinfliegen. Zweiter Tipp auf dieselbe: wieder raus.
  // 1. Tipp: hinfliegen, Fadenkreuz bleibt fest am Punkt. Karte weggedreht + nochmal Tipp: wieder hin.
  // Schon dort + nochmal Tipp: raus, Fadenkreuz weg.
  function toggle(i) {
    if (cur !== i) { focus(i, false); return; }
    const p = data.brennpunkte[i], s = map.project([p.lon, p.lat]), W = map.getContainer().clientWidth, H = map.getContainer().clientHeight;
    const z = ZOOM[p.genau] || (p.art === "lokal" ? 14 : 5.5);
    const there = Math.hypot(s.x - W / 2, s.y - H / 2) < 90 && map.getZoom() > z - 1.5;
    if (there) { overview(); } else focus(i, false);
  }
  // Fadenkreuz als Marker: hängt am Ort, nicht am Bildschirm
  let tgtMk = null;
  function target(p, show) {
    if (!map) return;
    if (!tgtMk) { const w = document.createElement("div"); w.className = "ltgtw"; w.appendChild(TGT); tgtMk = new maplibregl.Marker({ element: w }); }
    if (!p) { TGT.classList.remove("on"); tgtMk.remove(); return; }
    tgtMk.setLngLat([p.lon, p.lat]).addTo(map);
    TGT.classList.toggle("on", !!show);
  }

  function focus(i, tour, n, of) {
    const p = data && data.brennpunkte[i]; if (!p || !map) return;
    cur = i;
    if (p.art !== "lokal" && mode === "stadt") { mode = "welt"; document.querySelectorAll("#ltop .seg span").forEach((s) => s.classList.toggle("on", s.dataset.m === "welt")); }
    const z = ZOOM[p.genau] || (p.art === "lokal" ? 14 : 5.5);
    TGK.textContent = (tour ? `ZIEL ${n} / ${of} · ` : "") + (p.art || "").toUpperCase();
    TGN.textContent = p.ort || p.titel;
    target(p, false);
    if (tour && P.lage_zoom === false) target(p, true);
    else fly(p.lon, p.lat, z, z > 12 ? 50 : 0, () => { if (cur === i) target(p, true); });
    document.querySelectorAll(".lcd").forEach((e) => e.classList.toggle("hi", +e.dataset.i === i));
    const card = document.querySelector(`.lcd[data-i="${i}"]`);
    if (card) $("lcards").scrollTo({ left: card.offsetLeft - 14, behavior: "smooth" });
    if (tour) { touring = true; jar(true, "erzählt: " + (p.ort || p.titel)); }
  }
  function jar(on, txt) { $("ljar").classList.toggle("on", on); if (txt) $("ljartxt").textContent = txt; }

  function setMode(m, quiet) {
    mode = m;
    document.querySelectorAll("#ltop .seg span").forEach((s) => s.classList.toggle("on", s.dataset.m === m));
    $("lorte").classList.toggle("on", m === "orte");
    target(null); cur = -1;
    if (m === "fuer") { place = "@fuerdich"; jar(true, "sucht, was dich interessiert …"); if (A) A.getLage(place, false); return; }
    if (m === "orte") { const f = favList(); if (f.length && (!place || place === "@fuerdich")) { place = ""; loadPlace(f[0]); return; } }
    if (m !== "orte" && place) { place = ""; load(false); return; }
    render(); if (!quiet) overview();
  }
  document.querySelectorAll("#ltop .seg span").forEach((s) => s.addEventListener("click", () => setMode(s.dataset.m)));

  function load(force) { jar(true, "holt die Lage …"); if (A) A.getLage(place, !!force); }
  // Tipp auf einen Lieblingsort: sofort hinfliegen (Koordinaten kommen aus der Suche), Meldungen laden nach
  function loadPlace(p) {
    place = p; mode = "orte"; favorites(); jar(true, "holt die Lage aus " + p + " …");
    try { const g = JSON.parse(A && A.geocode ? A.geocode(p) : "null"); if (g && map) fly(g.lon, g.lat, 11.5, 0); } catch (e) {}
    if (A) A.getLage(p, false);
  }

  function applyPrefs() {
    if (!map || !map.isStyleLoaded()) return;
    for (const id of LABEL_IDS) try { map.setLayoutProperty(id, "visibility", P.lage_labels === false ? "none" : "visible"); } catch (e) {}
  }

  // ---------- Echte Satelliten (Bahndaten von CelesTrak, berechnet mit SGP4) ----------
  const SAT_NAMES = { 25544: "ISS", 48274: "TIANGONG", 20580: "HUBBLE", 40697: "SENTINEL-2A", 43013: "NOAA-20" };
  const SAT_COL = { 25544: "#ffe2a0", 48274: "#ffb46a", 20580: "#9fd8ff", 40697: "#8fffd0", 43013: "#c8b0ff" };
  let sats = [];
  function loadTle(txt) {
    if (!window.satellite) return;
    if (txt === undefined) { if (A && A.tle) txt = A.tle(); else return; }
    const L = String(txt || "").split(/\r?\n/), out = [];
    for (let i = 0; i < L.length - 1; i++) if (L[i].startsWith("1 ") && L[i + 1].startsWith("2 ")) {
      const id = +L[i].substring(2, 7); if (!SAT_NAMES[id] || out.some((s) => s.id === id)) continue;
      try { out.push({ id, name: SAT_NAMES[id], col: SAT_COL[id], rec: satellite.twoline2satrec(L[i], L[i + 1]), track: null, trackT: 0 }); } catch (e) {}
    }
    if (out.length) sats = out;
  }
  function geo(rec, date) {
    const pv = satellite.propagate(rec, date); if (!pv || !pv.position) return null;
    const g = satellite.eciToGeodetic(pv.position, satellite.gstime(date));
    return { lat: satellite.degreesLat(g.latitude), lon: satellite.degreesLong(g.longitude), h: g.height };
  }
  function satsDraw() {
    if (!orb) return;
    const W = orb.clientWidth, H = orb.clientHeight, d = Math.min(2, window.devicePixelRatio || 1);
    if (orb.width !== Math.round(W * d)) { orb.width = Math.round(W * d); orb.height = Math.round(H * d); }
    const g = orb.getContext("2d"); g.setTransform(d, 0, 0, d, 0, 0); g.clearRect(0, 0, W, H);
    const z = map.getZoom();
    // nur wenn man (fast) die ganze Erde sieht; beim Reinzoomen ausblenden
    const Rg = 512 * Math.pow(2, z) / (2 * Math.PI), Hc = map.getContainer().clientHeight;
    const fade = Math.max(0, Math.min(1, (Hc * .62 - Rg) / (Hc * .2)));   // nur wenn man (fast) die ganze Erde sieht
    if (fade <= 0 || P.lage_orbits === false || !sats.length || map.getPitch() > 5) return;
    const c = map.getCenter(), lat0 = c.lat * Math.PI / 180, lon0 = c.lng;
    const p0 = map.project(c), R = 512 * Math.pow(2, z) / (2 * Math.PI);   // Radius der Erde auf dem Bildschirm
    const br = -map.getBearing() * Math.PI / 180;
    const scr = (q) => {   // Kugel-Projektion um die Kartenmitte; k = Höhe über der Erde
      const la = q.lat * Math.PI / 180, dl = (q.lon - lon0) * Math.PI / 180, k = (6371 + q.h) / 6371;
      const x = Math.cos(la) * Math.sin(dl), y = Math.cos(lat0) * Math.sin(la) - Math.sin(lat0) * Math.cos(la) * Math.cos(dl);
      const zz = Math.sin(lat0) * Math.sin(la) + Math.cos(lat0) * Math.cos(la) * Math.cos(dl);
      const X = x * Math.cos(br) - y * Math.sin(br), Y = x * Math.sin(br) + y * Math.cos(br);
      return { x: p0.x + X * R * k, y: p0.y - Y * R * k, vis: zz > 0 || Math.hypot(x, y) * k > 1 };
    };
    const now = Date.now();
    g.globalAlpha = fade;
    for (const s of sats) {
      // Bahn: 45 Minuten zurück bis 45 Minuten voraus (einmal pro Minute neu berechnet)
      if (!s.track || now - s.trackT > 60000) { s.track = []; for (let m = -45; m <= 45; m += 1.5) { const q = geo(s.rec, new Date(now + m * 60000)); if (q) s.track.push(q); } s.trackT = now; }
      g.lineWidth = 1; g.strokeStyle = s.col; g.globalAlpha = fade * .45;
      let prev = null;
      for (const q of s.track) { const p = scr(q); if (prev && prev.vis && p.vis && Math.hypot(p.x - prev.x, p.y - prev.y) < R) { g.beginPath(); g.moveTo(prev.x, prev.y); g.lineTo(p.x, p.y); g.stroke(); } prev = p; }
      const q = geo(s.rec, new Date(now)); if (!q) continue;
      const p = scr(q); if (!p.vis) continue;
      g.globalAlpha = fade;
      g.fillStyle = "#fff6dc"; g.shadowColor = s.col; g.shadowBlur = 12; g.beginPath(); g.arc(p.x, p.y, 3, 0, 7); g.fill(); g.shadowBlur = 0;
      g.font = "600 9px monospace"; g.fillStyle = s.col; g.fillText(s.name, p.x + 6, p.y - 5);
      g.font = "500 8px monospace"; g.fillStyle = "rgba(255,230,190,.65)"; g.fillText(Math.round(q.h) + " km", p.x + 6, p.y + 5);
    }
    g.globalAlpha = 1;
  }

  // ---------- Schnittstelle für app.js ----------
  window.JLage = {
    map() { return map; },
    shown() { init(); if (map) setTimeout(() => map.resize(), 50); if (!data) load(false); else homeMarkers(); },
    onData(d, tour) {
      const fuer = d.ort === "Für dich";
      if (fuer) {   // kleine Vorschau auf der Info-Seite
        const c = $("info-fuer-card"); if (c) { c.style.display = ""; $("info-fuer").textContent = d.briefing || ((d.brennpunkte || []).slice(0, 2).map((p) => p.titel).join(" · ")); }
      }
      if (!tour && fuer !== (place === "@fuerdich")) return;   // gehört zu einer anderen Ansicht (kam zu spät)
      const first = !data; data = d; jar(false);
      if (tour) { place = fuer ? "@fuerdich" : ""; mode = fuer ? "fuer" : "welt"; document.querySelectorAll("#ltop .seg span").forEach((s) => s.classList.toggle("on", s.dataset.m === mode)); }
      render();
      if (first || tour || mode === "orte" || mode === "fuer") overview();
      if (tour) jar(true, "Lagebericht");
      if (!fuer) { const ic = $("info-lage"); if (ic) ic.textContent = (d.briefing || "") + ` (${(d.brennpunkte || []).length} Brennpunkte)`; }
    },
    onFocus(i, n, of) { if (i < 0) { touring = false; jar(false); overview(); return; } focus(i, true, n, of); },
    home() { homeMarkers(); if (data) render(); },
    prefs(c) { P = c || {}; applyPrefs(); homeMarkers(); if (data) render(); },
    tle(txt) { loadTle(txt); },
    onError(t, ort) {
      if (ort === "@fuerdich") { const c = $("info-fuer-card"); if (c) { c.style.display = ""; $("info-fuer").textContent = t; } if (place !== "@fuerdich") return; }
      jar(true, t); setTimeout(() => jar(false), 7000);
    },
    draw(dt) {
      if (mini && $("ljar").classList.contains("on")) mini.draw(dt);
      if (!map) return;
      const z = map.getZoom();
      if (P.lage_spin !== false && !touring && mode === "welt" && z < 3 && Date.now() - lastTouch > 6000 && !map.isMoving()) {
        const c = map.getCenter(); map.jumpTo({ center: [c.lng + dt * 2.2, c.lat] });
      }
      satsDraw();
    },
    swipeOk(target, x) { return !!target.closest("#ltop") || x < 26 || x > window.innerWidth - 26; },
  };
})();
