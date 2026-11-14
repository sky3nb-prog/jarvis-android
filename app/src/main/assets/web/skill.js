// "Neuer Skill freigeschaltet": wenn Jarvis etwas Neues lernt (merkt sich etwas über dich) oder nach einem Update neue
// Fähigkeiten hat, ploppt in seiner Kugel ein goldenes Sechseck mit Symbol auf, darunter eine Karte – dann fliegt es in die Kugel.
//   JSkill.show({title, text, kind})   kind: wissen | person | datum | vorliebe | ort | funktion (sonst aus dem Text geraten)
(function () {
  const ICON = { wissen: "🧠", person: "👤", datum: "🎂", vorliebe: "❤️", ort: "📍", funktion: "⚡", musik: "🎵", spiel: "🎮" };
  function guess(t) {
    t = (t || "").toLowerCase();
    if (/geburtstag|jahrestag|termin|am \d/.test(t)) return "datum";
    if (/mag |liebt|lieblings|hasst|mag kein|vorliebe|isst gern|trinkt/.test(t)) return "vorliebe";
    if (/wohnt|stadt|adresse|schule in|arbeitet in/.test(t)) return "ort";
    if (/musik|song|band|spotify|hört/.test(t)) return "musik";
    if (/spielt|zockt|game|ets2|truck/.test(t)) return "spiel";
    if (/heißt|schwester|bruder|mama|papa|opa|oma|freund|freundin|cousin/.test(t)) return "person";
    return "wissen";
  }
  const css = document.createElement("style");
  css.textContent = `
  #skl{position:fixed;inset:0;pointer-events:none;z-index:90}
  #skl .skl-hex{position:absolute;width:86px;height:96px;transform:translate(-50%,-50%) scale(0);display:flex;align-items:center;justify-content:center;
    clip-path:polygon(50% 0,100% 25%,100% 75%,50% 100%,0 75%,0 25%);background:radial-gradient(circle at 50% 40%,#fff3c8,#ffd678 30%,#c8861e 70%,#5a3a0c);
    font-size:38px;filter:drop-shadow(0 0 18px rgba(255,190,90,.9));transition:transform .5s cubic-bezier(.2,1.6,.4,1),opacity .6s}
  #skl .skl-hex.in{transform:translate(-50%,-50%) scale(1)}
  #skl .skl-hex.away{transform:translate(-50%,-50%) scale(.05);opacity:0;transition:transform .7s cubic-bezier(.6,0,.8,.4),opacity .7s}
  #skl .skl-burst{position:absolute;width:20px;height:20px;border-radius:50%;border:2px solid rgba(255,214,120,.9);transform:translate(-50%,-50%) scale(1);opacity:1;
    transition:transform .9s ease-out,opacity .9s ease-out}
  #skl .skl-burst.go{transform:translate(-50%,-50%) scale(14);opacity:0}
  #skl .skl-card{position:absolute;transform:translate(-50%,0) translateY(14px);opacity:0;min-width:240px;max-width:min(420px,86vw);text-align:center;
    background:rgba(12,9,4,.94);border:1px solid #8a5c18;border-radius:16px;padding:10px 16px;box-shadow:0 0 24px rgba(255,170,40,.25);transition:opacity .4s,transform .4s}
  #skl .skl-card.in{opacity:1;transform:translate(-50%,0)}
  #skl .skl-card small{display:block;font-size:10px;letter-spacing:.22em;color:#ffaa28;font-weight:700}
  #skl .skl-card b{display:block;color:#ffd678;font-size:16px;margin-top:3px}
  #skl .skl-card span{display:block;color:#ffe1b4;font-size:13px;margin-top:3px;line-height:1.3}`;
  document.head.appendChild(css);
  const root = document.createElement("div"); root.id = "skl"; document.body.appendChild(root);
  const queue = []; let busy = false;
  function center() {   // Mitte der größten sichtbaren Kugel
    let best = null, area = 0;
    document.querySelectorAll("canvas.sphere").forEach((c) => {
      const r = c.getBoundingClientRect();
      if (r.width < 40 || r.bottom < 0 || r.top > innerHeight || getComputedStyle(c).visibility === "hidden") return;
      let el = c, vis = true; while (el) { if (getComputedStyle(el).display === "none") { vis = false; break; } el = el.parentElement; }
      if (vis && r.width * r.height > area) { area = r.width * r.height; best = r; }
    });
    return best ? { x: best.left + best.width / 2, y: best.top + best.height / 2, r: best.width / 2 } : { x: innerWidth / 2, y: innerHeight * .42, r: 120 };
  }
  function next() {
    if (busy || !queue.length) return;
    busy = true;
    const s = queue.shift(), c = center(), kind = s.kind || guess(s.text);
    const emoji = s.emoji || ICON[kind] || "✦";
    const B = window.JarvisBrain, idx = B && B.addSkill ? B.addSkill({ emoji, title: s.title || s.text || "" }) : -1;
    const burst = document.createElement("div"); burst.className = "skl-burst"; burst.style.left = c.x + "px"; burst.style.top = c.y + "px";
    const hex = document.createElement("div"); hex.className = "skl-hex"; hex.textContent = ICON[kind] || "✦"; hex.style.left = c.x + "px"; hex.style.top = c.y + "px";
    const card = document.createElement("div"); card.className = "skl-card"; card.style.left = c.x + "px"; card.style.top = Math.min(innerHeight - 110, c.y + Math.max(70, c.r * .75)) + "px";
    card.innerHTML = `<small>${kind === "funktion" ? "NEUE FÄHIGKEIT" : "NEUER SKILL FREIGESCHALTET"}</small><b></b><span></span>`;
    card.querySelector("b").textContent = s.title || "Gelernt"; card.querySelector("span").textContent = s.text || "";
    root.append(burst, hex, card);
    requestAnimationFrame(() => { burst.classList.add("go"); hex.classList.add("in"); card.classList.add("in"); });
    // nach dem Aufploppen: in die Kugel fliegen und dort als kleines Symbol bleiben
    setTimeout(() => {
      card.classList.remove("in");
      const t = idx >= 0 ? B.skillPos(idx) : null;
      if (t) {
        hex.style.transition = "left .9s cubic-bezier(.5,0,.3,1), top .9s cubic-bezier(.5,0,.3,1), transform .9s cubic-bezier(.5,0,.3,1), opacity .9s";
        hex.style.left = t.x + "px"; hex.style.top = t.y + "px"; hex.style.transform = "translate(-50%,-50%) scale(.22)"; hex.style.opacity = ".6";
      } else hex.classList.add("away");
    }, 3300);
    setTimeout(() => {
      if (idx >= 0) {
        B.landSkill(idx);
        const t = B.skillPos(idx);
        if (t) { const b2 = document.createElement("div"); b2.className = "skl-burst"; b2.style.left = t.x + "px"; b2.style.top = t.y + "px"; root.appendChild(b2);
          requestAnimationFrame(() => b2.classList.add("go")); setTimeout(() => b2.remove(), 1000); }
        if (s.test) setTimeout(() => B.removeSkill(idx), 9000);   // Test: verschwindet wieder
      }
      burst.remove(); hex.remove(); card.remove(); busy = false; next();
    }, 4250);
  }
  window.JSkill = {
    show(s) { queue.push(s || {}); next(); },
    test() { this.show({ title: "Test-Skill", text: "So sieht es aus, wenn ich etwas Neues lerne.", kind: "wissen", test: true }); },
  };
})();
