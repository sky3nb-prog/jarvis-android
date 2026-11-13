// Brücke zum PC-Jarvis (statt der Android-Brücke am Handy): Fragen per /api, Ereignisse per /events.
(function () {
  function get(name, q) {
    try { const x = new XMLHttpRequest(); x.open("GET", "/api/" + name + (q ? "?" + new URLSearchParams(q) : ""), false); x.send();
      return x.status === 200 ? x.responseText : "null"; } catch (e) { return "null"; }
  }
  function post(name, body) { return fetch("/api/" + name, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }).catch(() => {}); }
  window.PC = { get: (n, q) => { try { return JSON.parse(get(n, q)); } catch (e) { return null; } }, post };
  window.Android = {
    lageFavorites: () => get("favorites"),
    city: () => { try { return JSON.parse(get("city")); } catch (e) { return "Leonberg"; } },
    home: () => get("home"),
    here: () => "null",
    tle: () => { try { return JSON.parse(get("tle")).text || ""; } catch (e) { return ""; } },
    geocode: (q) => get("geocode", { q }),
    lageNote: (k, t) => post("note", { kind: k, text: t }),
    getLage: (place, force) => post("getLage", { place, force }),
    hasGroqKey: () => true,
  };
})();
