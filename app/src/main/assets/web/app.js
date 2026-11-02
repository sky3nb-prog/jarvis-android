// Jarvis Handy-App – Oberfläche (Etappe 1: Kugel, Design, Reden mit Jarvis, Wetter/Uhr)
(function () {
  const $ = (id) => document.getElementById(id);
  const A = window.Android || null;   // Brücke zur App (Kotlin)
  const { Sphere, Rings, Globe } = window.JarvisGfx;

  const spheres = {
    fokus: new Sphere(document.querySelector("#sphere-fokus canvas"), 3),
    info: new Sphere(document.querySelector("#sphere-info canvas"), 5),
    steuern: new Sphere(document.querySelector("#sphere-steuern canvas"), 7),
  };
  const rings = new Rings(document.querySelector("#sphere-info canvas.rings"));
  const globe = new Globe($("globe"));
  let view = "fokus", talking = false, level = 0, target = 0;

  // --- Tabs ---
  function show(v) {
    view = v;
    document.querySelectorAll(".view").forEach((e) => e.classList.toggle("active", e.id === "v-" + v));
    document.querySelectorAll(".tab").forEach((e) => e.classList.toggle("on", e.dataset.v === v));
  }
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => show(t.dataset.v)));

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
    $("fokus-state").textContent = STATES[st] || st;
    $("callbtn").textContent = talking ? "Gespräch beenden" : "Gespräch starten";
    $("callbtn").classList.toggle("live", talking);
    $("fokus-hint").textContent = talking ? "Sprich einfach – du kannst ihn jederzeit unterbrechen"
                                          : "Tipp auf die Kugel, um mit Jarvis zu reden";
    Object.values(spheres).forEach((s) => (s.state = st));
    if (!talking) target = 0;
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
      else if (type === "model" || type === "info") toast(data.text);
    },
    back() {
      if ($("settings").classList.contains("on")) { $("settings").classList.remove("on"); return true; }
      if (view !== "fokus") { show("fokus"); return true; } return false;
    },
  };

  // --- Einstellungen ---
  function askKey() {
    setState("ended");
    const k = window.prompt("Für die kostenlose Stimme und das Aktivierungswort brauche ich Groq.\n\n" +
      "Bitte einmal deinen Groq-Schlüssel eintragen (console.groq.com → API Keys, beginnt mit gsk_):", "");
    if (k && k.trim().length > 20 && A) { A.setGroqKey(k.trim()); A.startTalk(); }
    else if (k !== null) toast("Das sah nicht nach einem Groq-Schlüssel aus.");
  }
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
      $("set-bg").value = c.background ? "1" : "0";
      $("set-wake").value = c.wake_words || "jarvis";
      $("set-level").value = String(c.wake_level);
      $("set-cloud").value = c.wake_cloud ? "1" : "0";
      $("set-status").textContent = (c.model ? "Spracherkennung fürs Aktivierungswort ist geladen." : "Spracherkennung wird noch geladen (45 MB, einmalig) – bis dahin prüft Groq.") +
        (c.overlay ? " Kugel über anderen Apps: erlaubt." : " Kugel über anderen Apps: noch nicht erlaubt.");
    } catch (e) {}
    $("set-key").value = "";
    $("set-version").textContent = "Version " + A.version() + (A.hasGroqKey() ? " · Groq-Schlüssel ist gespeichert" : " · noch kein Groq-Schlüssel");
    $("settings").classList.add("on");
  }
  $("btn-settings").addEventListener("click", openSettings);
  $("set-overlay").addEventListener("click", () => A.askOverlay());
  $("set-battery").addEventListener("click", () => A.askBattery());
  $("set-cancel").addEventListener("click", () => $("settings").classList.remove("on"));
  $("set-save").addEventListener("click", () => {
    A.setVoiceMode($("set-mode").value);
    A.setTtsVoice($("set-voice").value);
    const k = $("set-key").value.trim();
    if (k) A.setGroqKey(k);
    A.saveSettings(JSON.stringify({
      background: $("set-bg").value === "1",
      wake_words: $("set-wake").value.trim() || "jarvis",
      wake_level: parseInt($("set-level").value, 10),
      wake_cloud: $("set-cloud").value === "1",
    }));
    $("settings").classList.remove("on");
    toast("Gespeichert.");
  });

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
    if (view === "info") rings.draw(dt);
    if (view === "lage") globe.draw(dt);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
