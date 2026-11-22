"use strict";

/*
 * Informa AI ambient layer: a quiet, cursor-aware "signal network" behind every page,
 * a site-wide motion switch, and spring-loaded controls. Progressive enhancement only:
 * pages read and work the same without it, and nothing here touches stories or data.
 */
(() => {
  const root = document.documentElement;
  const KEY = "informa-motion";
  const systemReduce = matchMedia("(prefers-reduced-motion: reduce)");
  const listeners = new Set();
  const read = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
  const stored = read();

  // Motion is on unless the reader's system asks for less or they switched it off here.
  const motion = {
    allowed: () => root.dataset.motion !== "off",
    set(on) {
      root.dataset.motion = on ? "on" : "off";
      try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* Private mode: keep for this page. */ }
      for (const listener of listeners) listener(on);
    },
    onChange(listener) { listeners.add(listener); return () => listeners.delete(listener); },
  };
  root.dataset.motion = stored === "on" || stored === "off" ? stored : systemReduce.matches ? "off" : "on";
  systemReduce.addEventListener?.("change", (event) => { if (!read()) motion.set(!event.matches); });
  window.informaMotion = motion;

  // A header switch pauses every decorative animation on the site (WCAG 2.2.2).
  const tools = document.querySelector(".site-tools");
  if (tools && !document.getElementById("motion-toggle")) {
    const button = document.createElement("button");
    button.id = "motion-toggle";
    button.type = "button";
    button.className = "motion-toggle";
    button.innerHTML = '<svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true" focusable="false"><circle cx="10" cy="10" r="2.2"/><path class="motion-orbit" d="M3.2 10a6.8 3.2 0 1 0 13.6 0a6.8 3.2 0 1 0-13.6 0"/><path class="motion-pause" d="M7.5 6.5v7M12.5 6.5v7"/></svg>';
    const label = () => {
      const on = motion.allowed();
      button.setAttribute("aria-pressed", String(!on));
      button.setAttribute("aria-label", on ? "Pause animations" : "Play animations");
      button.title = on ? "Pause animations" : "Play animations";
    };
    button.addEventListener("click", () => motion.set(!motion.allowed()));
    motion.onChange(label);
    label();
    // Narrow screens float the switch bottom-left; the sticky header would otherwise overflow.
    const narrow = matchMedia("(max-width: 560px)");
    const dock = () => {
      if (narrow.matches) { button.classList.add("is-floating"); document.body.append(button); }
      else { button.classList.remove("is-floating"); tools.prepend(button); }
    };
    narrow.addEventListener?.("change", dock);
    dock();
  }

  const finePointer = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const saveData = navigator.connection?.saveData === true;
  const pointer = { x: -9999, y: -9999, active: false };
  addEventListener("pointermove", (event) => {
    pointer.x = event.clientX; pointer.y = event.clientY; pointer.active = event.pointerType === "mouse";
  }, { passive: true });
  document.addEventListener("pointerleave", () => { pointer.active = false; });

  // ---------- Signal network: nodes on springs that part around the cursor ----------
  function palette() {
    const dark = root.dataset.theme === "dark";
    return dark ? { node: "125, 211, 252", line: "56, 189, 248", alpha: 0.34 } : { node: "11, 58, 120", line: "8, 145, 178", alpha: 0.24 };
  }

  function startField() {
    if (saveData || matchMedia("(forced-colors: active)").matches) return;
    const canvas = document.createElement("canvas");
    canvas.className = "ambient-field";
    canvas.setAttribute("aria-hidden", "true");
    document.body.prepend(canvas);
    const context = canvas.getContext("2d");
    if (!context) { canvas.remove(); return; }
    let width = 0, height = 0, dpr = 1, nodes = [], colors = palette(), frame = 0, last = 0;

    function seed() {
      dpr = 1;  // A soft background needs no high-density backing store.
      width = innerWidth; height = innerHeight;
      canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.round(Math.min(90, Math.max(28, (width * height) / 22000)));
      nodes = Array.from({ length: count }, () => {
        const x = Math.random() * width, y = Math.random() * height;
        return { x, y, hx: x, hy: y, vx: 0, vy: 0, phase: Math.random() * Math.PI * 2, r: 0.8 + Math.random() * 1.6 };
      });
    }

    function step(now) {
      frame = 0;
      if (document.hidden || !motion.allowed()) return;
      frame = requestAnimationFrame(step);
      if (now - last < 33) return;  // About 30 frames a second is plenty for a background.
      const t = now / 1000;
      last = now;
      context.clearRect(0, 0, width, height);
      for (const node of nodes) {
        // Each node drifts around its home and is pushed aside by the cursor, then springs back.
        const tx = node.hx + Math.cos(t * 0.21 + node.phase) * 18, ty = node.hy + Math.sin(t * 0.17 + node.phase) * 14;
        node.vx += (tx - node.x) * 0.012; node.vy += (ty - node.y) * 0.012;
        if (pointer.active) {
          const dx = node.x - pointer.x, dy = node.y - pointer.y, d2 = dx * dx + dy * dy;
          if (d2 < 22500 && d2 > 1) { const f = (22500 - d2) / 22500 * 1.6, d = Math.sqrt(d2); node.vx += dx / d * f; node.vy += dy / d * f; }
        }
        node.vx *= 0.86; node.vy *= 0.86; node.x += node.vx; node.y += node.vy;
      }
      // Lines are batched into a few opacity bands: one stroke per band instead of one per line.
      context.lineWidth = 1;
      const bands = [[], [], [], []];
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j], dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
          if (d2 < 19600) bands[Math.min(3, Math.floor(d2 / 4900))].push(a, b);
        }
      }
      bands.forEach((band, level) => {
        if (!band.length) return;
        context.strokeStyle = `rgba(${colors.line}, ${(1 - (level + 0.5) / 4) * colors.alpha * 0.5})`;
        context.beginPath();
        for (let k = 0; k < band.length; k += 2) { context.moveTo(band[k].x, band[k].y); context.lineTo(band[k + 1].x, band[k + 1].y); }
        context.stroke();
      });
      for (const node of nodes) {
        const glow = pointer.active ? Math.max(0, 1 - Math.hypot(node.x - pointer.x, node.y - pointer.y) / 220) : 0;
        context.fillStyle = `rgba(${colors.node}, ${colors.alpha + glow * 0.5})`;
        context.beginPath(); context.arc(node.x, node.y, node.r + glow * 1.8, 0, Math.PI * 2); context.fill();
      }
    }
    const kick = () => { if (!frame && motion.allowed() && !document.hidden) frame = requestAnimationFrame(step); };
    seed();
    let resizeTimer = 0;
    addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { seed(); kick(); }, 200); }, { passive: true });
    document.addEventListener("visibilitychange", kick);
    new MutationObserver(() => { colors = palette(); }).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    motion.onChange((on) => { if (on) kick(); else context.clearRect(0, 0, width, height); });
    kick();
  }

  // ---------- Magnetic controls: primary actions lean toward the cursor on a spring ----------
  function magnetic() {
    if (!finePointer) return;
    const SELECTOR = ".button.primary, .signal-region, .deck-wire-toggle, .curiosity-chip";
    let target = null, x = 0, y = 0, vx = 0, vy = 0, gx = 0, gy = 0, frame = 0;
    const tick = () => {
      frame = 0;
      if (!target) return;
      vx = (vx + (gx - x) * 0.22) * 0.68; vy = (vy + (gy - y) * 0.22) * 0.68;
      x += vx; y += vy;
      target.style.setProperty("--mag-x", `${x.toFixed(2)}px`);
      target.style.setProperty("--mag-y", `${y.toFixed(2)}px`);
      if (Math.abs(gx - x) + Math.abs(gy - y) + Math.abs(vx) + Math.abs(vy) > 0.05) frame = requestAnimationFrame(tick);
      else if (!gx && !gy) { target.style.removeProperty("--mag-x"); target.style.removeProperty("--mag-y"); target = null; }
    };
    document.addEventListener("pointermove", (event) => {
      if (!motion.allowed()) return;
      const element = event.target.closest?.(SELECTOR);
      if (element !== target) {
        if (target) { target.style.removeProperty("--mag-x"); target.style.removeProperty("--mag-y"); }
        target = element; x = y = vx = vy = 0;
      }
      if (!target) return;
      const box = target.getBoundingClientRect();
      gx = (event.clientX - box.left - box.width / 2) * 0.18;
      gy = (event.clientY - box.top - box.height / 2) * 0.28;
      target.style.setProperty("--glow-x", `${event.clientX - box.left}px`);
      target.style.setProperty("--glow-y", `${event.clientY - box.top}px`);
      if (!frame) frame = requestAnimationFrame(tick);
    }, { passive: true });
    document.addEventListener("pointerout", (event) => {
      if (!target || target.contains(event.relatedTarget)) return;
      if (event.target.closest?.(SELECTOR) !== target) return;
      gx = gy = 0;
      if (!frame) frame = requestAnimationFrame(tick);
    }, { passive: true });
  }

  // Page heroes get a receding holographic floor and a light sweep (pure CSS once inserted).
  function holoFloors() {
    for (const hero of document.querySelectorAll(".research-header, .curiosity-hero, .information-hero, .directory-intro, .preview-empty")) {
      if (hero.querySelector(":scope > .holo-floor")) continue;
      const floor = document.createElement("span");
      floor.className = "holo-floor";
      floor.setAttribute("aria-hidden", "true");
      hero.append(floor);
    }
  }

  const ready = () => { holoFloors(); startField(); magnetic(); };
  if (document.body) ready();
  else document.addEventListener("DOMContentLoaded", ready, { once: true });
})();
