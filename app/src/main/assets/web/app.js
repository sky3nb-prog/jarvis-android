// Jarvis Handy-App – Oberfläche (Etappe 1: Kugel, Design, Reden mit Jarvis, Wetter/Uhr)
(function () {
  const $ = (id) => document.getElementById(id);
  const A = window.Android || null;   // Brücke zur App (Kotlin)
  const { Sphere, Rings } = window.JarvisGfx;

  // Echte 3D-Kugel (WebGL); falls das Handy kein WebGL kann, die alte flache Kugel
  const mkSphere = (c, seed) => { try { return new window.Sphere3D(c, seed); } catch (e) { return new Sphere(c, seed); } };
  const spheres = {
    fokus: mkSphere(document.querySelector("#sphere-fokus canvas"), 3),
    info: mkSphere(document.querySelector("#sphere-info canvas"), 5),
    steuern: mkSphere(document.querySelector("#sphere-steuern canvas"), 7),
  };
  // Gehirn in den Kugeln (nur bei der echten 3D-Kugel)
  const brains = {};
  for (const v of ["fokus", "info", "steuern"]) { const c = document.querySelector(`#sphere-${v} canvas.brain`); if (c && window.JarvisBrain && spheres[v].gl) brains[v] = new window.JarvisBrain(c, spheres[v]); }
  let powerOn = true;
  const strand = new window.Strand($("strand"), 4);
  let strandTarget = 0, dragging = false;
  const rings = new Rings(document.querySelector("#sphere-info canvas.rings"));
  let view = "fokus", talking = false, level = 0, target = 0;

  // --- Tabs ---
  const ORDER = ["fokus", "info", "lage", "steuern"];
  const el = (v) => $("v-" + v);
  function mark(v) {
    view = v; strandTarget = ORDER.indexOf(v); dragging = false;
    if (v === "lage" && window.JLage) window.JLage.shown();
    if (window.JSteuern && (v === "steuern" || v === "info")) window.JSteuern.refresh(v === "steuern");
    document.querySelectorAll(".view").forEach((e) => { e.classList.toggle("active", e.id === "v-" + v); e.classList.remove("peek", "slide"); e.style.transform = ""; });
    document.querySelectorAll(".tab").forEach((e) => e.classList.toggle("on", e.dataset.v === v));
    document.querySelectorAll("#dots i").forEach((d, i) => d.classList.toggle("on", ORDER[i] === v));
  }
  // Seite wechseln, mit Gleiten in die richtige Richtung
  function show(v, fromDx) {
    if (v === view) { mark(v); return; }
    const a = el(view), b = el(v), W = window.innerWidth, dir = ORDER.indexOf(v) > ORDER.indexOf(view) ? 1 : -1;
    const dx = fromDx || 0;
    b.classList.add("peek"); b.style.transform = `translateX(${dir * W + dx}px)`;
    a.style.transform = `translateX(${dx}px)`;
    void b.offsetWidth;
    a.classList.add("slide"); b.classList.add("slide");
    a.style.transform = `translateX(${-dir * W}px)`; b.style.transform = "translateX(0)";
    view = v;   // die neue Kugel läuft schon während des Gleitens
    strandTarget = ORDER.indexOf(v); dragging = false;
    if (v === "lage" && window.JLage) window.JLage.shown();
    if (window.JSteuern && (v === "steuern" || v === "info")) window.JSteuern.refresh(v === "steuern");
    document.querySelectorAll(".tab").forEach((e) => e.classList.toggle("on", e.dataset.v === v));
    document.querySelectorAll("#dots i").forEach((d, i) => d.classList.toggle("on", ORDER[i] === v));
    setTimeout(() => { if (view === v) mark(v); }, 300);
  }
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => show(t.dataset.v)));

  // --- Wischen zwischen Fokus / Info / Lage / Steuern ---
  (function swipe() {
    let x0 = 0, y0 = 0, t0 = 0, dx = 0, mode = 0, nb = null, dir = 0;   // mode: 0 offen, 1 waagrecht, 2 senkrecht
    const app = $("app");
    app.addEventListener("touchstart", (e) => {
      if (e.touches.length !== 1 || $("settings").classList.contains("on") || e.target.closest("nav") || e.target.closest("input[type=range], .mix")) { mode = 2; return; }
      if (view === "lage" && window.JLage && !window.JLage.swipeOk(e.target, e.touches[0].clientX)) { mode = 2; return; }
      x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; t0 = performance.now(); dx = 0; mode = 0; nb = null;
    }, { passive: true });
    app.addEventListener("touchmove", (e) => {
      if (mode === 2) return;
      const mx = e.touches[0].clientX - x0, my = e.touches[0].clientY - y0;
      if (mode === 0) {
        if (Math.abs(mx) < 12 && Math.abs(my) < 12) return;
        mode = Math.abs(mx) > Math.abs(my) * 1.2 ? 1 : 2;
        if (mode === 2) return;
      }
      const W = window.innerWidth, i = ORDER.indexOf(view);
      dir = mx < 0 ? 1 : -1;
      const nv = ORDER[i + dir];
      dx = nv ? mx : mx * 0.3;   // am Rand nur ein bisschen nachgeben
      const cur = el(view);
      cur.classList.add("dragging"); cur.style.transform = `translateX(${dx}px)`;
      dragging = true; strand.offset = i - dx / W;
      const nEl = nv ? el(nv) : null;
      if (nb && nb !== nEl) { nb.classList.remove("peek", "dragging"); nb.style.transform = ""; }
      nb = nEl;
      if (nb) { nb.classList.add("peek", "dragging"); nb.style.transform = `translateX(${dx + dir * W}px)`; }
    }, { passive: true });
    const end = () => {
      if (mode !== 1) { mode = 0; return; }
      mode = 0;
      const W = window.innerWidth, v = Math.abs(dx) / Math.max(1, performance.now() - t0);
      const i = ORDER.indexOf(view), nv = ORDER[i + dir];
      document.querySelectorAll(".view").forEach((e) => e.classList.remove("dragging"));
      dragging = false;
      if (nv && (Math.abs(dx) > W * 0.22 || v > 0.5)) show(nv, dx);
      else {   // zurückschnappen
        const cur = el(view); cur.classList.add("slide"); cur.style.transform = "translateX(0)";
        if (nb) { nb.classList.add("slide"); nb.style.transform = `translateX(${dir * W}px)`; }
        const keep = view; setTimeout(() => { if (view === keep) mark(keep); }, 300);
      }
      nb = null;
    };
    app.addEventListener("touchend", end); app.addEventListener("touchcancel", end);
  })();

  // --- Reden ---
  function toggleTalk() {
    if (A) A.toggleTalk(); else toast("Nur in der App verfügbar.");
  }
  $("callbtn").addEventListener("click", toggleTalk);
  let curState = "ended";
  document.querySelectorAll(".sphere-wrap").forEach((w) => w.addEventListener("click", () => {
    if (view !== "fokus") show("fokus");
    if (A && curState === "speaking") A.interrupt(); else toggleTalk();  // spricht er: nur unterbrechen
  }));

  const STATES = { connecting: "verbinde …", listening: "hört zu …", thinking: "denkt nach …", speaking: "spricht …",
                   ended: "bereit", idle: "bereit" };
  function setState(st) {
    curState = st;
    talking = st !== "ended" && st !== "idle";
    $("fokus-state").textContent = !talking && !powerOn ? "schläft" : (STATES[st] || st);
    $("callbtn").textContent = talking ? "Gespräch beenden" : "Gespräch starten";
    $("callbtn").classList.toggle("live", talking);
    $("fokus-hint").textContent = talking ? "Sprich einfach – du kannst ihn jederzeit unterbrechen"
                                          : "Tipp auf die Kugel, um mit Jarvis zu reden";
    Object.values(spheres).forEach((s) => (s.state = st));
    if (!talking) target = 0;
    applyLook();
  }

  let toastTimer = 0;
  function toast(text) {
    const t = $("toast"); t.textContent = text; t.style.display = "block";
    clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.style.display = "none"), 5000);
  }

  // Schreiben statt reden: getippt = leise Antwort als Text
  function tbSend() {
    const t = $("tb-in").value.trim(); if (!t || !A || !A.askText) return;
    $("tb-in").value = ""; $("tb-in").blur();
    $("last-you").textContent = t; $("last-jar").textContent = "denkt nach …";
    $("talkbox").classList.add("long");
    A.askText(t);
  }
  if ($("tb-send")) {
    $("tb-send").addEventListener("click", tbSend);
    $("tb-in").addEventListener("keydown", (e) => { if (e.key === "Enter") tbSend(); });
  }

  window.jarvis = {
    onEvent(type, data) {
      if (type === "state") setState(data.state);
      else if (type === "user" || type === "partial") $("last-you").textContent = data.text;
      else if (type === "needkey") askKey();
      else if (type === "agent") $("last-jar").textContent = data.text;
      else if (type === "level") { if (data.kind === "out" || !talking) target = data.value; else target = Math.max(target * 0.8, data.value * 0.6); }
      else if (type === "error") { toast(data.text); setState("ended"); }
      else if (type === "model" || type === "info" || type === "synced") toast(data.text);
      else if (type === "power") showPower(!!data.on);
      else if (type === "lage") { if (data.tour && prefsUi.lage_jump !== false) show("lage"); if (window.JLage) window.JLage.onData(data.data, !!data.tour); }
      else if (type === "lage_focus") { if (window.JLage) window.JLage.onFocus(data.i, data.n, data.of); }
      else if (type === "lage_error") { if (window.JLage) window.JLage.onError(data.text, data.ort); }
      else if (type === "pc_reply") { if (window.JSteuern) window.JSteuern.onReply(data); }
      else if (type === "pc_status") { if (window.JSteuern) window.JSteuern.onStatus(data); }
      else if (type === "think") { const k = data.kinds || []; Object.values(brains).forEach((b) => b.think(k, data.ms || 4000)); }
      else if (type === "tle") { if (window.JLage) window.JLage.tle(data.text); }
      else if (type === "home") { if (window.JLage) window.JLage.home(); }
    },
    back() {
      if (window.jSettingsBack && window.jSettingsBack()) return true;
      if ($("settings").classList.contains("on")) { $("settings").classList.remove("on"); return true; }
      for (const id of ["ask-aus", "ask-text"]) if ($(id) && $(id).classList.contains("on")) { $(id).classList.remove("on"); return true; }
      if (view !== "fokus") { show("fokus"); return true; } return false;
    },
  };

  // --- Ein/Aus: Jarvis hört im Hintergrund zu oder ist ganz aus ---
  function showPower(on) {
    powerOn = on;
    $("powerbtn").classList.toggle("on", on);
    applyLook();
  }
  // Aus = Kugel grau und "schläft" (solange er nicht gerade redet)
  function applyLook() {
    const awake = powerOn || talking;
    Object.values(spheres).forEach((s) => (s.power = awake));
    $("v-fokus").classList.toggle("asleep", !awake);
    $("fokus-hint").classList.toggle("gone", !awake);
    if (!talking) $("fokus-state").textContent = powerOn ? "bereit" : "schläft";
  }
  function readPower() {
    try { showPower(!!JSON.parse(A.getSettings()).background); } catch (e) {}
  }
  {
    $("powerbtn").addEventListener("click", (e) => {
      e.stopPropagation();
      if (!A) return;
      const on = !$("powerbtn").classList.contains("on");
      A.setPower(on);
      showPower(on);
      toast(on ? "Jarvis ist an und hört auf sein Aktivierungswort." : "Jarvis ist aus. Er hört nicht mehr zu.");
    });
    if (A) readPower();
    document.addEventListener("visibilitychange", () => { if (!document.hidden && A) readPower(); });
  }

  // --- Einstellungen ---
  function askKey() {
    setState("ended");
    const k = window.prompt("Für die kostenlose Stimme und das Aktivierungswort brauche ich Groq.\n\n" +
      "Bitte einmal deinen Groq-Schlüssel eintragen (console.groq.com → API Keys, beginnt mit gsk_):", "");
    if (k && k.trim().length > 20 && A) { A.setGroqKey(k.trim()); A.startTalk(); }
    else if (k !== null) toast("Das sah nicht nach einem Groq-Schlüssel aus.");
  }
  // Schalter (an/aus) in den Einstellungen
  const sw = (id, on) => { const e = $(id); if (on === undefined) return e.classList.contains("on"); e.classList.toggle("on", !!on); };
  document.querySelectorAll(".sheet .sw").forEach((e) => e.addEventListener("click", () => {
    e.classList.toggle("on");
    if (e.id === "set-loc" && e.classList.contains("on") && A && A.askLocation) A.askLocation();
  }));
  // Neue Einstellungen: kleiner roter Punkt (am Zahnrad und am Bereich), bis du den Bereich einmal geöffnet hast.
  // Bei jedem Update ergänzen: Bereich -> Kennung des Updates
  const NEW_TABS = { wege: "wege1", allg: "schau1", leute: "leute1", alltag: "alltag1", fern: "fern1" };
  const seenGet = () => { try { return JSON.parse(localStorage.getItem("seen_new") || "[]"); } catch (e) { return []; } };
  const seenAdd = (k) => { try { const s = seenGet(); if (!s.includes(k)) { s.push(k); localStorage.setItem("seen_new", JSON.stringify(s)); } } catch (e) {} };
  function newDots() {
    const seen = seenGet();
    let any = false;
    document.querySelectorAll("#stabs span, .sitem").forEach((t) => {
      const k = t.dataset.p || t.dataset.go;
      const n = NEW_TABS[k] && !seen.includes(NEW_TABS[k]);
      any = any || !!n;
      let d = t.querySelector(".ndot");
      if (n && !d) t.insertAdjacentHTML("beforeend", '<b class="ndot"></b>');
      if (!n && d) d.remove();
    });
    $("btn-settings").classList.toggle("hasnew", any);
  }
  newDots();
  // Einstellungen wie am Handy: Übersicht -> Bereich antippen -> eigene Seite, "‹" zurück
  const PAGE_NAMES = { home: "EINSTELLUNGEN", allg: "ALLGEMEIN", hoer: "ZUHÖREN", stimme: "STIMME", anz: "ANZEIGE", alltag: "ALLTAG & WECKER",
    wege: "WEGE & ORTE", leute: "LEUTE & ANRUFE", lage: "LAGE", fern: "FERNZUGRIFF", fit: "GESUNDHEIT & SCHLAF", sys: "SYSTEMSTATUS", schrank: "KLEIDERSCHRANK" };
  let setPage = "home";
  function showPage(p) {
    setPage = p;
    document.querySelectorAll(".spane").forEach((x) => x.classList.toggle("on", x.id === "sp-" + p));
    document.querySelectorAll("#stabs span").forEach((x) => x.classList.toggle("on", x.dataset.p === p));
    document.querySelector("#settings .sttl").textContent = PAGE_NAMES[p] || "EINSTELLUNGEN";
    $("settings").classList.toggle("ssub", p !== "home");
    document.querySelector("#settings .spanes").scrollTop = 0;
    if (NEW_TABS[p]) { seenAdd(NEW_TABS[p]); setTimeout(newDots, 1500); }
    const tab = document.querySelector(`#stabs span[data-p="${p}"]`); if (tab) tab.click && tab.dispatchEvent(new Event("pageopen"));
  }
  window.jSettingsBack = () => { if ($("settings").classList.contains("on") && setPage !== "home") { showPage("home"); return true; } return false; };
  document.querySelectorAll(".sitem").forEach((t) => t.addEventListener("click", () => {
    showPage(t.dataset.go);
    const tab = document.querySelector(`#stabs span[data-p="${t.dataset.go}"]`); if (tab) tab.click();
  }));
  document.querySelectorAll("#stabs span").forEach((t) => t.addEventListener("click", () => {
    if (setPage !== t.dataset.p) showPage(t.dataset.p);
  }));
  if ($("set-screen")) $("set-screen").addEventListener("click", () => { if (A && A.openScreenAccess) A.openScreenAccess(); });
  const perm = (id, ok, txt) => { const e = $(id); e.textContent = ok ? "erlaubt" : (txt || "Erlauben"); e.classList.toggle("ok", !!ok); };

  function openSettings() {
    if (!A) return;
    $("set-mode").value = A.getVoiceMode();
    const sel = $("set-voice");
    sel.length = 1;
    try {
      const v = JSON.parse(A.getTtsVoices() || "{}");
      (v.list || []).forEach((n) => { const o = document.createElement("option"); o.value = n; o.textContent = n; sel.appendChild(o); });
      if (v.current) sel.value = v.current;
      if (!(v.list || []).length) sel.options[0].textContent = "Automatisch (Liste erscheint nach dem ersten kostenlosen Gespräch)";
    } catch (e) {}
    try {
      const c = JSON.parse(A.getSettings());
      sw("set-bg", c.background);
      $("set-wake").value = c.wake_words || "jarvis";
      $("set-level").value = String(c.wake_level);
      $("set-cloud").value = c.wake_cloud ? "1" : "0";
      $("set-jvol").value = c.jarvis_volume || 70;
      $("set-orte").value = c.lage_orte || "";
      $("set-tselbst").value = c.themen_selbst || "";
      showThemen();
      $("set-name").value = c.assistant_name || "";
      $("set-anrede").value = c.anrede || "";
      $("set-city").value = c.city || "";
      $("set-addr").value = c.address || "";
      const cals = c.calendars || [];
      $("set-cal").innerHTML = '<option value="-1">Automatisch (Google-Hauptkalender)</option>' + cals.map((k) =>
        `<option value="${k.id}">${String(k.name).replace(/</g, "")} · ${k.kind}${k.account && k.account !== k.name ? " (" + String(k.account).replace(/</g, "") + ")" : ""}</option>`).join("");
      $("set-cal").value = String(c.calendar_id != null ? c.calendar_id : -1);
      if (!$("set-cal").value) $("set-cal").value = "-1";
      $("set-morte").value = c.orte || ""; $("set-mwege").value = c.wege || ""; $("set-routean").value = c.route_an || "";
      sw("set-loc", c.use_location);
      $("set-locstate").innerHTML = c.here ? "Gerade: <b style='color:#6effcd'>" + c.here + "</b>" : (c.use_location ? "Standort wird beim nächsten Mal ermittelt." : "");
      sw("set-ljump", c.lage_jump !== false); sw("set-lzoom", c.lage_zoom !== false); sw("set-lspin", c.lage_spin !== false);
      sw("set-lorbit", c.lage_orbits !== false); sw("set-llabels", c.lage_labels !== false); sw("set-strand", c.strand !== false);
      perm("set-screen", c.screen_ok, "Einrichten");
      $("set-gstate").textContent = c.has_gemini ? "● gespeichert" : "";
      $("set-wichtig").value = c.wichtig || ""; $("set-absage").value = c.absage || ""; sw("set-butler", c.butler !== false);
      $("set-wlan").value = c.heim_wlan || ""; sw("set-wegauto", c.weg_auto !== false); sw("set-losfahren", c.losfahren !== false); fwShow();
      $("set-ankunft").value = c.ankunft || ""; $("set-anzieh").value = c.anzieh || "";
      sw("set-bmorgen", c.brief_morgen !== false); sw("set-babend", c.brief_abend !== false); $("set-babendzeit").value = c.brief_abend_zeit || "20:00";
      sw("set-biwetter", c.bi_wetter !== false); sw("set-bianzieh", c.bi_anzieh !== false); sw("set-bitermine", c.bi_termine !== false); sw("set-bimit", c.bi_mitnehmen !== false);
      sw("set-rueck", c.rueckblick !== false); $("set-rueckzeit").value = c.rueckblick_zeit || "20:30";
      sw("set-schlaftipp", c.schlaf_tipp !== false); $("set-ticket").value = c.ticket_art || "erwachsen"; sw("set-termerin", c.termin_erinnern !== false); $("set-termvor").value = c.termin_vorher != null ? c.termin_vorher : 15; rmList();
      sw("set-bilanz", c.bilanz !== false); $("set-bilanzzeit").value = c.bilanz_zeit || "22:00";
      perm("set-locall", c.loc_ok && c.loc_always, "Erlauben");
      sw("wk-an", c.wecker_an !== false); $("wk-schule").value = (c.wecker_schule || "07:10").padStart(5, "0"); $("wk-we").value = c.wecker_we ? c.wecker_we.padStart(5, "0") : "";
      wkDays(c.wecker_tage || {});
      $("wk-vorher").value = c.wecker_vorher || "25, 20, 5"; wkInfo();
      perm("set-butlerok", c.butler_ok); perm("set-files", c.files_ok); perm("set-media2", !!c.media_ok);
      perm("set-overlay", c.overlay); perm("set-usage", c.usage); perm("set-media", !!c.media_ok);
      $("set-mediastate").textContent = c.media || "";
      $("set-link").value = c.link_code || "";
      $("set-linkstate").textContent = c.link_code
        ? (c.synced ? "Gekoppelt · zuletzt abgeglichen " + new Date(c.synced).toLocaleString("de-DE", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }) + " · " + c.facts + " Dinge über dich"
                    : "Code eingetragen – warte auf den PC (Jarvis am PC muss laufen).")
        : "Noch nicht gekoppelt. Ohne Code merkt sich das Handy alles nur für sich.";
      $("set-status").textContent = c.model ? "Spracherkennung fürs Aktivierungswort ist geladen." : "Spracherkennung wird noch geladen (45 MB, einmalig) – bis dahin prüft Groq.";
    } catch (e) {}
    $("set-key").value = "";
    $("set-version").textContent = "Version " + A.version() + (A.hasGroqKey() ? " · Groq-Schlüssel ist gespeichert" : " · noch kein Groq-Schlüssel");
    showPage("home");
    if ($("set-version2")) $("set-version2").textContent = $("set-version").textContent;
    $("settings").classList.add("on");
    fix24all();
  }
  $("btn-settings").addEventListener("click", openSettings);
  $("set-overlay").addEventListener("click", () => A.askOverlay());
  $("set-overlay2").addEventListener("click", () => A.askOverlay());
  $("set-battery").addEventListener("click", () => A.askBattery());
  $("set-media").addEventListener("click", () => { A.askMedia(); toast("Bei „Jarvis“ den Benachrichtigungszugriff einschalten."); });
  $("set-usage").addEventListener("click", () => { A.askUsage(); toast("Bei „Jarvis“ den Nutzungszugriff einschalten."); });
  $("set-media2").addEventListener("click", () => { A.askMedia(); toast("Bei „Jarvis“ den Benachrichtigungszugriff einschalten."); });
  $("set-files").addEventListener("click", () => { A.askFiles(); toast("Bei „Jarvis“ den Zugriff auf alle Dateien einschalten."); });
  $("set-butlerok").addEventListener("click", () => A.askButler());
  // Uhrzeiten immer im 24-Stunden-Format (kein AM/PM): eigenes Feld "HH:MM"
  function fix24(el) {
    if (el.dataset.f24) return; el.dataset.f24 = "1";
    const v = el.value; el.type = "text"; el.inputMode = "numeric"; el.maxLength = 5; el.placeholder = el.placeholder || "--:--"; el.value = v;
    el.classList.add("t24");
    el.addEventListener("input", () => {
      let d = el.value.replace(/\D/g, "").slice(0, 4);
      if (d.length >= 3) d = d.slice(0, d.length - 2) + ":" + d.slice(-2);
      el.value = d;
    });
    el.addEventListener("blur", () => {
      const m = el.value.match(/^(\d{1,2}):?(\d{2})?$/); if (!m) { el.value = ""; return; }
      const h = Math.min(23, +m[1]), mi = Math.min(59, +(m[2] || 0));
      el.value = String(h).padStart(2, "0") + ":" + String(mi).padStart(2, "0");
      el.dispatchEvent(new Event("change"));
    });
  }
  function fix24all() { document.querySelectorAll('input[type="time"]').forEach(fix24); }
  fix24all();
  // Datum als Auswahl der nächsten 60 Tage ("Sa 14.11.") statt US-Datumsfeld
  (function () {
    const d0 = $("em-datum"); if (!d0 || d0.tagName === "SELECT") return;
    const sel = document.createElement("select"); sel.id = "em-datum";
    for (let i = 0; i < 60; i++) { const d = new Date(); d.setDate(d.getDate() + i); const o = document.createElement("option");
      o.value = d.toLocaleDateString("sv-SE"); o.textContent = (i === 0 ? "Heute, " : i === 1 ? "Morgen, " : i === 2 ? "Übermorgen, " : "") + d.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" }); sel.appendChild(o); }
    d0.replaceWith(sel);
  })();
  // Wecker pro Wochentag (Kalender-Zählung: So=1 … Sa=7)
  const WK = [["2", "Mo"], ["3", "Di"], ["4", "Mi"], ["5", "Do"], ["6", "Fr"], ["7", "Sa"], ["1", "So"]];
  function wkDays(t) {
    $("wk-days").innerHTML = WK.map(([k, n]) => `<div class="wk-d"><b>${n}</b><input type="time" data-wk="${k}" value="${t[k] ? String(t[k]).padStart(5, "0") : ""}"><span class="wk-x" data-wkx="${k}">×</span></div>`).join("");
    $("wk-days").querySelectorAll("[data-wkx]").forEach((e) => e.addEventListener("click", () => { $("wk-days").querySelector(`[data-wk="${e.dataset.wkx}"]`).value = ""; wkInfo(); }));
    $("wk-days").querySelectorAll("[data-wk]").forEach((e) => { fix24(e); e.addEventListener("change", wkInfo); });
  }
  function wkTage() { const o = {}; $("wk-days").querySelectorAll("[data-wk]").forEach((e) => (o[e.dataset.wk] = e.value || "")); return o; }
  function wkInfo() {
    const tg = wkTage(); const first = WK.map(([k]) => tg[k]).find((x) => x);
    if (first) $("wk-schule").value = first;
    const up = first; if (!up) { $("wk-info").textContent = "An keinem Tag ein Wecker."; return; }
    const [h, m] = up.split(":").map(Number), off = ($("wk-vorher").value || "25,20,5").split(/[,; ]+/).map((x) => Math.abs(parseInt(x, 10))).filter((x) => x > 0).sort((a, b) => b - a);
    const t = off.map((o) => { const v = (h * 60 + m - o + 1440) % 1440; return Math.floor(v / 60) + ":" + String(v % 60).padStart(2, "0"); });
    const tage = WK.filter(([k]) => wkTage()[k]).map(([, n]) => n).join(", ");
    $("wk-info").textContent = `${tage}: z. B. bei ${h}:${String(m).padStart(2, "0")} Wecker um ${t.join(", ")}. Jeden Abend ab 19 Uhr für den nächsten Tag gestellt, dein Tages-Update kommt zur Aufsteh-Zeit.`;
  }
  ["wk-schule", "wk-vorher"].forEach((id) => $(id).addEventListener("input", wkInfo));
  // Fester Weg (jede Woche) und einmalige Termine
  function fwShow() {
    let f = {}; try { f = JSON.parse(A.festGet() || "{}"); } catch (e) {}
    sw("fw-an", f.an !== false); $("fw-tag").value = f.tag || "do"; $("fw-mode").value = f.mode || "ebike";
    $("fw-ziel").value = f.ziel || ""; $("fw-name").value = f.name || ""; $("fw-wer").value = f.wer || "";
    $("fw-bhin").value = f.bahn_hin || "regen"; $("fw-bback").value = f.bahn_zurueck || "regen";
    $("fw-los").value = f.los || ""; $("fw-heim").value = f.zuhause || "";
    emList();
  }
  const isoDay = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return d.toLocaleDateString("sv-SE"); };
  function emList() {
    let a = []; try { a = JSON.parse(A.einmaligGet() || "[]"); } catch (e) {}
    const fmt = (d) => new Date(d + "T12:00").toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" });
    $("em-list").innerHTML = a.length ? a.map((o, i) => `<div class="srow"><div>${fmt(o.datum)}: ${o.aus ? "fester Weg fällt aus"
      : `${String(o.name || o.ziel).replace(/</g, "")}, los ${o.los}${o.zuhause ? ", zuhause " + o.zuhause : ""}`}</div><div class="sbtn" data-del="${i}">×</div></div>`).join("")
      : '<div class="note">Keine einmaligen Termine.</div>';
    $("em-list").querySelectorAll("[data-del]").forEach((e) => e.addEventListener("click", () => { A.einmaligRemove(+e.dataset.del); emList(); }));
  }
  document.querySelector('[data-p="alltag"]').addEventListener("click", fwShow);
  $("em-datum").value = isoDay(0);
  document.querySelectorAll("[data-em]").forEach((e) => e.addEventListener("click", () => { $("em-datum").value = isoDay(+e.dataset.em); }));
  const emData = () => ({ datum: $("em-datum").value || isoDay(0), ziel: $("em-ziel").value.trim(), name: $("em-name").value.trim(),
    wer: $("em-wer").value.trim(), los: $("em-los").value, zuhause: $("em-heim").value, mode: $("em-mode").value });
  $("em-add").addEventListener("click", () => { toast(A.einmaligAdd(JSON.stringify(emData()))); emList(); });
  $("em-aus").addEventListener("click", () => { toast(A.einmaligAdd(JSON.stringify({ datum: $("em-datum").value || isoDay(0), aus: true }))); emList(); });
  $("set-test").addEventListener("click", () => { A.testAlltag(); toast("Testnachricht kommt gleich als Benachrichtigung."); });
  // Gassi + SMS-Tests (sofort gespeichert)
  try { const g = JSON.parse(A.getGassi() || "{}"); sw("gs-an", !!g.an); sw("gs-sms", !!g.sms); $("gs-wer").value = g.wer || "Mama"; $("gs-text").value = g.text || ""; } catch (e) {}
  const saveGassi = () => { try { A.setGassi($("gs-an").classList.contains("on"), $("gs-sms").classList.contains("on"), $("gs-wer").value, $("gs-text").value); } catch (e) {} };
  ["gs-an", "gs-sms"].forEach((id) => $(id).addEventListener("click", () => setTimeout(saveGassi, 50)));
  ["gs-wer", "gs-text"].forEach((id) => $(id).addEventListener("change", saveGassi));
  $("gs-test").addEventListener("click", () => { saveGassi(); toast(A.gassiTestSms()); });
  $("gs-infobtn").addEventListener("click", () => { $("gs-info").textContent = A.gassiStatus(); });
  $("gs-share").addEventListener("click", () => { toast("Schicke …"); setTimeout(() => toast(A.gassiShare()), 50); });
  $("tst-sms").addEventListener("click", () => toast(A.testSms($("tst-smswer").value || "")));
  try { sw("set-bootanim", localStorage.getItem("boot_anim") !== "0"); } catch (e) {}
  $("set-bootanim").addEventListener("click", () => setTimeout(() => { try { localStorage.setItem("boot_anim", sw("set-bootanim") ? "1" : "0"); } catch (e) {} }, 50));
  try { sw("set-melden", A.getFlag("melden", true)); } catch (e) {}
  $("set-melden").addEventListener("click", () => setTimeout(() => { try { A.setFlag("melden", sw("set-melden")); } catch (e) {} }, 50));
  $("tst-boot").addEventListener("click", () => { closeSettings(); setTimeout(() => window.JBoot && JBoot.play(), 350); });
  $("tst-check").addEventListener("click", () => { closeSettings(); setTimeout(() => { let it = []; try { it = JSON.parse(A.sysCheck(false)).items || []; } catch (e) {} window.JCheck && JCheck.play(it); }, 350); });
  $("lern-btn").addEventListener("click", () => { try { $("lern-info").textContent = A.lernInfo(); } catch (e) {} });
  $("lern-reset").addEventListener("click", () => { try { A.lernReset(); $("lern-info").textContent = A.lernInfo(); toast("Alles wieder an."); } catch (e) {} });
  $("set-testbahn").addEventListener("click", () => { A.testBahnZiel(($("bahn-ziel").value || "").trim()); toast("Ich suche die Verbindung beim VVS …"); });
  { const tb = $("tst-bahn"); if (tb) tb.addEventListener("click", () => { A.testBahnZiel(""); toast("Ich suche die Verbindung beim VVS …"); }); }
  try { const bs = JSON.parse(A.getBahn() || "{}"); $("bahn-art").value = bs.art || "rad_bahn"; $("ticket-app").value = bs.app || "vvs"; } catch (e) {}
  const saveBahn = () => { try { A.setBahn($("bahn-art").value, $("ticket-app").value, $("set-ticket").value); toast("Gespeichert."); } catch (e) {} };
  ["bahn-art", "ticket-app", "set-ticket"].forEach((id) => $(id).addEventListener("change", saveBahn));
  $("set-haltebtn").addEventListener("click", () => { try { $("set-halte").textContent = A.halteInfo() || "Noch nichts gelernt."; } catch (e) {} });
  // --- Jarvis-Erinnerungen ---
  function rmList() {
    if (!A || !A.remindList) return;
    let a = []; try { a = JSON.parse(A.remindList() || "[]"); } catch (e) {}
    const when = (r) => r.at ? new Date(r.at).toLocaleString("de-DE", { weekday: "short", hour: "2-digit", minute: "2-digit" }) : (r.datum ? new Date(r.datum + "T12:00").toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" }) + " · ohne Uhrzeit" : "");
    $("rm-list").innerHTML = a.length ? a.map((r) => `<div class="srow"><div>${r.text}<small>${when(r)}</small></div><div class="sbtn" data-rmdone="${r.id}">Erledigt</div></div>`).join("")
      : '<div class="note" style="margin:0">Keine offenen Erinnerungen. Sag z. B. „Friday, erinnere mich um 12:30 an Brot“.</div>';
    $("rm-list").querySelectorAll("[data-rmdone]").forEach((e) => e.addEventListener("click", () => { A.remindDone(e.dataset.rmdone); rmList(); }));
  }
  document.querySelectorAll("[data-calnotif]").forEach((e) => e.addEventListener("click", () => A && A.openCalNotif && A.openCalNotif(e.dataset.calnotif)));

  // --- Kleiderschrank ---
  let WS = null;
  const LAYERS = [["jacke", "🧥 JACKEN – DRÜBER", "#ffd678"], ["drunter", "👕 OBERTEILE – DRUNTER", "#6effcd"], ["mitte", "🧶 PULLIS & CO.", "#d7a8ff"], ["hose", "👖 HOSEN", "#3cc8ff"], ["extra", "🧢 EXTRAS", "#ff9a8a"]];
  const LO = -15, HI = 35;
  const tlabel = (v, lo) => (lo && v <= LO ? "kalt" : !lo && v >= HI ? "heiß" : v + " °C");
  function wsSave() { if (A && A.schrankSave) A.schrankSave(JSON.stringify(WS)); wsToday(); }
  function wsToday() {
    let p = {}; try { p = JSON.parse(A.schrankHeute() || "{}"); } catch (e) {}
    const icon = (n) => { const it = (WS.items || []).find((x) => x.name === n); return it ? it.icon : "•"; };
    $("ws-hero").querySelector("small").textContent = (p.tag || "HEUTE").toUpperCase() + " ANZIEHEN" + (p.min != null ? ` · ${p.min}° BIS ${p.max}°` : "");
    $("ws-today").innerHTML = p.error ? `<span class="ws-chip">${p.error}</span>` : (p.anziehen || []).map((n) => `<span class="ws-chip">${icon(n)} ${n}</span>`).join("");
    $("ws-why").textContent = p.warum || "";
  }
  function wsRender() {
    $("ws-layers").innerHTML = LAYERS.map(([l, title, col]) => `<div class="sec" style="--c:${col}"><h3>${title}</h3>` +
      (WS.items || []).map((it, i) => it.layer !== l ? "" : `<div class="ws-card ${it.on === false ? "off" : ""}" data-i="${i}">
        <div class="ws-top"><span class="ws-ic">${it.icon}</span><b>${it.name}</b>${it.rain ? '<span class="ws-tag">bei Regen</span>' : ""}<div class="sw ${it.on !== false ? "on" : ""}" data-on="${i}"></div></div>
        ${it.rain && l === "extra" ? '<div class="ws-rng-l">kommt nur bei Regen mit</div>' : `<div class="ws-rng" style="--a:${(Math.max(LO, it.min) - LO) / (HI - LO) * 100}%;--b:${(Math.min(HI, it.max) - LO) / (HI - LO) * 100}%">
          <input type="range" min="${LO}" max="${HI}" step="1" value="${Math.max(LO, it.min)}" data-min="${i}"><input type="range" min="${LO}" max="${HI}" step="1" value="${Math.min(HI, it.max)}" data-max="${i}"></div>
        <div class="ws-rng-l"><span>${tlabel(Math.max(LO, it.min), true)}</span><span>bis</span><span>${tlabel(Math.min(HI, it.max), false)}</span></div>`}
        ${it.custom ? `<div class="ws-del" data-del="${i}">entfernen</div>` : ""}</div>`).join("") + "</div>").join("");
    $("ws-layers").querySelectorAll("[data-on]").forEach((e) => e.addEventListener("click", () => { const it = WS.items[+e.dataset.on]; it.on = it.on === false; wsRender(); wsSave(); }));
    $("ws-layers").querySelectorAll("[data-del]").forEach((e) => e.addEventListener("click", () => { WS.items.splice(+e.dataset.del, 1); wsRender(); wsSave(); }));
    $("ws-layers").querySelectorAll(".ws-rng input").forEach((e) => {
      e.addEventListener("input", () => {
        const i = +(e.dataset.min || e.dataset.max), it = WS.items[i], wrap = e.parentElement;
        const a = +wrap.querySelector("[data-min]").value, b = +wrap.querySelector("[data-max]").value;
        const lo = Math.min(a, b), hi = Math.max(a, b);
        it.min = lo <= LO ? -30 : lo; it.max = hi >= HI ? 40 : hi;
        wrap.style.setProperty("--a", (lo - LO) / (HI - LO) * 100 + "%"); wrap.style.setProperty("--b", (hi - LO) / (HI - LO) * 100 + "%");
        const l = wrap.nextElementSibling.children; l[0].textContent = tlabel(lo, true); l[2].textContent = tlabel(hi, false);
      });
      e.addEventListener("change", wsSave);
    });
    sw("ws-dick", WS.dickeJacke !== false); sw("ws-wind", WS.wind !== false); sw("ws-tag", WS.tag_drinnen !== false); sw("ws-fragen", WS.fragen !== false);
    $("ws-in").value = WS.drinnen || 21; $("ws-inv").textContent = WS.drinnen || 21;
    const orte = WS.orte || {}, names = [...new Set([...(WS.ortnamen || []), ...Object.keys(orte)])];
    $("ws-orte").innerHTML = names.length ? names.map((n) => `<div class="srow"><div style="text-transform:capitalize">${n}</div><div class="ws-seg" data-ort="${n}"><span data-v="drinnen" class="${orte[n] === "drinnen" ? "on" : ""}">Drinnen</span><span data-v="draussen" class="${orte[n] !== "drinnen" ? "on" : ""}">Draußen</span></div></div>`).join("")
      : '<div class="note" style="margin:0">Noch keine Orte – trag sie unter Wege & Orte ein.</div>';
    $("ws-orte").querySelectorAll(".ws-seg span").forEach((e) => e.addEventListener("click", () => { WS.orte = WS.orte || {}; WS.orte[e.parentElement.dataset.ort] = e.dataset.v; wsRender(); wsSave(); }));
    const adj = +(WS.adj || 0);
    $("ws-adj").innerHTML = adj ? `Gelernt: <b>${adj > 0 ? "dir ist schnell warm" : "dir ist schnell kalt"}</b> – Grenzen ${adj > 0 ? "+" : ""}${adj.toFixed(1)} °C verschoben<small>aus ${(WS.log || []).length} Rückmeldungen</small>` : "Noch nichts angepasst<small>Kommt mit deinen Rückmeldungen</small>";
  }
  function wsShow() { try { WS = JSON.parse(A.schrankGet() || "{}"); } catch (e) { WS = { items: [] }; } wsRender(); setTimeout(wsToday, 30); }
  document.querySelector('[data-p="schrank"]').addEventListener("click", wsShow);
  $("go-schrank").addEventListener("click", () => { showPage("schrank"); wsShow(); });
  [["ws-dick", "dickeJacke"], ["ws-wind", "wind"], ["ws-tag", "tag_drinnen"], ["ws-fragen", "fragen"]].forEach(([id, k]) =>
    $(id).addEventListener("click", () => setTimeout(() => { WS[k] = sw(id); wsSave(); }, 0)));
  $("ws-in").addEventListener("input", () => { $("ws-inv").textContent = $("ws-in").value; });
  $("ws-in").addEventListener("change", () => { WS.drinnen = +$("ws-in").value; wsSave(); });
  $("ws-reset").addEventListener("click", () => { WS.adj = 0; WS.log = []; wsRender(); wsSave(); toast("Zurückgesetzt."); });
  $("ws-add").addEventListener("click", () => {
    const n = $("ws-nname").value.trim(); if (!n) return toast("Name fehlt.");
    const l = $("ws-nlayer").value, def = { jacke: [5, 15], mitte: [-30, 14], drunter: [-30, 40], hose: [-30, 20], extra: [-30, 4] }[l];
    WS.items.push({ id: "c" + Date.now(), name: n, icon: $("ws-nicon").value, layer: l, min: def[0], max: def[1], rain: false, on: true, custom: true });
    $("ws-nname").value = ""; wsRender(); wsSave(); toast(n + " ist im Schrank.");
  });

  // --- Systemstatus ---
  function sysShow(fresh) {
    if (!A || !A.sysCheck) return;
    if (fresh && window.JCheck) JCheck.play(new Promise((res) => setTimeout(() => { let d = {}; try { d = JSON.parse(A.sysCheck(false) || "{}"); } catch (e) {} res(d.items || []); }, 3500)));
    $("sys-sum").textContent = "prüfe …";
    setTimeout(() => {
      let d = {}; try { d = JSON.parse(A.sysCheck(!!fresh) || "{}"); } catch (e) {}
      const it = d.items || [], bad = it.filter((i) => i.ok === false).length;
      $("sys-sum").textContent = bad ? `${bad} Problem${bad > 1 ? "e" : ""} – siehe rot` : "● Alle Systeme laufen";
      $("sys-sub").textContent = bad ? `${bad} Problem${bad > 1 ? "e" : ""}` : "Alle Systeme laufen";
      $("sys-list").innerHTML = it.map((i) => `<div class="sys-row ${i.ok === true ? "g" : i.ok === false ? "r" : "n"}"><i></i><div style="flex:1"><b>${i.name}</b><small>${i.detail || ""}</small>${i.ok === false && i.fix ? `<em>${i.fix}</em>` : ""}<div class="sys-res" id="syr-${i.id}"></div></div><div class="sbtn sys-tb" data-test="${i.id}">Test</div></div>`).join("");
      $("sys-list").querySelectorAll("[data-test]").forEach((b) => b.addEventListener("click", () => {
        const out = $("syr-" + b.dataset.test); out.textContent = "teste …";
        setTimeout(() => { try { out.textContent = A.sysTest(b.dataset.test) || "–"; } catch (e) { out.textContent = "Test ging nicht."; } }, 30);
      }));
    }, 30);
  }
  document.querySelector('[data-p="sys"]').addEventListener("click", () => sysShow(false));
  $("sys-again").addEventListener("click", () => sysShow(true));
  const closeSettings = () => { $("settings").classList.remove("on"); if (window.show) try { show("fokus"); } catch (e) {} };
  $("tst-skill").addEventListener("click", () => { closeSettings(); setTimeout(() => window.JSkill && JSkill.test(), 400); });
  $("tst-rem").addEventListener("click", () => { if (A.remindTest) A.remindTest(); toast("Erinnerung kommt in 5 Sekunden."); });
  $("tst-fahrt").addEventListener("click", () => { A.testAlltag(); toast("Testnachricht kommt gleich als Benachrichtigung."); });
  $("tst-neu").addEventListener("click", () => { closeSettings(); setTimeout(() => (window.JNEU && JNEU.neu || []).forEach((x) => JSkill.show({ title: x.title, text: x.text, kind: "funktion", test: true })), 400); });
  // --- Gesundheit: Samsung Health (Health Connect) + Schlaf ---
  const nf = (v) => Number(v || 0).toLocaleString("de-DE");
  const hmT = (t) => new Date(t).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  function fitShow() {
    if (!A || !A.healthInfo) return;
    $("fit-state").textContent = "lädt …";
    setTimeout(() => {
      let h = {}; try { h = JSON.parse(A.healthInfo() || "{}"); } catch (e) {}
      $("fit-state").textContent = h.connected ? "● Verbunden mit Health Connect" : h.update ? "Health Connect muss aktualisiert werden – tipp auf Verbinden." :
        h.da === false ? "Health Connect nicht gefunden." : "Noch nicht verbunden.";
      perm("fit-connect", h.connected, "Verbinden");
      perm("fit-touch", h.touch, "Einrichten");
      const d = h.heute;
      $("fit-today").innerHTML = d ? [["🔥", nf(d.kcal), "kcal verbraucht"], ["⚡", nf(d.aktiv), "davon aktiv"], ["👣", nf(d.schritte), "Schritte"],
        d.defizit != null ? [d.defizit > 0 ? "📉" : "📈", nf(Math.abs(d.defizit)), d.defizit > 0 ? "Defizit" : "Überschuss"] : ["🏃", nf(d.sport_min), "Min. Sport"]]
        .map(([i, v, l]) => `<div class="fit-t"><span>${i}</span><b>${v}</b><small>${l}</small></div>`).join("")
        : `<div class="note" style="margin:0">${h.connected ? "Noch keine Daten von heute – Samsung Health teilt sie evtl. noch nicht (siehe oben)." : "Erst verbinden."}</div>`;
      const s = h.schlaf;
      $("fit-sleep").innerHTML = s ? `Letzte Nacht: <b>${Math.floor(s.min / 60)}:${String(s.min % 60).padStart(2, "0")} Std.</b> · ${hmT(s.start)} – ${hmT(s.end)} Uhr` +
        (s.wach ? ` · ${s.wach} Min. wach` : "") + (s.quelle === "touch" ? "" : " · (ab Bildschirm aus)")
        : "Letzte Nacht: noch keine Daten – die Erkennung läuft ab jetzt.";
    }, 30);
  }
  document.querySelector('[data-p="fit"]').addEventListener("click", fitShow);
  $("fit-connect").addEventListener("click", () => A.healthConnect && A.healthConnect());
  $("fit-open").addEventListener("click", () => A.healthOpen && A.healthOpen());
  $("fit-touch").addEventListener("click", () => A.openScreenAccess && A.openScreenAccess());
  $("fit-now").addEventListener("click", () => { toast("Tagesbilanz kommt …"); A.feedNow("bilanz"); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && setPage === "fit") fitShow(); });
  (function () {
    const prev = window.jarvis && window.jarvis.onEvent;
    if (!window.jarvis) return;
    window.jarvis.onEvent = function (type, data) {
      if (type === "health") { toast(data.connected ? (data.all ? "Verbunden mit Samsung Health." : "Verbunden – aber nicht alles erlaubt.") : "Nicht verbunden."); fitShow(); return; }
      return prev && prev.call(window.jarvis, type, data);
    };
  })();
  // --- Fernzugriff über Tailscale ---
  let fern = {};
  function fernShow(refresh) {
    try { fern = JSON.parse(A.fernInfo(!!refresh) || "{}"); } catch (e) { fern = {}; }
    $("fern-state").textContent = !fern.paired ? "Erst mit dem PC koppeln (Allgemein → Kopplungscode)."
      : fern.ip ? `PC erreichbar über Tailscale: ${fern.ip}${fern.cam ? " · Webcam erlaubt" : " · Webcam am PC nicht erlaubt"}`
      : "Der PC hat noch keine Tailscale-Adresse gemeldet. Tailscale am PC installieren und anmelden – der PC meldet sich alle 30 Minuten.";
  }
  const fernUrl = (p) => `http://${fern.ip}:${fern.port || 8765}${p}${p.includes("?") ? "&" : "?"}k=${fern.token}`;
  document.querySelector('[data-p="fern"]').addEventListener("click", () => { fernShow(false); setTimeout(() => fernShow(true), 50); });
  $("fern-hud").addEventListener("click", () => { if (!fern.ip) return toast("PC-Adresse fehlt noch."); location.href = fernUrl("/"); });
  $("fern-cam").addEventListener("click", () => { if (!fern.ip) return toast("PC-Adresse fehlt noch."); location.href = fernUrl("/cam"); });
  let camStream = null, camTimer = null;
  function camStop() {
    if (camTimer) clearInterval(camTimer); camTimer = null;
    if (camStream) camStream.getTracks().forEach((t) => t.stop()); camStream = null;
    $("phcam").classList.remove("on");
  }
  $("fern-phcam").addEventListener("click", async () => {
    if (!fern.ip) return toast("PC-Adresse fehlt noch.");
    $("phcam").classList.add("on"); $("phcam-s").textContent = "Kamera startet …";
    try {
      camStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: 960 }, audio: false });
    } catch (e) { $("phcam-s").textContent = "Kamera nicht erlaubt – erlauben und nochmal tippen."; return; }
    const v = $("phcam-v"); v.srcObject = camStream;
    const c = document.createElement("canvas"); let sent = 0, busy = false;
    camTimer = setInterval(() => {
      if (busy || !v.videoWidth) return; busy = true;
      const w = Math.min(960, v.videoWidth); c.width = w; c.height = Math.round(v.videoHeight * w / v.videoWidth);
      c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
      c.toBlob((b) => {
        fetch(fernUrl("/phonecam"), { method: "POST", body: b, headers: { "Content-Type": "image/jpeg" } })
          .then(() => { sent++; $("phcam-s").textContent = `Läuft – der PC zeigt es im HUD (${sent} Bilder).`; })
          .catch(() => { $("phcam-s").textContent = "PC nicht erreichbar – ist Tailscale am Handy an?"; })
          .finally(() => { busy = false; });
      }, "image/jpeg", 0.6);
    }, 350);
  });
  $("phcam-x").addEventListener("click", camStop);
  document.addEventListener("visibilitychange", () => { if (document.hidden) camStop(); });
  $("set-locall").addEventListener("click", () => { A.askLocationAlways(); toast("Erst „Genau“ erlauben, dann beim zweiten Mal „Immer erlauben“."); });
  $("set-wlanget").addEventListener("click", () => { const w = A.currentWifi(); if (w) { $("set-wlan").value = w; toast("Übernommen: " + w); } else toast("Kein WLAN erkannt – erst Standort erlauben, dann nochmal."); });
  $("set-cancel").addEventListener("click", () => { if (!window.jSettingsBack()) $("settings").classList.remove("on"); });
  $("set-save").addEventListener("click", () => {
    A.setVoiceMode($("set-mode").value);
    A.setTtsVoice($("set-voice").value);
    const k = $("set-key").value.trim();
    if (k) A.setGroqKey(k);
    const o = {
      background: sw("set-bg"),
      wake_words: $("set-wake").value.trim() || "jarvis",
      wake_level: parseInt($("set-level").value, 10),
      wake_cloud: $("set-cloud").value === "1",
      link_code: $("set-link").value.trim(),
      jarvis_volume: parseInt($("set-jvol").value, 10),
      lage_orte: $("set-orte").value.trim(),
      themen_selbst: $("set-tselbst").value.trim(),
      assistant_name: $("set-name").value.trim(), anrede: $("set-anrede").value.trim(),
      city: $("set-city").value.trim(), address: $("set-addr").value.trim(), use_location: sw("set-loc"),
      calendar_id: parseInt($("set-cal").value || "-1", 10),
      gemini_key: $("set-gkey").value.trim(),
      orte: $("set-morte").value.trim(), wege: $("set-mwege").value.trim(), route_an: $("set-routean").value.trim(),
      wichtig: $("set-wichtig").value.trim(), absage: $("set-absage").value.trim(), butler: sw("set-butler"),
      wecker_an: sw("wk-an"), wecker_schule: $("wk-schule").value, wecker_we: $("wk-we").value, wecker_vorher: $("wk-vorher").value.trim(),
      wecker_tage: wkTage(),
      heim_wlan: $("set-wlan").value.trim(), weg_auto: sw("set-wegauto"), losfahren: sw("set-losfahren"),
      ankunft: $("set-ankunft").value.trim(), anzieh: $("set-anzieh").value.trim(),
      brief_morgen: sw("set-bmorgen"), brief_abend: sw("set-babend"), brief_abend_zeit: $("set-babendzeit").value || "20:00",
      bi_wetter: sw("set-biwetter"), bi_anzieh: sw("set-bianzieh"), bi_termine: sw("set-bitermine"), bi_mitnehmen: sw("set-bimit"),
      rueckblick: sw("set-rueck"), rueckblick_zeit: $("set-rueckzeit").value || "20:30",
      schlaf_tipp: sw("set-schlaftipp"), ticket_art: $("set-ticket").value, termin_erinnern: sw("set-termerin"), termin_vorher: +($("set-termvor").value || 15),       bilanz: sw("set-bilanz"), bilanz_zeit: $("set-bilanzzeit").value || "22:00",
      lage_jump: sw("set-ljump"), lage_zoom: sw("set-lzoom"), lage_spin: sw("set-lspin"), lage_orbits: sw("set-lorbit"),
      lage_labels: sw("set-llabels"), strand: sw("set-strand"),
    };
    A.saveSettings(JSON.stringify(o));
    A.festSet(JSON.stringify({ an: sw("fw-an"), tag: $("fw-tag").value, mode: $("fw-mode").value, ziel: $("fw-ziel").value.trim(),
      name: $("fw-name").value.trim(), wer: $("fw-wer").value.trim(), los: $("fw-los").value, zuhause: $("fw-heim").value,
      bahn_hin: $("fw-bhin").value, bahn_zurueck: $("fw-bback").value }));
    applyPrefs(o);
    showPower(o.background);
    $("settings").classList.remove("on");
    toast("Gespeichert.");
  });
  // Gelernte Interessen anzeigen (× = Thema entfernen)
  function showThemen() {
    let t = []; try { t = JSON.parse(A.themen ? A.themen() : "[]"); } catch (e) {}
    const box = $("set-themen");
    const learned = t.filter((x) => !x.selbst);
    box.innerHTML = learned.length ? learned.map((x) => `<span data-n="${String(x.name).replace(/"/g, "&quot;")}">${x.name}<b>×</b></span>`).join("")
      : `<span class="none">Noch nichts gelernt – frag Jarvis einfach Dinge und tipp Meldungen an, dann lernt er dich kennen.</span>`;
    box.querySelectorAll("span[data-n] b").forEach((b) => b.addEventListener("click", () => { A.themaWeg(b.parentNode.dataset.n); b.parentNode.remove(); }));
  }

  // Anzeige-Einstellungen sofort anwenden
  let prefsUi = {};
  function applyPrefs(c) {
    prefsUi = c || {};
    $("strand").style.display = prefsUi.strand === false ? "none" : "";
    if (window.JLage) window.JLage.prefs(prefsUi);
  }
  try { if (A) applyPrefs(JSON.parse(A.getSettings())); } catch (e) {}
  // "Für dich" einmal im Hintergrund holen (für die Info-Seite; 15 Minuten zwischengespeichert)
  setTimeout(() => { try { if (A && A.hasGroqKey()) A.getLage("@fuerdich", false); } catch (e) {} }, 4000);

  // --- Wetter (Open-Meteo, Leonberg) und Uhr ---
  function clock() {
    const d = new Date();
    $("clock").textContent = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    $("date").textContent = d.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" });
  }
  clock(); setInterval(clock, 10000);
  function weather() {
    fetch("https://api.open-meteo.com/v1/forecast?latitude=48.80&longitude=9.01&current=temperature_2m,apparent_temperature" +
          "&daily=precipitation_probability_max&timezone=Europe%2FBerlin&forecast_days=1")
      .then((r) => r.json()).then((j) => {
        $("w-temp").textContent = Math.round(j.current.temperature_2m) + "°";
        $("w-feel").textContent = Math.round(j.current.apparent_temperature) + "°";
        const p = (j.daily.precipitation_probability_max || [null])[0];
        $("w-rain").textContent = p == null ? "–" : p + " %";
      }).catch(() => {});
  }
  weather(); setInterval(weather, 15 * 60 * 1000);

  // --- Animation ---
  let last = performance.now();
  function frame(now) {
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    level += (target - level) * 0.25; target *= 0.92;
    const s = spheres[view];
    if (s) { s.level = level; s.draw(dt); }
    if (brains[view]) brains[view].draw(dt);
    if (view === "info") rings.draw(dt);
    if (view === "lage" && window.JLage) window.JLage.draw(dt);
    if (!dragging) strand.offset += (strandTarget - strand.offset) * Math.min(1, dt * 9);
    strand.level = level; strand.power = powerOn || talking;
    if (view !== "lage" || dragging || Math.abs(strand.offset - strandTarget) > .01) strand.draw(dt);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
