// Lage-Seite: echtes Satellitenbild (Esri) als 3D-Erdkugel, die beim Reinzoomen zur Karte wird (MapLibre),
// Tag und Nacht live mit weicher Dämmerung, Brennpunkte, Lieblingsorte und die Jarvis-Tour (fliegt von Punkt zu Punkt).
(function () {
  const $ = (id) => document.getElementById(id);
  const A = window.Android || null;
  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  const COL = { konflikt: "#ff5a4a", politik: "#3cc8ff", wirtschaft: "#6effcd", katastrophe: "#ff9a3c", wetter: "#9ad8ff",
    gesellschaft: "#d7a8ff", sport: "#8cff8c", wissenschaft: "#7af0ff", lokal: "#ffd678" };
  const ZOOM = { punkt: 17, strasse: 16, stadtteil: 14.2, stadt: 11.5, region: 8, land: 5 };
  let P = {}, lastTouch = 0, touring = false, orb = null;
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

  function init() {
    if (map || !window.maplibregl) return;
    map = new maplibregl.Map({
      container: "lmap", attributionControl: { compact: true }, maxPitch: 70, fadeDuration: 150,
      style: {
        version: 8, projection: { type: "globe" },
        glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
        sky: { "sky-color": "#071a3a", "horizon-color": "#8cc8ff", "fog-color": "#bcdcff", "horizon-fog-blend": .6, "fog-ground-blend": .9,
          "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 5, .8, 9, .25, 12, 0] },
        sources: {
          sat: { type: "raster", tiles: [ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, maxzoom: 19, attribution: "Esri, Maxar, Earthstar Geographics" },
          ofm: { type: "vector", url: "https://tiles.openfreemap.org/planet", attribution: "OpenFreeMap © OpenMapTiles © OpenStreetMap" },
          night: { type: "geojson", data: nightData() },
        },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#000" } },
          { id: "sat", type: "raster", source: "sat", paint: { "raster-saturation": .08, "raster-contrast": .12, "raster-brightness-max": .97 } },
          // jede Stufe dunkelt ein bisschen ab; ganz nah heran (Straßen) wird die Nacht schwächer, damit man noch etwas sieht
          { id: "night", type: "fill", source: "night", paint: { "fill-color": "#01040d", "fill-antialias": false,
            "fill-opacity": ["interpolate", ["linear"], ["zoom"], 0, .075, 9, .06, 14, .035] } },
          ...LABELS,
        ],
      },
      center: [15, 30], zoom: 1.05,
    });
    setInterval(() => { try { map.getSource("night").setData(nightData()); } catch (e) {} }, 60000);
    map.on("move", readout);
    ["touchstart", "mousedown", "wheel"].forEach((ev) => $("lmap").addEventListener(ev, () => { lastTouch = Date.now(); }, { passive: true }));
    map.on("load", () => { applyPrefs(); document.querySelectorAll("#v-lage .maplibregl-ctrl-attrib").forEach((e) => e.classList.remove("maplibregl-compact-show")); });
    orb = $("lorb");
    map.on("zoom", () => $("v-lage").classList.toggle("far", map.getZoom() < 8));
    $("v-lage").classList.add("far");
    try { mini = new window.Sphere3D($("lmini"), 5); mini.state = "speaking"; } catch (e) {}
    if (data) render();
  }

  function readout() {
    const c = map.getCenter(), z = map.getZoom();
    const ns = c.lat >= 0 ? "N" : "S", ew = c.lng >= 0 ? "E" : "W";
    $("lread").innerHTML = `SAT · LIVE · TAG/NACHT ECHTZEIT<br><b>${Math.abs(c.lat).toFixed(4)} ${ns}  ${Math.abs(c.lng).toFixed(4)} ${ew}</b><br>ZOOM ${z.toFixed(1)}${map.getPitch() > 5 ? " · NEIGUNG " + map.getPitch().toFixed(0) + "°" : ""}`;
  }

  // ---------- Punkte und Karten ----------
  function shown() {
    const pts = (data && data.brennpunkte) || [];
    return pts.map((p, i) => ({ ...p, i })).filter((p) => mode !== "stadt" || p.art === "lokal");
  }
  function render() {
    if (!data) return;
    const city = data.stadt || (A && A.city && A.city()) || "Leonberg";
    $("seg-stadt").textContent = city.toUpperCase();
    const list = shown();
    $("lnum").textContent = list.length;
    $("lttl").textContent = mode === "stadt" ? city.toUpperCase() + " · LOKAL" : mode === "orte" ? ("LAGE · " + (data.ort || "").toUpperCase()) : "BRENNPUNKTE WELTWEIT";
    $("lcards").innerHTML = list.map((p) => `<div class="lcd" data-i="${p.i}" style="--c:${COL[p.art] || "#ffa03c"}">
      <div class="k">${(p.art || "").toUpperCase()} · ${esc(p.ort || "")}</div><div class="t">${esc(p.titel)}</div><div class="x">${esc(p.text)}</div></div>`).join("")
      || `<div class="lcd"><div class="t">Gerade keine Meldungen</div></div>`;
    document.querySelectorAll(".lcd[data-i]").forEach((e) => e.addEventListener("click", () => focus(+e.dataset.i, false)));
    $("lcards").scrollLeft = 0;
    if (!map) return;
    markers.forEach((m) => m.remove()); markers = [];
    for (const p of list) {
      const e = document.createElement("div"); e.className = "lmk" + (p.art === "lokal" ? " lok" : ""); e.style.color = COL[p.art] || "#ffa03c";
      e.innerHTML = `<span class="lb">${esc(p.ort || p.titel)}</span>`;
      e.addEventListener("click", (ev) => { ev.stopPropagation(); focus(p.i, false); });
      markers.push(new maplibregl.Marker({ element: e }).setLngLat([p.lon, p.lat]).addTo(map));
    }
    favorites();
  }
  function favorites() {
    if (!map) return;
    const fav = favList(); const city = data && data.stadt;
    const home = data && data.lat != null && !(data.ort && city && data.ort.toLowerCase() !== city.toLowerCase()) ? [[ "Zuhause", data.lat, data.lon ]] : [];
    for (const [n, la, lo] of home) {
      const e = document.createElement("div"); e.className = "lfav"; e.innerHTML = `<span class="lb">${n}</span>`;
      markers.push(new maplibregl.Marker({ element: e }).setLngLat([lo, la]).addTo(map));
    }
    // Lieblingsorte als Chips oben (Koordinaten kennt erst die Lage des Ortes)
    $("lorte").innerHTML = fav.map((f) => `<span class="chip${place.toLowerCase() === f.toLowerCase() ? " on" : ""}">${esc(f)}</span>`).join("");
    document.querySelectorAll("#lorte .chip").forEach((c) => c.addEventListener("click", () => loadPlace(c.textContent)));
  }
  function favList() { try { return JSON.parse(A ? A.lageFavorites() : '["Stuttgart","Seoul"]'); } catch (e) { return []; } }
  const esc = (s) => String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function overview() {
    if (!map || !data) return;
    if (mode === "stadt" || (mode === "orte" && data.lat != null)) {
      const pts = shown();
      if (pts.length > 1) {
        const b = new maplibregl.LngLatBounds(); pts.forEach((p) => b.extend([p.lon, p.lat]));
        map.fitBounds(b, { padding: { top: 140, bottom: 210, left: 50, right: 50 }, maxZoom: 13.5, pitch: 35, bearing: -10, duration: 2200 });
      } else if (data.lat != null) map.flyTo({ center: [data.lon, data.lat], zoom: 12, pitch: 35, duration: 2200 });
    } else map.flyTo({ center: [15, 30], zoom: 1.05, pitch: 0, bearing: 0, duration: 2600, curve: 1.6 });
  }

  // ---------- Fokus auf einen Punkt (auch für die Tour) ----------
  function focus(i, tour, n, of) {
    const p = data && data.brennpunkte[i]; if (!p || !map) return;
    if (p.art !== "lokal" && mode === "stadt") setMode("welt", true);
    const z = ZOOM[p.genau] || (p.art === "lokal" ? 14 : 5.5);
    if (tour && P.lage_zoom === false) { /* nur markieren, nicht hinfliegen */ } else map.flyTo({ center: [p.lon, p.lat], zoom: z, pitch: z > 11 ? 55 : z > 6 ? 30 : 0, bearing: z > 11 ? (Math.random() * 70 - 35) : 0,
      duration: tour ? 1800 : 1600, curve: 1.5, essential: true });
    $("ltgk").textContent = (tour ? `ZIEL ${n} / ${of} · ` : "") + (p.art || "").toUpperCase();
    $("ltgn").textContent = p.ort || p.titel;
    const t = $("ltgt"); t.classList.remove("on"); setTimeout(() => t.classList.add("on"), tour ? 1300 : 1100);
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
    $("ltgt").classList.remove("on");
    if (m === "orte") { const f = favList(); if (f.length && !place) { loadPlace(f[0]); return; } }
    if (m !== "orte" && place) { place = ""; load(false); return; }
    render(); if (!quiet) overview();
  }
  document.querySelectorAll("#ltop .seg span").forEach((s) => s.addEventListener("click", () => setMode(s.dataset.m)));

  function load(force) { jar(true, "holt die Lage …"); if (A) A.getLage(place, !!force); }
  function loadPlace(p) { place = p; mode = "orte"; favorites(); jar(true, "holt die Lage aus " + p + " …"); if (A) A.getLage(p, false); }

  function applyPrefs() {
    if (!map || !map.isStyleLoaded()) return;
    for (const id of LABEL_IDS) try { map.setLayoutProperty(id, "visibility", P.lage_labels === false ? "none" : "visible"); } catch (e) {}
  }
  // Atmosphären-Schein und Satellitenbahnen um die Erde (nur in der Weltansicht)
  const SATS = [["SAT-1 · SENTINEL", 1.24, .30, -16, "rgba(255,185,80,.6)", [], .06], ["ISS", 1.38, .20, 22, "rgba(255,205,120,.42)", [4, 6], .11], ["METEOSAT", 1.52, .38, -50, "rgba(130,195,255,.36)", [1, 5], .015]];
  let orbT = 0;
  function orbits(z) {
    if (!orb) return;
    const W = orb.clientWidth, H = orb.clientHeight, d = Math.min(2, window.devicePixelRatio || 1);
    if (orb.width !== Math.round(W * d)) { orb.width = Math.round(W * d); orb.height = Math.round(H * d); }
    const g = orb.getContext("2d"); g.setTransform(d, 0, 0, d, 0, 0); g.clearRect(0, 0, W, H);
    const fade = Math.max(0, Math.min(1, (3.2 - z) / 1.2)); if (fade <= 0) return;
    const ctr = map.project(map.getCenter()), cx = ctr.x, cy = ctr.y, R = 512 * Math.pow(2, z) / (2 * Math.PI);
    g.globalAlpha = fade;
    const hg = g.createRadialGradient(cx, cy, R * .97, cx, cy, R * 1.16);
    hg.addColorStop(0, "rgba(120,190,255,.5)"); hg.addColorStop(.35, "rgba(80,150,255,.16)"); hg.addColorStop(1, "rgba(40,90,200,0)");
    g.fillStyle = hg; g.beginPath(); g.arc(cx, cy, R * 1.16, 0, 7); g.arc(cx, cy, R * .97, 0, 7, true); g.fill("evenodd");
    if (P.lage_orbits === false) { g.globalAlpha = 1; return; }
    orbT += 1 / 60;
    for (const [name, k, flat, rot, col, dash, speed] of SATS) {
      const rr = rot * Math.PI / 180;
      const pt = (a) => { const x = Math.cos(a) * R * k, y = Math.sin(a) * R * k * flat; return [cx + x * Math.cos(rr) - y * Math.sin(rr), cy + x * Math.sin(rr) + y * Math.cos(rr)]; };
      g.setLineDash(dash); g.lineWidth = 1.1; g.strokeStyle = col;
      g.save(); g.beginPath(); g.rect(0, 0, W, H); g.arc(cx, cy, R * 1.01, 0, 7, true); g.clip("evenodd");
      g.beginPath(); for (let a = Math.PI; a <= 2 * Math.PI + 1e-3; a += .04) { const [x, y] = pt(a); a === Math.PI ? g.moveTo(x, y) : g.lineTo(x, y); } g.stroke(); g.restore();
      g.beginPath(); for (let a = 0; a <= Math.PI + 1e-3; a += .04) { const [x, y] = pt(a); a === 0 ? g.moveTo(x, y) : g.lineTo(x, y); } g.stroke();
      g.setLineDash([]);
      const a = (orbT * speed * 2 * Math.PI) % (2 * Math.PI), [X, Y] = pt(a), behind = a > Math.PI && Math.hypot(X - cx, Y - cy) < R;
      if (behind) continue;
      g.fillStyle = "#fff2cc"; g.shadowColor = "#ffb040"; g.shadowBlur = 10; g.beginPath(); g.arc(X, Y, 2.6, 0, 7); g.fill(); g.shadowBlur = 0;
      g.font = "600 9px monospace"; g.fillStyle = "rgba(255,214,140,.85)"; g.fillText(name, X + 6, Y + 3);
    }
    g.globalAlpha = 1;
  }

  // ---------- Schnittstelle für app.js ----------
  window.JLage = {
    shown() { init(); if (map) setTimeout(() => map.resize(), 50); if (!data) load(false); },
    onData(d, tour) {
      const first = !data; data = d; jar(false);
      if (tour) { place = ""; mode = "welt"; document.querySelectorAll("#ltop .seg span").forEach((s) => s.classList.toggle("on", s.dataset.m === "welt")); }
      render();
      if (first || tour) overview();
      if (tour) jar(true, "Lagebericht");
      // kleine Zusammenfassung auf der Info-Seite
      const ic = $("info-lage"); if (ic) ic.textContent = (d.briefing || "") + ` (${(d.brennpunkte || []).length} Brennpunkte)`;
    },
    onFocus(i, n, of) { if (i < 0) { touring = false; $("ltgt").classList.remove("on"); jar(false); overview(); return; } focus(i, true, n, of); },
    prefs(c) { P = c || {}; applyPrefs(); },
    onError(t) { jar(true, t); setTimeout(() => jar(false), 6000); },
    draw(dt) {
      if (mini && $("ljar").classList.contains("on")) mini.draw(dt);
      if (!map) return;
      const z = map.getZoom();
      // Erde langsam drehen, wenn niemand sie anfasst
      if (P.lage_spin !== false && !touring && mode === "welt" && z < 3 && Date.now() - lastTouch > 6000 && !map.isMoving()) {
        const c = map.getCenter(); map.jumpTo({ center: [c.lng + dt * 2.2, c.lat] });
      }
      orbits(z);
    },
    // auf der Karte soll Wischen die Karte bewegen, nicht die Seite wechseln
    swipeOk(target, x) { return !!target.closest("#ltop") || x < 26 || x > window.innerWidth - 26; },
  };
})();
