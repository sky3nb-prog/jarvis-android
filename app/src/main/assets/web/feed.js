// Mitteilungen: Liste aller Meldungen von Jarvis + schön aufbereitete Einzelansicht (Fahrt, Heimweg, Tages-/Wochen-Update …)
(function () {
  const A = window.Android || null;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const hm = (t) => (t ? new Date(t).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) : "–");
  const SEEN = "feed_seen";
  const seenTs = () => { try { return +localStorage.getItem(SEEN) || 0; } catch (e) { return 0; } };
  const setSeen = (t) => { try { localStorage.setItem(SEEN, String(t)); } catch (e) {} };

  // Arten: Symbol, Farbe, Filter
  const KIND = {
    fahrt: ["🚲", "#0b2a3c", "fahrt"], heimweg: ["🏠", "#3a2608", "fahrt"], ankunft: ["💬", "#0b2a22", "fahrt"],
    morgen: ["☀️", "#1f1430", "brief"], abend: ["🌙", "#1f1430", "brief"], woche: ["📊", "#2a1a05", "brief"],
    anruf: ["📞", "#2a1306", "anruf"], erinnerung: ["📌", "#2a1a05", "brief"], test: ["🧪", "#0b2a3c", "fahrt"],
    vorschau: ["🗓️", "#0b2a3c", "brief"], wecker: ["⏰", "#2a1a05", "brief"], bilanz: ["❤️", "#2a0f18", "brief"],
  };
  const FILTERS = [["alle", "Alle"], ["fahrt", "Fahrten"], ["brief", "Updates"], ["anruf", "Anrufe"]];
  let filter = "alle", stack = [];

  // Wetter-Symbol aus WMO-Code
  function wxIcon(code, dark) {
    if (code >= 95) return "⛈️"; if (code >= 71 && code <= 77 || code === 85 || code === 86) return "🌨️";
    if (code >= 51) return "🌧️"; if (code >= 45) return "🌫️"; if (code >= 3) return "☁️";
    if (code >= 1) return dark ? "☁️" : "⛅"; return dark ? "🌙" : "☀️";
  }
  const CLOTH = [[/winterjacke|daunen/i, "🧥"], [/jacke/i, "🧥"], [/regen|schirm/i, "☔"], [/mütze|kappe/i, "🧢"], [/handschuh/i, "🧤"],
    [/schal/i, "🧣"], [/pulli|pullover|hoodie/i, "👕"], [/t-shirt|shirt/i, "👕"], [/hose/i, "👖"], [/schuh|stiefel/i, "👟"], [/brille/i, "🕶️"]];
  const clothIcon = (t) => (CLOTH.find(([r]) => r.test(t)) || [0, "•"])[1];
  const WARN = [[/glatt|glätte|eis|frost/i, "❄️"], [/wind|böe/i, "💨"], [/licht|dunkel/i, "💡"], [/nass|regen/i, "💧"], [/hitze|sonne/i, "🧴"]];
  const warnIcon = (t) => (WARN.find(([r]) => r.test(t)) || [0, "⚠️"])[1];

  // Anziehen: Jacke, Oberteil, Hose, Extras (genau nach deinen Regeln)
  function outfit(o, list) {
    if (!o) return list && list.length ? card("👕 ANZIEHEN", "#d7a8ff", chips(list)) : "";
    const row = (ic, k, v) => (v && !/^keine?$/i.test(v) ? `<div class="fp-row"><span class="z">${ic} ${k}</span><span>${esc(v)}</span></div>` : "");
    const ex = (o.extras || []).filter((x) => x && x !== "null");
    return card("👕 ANZIEHEN", "#d7a8ff", row("🧥", "Jacke", o.jacke) + row("👕", "Oben", o.oben) + row("👖", "Hose", o.hose) +
      (ex.length ? `<div style="margin-top:8px">${chips(ex)}</div>` : ""));
  }
  const card = (title, color, inner) => `<div class="fp-card" style="--c:${color}"><h3>${title}</h3>${inner}</div>`;
  const chips = (a) => (a && a.length ? `<div class="fp-chips">${a.map((x) => `<span class="fp-chip">${clothIcon(x)} ${esc(x)}</span>`).join("")}</div>` : "");
  const warns = (a) => (a || []).map((x) => `<div class="fp-warn"><span>${warnIcon(x)}</span><span>${esc(x)}</span></div>`).join("");
  const todos = (a) => (a || []).map((x) => `<div class="fp-todo"><span class="fp-box" onclick="this.classList.toggle('ok');this.textContent=this.classList.contains('ok')?'✓':''"></span>${esc(x)}</div>`).join("");
  const wxBox = (label, w) => (w ? `<div class="fp-w"><small>${label}</small><div class="i">${wxIcon(w.code, w.dark)}</div><b>${w.temp}°</b>
    <div class="f">gefühlt ${w.feel}° · ${w.rain_mm > 0.05 ? "Regen " + w.rain_mm + " mm" : "Wind " + w.wind}${w.dark ? " · dunkel" : ""}</div></div>` : "");
  const say = (t) => card("JARVIS SAGT", "var(--gold-l)", `<div class="fp-say">${esc(t)}</div>`);

  // --- Einzelansichten ---
  function viewFahrt(m) {
    const d = m.data || {}, p = d.plan || {}, bahn = p.mode === "transit", home = m.kind === "heimweg";
    const veh = p.vehicle === "rad" ? "Fahrrad" : p.vehicle === "fuss" ? "zu Fuß" : "E-Bike";
    const times = bahn
      ? [["LOSGEHEN", hm(p.go)], ["BAHN", esc(p.line) + " " + hm(p.ride_dep)], ["AN", hm(p.arr)]]
      : home ? [["LOSFAHREN", hm(p.go)], ["FAHRZEIT", Math.round(p.ride || p.min || 0) + " Min."], ["ZUHAUSE", hm(d.home_at)]]
        : [["LOSFAHREN", hm(p.go || d.leave)], ["ANKUNFT CA.", hm(p.arr)], ["ZUHAUSE", d.home_at ? hm(d.home_at) : "–"]];
    let h = `<div class="fp-hero ${bahn ? "blue" : ""}">${bahn ? "" : '<div class="fp-orb"></div>'}
      <div class="k">${home ? "HEIMWEG" : d.fest ? "FESTER WEG" : d.test ? "TEST" : "FAHRT"}${d.ziel && !home ? " · " + esc(String(d.ziel).toUpperCase()) : ""}</div>
      <h1>${esc(m.title)}</h1><div class="s">${bahn ? "Es soll regnen – DWD, ECMWF und GFS." : p.rain ? "Es soll regnen – Regensachen mit." : "Kein Regen – heute mit dem " + veh + "."}</div>
      <div class="fp-times">${times.map(([k, v]) => `<div class="fp-tb"><small>${k}</small><b>${v}</b></div>`).join("")}</div></div>`;
    h += `<div class="fp-card"><div class="fp-mode"><div class="fp-ic">${bahn ? "🚆" : p.vehicle === "fuss" ? "🚶" : "🚲"}</div><div>
      <b>${bahn ? esc(p.line) + " ab " + esc(p.stop) : veh + " · etwa " + Math.round(p.ride || p.min || 0) + " Min."}</b>
      <small>${bahn ? "Losgehen um " + hm(p.go) + ", an um " + hm(p.arr) : p.learned ? "gelernt aus deinen letzten " + p.learned + " Fahrten" : "geschätzt – wird mit jeder Fahrt genauer"}</small></div></div></div>`;
    if (d.wx_hin || d.wx_back) h += card("🌡️ WETTER", "var(--cyan)", `<div class="fp-wx">${wxBox(home ? "LOS " + hm(p.go) : "HIN " + hm(p.go || d.leave), d.wx_hin)}${wxBox("ZURÜCK " + hm(d.back), d.wx_back)}</div>`);
    h += outfit(d.outfit, d.anziehen);
    if (d.achtung && d.achtung.length) h += card("⚠️ PASS AUF", "var(--gold)", warns(d.achtung));
    if (d.denk && d.denk.length) h += card("🎒 DENK AN", "var(--gold-l)", todos(d.denk));
    if (d.sms_to) h += `<div class="fp-card"><div class="fp-sms"><i></i>SMS an ${esc(d.sms_to)} geht automatisch raus, ca. 5 Min. bevor du da bist.</div></div>`;
    h += say(m.text);
    if (p.mode === "transit" || p.go) h += `<div class="fp-btns"><div class="fp-btn" data-maps="${bahn ? "transit" : "bicycling"}">Route zeigen</div></div>`;
    return h;
  }

  function viewDay(m) {
    const d = m.data || {}, w = d.wx;
    let h = `<div class="fp-hero violet"><div class="k">${d.day ? "UPDATE FÜR MORGEN" : "TAGES-UPDATE"} · ${esc(String(d.datum || "").toUpperCase())}</div>
      <h1>${esc(m.title)}</h1><div class="s">${w ? `${w.min}° bis ${w.max}°, ${w.rain_pct >= 50 ? "Regen wahrscheinlich" : "eher trocken"}` : ""}</div>
      <div class="fp-times"><div class="fp-tb"><small>MIN / MAX</small><b>${w ? w.min + "° / " + w.max + "°" : "–"}</b></div>
      <div class="fp-tb"><small>REGEN</small><b>${w ? w.rain_pct + " %" : "–"}</b></div>
      <div class="fp-tb"><small>${d.wecker ? "WECKER" : "DUNKEL AB"}</small><b>${d.wecker ? hm(d.wecker) : w && w.sunset ? esc(w.sunset) : "–"}</b></div></div></div>`;
    if (w && w.hours && w.hours.length) h += card("🌡️ WETTER ÜBER DEN TAG", "var(--cyan)",
      `<div class="fp-wx">${w.hours.map((x) => `<div class="fp-w"><small>${x.h}:00</small><div class="i">${wxIcon(x.code, x.dark)}</div><b>${x.temp}°</b><div class="f">gefühlt ${x.feel}° · ${x.rain_pct} %</div></div>`).join("")}</div>`);
    h += outfit(d.outfit, d.anziehen);
    if (d.achtung && d.achtung.length) h += card("⚠️ PASS AUF", "var(--gold)", warns(d.achtung));
    h += sleepCard(d.schlaf);
    if (d.termine && d.termine.length) h += card("📅 TERMINE", "var(--green)", d.termine.map((t) => `<div class="fp-row"><span class="z">${esc(t.zeit)}</span><span>${esc(t.titel)}${t.ort ? `<span class="o">${esc(t.ort)}</span>` : ""}</span></div>`).join(""));
    if (d.mitnehmen && d.mitnehmen.length) h += card("🎒 MITNEHMEN", "var(--gold-l)", todos(d.mitnehmen));
    return h + say(m.text);
  }

  function viewWeek(m) {
    const d = m.data || {};
    const visits = (d.besuche || []).reduce((s, b) => s + b.n, 0);
    let h = `<div class="fp-hero"><div class="fp-orb"></div><div class="k">LETZTE 7 TAGE · ${esc(d.von)} – ${esc(d.bis)}</div><h1>${esc(m.title)}</h1>
      <div class="s">So lief deine Woche.</div></div>`;
    h += `<div class="fp-card"><div class="fp-tiles"><div class="fp-tile"><b>${visits}</b><small>Besuche</small></div>
      <div class="fp-tile"><b>${Math.round(d.rad_km || 0)}</b><small>km Rad</small></div>
      <div class="fp-tile"><b>${Math.floor((d.musik_min || 0) / 60)}<span style="font-size:14px">h ${(d.musik_min || 0) % 60}m</span></b><small>Musik</small></div></div></div>`;
    const fit = d.fit || [], sl = d.schlaf || [];
    if (fit.length) h += `<div class="fp-card"><div class="fp-tiles"><div class="fp-tile"><b>${nf(d.kcal_avg)}</b><small>kcal / Tag</small></div>
      <div class="fp-tile"><b>${nf(d.schritte)}</b><small>Schritte</small></div>
      <div class="fp-tile"><b>${d.schlaf_avg ? dur(d.schlaf_avg) : "–"}</b><small>Schlaf / Nacht</small></div></div></div>` +
      bars("🔥 KALORIEN VERBRAUCHT", "#ff9a5a", fit, (r) => r.kcal || 0, (r) => nf(r.kcal)) + bars("👣 SCHRITTE", "#6effcd", fit, (r) => r.schritte || 0, (r) => nf(r.schritte));
    if (sl.length) h += bars("🌙 SCHLAF", "#b98cff", sl, (r) => r.min || 0, (r) => dur(r.min));
    if (d.besuche && d.besuche.length) h += card("📍 BESUCHE", "var(--green)", d.besuche.map((b) => `<div class="fp-row"><span class="z">${b.n}×</span><span>${esc(b.ort)}</span></div>`).join(""));
    if (d.termine && d.termine.length) h += card(d.richtung === "zurueck" ? "📅 WAS LOS WAR" : "📅 NÄCHSTE WOCHE", "var(--cyan)", d.termine.map((t) => `<div class="fp-row"><span class="z">${esc(t.zeit)}</span><span>${esc(t.titel)}${t.ort ? `<span class="o">${esc(t.ort)}</span>` : ""}</span></div>`).join(""));
    if (d.mitnehmen && d.mitnehmen.length) h += card("🎒 VORBEREITEN", "var(--gold-l)", todos(d.mitnehmen));
    return h + say(m.text);
  }

  const nf = (v) => Number(v || 0).toLocaleString("de-DE");
  const dur = (min) => `${Math.floor(min / 60)}:${String(min % 60).padStart(2, "0")}`;
  function sleepCard(s) {
    if (!s) return "";
    return card("🌙 SCHLAF LETZTE NACHT", "#d7a8ff", `<div class="fp-row"><span class="z">${hm(s.start)} – ${hm(s.end)}</span><span><b style="color:#fff">${dur(s.min)} Std.</b>${s.wach ? `<span class="o">${s.wach} Min. zwischendurch wach</span>` : ""}</span></div>`);
  }
  // Balken pro Tag (Woche): Kalorien / Schritte / Schlaf
  function bars(title, color, rows, val, fmt) {
    const max = Math.max(1, ...rows.map(val));
    return card(title, color, rows.map((r) => `<div class="fp-bar"><span>${esc(r.tag)}</span><i><u style="width:${Math.round((val(r) / max) * 100)}%;background:${color}"></u></i><b>${fmt(r)}</b></div>`).join(""));
  }

  // Tagesabschluss: Rückblick auf heute + morgen nur Aufstehen und Anziehen
  function viewEvening(m) {
    const d = m.data || {}, f = d.fit || null, w = d.wx;
    let h = `<div class="fp-hero violet"><div class="k">TAGESABSCHLUSS · ${esc(String(d.datum || "").toUpperCase())}</div><h1>${esc(m.title)}</h1>
      <div class="s">Heute im Rückblick – und was du für morgen wissen musst.</div>
      <div class="fp-times"><div class="fp-tb"><small>MORGEN AUF</small><b>${d.aufstehen ? hm(d.aufstehen) : d.erster_wecker ? hm(d.erster_wecker) : "frei"}</b></div>
      <div class="fp-tb"><small>MORGEN</small><b>${w ? w.min + "° / " + w.max + "°" : "–"}</b></div>
      <div class="fp-tb"><small>${f ? "VERBRAUCHT" : "SCHLAF"}</small><b>${f ? nf(f.kcal) : d.schlaf ? dur(d.schlaf.min) : "–"}</b></div></div></div>`;
    if ((d.heute || []).length) h += card("📅 HEUTE", "var(--green)", d.heute.map((x) => `<div class="fp-todo" style="gap:9px"><span style="color:var(--green)">•</span>${esc(x)}</div>`).join(""));
    if (f) h += `<div class="fp-card"><h3>🔥 AKTIVITÄT HEUTE</h3><div class="fp-tiles"><div class="fp-tile"><b>${nf(f.kcal)}</b><small>kcal verbraucht</small></div>
      <div class="fp-tile"><b>${nf(f.schritte)}</b><small>Schritte</small></div>
      <div class="fp-tile"><b>${f.defizit != null ? nf(Math.abs(f.defizit)) : nf(f.aktiv)}</b><small>${f.defizit != null ? (f.defizit > 0 ? "kcal Defizit" : "kcal Überschuss") : "kcal aktiv"}</small></div></div></div>`;
    h += sleepCard(d.schlaf);
    h += card("⏰ MORGEN AUFSTEHEN", "#d7a8ff", d.aufstehen ? `<div class="fp-row"><span class="z">${hm(d.aufstehen)}</span><span>aufstehen${(d.wecker || []).length ? `<span class="o">Wecker ${d.wecker.map(esc).join(", ")}</span>` : ""}</span></div>`
      : `<div class="fp-row"><span class="z">${d.erster_wecker ? hm(d.erster_wecker) : "–"}</span><span>${d.erster_wecker ? "erster Wecker" : "kein Wecker – ausschlafen"}</span></div>`);
    h += outfit(d.outfit, d.anziehen);
    return h + say(m.text);
  }

  function viewBilanz(m) {
    const d = m.data || {}, f = d.fit || null, s = d.schlaf || null;
    const vs = f && d.avg_kcal ? Math.round(((f.kcal || 0) - d.avg_kcal) / d.avg_kcal * 100) : null;
    let h = `<div class="fp-hero violet"><div class="k">TAGESBILANZ · ${esc(String(d.datum || "").toUpperCase())}</div><h1>${esc(m.title)}</h1>
      <div class="s">${f && f.defizit != null ? (f.defizit > 0 ? nf(f.defizit) + " kcal Defizit" : nf(-f.defizit) + " kcal Überschuss") : vs != null ? (vs >= 0 ? "+" : "") + vs + " % Kalorien gegenüber deinem Schnitt" : ""}</div>
      <div class="fp-times"><div class="fp-tb"><small>VERBRAUCHT</small><b>${f ? nf(f.kcal) : "–"}</b></div>
      <div class="fp-tb"><small>SCHRITTE</small><b>${f ? nf(f.schritte) : "–"}</b></div>
      <div class="fp-tb"><small>SCHLAF</small><b>${s ? dur(s.min) : "–"}</b></div></div></div>`;
    if (f) h += `<div class="fp-card"><div class="fp-tiles"><div class="fp-tile"><b>${nf(f.aktiv)}</b><small>kcal aktiv</small></div>
      <div class="fp-tile"><b>${nf(f.sport_min)}</b><small>Min. Sport</small></div>
      <div class="fp-tile"><b>${f.gegessen ? nf(f.gegessen) : "–"}</b><small>kcal gegessen</small></div></div>
      ${d.avg_kcal ? `<div class="note" style="margin:8px 0 0">Dein Schnitt der letzten Tage: ${nf(d.avg_kcal)} kcal · ${nf(d.avg_schritte)} Schritte</div>` : ""}</div>`;
    h += sleepCard(s);
    return h + say(m.text);
  }

  function viewAhead(m) {
    const d = m.data || {};
    let h = `<div class="fp-hero blue"><div class="k">NÄCHSTE 7 TAGE · ${esc(d.von)} – ${esc(d.bis)}</div><h1>${esc(m.title)}</h1>
      <div class="s">Tag für Tag: Wetter und Termine.</div></div>`;
    for (const t of d.tage || []) {
      const w = t.wx;
      h += `<div class="fp-card"><div style="display:flex;align-items:center;gap:12px">
        <div style="flex:0 0 74px"><b style="color:var(--gold-l);font-size:15px">${esc(t.tag)}</b><div style="color:var(--dim);font-size:12px">${esc(t.datum)}</div></div>
        ${w ? `<div style="font-size:26px">${wxIcon(w.code, false)}</div><div style="font-size:13px;color:#dff3ff">${w.min}° / ${w.max}°<div style="color:var(--dim);font-size:11.5px">Regen ${w.rain_pct} %</div></div>` : ""}</div>
        ${(t.termine || []).map((x) => `<div class="fp-row"><span class="z">${esc(x.zeit)}</span><span>${esc(x.titel)}${x.ort ? `<span class="o">${esc(x.ort)}</span>` : ""}</span></div>`).join("") ||
          '<div style="color:var(--dim);font-size:13px;margin-top:6px">keine Termine</div>'}</div>`;
    }
    if (d.mitnehmen && d.mitnehmen.length) h += card("🎒 VORBEREITEN", "var(--gold-l)", todos(d.mitnehmen));
    return h + say(m.text);
  }

  function viewSimple(m) {
    const k = KIND[m.kind] || ["🔔", "#0b2a3c"];
    let h = `<div class="fp-hero blue"><div class="k">${new Date(m.ts).toLocaleString("de-DE", { weekday: "long", hour: "2-digit", minute: "2-digit" }).toUpperCase()}</div>
      <h1>${k[0]} ${esc(m.title)}</h1></div>`;
    const d = m.data || {};
    if (d.sms) h += card("💬 NACHRICHT", "var(--green)", `<div class="fp-say">${esc(d.sms)}</div>`);
    if (d.denk && d.denk.length) h += card("🎒 DENK AN", "var(--gold-l)", todos(d.denk));
    return h + say(m.text);
  }

  // --- Vorlesen: Punkt für Punkt, "Friday, weiter" oder ⏭ springt weiter ---
  let current = null, autoRead = true, reading = false, readKeys = [];
  const readBar = () => `<div class="fp-read"><div class="fp-rb" id="rd-play">🔊 Vorlesen</div><div class="fp-rb" id="rd-next">⏭ Weiter</div><div class="fp-rb" id="rd-stop">⏹</div></div>`;
  function hookRead() {
    $("rd-play").addEventListener("click", readNow);
    $("rd-next").addEventListener("click", () => A.readNext && A.readNext());
    $("rd-stop").addEventListener("click", () => A.readStop && A.readStop());
  }
  function partsOf(m) {
    const d = m.data || {}, out = [], cards = [];
    const o = d.outfit, list = d.anziehen || [];
    const outfitText = o ? ["Anziehen:", o.jacke && !/^keine?$/i.test(o.jacke) ? o.jacke + "," : "", o.oben ? o.oben + "," : "", o.hose || "", (o.extras || []).length ? ", dazu " + o.extras.join(", ") : ""].join(" ")
      : list.length ? "Anziehen: " + list.join(", ") : "";
    const add = (sel, t) => { if (t && t.trim()) { out.push(t); cards.push(sel); } };
    if (m.kind === "abend" && d.aufstehen !== undefined) {
      add("hero", m.text);
      add("MORGEN AUFSTEHEN", d.aufstehen ? "Morgen aufstehen um " + hm(d.aufstehen) + "." : "Morgen kein Wecker.");
      add("ANZIEHEN", outfitText);
    } else if (m.kind === "morgen" || m.kind === "abend") {
      const w = d.wx;
      add("hero", (m.kind === "morgen" ? "Guten Morgen. " : "Kurz zu morgen. ") + (w ? `${w.min} bis ${w.max} Grad, ${w.rain_pct >= 50 ? "Regen wahrscheinlich" : "eher trocken"}.` : ""));
      add("ANZIEHEN", outfitText);
      add("PASS AUF", (d.achtung || []).length ? "Pass auf: " + d.achtung.join(". ") : "");
      add("TERMINE", (d.termine || []).length ? "Termine: " + d.termine.map((t) => t.zeit + " " + t.titel).join(". ") : "Keine Termine.");
      add("MITNEHMEN", (d.mitnehmen || []).length ? "Mitnehmen: " + d.mitnehmen.join(", ") : "");
      if (d.wecker) add("hero", "Dein Wecker klingelt um " + hm(d.wecker) + ".");
    } else if (m.kind === "bilanz") {
      add("hero", m.text);
      if (d.schlaf) add("SCHLAF", `Geschlafen ${Math.floor(d.schlaf.min / 60)} Stunden ${d.schlaf.min % 60} Minuten.`);
    } else if (m.kind === "vorschau") {
      add("hero", "Deine nächste Woche.");
      (d.tage || []).forEach((t, i) => add("#day" + i, t.tag + ": " + (t.wx ? `${t.wx.min} bis ${t.wx.max} Grad. ` : "") + ((t.termine || []).map((x) => x.zeit + " " + x.titel).join(". ") || "keine Termine")));
      add("VORBEREITEN", (d.mitnehmen || []).length ? "Vorbereiten: " + d.mitnehmen.join(", ") : "");
    } else if (m.kind === "woche") {
      const v = (d.besuche || []).reduce((s, b) => s + b.n, 0);
      add("hero", `Deine letzten 7 Tage: ${v} Besuche, ${Math.round(d.rad_km || 0)} Kilometer Rad, ${Math.floor((d.musik_min || 0) / 60)} Stunden Musik.`);
      if ((d.fit || []).length) add("KALORIEN", `Im Schnitt ${d.kcal_avg} Kalorien am Tag verbraucht, ${d.schritte} Schritte in der Woche.`);
      if ((d.schlaf || []).length && d.schlaf_avg) add("SCHLAF", `Geschlafen im Schnitt ${Math.floor(d.schlaf_avg / 60)} Stunden ${d.schlaf_avg % 60} Minuten.`);
      add("WAS LOS WAR", (d.termine || []).length ? "Was los war: " + d.termine.map((t) => t.zeit + " " + t.titel).join(". ") : "");
    } else {
      add("JARVIS SAGT", m.text);
    }
    if (!out.length) add("JARVIS SAGT", m.text);
    readKeys = cards;
    return out;
  }
  function readNow() { if (!current || !A.readStart) return; reading = true; A.readStart(JSON.stringify(partsOf(current))); }
  function highlight(i) {
    const body = $("fp-body"), key = readKeys[i] || "hero";
    body.querySelectorAll(".reading").forEach((c) => c.classList.remove("reading"));
    let c = null;
    if (key === "hero") c = body.querySelector(".fp-hero");
    else if (key.startsWith("#day")) c = body.querySelectorAll(".fp-card")[+key.slice(4)];
    else c = [...body.querySelectorAll(".fp-card")].find((x) => (x.querySelector("h3") || {}).textContent && x.querySelector("h3").textContent.includes(key));
    if (c) { c.classList.add("reading"); c.scrollIntoView({ behavior: "smooth", block: "center" }); }
  }

  // --- Seite ---
  function open() { $("feed").classList.add("on"); stack = []; list(); }
  function close() { $("feed").classList.remove("on"); if (reading && A.readStop) A.readStop(); }
  function list() {
    $("fp-ttl").textContent = "MITTEILUNGEN";
    let a = []; try { a = JSON.parse(A.feedList() || "[]"); } catch (e) {}
    const seen = seenTs();
    if (a.length) setSeen(a[0].ts);
    dots(false);
    const shown = a.filter((m) => filter === "alle" || (KIND[m.kind] || [])[2] === filter);
    let h = `<div class="fp-now"><div data-now="heute">☀️ Heute<small>Tages-Update</small></div><div data-now="morgen">🌙 Abend<small>Tagesabschluss</small></div></div>
      <div class="fp-now"><div data-now="woche">🗓️ Nächste Woche<small>7 Tage voraus</small></div><div data-now="rueckblick">📊 Letzte Woche<small>Rückblick</small></div></div>
      <div class="fp-seg">${FILTERS.map(([k, n]) => `<span data-f="${k}" class="${k === filter ? "on" : ""}">${n}</span>`).join("")}</div>`;
    if (!shown.length) h += '<div class="fp-empty">Noch keine Mitteilungen.<br>Briefings, Fahrten und Anrufe erscheinen hier.</div>';
    let lastDay = "";
    const today = new Date().toDateString(), yest = new Date(Date.now() - 864e5).toDateString();
    for (const m of shown) {
      const ds = new Date(m.ts).toDateString();
      if (ds !== lastDay) { lastDay = ds; h += `<div class="fp-day">${ds === today ? "HEUTE" : ds === yest ? "GESTERN" : new Date(m.ts).toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "numeric" }).toUpperCase()}</div>`; }
      const k = KIND[m.kind] || ["🔔", "#0b2a3c"];
      h += `<div class="fp-it ${m.ts > seen ? "new" : ""}" data-id="${esc(m.id)}"><div class="fp-ic" style="background:${k[1]}">${k[0]}</div>
        <div><b>${esc(m.title)}</b><small>${esc(m.sub)}</small></div><div class="t">${hm(m.ts)}</div></div>`;
    }
    $("fp-body").innerHTML = h; $("fp-body").scrollTop = 0;
    $("fp-body").querySelectorAll("[data-id]").forEach((e) => e.addEventListener("click", () => detail(e.dataset.id, true)));
    $("fp-body").querySelectorAll("[data-f]").forEach((e) => e.addEventListener("click", () => { filter = e.dataset.f; list(); }));
    $("fp-body").querySelectorAll("[data-now]").forEach((e) => e.addEventListener("click", () => {
      e.innerHTML = "… einen Moment"; A.feedNow(e.dataset.now);
    }));
  }
  function detail(id, push) {
    let m = null; try { m = JSON.parse(A.feedGet(id)); } catch (e) {}
    if (!m) { list(); return; }
    if (push) stack.push("list");
    $("fp-ttl").textContent = "MITTEILUNG";
    const v = m.kind === "fahrt" || m.kind === "heimweg" || m.kind === "test" ? viewFahrt(m)
      : m.kind === "abend" && (m.data || {}).aufstehen !== undefined ? viewEvening(m)
      : m.kind === "morgen" || m.kind === "abend" ? viewDay(m) : m.kind === "bilanz" ? viewBilanz(m) : m.kind === "woche" ? viewWeek(m) : m.kind === "vorschau" ? viewAhead(m) : viewSimple(m);
    current = m;
    $("fp-body").innerHTML = readBar() + v;
    hookRead();
    if (/^(morgen|abend|woche|vorschau|bilanz)$/.test(m.kind) && autoRead) readNow();
    autoRead = true;
    $("fp-body").scrollTop = 0;
    $("fp-body").querySelectorAll("[data-maps]").forEach((e) => e.addEventListener("click", () => {
      const d = m.data || {}; const z = d.ziel === "zuhause" ? (d.home_addr || "") : d.ziel || "";
      location.href = "https://www.google.com/maps/dir/?api=1&destination=" + encodeURIComponent(z) + "&travelmode=" + e.dataset.maps;
    }));
  }
  function dots(on) { document.querySelectorAll(".feedbtn, .feedbtn2").forEach((b) => b.classList.toggle("has-new", !!on)); }
  function checkNew() {
    if (!A || !A.feedList) return;
    try { const a = JSON.parse(A.feedList() || "[]"); dots(a.length && a[0].ts > seenTs()); } catch (e) {}
  }

  ["feedbtn-f", "feedbtn-i"].forEach((id) => $(id) && $(id).addEventListener("click", open));
  $("fp-back").addEventListener("click", () => back());
  function back() {
    if (!$("feed").classList.contains("on")) return false;
    if (reading && A.readStop) A.readStop();
    if (stack.length) { stack.pop(); list(); } else close();
    return true;
  }
  setInterval(checkNew, 30000); setTimeout(checkNew, 1500);

  // Ereignisse aus der App: Benachrichtigung angetippt / Update fertig
  const prev = window.jarvis && window.jarvis.onEvent;
  const prevBack = window.jarvis && window.jarvis.back;
  if (window.jarvis) {
    window.jarvis.onEvent = function (type, data) {
      if (type === "read_pos") { highlight(data.i); return; }
      if (type === "read_end") { reading = false; document.querySelectorAll(".reading").forEach((c) => c.classList.remove("reading")); return; }
      if (type === "feed_open") { $("feed").classList.add("on"); stack = ["list"]; detail(data.id, false); setSeen(Date.now()); dots(false); return; }
      return prev && prev.call(window.jarvis, type, data);
    };
    window.jarvis.back = function () { return back() || (prevBack ? prevBack.call(window.jarvis) : false); };
  }
})();
