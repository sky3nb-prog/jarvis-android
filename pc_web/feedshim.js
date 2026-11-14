// Mitteilungen im PC-HUD: dieselbe Ansicht wie am Handy (feed.js). Die Daten holt der PC vom Handy (/api/feed).
(function () {
  let list = [], items = {};
  async function load() {
    try { const d = await (await fetch("/api/feed")).json(); list = d.list || []; items = d.items || {}; return true; } catch (e) { return false; }
  }
  window.Android = {
    feedList: () => JSON.stringify(list),
    feedGet: (id) => JSON.stringify(items[id] || null),
    feedNow: (kind) => {
      fetch("/api/feed_now?kind=" + encodeURIComponent(kind)).then((r) => r.json()).then(async (d) => {
        await load();
        if (d.id && window.jarvis && window.jarvis.onEvent) window.jarvis.onEvent("feed_open", { id: d.id });
      }).catch(() => {});
    },
    readStart: () => {}, readNext: () => {}, readStop: () => {}, openUrl: (u) => window.open(u, "_blank"),
  };
  window.jarvis = window.jarvis || { onEvent: () => {}, back: () => false };
  window.JFeedPC = { load };
  document.addEventListener("DOMContentLoaded", () => {});
  // Klick auf die Glocke: erst laden, dann öffnen (feed.js hängt seinen Klick selbst an)
  const b = document.getElementById("feedbtn-f");
  if (b) b.addEventListener("click", (e) => {
    if (b.dataset.ready) return;
    e.stopImmediatePropagation(); b.textContent = "…";
    load().then(() => { b.dataset.ready = "1"; b.innerHTML = '🔔<i class="fdot"></i>'; b.click(); setTimeout(() => { delete b.dataset.ready; }, 500); });
  }, true);
})();
