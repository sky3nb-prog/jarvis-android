// Einstellungen im HUD (gleicher Look wie die Handy-App): Aufbau und Werte kommen vom PC (/api/settings_full).
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const COL = { konto: "#ffd678", schule: "#ffd678", wege: "#6effcd", leute: "#ffb43c", allg: "#ffd678", hoer: "#3cc8ff", anz: "#d7a8ff", fern: "#3cc8ff", gaming: "#ff7a9a", lage: "#6effcd" };
  const BG = { konto: "#2a1c06", schule: "#2a2205", wege: "#0b2a22", leute: "#2a1306", allg: "#3a2608", hoer: "#0b2a3c", anz: "#13202a", fern: "#05202e", gaming: "#2a0f18", lage: "#2a1a05" };
  const OPEN = {};   // welche Karten aufgeklappt sind (pro Bereich)
  let data = null, vals = {}, tab = "", dirty = false, voiceNames = {};
  const root = $("pset");

  function open() {
    data = window.PC.get("settings_full");
    if (!data) { toast("Einstellungen konnten nicht geladen werden."); return; }
    vals = JSON.parse(JSON.stringify(data.values)); dirty = false;
    root.classList.add("on");   // Fenster schon zeigen, bevor gerendert wird – ein kaputtes Feld soll es nicht verstecken
    try { render(); } catch (e) { toast("Einstellungen: ein Feld war fehlerhaft, der Rest ist trotzdem da."); console.error(e); }
  }
  function close(ask) {
    if (ask && dirty && !confirmBox()) return;
    root.classList.remove("on");
    try { document.getElementById("gear").classList.toggle("hasnew", !!(data && (data.new || []).length)); } catch (e) {}
    if (window.__reload) location.reload();   // Einstellungen wurden inzwischen geändert (z. B. vom Handy)
  }
  // eigene Rückfrage statt confirm() (Dialoge blockieren das Fenster)
  function confirmBox() { $("ps-ask").classList.add("on"); return false; }

  function render() {
    const isNew = (k) => (data.new || []).includes(k);
    const tabNew = (t) => t.items.some((c) => c.items.some((i) => isNew(i.k)));
    if (!data.tabs.some((x) => x.id === tab)) tab = data.tabs[0].id;
    let lastG = "";
    $("ps-tabs").innerHTML = data.tabs.map((t) => { const g = t.g && t.g !== lastG ? `<div class="psg">${esc(t.g)}</div>` : ""; lastG = t.g || lastG;
      return g + `<div class="pst${t.id === tab ? " on" : ""}" data-t="${t.id}" style="--c:${COL[t.id] || "#3cc8ff"};--bg:${BG[t.id] || "#0b1820"}"><i>${t.i}</i>${esc(t.n)}${tabNew(t) ? '<b class="ndot"></b>' : ""}</div>`; }).join("");
    $("ps-tabs").querySelectorAll(".pst").forEach((e) => e.addEventListener("click", () => { tab = e.dataset.t; render(); $("ps-body").scrollTop = 0; }));
    const t = data.tabs.find((x) => x.id === tab) || data.tabs[0];
    $("ps-title").textContent = t.n.toUpperCase();
    if (!OPEN[t.id]) { OPEN[t.id] = {}; t.items.forEach((c, n) => { if (n === 0 || c.items.some((i) => isNew(i.k))) OPEN[t.id][n] = true; }); }
    $("ps-body").innerHTML = `<div class="ps-grid">${t.items.map((c, n) => card(c, COL[t.id], n, !!OPEN[t.id][n])).join("")}</div>`;
    $("ps-body").querySelectorAll(".ps-card > h3").forEach((h) => h.addEventListener("click", () => { const k = h.parentElement; const n = +k.dataset.n; OPEN[t.id][n] = !OPEN[t.id][n]; k.classList.toggle("open", OPEN[t.id][n]); }));
    (data.new || []).forEach((k) => { const e = $("ps-body").querySelector(`[data-k="${k}"]`); const f = e && e.closest(".ps-f, .ps-row"); const l = f && (f.querySelector("label") || f.firstElementChild); if (l) l.insertAdjacentHTML("beforeend", '<b class="ndot"></b>'); });
    // was du hier siehst, gilt als gesehen (der Punkt verschwindet beim nächsten Öffnen)
    const here = []; t.items.forEach((c) => c.items.forEach((i) => { if (i.k && isNew(i.k)) here.push(i.k); }));
    if (here.length) { window.PC.post("settings_seen", { keys: here }); setTimeout(() => { data.new = (data.new || []).filter((k) => !here.includes(k)); }, 0); }
    wire();
  }

  function card(c, col, n, op) {
    try {
      return `<div class="ps-card coll${op ? " open" : ""}${(c.items || []).some((i) => ["buttons", "plan", "schulkal", "ideen", "sticker"].includes(i.t)) ? " wide" : ""}" data-n="${n}" style="--c:${col}"><h3>${esc((c.l || "").toUpperCase())}</h3>${(c.items || []).map(item).join("")}</div>`;
    } catch (e) { console.error(e); return ""; }   // eine kaputte Karte soll nicht die ganze Seite leer lassen
  }
  function hint(i) { return i.h ? `<small>${esc(i.h)}</small>` : ""; }
  function item(i) {
    try { return itemRaw(i); } catch (e) { console.error(e); return ""; }   // ein kaputtes Feld soll nicht die ganze Karte/Seite mitreißen
  }
  function itemRaw(i) {
    const v = vals[i.k];
    switch (i.t) {
      case "sw": return `<div class="ps-row" data-k="${i.k}" data-t="sw"><div>${esc(i.l)}${hint(i)}</div><div class="sw${v ? " on" : ""}"></div></div>`;
      case "text": return `<div class="ps-f"><label>${esc(i.l)}</label><input data-k="${i.k}" type="${i.pw ? "password" : "text"}" value="${esc(v)}" placeholder="${esc(i.ph || "")}">${hint(i)}</div>`;
      case "area": return `<div class="ps-f"><label>${esc(i.l)}</label><textarea data-k="${i.k}" rows="4" placeholder="${esc(i.ph || "")}">${esc(v)}</textarea>${hint(i)}</div>`;
      case "secret": return `<div class="ps-f"><label>${esc(i.l)} <em class="${vals["_has_" + i.k] ? "ok" : ""}">${vals["_has_" + i.k] ? "● gespeichert" : "○ leer"}</em></label><input data-k="${i.k}" type="password" value="" placeholder="${vals["_has_" + i.k] ? "leer lassen = behalten" : "einfügen …"}">${hint(i)}</div>`;
      case "sel": {
        const opts = i.o.map(([n, ov]) => `<option value="${esc(ov == null ? "" : ov)}"${String(ov == null ? "" : ov) === String(v == null ? "" : v) ? " selected" : ""}>${esc(n)}</option>`).join("");
        return `<div class="ps-f"><label>${esc(i.l)}</label><div class="ps-sel"><select data-k="${i.k}">${opts}</select></div>${hint(i)}</div>`;
      }
      case "range": return `<div class="ps-f"><label>${esc(i.l)}<b data-out="${i.k}">${v}${i.u || ""}</b></label><input class="jr" data-k="${i.k}" data-u="${esc(i.u || "")}" type="range" min="${i.min}" max="${i.max}" value="${v}">${hint(i)}</div>`;
      case "choice": return `<div class="ps-f"><label>${esc(i.l)}</label><div class="ps-choice">${i.o.map(([n, ov, sub]) =>
        `<div class="pc-o${ov === v ? " on" : ""}" data-k="${i.k}" data-v="${esc(ov)}"><div class="mini ${esc(ov)}"><i></i><b></b></div><div class="n">${esc(n)}</div><small>${esc(sub || "")}</small></div>`).join("")}</div>${hint(i)}</div>`;
      case "btn": return `<div class="ps-btnrow"><button class="ps-btn" data-a="${i.a}">${esc(i.l)}</button><span class="ps-st" data-st="${i.a}"></span></div>`;
      case "plan": return `<div class="ps-f pp" data-k="${i.k}"><label>Wochenplan <span class="ps-st" id="pp-st"></span></label><div id="pp-grid" class="pp-load">Hole den Plan vom Handy …</div></div>`;
      case "schulkal": return `<div class="ps-f" data-k="${i.k}"><label>Kalender <span class="ps-st" id="sk-st"></span></label><div id="sk-pc" class="pp-load">Hole die Einträge vom Handy …</div></div>`;
      case "sticker": return `<div class="ps-f" data-k="sticker_wahl"><label>Welcher Sticker?</label><div id="stk-pc" class="stk-grid">…</div>
        <div class="ps-btnrow"><button class="ps-btn" id="stk-folder">Ordner öffnen (eigene Sticker reinlegen)</button><button class="ps-btn" id="stk-reload">Neu laden</button></div></div>`;
      case "ideen": return `<div class="ps-f" data-k="${i.k}"><label>Liste</label><div id="ideen-pc" class="pp-load">…</div></div>`;
      case "note": return i.l ? `<div class="ps-note">${esc(i.l)}</div>` : "";
      case "code": return `<div class="ps-f"><label>${esc(i.l)}</label><div class="ps-code" id="ps-code">${esc(i.v)}</div></div>`;
      case "buttons": {
        const rows = (Array.isArray(vals.hud_buttons) ? vals.hud_buttons : []).slice();
        while (rows.length < i.n) rows.push(["", "", ""]);
        return `<div class="ps-bt"><div class="h"><span></span><span>Name</span><span>Befehl</span></div>${rows.map((r, n) =>
          `<div class="r" data-n="${n}"><input value="${esc((r || [])[0])}" maxlength="2"><input value="${esc((r || [])[1])}" placeholder="z. B. Musik"><input value="${esc((r || [])[2])}" placeholder="z. B. musik an"></div>`).join("")}</div>
          <div class="ps-note">Symbole zum Kopieren: ♪ ▶ ⏸ « » ◍ ☀ ✉ ☎ ⚙ ★ ♥ ⌂ ✎ ☾ ⏻ D S C W</div>`;
      }
    }
    return "";
  }

  function set(k, v) { vals[k] = v; dirty = true; $("ps-save").classList.add("on"); }
  function wire() {
    const b = $("ps-body");
    b.querySelectorAll('[data-t="sw"]').forEach((r) => r.addEventListener("click", () => { const on = !vals[r.dataset.k]; set(r.dataset.k, on); r.querySelector(".sw").classList.toggle("on", on); }));
    b.querySelectorAll("input[data-k]:not([type=range]), select[data-k], textarea[data-k]").forEach((e) => e.addEventListener("input", () => set(e.dataset.k, e.value)));
    b.querySelectorAll("input[type=range][data-k]").forEach((e) => {
      const paint = () => e.style.setProperty("--p", ((e.value - e.min) / (e.max - e.min) * 100) + "%");
      paint();
      e.addEventListener("input", () => { paint(); set(e.dataset.k, +e.value); const o = b.querySelector(`[data-out="${e.dataset.k}"]`); if (o) o.textContent = e.value + (e.dataset.u || ""); });
    });
    b.querySelectorAll(".ps-bt .r").forEach((r) => r.querySelectorAll("input").forEach((inp, col) => inp.addEventListener("input", () => {
      const rows = []; b.querySelectorAll(".ps-bt .r").forEach((rr) => rows.push([...rr.querySelectorAll("input")].map((x) => x.value)));
      set("hud_buttons", rows);
    })));
    b.querySelectorAll(".pc-o").forEach((o) => o.addEventListener("click", () => {
      set(o.dataset.k, o.dataset.v);
      b.querySelectorAll(`.pc-o[data-k="${o.dataset.k}"]`).forEach((x) => x.classList.toggle("on", x === o));
    }));
    b.querySelectorAll(".ps-btn").forEach((btn) => btn.addEventListener("click", () => run(btn.dataset.a, btn)));
    if ($("pp-grid")) Plan.load();
    if ($("sk-pc") && window.JSchulKal) {
      const st = (t) => { const e = $("sk-st"); if (e) { e.textContent = t || ""; e.className = "ps-st" + (t && t.startsWith("✓") ? " ok" : ""); } };
      window.JSchulKal.mount($("sk-pc"), {
        host: root,
        load: () => window.PC.post("stundenplan", { op: "kal_get" }).then((r) => r && r.json()).then((r) => { $("sk-pc").className = ""; st(r && r.text); return (r && r.items) || []; }),
        save: (items) => window.PC.post("stundenplan", { op: "kal_set", items }).then((r) => r && r.json()).then((r) => st(r && r.text)),
        faecher: () => [],
      });
    }
    if ($("ideen-pc")) Ideen.load();
    if ($("stk-pc")) Sticker.load();
  }

  // --- Ideenliste -------------------------------------------------------------------------------------------
  const Ideen = (function () {
    function show(items) {
      const e = $("ideen-pc"); if (!e) return; e.className = "";
      e.innerHTML = items.length ? items.map((x, i) => ({ x, i })).reverse().map(({ x, i }) => `<div class="ps-row" style="cursor:default"><div>${esc(x.text)}<small>${new Date(x.t * 1000).toLocaleDateString("de-DE")} · ${x.von === "handy" ? "vom Handy" : "am PC"}</small></div><button class="ps-btn" data-idel="${i}">Löschen</button></div>`).join("") : '<div class="ps-note">Noch keine Ideen.</div>';
      e.querySelectorAll("[data-idel]").forEach((b) => b.addEventListener("click", () => window.PC.post("ideen", { op: "del", i: +b.dataset.idel }).then((r) => r && r.json()).then((r) => show((r && r.items) || []))));
    }
    return { load: () => window.PC.post("ideen", {}).then((r) => r && r.json()).then((r) => show((r && r.items) || [])) };
  })();

  // --- Stundenplan: gleiches Wochenraster wie am Handy, Änderungen gehen sofort aufs Handy -------------------
  const Plan = (function () {
    const D = [["mo", "Mo"], ["di", "Di"], ["mi", "Mi"], ["do", "Do"], ["fr", "Fr"]];
    const FAECHER = ["Mathe", "Deutsch", "Englisch", "Französisch", "Latein", "Spanisch", "Bio", "Chemie", "Physik", "Geschichte", "Erdkunde", "Gemeinschaftskunde", "WBS", "Religion", "Ethik", "Sport", "Kunst", "Musik", "Informatik", "NwT", "Technik", "AES", "Klassenrat", "Frei"];
    const hue = (f) => { let h = 0; for (const c of f.toLowerCase()) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
    const mins = (t) => { const m = /^(\d{1,2}):(\d{2})/.exec(t || ""); return m ? +m[1] * 60 + +m[2] : -1; };
    const today = ["", "mo", "di", "mi", "do", "fr", ""][new Date().getDay()];
    let plan = null;
    const st = (t, ok) => { const e = $("pp-st"); if (e) { e.textContent = t || ""; e.className = "ps-st" + (ok === true ? " ok" : ok === false ? " bad" : ""); } };
    function load() {
      st("…");
      window.PC.post("stundenplan", { op: "get" }).then((r) => r && r.json()).then((r) => { plan = (r && r.plan) || {}; draw(); st(r && r.text, true); })
        .catch(() => { plan = plan || {}; draw(); st("Konnte den Plan nicht laden.", false); });
    }
    function save() {
      st("schicke ans Handy …");
      window.PC.post("stundenplan", { op: "set", plan }).then((r) => r && r.json()).then((r) => st((r && r.text) || "", !!(r && r.text && r.text.startsWith("✓")) || undefined)).catch(() => st("Speichern ging nicht.", false));
    }
    function draw() {
      const g = $("pp-grid"); if (!g) return; g.className = "";
      const rows = Math.max(...D.map(([k]) => (plan[k] || []).length), 0), ref = plan.mo || [];
      const n = new Date(), m = n.getHours() * 60 + n.getMinutes();
      const cur = today ? (plan[today] || []).findIndex((l) => mins(l.von) <= m && m < mins(l.bis)) : -1;
      let h = `<div class="pp-tt"><div></div>` + D.map(([k, nm]) => `<div class="pp-h${k === today ? " today" : ""}">${nm}</div>`).join("");
      for (let i = 0; i <= rows; i++) {
        if (i > 0 && i < rows && ref[i] && ref[i - 1] && ref[i].von !== ref[i - 1].bis) h += `<div class="pp-p">${mins(ref[i].von) - mins(ref[i - 1].bis) >= 45 ? "Mittagspause" : "Pause"} · ${ref[i - 1].bis}–${ref[i].von}</div>`;
        h += `<div class="pp-n">${i < rows ? i + 1 : ""}</div>`;
        D.forEach(([k]) => {
          const l = (plan[k] || [])[i];
          if (l) { const f = (l.fach || "").trim();
            h += `<button class="pp-c${f ? " f" : ""}${k === today && i === cur ? " now" : ""}"${f ? ` style="--h:${hue(f)}"` : ""} data-d="${k}" data-i="${i}"><b>${f ? esc(f) : "+ Fach"}</b><small>${esc(l.von)}–${esc(l.bis)}</small></button>`; }
          else if (i === (plan[k] || []).length) h += `<button class="pp-c add" data-d="${k}" data-i="${i}"><b>＋</b></button>`;
          else h += `<div></div>`;
        });
      }
      g.innerHTML = h + "</div>";
      g.querySelectorAll(".pp-c").forEach((e) => e.addEventListener("click", () => edit(e.dataset.d, +e.dataset.i)));
    }
    function edit(d, i) {
      const L = plan[d] = plan[d] || [], isNew = i >= L.length, prev = L[L.length - 1];
      const l = isNew ? { von: prev ? prev.bis : "08:00", bis: "", fach: "" } : Object.assign({}, L[i]);
      if (isNew && prev && mins(prev.bis) >= 0) { const x = mins(prev.bis) + 45; l.bis = String(Math.floor(x / 60)).padStart(2, "0") + ":" + String(x % 60).padStart(2, "0"); }
      const used = [...new Set(D.flatMap(([k]) => (plan[k] || []).map((x) => (x.fach || "").trim())).filter(Boolean))];
      const chips = [...used, ...FAECHER.filter((f) => !used.includes(f))];
      let ed = $("pp-ed"); if (!ed) { ed = document.createElement("div"); ed.id = "pp-ed"; root.appendChild(ed); }
      const dn = D.find((x) => x[0] === d)[1];
      ed.innerHTML = `<div class="pp-box"><div class="pp-t">${dn} · ${i + 1}. Stunde</div>
        <input id="pp-f" class="pp-in" placeholder="Fach, z. B. Mathe" value="${esc(l.fach)}" autocomplete="off">
        <div class="pp-chips">${chips.map((f) => `<span class="pp-chip" style="--h:${hue(f)}">${esc(f)}</span>`).join("")}</div>
        <div class="pp-times"><label>von<input id="pp-v" type="time" value="${esc(l.von)}"></label><label>bis<input id="pp-b" type="time" value="${esc(l.bis)}"></label>
        <label class="pp-all"><input id="pp-all" type="checkbox"> Fach an allen Tagen in dieser Stunde</label></div>
        <div class="pp-btns">${isNew ? "" : '<button class="ps-btn pp-del" id="pp-del">Stunde löschen</button>'}<button class="ps-btn" id="pp-no">Abbrechen</button><button class="ps-btn pp-ok" id="pp-ok">Speichern</button></div></div>`;
      ed.className = "on";
      const f = $("pp-f"); setTimeout(() => f.focus(), 30);
      ed.querySelectorAll(".pp-chip").forEach((c) => c.addEventListener("click", () => { f.value = c.textContent; f.focus(); }));
      const close = () => { ed.className = ""; };
      ed.onclick = (e) => { if (e.target === ed) close(); };
      $("pp-no").onclick = close;
      if ($("pp-del")) $("pp-del").onclick = () => { L.splice(i, 1); close(); draw(); save(); };
      const ok = () => {
        l.fach = f.value.trim(); l.von = $("pp-v").value || l.von; l.bis = $("pp-b").value || l.bis;
        if (isNew) L.push(l); else L[i] = l;
        if ($("pp-all").checked) D.forEach(([k]) => { const x = (plan[k] || [])[i]; if (x) x.fach = l.fach; });
        close(); draw(); save();
      };
      $("pp-ok").onclick = ok;
      f.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); ok(); } if (e.key === "Escape") { e.stopPropagation(); close(); } });
    }
    const css = document.createElement("style");
    css.textContent = `
.pp-load{color:#8a9aa4;padding:10px 0}
.pp-tt{display:grid;grid-template-columns:22px repeat(5,minmax(0,1fr));gap:6px;margin-top:6px}
.pp-h{text-align:center;font-size:12px;letter-spacing:.12em;color:#c8965a;padding-bottom:2px}
.pp-h.today{color:#ffd678;font-weight:700;text-shadow:0 0 8px rgba(255,190,80,.7)}
.pp-n{font-size:12px;color:#8a6a3a;display:flex;align-items:center;justify-content:center}
.pp-p{grid-column:1/-1;text-align:center;font-size:11px;letter-spacing:.08em;color:#6effcd;opacity:.85;background:linear-gradient(90deg,transparent,rgba(110,255,205,.08),transparent);border-radius:6px;padding:1px 0}
.pp-c{all:unset;box-sizing:border-box;min-height:50px;padding:6px 4px;border-radius:10px;text-align:center;cursor:pointer;border:1px dashed rgba(255,190,90,.25);background:rgba(0,0,0,.25);display:flex;flex-direction:column;justify-content:center;gap:2px;min-width:0;transition:transform .12s,box-shadow .12s}
.pp-c:hover{transform:translateY(-2px);box-shadow:0 4px 14px rgba(255,170,40,.18)}
.pp-c:focus-visible{outline:2px solid #ffd678}
.pp-c b{font-size:13px;color:#8a6a3a;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pp-c small{font-size:10.5px;color:#8a6a3a;opacity:.85;font-variant-numeric:tabular-nums}
.pp-c.f{border:1px solid hsla(var(--h),70%,60%,.55);background:hsla(var(--h),60%,30%,.35)}
.pp-c.f b{color:hsl(var(--h),85%,80%)} .pp-c.f small{color:hsl(var(--h),40%,72%)}
.pp-c.now{box-shadow:0 0 0 2px #ffd678,0 0 14px rgba(255,200,90,.6)}
.pp-c.add{opacity:.6;min-height:34px} .pp-c.add b{font-size:12px;color:#c8965a}
#pp-ed{position:absolute;inset:0;z-index:60;background:rgba(4,3,1,.7);display:none;align-items:center;justify-content:center;backdrop-filter:blur(3px)}
#pp-ed.on{display:flex}
.pp-box{width:min(520px,92%);background:linear-gradient(180deg,#1d1408,#0d0904);border:1px solid rgba(255,190,90,.4);border-radius:18px;padding:18px;box-shadow:0 10px 50px rgba(255,160,30,.18)}
.pp-t{font-size:13px;letter-spacing:.14em;color:#ffaa28;text-transform:uppercase;margin-bottom:10px}
.pp-in{width:100%;box-sizing:border-box;font-size:24px;padding:12px 14px;border-radius:12px;border:1px solid #ffaa28;background:rgba(0,0,0,.45);color:#fff1c8;outline:none}
.pp-chips{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0;max-height:130px;overflow-y:auto}
.pp-chip{padding:5px 10px;border-radius:999px;font-size:13px;cursor:pointer;color:hsl(var(--h),85%,80%);background:hsla(var(--h),60%,30%,.35);border:1px solid hsla(var(--h),70%,60%,.45)}
.pp-chip:hover{filter:brightness(1.25)}
.pp-times{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end}
.pp-times label{flex:1;font-size:12px;color:#c8965a;display:flex;flex-direction:column;gap:4px;min-width:110px}
.pp-times input[type=time]{padding:9px;border-radius:10px;border:1px solid #4a3410;background:rgba(0,0,0,.4);color:#ffe1b4;font-size:15px;color-scheme:dark}
.pp-times .pp-all{flex-basis:100%;flex-direction:row;align-items:center;gap:8px;font-size:13px;color:#d9c3a0;cursor:pointer}
.pp-btns{display:flex;gap:8px;margin-top:16px;justify-content:flex-end}
.pp-btns .pp-del{margin-right:auto;color:#ff8a6a}
.pp-btns .pp-ok{background:#ffaa28;color:#1a1006;font-weight:700}`;
    document.head.appendChild(css);
    return { load };
  })();

  // Sticker-Auswahl: Bilder aus dem Ordner „Sticker“, antippen = auswählen
  const Sticker = (function () {
    const css = document.createElement("style");
    css.textContent = `.stk-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(74px,1fr));gap:8px;margin:4px 0 10px}
      .stk-it{aspect-ratio:1;border-radius:14px;border:1px solid #23343e;background:#0b1820;display:flex;align-items:center;justify-content:center;cursor:pointer;position:relative;overflow:hidden}
      .stk-it img{max-width:82%;max-height:82%}.stk-it.on{border-color:#ffb43c;box-shadow:0 0 0 2px rgba(255,180,60,.45)}
      .stk-it.on::after{content:"✓";position:absolute;top:4px;right:7px;color:#ffd678;font-weight:700}
      .stk-empty{color:#8aa0ad;font-size:13px;line-height:1.45}`;
    document.head.appendChild(css);
    function show(d) {
      const e = $("stk-pc"); if (!e) return;
      const it = (d && d.items) || [];
      e.innerHTML = it.length ? it.map((s) => `<div class="stk-it${s.name === d.chosen ? " on" : ""}" data-n="${esc(s.name)}" title="${esc(s.name)}">${s.img ? `<img src="${s.img}">` : esc(s.name)}</div>`).join("")
        : '<div class="stk-empty">Noch keine Sticker. Tipp auf „Ordner öffnen“ und leg Bilder rein (.png, .webp oder .gif – am besten mit durchsichtigem Hintergrund). Dann „Neu laden“.</div>';
      e.querySelectorAll(".stk-it").forEach((x) => x.addEventListener("click", () => window.PC.post("sticker_pick", { name: x.dataset.n }).then(() => load())));
    }
    function load() { show(window.PC.get("sticker")); const f = $("stk-folder"), r = $("stk-reload");
      if (f) f.onclick = () => window.PC.post("sticker_folder", {}); if (r) r.onclick = () => load(); }
    return { load };
  })();

  // Selbstzerstörung: erst nach zweimal Bestätigen (dreimal tippen); nach 6 s ohne Tippen wieder zurück
  let wegStep = 0, wegT = null;
  // Countdown, alles zerfällt und wird in die Mitte gesaugt, roter Blitz, „GELÖSCHT“
  function boom(after) {
    const st = document.createElement("style");
    st.textContent = `
    .zf{transition:transform 1.1s cubic-bezier(.6,0,.9,.4),opacity 1.1s ease-in,filter 1.1s ease-in!important;transform:translate(var(--dx),var(--dy)) scale(.05) rotate(var(--rot))!important;opacity:0!important;filter:blur(6px) hue-rotate(-40deg)!important}
    #boom{position:fixed;inset:0;z-index:99999;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#ff6a5a;transition:background .6s}
    #boom.dark{background:radial-gradient(circle at 50% 50%,rgba(60,0,0,.85),#000 70%)}
    #boom .cnt{font-size:140px;font-weight:800;letter-spacing:4px;text-shadow:0 0 30px #ff2a1a,0 0 80px #ff2a1a;animation:bpulse .5s ease-in-out infinite alternate}
    #boom .lbl{margin-top:6px;font-size:14px;letter-spacing:8px;color:#ffb0a0}
    #boom .scan{position:absolute;inset:0;background:repeating-linear-gradient(0deg,rgba(255,40,20,.10) 0 2px,transparent 2px 5px);mix-blend-mode:screen;animation:bscan 1.2s linear infinite;pointer-events:none}
    #boom .core{position:absolute;width:24px;height:24px;border-radius:50%;background:#fff;box-shadow:0 0 40px 20px #ff5a2a,0 0 120px 60px #ff2a1a;opacity:0;transform:scale(.2)}
    #boom.flash .core{animation:bcore .7s ease-out forwards}
    #boom .done{font-size:26px;letter-spacing:10px;color:#fff;opacity:0;transition:opacity .6s;text-shadow:0 0 20px #ff4a2a;position:relative;z-index:2}
    @keyframes bpulse{to{transform:scale(1.08)}} @keyframes bscan{to{background-position:0 40px}}
    @keyframes bcore{0%{opacity:0;transform:scale(.2)}20%{opacity:1;transform:scale(3)}100%{opacity:0;transform:scale(80)}}`;
    document.head.appendChild(st);
    const ov = document.createElement("div"); ov.id = "boom";
    ov.innerHTML = '<div class="scan"></div><div class="core"></div><div class="cnt">3</div><div class="lbl">SELBSTZERSTÖRUNG</div><div class="done">GELÖSCHT</div>';
    document.body.appendChild(ov);
    setTimeout(() => ov.classList.add("dark"), 100);
    let n = 3; const c = ov.querySelector(".cnt");
    const tick = setInterval(() => {
      n--; if (n > 0) { c.textContent = n; return; }
      clearInterval(tick); c.style.display = "none"; ov.querySelector(".lbl").style.display = "none";
      const cx = innerWidth / 2, cy = innerHeight / 2;
      document.querySelectorAll(".ps-card, .ps-row, .ps-btnrow, .ps-note, h2, h3, canvas, .ps-side a, .ps-tab, input, button, select").forEach((el, i) => {
        if (ov.contains(el)) return;
        const r = el.getBoundingClientRect(); if (r.width === 0 || r.bottom < 0 || r.top > innerHeight) return;
        el.style.setProperty("--dx", (cx - (r.left + r.width / 2)) + "px"); el.style.setProperty("--dy", (cy - (r.top + r.height / 2)) + "px");
        el.style.setProperty("--rot", ((Math.random() * 2 - 1) * 180).toFixed(0) + "deg");
        setTimeout(() => el.classList.add("zf"), Math.min(900, i * 12));
      });
      setTimeout(() => { ov.classList.add("flash"); Array.from(document.body.children).forEach((el) => { if (el !== ov) { el.style.transition = "opacity .5s"; el.style.opacity = "0"; } }); }, 1100);
      setTimeout(() => { ov.style.background = "#000"; }, 1800);
      setTimeout(() => { ov.querySelector(".done").style.opacity = "1"; }, 1900);
      setTimeout(after, 3000);
    }, 1000);
  }
  const WEG = [["Selbstzerstörung", ""], ["Wirklich? Nochmal klicken", "Noch einmal klicken – dann ist alles weg"], ["JA, ALLES LÖSCHEN", "Letzte Chance: jetzt klicken löscht Vector von diesem PC"]];
  function run(a, btn) {
    if (a === "konto_open" && window.JKonto) { close(false); window.JKonto.open(); return; }
    if (a === "farbe_open" && window.JFarbe) { window.JFarbe.open(); return; }
    if (a === "selbstzerstoerung" && wegStep < 2 && !btn.dataset.boom) {
      clearTimeout(wegT); wegStep++;
      btn.textContent = WEG[wegStep][0]; btn.style.color = "#ff9a8a"; btn.style.borderColor = "#ff5a5a";
      const st0 = $("ps-body").querySelector('[data-st="selbstzerstoerung"]'); if (st0) { st0.className = "ps-st bad"; st0.textContent = WEG[wegStep][1]; }
      wegT = setTimeout(() => { wegStep = 0; btn.textContent = WEG[0][0]; btn.style.color = ""; btn.style.borderColor = ""; if (st0) st0.textContent = ""; }, 6000);
      return;
    }
    if (a === "selbstzerstoerung" && !btn.dataset.boom) {   // dritter Klick: erst die Animation, dann wirklich löschen
      clearTimeout(wegT); wegStep = 0; btn.dataset.boom = "1";
      boom(() => run(a, btn)); return;
    }
    const st = $("ps-body").querySelector(`[data-st="${a}"]`);
    btn.classList.add("busy"); if (st) { st.className = "ps-st"; st.textContent = "…"; }
    window.PC.post("settings_run", { name: a, values: vals }).then((r) => r && r.json()).then((r) => {
      btn.classList.remove("busy"); r = r || {};
      if (st) { st.textContent = (r.ok ? "✓ " : "✕ ") + (r.text || ""); st.className = "ps-st " + (r.ok ? "ok" : "bad"); }
      if (r.code && $("ps-code")) $("ps-code").textContent = r.code;
      if (r.options) for (const k in r.options) {
        data.tabs.forEach((t) => t.items.forEach((c) => c.items.forEach((i) => { if (i.k === k) i.o = r.options[k]; })));
        r.options[k].forEach(([n, v]) => (voiceNames[v] = n));
        render();
      }
    }).catch(() => { btn.classList.remove("busy"); if (st) st.textContent = "✕ keine Antwort"; });
  }

  function save() {
    const v = Object.assign({}, vals, { _voice_names: voiceNames });
    window.PC.post("settings_save", { values: v }).then((r) => r && r.json()).then((r) => {
      dirty = false; $("ps-save").classList.remove("on"); toast("✓ Gespeichert");
      setTimeout(() => close(false), 350);
    }).catch(() => toast("Speichern ging nicht."));
  }
  function toast(t) { const e = $("toast"); if (!e) return; e.textContent = t; e.classList.add("ok"); e.style.display = "block"; clearTimeout(toast.j); toast.j = setTimeout(() => (e.style.display = "none"), 2500); }

  // --- Suche in den Einstellungen (wie am Handy): durchsucht alle Tabs, Tippen springt hin -----------------
  (function () {
    const inp = $("ps-search"), out = $("ps-results"); if (!inp || !out) return;
    const norm = (t) => String(t || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    const esc = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;");
    function index() {
      const items = [];
      if (!data) return items;
      data.tabs.forEach((t) => {
        t.items.forEach((c, n) => {
          const cardText = (c.items || []).map((i) => (i.l || "") + " " + (i.h || "")).join(" ");
          items.push({ tid: t.id, n, label: c.l, area: t.n, text: norm(c.l + " " + cardText) });
          (c.items || []).forEach((i) => {
            if (!i.l || i.l.length < 2) return;
            items.push({ tid: t.id, n, label: i.l, area: t.n + " › " + c.l, text: norm(i.l + " " + (i.h || "")) });
          });
        });
      });
      return items;
    }
    let idx = null;
    function go(it) {
      inp.value = ""; out.style.display = "none"; out.innerHTML = "";
      tab = it.tid; OPEN[it.tid] = OPEN[it.tid] || {}; OPEN[it.tid][it.n] = true;
      render();
      setTimeout(() => {
        const el = $("ps-body").querySelector(`.ps-card[data-n="${it.n}"]`); if (!el) return;
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.style.transition = "background .6s"; el.style.background = "#ffd67822";
        setTimeout(() => { el.style.background = ""; }, 1600);
      }, 60);
    }
    inp.addEventListener("input", () => {
      const q = norm(inp.value.trim());
      if (!q) { out.style.display = "none"; out.innerHTML = ""; return; }
      idx = idx || index();
      const words = q.split(/\s+/);
      const hits = idx.filter((it) => words.every((w) => it.text.includes(w))).slice(0, 10);
      out.innerHTML = hits.length ? hits.map((it, i) => `<div class="psr" data-i="${i}"><b>${esc(it.label)}</b><small>${esc(it.area)}</small></div>`).join("")
        : '<div class="psr-none">Nichts gefunden.</div>';
      out.style.display = "block";
      out.querySelectorAll(".psr[data-i]").forEach((e) => e.addEventListener("click", () => go(hits[+e.dataset.i])));
    });
    inp.addEventListener("focus", () => { idx = null; });
    document.addEventListener("click", (e) => { if (e.target !== inp && !out.contains(e.target)) { out.style.display = "none"; } });
  })();

  $("ps-close").addEventListener("click", () => close(true));
  $("ps-save").addEventListener("click", save);
  $("ps-ask-no").addEventListener("click", () => $("ps-ask").classList.remove("on"));
  $("ps-ask-drop").addEventListener("click", () => { $("ps-ask").classList.remove("on"); dirty = false; close(false); });
  $("ps-ask-save").addEventListener("click", () => { $("ps-ask").classList.remove("on"); save(); });
  root.addEventListener("click", (e) => { if (e.target === root) close(true); });
  addEventListener("keydown", (e) => { if (e.key === "Escape" && root.classList.contains("on")) close(true); });
  window.JSettings = { open, close, isOpen: () => root.classList.contains("on"), dirty: () => dirty };
})();
