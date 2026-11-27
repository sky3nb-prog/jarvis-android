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

// Infos beim Start: welche Kacheln beim Hochfahren einfliegen (gleiche Liste wie am PC).
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("set-bootinfo");
  if (!btn) return;
  const KEY = "vector_boot_infos";
  const BEKANNT = [["uhrzeit", "Uhrzeit"], ["datum", "Datum"], ["wochentag", "Wochentag"],
                   ["skills", "Gelernte Skills"], ["status", "Status"], ["kalenderwoche", "Kalenderwoche"]];
  btn.addEventListener("click", () => {
    if (document.getElementById("jbinf")) return;
    let wahl = [];
    try { wahl = JSON.parse(localStorage.getItem(KEY) || "null") || []; } catch (e) {}
    if (!wahl.length) wahl = ["uhrzeit", "datum", "skills", "status"];
    const eig = wahl.find((w) => w && typeof w === "object") || { l: "", v: "" };
    const ov = document.createElement("div");
    ov.id = "jbinf";
    ov.innerHTML =
      '<style>#jbinf{position:fixed;inset:0;z-index:99990;background:rgba(0,0,0,.76);display:flex;align-items:flex-end;font-family:inherit}' +
      '#jbinf .box{width:100%;padding:20px 18px calc(18px + env(safe-area-inset-bottom));border-radius:22px 22px 0 0;background:#0b1413;border-top:1px solid rgba(255,255,255,.12);color:#e8e4da}' +
      '#jbinf h3{margin:0 0 5px;font-size:13px;letter-spacing:2.4px;font-weight:600}' +
      '#jbinf p{margin:0 0 13px;font-size:12px;color:#8fb9ac;line-height:1.5}' +
      '#jbinf .t{display:flex;flex-wrap:wrap;gap:7px}' +
      '#jbinf .t button{padding:9px 13px;border-radius:11px;border:1px solid rgba(255,255,255,.14);background:#111b19;color:#9dc9bb;font:inherit;font-size:12.5px}' +
      '#jbinf .t button.on{border-color:#C45CFF;color:#D98BFF;background:rgba(196,92,255,.12)}' +
      '#jbinf label{display:block;margin:15px 0 6px;font-size:11px;letter-spacing:1.4px;color:#8fb9ac}' +
      '#jbinf .e{display:flex;gap:7px}' +
      '#jbinf input{flex:1;padding:10px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.14);background:#0d1716;color:#e8e4da;font:inherit;font-size:13px}' +
      '#jbinf input.k{flex:0 0 110px}' +
      '#jbinf .row{display:flex;gap:10px;margin-top:17px}' +
      '#jbinf .row button{flex:1;padding:13px;border-radius:13px;border:1px solid rgba(255,255,255,.18);background:#141a20;color:#e8e4da;font:inherit;font-size:14px}' +
      '#jbinf .row button.ok{background:#9fe1cb;color:#04231c;font-weight:600}</style>' +
      '<div class="box"><h3>INFOS BEIM START</h3>' +
      '<p>Was beim Hochfahren einfliegt. Am Handy werden die ersten zwei gezeigt.</p><div class="t">' +
      BEKANNT.map((b) => '<button data-k="' + b[0] + '"' + (wahl.indexOf(b[0]) >= 0 ? ' class="on"' : "") +
        ">" + b[1] + "</button>").join("") + "</div>" +
      '<label>EIGENE ZEILE</label><div class="e">' +
      '<input class="k" id="jbi-l" placeholder="SPRUCH" value="' + (eig.l || "") + '">' +
      '<input id="jbi-v" placeholder="Auf geht’s" value="' + (eig.v || "") + '"></div>' +
      '<div class="row"><button id="jbi-no">Abbrechen</button><button class="ok" id="jbi-ok">Fertig</button></div></div>';
    document.body.appendChild(ov);
    ov.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-k]");
      if (b) { b.classList.toggle("on"); return; }
      if (e.target.id === "jbi-no" || e.target === ov) { ov.remove(); return; }
      if (e.target.id !== "jbi-ok") return;
      const neu = [];
      ov.querySelectorAll("button[data-k].on").forEach((x) => neu.push(x.dataset.k));
      const l = ov.querySelector("#jbi-l").value.trim(), v = ov.querySelector("#jbi-v").value.trim();
      if (l) neu.push({ l, v });
      try { localStorage.setItem(KEY, JSON.stringify(neu)); } catch (x) {}
      ov.remove();
      if (window.toast) window.toast("Gespeichert – beim nächsten Start siehst du es.");
    });
  });
});
