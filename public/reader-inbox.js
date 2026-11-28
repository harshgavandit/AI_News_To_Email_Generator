import { monitorInbox } from "./monitor-inbox.js";
import { readableError } from "./evidence-ui.js";
import { developmentLink } from "./development-link.js";
import { followedStories, saveStoryFollow } from "./technology-follow.js";
import { markDevelopmentsSeen, seenDevelopments } from "./development-seen.js";
import { node, requestJSON, sourceLink } from "./evidence-ui.js";
import { alertDetails, watchPrecision } from "./watch-agent-ui.js";
import { alertSupport, defaultSettings, enableAlerts, readState } from "./push-alerts.js";

const byId = id => document.getElementById(id);
const feedback = byId("inbox-page-status");

function linkTo(label, url) {
  const link = node("a", label);
  link.href = url;
  return link;
}

function action(label, run) {
  const button = node("button", label, "button secondary");
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await run();
      if (!button.isConnected) feedback.focus({ preventScroll: true });
    } catch (error) { feedback.textContent = readableError(error); }
    finally { button.disabled = false; }
  });
  return button;
}
feedback.tabIndex = -1;

let pushConfig;
function renderAgentPush(data) {
  const panel = byId("inbox-agent-push");
  const button = panel.querySelector("button");
  const status = panel.querySelector("[role=status]");
  panel.hidden = !data.watches.some((watch) => watch.agent);
  if (panel.hidden) return;
  const support = alertSupport();
  if (data.agent_push || !support.supported) {
    button.hidden = true;
    status.textContent = data.agent_push ? "Watch agent push is on for this device." :
      support.reason === "ios-home-screen" ? "Add Informa to your Home Screen to use push." : "This browser cannot receive push.";
    return;
  }
  button.hidden = false;
  button.disabled = true;
  pushConfig ||= requestJSON("/api/push/config").catch(() => { pushConfig = null; return null; });
  pushConfig.then((config) => {
    button.disabled = !config?.enabled;
    status.textContent = config?.enabled ? "Uses your device’s quiet hours and delivery limits." : "Device alerts are unavailable right now.";
    button.onclick = async () => {
      button.disabled = true;
      try {
        await enableAlerts({ config, registration: navigator.serviceWorker.ready, watchAgent: true,
          settings: readState()?.settings || defaultSettings() });
        renderWatches(await monitorInbox());
      } catch (error) { status.textContent = readableError(error); button.disabled = false; }
    };
  });
}

function renderWatches(data) {
  const list = byId("inbox-alerts");
  const filters = byId("inbox-watches");
  list.replaceChildren();
  filters.replaceChildren();
  renderAgentPush(data);
  byId("inbox-start-watches").hidden = data.active && data.watches.length > 0;
  byId("inbox-manage-watches").hidden = !data.active || !data.watches.length;
  byId("inbox-watch-status").textContent = !data.available ? "Background monitoring is unavailable." :
    !data.active || !data.watches.length ? "Pick a topic to receive matching stories here." :
    `${data.unread} unread watch alerts`;
  for (const alert of data.alerts) {
    const item = node("li");
    const sources = alert.sources || [];
    item.append(node("p", alert.unread ? "Unread" : "Seen", "research-meta"));
    const links = node("ul");
    for (const item of sources) {
      const li = node("li");
      li.append(sourceLink(item));
      links.append(li);
    }
    item.append(links);
    const explanation = alertDetails(alert, async (id, rating) => {
      try {
        renderWatches(await monitorInbox("/feedback/" + id, { method: "PUT", body: { rating } }));
        feedback.textContent = "Alert feedback saved.";
        feedback.focus({ preventScroll: true });
      } catch (error) { feedback.textContent = readableError(error); }
    });
    if (explanation) item.append(explanation);
    if (alert.unread) item.append(action("Mark seen", async () => {
      renderWatches(await monitorInbox(`/read/${alert.id}`, { method: "POST" }));
      feedback.textContent = "Watch alert marked seen.";
    }));
    list.append(item);
  }
  if (data.active && data.watches.length && !list.children.length) list.append(node("li", "No alerts in the current watch selection."));
  for (const watch of data.watches) {
    const item = node("li");
    const actions = node("div", null, "reader-actions");
    const paused = watch.delivery?.muted || watch.delivery?.snoozed_until;
    item.append(node("strong", watch.query), node("p", watch.delivery?.muted ? "Muted" :
      paused ? `Snoozed until ${new Date(watch.delivery.snoozed_until * 1000).toLocaleString()}` : "Active", "research-meta"));
    if (watch.agent) item.append(node("p", watchPrecision(watch), "research-meta"));
    if (watch.agent_status === "ai_unavailable" && !paused) {
      item.append(node("p", "AI unavailable. The check will retry.", "research-meta"));
    }
    if (data.controls_ready) {
      const controls = paused ? [["Resume", "resume"]] : [["Snooze for 24 hours", "snooze"], [watch.agent ? "Pause" : "Mute", "mute"]];
      for (const [label, control] of controls) actions.append(action(label, async () => {
        renderWatches(await monitorInbox(`/watches/${encodeURIComponent(watch.id)}/delivery`,
          { method: "PUT", body: { action: control } }));
        feedback.textContent = `${watch.query} · ${label}. Morning email preferences are managed separately.`;
      }));
    }
    item.append(actions);
    filters.append(item);
  }
}

async function renderFollows() {
  const list = byId("inbox-follows");
  const explore = byId("inbox-explore");
  const followed = followedStories().filter(developmentLink).slice(0, 40);
  if (!followed.length) {
    list.replaceChildren();
    explore.hidden = false;
    byId("inbox-follow-status").textContent = "Follow a development from its timeline to see it here.";
    return;
  }
  const { events } = await requestJSON(`/api/intelligence/events?${new URLSearchParams({ limit: 40, followed: followed.join(",") })}`,
    { signal: AbortSignal.timeout(15000) });
  list.replaceChildren();
  explore.hidden = events.length > 0;
  const seen = seenDevelopments();
  let unread = 0;
  for (const event of events) {
    const item = node("li");
    const changed = Number(seen[event.id] ?? 0) < Number(event.digest_version);
    if (changed) unread++;
    item.append(linkTo(event.title, developmentLink(event.id)), node("p",
      changed ? "Unread update" : "Seen", "research-meta"));
    const actions = node("div", null, "reader-actions");
    if (changed) actions.append(action("Mark seen", () => {
      markDevelopmentsSeen([event]);
      feedback.textContent = "Development marked seen in this browser.";
      return renderFollows();
    }));
    actions.append(action("Unfollow", () => {
      saveStoryFollow(event.id, false);
      feedback.textContent = "Unfollowed in this browser. Save your Tech Radar for the same change in verified email.";
      return renderFollows();
    }));
    item.append(actions);
    list.append(item);
  }
  byId("inbox-follow-status").textContent = events.length ? `${unread} unread followed developments` :
    "Your followed developments are outside the retained archive.";
}

monitorInbox().then(renderWatches).catch(error => { byId("inbox-watch-status").textContent = readableError(error); });
renderFollows().catch(error => { byId("inbox-follow-status").textContent = readableError(error); });
