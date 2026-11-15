// Modi-Raster (PC-HUD und Handy gleich): Knopf oben öffnet Kacheln – Fokus, Gaming, Chill, Kino, Schule, Gute Nacht, Normal.
// Umschalten läuft über einen normalen Befehl (Jarvis antwortet), der aktuelle Stand kommt live zurück (Ereignis "modi").
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const CMD = { fokus: "fokus modus", gaming: "gaming modus", chill: "chill modus", kino: "kino modus", schule: "schulmodus", nacht: "gute nacht", aus: "modus aus" };
  const DEF = [
    { id: "fokus", n: "Fokus", i: "◎", h: 200, d: "Lernen ohne Ablenkung – 25/5 Minuten" },
    { id: "gaming", n: "Gaming", i: "▶", h: 280, d: "Discord an, Anrufe weg" },
    { id: "chill", n: "Chill", i: "♪", h: 160, d: "Musik an, entspannt" },
    { id: "kino", n: "Kino", i: "◐", h: 320, d: "Alles leise, nichts stört" },
    { id: "schule", n: "Schule", i: "▦", h: 45, d: "Handy leise" },
    { id: "nacht", n: "Gute Nacht", i: "☾", h: 230, d: "Handy still, PC aus" },
    { id: "aus", n: "Normal", i: "○", h: 30, d: "Alles wieder normal" },
  ];
  let st = { mode: "", modi: DEF }, lofi = true, tick = null;
  const send = window.JModiSend || ((text) => window.PC && window.PC.post("cmd", { text }));

  const css = document.createElement("style");
  css.textContent = `
.mdbtn{display:flex;align-items:center;gap:6px;height:30px;padding:0 11px;border-radius:999px;border:1.5px solid #5a3e14;color:#c8965a;cursor:pointer;font:600 11px/1 system-ui,sans-serif;letter-spacing:.12em;white-space:nowrap}
.mdbtn b{font-size:14px;letter-spacing:0}
.mdbtn.on{border-color:hsl(var(--h),80%,60%);color:hsl(var(--h),90%,80%);box-shadow:0 0 12px hsla(var(--h),90%,60%,.45);background:hsla(var(--h),60%,20%,.4)}
.md-ov{position:fixed;inset:0;z-index:70;background:rgba(3,6,8,.72);backdrop-filter:blur(4px);display:none;align-items:center;justify-content:center;padding:16px}
.md-ov.on{display:flex}
.md-win{width:min(640px,100%);background:linear-gradient(180deg,#1a1308,#0b0805);border:1px solid rgba(255,190,90,.4);border-radius:20px;padding:18px 18px 16px;box-shadow:0 10px 60px rgba(255,160,30,.18)}
.md-hd{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.md-hd b{font:700 13px/1 system-ui,sans-serif;letter-spacing:.2em;color:#ffaa28}
.md-x{width:30px;height:30px;border-radius:50%;border:1px solid #5a3e14;color:#c8965a;display:flex;align-items:center;justify-content:center;cursor:pointer}
.md-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
.md-t{all:unset;box-sizing:border-box;cursor:pointer;position:relative;min-height:104px;padding:12px;border-radius:14px;display:flex;flex-direction:column;gap:4px;
 border:1px solid hsla(var(--h),70%,60%,.35);background:linear-gradient(160deg,hsla(var(--h),60%,26%,.38),rgba(0,0,0,.35));transition:transform .15s,box-shadow .15s}
.md-t:hover{transform:translateY(-2px);box-shadow:0 6px 20px hsla(var(--h),90%,55%,.22)}
.md-t:focus-visible{outline:2px solid #ffd678}
.md-t i{font-style:normal;font-size:24px;color:hsl(var(--h),90%,78%);line-height:1}
.md-t b{font:700 16px/1.1 system-ui,sans-serif;color:hsl(var(--h),90%,85%)}
.md-t small{font-size:12px;color:hsl(var(--h),30%,75%);line-height:1.3}
.md-t.on{border-color:hsl(var(--h),85%,65%);box-shadow:0 0 0 2px hsla(var(--h),90%,65%,.7),0 0 22px hsla(var(--h),90%,60%,.4)}
.md-t.on::after{content:"AN";position:absolute;top:10px;right:10px;font:700 10px/1 system-ui;letter-spacing:.14em;color:#0b0805;background:hsl(var(--h),90%,70%);padding:3px 6px;border-radius:999px}
.md-t .md-cd{font:600 13px/1 ui-monospace,Consolas,monospace;color:#fff1c8;margin-top:auto;font-variant-numeric:tabular-nums}
.md-opt{display:flex;align-items:center;gap:8px;margin-top:12px;font-size:13px;color:#d9c3a0;cursor:pointer;user-select:none}
.md-opt span{width:34px;height:18px;border-radius:999px;background:#2a2014;border:1px solid #5a3e14;position:relative}
.md-opt span::after{content:"";position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:#8a6a3a;transition:left .15s}
.md-opt.on span{background:#3a2608;border-color:#ffaa28}.md-opt.on span::after{left:18px;background:#ffd678}
.md-note{font-size:12px;color:#8a7a62;margin-top:8px}`;
  document.head.appendChild(css);

  const ov = document.createElement("div");
  ov.className = "md-ov"; ov.id = "md-ov";
  ov.innerHTML = `<div class="md-win" role="dialog" aria-label="Modi"><div class="md-hd"><b>MODI</b><div class="md-x" id="md-x">✕</div></div><div class="md-grid" id="md-grid"></div>
    <div class="md-opt on" id="md-lofi"><span></span>Fokus mit Lofi-Musik</div><div class="md-note">Im Fokus sammle ich Nachrichten und sage sie dir in der Pause. „Wie lange noch?“ geht jederzeit.</div></div>`;
  document.body.appendChild(ov);
  ov.addEventListener("click", (e) => { if (e.target === ov) close(); });
  $("md-x").addEventListener("click", close);
  $("md-lofi").addEventListener("click", () => { lofi = !lofi; $("md-lofi").classList.toggle("on", lofi); try { localStorage.setItem("md_lofi", lofi ? "1" : "0"); } catch (e) {} });
  try { lofi = localStorage.getItem("md_lofi") !== "0"; $("md-lofi").classList.toggle("on", lofi); } catch (e) {}
  addEventListener("keydown", (e) => { if (e.key === "Escape" && ov.classList.contains("on")) close(); });

  function cd() {
    if (st.mode !== "fokus" || !st.phase_end) return "";
    const s = Math.max(0, Math.round(st.phase_end - Date.now() / 1000));
    return (st.phase === "pause" ? "Pause " : "Fokus ") + String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0") + (st.runden ? ` · ${st.runden}×` : "");
  }
  function draw() {
    const list = (st.modi && st.modi.length ? st.modi : DEF);
    $("md-grid").innerHTML = list.map((m) => `<button class="md-t${(st.mode || "aus") === m.id ? " on" : ""}" style="--h:${m.h}" data-m="${m.id}"><i>${m.i}</i><b>${esc(m.n)}</b><small>${esc(m.d)}</small>${m.id === "fokus" && st.mode === "fokus" ? `<span class="md-cd" id="md-cd">${cd()}</span>` : ""}</button>`).join("");
    $("md-grid").querySelectorAll(".md-t").forEach((b) => b.addEventListener("click", () => pick(b.dataset.m)));
    const btn = $("mdbtn");
    if (btn) {
      const m = list.find((x) => x.id === st.mode);
      btn.classList.toggle("on", !!m); btn.style.setProperty("--h", m ? m.h : 40);
      btn.innerHTML = m ? `<b>${m.i}</b>${esc(m.n.toUpperCase())}${st.mode === "fokus" ? " " + cd().replace(/^(Fokus|Pause) /, "") .split(" ·")[0] : ""}` : "<b>◈</b>MODI";
    }
    document.querySelectorAll(".mdround, .mdround2").forEach((r) => {   // Knöpfe in der Handy-App
      const m = list.find((x) => x.id === st.mode);
      r.classList.toggle("on", !!m); r.style.setProperty("--h", m ? m.h : 40); r.textContent = m ? m.i : "◈";
    });
    clearInterval(tick);
    if (st.mode === "fokus") tick = setInterval(() => { const e = $("md-cd"); if (e) e.textContent = cd(); const b = $("mdbtn"); if (b && st.mode === "fokus") b.innerHTML = `<b>◎</b>FOKUS ${cd().replace(/^(Fokus|Pause) /, "").split(" ·")[0]}`; }, 1000);
  }
  function pick(id) {
    let t = CMD[id] || "modus aus";
    if (id === "fokus" && !lofi) t = "fokus modus ohne musik";
    if (id === (st.mode || "aus") && id !== "aus") t = "modus aus";   // nochmal tippen = aus
    send(t);
    st = Object.assign({}, st, { mode: t === "modus aus" ? "" : id, phase: id === "fokus" ? "lernen" : "", phase_end: id === "fokus" ? Date.now() / 1000 + 1500 : 0 });
    draw(); setTimeout(close, 450);
  }
  function open() { draw(); ov.classList.add("on"); }
  function close() { ov.classList.remove("on"); }
  function update(d) { if (d) { st = Object.assign({}, st, d); draw(); } }
  window.JModi = { open, close, update };
  // Knopf in die obere Leiste (PC) – am Handy setzt die App ihren eigenen Knopf
  const host = document.querySelector(".top #feedbtn-f");
  if (host) {
    const b = document.createElement("div"); b.className = "mdbtn"; b.id = "mdbtn"; b.title = "Modi: Fokus, Gaming, Chill …";
    host.parentNode.insertBefore(b, host); b.addEventListener("click", open);
  }
  try { const d = window.PC && window.PC.get && window.PC.get("modi"); if (d) st = Object.assign(st, d); } catch (e) {}
  draw();
})();
