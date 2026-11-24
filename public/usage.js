// Anonymous feature usage counts (feature + action, nothing about the reader or the story).
// Same consent rule as Curiosity counts: audience analytics on, and no GPC or Do Not Track signal.
import { trackingAllowed } from "./curiosity-events.js";

const ENDPOINT = "/api/usage/events";
const queue = [];
let timer = null;

export function flushUsage(nav = globalThis.navigator, fetcher = globalThis.fetch) {
  clearTimeout(timer);
  timer = null;
  if (!queue.length) return;
  const body = JSON.stringify({ events: queue.splice(0, 20) });
  let sent = false;
  try { sent = Boolean(nav?.sendBeacon?.(ENDPOINT, new Blob([body], { type: "application/json" }))); } catch { sent = false; }
  if (!sent) fetcher?.(ENDPOINT, { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true })?.catch?.(() => {});
  if (queue.length) flushUsage(nav, fetcher);
}

export function countUse(feature, action, { allowed = trackingAllowed } = {}) {
  if (!allowed()) return false;
  queue.push({ feature, action });
  clearTimeout(timer);
  if (queue.length >= 20) flushUsage();
  else timer = setTimeout(() => flushUsage(), 2000);
  return true;
}

if (typeof addEventListener === "function") {
  addEventListener("pagehide", () => flushUsage());
}
