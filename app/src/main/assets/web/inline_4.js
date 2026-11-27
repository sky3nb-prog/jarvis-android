document.addEventListener("DOMContentLoaded", () => { const b = document.getElementById("ws-heute"); if (b) b.addEventListener("click", () => { if (window.JOutfit) window.JOutfit.open(); }); const f = document.getElementById("set-farbe"); if (f) f.addEventListener("click", () => window.JFarbe && window.JFarbe.open()); });

// Akzentfarbe (Anzeige): Punkt antippen -> Kugel, Zustand und Pegel stellen sich sofort um, Auswahl bleibt gespeichert.
document.addEventListener("DOMContentLoaded", () => {
  const box = document.getElementById("set-akzent");
  if (!box || !window.VectorAccent) return;
  const mark = () => {
    const cur = window.VectorAccent.get().toLowerCase();
    [...box.children].forEach((s) => {
      const on = (s.dataset.a || "").toLowerCase() === cur;
      s.classList.toggle("on", on); s.style.color = s.dataset.a;
    });
  };
  box.addEventListener("click", (e) => {
    const s = e.target.closest("span[data-a]"); if (!s) return;
    window.VectorAccent.set(s.dataset.a); mark();
    try { if (window.Android && window.Android.saveSettings) { /* Konto-Abgleich läuft über die Einstellungen */ } } catch (x) {}
  });
  mark();
});

// System-Knopf auf der Kugel-Seite: öffnet direkt Systemstatus, Tests und Updates (wie SYSTEME am PC).
// Ist etwas nicht in Ordnung, färbt sich der Punkt orange.
document.addEventListener("DOMContentLoaded", () => {
  const b = document.getElementById("sysbtn-f");
  if (!b) return;
  b.addEventListener("click", () => {
    const item = document.querySelector('.sitem[data-go="sys"]');
    const open = document.getElementById("btn-settings");
    if (open) open.click();
    setTimeout(() => { if (item) item.click(); }, 60);
  });
  const pruefen = () => {
    try {
      const r = JSON.parse(window.Android.sysCheck(false)) || {};
      const schlecht = (r.items || []).filter((i) => i.ok === false).length;
      b.classList.toggle("warn", schlecht > 0);
      b.title = schlecht ? schlecht + " Punkt(e) brauchen Aufmerksamkeit" : "Systemstatus, Tests und Updates";
    } catch (e) {}
  };
  setTimeout(pruefen, 2500);
  setInterval(pruefen, 10 * 60 * 1000);
});
