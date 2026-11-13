// Seite "Steuern" am PC: dein Handy fernsteuern (Gegenstück zur Steuern-Seite der Handy-App).
// Alles geht über die Kopplung; das Handy meldet seinen Stand nur auf Nachfrage (ntfy.sh erlaubt ~250 Nachrichten am Tag).
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  let st = null, age = null, paired = true, drag = false;

  function toast(t, ok) { const e = $("toast"); if (!e) return; e.textContent = t; e.classList.toggle("ok", ok !== false); e.style.display = "block"; clearTimeout(toast.j); toast.j = setTimeout(() => (e.style.display = "none"), 3500); }
  const send = (b, label) => { toast((label || "Befehl") + " … wird ans Handy geschickt"); window.PC.post("phone", b); };

  function show() {
    const s = st || {};
    const fresh = s.ts && Date.now() / 1000 - s.ts < 40 * 60;
    $("ph-bar").classList.toggle("off", !fresh);
    $("ph-head").textContent = !paired ? "DEIN HANDY · NICHT GEKOPPELT" : fresh ? "DEIN HANDY · VERBUNDEN" : "DEIN HANDY · KEIN STAND";
    const mins = s.ts ? Math.round((Date.now() / 1000 - s.ts) / 60) : null;
    $("ph-sub").textContent = !paired ? "Kopplungscode in der App eintragen" : !s.ts ? "Jarvis-App mit Schalter oben rechts an?" :
      `${esc(s.model || "Handy")} · ${mins < 1 ? "gerade eben" : "vor " + mins + " Min."} gemeldet`;
    $("ph-r").innerHTML = s.akku != null ? `Akku ${s.akku} %${s.laedt ? " ⚡" : ""}<span class="bat"><i style="width:${Math.max(4, s.akku * .9)}%"></i></span><br>${{ an: "Klingelton an", vibration: "Vibration", lautlos: "Lautlos" }[s.ringer] || ""}` : "";
    const p = s.playing;
    $("ph-title").textContent = p ? p.title : "–";
    $("ph-artist").textContent = p ? [p.artist, p.app].filter(Boolean).join(" · ") : (fresh ? "nichts läuft" : "–");
    $("ph-lampe").classList.toggle("on", !!s.lampe);
    $("ph-laut").classList.toggle("on", s.ringer && s.ringer !== "an");
    vol(s.vol);
    const t = s.termine || [];
    $("ph-ter").innerHTML = t.length ? t.map((e) => `<div>${esc(e.when)} · <b>${esc(e.title)}</b></div>`).join("") : (fresh ? "Keine Termine in den nächsten Tagen." : "–");
  }

  // Lautstärke am Handy (geschickt wird erst beim Loslassen)
  function vol(v) {
    if (drag) return;
    v = v || {};
    const rows = [["medien", "♪", "Medien"], ["klingel", "☎", "Klingelton"], ["wecker", "◷", "Wecker"]];
    $("ph-vol").innerHTML = rows.map(([k, ic, n]) => `<div class="ch" data-k="${k}"><span class="ic">${ic}</span><span class="nm">${n}</span>
      <input class="jr" type="range" min="0" max="100" value="${v[k] != null ? v[k] : 50}"${v[k] == null ? " disabled" : ""}><span class="pc">${v[k] != null ? v[k] : "–"}</span></div>`).join("");
    $("ph-vol").querySelectorAll(".ch").forEach((row) => {
      const inp = row.querySelector("input"), pc = row.querySelector(".pc");
      const paint = () => inp.style.setProperty("--p", inp.value + "%"); paint();
      inp.addEventListener("pointerdown", () => (drag = true));
      inp.addEventListener("input", () => { paint(); pc.textContent = inp.value; });
      inp.addEventListener("change", () => { drag = false; send({ op: "ctl", what: "vol", stream: row.dataset.k, level: inp.value / 100 }, row.querySelector(".nm").textContent + " auf " + inp.value + " %"); });
    });
  }

  // Kacheln mit Rückfrage (Anrufen, Wecker, Termin, WhatsApp, Route)
  const ASK = {
    call: { t: "Wen soll dein Handy anrufen?", f: ["Name aus den Kontakten"], go: (v) => ({ op: "call", who: v[0] }), l: "Anruf" },
    wecker: { t: "Wecker am Handy stellen", f: ["Uhrzeit, z. B. 7:00"], go: (v) => ({ op: "do", text: "stell einen Wecker auf " + v[0] }), l: "Wecker" },
    termin: { t: "Termin im Handy-Kalender", f: ["z. B. morgen 15 Uhr Zahnarzt"], go: (v) => ({ op: "do", text: "trag " + v[0] + " in den Kalender ein" }), l: "Termin" },
    whatsapp: { t: "WhatsApp vom Handy", f: ["An wen?", "Nachricht"], go: (v) => ({ op: "do", text: `schreib ${v[0]} per WhatsApp: ${v[1]}` }), l: "WhatsApp" },
    route: { t: "Route aufs Handy", f: ["Wohin?"], go: (v) => ({ op: "do", text: "starte die Navigation nach " + v[0] }), l: "Route" },
  };
  let cur = null;
  function ask(k) {
    cur = ASK[k]; $("ph-ask-t").textContent = cur.t;
    $("ph-ask-f").innerHTML = cur.f.map((p) => `<input placeholder="${esc(p)}">`).join("");
    $("ph-ask").classList.add("on");
    setTimeout(() => { const i = $("ph-ask-f").querySelector("input"); if (i) i.focus(); }, 50);
  }
  function askOk() {
    const v = [...$("ph-ask-f").querySelectorAll("input")].map((i) => i.value.trim());
    if (v.some((x) => !x)) return;
    $("ph-ask").classList.remove("on"); send(cur.go(v), cur.l);
  }
  $("ph-ask-ok").addEventListener("click", askOk);
  $("ph-ask-no").addEventListener("click", () => $("ph-ask").classList.remove("on"));
  $("ph-ask-f").addEventListener("keydown", (e) => { if (e.key === "Enter") askOk(); if (e.key === "Escape") $("ph-ask").classList.remove("on"); });

  document.querySelectorAll("#pv-steuern [data-ask]").forEach((e) => e.addEventListener("click", () => ask(e.dataset.ask)));
  document.querySelectorAll("#pv-steuern [data-ctl]").forEach((e) => e.addEventListener("click", () => {
    let c; try { c = JSON.parse(e.dataset.ctl); } catch (x) { return; }
    send(Object.assign({ op: "ctl" }, c), (e.textContent || "").trim().split("\n")[0].slice(0, 20) || "Befehl");
  }));
  document.querySelectorAll("#pv-steuern [data-op]").forEach((e) => e.addEventListener("click", () => send({ op: e.dataset.op }, "Lied rüber")));
  const cmd = () => { const t = $("ph-cmd").value.trim(); if (!t) return; $("ph-cmd").value = ""; send({ op: "do", text: t }, "Befehl"); };
  $("ph-send").addEventListener("click", cmd);
  $("ph-re").addEventListener("click", () => { $("ph-re").classList.add("spin"); setTimeout(() => $("ph-re").classList.remove("spin"), 15000); window.PC.post("phone", { op: "refresh", force: true }); });
  $("ph-cmd").addEventListener("keydown", (e) => { if (e.key === "Enter") cmd(); });

  window.JHandy = {
    shown() {   // Seite geöffnet: letzten Stand zeigen und (höchstens alle 2 Minuten) neu fragen
      try { const r = window.PC.get("phone") || {}; paired = r.paired !== false; if (r.status) st = r.status; } catch (e) {}
      show();
      if (paired) window.PC.post("phone", { op: "refresh" });
    },
    onStatus(d) { if (d && d.status) { st = d.status; $("ph-re").classList.remove("spin"); show(); } },
    onReply(r) { r = r || {}; $("ph-re").classList.remove("spin"); toast((r.ok === false ? "✕ " : "✓ Handy: ") + (r.text || (r.ok === false ? "Ging nicht." : "erledigt")), r.ok !== false); },
  };
  show();
})();
