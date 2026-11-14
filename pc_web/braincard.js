// Gelernte Symbole in der Kugel antippen: das Symbol fliegt heraus und öffnet sich als Karte.
//  - Kernerinnerung: Text ansehen und bearbeiten, "Zurück in die Kugel" (speichert), "Vergessen"
//  - Skill/Fähigkeit: ansehen, "Zurück in die Kugel", "Rausnehmen" (er lernt ihn beim nächsten Mal neu)
// Läuft in der App (window.Android) und am PC (/api/...). Braucht brain.js (JarvisBrain).
(function () {
  const A = window.Android || null;
  const css = document.createElement("style");
  css.textContent = `
  #bcard-bg{position:fixed;inset:0;z-index:95;background:rgba(0,0,0,0);backdrop-filter:blur(0);transition:background .45s,backdrop-filter .45s;pointer-events:none}
  #bcard-bg.on{background:rgba(0,0,0,.55);backdrop-filter:blur(3px);pointer-events:auto}
  .bc-fly{position:fixed;z-index:97;width:64px;height:72px;transform:translate(-50%,-50%) scale(.2);display:flex;align-items:center;justify-content:center;
    clip-path:polygon(50% 0,100% 25%,100% 75%,50% 100%,0 75%,0 25%);background:radial-gradient(circle at 50% 40%,#fff3c8,#ffd678 30%,#c8861e 70%,#5a3a0c);
    filter:drop-shadow(0 0 16px rgba(255,190,90,.9));transition:left .55s cubic-bezier(.2,.9,.3,1),top .55s cubic-bezier(.2,.9,.3,1),transform .55s cubic-bezier(.2,1.4,.4,1),opacity .4s}
  .bc-card{position:fixed;z-index:96;left:50%;top:50%;width:min(420px,88vw);transform:translate(-50%,-40%) scale(.6);opacity:0;
    background:linear-gradient(160deg,rgba(26,18,6,.97),rgba(10,7,3,.97));border:1px solid #8a5c18;border-radius:18px;padding:52px 18px 16px;
    box-shadow:0 0 40px rgba(255,170,40,.28);transition:transform .5s cubic-bezier(.2,1.2,.3,1),opacity .4s;font-family:inherit;color:#ffe1b4}
  .bc-card.on{transform:translate(-50%,-50%) scale(1);opacity:1}
  .bc-card small{display:block;text-align:center;font-size:10px;letter-spacing:.24em;color:#ffaa28;font-weight:700}
  .bc-card h4{margin:4px 0 10px;text-align:center;color:#ffd678;font-size:17px;font-weight:600}
  .bc-card textarea{width:100%;box-sizing:border-box;min-height:84px;background:rgba(0,0,0,.35);border:1px solid #5a3e14;border-radius:12px;color:#ffe1b4;
    font-family:inherit;font-size:14px;line-height:1.4;padding:10px;resize:vertical;outline:none}
  .bc-card textarea:focus{border-color:#ffaa28;box-shadow:0 0 10px rgba(255,170,40,.3)}
  .bc-card .meta{font-size:11px;color:#a07a44;margin:6px 2px 0}
  .bc-card .btns{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}
  .bc-card .btns div{flex:1;min-width:110px;text-align:center;padding:10px 8px;border-radius:12px;border:1px solid #8a5c18;color:#ffd678;cursor:pointer;font-size:13px;user-select:none}
  .bc-card .btns .go{background:linear-gradient(180deg,#5a3a0c,#3a2406);border-color:#ffaa28}
  .bc-card .btns .del{border-color:#7a2a1a;color:#ff9a7a}
  .bc-card .x{position:absolute;right:12px;top:10px;color:#8a6a3a;font-size:18px;cursor:pointer}`;
  document.head.appendChild(css);

  let open = null;
  function hexIcon(kind) {
    const ic = document.createElement("canvas"); ic.width = ic.height = 120; ic.style.width = ic.style.height = "40px";
    const g = ic.getContext("2d"); g.translate(60, 60); g.strokeStyle = g.fillStyle = "#3a2204";
    if (window.JarvisBrain) JarvisBrain.drawIcon(g, kind || "wissen", 74);
    return ic;
  }
  async function api(name, body) {
    if (A) {
      if (name === "edit" && A.factEdit) return A.factEdit(body.old || "", body.text || "");
      if (name === "forget" && A.factForget) return A.factForget(body.old || "");
      return "";
    }
    try { const r = await fetch("/api/fact_" + name, { method: "POST", body: JSON.stringify(body) }); return (await r.json()).text || ""; } catch (e) { return ""; }
  }

  function show(i, from) {
    const B = window.JarvisBrain; const sk = B && B.learned[i]; if (!sk || open) return;
    const isSkill = sk.type === "skill" || sk.kind === "funktion";
    const full = sk.text || sk.title || "";
    const bg = document.createElement("div"); bg.id = "bcard-bg";
    const fly = document.createElement("div"); fly.className = "bc-fly"; fly.appendChild(hexIcon(sk.kind));
    fly.style.left = from.x + "px"; fly.style.top = from.y + "px";
    const card = document.createElement("div"); card.className = "bc-card";
    const when = sk.ts ? new Date(sk.ts).toLocaleDateString("de-DE", { day: "numeric", month: "long" }) : "";
    card.innerHTML = `<div class="x">✕</div><small>${isSkill ? "SKILL · FÄHIGKEIT" : "KERNERINNERUNG"}</small><h4></h4>
      <textarea ${isSkill ? "readonly" : ""}></textarea><div class="meta">${when ? (isSkill ? "Gelernt am " : "Gemerkt am ") + when : ""}${isSkill ? "" : " · Text antippen zum Bearbeiten"}</div>
      <div class="btns"><div class="go">◉ Zurück in die Kugel</div><div class="del">${isSkill ? "Rausnehmen (neu lernen)" : "Vergessen"}</div></div>`;
    card.querySelector("h4").textContent = isSkill ? (sk.title || "Fähigkeit") : (sk.title && sk.title !== "Gelernt" ? sk.title : "Über dich");
    card.querySelector("textarea").value = full;
    document.body.append(bg, card, fly);
    B.hide(i, true);   // während die Karte offen ist, fehlt das Symbol in der Kugel
    open = { i, bg, card, fly, from };
    requestAnimationFrame(() => {
      bg.classList.add("on");
      const r = card.getBoundingClientRect();
      fly.style.left = innerWidth / 2 + "px"; fly.style.top = (innerHeight / 2 - Math.min(innerHeight * .5, 300) / 2 - 10) + "px";
      fly.style.transform = "translate(-50%,-50%) scale(1)";
      setTimeout(() => card.classList.add("on"), 120);
    });
    const close = async (mode) => {
      if (!open) return;
      const o = open; open = null;
      const txt = card.querySelector("textarea").value.trim();
      card.classList.remove("on"); bg.classList.remove("on");
      if (mode === "back") {
        if (!isSkill && txt && txt !== full) { B.update(i, { text: txt, title: "Über dich" }); api("edit", { old: full, text: txt }); }
        const t = B.skillPos(i) || from;   // zurück an seinen Platz fliegen
        fly.style.left = t.x + "px"; fly.style.top = t.y + "px"; fly.style.transform = "translate(-50%,-50%) scale(.22)"; fly.style.opacity = ".7";
        setTimeout(() => { B.hide(i, false); B.update(i, { flash: performance.now() + 2200 }); }, 520);
      } else {   // vergessen / rausnehmen: Symbol löst sich auf
        fly.style.transform = "translate(-50%,-50%) scale(1.8)"; fly.style.opacity = "0";
        if (!isSkill) api("forget", { old: full });
        else try {   // beim nächsten App-/PC-Start wieder einfliegen lassen
          const seen = JSON.parse(localStorage.getItem("skills_seen") || "[]").filter((t) => t !== sk.title);
          localStorage.setItem("skills_seen", JSON.stringify(seen)); localStorage.removeItem("neu_seen");
        } catch (e) {}
        setTimeout(() => B.removeSkill(i), 300);
      }
      setTimeout(() => { bg.remove(); card.remove(); fly.remove(); }, 650);
    };
    card.querySelector(".go").onclick = () => close("back");
    card.querySelector(".del").onclick = () => close("del");
    card.querySelector(".x").onclick = () => close("back");
    bg.onclick = () => close("back");
  }

  // Antippen in der Kugel abfangen (vor dem "Gespräch starten"), nur wenn ein Symbol getroffen ist
  function onTap(e) {
    if (open || !window.JarvisBrain) return;
    const p = e.touches ? e.touches[0] : e;
    const i = JarvisBrain.hit(p.clientX, p.clientY, document.body.classList.contains("clean") ? 34 : 26);
    if (i < 0) return;
    e.stopPropagation(); e.preventDefault();
    show(i, { x: p.clientX, y: p.clientY });
  }
  document.addEventListener("click", onTap, true);
  // Kernerinnerungen aus dem Gedächtnis in die Kugel holen (damit es dort immer etwas zum Antippen gibt)
  setTimeout(async () => {
    try {
      let f = [];
      if (A && A.coreFacts) f = JSON.parse(A.coreFacts() || "[]");
      else if (!A) f = (await (await fetch("/api/core")).json()).facts || [];
      const g = (window.JSkill && JSkill.guess) || (() => "wissen");
      if (window.JarvisBrain) JarvisBrain.ensure(f.slice(-16).map((t) => ({ text: t, kind: g(t), title: "Über dich" })));
    } catch (e) {}
  }, 1500);
  window.JBrainCard = { show };
})();
