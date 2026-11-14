// Statuscheck-Animation (PC-HUD und App): Scan-Ring in der Mitte, die Prüfpunkte laufen einzeln durch
// (Kreisel -> grüner oder roter Punkt), Fortschrittsring füllt sich, am Ende "ALLE SYSTEME BEREIT" bzw. Anzahl Probleme.
//   JCheck.play(items)   items = [{name, ok, detail}] – ohne items nur Show mit Standardpunkten
(function () {
  const css = document.createElement("style");
  css.textContent = `
  #chkfx{position:fixed;inset:0;z-index:150;background:rgba(0,0,0,0);display:flex;align-items:center;justify-content:center;transition:background .4s;font-family:"Segoe UI",system-ui,sans-serif}
  #chkfx.on{background:rgba(0,0,0,.72)}
  #chkfx .pan{width:min(460px,90vw);background:linear-gradient(160deg,rgba(24,17,6,.97),rgba(8,6,3,.97));border:1px solid #8a5c18;border-radius:18px;padding:18px;
    box-shadow:0 0 40px rgba(255,170,40,.25);transform:scale(.85) translateY(20px);opacity:0;transition:transform .45s cubic-bezier(.2,1.3,.3,1),opacity .35s}
  #chkfx.on .pan{transform:none;opacity:1}
  #chkfx .hd{display:flex;align-items:center;gap:14px;margin-bottom:10px}
  #chkfx .ring{position:relative;width:74px;height:74px;flex:0 0 74px}
  #chkfx .ring svg{position:absolute;inset:0;transform:rotate(-90deg)}
  #chkfx .ring .scan{position:absolute;inset:6px;border-radius:50%;background:conic-gradient(rgba(255,214,120,.55),transparent 30%);animation:chkspin 1.1s linear infinite;
    -webkit-mask:radial-gradient(circle,transparent 52%,#000 54%);mask:radial-gradient(circle,transparent 52%,#000 54%)}
  #chkfx .ring b{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#ffd678;font-size:16px;font-weight:600}
  @keyframes chkspin{to{transform:rotate(360deg)}}
  #chkfx .tt small{display:block;font-size:10px;letter-spacing:.26em;color:#ffaa28;font-weight:700}
  #chkfx .tt div{color:#ffd678;font-size:17px;font-weight:600;margin-top:3px}
  #chkfx .rows{max-height:52vh;overflow:hidden}
  #chkfx .r{display:flex;align-items:center;gap:10px;padding:6px 2px;border-bottom:1px solid rgba(255,170,40,.1);opacity:0;transform:translateX(24px);transition:opacity .25s,transform .25s;font-size:13px}
  #chkfx .r.v{opacity:1;transform:none}
  #chkfx .r i{flex:0 0 12px;height:12px;border-radius:50%;border:2px solid rgba(255,214,120,.25);border-top-color:#ffd678;animation:chkspin .7s linear infinite;box-sizing:border-box}
  #chkfx .r.g i{animation:none;border:none;background:#6effcd;box-shadow:0 0 10px #6effcd}
  #chkfx .r.x i{animation:none;border:none;background:#ff6a4a;box-shadow:0 0 10px #ff6a4a}
  #chkfx .r.n i{animation:none;border:none;background:#6a6050}
  #chkfx .r b{flex:1;color:#ffe1b4;font-weight:500}#chkfx .r small{color:#8aa8b8;font-size:11px;text-align:right;max-width:46%}
  #chkfx .r.x small{color:#ff9a7a}
  #chkfx .end{margin-top:12px;text-align:center;font-size:12px;letter-spacing:.2em;color:#6effcd;opacity:0;transition:opacity .4s}
  #chkfx .end.v{opacity:1}#chkfx .end.bad{color:#ffaa28}`;
  document.head.appendChild(css);
  let open = false;
  function play(items) {
    if (items && typeof items.then === "function") {   // Prüfung läuft noch: Scan-Fenster zeigen, dann durchlaufen lassen
      if (open) return; open = true;
      const w = document.createElement("div"); w.id = "chkfx";
      w.innerHTML = `<div class="pan"><div class="hd"><div class="ring"><div class="scan"></div><b>…</b></div><div class="tt"><small>SYSTEMCHECK</small><div>Ich prüfe alle Systeme …</div></div></div></div>`;
      document.body.appendChild(w); requestAnimationFrame(() => w.classList.add("on"));
      items.then((l) => { w.remove(); open = false; play(l || []); }, () => { w.remove(); open = false; play([]); });
      return;
    }
    if (open) return; open = true;
    items = (items && items.length ? items : [{ name: "Kern", ok: true }, { name: "Gedächtnis", ok: true }, { name: "Sprache", ok: true }, { name: "Netz", ok: true }]).slice(0, 14);
    const box = document.createElement("div"); box.id = "chkfx";
    const C = 2 * Math.PI * 32;
    box.innerHTML = `<div class="pan"><div class="hd"><div class="ring"><svg viewBox="0 0 74 74"><circle cx="37" cy="37" r="32" fill="none" stroke="rgba(255,170,40,.15)" stroke-width="4"/>
      <circle class="pr" cx="37" cy="37" r="32" fill="none" stroke="#ffd678" stroke-width="4" stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${C}" style="transition:stroke-dashoffset .3s"/></svg>
      <div class="scan"></div><b>0%</b></div><div class="tt"><small>SYSTEMCHECK</small><div>Ich prüfe alle Systeme …</div></div></div><div class="rows"></div><div class="end"></div></div>`;
    document.body.appendChild(box);
    requestAnimationFrame(() => box.classList.add("on"));
    const rows = box.querySelector(".rows"), pr = box.querySelector(".pr"), pct = box.querySelector(".ring b");
    const step = Math.max(180, Math.min(380, 3600 / items.length));
    items.forEach((it, k) => setTimeout(() => {
      const r = document.createElement("div"); r.className = "r"; r.innerHTML = "<i></i><b></b><small>prüfe …</small>";
      r.querySelector("b").textContent = it.name || "?"; rows.appendChild(r); rows.scrollTop = rows.scrollHeight;
      requestAnimationFrame(() => r.classList.add("v"));
      setTimeout(() => {
        r.classList.add(it.ok === true ? "g" : it.ok === false ? "x" : "n");
        r.querySelector("small").textContent = it.ok === false ? (it.detail || "Problem") : (it.detail || (it.ok ? "OK" : "aus"));
        const p = (k + 1) / items.length; pr.style.strokeDashoffset = C * (1 - p); pct.textContent = Math.round(p * 100) + "%";
      }, step * .7);
    }, 300 + k * step));
    const total = 300 + items.length * step + 300;
    setTimeout(() => {
      const bad = items.filter((i) => i.ok === false).length, e = box.querySelector(".end");
      box.querySelector(".scan").style.animation = "none"; box.querySelector(".scan").style.opacity = "0";
      e.textContent = bad ? `${bad} ${bad > 1 ? "SYSTEME BRAUCHEN" : "SYSTEM BRAUCHT"} AUFMERKSAMKEIT` : "ALLE SYSTEME BEREIT";
      if (bad) e.classList.add("bad"); e.classList.add("v");
      box.querySelector(".tt div").textContent = bad ? "Fast alles läuft." : "Alles im grünen Bereich.";
    }, total);
    const close = () => { if (!box.isConnected) return; box.classList.remove("on"); setTimeout(() => { box.remove(); open = false; }, 400); };
    box.addEventListener("click", close);
    setTimeout(close, total + 3800);
  }
  window.JCheck = { play };
  if (!window.Android) try { const es = new EventSource("/events"); es.onmessage = (e) => { try { const m = JSON.parse(e.data); if (m.type === "checkfx") play((m.data || {}).items); } catch (x) {} }; } catch (e) {}
})();
