// Schritt-für-Schritt-Anleitung direkt in der App (idiotensicher, mit echten Links). window.JAnleitung.open()
(function () {
  const REL = "https://github.com/sky3nb-prog/jarvis-android/releases/latest";
  const SEITE = "https://sky3nb-prog.github.io/jarvis-android/";
  const STEPS = [
    ["Mikrofon & Benachrichtigungen erlauben", "Beim ersten Start fragt Android danach. Ohne Mikrofon hört Vector nicht zu, ohne Benachrichtigungen meldet er sich nicht."],
    ["Konto (optional)", "Unter Einstellungen → Systemstatus → „Dein Konto“ anmelden oder neu anlegen. Damit sind PC und Handy gleich eingerichtet – alles wird vorher mit deinem Passwort verschlüsselt. Geht auch ganz ohne Konto."],
    ["KI-Schlüssel eintragen (kostenlos)", 'Auf <a href="https://console.groq.com/keys" target="_blank" rel="noopener">console.groq.com/keys</a> anmelden → „Create API Key“. Den Schlüssel (beginnt mit <code>gsk_</code>) unter Einstellungen → Allgemein → KI-Schlüssel einfügen. Ohne ihn versteht Vector nur feste Befehle.'],
    ["Wohnort eintragen", "Unter Einstellungen → Zuhause &amp; Orte – für Wetter, Lage und den Weg zur Schule/Arbeit."],
    ["Reden", 'Einfach „<i>Vector</i>“ sagen und dann, was du willst – z. B. „Vector, wie wird das Wetter?“. Das Weckwort kannst du in den Einstellungen ändern.'],
    ["PC dazu holen (optional)", 'Das PC-Programm gibt es auf <a href="' + SEITE + '" target="_blank" rel="noopener">derselben Seite</a>, von der du die App hast. Mit demselben Konto anmelden – PC und Handy finden sich dann von selbst.'],
    ["Updates", "Kommen von selbst (Einstellungen → System → Updates). Du musst nichts tun – nur beim allerersten Mal einmal „Unbekannte Apps installieren“ erlauben."],
    ["Nochmal fragen", "Jederzeit einfach „Vector, wie richte ich dich ein?“ sagen oder tippen – dann kommt diese Anleitung in Kurzform auch gesprochen."],
  ];
  let built = false;
  function build() {
    if (built) return; built = true;
    const css = document.createElement("style");
    css.textContent = `
#janl{position:fixed;inset:0;z-index:10000;display:none;background:rgba(2,3,4,.86);backdrop-filter:blur(3px)}
#janl.on{display:flex;align-items:center;justify-content:center}
#janl .box{width:min(520px,94%);max-height:88vh;overflow-y:auto;background:#07090b;border:1px solid rgba(255,206,120,.25);border-radius:20px;padding:22px 20px 18px;box-shadow:0 20px 70px rgba(0,0,0,.6)}
#janl h2{margin:0 0 2px;font-size:22px;letter-spacing:.14em;color:#ffcf6e}
#janl .sub{color:#a39a88;margin:0 0 18px;font-size:13px}
#janl .st{display:flex;gap:12px;margin:10px 0;padding:12px 14px;border:1px solid rgba(255,206,120,.16);border-radius:14px;background:#0f1317}
#janl .n{flex:none;width:24px;height:24px;border-radius:50%;border:1px solid rgba(255,206,120,.4);display:grid;place-items:center;color:#ffcf6e;font-size:12px;font-weight:700}
#janl b{color:#fff}#janl a{color:#7fd4ff}#janl code{background:#1a1f24;padding:1px 6px;border-radius:5px}
#janl .tt{color:#efe7d6;font-weight:600;margin-bottom:3px}
#janl .dd{color:#a39a88;font-size:13px;line-height:1.5}
#janl .close{margin-top:14px;width:100%;padding:12px;border-radius:12px;border:1px solid rgba(255,206,120,.3);background:#ffcf6e;color:#1a1006;font-weight:700;font-size:14px}`;
    document.head.appendChild(css);
    const ov = document.createElement("div"); ov.id = "janl";
    ov.innerHTML = `<div class="box"><h2>VECTOR EINRICHTEN</h2><div class="sub">In ein paar Minuten fertig – Schritt für Schritt.</div>`
      + STEPS.map((s, i) => `<div class="st"><div class="n">${i + 1}</div><div><div class="tt">${s[0]}</div><div class="dd">${s[1]}</div></div></div>`).join("")
      + `<button class="close" id="janl-close">Fertig</button></div>`;
    document.body.appendChild(ov);
    ov.addEventListener("click", (e) => { if (e.target === ov) ov.classList.remove("on"); });
    ov.querySelector("#janl-close").addEventListener("click", () => ov.classList.remove("on"));
  }
  function open() { build(); document.getElementById("janl").classList.add("on"); }
  window.JAnleitung = { open };
})();
