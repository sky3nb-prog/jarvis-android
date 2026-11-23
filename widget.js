// Einbau-Widget für fremde Websites ("Mit Vector anmelden"-Button) - statische Variante ohne Cloud Functions/Blaze.
// Nur der Passwort-Weg, läuft komplett über login.html auf dieser Seite (GitHub Pages).
//
// Einbau beim Freund:
//   <div data-vector-login data-client-id="DEINE_CLIENT_ID"></div>
//   <script src="https://sky3nb-prog.github.io/jarvis-android/widget.js"></script>
//
// Optional: data-redirect-uri="https://deine-seite.de/vector_callback.php" (sonst: aktuelle Seite).
(function () {
  var SELF = document.currentScript || (function () { var s = document.getElementsByTagName("script"); return s[s.length - 1]; })();
  var BASE = SELF.src.replace(/\/widget\.js.*$/, "");

  function el(tag, attrs, children) {
    var e = document.createElement(tag);
    for (var k in (attrs || {})) { if (k === "text") e.textContent = attrs[k]; else e.setAttribute(k, attrs[k]); }
    (children || []).forEach(function (c) { e.appendChild(c); });
    return e;
  }

  function mount(root) {
    var clientId = root.getAttribute("data-client-id");
    if (!clientId) { root.textContent = "Vector-Login: data-client-id fehlt."; return; }
    var redirectUri = root.getAttribute("data-redirect-uri") || window.location.origin + window.location.pathname;
    var state = Math.random().toString(36).slice(2);

    var url = BASE + "/login.html?client_id=" + encodeURIComponent(clientId) +
      "&redirect_uri=" + encodeURIComponent(redirectUri) +
      "&state=" + encodeURIComponent(state);

    var btn = el("a", { href: url, text: "Mit Vector anmelden" }, []);
    btn.style.cssText = "display:inline-flex;align-items:center;font:600 15px system-ui,sans-serif;padding:10px 18px;border-radius:8px;border:0;background:#1D9E75;color:#04342C;cursor:pointer;text-decoration:none";

    var hint = el("p", { text: "QR-/Code-Login kommt bald." }, []);
    hint.style.cssText = "margin:8px 0 0;font:13px system-ui,sans-serif;color:#9c9a92";

    root.appendChild(btn);
    root.appendChild(hint);
  }

  document.querySelectorAll("[data-vector-login]").forEach(mount);
})();
