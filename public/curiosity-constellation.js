// Knowledge constellation for Curiosity Cards: each theme is a star sized by how many stories it holds,
// and themes that share stories are joined by light that carries small pulses between them. A gentle
// spring simulation settles the layout; the pointer pushes stars aside and a click opens that theme.
// Decorative: the theme tabs remain the accessible control, so the canvas is hidden from assistive tech.

export function themeGraph(cards, labels) {
  const counts = new Map();
  const pairs = new Map();
  for (const card of Array.isArray(cards) ? cards : []) {
    const themes = [...new Set((Array.isArray(card?.themes) && card.themes.length ? card.themes : [card?.theme])
      .filter((theme) => labels[theme]))];
    for (const theme of themes) counts.set(theme, (counts.get(theme) || 0) + 1);
    for (let i = 0; i < themes.length; i += 1) {
      for (let j = i + 1; j < themes.length; j += 1) {
        const key = [themes[i], themes[j]].sort().join("|");
        pairs.set(key, (pairs.get(key) || 0) + 1);
      }
    }
  }
  const nodes = Object.keys(labels).filter((id) => counts.get(id)).map((id) => ({ id, label: labels[id], count: counts.get(id) }));
  const links = [...pairs].map(([key, weight]) => {
    const [a, b] = key.split("|");
    return { a, b, weight };
  }).filter((link) => counts.get(link.a) && counts.get(link.b));
  return { nodes, links };
}

// Seed positions on a circle so the layout is the same on every visit.
export function seedLayout(graph, width, height) {
  const count = graph.nodes.length || 1;
  const max = Math.max(1, ...graph.nodes.map((node) => node.count));
  graph.nodes.forEach((node, index) => {
    const angle = (index / count) * Math.PI * 2 - Math.PI / 2;
    node.x = width / 2 + Math.cos(angle) * width * 0.32;
    node.y = height / 2 + Math.sin(angle) * height * 0.32;
    node.vx = 0;
    node.vy = 0;
    node.r = 6 + 16 * Math.sqrt(node.count / max);
    node.w = (node.label.length + String(node.count).length + 3) * 6.2;  // Label width, so labels never collide.
  });
  return graph;
}

// One physics step: node repulsion, springs along shared-story links, a pull to the centre, damping.
export function layoutStep(graph, width, height, pointer = null, dt = 1) {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const maxWeight = Math.max(1, ...graph.links.map((link) => link.weight));
  const span = Math.min(width, height);
  for (let i = 0; i < graph.nodes.length; i += 1) {
    const a = graph.nodes[i];
    for (let j = i + 1; j < graph.nodes.length; j += 1) {
      const b = graph.nodes[j];
      const dx = b.x - a.x, dy = b.y - a.y;
      const distance = Math.max(12, Math.hypot(dx, dy));
      const force = (span * span * 0.05) / (distance * distance);
      const fx = (dx / distance) * force, fy = (dy / distance) * force;
      a.vx -= fx; a.vy -= fy; b.vx += fx; b.vy += fy;
      // Labels sit under the stars: keep stars on a similar line further apart than their labels are wide.
      const overlapX = ((a.w || 0) + (b.w || 0)) / 2 + 8 - Math.abs(dx);
      const overlapY = 34 - Math.abs(dy);
      if (overlapX > 0 && overlapY > 0) {
        const push = Math.min(overlapX, overlapY) * 0.16;
        if (overlapY < overlapX) { const s = dy >= 0 ? 1 : -1; a.vy -= push * s; b.vy += push * s; }
        else { const s = dx >= 0 ? 1 : -1; a.vx -= push * s; b.vx += push * s; }
      }
    }
  }
  for (const link of graph.links) {
    const a = byId.get(link.a), b = byId.get(link.b);
    if (!a || !b) continue;
    const dx = b.x - a.x, dy = b.y - a.y;
    const distance = Math.max(1, Math.hypot(dx, dy));
    const rest = span * (0.55 - 0.2 * (link.weight / maxWeight));
    const force = (distance - rest) * 0.002 * (0.4 + link.weight / maxWeight);
    const fx = (dx / distance) * force, fy = (dy / distance) * force;
    a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
  }
  for (const node of graph.nodes) {
    node.vx += (width / 2 - node.x) * 0.0012;
    node.vy += (height / 2 - node.y) * 0.0016;
    if (pointer) {
      const dx = node.x - pointer.x, dy = node.y - pointer.y;
      const distance = Math.hypot(dx, dy);
      if (distance < 90 && distance > 0.5) {
        const push = (90 - distance) * 0.03;
        node.vx += (dx / distance) * push;
        node.vy += (dy / distance) * push;
      }
    }
    node.vx *= 0.86;
    node.vy *= 0.86;
    const half = Math.max(node.r + 4, (node.w || 0) / 2 + 4);
    node.x = Math.min(width - half, Math.max(half, node.x + node.vx * dt));
    node.y = Math.min(height - node.r - 40, Math.max(node.r + 8, node.y + node.vy * dt));
  }
  return graph;
}

export function nodeAt(graph, x, y) {
  let best = null;
  for (const node of graph.nodes) {
    if (Math.hypot(node.x - x, node.y - y) <= node.r + 8) best = node;
  }
  return best;
}

export function mountConstellation(canvas, graph, { onSelect = () => {}, motion = { allowed: () => true, onChange() {} } } = {}) {
  const context = canvas.getContext?.("2d");
  if (!context || !graph.nodes.length) return null;
  const host = canvas.parentElement;
  let width = 0, height = 0, dpr = 1, frame = 0, visible = true, active = "all", hover = null, pointer = null;
  let pulses = [];
  let last = 0;

  function resize() {
    const box = host.getBoundingClientRect();
    dpr = Math.min(2, window.devicePixelRatio || 1);
    const nextWidth = Math.max(1, Math.round(box.width)), nextHeight = Math.max(1, Math.round(box.height));
    if (width && height) {
      for (const node of graph.nodes) { node.x *= nextWidth / width; node.y *= nextHeight / height; }
    } else {
      seedLayout(graph, nextWidth, nextHeight);
      for (let i = 0; i < 600; i += 1) layoutStep(graph, nextWidth, nextHeight);  // Settle before the first frame.
    }
    width = nextWidth; height = nextHeight;
    canvas.width = width * dpr; canvas.height = height * dpr;
    canvas.style.width = `${width}px`; canvas.style.height = `${height}px`;
    draw(performance.now());
  }

  const css = getComputedStyle(canvas);
  const ink = css.getPropertyValue("--constellation-ink").trim() || "#e7f1fc";
  const glow = css.getPropertyValue("--constellation-glow").trim() || "#22d3ee";
  const accent = css.getPropertyValue("--constellation-accent").trim() || "#67e8f9";

  function draw(time) {
    const byId = new Map(graph.nodes.map((node) => [node.id, node]));
    const maxWeight = Math.max(1, ...graph.links.map((link) => link.weight));
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, width, height);
    const focus = hover?.id || (active !== "all" ? active : null);
    for (const link of graph.links) {
      const a = byId.get(link.a), b = byId.get(link.b);
      if (!a || !b) continue;
      const lit = focus && (link.a === focus || link.b === focus);
      context.strokeStyle = lit ? accent : glow;
      context.globalAlpha = (lit ? 0.55 : 0.12) + 0.3 * (link.weight / maxWeight) * (focus && !lit ? 0.3 : 1);
      context.lineWidth = 0.6 + 2.2 * (link.weight / maxWeight);
      context.beginPath();
      context.moveTo(a.x, a.y);
      context.lineTo(b.x, b.y);
      context.stroke();
    }
    context.globalAlpha = 1;
    for (const pulse of pulses) {
      const a = byId.get(pulse.a), b = byId.get(pulse.b);
      if (!a || !b) continue;
      const t = Math.min(1, (time - pulse.start) / pulse.duration);
      context.fillStyle = accent;
      context.globalAlpha = Math.sin(t * Math.PI);
      context.beginPath();
      context.arc(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, 2.2, 0, Math.PI * 2);
      context.fill();
    }
    context.globalAlpha = 1;
    context.font = "600 11px Instrument Sans, system-ui, sans-serif";
    context.textAlign = "center";
    for (const node of graph.nodes) {
      const lit = node.id === focus;
      const dim = focus && !lit && !graph.links.some((l) => (l.a === focus && l.b === node.id) || (l.b === focus && l.a === node.id));
      const halo = context.createRadialGradient(node.x, node.y, 0, node.x, node.y, node.r * 2.6);
      halo.addColorStop(0, lit ? accent : glow);
      halo.addColorStop(1, "transparent");
      context.globalAlpha = dim ? 0.25 : lit ? 0.9 : 0.55;
      context.fillStyle = halo;
      context.beginPath();
      context.arc(node.x, node.y, node.r * 2.6, 0, Math.PI * 2);
      context.fill();
      context.globalAlpha = dim ? 0.45 : 1;
      context.fillStyle = lit ? "#ffffff" : ink;
      context.beginPath();
      context.arc(node.x, node.y, node.r * (lit ? 0.62 : 0.5), 0, Math.PI * 2);
      context.fill();
      context.fillStyle = ink;
      context.globalAlpha = dim ? 0.45 : lit ? 1 : 0.85;
      context.fillText(`${node.label} · ${node.count}`, node.x, node.y + node.r + 13);
    }
    context.globalAlpha = 1;
  }

  function tick(time) {
    frame = 0;
    if (!visible || !motion.allowed()) { draw(time); return; }
    const dt = Math.min(2, (time - (last || time)) / 16.7 || 1);
    last = time;
    layoutStep(graph, width, height, pointer, dt);
    pulses = pulses.filter((pulse) => time - pulse.start < pulse.duration);
    if (pulses.length < 10 && graph.links.length && Math.random() < 0.08) {
      const link = graph.links[Math.floor(Math.random() * graph.links.length)];
      const forward = Math.random() < 0.5;
      pulses.push({ a: forward ? link.a : link.b, b: forward ? link.b : link.a, start: time, duration: 1400 + Math.random() * 1200 });
    }
    draw(time);
    frame = requestAnimationFrame(tick);
  }
  const kick = () => { if (!frame) frame = requestAnimationFrame(tick); };

  function local(event) {
    const box = canvas.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  }
  canvas.addEventListener("pointermove", (event) => {
    pointer = local(event);
    hover = nodeAt(graph, pointer.x, pointer.y);
    canvas.style.cursor = hover ? "pointer" : "default";
    if (!motion.allowed()) draw(performance.now());
    kick();
  });
  canvas.addEventListener("pointerleave", () => { pointer = null; hover = null; draw(performance.now()); kick(); });
  canvas.addEventListener("click", (event) => {
    const point = local(event);
    const node = nodeAt(graph, point.x, point.y);
    if (node) onSelect(node.id);
  });

  const resizer = new ResizeObserver(resize);
  resizer.observe(host);
  const watcher = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; if (visible) kick(); });
  watcher.observe(canvas);
  document.addEventListener("visibilitychange", () => { visible = !document.hidden; if (visible) kick(); });
  motion.onChange?.(() => kick());
  resize();
  kick();

  return {
    setActive(id) { active = id || "all"; draw(performance.now()); kick(); },
    destroy() { cancelAnimationFrame(frame); resizer.disconnect(); watcher.disconnect(); },
  };
}
