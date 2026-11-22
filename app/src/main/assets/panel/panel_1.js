const A = window.Panel || { close(){}, talk(){}, open(){}, size(){}, mini(){} };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const N = 15; for (let i = 0; i < N; i++) $("wave").appendChild(document.createElement("i"));
let level = 0, shown = 0, st = "ended", minimized = false, cardOn = false;

// Wellenform: 60 Bilder pro Sekunde, nur "transform" (läuft auf der Grafikkarte)
const bars = [...$("wave").children];
function frame(t) {
  shown += (level - shown) * 0.25;
  if (st === "listening") bars.forEach((b, i) => {
    const k = 0.35 + 0.65 * Math.abs(Math.sin(t / 260 + i * 0.7)) * (0.25 + shown * 1.4);
    b.style.transform = "scaleY(" + (0.6 + k * 4.2).toFixed(3) + ")";
  });
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

function reportSize() {
  const r = $("wrap").getBoundingClientRect();
  A.size(Math.ceil(window.innerHeight - r.top + 2));
}
new ResizeObserver(reportSize).observe($("wrap"));

function setState(s, text) {
  st = s;
  const pw = $("pillwrap");
  pw.classList.remove("hidden", "listen", "busy");
  if (s === "listening") pw.classList.add("listen");
  else if (s === "thinking") { pw.classList.add("busy"); setText(text || "Einen Moment …", true); }
  else if (s === "searching") { pw.classList.add("busy"); setText(text || "Jarvis sucht im Web …", true); }
  else if (s === "speaking") setText("Frag Jarvis", false);
  else setText("Frag Jarvis", false);
  $("micicon").innerHTML = (s === "thinking" || s === "searching")
    ? '<rect x="7" y="7" width="10" height="10" rx="2.5" stroke-width="2.2"/>'
    : '<path d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>';
  setTimeout(reportSize, 20);
}
function setText(t, shim) { const p = $("ptext"); p.textContent = t; p.className = shim ? "shimmer" : ""; }

function minimize() { minimized = true; $("cardbox").classList.add("hidden"); A.mini(true); setTimeout(reportSize, 450); }
function showCard(html) {
  minimized = false; cardOn = true;
  $("content").innerHTML = html;
  $("content").scrollTop = 0;
  $("cardbox").classList.remove("hidden");
  A.mini(false);
  reportSize();
}
function hideAll() { $("cardbox").classList.add("hidden"); $("pillwrap").classList.add("hidden"); cardOn = false; setTimeout(reportSize, 450); }

function openLink(el) { A.open(el.dataset.url || "", el.dataset.app || ""); }
document.addEventListener("click", (e) => { const el = e.target.closest("[data-url]"); if (el) openLink(el); });

// --- Karten -------------------------------------------------------------------------------------
function cardText(d) {
  return '<div class="text fade-in">' + esc(d.text) + "</div>";
}
function cardMusic(d) {
  let h = '<div class="lead fade-in">' + esc(d.say || "") + "</div>";
  if (d.genres && d.genres.length) h += '<div class="chips fade-in">' + d.genres.map((g, i) =>
    '<div class="chip' + (i === 0 ? " on" : "") + '">' + esc(g.name) + (g.pct ? " " + g.pct + " %" : "") + "</div>").join("") + "</div>";
  if (d.top && d.top.length) {
    h += '<div class="sec">DEINE TOP-SONGS GERADE</div>';
    h += d.top.map((s) => '<div class="row fade-in" data-url="' + esc(s.url) + '" data-app="deezer"><div class="cover" style="background-image:url(\'' +
      esc(s.cover) + '\')"></div><div class="meta"><div class="t1">' + esc(s.title) + '</div><div class="t2">' + esc(s.artist) +
      '</div></div><div class="n">' + esc(s.count ? s.count + "×" : "") + "</div></div>").join("");
  }
  if (d.suggest && d.suggest.length) {
    h += '<div class="sec">PASST DAZU – NEU FÜR DICH</div>';
    h += d.suggest.map((s) => '<div class="row fade-in" data-url="' + esc(s.url) + '" data-app="deezer"><div class="cover" style="background-image:url(\'' +
      esc(s.cover) + '\')"></div><div class="meta"><div class="t1">' + esc(s.title) + '</div><div class="t2">' + esc(s.artist) +
      (s.why ? " · " + esc(s.why) : "") + '</div></div><div class="play"></div></div>').join("");
  }
  if (d.play) h += '<div class="btns"><div class="btn gold" data-url="' + esc(d.play.url) + '" data-app="deezer">▶  ' + esc(d.play.label) + "</div></div>";
  return h;
}
function cardYoutube(d) {
  let h = '<div class="lead fade-in">' + esc(d.say || "Neu von den Kanälen, die du gerade viel schaust:") + "</div>";
  h += (d.videos || []).map((v) => '<div class="row fade-in" data-url="' + esc(v.url) + '" data-app="youtube"><div class="thumb" style="background-image:url(\'' +
    esc(v.thumb) + '\')"></div><div class="meta"><div class="t1">' + esc(v.title) + '</div><div class="t2"><b>' + esc(v.channel) +
    '</b></div><div class="t2">' + esc(v.ago || "") + "</div></div></div>").join("");
  if (d.more && d.more.length) h += '<div class="sec">KÖNNTE DIR AUCH GEFALLEN</div><div class="chips">' + d.more.map((c) =>
    '<div class="chip" data-url="' + esc(c.url) + '" data-app="youtube">' + esc(c.name) + "</div>").join("") + "</div>";
  return h;
}
function cardWeb(d) {
  let h = '<div class="text fade-in">' + esc(d.text) + "</div>";
  if (d.sources && d.sources.length) h += '<div class="sec">QUELLEN</div><div class="chips">' + d.sources.map((s) =>
    '<div class="chip src" data-url="' + esc(s.url) + '">' + esc(s.name) + "</div>").join("") + "</div>";
  return h;
}

window.J = {
  ev(type, d) {
    if (type === "screen") { document.documentElement.style.setProperty("--maxh", Math.round(d.h * 0.6) + "px"); reportSize(); }
    else if (type === "state") setState(d.state, d.text);
    else if (type === "level") level = d.value || 0;
    else if (type === "colors") { const r = document.documentElement.style;
      ["--c0", "--c1", "--c2"].forEach((k, i) => d.c[i] && r.setProperty(k, d.c[i])); }
    else if (type === "card") {
      const k = d.kind;
      showCard(k === "music" ? cardMusic(d) : k === "youtube" ? cardYoutube(d) : k === "web" ? cardWeb(d) : cardText(d));
    }
    else if (type === "hide") hideAll();
  },
};
A.ready && A.ready();

// früher onclick im HTML – jetzt hier (strenge Sicherheitsregel: kein Code im HTML)
(function () {
  const on = (id, fn) => { const e = document.getElementById(id); if (e) e.addEventListener("click", fn); };
  on("mini", () => minimize()); on("ib-close", () => A.close()); on("mic", () => A.talk());
})();
