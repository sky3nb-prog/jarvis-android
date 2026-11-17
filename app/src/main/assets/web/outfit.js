// Abends: „Was hattest du heute an?“ – Teile antippen, dann zu kalt / passt / zu warm. Der Kleiderschrank lernt daraus.
(function () {
  const A = window.Android;
  if (!A || !A.outfitData) return;
  const $ = (id) => document.getElementById(id);
  const css = document.createElement("style");
  css.textContent = `
  #of-ov{position:fixed;inset:0;z-index:8500;background:rgba(2,6,10,.86);display:flex;align-items:flex-end;justify-content:center}
  #of-ov[hidden]{display:none}
  #of-ov .of-sheet{width:100%;max-width:520px;max-height:88vh;overflow:auto;background:linear-gradient(#1a1206,#070b0f 40%);border:1px solid rgba(255,180,60,.45);border-bottom:0;border-radius:24px 24px 0 0;padding:20px 16px 26px;color:#f3e6c8}
  #of-ov h2{margin:0;font-size:13px;letter-spacing:2px;color:#ffd678}
  #of-ov .of-sub{color:#a7987a;font-size:13.5px;margin:6px 0 12px;line-height:1.4}
  #of-ov .of-grp{font-size:10.5px;letter-spacing:1.6px;color:#9a7a3c;margin:12px 2px 6px;font-weight:700}
  #of-ov .of-chips{display:flex;flex-wrap:wrap;gap:8px}
  #of-ov .of-chip{padding:9px 12px;border-radius:999px;border:1px solid #2c3b44;background:#0b1820;font-size:14.5px}
  #of-ov .of-chip.on{border-color:#ffb43c;background:#2a1c06;color:#ffd678}
  #of-ov .of-row{display:flex;gap:8px;margin-top:18px}
  #of-ov .of-btn{flex:1;padding:14px 6px;border-radius:14px;border:1px solid #3a4a55;background:#0d1217;text-align:center;font-weight:700;font-size:15px}
  #of-ov .of-btn.ok{border-color:#6effcd;color:#6effcd}
  #of-ov .of-msg{min-height:18px;margin-top:10px;font-size:13px;color:#6effcd;text-align:center}
  #of-ov .of-x{float:right;color:#7f8b92;font-size:22px;line-height:1;margin:-4px 2px 0 0}`;
  document.head.appendChild(css);
  const ov = document.createElement("div");
  ov.id = "of-ov"; ov.hidden = true;
  ov.innerHTML = `<div class="of-sheet"><span class="of-x" id="of-x">×</span><h2>WAS HATTEST DU HEUTE AN?</h2>
    <div class="of-sub" id="of-sub">Tipp an, was du anhattest – dann ob es gepasst hat.</div><div id="of-list"></div>
    <div class="of-row"><div class="of-btn" data-v="-1">🥶 Zu kalt</div><div class="of-btn ok" data-v="0">👍 Passt</div><div class="of-btn" data-v="1">🥵 Zu warm</div></div>
    <div class="of-msg" id="of-msg"></div></div>`;
  document.body.appendChild(ov);
  const NAMES = { jacke: "JACKE", mitte: "PULLI & CO.", drunter: "DRUNTER", hose: "HOSE", extra: "EXTRAS" };
  let T = null;
  function open() {
    let d = {}; try { d = JSON.parse(A.outfitData()); } catch (e) {}
    T = typeof d.t === "number" ? d.t : null;
    const sel = new Set(d.vorschlag || []);
    $("of-sub").textContent = (T != null ? `Heute draußen gefühlt bis ${Math.round(T)} °. ` : "") + "Tipp an, was du anhattest – dann ob es gepasst hat.";
    const by = {}; (d.items || []).forEach((i) => (by[i.layer] = by[i.layer] || []).push(i));
    $("of-list").innerHTML = ["jacke", "mitte", "drunter", "hose", "extra"].filter((l) => by[l]).map((l) => `<div class="of-grp">${NAMES[l]}</div><div class="of-chips">` +
      by[l].map((i) => `<div class="of-chip${sel.has(i.id) ? " on" : ""}" data-id="${i.id}">${i.icon || ""} ${String(i.name).replace(/</g, "")}</div>`).join("") + "</div>").join("");
    $("of-list").querySelectorAll(".of-chip").forEach((c) => c.onclick = () => c.classList.toggle("on"));
    $("of-msg").textContent = ""; ov.hidden = false;
  }
  ov.querySelectorAll(".of-btn").forEach((b) => b.onclick = () => {
    const ids = [...ov.querySelectorAll(".of-chip.on")].map((c) => c.dataset.id);
    if (!ids.length) { $("of-msg").textContent = "Tipp erst an, was du anhattest."; return; }
    $("of-msg").textContent = A.outfitSave(JSON.stringify(ids), +b.dataset.v, T == null ? NaN : T);
    setTimeout(() => (ov.hidden = true), 1600);
  });
  $("of-x").onclick = () => (ov.hidden = true);
  window.JOutfit = { open };
  const prev = window.jarvis && window.jarvis.onEvent;
  if (window.jarvis) window.jarvis.onEvent = function (type, data) {
    if (type === "outfit_ask") { open(); return; }
    if (type === "outfit_t") {   // Wetter + Vorschlag kommen nach
      const d = typeof data === "string" ? JSON.parse(data) : (data || {});
      if (ov.hidden) return;
      if (typeof d.t === "number") { T = d.t; $("of-sub").textContent = `Heute draußen gefühlt bis ${Math.round(T)} °. Tipp an, was du anhattest – dann ob es gepasst hat.`; }
      const sel = new Set(d.vorschlag || []);
      if (sel.size && !ov.querySelector(".of-chip.on")) ov.querySelectorAll(".of-chip").forEach((c) => c.classList.toggle("on", sel.has(c.dataset.id)));
      return;
    }
    return prev && prev.call(window.jarvis, type, data);
  };
})();
