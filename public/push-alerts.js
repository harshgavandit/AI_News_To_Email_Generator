// Device alerts (Web Push) for the stories, technologies and companies a reader follows.
// Follows stay in this browser; turning alerts on sends only the follow list and this
// browser's push address to Informa AI, which is what lets the server pick what to send.
import { readingGroups } from "./privacy-data.js";

export const PUSH_KEY = "informa-push-v1";
const radarKey = readingGroups.radar.key;
const STORY_ID = /^[a-f0-9]{32}$/;

const list = (value, max) => Array.isArray(value)
  ? [...new Set(value.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim()))].slice(0, max)
  : [];

export function alertProfile(storage = globalThis.localStorage) {
  let saved = {};
  try { saved = JSON.parse(storage?.getItem(radarKey) || "null") || {}; } catch { saved = {}; }
  const feedback = saved.feedback && typeof saved.feedback === "object" ? saved.feedback : {};
  return {
    interests: list(saved.interests, 12), stack: list(saved.stack, 12), topics: list(saved.topics, 6),
    followed_events: list(saved.followed_events, 40).filter((id) => STORY_ID.test(id)),
    followed_technologies: list(saved.followed_technologies, 20),
    feedback: { companies: list(feedback.companies, 12), muted_topics: list(feedback.muted_topics, 12) },
  };
}

export function followSummary(profile) {
  const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;
  const parts = [
    [profile.followed_events.length, "story", "stories"],
    [profile.followed_technologies.length, "technology", "technologies"],
    [profile.feedback.companies.length, "company", "companies"],
    [profile.topics.length, "topic", "topics"],
    [profile.stack.length + profile.interests.length, "stack or interest term", "stack and interest terms"],
  ].filter(([count]) => count > 0);
  const total = parts.reduce((sum, [count]) => sum + count, 0);
  return { total, text: total ? parts.map(([count, one, many]) => plural(count, one, many)).join(", ") : "" };
}

export function defaultSettings() {
  let timezone = "UTC";
  try { timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { /* Keep UTC. */ }
  return { max_per_day: 3, quiet_hours: true, timezone };
}

export function readState(storage = globalThis.localStorage) {
  try {
    const state = JSON.parse(storage?.getItem(PUSH_KEY) || "null");
    return state && typeof state.endpoint === "string" ? state : null;
  } catch { return null; }
}

function writeState(storage, state) {
  try { state ? storage.setItem(PUSH_KEY, JSON.stringify(state)) : storage.removeItem(PUSH_KEY); } catch { /* Session only. */ }
}

export const syncKey = (profile, settings) => JSON.stringify([profile, settings]);

export function applicationServerKey(base64) {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(padded), (char) => char.charCodeAt(0));
}

export function alertSupport(win = globalThis) {
  const nav = win.navigator || {};
  const standalone = win.matchMedia?.("(display-mode: standalone)")?.matches || nav.standalone === true;
  const ios = /iPad|iPhone|iPod/.test(nav.userAgent || "") || (nav.platform === "MacIntel" && nav.maxTouchPoints > 1);
  if ("serviceWorker" in nav && "PushManager" in win && "Notification" in win) return { supported: true };
  if (ios && !standalone) return { supported: false, reason: "ios-home-screen" };
  return { supported: false, reason: "unsupported" };
}

async function problem(response, fallback) {
  try { return (await response.json()).detail || fallback; } catch { return fallback; }
}

async function putSubscription(fetcher, subscription, profile, settings, watchAgent = false) {
  const path = watchAgent ? "/api/intelligence/inbox/agent-push" : "/api/push/subscription";
  const response = await fetcher(path, { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subscription: subscription.toJSON(), profile, settings }) });
  if (!response.ok) throw new Error(await problem(response, "Alerts could not be saved. Try again later."));
  return response.json();
}

export async function enableAlerts({ config, registration, storage = globalThis.localStorage, fetcher = globalThis.fetch,
  requestPermission = () => globalThis.Notification.requestPermission(), settings = defaultSettings(), watchAgent = false }) {
  if (!config?.enabled || !config.public_key) throw new Error("Alerts aren't available yet.");
  const profile = alertProfile(storage);
  watchAgent ||= readState(storage)?.watchAgent === true;
  if (!watchAgent && !followSummary(profile).total) throw new Error("Follow a story, technology, company or topic first, then turn on alerts.");
  // Ask first: Safari only shows the permission prompt directly after the click.
  const permission = await requestPermission();
  if (permission !== "granted") throw new Error(permission === "denied"
    ? "Notifications are blocked for this site. Allow them in your browser's site settings, then try again."
    : "Notifications weren't allowed, so alerts stay off.");
  const worker = await registration;  // may be a promise, so the prompt above is not delayed
  let subscription;
  try {
    subscription = await worker.pushManager.getSubscription() || await worker.pushManager.subscribe({
      userVisibleOnly: true, applicationServerKey: applicationServerKey(config.public_key) });
  } catch {
    throw new Error("This browser couldn't set up alerts. Private or incognito windows can't receive them; try a regular window.");
  }
  const saved = await putSubscription(fetcher, subscription, profile, settings, watchAgent);
  writeState(storage, { endpoint: subscription.endpoint, settings, synced: syncKey(profile, settings), ...(watchAgent && { watchAgent }) });
  return saved;
}

export async function disableAlerts({ registration, storage = globalThis.localStorage, fetcher = globalThis.fetch }) {
  const state = readState(storage);
  const subscription = await registration?.pushManager.getSubscription();
  const endpoint = state?.endpoint || subscription?.endpoint;
  if (endpoint) await fetcher("/api/push/subscription/remove", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ endpoint }) }).catch(() => undefined);
  await subscription?.unsubscribe().catch(() => undefined);
  writeState(storage, null);
}

export async function updateSettings(settings, { registration, storage = globalThis.localStorage, fetcher = globalThis.fetch }) {
  const subscription = await registration.pushManager.getSubscription();
  if (!subscription) throw new Error("Alerts are off for this browser.");
  const profile = alertProfile(storage);
  const watchAgent = readState(storage)?.watchAgent === true;
  await putSubscription(fetcher, subscription, profile, settings, watchAgent);
  writeState(storage, { endpoint: subscription.endpoint, settings, synced: syncKey(profile, settings), ...(watchAgent && { watchAgent }) });
}

// Runs on every page load: keeps the server's copy of the follow list in step with this browser.
export async function syncAlerts({ registration, storage = globalThis.localStorage, fetcher = globalThis.fetch,
  permission = globalThis.Notification?.permission }) {
  const state = readState(storage);
  if (!state) return "off";
  const subscription = await registration.pushManager.getSubscription();
  if (!subscription || permission !== "granted") {
    await disableAlerts({ registration, storage, fetcher });
    return "removed";
  }
  if (subscription.endpoint !== state.endpoint) {
    const moved = await fetcher("/api/push/subscription/rotate", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_endpoint: state.endpoint, subscription: subscription.toJSON() }) });
    if (!moved.ok && moved.status !== 404) return "error";
    state.endpoint = subscription.endpoint;
    state.synced = "";
  }
  const profile = alertProfile(storage);
  if (!state.watchAgent && !followSummary(profile).total) {
    await disableAlerts({ registration, storage, fetcher });
    return "no-follows";
  }
  if (state.synced === syncKey(profile, state.settings)) return "current";
  await putSubscription(fetcher, subscription, profile, state.settings, state.watchAgent);
  writeState(storage, { ...state, synced: syncKey(profile, state.settings) });
  return "synced";
}

export async function sendTest({ storage = globalThis.localStorage, fetcher = globalThis.fetch }) {
  const state = readState(storage);
  if (!state) throw new Error("Alerts are off for this browser.");
  const response = await fetcher("/api/push/test", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: state.endpoint }) });
  if (!response.ok) throw new Error(await problem(response, "The test alert could not be sent."));
}

function node(tag, attributes = {}, text = "") {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  if (text) element.textContent = text;
  return element;
}

export function mountAlertPanel(root, { win = globalThis, storage = globalThis.localStorage, fetcher = globalThis.fetch,
  ready = () => win.navigator.serviceWorker.ready, requestPermission } = {}) {
  if (!root || root.dataset.alertMounted) return null;
  root.dataset.alertMounted = "1";
  const state = node("p", { class: "alert-state" });
  const follows = node("p", { class: "small alert-follows" });
  const options = node("div", { class: "alert-options" });
  const perDay = node("select", { "aria-label": "Most alerts a day" });
  for (const count of [1, 3, 5]) perDay.append(node("option", { value: String(count) }, String(count)));
  const quietBox = node("input", { type: "checkbox" });
  const perDayLabel = node("label");
  perDayLabel.append("At most ", perDay, " a day");
  const quietLabel = node("label");
  quietLabel.append(quietBox, " Quiet hours, 22:00–07:00 your time");
  options.append(perDayLabel, quietLabel);
  const actions = node("div", { class: "alert-actions" });
  const toggle = node("button", { type: "button", class: "button primary" });
  const test = node("button", { type: "button", class: "text-button" }, "Send a test alert");
  actions.append(toggle, test);
  const status = node("p", { class: "status", role: "status", "aria-live": "polite" });
  root.replaceChildren(state, follows, options, actions, status);
  perDay.value = String(defaultSettings().max_per_day);
  quietBox.checked = true;
  let config = null;
  let busy = false;

  const settings = () => ({ ...(readState(storage)?.settings || defaultSettings()),
    max_per_day: Number(perDay.value), quiet_hours: quietBox.checked });

  function render() {
    const support = alertSupport(win);
    const on = Boolean(readState(storage));
    const summary = followSummary(alertProfile(storage));
    const saved = readState(storage)?.settings;
    if (saved) {
      perDay.value = String(saved.max_per_day);
      quietBox.checked = saved.quiet_hours !== false;
    }
    follows.replaceChildren(summary.total ? `You follow ${summary.text}. ` : "You don't follow anything yet. ",
      Object.assign(node("a", { href: "/research.html#radar-title" }), { textContent: "Manage follows" }));
    toggle.hidden = test.hidden = options.hidden = true;
    if (!support.supported) {
      state.textContent = support.reason === "ios-home-screen"
        ? "On iPhone and iPad, add Informa AI to your Home Screen first (Share, then Add to Home Screen), then open it and turn on alerts here."
        : "This browser can't show alerts from websites.";
      return;
    }
    if (config && !config.enabled) {
      state.textContent = "Alerts aren't available yet.";
      return;
    }
    state.textContent = on
      ? "Alerts are on for this browser. You'll get a notification when there's new coverage of what you follow."
      : "Get a notification on this device when there's new coverage of what you follow.";
    toggle.textContent = on ? "Turn off alerts" : "Turn on alerts";
    toggle.hidden = false;
    toggle.disabled = busy || (!on && !summary.total) || !config;
    options.hidden = false;
    test.hidden = !on;
    test.disabled = busy;
  }

  async function run(action, success) {
    busy = true;
    render();
    status.textContent = "";
    try {
      await action();
      status.textContent = success;
    } catch (error) {
      status.textContent = error?.message || "Something went wrong. Try again.";
    } finally {
      busy = false;
      render();
    }
  }

  toggle.addEventListener("click", () => {
    if (readState(storage)) {
      run(async () => disableAlerts({ registration: await ready(), storage, fetcher }), "Alerts are off for this browser.");
    } else {
      const chosen = settings();
      run(async () => {
        await enableAlerts({ config, registration: ready(), storage, fetcher, settings: chosen,
          ...(requestPermission ? { requestPermission } : {}) });
      }, "Alerts are on. You can send yourself a test alert.");
    }
  });
  test.addEventListener("click", () => run(() => sendTest({ storage, fetcher }), "Test alert sent. It should arrive in a few seconds."));
  for (const control of [perDay, quietBox]) control.addEventListener("change", () => {
    if (!readState(storage)) return;
    const chosen = settings();
    run(async () => updateSettings(chosen, { registration: await ready(), storage, fetcher }), "Alert settings saved.");
  });

  render();
  const loaded = fetcher("/api/push/config").then((response) => (response.ok ? response.json() : { enabled: false }))
    .catch(() => ({ enabled: false })).then((value) => { config = value; render(); });
  return { render, loaded };
}
