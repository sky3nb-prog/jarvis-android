// Echte 3D-Kugel für Jarvis: Leiterbahn-Netz auf mehreren Schalen, innerer Kern, Ringband, dreht sich, wabert und
// atmet mit der Stimme. WebGL mit Leucht-Effekt (Bloom). Gleiche Schnittstelle wie die alte 2D-Kugel:
//   new Sphere3D(canvas, seed);  s.state = "speaking"; s.level = 0..1; s.power = true/false; s.draw(dt)
(function () {
  function rnd(seed) { let s = seed % 2147483647 || 1; return () => (s = (s * 16807) % 2147483647) / 2147483647; }
  const D2R = Math.PI / 180;

  // ---------------- Geometrie --------------------------------------------------------------------------------
  // Jeder Punkt: x,y,z, Drehgeschwindigkeit, Helligkeit, Wabern
  function buildGeometry(seed) {
    const r = rnd(seed * 7919 + 13), V = [];
    const seg = (a, b, spin, br, wob) => { V.push(a[0], a[1], a[2], spin, br, wob, b[0], b[1], b[2], spin, br, wob); };
    const sph = (lat, lon, rad) => {
      const la = lat * D2R, lo = lon * D2R;
      return [Math.cos(la) * Math.sin(lo) * rad, Math.sin(la) * rad, Math.cos(la) * Math.cos(lo) * rad];
    };
    // Leiterbahn: Zufallsweg in 45°-Schritten auf einer Kugelschale, mit kleinen Zickzacks und Abzweigen
    const DIRS = [[0, 1], [1, 1], [1, 0], [1, -1], [0, -1], [-1, -1], [-1, 0], [-1, 1]];
    function trace(lat, lon, rad, steps, stepDeg, latMin, latMax, spin, br, wob, preferLon) {
      let d = preferLon ? (r() < .5 ? 0 : 4) : (r() * 8) | 0;
      const wig = r() < .55 ? stepDeg * (.18 + r() * .2) : 0; let flip = 1;
      let p = sph(lat, lon, rad);
      for (let i = 0; i < steps; i++) {
        const t = r();
        if (t < .18) d = (d + (r() < .5 ? 1 : 7)) % 8;
        else if (t < .26) d = (d + (r() < .5 ? 2 : 6)) % 8;
        if (preferLon && t > .9) d = r() < .5 ? 0 : 4;
        const s = stepDeg * (r() < .25 ? .45 : 1);
        let nl = lat + DIRS[d][0] * s, nlon = lon + DIRS[d][1] * s / Math.max(.35, Math.cos(lat * D2R));
        if (nl > latMax || nl < latMin) { d = (d + 4) % 8; continue; }
        const q = sph(nl, nlon, rad);
        if (wig) {   // feines Zickzack wie bei Leiterbahnen
          flip = -flip; const ml = (lat + nl) / 2 + DIRS[d][1] * wig * flip, mo = (lon + nlon) / 2 - DIRS[d][0] * wig * flip;
          const m = sph(ml, mo, rad); seg(p, m, spin, br, wob); seg(m, q, spin, br, wob);
        } else seg(p, q, spin, br, wob);
        p = q; lat = nl; lon = nlon;
        if (r() < .04 && steps - i > 6) trace(lat, lon, rad, (steps - i) >> 1, stepDeg, latMin, latMax, spin, br * .8, wob, preferLon);
      }
      // kleines Endstück (wie ein Lötpunkt)
      const a = sph(lat + .6, lon, rad), b = sph(lat - .6, lon, rad), c = sph(lat, lon + .6, rad), e = sph(lat, lon - .6, rad);
      seg(a, c, spin, br * 1.3, wob); seg(c, b, spin, br * 1.3, wob); seg(b, e, spin, br * 1.3, wob); seg(e, a, spin, br * 1.3, wob);
    }
    const asinLat = () => Math.asin(r() * 2 - 1) / D2R;
    // 1) Hauptschale – dichtes Netz
    for (let k = 0; k < 520; k++) trace(asinLat() * .9, r() * 360, .9 + r() * .05, 8 + (r() * 26 | 0), 1.4, -78, 78, .22, .55 + r() * .35, 1, false);
    // 2) Zweite, leicht größere Schale, gegenläufig, dünner
    for (let k = 0; k < 160; k++) trace(asinLat(), r() * 360, 1.0 + r() * .03, 6 + (r() * 18 | 0), 1.8, -80, 80, -.12, .35 + r() * .25, 1.4, false);
    // 3) Bruchstückhafte Kappen oben und unten (äußere Bänder)
    for (let k = 0; k < 140; k++) {
      const top = r() < .5, la = (top ? 1 : -1) * (58 + r() * 14);
      trace(la, r() * 360, 1.1 + r() * .06, 10 + (r() * 22 | 0), 1.7, top ? 52 : -76, top ? 76 : -52, .3, .5 + r() * .4, 1.6, true);
    }
    // 4) Innerer Kern: kleine, dichte Kugel, dreht sich schneller
    for (let k = 0; k < 260; k++) trace(asinLat(), r() * 360, .38 + r() * .1, 6 + (r() * 14 | 0), 3.2, -88, 88, .7, .7 + r() * .3, .6, false);
    // Kern-Breitenkreise (konzentrische Ringe)
    for (let k = 0; k < 14; k++) {
      const rad = .3 + k * .018, la = -60 + k * 9;
      let prev = null;
      for (let lo = 0; lo <= 360; lo += 6) { const q = sph(la, lo, rad); if (prev && r() > .15) seg(prev, q, .9, .55, .5); prev = q; }
    }
    // 5) Äquator-Ringband: viele parallele Linien, leicht gekippt, eigene Drehung
    const tilt = 8 * D2R;
    for (let k = 0; k < 46; k++) {
      const rad = 1.03 + r() * .2, la0 = (r() - .5) * 5, a0 = r() * 360, len = 60 + r() * 280;
      let prev = null;
      for (let a = a0; a < a0 + len; a += 2.5) {
        let [x, y, z] = sph(la0 + Math.sin(a * .2 + k) * .6, a, rad);
        const y2 = y * Math.cos(tilt) - x * Math.sin(tilt), x2 = x * Math.cos(tilt) + y * Math.sin(tilt);
        const q = [x2, y2, z];
        if (prev && r() > .06) seg(prev, q, .45, .7 + r() * .4, 2); prev = q;
      }
    }
    // 6) Diagonaler Lichtstrahl durch den Kern
    const bdir = [Math.sin(-28 * D2R), Math.cos(-28 * D2R), .25];
    for (let k = 0; k < 7; k++) {
      const o = (r() - .5) * .03, len = .75 + r() * .2;
      seg([-bdir[0] * len + o, -bdir[1] * len, -bdir[2] * len], [bdir[0] * len + o, bdir[1] * len + o, bdir[2] * len], .05, 1.6, .2);
    }
    return new Float32Array(V);
  }

  // ---------------- Shader -----------------------------------------------------------------------------------
  const VS_LINES = `
  attribute vec3 aPos; attribute vec3 aP;   // aP: Drehung, Helligkeit, Wabern
  uniform float uT, uLevel, uAspect, uBreath, uTiltX;
  varying float vB;
  // weiches 3D-Rauschen (billig)
  float n3(vec3 p){ return sin(p.x*2.1+uT*1.3)*sin(p.y*2.7-uT*1.1)*sin(p.z*2.3+uT*.9); }
  void main(){
    float a = uT * aP.x;
    vec3 p = aPos;
    p = vec3(p.x*cos(a)+p.z*sin(a), p.y, -p.x*sin(a)+p.z*cos(a));
    float w = n3(p*1.7) * (0.035 + uLevel*0.09) * aP.z;            // Wabern
    w += sin(length(aPos)*14.0 - uT*3.0) * 0.012 * aP.z;              // Welle, die nach außen läuft
    p *= (1.0 + w) * uBreath;
    float c = cos(uTiltX), s = sin(uTiltX);
    p = vec3(p.x, p.y*c - p.z*s, p.y*s + p.z*c);
    float zc = 3.2 - p.z;                                              // Kamera
    gl_Position = vec4(p.x*1.88/zc/uAspect, p.y*1.88/zc, 0.0, 1.0);
    float depth = clamp((p.z + 1.25) / 2.5, 0.0, 1.0);
    vB = aP.y * (0.12 + 0.88*pow(depth, 1.6));
  }`;
  const FS_LINES = `precision mediump float; varying float vB; uniform vec3 uCol;
  void main(){ gl_FragColor = vec4(uCol * vB, 1.0); }`;
  const VS_QUAD = `attribute vec2 aQ; varying vec2 vUv; void main(){ vUv = aQ*.5+.5; gl_Position = vec4(aQ,0.,1.); }`;
  const FS_COPY = `precision mediump float; varying vec2 vUv; uniform sampler2D uTex; uniform vec2 uPx;
  void main(){ vec4 c = texture2D(uTex,vUv+uPx*vec2(-1.,-1.))+texture2D(uTex,vUv+uPx*vec2(1.,-1.))+texture2D(uTex,vUv+uPx*vec2(-1.,1.))+texture2D(uTex,vUv+uPx*vec2(1.,1.)); gl_FragColor = c*.25; }`;
  const FS_BLUR = `precision mediump float; varying vec2 vUv; uniform sampler2D uTex; uniform vec2 uDir;
  void main(){ vec4 c = texture2D(uTex,vUv)*.227;
    c += (texture2D(uTex,vUv+uDir*1.38)+texture2D(uTex,vUv-uDir*1.38))*.316;
    c += (texture2D(uTex,vUv+uDir*3.23)+texture2D(uTex,vUv-uDir*3.23))*.070; gl_FragColor = c; }`;
  const FS_COMP = `precision mediump float; varying vec2 vUv; uniform sampler2D uBase, uBloom; uniform float uAspect, uCore, uT;
  uniform vec3 uCol, uHot;
  void main(){
    vec3 c = texture2D(uBase,vUv).rgb + texture2D(uBloom,vUv).rgb*1.7;
    vec2 d = (vUv-.5)*vec2(uAspect,1.);
    float r = length(d);
    float core = exp(-r*r*55.0) * uCore + exp(-r*r*9.0) * uCore * .22;          // leuchtender Kern
    float halo = exp(-r*r*3.2) * .10 * uCore;
    c += uHot * core + uCol * halo;
    c = 1.0 - exp(-c*1.25);                                                      // weiches Abregeln
    float a = clamp(max(c.r, max(c.g, c.b)) * 1.2, 0.0, 1.0);
    gl_FragColor = vec4(c, a);
  }`;

  function sh(gl, type, src) { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; }
  function prog(gl, vs, fs) { const p = gl.createProgram(); gl.attachShader(p, sh(gl, gl.VERTEX_SHADER, vs));
    gl.attachShader(p, sh(gl, gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    const u = {}; const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < n; i++) { const nm = gl.getActiveUniform(p, i).name; u[nm] = gl.getUniformLocation(p, nm); }
    return { p, u }; }
  function fbo(gl, w, h) { const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    [gl.TEXTURE_MIN_FILTER, gl.TEXTURE_MAG_FILTER].forEach((k) => gl.texParameteri(gl.TEXTURE_2D, k, gl.LINEAR));
    [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T].forEach((k) => gl.texParameteri(gl.TEXTURE_2D, k, gl.CLAMP_TO_EDGE));
    const f = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, f);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, t, 0); return { f, t, w, h }; }

  const mix = (a, b, k) => a.map((v, i) => v + (b[i] - v) * k);
  const GOLD = [1.0, 0.5, 0.14], HOT = [1.0, 0.84, 0.58], GREY = [0.55, 0.57, 0.62], GREY_HOT = [0.7, 0.72, 0.76];

  class Sphere3D {
    constructor(canvas, seed) {
      this.c = canvas; this.t = Math.random() * 20; this.level = 0; this.state = "idle"; this.power = true;
      this.pw = 1; this.speed = 1;
      const gl = canvas.getContext("webgl", { alpha: true, premultipliedAlpha: false, antialias: true });
      if (!gl) throw new Error("kein WebGL");
      this.gl = gl;
      this.pl = prog(gl, VS_LINES, FS_LINES); this.pc = prog(gl, VS_QUAD, FS_COPY);
      this.pb = prog(gl, VS_QUAD, FS_BLUR); this.pk = prog(gl, VS_QUAD, FS_COMP);
      const geo = buildGeometry(seed || 3); this.n = geo.length / 6;
      this.vb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, this.vb); gl.bufferData(gl.ARRAY_BUFFER, geo, gl.STATIC_DRAW);
      this.qb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, this.qb);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      this.W = 0;
    }
    resize() {
      const dpr = Math.min(2.5, window.devicePixelRatio || 1);
      const w = Math.round(this.c.clientWidth * dpr), h = Math.round(this.c.clientHeight * dpr);
      if (!w || !h) return false;
      if (w !== this.W || h !== this.H) {
        this.c.width = this.W = w; this.c.height = this.H = h; const gl = this.gl;
        this.fA = fbo(gl, w, h);
        const bw = Math.max(1, w >> 2), bh = Math.max(1, h >> 2);
        this.fB = fbo(gl, bw, bh); this.fC = fbo(gl, bw, bh);
      }
      return true;
    }
    quad(P) { const gl = this.gl, l = gl.getAttribLocation(P.p, "aQ");
      gl.bindBuffer(gl.ARRAY_BUFFER, this.qb); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, 2, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); gl.disableVertexAttribArray(l); }
    draw(dt) {
      if (!this.resize()) return;
      const gl = this.gl, W = this.W, H = this.H, asp = W / H;
      // Zustand weich überblenden
      this.pw += ((this.power ? 1 : 0) - this.pw) * Math.min(1, dt * 3);
      const tgt = !this.power ? .25 : this.state === "speaking" ? 2.0 : this.state === "listening" ? 1.5 : this.state === "thinking" ? 2.6 : 1;
      this.speed += (tgt - this.speed) * Math.min(1, dt * 2);
      this.t += dt * this.speed;
      const lv = this.level * this.pw;
      const breath = (1 + .03 * Math.sin(this.t * 1.5) + lv * .08) * (.92 + .08 * this.pw);
      const col = mix(GREY, GOLD, this.pw), hot = mix(GREY_HOT, HOT, this.pw);
      const bright = .62 + .38 * this.pw;

      // 1) Linien in Textur A
      gl.bindFramebuffer(gl.FRAMEBUFFER, this.fA.f); gl.viewport(0, 0, W, H);
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE);
      const L = this.pl; gl.useProgram(L.p);
      gl.uniform1f(L.u.uT, this.t); gl.uniform1f(L.u.uLevel, lv); gl.uniform1f(L.u.uAspect, asp);
      gl.uniform1f(L.u.uBreath, breath); gl.uniform1f(L.u.uTiltX, .32 + .08 * Math.sin(this.t * .37));
      gl.uniform3fv(L.u.uCol, col.map((v) => v * bright * (.85 + lv * .5)));
      gl.bindBuffer(gl.ARRAY_BUFFER, this.vb);
      const a0 = gl.getAttribLocation(L.p, "aPos"), a1 = gl.getAttribLocation(L.p, "aP");
      gl.enableVertexAttribArray(a0); gl.enableVertexAttribArray(a1);
      gl.vertexAttribPointer(a0, 3, gl.FLOAT, false, 24, 0); gl.vertexAttribPointer(a1, 3, gl.FLOAT, false, 24, 12);
      gl.drawArrays(gl.LINES, 0, this.n);
      gl.disableVertexAttribArray(a0); gl.disableVertexAttribArray(a1);
      gl.disable(gl.BLEND);

      // 2) Verkleinern + weichzeichnen (Leuchten)
      gl.useProgram(this.pc.p); gl.bindFramebuffer(gl.FRAMEBUFFER, this.fB.f); gl.viewport(0, 0, this.fB.w, this.fB.h);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.fA.t);
      gl.uniform1i(this.pc.u.uTex, 0); gl.uniform2f(this.pc.u.uPx, 1.5 / W, 1.5 / H); this.quad(this.pc);
      gl.useProgram(this.pb.p); gl.uniform1i(this.pb.u.uTex, 0);
      for (let i = 0; i < 2; i++) {
        gl.bindFramebuffer(gl.FRAMEBUFFER, this.fC.f); gl.bindTexture(gl.TEXTURE_2D, this.fB.t);
        gl.uniform2f(this.pb.u.uDir, (1 + i) / this.fB.w, 0); this.quad(this.pb);
        gl.bindFramebuffer(gl.FRAMEBUFFER, this.fB.f); gl.bindTexture(gl.TEXTURE_2D, this.fC.t);
        gl.uniform2f(this.pb.u.uDir, 0, (1 + i) / this.fB.h); this.quad(this.pb);
      }

      // 3) Zusammensetzen auf den Bildschirm
      gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.viewport(0, 0, W, H);
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      const K = this.pk; gl.useProgram(K.p);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.fA.t); gl.uniform1i(K.u.uBase, 0);
      gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, this.fB.t); gl.uniform1i(K.u.uBloom, 1);
      gl.uniform1f(K.u.uAspect, asp); gl.uniform1f(K.u.uT, this.t);
      const pulse = .55 + .12 * Math.sin(this.t * 2.2) + lv * .8;
      gl.uniform1f(K.u.uCore, pulse * (.15 + .85 * this.pw));
      gl.uniform3fv(K.u.uCol, col); gl.uniform3fv(K.u.uHot, hot);
      this.quad(K);
      gl.activeTexture(gl.TEXTURE0);
    }
  }
  window.Sphere3D = Sphere3D;
})();
