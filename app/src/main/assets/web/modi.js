// Modi-Raster (PC-HUD und Handy gleich): Knopf oben öffnet Kacheln – Fokus, Gaming, Chill, Kino, Schule, Gute Nacht, Normal.
// Umschalten läuft über einen normalen Befehl (Jarvis antwortet), der aktuelle Stand kommt live zurück (Ereignis "modi").
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const CMD = { fokus: "fokus modus", gaming: "gaming modus", chill: "chill modus", kino: "kino modus", schule: "schulmodus", nacht: "gute nacht", aus: "modus aus" };
  const B = { handy: "normal", sammeln: false, still: false, musik: "", discord: "", apps: "", pomo: false, lern: 25, pause: 5, aus: false };
  const DEF = [
    Object.assign({}, B, { id: "fokus", n: "Fokus", i: "◎", h: 200, d: "Lernen ohne Ablenkung", handy: "dnd", sammeln: true, still: true, musik: "lofi", pomo: true }),
    Object.assign({}, B, { id: "gaming", n: "Gaming", i: "▶", h: 280, d: "Discord an, Anrufe weg", handy: "dnd", discord: "Gurken" }),
    Object.assign({}, B, { id: "chill", n: "Chill", i: "♪", h: 160, d: "Musik an, entspannt", musik: "deezer" }),
    Object.assign({}, B, { id: "kino", n: "Kino", i: "◐", h: 320, d: "Alles leise, nichts stört", handy: "lautlos", sammeln: true, still: true }),
    Object.assign({}, B, { id: "schule", n: "Schule", i: "▦", h: 45, d: "Alles stumm, nur Uhr", handy: "stumm", still: true }),
    Object.assign({}, B, { id: "nacht", n: "Gute Nacht", i: "☾", h: 230, d: "Handy still, PC aus", handy: "dnd", sammeln: true, still: true, aus: true }),
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
.md-ov [hidden]{display:none!important}
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
.md-note{font-size:12px;color:#8a7a62;margin-top:8px}
.md-ed{height:30px;padding:0 12px;border-radius:999px;border:1px solid #5a3e14;color:#ffd678;display:flex;align-items:center;cursor:pointer;font-size:12px;letter-spacing:.08em}
.md-ed.on{background:#ffaa28;color:#1a1006;border-color:#ffaa28}
.md-win{max-height:calc(100vh - 32px);overflow-y:auto}
.me-m{border:1px solid hsla(var(--h),70%,60%,.35);border-radius:14px;margin:8px 0;background:linear-gradient(160deg,hsla(var(--h),60%,22%,.3),rgba(0,0,0,.3))}
.me-m summary{cursor:pointer;padding:10px 12px;font-weight:700;color:hsl(var(--h),90%,85%);list-style:none;display:flex;gap:8px;align-items:center}
.me-m summary small{font-weight:400;color:#b9a78a;font-size:12px}
.me-b{padding:0 12px 12px;display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px 12px}
.me-f{display:flex;flex-direction:column;gap:4px;font-size:12px;color:#c8965a;min-width:0}
.me-f input,.me-f select{padding:8px 9px;border-radius:9px;border:1px solid #4a3410;background:rgba(0,0,0,.4);color:#ffe1b4;font-size:14px;min-width:0;color-scheme:dark}
.me-t{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:13px;color:#e8d6b8;cursor:pointer;padding:6px 0}
.me-t i{width:34px;height:18px;border-radius:999px;background:#2a2014;border:1px solid #5a3e14;position:relative;flex:0 0 34px}
.me-t i::after{content:"";position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:#8a6a3a;transition:left .15s}
.me-t.on i{background:#3a2608;border-color:#ffaa28}.me-t.on i::after{left:18px;background:#ffd678}
.me-row{grid-column:1/-1;display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}
.me-btn{all:unset;cursor:pointer;padding:8px 13px;border-radius:999px;border:1px solid #5a3e14;color:#d9c3a0;font-size:13px}
.me-btn.ok{background:#ffaa28;color:#1a1006;border-color:#ffaa28;font-weight:700}
.me-btn.del{color:#ff8a6a;margin-right:auto}`;
  document.head.appendChild(css);

  const ov = document.createElement("div");
  ov.className = "md-ov"; ov.id = "md-ov";
  ov.innerHTML = `<div class="md-win" role="dialog" aria-label="Modi"><div class="md-hd"><b id="md-ttl">MODI</b><div style="display:flex;gap:8px"><div class="md-ed" id="md-edbtn">Bearbeiten</div><div class="md-x" id="md-x">✕</div></div></div><div class="md-grid" id="md-grid"></div><div id="md-edit" hidden></div>
    <div class="md-opt on" id="md-lofi" hidden><span></span>Fokus mit Lofi-Musik</div><div class="md-note">Tipp auf einen Modus zum Einschalten, nochmal tippen = aus. Unter „Bearbeiten“ stellst du ein, was jeder Modus macht – oder legst eigene an.</div></div>`;
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
    const list = (st.modi && st.modi.length ? st.modi : DEF).filter((m) => !m.weg);
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
    if (!CMD[id]) { const m = (st.modi || []).find((x) => x.id === id); t = (m ? m.n : id) + " modus"; }
    if (id === (st.mode || "aus") && id !== "aus") t = "modus aus";   // nochmal tippen = aus
    send(t);
    st = Object.assign({}, st, { mode: t === "modus aus" ? "" : id, phase: id === "fokus" ? "lernen" : "", phase_end: id === "fokus" ? Date.now() / 1000 + 1500 : 0 });
    draw(); setTimeout(close, 450);
  }
  // --- Bearbeiten: was jeder Modus macht -------------------------------------------------------------------
  let editing = false, cfg = null;
  const saveCfg = window.JModiSaveCfg || ((c) => window.PC && window.PC.post("modi_cfg", { cfg: c }));
  const HANDY = [["stumm", "Alles stumm (nur Uhr)"], ["dnd", "Nicht stören"], ["lautlos", "Lautlos"], ["normal", "Normal"], ["", "Nichts ändern"]];
  const MUSIK = [["", "Keine"], ["lofi", "Lofi (YouTube)"], ["deezer", "Deezer"], ["spotify", "Spotify"], ["youtube", "Eigene YouTube-Suche"]];
  function editDraw() {
    const list = (cfg || (st.alle || st.modi || DEF).filter((m) => m.id !== "aus")).map((m) => Object.assign({ handy: "normal", sammeln: false, still: false, musik: "", discord: "", apps: "", pomo: false, lern: 25, pause: 5, aus: false }, m));
    cfg = list;
    const tg = (k, on, label) => `<div class="me-t${on ? " on" : ""}" data-k="${k}">${label}<i></i></div>`;
    const opt = (arr, v) => arr.map(([a, b]) => `<option value="${a}"${a === v ? " selected" : ""}>${b}</option>`).join("");
    $("md-edit").innerHTML = list.map((m, i) => { const mu = (m.musik || "").startsWith("youtube:") ? "youtube" : (m.musik || "");
      return `<details class="me-m" style="--h:${m.h || 40}" data-i="${i}"${m.weg ? ' style="opacity:.5"' : ""}><summary>${esc(m.i || "◆")} ${esc(m.n)} <small>${esc(m.weg ? "ausgeblendet" : m.d || "")}</small></summary><div class="me-b">
        <label class="me-f">Name<input data-k="n" value="${esc(m.n)}" maxlength="20"></label>
        <label class="me-f">Symbol<input data-k="i" value="${esc(m.i || "")}" maxlength="2"></label>
        <label class="me-f">Beschreibung<input data-k="d" value="${esc(m.d || "")}" maxlength="40"></label>
        <label class="me-f">Handy<select data-k="handy">${opt(HANDY, m.handy || "")}</select></label>
        <label class="me-f">Musik (am PC)<select data-k="musik">${opt(MUSIK, mu)}</select></label>
        <label class="me-f"${mu === "youtube" ? "" : " hidden"} data-yt>YouTube-Suche<input data-k="yt" value="${esc((m.musik || "").replace(/^youtube:/, ""))}" placeholder="z. B. Synthwave Mix"></label>
        <label class="me-f">Discord-Sprachkanal (am PC)<input data-k="discord" value="${esc(m.discord || "")}" placeholder="leer = keiner"></label>
        <label class="me-f">Programme öffnen (am PC, mit Komma)<input data-k="apps" value="${esc(m.apps || "")}" placeholder="z. B. Steam, Chrome"></label>
        <div class="me-f">${tg("sammeln", m.sammeln, "Nachrichten sammeln")}${tg("still", m.still, "Keine Kommentare von selbst")}${tg("aus", m.aus, "PC danach herunterfahren")}</div>
        <div class="me-f">${tg("pomo", m.pomo, "Pomodoro (Pausen ansagen)")}<div style="display:flex;gap:8px"${m.pomo ? "" : " hidden"} data-pomo><label class="me-f" style="flex:1">Minuten<input data-k="lern" type="number" min="5" max="120" value="${m.lern}"></label><label class="me-f" style="flex:1">Pause<input data-k="pause" type="number" min="1" max="60" value="${m.pause}"></label></div></div>
        <div class="me-row"><button class="me-btn del" data-del>${DEF.some((d) => d.id === m.id) ? (m.weg ? "Wieder zeigen" : "Ausblenden") : "Löschen"}</button></div></div></details>`; }).join("") +
      `<div class="me-row" style="margin-top:10px"><button class="me-btn" id="me-new">＋ Eigener Modus</button><button class="me-btn" id="me-reset">Standard</button><button class="me-btn ok" id="me-save">Speichern</button></div>`;
    $("md-edit").querySelectorAll(".me-m").forEach((box) => {
      const m = cfg[+box.dataset.i];
      box.querySelectorAll("input[data-k],select[data-k]").forEach((e) => e.addEventListener("input", () => {
        const k = e.dataset.k; let v = e.type === "number" ? +e.value : e.value;
        if (k === "musik") { box.querySelector("[data-yt]").hidden = v !== "youtube"; if (v === "youtube") v = "youtube:" + (box.querySelector('[data-k="yt"]').value || ""); }
        if (k === "yt") { m.musik = "youtube:" + v; return; }
        m[k] = v;
      }));
      box.querySelectorAll(".me-t").forEach((t) => t.addEventListener("click", () => { const k = t.dataset.k; m[k] = !m[k]; t.classList.toggle("on", m[k]); if (k === "pomo") box.querySelector("[data-pomo]").hidden = !m[k]; }));
      box.querySelector("[data-del]").addEventListener("click", () => { if (DEF.some((d) => d.id === m.id)) m.weg = !m.weg; else cfg.splice(cfg.indexOf(m), 1); editDraw(); });
    });
    $("me-new").onclick = () => { cfg.push({ id: "eigen" + Date.now().toString(36).slice(-4), n: "Neuer Modus", i: "◆", h: Math.floor(Math.random() * 360), d: "", handy: "normal", sammeln: false, still: false, musik: "", discord: "", apps: "", pomo: false, lern: 25, pause: 5, aus: false }); editDraw(); const all = $("md-edit").querySelectorAll(".me-m"); all[all.length - 1].open = true; };
    $("me-reset").onclick = () => { cfg = DEF.filter((d) => d.id !== "aus").map((d) => Object.assign({}, d)); saveCfg([]); st.modi = null; st.alle = null; editDraw(); };
    $("me-save").onclick = () => { saveCfg(cfg); st.alle = cfg; st.modi = cfg.filter((m) => !m.weg).concat([DEF[DEF.length - 1]]); toggleEdit(false); if (window.JModiToast) window.JModiToast("Modi gespeichert."); };
  }
  function toggleEdit(on) {
    editing = on; cfg = null;
    $("md-edbtn").classList.toggle("on", on); $("md-edbtn").textContent = on ? "Fertig" : "Bearbeiten";
    $("md-ttl").textContent = on ? "MODI BEARBEITEN" : "MODI";
    $("md-grid").hidden = on; $("md-edit").hidden = !on;
    if (on) editDraw(); else draw();
  }
  $("md-edbtn").addEventListener("click", () => toggleEdit(!editing));
  function open() { if (editing) toggleEdit(false); draw(); ov.classList.add("on"); }
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
