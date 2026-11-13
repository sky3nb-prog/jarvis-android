// Steuern-Seite: Handy-Kacheln und Fernbedienung für den PC (Discord, Musik, Stumm, Sperren, Aus, Wave Link).
// Der PC antwortet über die Kopplung; ntfy.sh erlaubt nur ~250 Nachrichten am Tag, darum fragen wir sparsam.
(function () {
  const $ = (id) => document.getElementById(id);
  const A = window.Android || null;
  let st = null, mix = null, lastAsk = 0;
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function toast(t, ok) { const e = $("toast"); if (!e) return; e.textContent = t; e.classList.toggle("ok", ok !== false); e.style.display = "block"; clearTimeout(toast.j); toast.j = setTimeout(() => (e.style.display = "none"), 3500); }
  const ago = (ts) => { const m = Math.round((Date.now() / 1000 - ts) / 60); return m < 1 ? "gerade eben" : m < 60 ? `vor ${m} Min.` : new Date(ts * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }); };

  // --- Anzeige -------------------------------------------------------------------------------------------
  function show(s) {
    st = s && Object.keys(s).length ? s : st;
    const s2 = st || {};
    const fresh = s2.ts && Date.now() / 1000 - s2.ts < 35 * 60;   // Lebenszeichen kommt alle 30 Minuten
    const online = !!(s2.online && fresh);
    $("pcbar").classList.toggle("off", !online);
    $("pc-head").textContent = online ? "PC ZUHAUSE · ONLINE" : "PC ZUHAUSE · OFFLINE";
    $("pc-sub").textContent = !s2.ts ? (A && A.paired && !A.paired() ? "noch nicht gekoppelt" : "noch keine Antwort vom PC")
      : online ? `an seit ${new Date((s2.boot || s2.since) * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}${s2.wl ? " · Wave Link verbunden" : ""}`
      : `zuletzt gesehen ${ago(s2.ts)}`;
    $("pc-perf").innerHTML = online && s2.cpu != null ? `CPU ${s2.cpu} %<br>${s2.gpu ? `GPU ${s2.gpu.temp} °C` : `RAM ${s2.ram} %`}` : "";
    const p = s2.playing;
    $("pc-title").textContent = p ? p.title : "–";
    $("pc-artist").textContent = p ? [p.artist, p.app].filter(Boolean).join(" · ") : (online ? "nichts läuft" : "–");
    $("pc-pp").textContent = p && p.on ? "⏸" : "▶";
    $("t-discord").querySelector("small").textContent = s2.discord ? (s2.deaf ? "läuft · stumm" : "läuft") : "starten";
    $("t-steam").querySelector("small").textContent = s2.game ? (s2.game.length > 14 ? s2.game.slice(0, 13) + "…" : s2.game) : s2.steam ? "läuft" : "starten";
    $("t-mic").querySelector("small").textContent = s2.mic_muted ? "aus" : "an";
    $("t-mic").classList.toggle("muted", !!s2.mic_muted);
    wave(s2.wl);
    // Info-Seite
    if ($("ipc-st")) {
      $("ipc-st").innerHTML = online ? '<span style="color:var(--green)">● online</span>' : s2.ts ? `offline · ${ago(s2.ts)}` : "–";
      const run = online ? (s2.game || (p ? p.title : "–")) : "–";
      $("ipc-run").textContent = run.length > 16 ? run.slice(0, 15) + "…" : run;
      $("ipc-perf").textContent = online && s2.cpu != null ? `${s2.cpu} %${s2.gpu ? ` · ${s2.gpu.temp}°` : ""}` : "–";
    }
  }

  // Wave-Link-Regler (Mix wählbar, Werte live vom PC)
  let drag = false, again = null;   // während ein Regler gezogen wird, nicht neu aufbauen
  function wave(wl) {
    if (drag) { again = wl; return; }
    const on = !!(wl && wl.channels && wl.channels.length);
    $("wl").style.display = $("wl-head").style.display = on ? "" : "none";
    if (!on) return;
    if (!mix || !wl.mixes.some((m) => m.id === mix)) mix = wl.mine || (wl.mixes[0] || {}).id;
    $("wl-mixes").innerHTML = wl.mixes.map((m) => `<span data-mix="${esc(m.id)}" class="${m.id === mix ? "on" : ""}">${esc(m.name)}</span>`).join("");
    $("wl-mixes").querySelectorAll("span").forEach((e) => e.addEventListener("click", () => { mix = e.dataset.mix; wave(st.wl); }));
    const rows = wl.channels.map((c) => { const m = (c.mixes || {})[mix] || c; return { id: c.id, name: c.name, level: m.level, muted: m.muted, mix: true }; });
    if (wl.mic) rows.push({ id: "mic", name: "Mikro", level: wl.mic.level, muted: wl.mic.muted, icon: "🎙" });
    if (wl.gesamt) rows.push({ id: "gesamt", name: "Gesamt", level: wl.gesamt.level, muted: wl.gesamt.muted, icon: "Σ", total: true });
    const ICON = (n) => /musik|music|deezer|spotify/i.test(n) ? "♪" : /discord|chat/i.test(n) ? "D" : /game|spiel/i.test(n) ? "🎮" : /browser|chrome/i.test(n) ? "◎" : /system/i.test(n) ? "⚙" : "•";
    $("wl").innerHTML = rows.map((r) => `<div class="ch${r.muted ? " muted" : ""}${r.total ? " total" : ""}" data-ch="${esc(r.id)}" data-mixed="${r.mix ? 1 : 0}">
      <span class="ic">${r.icon || ICON(r.name)}</span><span class="nm">${esc(r.name)}</span>
      <input type="range" min="0" max="100" value="${Math.round((r.level || 0) * 100)}"><span class="pc">${r.muted ? "aus" : Math.round((r.level || 0) * 100)}</span>
      <span class="mu">${r.muted ? "🔇" : "🔈"}</span></div>`).join("");
    $("wl").querySelectorAll(".ch").forEach((row) => {
      const inp = row.querySelector("input"), pc = row.querySelector(".pc"), ch = row.dataset.ch, mixed = row.dataset.mixed === "1";
      const paint = () => inp.style.setProperty("--p", inp.value + "%");
      paint();
      inp.addEventListener("pointerdown", () => (drag = true));
      inp.addEventListener("touchstart", (e) => { drag = true; e.stopPropagation(); }, { passive: true });
      inp.addEventListener("input", () => { paint(); pc.textContent = inp.value; });
      const end = () => { if (!drag) return; drag = false; if (again) { const w = again; again = null; setTimeout(() => wave(w), 600); } };
      ["pointerup", "pointercancel", "touchend", "touchcancel"].forEach((t) => inp.addEventListener(t, end));
      inp.addEventListener("change", () => cmd({ type: "wl", ch, mix: mixed ? mix : null, level: inp.value / 100 }, `${row.querySelector(".nm").textContent} auf ${inp.value} %`));
      row.querySelector(".mu").addEventListener("click", () => {
        const m = !row.classList.contains("muted"); row.classList.toggle("muted", m); pc.textContent = m ? "aus" : inp.value;
        cmd({ type: "wl", ch, mix: mixed ? mix : null, mute: m }, `${row.querySelector(".nm").textContent} ${m ? "stumm" : "an"}`);
      });
    });
  }

  // --- Befehle --------------------------------------------------------------------------------------------
  function cmd(c, label) {
    if (!A || !A.pcCmd) { toast("Nur in der App verfügbar."); return; }
    toast((label || "Befehl") + " … wird an den PC geschickt");
    A.pcCmd(JSON.stringify(c));
  }
  document.querySelectorAll("#v-steuern [data-pc]").forEach((e) => e.addEventListener("click", (ev) => {
    ev.stopPropagation();
    let c; try { c = JSON.parse(e.dataset.pc); } catch (x) { return; }
    e.classList.add("busy"); setTimeout(() => e.classList.remove("busy"), 1200);
    cmd(c, (e.textContent || "").trim().split("\n")[0].slice(0, 20));
  }));
  document.querySelectorAll("#v-steuern [data-tile]").forEach((e) => e.addEventListener("click", () => { if (A && A.openTile) A.openTile(e.dataset.tile); }));
  $("t-aus").addEventListener("click", () => $("ask-aus").classList.add("on"));
  $("aus-no").addEventListener("click", () => $("ask-aus").classList.remove("on"));
  $("aus-yes").addEventListener("click", () => { $("ask-aus").classList.remove("on"); cmd({ type: "power", what: "shutdown" }, "Ausschalten"); });
  $("t-text").addEventListener("click", () => { $("ask-text").classList.add("on"); setTimeout(() => $("pc-text").focus(), 100); });
  $("text-no").addEventListener("click", () => $("ask-text").classList.remove("on"));
  $("text-yes").addEventListener("click", () => { const t = $("pc-text").value.trim(); $("ask-text").classList.remove("on"); if (t) { cmd({ type: "text", text: t }, "Befehl"); $("pc-text").value = ""; } });

  window.JSteuern = {
    onReply(r) { if (r.status) show(r.status); toast(r.ok === false ? "✕ " + (r.text || "Ging nicht.") : "✓ PC: " + (r.text || "erledigt"), r.ok !== false); },
    onStatus(s) { show(s && s.unknown ? null : s); },
    // force = PC direkt fragen (kostet 2 Nachrichten, darum höchstens alle 2 Minuten); sonst letztes Lebenszeichen lesen
    refresh(force) {
      if (!A || !A.pcStatus) return;
      const f = force && Date.now() - lastAsk > 120000; if (f) lastAsk = Date.now();
      try { const c = A.pcStatus(!!f); if (c) show(JSON.parse(c)); } catch (e) {}
    },
  };
  try { if (A && A.pcStatus) { const c = A.pcStatus(false); if (c) show(JSON.parse(c)); } } catch (e) {}
})();
