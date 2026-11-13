// Einstellungen im HUD (gleicher Look wie die Handy-App): Aufbau und Werte kommen vom PC (/api/settings_full).
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const COL = { allg: "#ffd678", hoer: "#3cc8ff", stim: "#ffb43c", lage: "#6effcd", anz: "#d7a8ff", kn: "#ffd678", inf: "#3cc8ff", ki: "#ffa03c", dat: "#6effcd", hdy: "#d7a8ff" };
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
    if (window.__reload) location.reload();   // Einstellungen wurden inzwischen geändert (z. B. vom Handy)
  }
  // eigene Rückfrage statt confirm() (Dialoge blockieren das Fenster)
  function confirmBox() { $("ps-ask").classList.add("on"); return false; }

  function render() {
    $("ps-tabs").innerHTML = data.tabs.map((t) => `<div class="pst${t.id === tab ? " on" : ""}" data-t="${t.id}" style="--c:${COL[t.id] || "#3cc8ff"}"><i>${t.i}</i>${esc(t.n)}</div>`).join("");
    $("ps-tabs").querySelectorAll(".pst").forEach((e) => e.addEventListener("click", () => { tab = e.dataset.t; render(); $("ps-body").scrollTop = 0; }));
    const t = data.tabs.find((x) => x.id === tab) || data.tabs[0];
    $("ps-title").textContent = t.n.toUpperCase();
    $("ps-body").innerHTML = `<div class="ps-grid">${t.items.map((c) => card(c, COL[t.id])).join("")}</div>`;
    wire();
  }

  function card(c, col) {
    return `<div class="ps-card${c.items.some((i) => i.t === "buttons") ? " wide" : ""}" style="--c:${col}"><h3>${esc(c.l.toUpperCase())}</h3>${c.items.map(item).join("")}</div>`;
  }
  function hint(i) { return i.h ? `<small>${esc(i.h)}</small>` : ""; }
  function item(i) {
    const v = vals[i.k];
    switch (i.t) {
      case "sw": return `<div class="ps-row" data-k="${i.k}" data-t="sw"><div>${esc(i.l)}${hint(i)}</div><div class="sw${v ? " on" : ""}"></div></div>`;
      case "text": return `<div class="ps-f"><label>${esc(i.l)}</label><input data-k="${i.k}" type="${i.pw ? "password" : "text"}" value="${esc(v)}" placeholder="${esc(i.ph || "")}">${hint(i)}</div>`;
      case "secret": return `<div class="ps-f"><label>${esc(i.l)} <em class="${vals["_has_" + i.k] ? "ok" : ""}">${vals["_has_" + i.k] ? "● gespeichert" : "○ leer"}</em></label><input data-k="${i.k}" type="password" value="" placeholder="${vals["_has_" + i.k] ? "leer lassen = behalten" : "einfügen …"}">${hint(i)}</div>`;
      case "sel": {
        const opts = i.o.map(([n, ov]) => `<option value="${esc(ov == null ? "" : ov)}"${String(ov == null ? "" : ov) === String(v == null ? "" : v) ? " selected" : ""}>${esc(n)}</option>`).join("");
        return `<div class="ps-f"><label>${esc(i.l)}</label><div class="ps-sel"><select data-k="${i.k}">${opts}</select></div>${hint(i)}</div>`;
      }
      case "range": return `<div class="ps-f"><label>${esc(i.l)}<b data-out="${i.k}">${v}${i.u || ""}</b></label><input class="jr" data-k="${i.k}" data-u="${esc(i.u || "")}" type="range" min="${i.min}" max="${i.max}" value="${v}">${hint(i)}</div>`;
      case "choice": return `<div class="ps-f"><label>${esc(i.l)}</label><div class="ps-choice">${i.o.map(([n, ov, sub]) =>
        `<div class="pc-o${ov === v ? " on" : ""}" data-k="${i.k}" data-v="${esc(ov)}"><div class="mini ${esc(ov)}"><i></i><b></b></div><div class="n">${esc(n)}</div><small>${esc(sub || "")}</small></div>`).join("")}</div>${hint(i)}</div>`;
      case "btn": return `<div class="ps-btnrow"><button class="ps-btn" data-a="${i.a}">${esc(i.l)}</button><span class="ps-st" data-st="${i.a}"></span></div>`;
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
    b.querySelectorAll("input[data-k]:not([type=range]), select[data-k]").forEach((e) => e.addEventListener("input", () => set(e.dataset.k, e.value)));
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
  }

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
