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
      if (e.touches.length !== 1 || $("settings").classList.contains("on") || e.target.closest("nav")) { mode = 2; return; }
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
      else if (type === "think") { const k = data.kinds || []; Object.values(brains).forEach((b) => b.think(k, data.ms || 4000)); }
      else if (type === "tle") { if (window.JLage) window.JLage.tle(data.text); }
      else if (type === "home") { if (window.JLage) window.JLage.home(); }
    },
    back() {
      if ($("settings").classList.contains("on")) { $("settings").classList.remove("on"); return true; }
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
  document.querySelectorAll("#stabs span").forEach((t) => t.addEventListener("click", () => {
    document.querySelectorAll("#stabs span").forEach((x) => x.classList.toggle("on", x === t));
    document.querySelectorAll(".spane").forEach((p) => p.classList.toggle("on", p.id === "sp-" + t.dataset.p));
  }));
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
      sw("set-loc", c.use_location);
      $("set-locstate").innerHTML = c.here ? "Gerade: <b style='color:#6effcd'>" + c.here + "</b>" : (c.use_location ? "Standort wird beim nächsten Mal ermittelt." : "");
      sw("set-ljump", c.lage_jump !== false); sw("set-lzoom", c.lage_zoom !== false); sw("set-lspin", c.lage_spin !== false);
      sw("set-lorbit", c.lage_orbits !== false); sw("set-llabels", c.lage_labels !== false); sw("set-strand", c.strand !== false);
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
    $("settings").classList.add("on");
  }
  $("btn-settings").addEventListener("click", openSettings);
  $("set-overlay").addEventListener("click", () => A.askOverlay());
  $("set-overlay2").addEventListener("click", () => A.askOverlay());
  $("set-battery").addEventListener("click", () => A.askBattery());
  $("set-media").addEventListener("click", () => { A.askMedia(); toast("Bei „Jarvis“ den Benachrichtigungszugriff einschalten."); });
  $("set-usage").addEventListener("click", () => { A.askUsage(); toast("Bei „Jarvis“ den Nutzungszugriff einschalten."); });
  $("set-cancel").addEventListener("click", () => $("settings").classList.remove("on"));
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
      lage_jump: sw("set-ljump"), lage_zoom: sw("set-lzoom"), lage_spin: sw("set-lspin"), lage_orbits: sw("set-lorbit"),
      lage_labels: sw("set-llabels"), strand: sw("set-strand"),
    };
    A.saveSettings(JSON.stringify(o));
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
