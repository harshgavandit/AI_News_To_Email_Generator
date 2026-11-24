// Informa AI command deck: live telemetry, "transmissions" that fly in from the Signal Globe,
// and a pausable live wire of the latest headlines. Every headline is a real link to its
// publisher, the wire is a plain list underneath, and nothing here is needed to read news.
import { HUBS } from "./globe.js";
import { mountSignalGlobe, regionCounts } from "./globe-home.js";

const HUB_IDS = new Set(HUBS.map((hub) => hub.id));
// Most publishers report globally; they travel the wire too, without a regional hub on the globe.
const LABELS = { ...Object.fromEntries(HUBS.map((hub) => [hub.id, hub.label])), Global: "Global" };
const CYCLE_MS = 6500;

export function safeLink(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : "";
  } catch {
    return "";
  }
}

// Choose a varied, readable set: one story per publisher, newest first, regions mixed.
export function pickTransmissions(articles, limit = 14) {
  const seen = new Set();
  const picked = [];
  // Newsroom reporting leads, then engineering writing, then community discussion; release notes stay in the feed.
  const RANK = { reporting: 0, publisher: 0, article: 1, discussion: 2 };
  const ranked = (Array.isArray(articles) ? articles : [])
    .filter((article) => article && article.coverage !== "release")
    .map((article, index) => ({ article, index, rank: RANK[article.coverage] ?? 1 }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map((entry) => entry.article);
  for (const article of ranked) {
    if (!article || typeof article.title !== "string" || !article.title.trim()) continue;
    if (!safeLink(article.url)) continue;
    const publisher = article.publisher || article.sourceName || "";
    if (seen.has(publisher)) continue;
    seen.add(publisher);
    picked.push({ id: String(article.id), title: article.title.trim(), url: safeLink(article.url), publisher,
      region: HUB_IDS.has(article.region_id) ? article.region_id : "Global",
      published: article.published_at || article.publishedAt || "" });
    if (picked.length === limit) break;
  }
  // Interleave regions so consecutive transmissions come from different parts of the world.
  const byRegion = new Map();
  for (const item of picked) byRegion.set(item.region, [...(byRegion.get(item.region) || []), item]);
  const mixed = [];
  while (mixed.length < picked.length) {
    for (const queue of byRegion.values()) if (queue.length) mixed.push(queue.shift());
  }
  return mixed;
}

export function relativeAge(iso, now = Date.now()) {
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return "";
  const minutes = Math.max(0, Math.round((now - time) / 60000));
  if (minutes < 60) return `${Math.max(1, minutes)} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`;
}

export function parseFeedHealth(text) {
  const match = /([\d,]+)\s+of\s+([\d,]+)\s+feeds/i.exec(text || "");
  return match ? { fresh: Number(match[1].replace(/,/g, "")), total: Number(match[2].replace(/,/g, "")) } : null;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function headlineLink(item, { hidden = false } = {}) {
  const link = el("a", "deck-wire-item");
  link.href = item.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  if (hidden) link.tabIndex = -1;
  link.append(el("span", "deck-wire-region", LABELS[item.region]), el("span", "deck-wire-title", item.title),
    el("span", "deck-wire-source", item.publisher));
  return link;
}

export function renderWire(container, items) {
  const track = container.querySelector(".deck-wire-track");
  const list = el("ul", "deck-wire-list");
  list.setAttribute("aria-label", "Latest headlines");
  for (const item of items) {
    const entry = el("li");
    entry.append(headlineLink(item));
    list.append(entry);
  }
  // A second, hidden copy lets the band loop seamlessly; assistive tech reads the first only.
  const echo = list.cloneNode(false);
  echo.setAttribute("aria-hidden", "true");
  echo.removeAttribute("aria-label");
  for (const item of items) { const entry = el("li"); entry.append(headlineLink(item, { hidden: true })); echo.append(entry); }
  track.replaceChildren(list, echo);
  track.style.setProperty("--wire-duration", `${Math.max(40, items.length * 7)}s`);
  container.hidden = !items.length;
}

function countUp(node, value, animate) {
  const format = new Intl.NumberFormat();
  if (!animate) { node.textContent = format.format(value); return; }
  const start = performance.now(), from = 0;
  const step = (now) => {
    const t = Math.min(1, (now - start) / 1200), eased = 1 - Math.pow(1 - t, 4);
    node.textContent = format.format(Math.round(from + (value - from) * eased));
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

export function mountCommandDeck(doc = document) {
  const deck = doc.getElementById("command-deck");
  const host = doc.getElementById("signal-globe");
  if (!deck || !host || deck.dataset.mounted) return null;
  deck.dataset.mounted = "";
  const motion = window.informaMotion || { allowed: () => !matchMedia("(prefers-reduced-motion: reduce)").matches, onChange() {} };
  const mounted = mountSignalGlobe(doc);
  const globe = mounted?.globe || null;
  const wire = doc.getElementById("deck-wire");
  const toggle = doc.getElementById("deck-wire-toggle");
  const card = doc.getElementById("deck-transmission");
  const beam = doc.getElementById("deck-beam");
  const stats = doc.getElementById("deck-telemetry");
  let items = [], index = -1, timer = 0, frame = 0, paused = false, current = null, onscreen = true;
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(([entry]) => {
      onscreen = entry.isIntersecting;
      if (onscreen) { schedule(); if (!frame) frame = requestAnimationFrame(place); }
    }).observe(host);
  }

  globe?.setMotion?.(motion.allowed());

  function setStat(name, value) {
    const node = stats?.querySelector(`[data-stat="${name}"]`);
    if (!node || !Number.isFinite(value)) return;
    node.closest(".deck-stat").hidden = false;
    countUp(node, value, motion.allowed());
    stats.hidden = false;
    const visible = [...stats.querySelectorAll(".deck-stat:not([hidden])")];
    stats.dataset.count = String(visible.length);
    visible.forEach((stat, i) => { stat.toggleAttribute("data-last", i === visible.length - 1); });
  }

  // Health counts appear once app.js has checked the feeds; follow its label rather than re-fetching.
  const health = doc.getElementById("source-health-label");
  const readHealth = () => {
    const parsed = parseFeedHealth(health?.textContent);
    if (parsed) setStat("feeds", parsed.fresh);
  };
  if (health) new MutationObserver(readHealth).observe(health, { childList: true, characterData: true, subtree: true });
  const select = doc.getElementById("region");
  const readRegions = () => {
    const live = Object.values(regionCounts(select)).filter((count) => count > 0).length;
    if (live) setStat("regions", live);
  };
  if (select) new MutationObserver(readRegions).observe(select, { childList: true, subtree: true, characterData: true });

  // ---------- Transmissions: a headline flies out of its region's hub ----------
  function place() {
    frame = 0;
    if (!current || !globe || card.hidden || !onscreen) return;
    const box = host.getBoundingClientRect();
    // Global stories have no hub: they hover over the front of the globe without a beam.
    const point = HUB_IDS.has(current.region) ? globe.project(current.region)
      : { x: box.width * 0.5, y: box.height * 0.42, z: 1, global: true };
    if (!point || !box.width) return;
    const facing = point.z > 0.05;
    card.dataset.facing = String(facing);
    beam.dataset.facing = String(facing && !point.global);
    // The card stays inside the globe's half of the deck: beside the hub when there is room,
    // otherwise above or below it, and never over the headline column.
    const frameBox = deck.getBoundingClientRect();
    const minX = Math.max(8, frameBox.left + frameBox.width * 0.5 - box.left);
    const maxX = frameBox.right - 16 - box.left;
    const width = card.offsetWidth || 260, height = card.offsetHeight || 110, gap = 30;
    let x, y;
    if (point.global) { x = Math.min(maxX - width, Math.max(minX, point.x - width / 2)); y = point.y; }
    else if (point.x + gap + width <= maxX) { x = point.x + gap; y = point.y - height / 2; }
    else if (point.x - gap - width >= minX) { x = point.x - gap - width; y = point.y - height / 2; }
    else {
      x = Math.min(maxX - width, Math.max(minX, point.x - width / 2));
      y = point.y + gap + height <= box.height ? point.y + gap : point.y - gap - height;
    }
    y = Math.min(box.height - height - 8, Math.max(8, y));
    card.style.setProperty("--card-x", `${x.toFixed(1)}px`);
    card.style.setProperty("--card-y", `${y.toFixed(1)}px`);
    // A beam joins the hub to the nearest point of the card.
    const tx = Math.min(x + width, Math.max(x, point.x)), ty = Math.min(y + height, Math.max(y, point.y));
    const length = Math.hypot(tx - point.x, ty - point.y);
    beam.style.setProperty("--hub-x", `${point.x.toFixed(1)}px`);
    beam.style.setProperty("--hub-y", `${point.y.toFixed(1)}px`);
    beam.style.setProperty("--beam-length", `${length.toFixed(1)}px`);
    beam.style.setProperty("--beam-angle", `${Math.atan2(ty - point.y, tx - point.x).toFixed(4)}rad`);
    if (motion.allowed()) frame = requestAnimationFrame(place);
  }

  function show(item) {
    current = item;
    card.querySelector(".deck-transmission-region").textContent = `Incoming · ${LABELS[item.region]}`;
    const link = card.querySelector(".deck-transmission-link");
    link.href = item.url;
    link.textContent = item.title;
    card.querySelector(".deck-transmission-meta").textContent =
      [item.publisher, relativeAge(item.published)].filter(Boolean).join(" · ");
    card.hidden = false;
    beam.hidden = false;
    card.dataset.state = "in";
    if (!frame) frame = requestAnimationFrame(place);
  }

  function next() {
    clearTimeout(timer);
    if (!items.length || !globe) return;
    index = (index + 1) % items.length;
    const item = items[index];
    card.dataset.state = "out";
    const regional = HUB_IDS.has(item.region);
    if (regional) globe.focus(item.region);
    timer = setTimeout(() => {
      if (regional) globe.pulse(item.region);
      show(item);
      schedule();
    }, motion.allowed() && regional ? 900 : motion.allowed() ? 350 : 0);
  }

  function schedule() {
    clearTimeout(timer);
    if (!paused && onscreen && motion.allowed() && !document.hidden && items.length > 1) timer = setTimeout(next, CYCLE_MS);
  }

  function hold(on) {
    paused = on;
    globe?.hold?.(on);
    if (on) clearTimeout(timer);
    else schedule();
  }
  // Reading or focusing a transmission holds it in place.
  for (const target of [card, wire]) {
    target?.addEventListener("pointerenter", () => hold(true));
    target?.addEventListener("pointerleave", () => hold(wire?.dataset.paused === "true"));
    target?.addEventListener("focusin", () => hold(true));
    target?.addEventListener("focusout", (event) => { if (!target.contains(event.relatedTarget)) hold(wire?.dataset.paused === "true"); });
  }
  doc.addEventListener("visibilitychange", schedule);

  function setWirePaused(value) {
    if (!wire || !toggle) return;
    wire.dataset.paused = String(value);
    toggle.setAttribute("aria-pressed", String(value));
    toggle.setAttribute("aria-label", value ? "Play live wire" : "Pause live wire");
    toggle.querySelector(".deck-wire-toggle-text").textContent = value ? "Play" : "Pause";
    hold(value);
  }
  toggle?.addEventListener("click", () => setWirePaused(wire.dataset.paused !== "true"));

  motion.onChange?.((on) => {
    globe?.setMotion?.(on);
    setWirePaused(!on);
    if (on) { schedule(); if (!frame) frame = requestAnimationFrame(place); }
  });

  async function load() {
    try {
      const response = await fetch("/api/news?hours=24&limit=50&sort=latest&catalog=0", { headers: { accept: "application/json" } });
      if (!response.ok) return;
      const data = await response.json();
      setStat("stories", Number(data.total));
      const publishers = Object.keys(data.source_counts || {}).filter((key) => key !== "all").length;
      if (publishers) setStat("publishers", publishers);
      items = pickTransmissions(data.articles);
      if (wire) renderWire(wire, items);
      if (!motion.allowed()) setWirePaused(true);
      if (globe && items.length) next();
      readHealth();
      readRegions();
    } catch { /* The deck is optional; the Reading Room below has the same stories. */ }
  }

  const start = () => (window.requestIdleCallback ? requestIdleCallback(load, { timeout: 1200 }) : setTimeout(load, 300));
  if (doc.readyState === "complete") start();
  else addEventListener("load", start, { once: true });
  return { next, hold, get items() { return items; } };
}

if (typeof document !== "undefined" && document.getElementById("command-deck")) {
  // Wait for ambient.js (a deferred script later in the page) so the motion switch is shared.
  if (window.informaMotion || document.readyState === "complete") mountCommandDeck();
  else document.addEventListener("DOMContentLoaded", () => mountCommandDeck(), { once: true });
}
