// The Signal Orb: when the command deck scrolls away, a small globe docks in the corner and
// turns to the region of whichever story sits in the middle of the screen. It is a reading
// companion, not a control: stories, links and filters work the same without it.
import { HUBS, createGlobe } from "./globe.js";

const LABELS = Object.fromEntries(HUBS.map((hub) => [hub.id, hub.label]));

// The story nearest the reading line (40% down the viewport) is the one being read.
export function storyAtReadingLine(stories, viewportHeight) {
  const line = viewportHeight * 0.4;
  let best = null;
  let bestDistance = Infinity;
  for (const story of stories) {
    if (!story?.dataset?.region || !LABELS[story.dataset.region]) continue;
    const box = story.getBoundingClientRect();
    if (box.bottom < 0 || box.top > viewportHeight) continue;
    const distance = line < box.top ? box.top - line : line > box.bottom ? line - box.bottom : 0;
    if (distance < bestDistance) { best = story; bestDistance = distance; }
  }
  return best;
}

export function orbLabel(region, publisher) {
  const place = LABELS[region];
  if (!place) return "";
  return publisher ? `${place} · ${publisher}` : place;
}

export function mountSignalOrb(doc = document, win = window) {
  const deck = doc.getElementById("signal-globe");
  const stories = doc.getElementById("stories");
  const motion = win.informaMotion;
  const wide = win.matchMedia?.("(min-width: 1100px)").matches;
  const saveData = win.navigator?.connection?.saveData;
  if (!deck || !stories || !wide || saveData || !motion?.allowed() || doc.querySelector(".signal-orb")) return null;

  const orb = doc.createElement("button");
  orb.type = "button";
  orb.className = "signal-orb";
  orb.hidden = true;
  orb.setAttribute("aria-label", "Back to the Signal Globe");
  orb.innerHTML = '<span class="signal-orb-sphere"><canvas width="128" height="128"></canvas></span>'
    + '<span class="signal-orb-text"><span class="signal-orb-kicker">Now reading from</span>'
    + '<span class="signal-orb-place">The world</span></span>';
  doc.body.append(orb);
  const place = orb.querySelector(".signal-orb-place");
  let globe = null;
  let current = "";
  let docked = false;
  let frame = 0;

  function follow() {
    frame = 0;
    if (!docked) return;
    const story = storyAtReadingLine(stories.querySelectorAll(".story[data-region]"), win.innerHeight);
    const region = story?.dataset.region || "";
    if (!region || region === current) return;
    current = region;
    place.textContent = orbLabel(region, story.dataset.publisher);
    globe?.focus(region);
    globe?.setActive(region);
    globe?.pulse(region);
  }
  const schedule = () => { if (!frame) frame = win.requestAnimationFrame(follow); };

  function dock(value) {
    if (value === docked) return;
    docked = value && motion.allowed();
    orb.hidden = !docked;
    if (docked && !globe) {
      globe = createGlobe(orb.querySelector("canvas"), { reduceMotion: false });
      if (!globe) { orb.remove(); return; }  // No WebGL: the orb simply never appears.
    }
    if (docked) { current = ""; schedule(); }
  }

  const watcher = new win.IntersectionObserver(([entry]) => dock(!entry.isIntersecting), { threshold: 0 });
  watcher.observe(deck);
  win.addEventListener("scroll", schedule, { passive: true });
  motion.onChange?.((on) => { if (!on) dock(false); else schedule(); });
  orb.addEventListener("click", () => {
    deck.scrollIntoView({ behavior: motion.allowed() ? "smooth" : "auto", block: "center" });
    deck.querySelector("button, [tabindex]")?.focus?.({ preventScroll: true });
  });
  return { orb, dock, follow, get region() { return current; } };
}

if (typeof window !== "undefined" && window.document?.getElementById("stories")) {
  const start = () => {
    if (mountSignalOrb()) return;
    // If motion starts off, the orb appears once the reader switches motion on.
    const stop = window.informaMotion?.onChange?.((on) => { if (on && mountSignalOrb()) stop?.(); });
  };
  if ("requestIdleCallback" in window) window.requestIdleCallback(start, { timeout: 3000 });
  else window.addEventListener("load", start, { once: true });
}
