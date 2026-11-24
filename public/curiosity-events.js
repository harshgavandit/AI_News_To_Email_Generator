// Anonymous Curiosity Cards usage counts: which cards, reading lists and lessons readers open.
//
// Sent only when the reader has turned on audience analytics on Privacy & Controls (off by default) and the
// browser sends no Global Privacy Control or Do Not Track signal: the same rule as the site's other analytics.
// Events carry a card or list id and the page section, nothing about the reader, and are batched.

const CONSENT_KEY = "informa-analytics-consent";
const ENDPOINT = "/api/curiosity/events";
const BATCH = 20;
const queue = [];
let timer = null;

export function trackingAllowed(nav = globalThis.navigator, storage = globalThis.localStorage) {
  try {
    return nav?.globalPrivacyControl !== true && nav?.doNotTrack !== "1" && storage?.getItem(CONSENT_KEY) === "granted";
  } catch {
    return false;
  }
}

export function flushEvents(nav = globalThis.navigator, fetcher = globalThis.fetch) {
  clearTimeout(timer);
  timer = null;
  while (queue.length) {
    const body = JSON.stringify({ events: queue.splice(0, BATCH) });
    let sent = false;
    try {
      sent = Boolean(nav?.sendBeacon?.(ENDPOINT, new Blob([body], { type: "application/json" })));
    } catch { sent = false; }
    if (!sent) fetcher?.(ENDPOINT, { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true }).catch?.(() => {});
  }
}

export function track(type, { cardId = "", listId = "", surface } = {}) {
  if (!trackingAllowed() || !surface) return false;
  queue.push({ type, surface, ...(cardId ? { card_id: String(cardId).slice(0, 96) } : {}), ...(listId ? { list_id: String(listId).slice(0, 96) } : {}) });
  if (queue.length >= BATCH) flushEvents();
  else {
    clearTimeout(timer);
    timer = setTimeout(() => flushEvents(), 2000);
  }
  return true;
}

export function pendingEvents() {
  return [...queue];
}

// One delegated listener per container: publisher links, "Read next" links and share buttons.
export function bindCardTracking(root, surface) {
  if (!root || root.dataset.curiosityTracked === "1") return;
  root.dataset.curiosityTracked = "1";
  root.addEventListener("click", (event) => {
    const target = event.target.closest?.("a, button");
    if (!target || !root.contains(target)) return;
    const card = target.closest("[data-curiosity-id]")?.dataset.curiosityId;
    if (target.matches(".curiosity-related-link") && target.dataset.related) track("read_next", { cardId: target.dataset.related, surface });
    else if (target.matches(".curiosity-link, [data-card-source]") && card) track("open_source", { cardId: card, surface });
    else if (target.matches("[data-curiosity-share], [data-card-share]") && card) track("share", { cardId: card, surface });
  });
}

if (typeof window !== "undefined") {
  window.addEventListener("pagehide", () => flushEvents());
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushEvents();
  });
}
