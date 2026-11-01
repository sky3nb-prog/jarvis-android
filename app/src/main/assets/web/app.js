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
  document.querySelectorAll(".sphere-wrap").forEach((w) => w.addEventListener("click", () => {
    if (view !== "fokus") show("fokus");
    toggleTalk();
  }));

  const STATES = { connecting: "verbinde …", listening: "hört zu …", speaking: "spricht …", ended: "bereit", idle: "bereit" };
  function setState(st) {
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
      else if (type === "user") $("last-you").textContent = data.text;
      else if (type === "agent") $("last-jar").textContent = data.text;
      else if (type === "level") { if (data.kind === "out" || !talking) target = data.value; else target = Math.max(target * 0.8, data.value * 0.6); }
      else if (type === "error") { toast(data.text); setState("ended"); }
    },
    back() { if (view !== "fokus") { show("fokus"); return true; } return false; },
  };

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
