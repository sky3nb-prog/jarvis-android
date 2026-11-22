// Download: immer die neueste Version (direkt von den fertigen Builds), mit Datum und Größe
(function () {
  const REL = "https://api.github.com/repos/sky3nb-prog/jarvis-android/releases/tags/konto-neueste";
  const fmt = (d) => new Date(d).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  const mb = (b) => (b / 1048576).toFixed(0) + " MB";
  fetch(REL, { headers: { Accept: "application/vnd.github+json" } }).then((r) => r.json()).then((rel) => {
    const a = {}; (rel.assets || []).forEach((x) => { a[x.name] = x; });
    const build = /Build (\d+)/.exec(rel.name || "");
    const set = (id, btn, x, label) => {
      const e = document.getElementById(id); if (!e) return;
      if (!x) { e.textContent = "Gerade nicht verfügbar – gleich nochmal versuchen."; return; }
      e.innerHTML = `<b>${label}</b> · Stand ${fmt(x.updated_at)} · ${mb(x.size)}`;
      const b = document.getElementById(btn); if (b) b.href = x.browser_download_url;
    };
    set("ver-apk", "dl-apk", a["Jarvis-Konto.apk"], build ? "Version 0.3." + build[1] : "Neueste Version");
    set("ver-pc", "dl-pc", a["Jarvis-Konto-PC.zip"], "Neueste Version");
    const t = document.getElementById("ver-tag"); if (t && build) t.textContent = "Version 0.3." + build[1] + " · " + fmt(((a["Jarvis-Konto.apk"] || {}).updated_at) || rel.published_at);
  }).catch(() => {
    ["ver-apk", "ver-pc"].forEach((id) => { const e = document.getElementById(id); if (e) e.textContent = "Neueste Version"; });
  });
})();
