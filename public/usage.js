// Anonymous feature usage counts (feature + action, nothing about the reader or the story).
// Same consent rule as Curiosity counts: audience analytics on, and no GPC or Do Not Track signal.
import { trackingAllowed } from "./curiosity-events.js";

const ENDPOINT = "/api/usage/events";
export const MILESTONES_KEY = "informa-reader-milestones-v1";
const WEEK = 7 * 24 * 60 * 60 * 1000;
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

export function noteReaderMilestone(action, {
  storage = globalThis.localStorage, nav = globalThis.navigator, now = Date.now(), sessionStartedAt, track = countUse,
} = {}) {
  if (!trackingAllowed(nav, storage) || !Number.isSafeInteger(sessionStartedAt)) return;
  try {
    let data = JSON.parse(storage.getItem(MILESTONES_KEY) || "null");
    if (!Number.isFinite(data?.firstAt) || !Array.isArray(data.actions)) {
      data = { firstAt: now, session: sessionStartedAt, actions: [] };
    }
    const events = ["first_visit"];
    if (action !== "first_visit") events.push(action);
    if (sessionStartedAt > data.session && now - data.firstAt <= WEEK) events.push("return_7d");
    const pending = events.filter(event => !data.actions.includes(event));
    if (!pending.length) return;
    storage.setItem(MILESTONES_KEY, JSON.stringify({ ...data, actions: [...data.actions, ...pending] }));
    for (const event of pending) track("reader_milestone", event);
  } catch { /* First-use signals require working local storage. */ }
}

if (typeof addEventListener === "function") {
  addEventListener("pagehide", () => flushUsage());
}
