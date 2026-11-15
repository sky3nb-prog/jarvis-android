// Einstellungen im HUD (gleicher Look wie die Handy-App): Aufbau und Werte kommen vom PC (/api/settings_full).
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const COL = { ideen: "#d7a8ff", schule: "#ffd678", allg: "#ffd678", hoer: "#3cc8ff", stim: "#ffb43c", lage: "#6effcd", anz: "#d7a8ff", kn: "#ffd678", inf: "#3cc8ff", ki: "#ffa03c", dat: "#6effcd", hdy: "#d7a8ff", wege: "#6effcd" };
  let data = null, vals = {}, tab = "allg", dirty = false, voiceNames = {};
  const root = $("pset");

  function open() {
    data = window.PC.get("settings_full");
    if (!data) { toast("Einstellungen konnten nicht geladen werden."); return; }
    vals = JSON.parse(JSON.stringify(data.values)); dirty = false;
    render(); root.classList.add("on");
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
    $("ps-tabs").innerHTML = data.tabs.map((t) => `<div class="pst${t.id === tab ? " on" : ""}" data-t="${t.id}" style="--c:${COL[t.id] || "#3cc8ff"}"><i>${t.i}</i>${esc(t.n)}${tabNew(t) ? '<b class="ndot"></b>' : ""}</div>`).join("");
    $("ps-tabs").querySelectorAll(".pst").forEach((e) => e.addEventListener("click", () => { tab = e.dataset.t; render(); $("ps-body").scrollTop = 0; }));
    const t = data.tabs.find((x) => x.id === tab) || data.tabs[0];
    $("ps-title").textContent = t.n.toUpperCase();
    $("ps-body").innerHTML = `<div class="ps-grid">${t.items.map((c) => card(c, COL[t.id])).join("")}</div>`;
    (data.new || []).forEach((k) => { const e = $("ps-body").querySelector(`[data-k="${k}"]`); const f = e && e.closest(".ps-f, .ps-row"); const l = f && (f.querySelector("label") || f.firstElementChild); if (l) l.insertAdjacentHTML("beforeend", '<b class="ndot"></b>'); });
    // was du hier siehst, gilt als gesehen (der Punkt verschwindet beim nächsten Öffnen)
    const here = []; t.items.forEach((c) => c.items.forEach((i) => { if (i.k && isNew(i.k)) here.push(i.k); }));
    if (here.length) { window.PC.post("settings_seen", { keys: here }); setTimeout(() => { data.new = (data.new || []).filter((k) => !here.includes(k)); }, 0); }
    wire();
  }

  function card(c, col) {
    return `<div class="ps-card${c.items.some((i) => ["buttons", "plan", "schulkal", "ideen"].includes(i.t)) ? " wide" : ""}" style="--c:${col}"><h3>${esc(c.l.toUpperCase())}</h3>${c.items.map(item).join("")}</div>`;
  }
  function hint(i) { return i.h ? `<small>${esc(i.h)}</small>` : ""; }
  function item(i) {
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
      case "ideen": return `<div class="ps-f" data-k="${i.k}"><label>Liste</label><div id="ideen-pc" class="pp-load">…</div></div>`;
      case "note": return i.l ? `<div class="ps-note">${esc(i.l)}</div>` : "";
      case "code": return `<div class="ps-f"><label>${esc(i.l)}</label><div class="ps-code" id="ps-code">${esc(i.v)}</div></div>`;
      case "buttons": {
        const rows = (vals.hud_buttons || []).slice();
        while (rows.length < i.n) rows.push(["", "", ""]);
        return `<div class="ps-bt"><div class="h"><span></span><span>Name</span><span>Befehl</span></div>${rows.map((r, n) =>
          `<div class="r" data-n="${n}"><input value="${esc(r[0])}" maxlength="2"><input value="${esc(r[1])}" placeholder="z. B. Musik"><input value="${esc(r[2])}" placeholder="z. B. musik an"></div>`).join("")}</div>
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

  function run(a, btn) {
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

  $("ps-close").addEventListener("click", () => close(true));
  $("ps-save").addEventListener("click", save);
  $("ps-ask-no").addEventListener("click", () => $("ps-ask").classList.remove("on"));
  $("ps-ask-drop").addEventListener("click", () => { $("ps-ask").classList.remove("on"); dirty = false; close(false); });
  $("ps-ask-save").addEventListener("click", () => { $("ps-ask").classList.remove("on"); save(); });
  root.addEventListener("click", (e) => { if (e.target === root) close(true); });
  addEventListener("keydown", (e) => { if (e.key === "Escape" && root.classList.contains("on")) close(true); });
  window.JSettings = { open, close, isOpen: () => root.classList.contains("on"), dirty: () => dirty };
})();
