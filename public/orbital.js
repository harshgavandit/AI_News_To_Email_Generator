"use strict";

/*
 * Informa AI orbital layer: the effects that make the site feel like one instrument.
 *  - Aurora field: a GPU-drawn flow of light behind every page that follows the pointer,
 *    leans with scrolling and brightens when the reader acts (pins, saves, searches).
 *  - Comets: pinning a story sends a particle comet into the Brief Builder.
 *  - Warp-in: arriving from another Informa page plays a short light-speed burst.
 *  - Decoding headlines: page titles resolve out of signal noise once per visit.
 * Everything is decoration. It reads window.informaMotion (ambient.js), stays off for reduced
 * motion, Save-Data, forced colours and print, and never delays content or navigation.
 */
(() => {
  const root = document.documentElement;
  const motion = window.informaMotion || { allowed: () => !matchMedia("(prefers-reduced-motion: reduce)").matches, onChange() {} };
  const saveData = navigator.connection?.saveData === true;
  const forced = matchMedia("(forced-colors: active)").matches;
  const enabled = () => motion.allowed() && !saveData && !forced;
  const dark = () => root.dataset.theme === "dark";

  // ---------- Aurora field ----------
  const VS = "attribute vec2 a; void main(){ gl_Position = vec4(a, 0.0, 1.0); }";
  const FS = `
precision mediump float;
uniform vec2 uRes, uMouse; uniform float uTime, uScroll, uSurge, uDark;
uniform vec3 uA, uB, uC;
float hash(vec2 p) { return fract(sin(dot(p, vec2(41.3, 289.1))) * 43758.5453); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 4; i++) { v += a * noise(p); p = p * 2.03 + vec2(1.7, 9.2); a *= 0.5; }
  return v;
}
void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  float aspect = uRes.x / uRes.y;
  vec2 p = vec2(uv.x * aspect, uv.y) * 1.5 + vec2(0.0, uScroll);
  float t = uTime;
  vec2 q = vec2(fbm(p + vec2(0.0, t * 0.04)), fbm(p + vec2(5.2, 1.3) - t * 0.035));
  vec2 m = (uMouse - uv) * vec2(aspect, 1.0);
  float pull = exp(-dot(m, m) * 7.0);
  vec2 r = vec2(fbm(p + 3.2 * q + vec2(1.7, 9.2) + t * 0.05 + m * pull),
                fbm(p + 3.2 * q + vec2(8.3, 2.8) - t * 0.045));
  float f = fbm(p + 3.0 * r);
  float ribbon = smoothstep(0.0, 1.0, 1.0 - abs(f - 0.55) * 2.2);
  ribbon *= ribbon;
  vec3 color = mix(uA, uB, clamp(q.x * 1.3, 0.0, 1.0));
  color = mix(color, uC, clamp(r.y * r.y * 1.6, 0.0, 1.0));
  float top = 0.45 + 0.55 * smoothstep(0.0, 1.0, uv.y);
  float alpha = (0.04 + 0.30 * ribbon) * top + pull * 0.14 + uSurge * 0.22 * (ribbon + pull);
  alpha *= mix(0.72, 1.0, uDark);
  gl_FragColor = vec4(color, clamp(alpha, 0.0, 0.55));
}`;

  function hex(value, fallback) {
    const match = /^#([0-9a-f]{6})$/i.exec((value || "").trim());
    const code = match ? match[1] : fallback;
    return [0, 2, 4].map((i) => parseInt(code.slice(i, i + 2), 16) / 255);
  }

  const aurora = { surge() {}, ready: false };
  window.informaAurora = aurora;

  function startAurora() {
    if (!enabled() || document.querySelector(".aurora-field")) return;
    const canvas = document.createElement("canvas");
    canvas.className = "aurora-field";
    canvas.setAttribute("aria-hidden", "true");
    let gl = null;
    try { gl = canvas.getContext("webgl", { alpha: true, premultipliedAlpha: false, antialias: false, powerPreference: "low-power" }); } catch { gl = null; }
    if (!gl) return;
    const compile = (type, source) => {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source); gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error("aurora shader");
      return shader;
    };
    const program = gl.createProgram();
    try {
      gl.attachShader(program, compile(gl.VERTEX_SHADER, VS));
      gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FS));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;
    } catch { return; }
    document.body.prepend(canvas);
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const location = gl.getAttribLocation(program, "a");
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location, 2, gl.FLOAT, false, 0, 0);
    // No blending: the shader's colour and alpha go straight to the (unpremultiplied) canvas.
    gl.disable(gl.BLEND);
    const u = (name) => gl.getUniformLocation(program, name);
    const uniforms = Object.fromEntries(["uRes", "uMouse", "uTime", "uScroll", "uSurge", "uDark", "uA", "uB", "uC"].map((n) => [n, u(n)]));

    // A soft background needs only a fraction of the pixels; CSS scales it up smoothly.
    const narrow = matchMedia("(max-width: 760px)").matches;
    const RESOLUTION = narrow ? 0.22 : 0.33;
    const INTERVAL = narrow ? 66 : 33;  // Phones get 15 frames a second to spare the battery.
    let width = 1, height = 1;
    function resize() {
      width = Math.max(1, Math.round(innerWidth * RESOLUTION));
      height = Math.max(1, Math.round(innerHeight * RESOLUTION));
      canvas.width = width; canvas.height = height;
      gl.viewport(0, 0, width, height);
    }
    function colors() {
      const style = getComputedStyle(root);
      const isDark = dark();
      gl.uniform3fv(uniforms.uA, hex(style.getPropertyValue("--aurora-a"), isDark ? "0e4fa8" : "7cc4ff"));
      gl.uniform3fv(uniforms.uB, hex(style.getPropertyValue("--aurora-b"), isDark ? "06b6d4" : "22d3ee"));
      gl.uniform3fv(uniforms.uC, hex(style.getPropertyValue("--aurora-c"), isDark ? "60a5fa" : "2563eb"));
      gl.uniform1f(uniforms.uDark, isDark ? 1 : 0);
    }

    // Pointer and scroll are springs, so the field drifts after the reader rather than snapping.
    const mouse = { x: 0.7, y: 0.75, tx: 0.7, ty: 0.75 };
    let scroll = 0, scrollTarget = 0, surge = 0, frame = 0, last = 0, start = performance.now(), slow = 0;
    addEventListener("pointermove", (event) => {
      mouse.tx = event.clientX / innerWidth; mouse.ty = 1 - event.clientY / innerHeight;
    }, { passive: true });
    addEventListener("scroll", () => { scrollTarget = scrollY / Math.max(1, innerHeight) * 0.35; kick(); }, { passive: true });

    function step(now) {
      frame = 0;
      if (document.hidden || !enabled()) return;
      frame = requestAnimationFrame(step);
      if (now - last < INTERVAL) return;  // About 30 frames a second is plenty for a background.
      const spent = now - last;
      last = now;
      mouse.x += (mouse.tx - mouse.x) * 0.06; mouse.y += (mouse.ty - mouse.y) * 0.06;
      scroll += (scrollTarget - scroll) * 0.08;
      surge *= 0.94;
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform2f(uniforms.uRes, width, height);
      gl.uniform2f(uniforms.uMouse, mouse.x, mouse.y);
      gl.uniform1f(uniforms.uTime, (now - start) / 1000);
      gl.uniform1f(uniforms.uScroll, scroll);
      gl.uniform1f(uniforms.uSurge, surge);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      // A device that cannot keep up keeps a still frame instead of stuttering the page.
      slow = spent > INTERVAL * 2.2 ? slow + 1 : Math.max(0, slow - 1);
      if (slow > 40) { cancelAnimationFrame(frame); frame = 0; canvas.dataset.still = ""; }
    }
    function kick() { if (!frame && !canvas.hasAttribute("data-still") && enabled() && !document.hidden) frame = requestAnimationFrame(step); }

    resize(); colors();
    let resizeTimer = 0;
    addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { resize(); kick(); }, 180); }, { passive: true });
    document.addEventListener("visibilitychange", kick);
    new MutationObserver(colors).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    motion.onChange?.((on) => { if (on) kick(); });
    aurora.surge = (amount = 1) => { surge = Math.min(1.6, surge + amount); kick(); };
    aurora.ready = true;
    kick();
  }

  // ---------- Overlay canvas shared by comets, sparks and the warp-in ----------
  let overlay = null, context = null, effects = [], overlayFrame = 0;
  function ensureOverlay() {
    if (overlay) return true;
    overlay = document.createElement("canvas");
    overlay.className = "orbital-overlay";
    overlay.setAttribute("aria-hidden", "true");
    context = overlay.getContext("2d");
    if (!context) { overlay = null; return false; }
    document.body.append(overlay);
    sizeOverlay();
    addEventListener("resize", sizeOverlay, { passive: true });
    return true;
  }
  function sizeOverlay() {
    if (!overlay) return;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    overlay.width = Math.round(innerWidth * dpr); overlay.height = Math.round(innerHeight * dpr);
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function play(effect) {
    if (!ensureOverlay()) return;
    effects.push(effect);
    if (!overlayFrame) overlayFrame = requestAnimationFrame(render);
  }
  function render(now) {
    overlayFrame = 0;
    context.clearRect(0, 0, innerWidth, innerHeight);
    effects = effects.filter((effect) => effect.draw(context, now) !== false);
    if (effects.length) overlayFrame = requestAnimationFrame(render);
  }

  const ink = () => dark() ? { core: "255,255,255", glow: "103,232,249", tail: "56,189,248" } : { core: "255,255,255", glow: "34,211,238", tail: "14,99,190" };

  // Sparks: small particles with velocity, drag and a little gravity.
  function sparks(x, y, count = 18, power = 3.2) {
    const colors = ink();
    const list = Array.from({ length: count }, () => {
      const angle = Math.random() * Math.PI * 2, speed = power * (0.4 + Math.random());
      return { x, y, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed - 1, life: 1, size: 1 + Math.random() * 2 };
    });
    play({ draw(ctx) {
      let alive = false;
      for (const s of list) {
        if (s.life <= 0) continue;
        alive = true;
        s.vx *= 0.92; s.vy = s.vy * 0.92 + 0.08; s.x += s.vx; s.y += s.vy; s.life -= 0.028;
        ctx.fillStyle = `rgba(${colors.glow}, ${Math.max(0, s.life)})`;
        ctx.beginPath(); ctx.arc(s.x, s.y, s.size * s.life + 0.3, 0, Math.PI * 2); ctx.fill();
      }
      return alive;
    } });
  }

  // A comet on a quadratic arc from a story to the Brief Builder, with a fading tail.
  function comet(from, to, onArrive) {
    const colors = ink();
    const start = performance.now(), duration = 760;
    const lift = Math.min(260, Math.hypot(to.x - from.x, to.y - from.y) * 0.35);
    // Arc upward, but never above the top of the screen where the comet would vanish.
    const control = { x: (from.x + to.x) / 2 + (to.x < from.x ? lift * 0.4 : -lift * 0.4), y: Math.max(24, Math.min(from.y, to.y) - lift) };
    const at = (t) => ({
      x: (1 - t) * (1 - t) * from.x + 2 * (1 - t) * t * control.x + t * t * to.x,
      y: (1 - t) * (1 - t) * from.y + 2 * (1 - t) * t * control.y + t * t * to.y,
    });
    const ease = (t) => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    let arrived = false;
    play({ draw(ctx, now) {
      const raw = Math.min(1, (now - start) / duration), t = ease(raw);
      ctx.save();
      ctx.globalCompositeOperation = dark() ? "lighter" : "source-over";
      for (let k = 22; k >= 0; k--) {
        const tt = Math.max(0, t - k * 0.016), p = at(tt), fade = 1 - k / 22;
        ctx.fillStyle = `rgba(${k ? colors.tail : colors.core}, ${fade * (k ? 0.55 : 1)})`;
        ctx.beginPath(); ctx.arc(p.x, p.y, 1.4 + fade * 5.4, 0, Math.PI * 2); ctx.fill();
      }
      const head = at(t);
      const glow = ctx.createRadialGradient(head.x, head.y, 0, head.x, head.y, 30);
      glow.addColorStop(0, `rgba(${colors.core}, 1)`); glow.addColorStop(0.18, `rgba(${colors.glow}, .9)`); glow.addColorStop(1, `rgba(${colors.glow}, 0)`);
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(head.x, head.y, 30, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
      if (raw >= 1 && !arrived) { arrived = true; onArrive?.(); sparks(to.x, to.y, 26, 3.6); }
      return raw < 1;
    } });
  }

  // The visible place a pinned story lands: the header builder, the mobile bar or the tray.
  function builderTarget() {
    for (const id of ["nav-builder", "mobile-builder", "pinned-build"]) {
      const element = document.getElementById(id);
      if (!element || element.hidden) continue;
      const box = element.getBoundingClientRect();
      if (box.width && box.height && box.bottom > 0 && box.top < innerHeight) return { element, x: box.left + box.width / 2, y: box.top + box.height / 2 };
    }
    return null;
  }

  function absorb(element) {
    element.classList.remove("orbital-absorb");
    void element.offsetWidth;  // Restart the ring animation on repeated pins.
    element.classList.add("orbital-absorb");
    setTimeout(() => element.classList.remove("orbital-absorb"), 900);
  }

  function actions() {
    // Capture phase: read the button's position before the Reading Room re-renders the card.
    document.addEventListener("click", (event) => {
      if (!enabled()) return;
      const button = event.target.closest?.("button");
      if (!button) return;
      const label = (button.textContent || "").trim();
      const box = button.getBoundingClientRect();
      const from = { x: box.left + box.width / 2, y: box.top + box.height / 2 };
      const pinning = (button.matches("[data-pin-id]") && /^Pin\b/.test(label)) || label === "Add to Brief Builder";
      if (pinning) {
        const target = builderTarget();
        if (target) comet(from, target, () => { absorb(target.element); aurora.surge(0.8); });
        else sparks(from.x, from.y);
        return;
      }
      if (button.matches(".save-button") && label === "Save") { sparks(from.x, from.y, 14, 2.6); aurora.surge(0.3); }
    }, true);
    // Searching and asking questions stir the field: the desk is "listening".
    document.addEventListener("submit", () => { if (enabled()) aurora.surge(1); }, true);
  }

  // ---------- Warp-in: a light-speed burst when arriving from another Informa page ----------
  function warpIn() {
    if (!enabled()) return;
    const navigation = performance.getEntriesByType?.("navigation")?.[0];
    let sameSite = false;
    try { sameSite = Boolean(document.referrer) && new URL(document.referrer).origin === location.origin; } catch { sameSite = false; }
    if (!sameSite || (navigation && navigation.type !== "navigate")) return;
    const colors = ink();
    const cx = innerWidth / 2, cy = Math.min(innerHeight * 0.38, 360);
    const streaks = Array.from({ length: 110 }, () => ({
      angle: Math.random() * Math.PI * 2, distance: 20 + Math.random() * 140, speed: 0.7 + Math.random() * 1.4, width: 0.6 + Math.random() * 1.6,
    }));
    const start = performance.now(), duration = 620;
    play({ draw(ctx, now) {
      const t = Math.min(1, (now - start) / duration), fade = 1 - t;
      ctx.save();
      ctx.globalCompositeOperation = dark() ? "lighter" : "source-over";
      for (const s of streaks) {
        const r0 = s.distance + t * t * 900 * s.speed, r1 = r0 + 30 + 260 * t * s.speed;
        ctx.strokeStyle = `rgba(${colors.glow}, ${fade * 0.5})`;
        ctx.lineWidth = s.width;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(s.angle) * r0, cy + Math.sin(s.angle) * r0);
        ctx.lineTo(cx + Math.cos(s.angle) * r1, cy + Math.sin(s.angle) * r1);
        ctx.stroke();
      }
      ctx.restore();
      return t < 1;
    } });
  }

  // ---------- Decoding headlines ----------
  const GLYPHS = "01<>/\\_=+*#%{}[]░▒";
  // Each character resolves at a staggered moment; until then it shows signal noise.
  function decodeFrame(text, progress, random = Math.random) {
    let out = "";
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      const settle = (i / Math.max(1, text.length)) * 0.7 + 0.25;
      out += ch === " " || progress >= settle ? ch : GLYPHS[Math.floor(random() * GLYPHS.length)];
    }
    return out;
  }
  aurora.decodeFrame = decodeFrame;

  function decodeTitles() {
    if (!enabled()) return;
    const key = `informa-decoded:${location.pathname}`;
    try { if (sessionStorage.getItem(key)) return; sessionStorage.setItem(key, "1"); } catch { /* Private mode: decode anyway. */ }
    const titles = document.querySelectorAll("#hero-title, .curiosity-hero h1, .directory-intro h1, .information-hero h1, .contribute-hero h1");
    for (const title of titles) {
      if (title.children.length || !title.textContent.trim()) continue;
      const text = title.textContent;
      title.setAttribute("aria-label", text);
      title.dataset.decoding = "";
      const start = performance.now(), duration = 900;
      const tick = (now) => {
        const progress = Math.min(1, (now - start) / duration);
        title.textContent = decodeFrame(text, progress);
        if (progress < 1 && motion.allowed()) requestAnimationFrame(tick);
        else { title.textContent = text; title.removeAttribute("aria-label"); delete title.dataset.decoding; }
      };
      requestAnimationFrame(tick);
    }
  }

  const ready = () => {
    actions();
    decodeTitles();
    warpIn();
    // The field waits for idle time so it never competes with the first stories painting.
    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 400));
    idle(() => startAurora(), { timeout: 1500 });
    motion.onChange?.((on) => { if (on) startAurora(); });
  };
  if (document.body) ready();
  else document.addEventListener("DOMContentLoaded", ready, { once: true });
})();
