// Systemstatus: "Friday, Statuscheck" oder Klick auf SYSTEME oben – Liste mit grünen/roten Punkten und was zu tun ist.
(function () {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const box = document.createElement("div"); box.id = "syspanel";
  box.innerHTML = '<div class="sp-card"><div class="sp-head"><b>SYSTEMSTATUS</b><span id="sp-sum">…</span><div class="sp-x" id="sp-x">✕</div></div><div id="sp-list"></div><div class="sp-foot"><span id="sp-t"></span><div class="sp-btn" id="sp-again">Neu prüfen</div></div>' +
    '<div class="sp-test"><b>TESTEN – so sieht es aus</b><div><span class="sp-btn" data-t="skill">Skill freischalten</span><span class="sp-btn" data-t="boot">Startanimation</span><span class="sp-btn" data-t="overlay">Overlay</span><span class="sp-btn" data-t="update">Update-Frage</span></div></div></div>';
  document.body.appendChild(box);
  const dot = document.getElementById("sysdot");
  function render(d) {
    const items = d.items || [];
    const bad = items.filter((i) => i.ok === false).length;
    if (dot) { dot.classList.toggle("bad", bad > 0); dot.classList.toggle("ok", bad === 0 && items.length > 0); dot.title = d.text || ""; }
    document.getElementById("sp-sum").textContent = bad ? `${bad} Problem${bad > 1 ? "e" : ""}` : "Alle Systeme laufen";
    document.getElementById("sp-list").innerHTML = items.map((i) => `<div class="sp-row ${i.ok === true ? "g" : i.ok === false ? "r" : "n"}"><i></i>
      <div><b>${esc(i.name)}</b><small>${esc(i.detail)}</small>${i.ok === false && i.fix ? `<em>${esc(i.fix)}</em>` : ""}</div></div>`).join("");
    document.getElementById("sp-t").textContent = d.t ? "Geprüft " + new Date(d.t * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) : "";
  }
  async function load(fresh) {
    document.getElementById("sp-sum").textContent = "prüfe …";
    try { render(await (await fetch("/api/syscheck" + (fresh ? "?neu=1" : ""))).json()); } catch (e) {}
  }
  function open(fresh) { box.classList.add("on"); load(fresh); }
  if (dot) dot.addEventListener("click", () => open(false));
  document.getElementById("sp-x").addEventListener("click", () => box.classList.remove("on"));
  document.getElementById("sp-again").addEventListener("click", () => load(true));
  box.querySelectorAll("[data-t]").forEach((b) => b.addEventListener("click", () => {
    const t = b.dataset.t;
    if (t === "skill") { box.classList.remove("on"); setTimeout(() => window.JSkill && JSkill.test(), 300); return; }
    if (t === "overlay") box.classList.remove("on");
    fetch("/api/test", { method: "POST", body: JSON.stringify({ what: t }) }).catch(() => {});
  }));
  box.addEventListener("click", (e) => { if (e.target === box) box.classList.remove("on"); });
  // Ergebnis vom Sprachbefehl: Seite aufmachen
  const es = new EventSource("/events");
  es.onmessage = (e) => { try { const m = JSON.parse(e.data); if (m.type === "syscheck") { box.classList.add("on"); render(m.data || {}); } } catch (x) {} };
  setTimeout(() => load(false), 4000);   // Punkt oben gleich richtig färben
  window.JSys = { open, render };
})();
