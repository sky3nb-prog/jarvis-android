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
    if (d.anziehen && d.anziehen.length) h += card("👕 ANZIEHEN", "#d7a8ff", chips(d.anziehen));
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
    if (d.anziehen && d.anziehen.length) h += card("👕 ANZIEHEN", "#d7a8ff", chips(d.anziehen));
    if (d.achtung && d.achtung.length) h += card("⚠️ PASS AUF", "var(--gold)", warns(d.achtung));
    if (d.termine && d.termine.length) h += card("📅 TERMINE", "var(--green)", d.termine.map((t) => `<div class="fp-row"><span class="z">${esc(t.zeit)}</span><span>${esc(t.titel)}${t.ort ? `<span class="o">${esc(t.ort)}</span>` : ""}</span></div>`).join(""));
    if (d.mitnehmen && d.mitnehmen.length) h += card("🎒 MITNEHMEN", "var(--gold-l)", todos(d.mitnehmen));
    return h + say(m.text);
  }

  function viewWeek(m) {
    const d = m.data || {};
    const visits = (d.besuche || []).reduce((s, b) => s + b.n, 0);
    let h = `<div class="fp-hero"><div class="fp-orb"></div><div class="k">WOCHEN-UPDATE · ${esc(d.von)} – ${esc(d.bis)}</div><h1>${esc(m.title)}</h1>
      <div class="s">So lief deine Woche.</div></div>`;
    h += `<div class="fp-card"><div class="fp-tiles"><div class="fp-tile"><b>${visits}</b><small>Besuche</small></div>
      <div class="fp-tile"><b>${Math.round(d.rad_km || 0)}</b><small>km Rad</small></div>
      <div class="fp-tile"><b>${Math.floor((d.musik_min || 0) / 60)}<span style="font-size:14px">h ${(d.musik_min || 0) % 60}m</span></b><small>Musik</small></div></div></div>`;
    if (d.besuche && d.besuche.length) h += card("📍 BESUCHE", "var(--green)", d.besuche.map((b) => `<div class="fp-row"><span class="z">${b.n}×</span><span>${esc(b.ort)}</span></div>`).join(""));
    if (d.termine && d.termine.length) h += card("📅 NÄCHSTE WOCHE", "var(--cyan)", d.termine.map((t) => `<div class="fp-row"><span class="z">${esc(t.zeit)}</span><span>${esc(t.titel)}${t.ort ? `<span class="o">${esc(t.ort)}</span>` : ""}</span></div>`).join(""));
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

  // --- Seite ---
  function open() { $("feed").classList.add("on"); stack = []; list(); }
  function close() { $("feed").classList.remove("on"); }
  function list() {
    $("fp-ttl").textContent = "MITTEILUNGEN";
    let a = []; try { a = JSON.parse(A.feedList() || "[]"); } catch (e) {}
    const seen = seenTs();
    if (a.length) setSeen(a[0].ts);
    dots(false);
    const shown = a.filter((m) => filter === "alle" || (KIND[m.kind] || [])[2] === filter);
    let h = `<div class="fp-now"><div data-now="heute">☀️ Tages-Update<small>für heute</small></div><div data-now="morgen">🌙 Für morgen<small>Update</small></div><div data-now="woche">📊 Woche<small>Rückblick</small></div></div>
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
      : m.kind === "morgen" || m.kind === "abend" ? viewDay(m) : m.kind === "woche" ? viewWeek(m) : viewSimple(m);
    $("fp-body").innerHTML = v; $("fp-body").scrollTop = 0;
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
    if (stack.length) { stack.pop(); list(); } else close();
    return true;
  }
  setInterval(checkNew, 30000); setTimeout(checkNew, 1500);

  // Ereignisse aus der App: Benachrichtigung angetippt / Update fertig
  const prev = window.jarvis && window.jarvis.onEvent;
  const prevBack = window.jarvis && window.jarvis.back;
  if (window.jarvis) {
    window.jarvis.onEvent = function (type, data) {
      if (type === "feed_open") { $("feed").classList.add("on"); stack = ["list"]; detail(data.id, false); setSeen(Date.now()); dots(false); return; }
      return prev && prev.call(window.jarvis, type, data);
    };
    window.jarvis.back = function () { return back() || (prevBack ? prevBack.call(window.jarvis) : false); };
  }
})();
