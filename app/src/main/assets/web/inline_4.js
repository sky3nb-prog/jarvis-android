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
