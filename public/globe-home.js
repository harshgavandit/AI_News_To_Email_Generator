// Connects the Signal Globe to the Reading Room's publisher-region filter.
// The region buttons are the accessible, always-available control; the globe mirrors them.
import { HUBS, createGlobe } from "./globe.js";

const COUNT = /\(([\d,.\s]+)\)\s*$/;

export function regionCounts(select) {
  const counts = {};
  for (const option of select?.options || []) {
    const match = COUNT.exec(option.textContent || "");
    if (option.value && match) counts[option.value] = Number(match[1].replace(/[^\d]/g, "")) || 0;
  }
  return counts;
}

export function mountSignalGlobe(root = document) {
  const host = root.getElementById ? root.getElementById("signal-globe") : root.querySelector("#signal-globe");
  // Each page names the region filter it drives, the button list and where results start.
  const select = document.getElementById(host?.dataset.select || "region");
  const list = document.getElementById(host?.dataset.regions || "signal-regions");
  const results = host?.dataset.results || "story-results-line";
  if (!host || !select || !list) return null;
  if (host.signalGlobe) return host.signalGlobe;  // Mount once, even if called again.
  const canvas = host.querySelector("canvas");
  const tip = host.querySelector(".signal-globe-tip");
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  const number = new Intl.NumberFormat();
  const buttons = new Map();
  const noun = host.dataset.noun || "in this view";

  for (const hub of HUBS) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "signal-region";
    button.dataset.region = hub.id;
    button.setAttribute("aria-pressed", "false");
    const name = document.createElement("span");
    name.className = "signal-region-name";
    name.textContent = hub.label;
    const count = document.createElement("span");
    count.className = "signal-region-count";
    button.append(name, count);
    button.addEventListener("click", () => choose(hub.id));
    button.addEventListener("pointerenter", () => globe?.setActive(hub.id));
    button.addEventListener("pointerleave", () => globe?.setActive(select.value));
    item.append(button);
    list.append(item);
    buttons.set(hub.id, button);
  }

  let globe = null;
  try {
    globe = canvas ? createGlobe(canvas, {
      reduceMotion: reduce,
      onSelect: (hub) => choose(hub.id),
      onHover: (hub, x, y) => {
        if (!tip) return;
        if (!hub) { tip.hidden = true; return; }
        const stories = regionCounts(select)[hub.id];
        tip.textContent = Number.isInteger(stories) ? `${hub.label} · ${number.format(stories)} ${noun}` : hub.label;
        tip.style.setProperty("--x", `${Math.round(x)}px`);
        tip.style.setProperty("--y", `${Math.round(y)}px`);
        tip.hidden = false;
      },
    }) : null;
  } catch { globe = null; }
  host.classList.toggle("is-live", Boolean(globe));

  function choose(id) {
    const next = select.value === id ? "" : id;
    if (![...select.options].some((option) => option.value === next)) return;
    select.value = next;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    if (next) globe?.focus(next);
    document.getElementById(results)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }

  function sync() {
    const counts = regionCounts(select);
    for (const [id, button] of buttons) {
      const pressed = select.value === id;
      button.setAttribute("aria-pressed", String(pressed));
      const value = counts[id];
      button.querySelector(".signal-region-count").textContent = Number.isInteger(value) ? number.format(value) : "";
      button.title = Number.isInteger(value) ? `${number.format(value)} ${noun}` : "";
    }
    globe?.setWeights(counts);
    globe?.setActive(select.value);
  }

  select.addEventListener("change", sync);
  new MutationObserver(sync).observe(select, { childList: true, subtree: true, characterData: true });
  sync();
  host.signalGlobe = { globe, sync, choose };
  return host.signalGlobe;
}

if (typeof document !== "undefined" && document.getElementById("signal-globe")) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => mountSignalGlobe());
  else mountSignalGlobe();
}
