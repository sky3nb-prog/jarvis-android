// Schul-Kalender (Handy und PC gleich): Monat mit Arbeiten, Tests und Hausaufgaben, Tag antippen -> eintragen.
// JSchulKal.mount(element, { load: () => Promise<items>, save: (items) => Promise, faecher: () => [..] })
(function () {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const ART = { arbeit: ["Arbeit", 8], test: ["Test", 30], ha: ["Hausaufgabe", 200], info: ["Termin", 140] };
  const MON = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
  const gnum = (n) => { const m = /^\s*([1-6])\s*([+-])?/.exec(String(n || "")); return m ? +m[1] + (m[2] === "+" ? -0.25 : m[2] === "-" ? 0.25 : 0) : null; };
  const gcol = (v) => v == null ? 40 : v <= 2 ? 140 : v <= 3 ? 90 : v <= 4 ? 40 : 0;
  const iso = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  const css = document.createElement("style");
  css.textContent = `
.sk{font-size:14px}
.sk-hd{display:flex;align-items:center;justify-content:space-between;margin:2px 0 8px}
.sk-hd b{font-size:15px;color:#9fe1cb;letter-spacing:.06em}
.sk-nav{all:unset;cursor:pointer;width:32px;height:32px;border-radius:10px;border:1px solid #145a42;color:#5ac89b;display:flex;align-items:center;justify-content:center}
.sk-g{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px}
.sk-wd{text-align:center;font-size:11px;letter-spacing:.1em;color:#3a8a6e;padding-bottom:2px}
.sk-d{all:unset;box-sizing:border-box;cursor:pointer;min-height:48px;border-radius:9px;padding:3px 3px 4px;background:rgba(0,0,0,.25);border:1px solid rgba(90, 255, 198,.12);display:flex;flex-direction:column;gap:2px;min-width:0}
.sk-d.out{opacity:.35}.sk-d.today{border-color:#9fe1cb;box-shadow:0 0 10px rgba(90, 255, 208,.35)}.sk-d.sel{background:rgba(29, 158, 117,.16)}
.sk-d .n{font-size:11px;color:#5ac89b}.sk-d.today .n{color:#9fe1cb;font-weight:700}
.sk-d .e{font-size:9.5px;line-height:1.15;padding:1px 3px;border-radius:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:hsl(var(--h),90%,82%);background:hsla(var(--h),70%,35%,.45)}
.sk-d .e.done{opacity:.4;text-decoration:line-through}
.sk-day{margin-top:10px;padding:10px;border-radius:12px;border:1px solid rgba(90, 255, 198,.25);background:rgba(0,0,0,.25)}
.sk-day h4{margin:0 0 6px;font-size:13px;color:#1d9e75;letter-spacing:.08em;font-weight:700}
.sk-it{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid rgba(90, 255, 198,.1)}
.sk-it:last-child{border-bottom:0}
.sk-chk{all:unset;cursor:pointer;width:20px;height:20px;border-radius:6px;border:1.5px solid hsl(var(--h),70%,60%);flex:0 0 20px;display:flex;align-items:center;justify-content:center;color:#050b08;font-size:13px}
.sk-chk.on{background:hsl(var(--h),80%,65%)}
.sk-it .t{flex:1;min-width:0}.sk-it .t b{color:hsl(var(--h),90%,82%);font-size:13px}.sk-it .t small{display:block;color:#8ab9a9;font-size:12px;overflow-wrap:anywhere}
.sk-it .t i{font-style:normal;font-size:10px;color:#6effcd;margin-left:4px}
.sk-x{all:unset;cursor:pointer;color:#ff8a6a;padding:4px 6px}
.sk-adds{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.sk-add{all:unset;cursor:pointer;padding:7px 11px;border-radius:999px;font-size:13px;color:hsl(var(--h),90%,82%);border:1px solid hsla(var(--h),70%,60%,.5);background:hsla(var(--h),60%,25%,.35)}
.sk-up{margin-top:10px}.sk-up h4{margin:0 0 4px;font-size:12px;color:#3a8a6e;letter-spacing:.14em;font-weight:700}
.sk-ed{position:fixed;inset:0;z-index:9999;background:rgba(1, 4, 3,.72);display:none;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(3px)}
.sk-ed.on{display:flex}
.sk-box{width:min(520px,100%);background:linear-gradient(180deg,#081d15,#040d09);border:1px solid rgba(90, 255, 198,.4);border-radius:18px;padding:16px}
.sk-box .sk-tt{font-size:13px;letter-spacing:.14em;color:#1d9e75;text-transform:uppercase;margin-bottom:10px}
.sk-row{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.sk-chip{all:unset;cursor:pointer;padding:6px 10px;border-radius:999px;font-size:13px;color:#a0d9c6;border:1px solid #145a42}
.sk-chip.on{color:#050b08;background:#9fe1cb;border-color:#9fe1cb}
.sk-chip.f.on{background:#3cc8ff;border-color:#3cc8ff}
.sk-box input{width:100%;box-sizing:border-box;font-size:17px;padding:11px 12px;border-radius:12px;border:1px solid #1d9e75;background:rgba(0,0,0,.45);color:#c8fff4;outline:none;color-scheme:dark}
.sk-box input[type=date]{font-size:15px;border-color:#104a37;margin-top:8px}
.sk-btns{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}
.sk-btn{all:unset;cursor:pointer;padding:9px 14px;border-radius:999px;border:1px solid #145a42;color:#a0d9c6;font-size:14px}
.sk-g1{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:999px;font-size:12px;font-weight:700;color:#050b08;background:hsl(var(--g),70%,60%)}
.sk-noten{margin-top:10px}.sk-noten h4{margin:0 0 6px;font-size:12px;color:#3a8a6e;letter-spacing:.14em;font-weight:700}
.sk-nr{display:flex;align-items:center;gap:8px;padding:5px 0;font-size:13px;color:#b8e8d8;border-bottom:1px solid rgba(90, 255, 198,.1)}
.sk-nr b{flex:1}.sk-nr small{color:#8ab9a9}.sk-nr i{font-style:normal;font-weight:700;min-width:38px;text-align:center;padding:2px 6px;border-radius:8px;color:#050b08;background:hsl(var(--g),70%,60%)}
.sk-btn.ok{background:#1d9e75;color:#061a11;font-weight:700;border-color:#1d9e75}`;
  document.head.appendChild(css);

  function mount(el, io) {
    let items = [], view = new Date(), sel = iso(new Date());
    view.setDate(1);
    const st = { busy: false };
    const save = () => io.save(items);
    async function reload() { try { items = (await io.load()) || []; } catch (e) { items = []; } draw(); }
    function forDay(d) { return items.filter((x) => x.datum === d).sort((a, b) => (a.art > b.art ? 1 : -1)); }
    function draw() {
      const y = view.getFullYear(), m = view.getMonth(), first = new Date(y, m, 1), start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7));
      const today = iso(new Date());
      let h = `<div class="sk"><div class="sk-hd"><button class="sk-nav" data-nav="-1" aria-label="Monat zurück">‹</button><b>${MON[m]} ${y}</b><button class="sk-nav" data-nav="1" aria-label="Monat vor">›</button></div><div class="sk-g">`;
      h += ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"].map((w) => `<div class="sk-wd">${w}</div>`).join("");
      for (let i = 0; i < 42; i++) {
        const d = new Date(start); d.setDate(start.getDate() + i); const k = iso(d);
        if (i >= 35 && d.getMonth() !== m) break;
        h += `<button class="sk-d${d.getMonth() !== m ? " out" : ""}${k === today ? " today" : ""}${k === sel ? " sel" : ""}" data-d="${k}"><span class="n">${d.getDate()}</span>` +
          forDay(k).slice(0, 3).map((x) => `<span class="e${x.done ? " done" : ""}" style="--h:${(ART[x.art] || ART.info)[1]}">${esc(x.fach || (ART[x.art] || ART.info)[0])}</span>`).join("") + `</button>`;
      }
      h += `</div>`;
      const sd = new Date(sel + "T12:00"), list = forDay(sel);
      h += `<div class="sk-day"><h4>${sd.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" })}</h4>` +
        (list.length ? list.map(row).join("") : `<div style="color:#628a7c;font-size:13px">Nichts eingetragen.</div>`) +
        `<div class="sk-adds">${["arbeit", "test", "ha"].map((a) => `<button class="sk-add" style="--h:${ART[a][1]}" data-add="${a}">＋ ${ART[a][0]}</button>`).join("")}</div></div>`;
      const up = items.filter((x) => !x.done && x.datum >= today && x.datum !== sel).sort((a, b) => (a.datum > b.datum ? 1 : -1)).slice(0, 6);
      if (up.length) h += `<div class="sk-up"><h4>DEMNÄCHST</h4>${up.map(row).join("")}</div>`;
      const ng = items.filter((x) => gnum(x.note) != null);
      if (ng.length) {
        const by = {}; ng.forEach((x) => { const f = x.fach || "Ohne Fach"; (by[f] = by[f] || []).push(x); });
        h += `<div class="sk-noten"><h4>NOTEN</h4>` + Object.keys(by).sort().map((f) => { const l = by[f].sort((a, b) => (a.datum > b.datum ? 1 : -1)); const avg = l.reduce((s, x) => s + gnum(x.note), 0) / l.length;
          return `<div class="sk-nr"><b>${esc(f)}</b><small>${l.map((x) => esc(x.note)).join(" · ")}</small><i style="--g:${gcol(avg)}">Ø ${avg.toFixed(1).replace(".", ",")}</i></div>`; }).join("") + `</div>`;
      }
      el.innerHTML = h + "</div>";
      el.querySelectorAll("[data-nav]").forEach((b) => b.onclick = () => { view.setMonth(view.getMonth() + +b.dataset.nav); draw(); });
      el.querySelectorAll(".sk-d").forEach((b) => b.onclick = () => { sel = b.dataset.d; draw(); });
      el.querySelectorAll("[data-add]").forEach((b) => b.onclick = () => edit({ art: b.dataset.add, datum: sel, fach: "", text: "" }, true));
      el.querySelectorAll("[data-chk]").forEach((b) => b.onclick = () => { const x = items.find((i) => i.id === b.dataset.chk); if (x) { x.done = !x.done; save(); draw(); } });
      el.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => { items = items.filter((i) => i.id !== b.dataset.del); save(); draw(); });
      el.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => { const x = items.find((i) => i.id === b.dataset.edit); if (x) edit(x, false); });
    }
    function row(x) {
      const a = ART[x.art] || ART.info, d = new Date(x.datum + "T12:00");
      return `<div class="sk-it" style="--h:${a[1]}"><button class="sk-chk${x.done ? " on" : ""}" data-chk="${x.id}" aria-label="erledigt">${x.done ? "✓" : ""}</button>` +
        `<div class="t" data-edit="${x.id}" style="cursor:pointer"><b>${esc(a[0])}${x.fach ? " · " + esc(x.fach) : ""}</b>${x.note ? `<span class="sk-g1" style="--g:${gcol(gnum(x.note))}">${esc(x.note)}</span>` : ""}${x.quelle === "schul.cloud" ? "<i>schul.cloud</i>" : ""}<small>${d.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" })}${x.text ? " – " + esc(x.text) : ""}</small></div>` +
        `<button class="sk-x" data-del="${x.id}" aria-label="löschen">✕</button></div>`;
    }
    function edit(x, isNew) {
      let ed = document.getElementById("sk-ed"); if (!ed) { ed = document.createElement("div"); ed.id = "sk-ed"; ed.className = "sk-ed"; (io.host || document.body).appendChild(ed); }
      const fa = [...new Set([...(io.faecher ? io.faecher() : []), "Mathe", "Deutsch", "Englisch", "Bio", "Chemie", "Physik", "Geschichte", "Erdkunde", "Gemeinschaftskunde"])].filter(Boolean).slice(0, 18);
      let art = x.art, fach = x.fach || "";
      ed.innerHTML = `<div class="sk-box"><div class="sk-tt">${isNew ? "Neu eintragen" : "Bearbeiten"}</div>
        <div class="sk-row">${["arbeit", "test", "ha"].map((a) => `<button class="sk-chip${a === art ? " on" : ""}" data-a="${a}">${ART[a][0]}</button>`).join("")}</div>
        <div class="sk-row">${fa.map((f) => `<button class="sk-chip f${f === fach ? " on" : ""}" data-f="${esc(f)}">${esc(f)}</button>`).join("")}</div>
        <input id="sk-t" placeholder="Was genau? z. B. Seite 42 Nr. 3 · Thema der Arbeit" value="${esc(x.text)}" autocomplete="off">
        <input id="sk-dt" type="date" value="${esc(x.datum)}">
        <input id="sk-note" placeholder="Note (wenn zurück), z. B. 2+ oder 3-" value="${esc(x.note || "")}" autocomplete="off" style="margin-top:8px">
        <div class="sk-btns"><button class="sk-btn" id="sk-no">Abbrechen</button><button class="sk-btn ok" id="sk-ok">Speichern</button></div></div>`;
      ed.classList.add("on");
      ed.querySelectorAll("[data-a]").forEach((b) => b.onclick = () => { art = b.dataset.a; ed.querySelectorAll("[data-a]").forEach((c) => c.classList.toggle("on", c === b)); });
      ed.querySelectorAll("[data-f]").forEach((b) => b.onclick = () => { fach = fach === b.dataset.f ? "" : b.dataset.f; ed.querySelectorAll("[data-f]").forEach((c) => c.classList.toggle("on", c.dataset.f === fach)); });
      const close = () => ed.classList.remove("on");
      ed.onclick = (e) => { if (e.target === ed) close(); };
      document.getElementById("sk-no").onclick = close;
      document.getElementById("sk-ok").onclick = () => {
        const o = isNew ? { id: "s" + Date.now().toString(36), done: false, quelle: "ich", ts: Date.now() } : x;
        Object.assign(o, { art, fach, text: document.getElementById("sk-t").value.trim(), datum: document.getElementById("sk-dt").value || x.datum, note: document.getElementById("sk-note").value.trim().replace(/\s+/g, "") });
        if (isNew) items.push(o);
        sel = o.datum; const d = new Date(o.datum + "T12:00"); view = new Date(d.getFullYear(), d.getMonth(), 1);
        save(); close(); draw();
      };
      setTimeout(() => { try { document.getElementById("sk-t").focus(); } catch (e) {} }, 50);
    }
    reload();
    return { reload };
  }
  window.JSchulKal = { mount };
})();
