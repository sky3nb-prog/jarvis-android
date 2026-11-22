// Unsere Kugel – dieselbe wie in der App und am PC. Ohne WebGL bleibt die einfache leuchtende Kugel.
(function () {
  const box = document.getElementById("kugel"), cv = document.getElementById("kugel-c");
  let s = null;
  try { s = new Sphere3D(cv, 3); box.classList.add("gl"); } catch (e) { return; }
  const still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let last = performance.now(), talk = 0, next = 2.5, hover = false;
  box.addEventListener("mouseenter", () => { hover = true; });
  box.addEventListener("mouseleave", () => { hover = false; });
  box.addEventListener("click", () => { talk = 2.2; });
  function frame(now) {
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    next -= dt; if (next <= 0) { talk = 1.6 + Math.random(); next = 7 + Math.random() * 6; }   // ab und zu „spricht“ er kurz
    talk = Math.max(0, talk - dt);
    s.state = talk > 0 ? "speaking" : hover ? "listening" : "idle";
    s.level = talk > 0 ? 0.35 + 0.35 * Math.abs(Math.sin(now / 90)) : 0;
    s.draw(still ? dt * 0.3 : dt);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
