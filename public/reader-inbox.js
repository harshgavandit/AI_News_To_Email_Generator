import { monitorInbox } from "./monitor-inbox.js";
import { developmentLink } from "./development-link.js";
import { followedStories, saveStoryFollow } from "./technology-follow.js";
import { readingGroups } from "./privacy-data.js";
import { node, requestJSON, sourceLink } from "./evidence-ui.js";

const byId = id => document.getElementById(id);
const feedback = byId("inbox-page-status");
const seenKey = readingGroups.inbox.key;

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
    } catch (error) { feedback.textContent = error.message; }
    finally { button.disabled = false; }
  });
  return button;
}
feedback.tabIndex = -1;

function renderWatches(data) {
  const list = byId("inbox-alerts");
  const filters = byId("inbox-watches");
  list.replaceChildren();
  filters.replaceChildren();
  byId("inbox-watch-status").textContent = !data.available ? "Background monitoring is unavailable." :
    !data.active ? "Enable background monitoring in the Research Desk to receive alerts here." :
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
    if (alert.unread) item.append(action("Mark seen", async () => {
      renderWatches(await monitorInbox(`/read/${alert.id}`, { method: "POST" }));
      feedback.textContent = "Watch alert marked seen.";
    }));
    list.append(item);
  }
  if (data.active && !list.children.length) list.append(node("li", "No alerts in the current watch selection."));
  for (const watch of data.watches) {
    const item = node("li");
    const actions = node("div", null, "reader-actions");
    const paused = watch.delivery?.muted || watch.delivery?.snoozed_until;
    item.append(node("strong", watch.query), node("p", watch.delivery?.muted ? "Muted" :
      paused ? `Snoozed until ${new Date(watch.delivery.snoozed_until * 1000).toLocaleString()}` : "Active", "research-meta"));
    if (data.controls_ready) {
      const controls = paused ? [["Resume", "resume"]] : [["Snooze for 24 hours", "snooze"], ["Mute", "mute"]];
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

function seenDevelopments() {
  try {
    const data = JSON.parse(localStorage.getItem(seenKey));
    return data && typeof data === "object" && !Array.isArray(data) ? data : {};
  } catch { return {}; }
}

async function renderFollows() {
  const list = byId("inbox-follows");
  list.replaceChildren();
  const followed = followedStories().filter(developmentLink).slice(0, 40);
  if (!followed.length) {
    byId("inbox-follow-status").textContent = "Follow a development from its timeline to see it here.";
    return;
  }
  const { events } = await requestJSON(`/api/intelligence/events?${new URLSearchParams({ limit: 40, followed: followed.join(",") })}`,
    { signal: AbortSignal.timeout(15000) });
  const seen = seenDevelopments();
  let unread = 0;
  for (const event of events) {
    const item = node("li");
    const changed = seen[event.id] !== event.digest_version;
    if (changed) unread++;
    item.append(linkTo(event.title, developmentLink(event.id)), node("p",
      changed ? "Unread update" : "Seen", "research-meta"));
    const actions = node("div", null, "reader-actions");
    if (changed) actions.append(action("Mark seen", () => {
      const current = seenDevelopments();
      current[event.id] = event.digest_version;
      localStorage.setItem(seenKey, JSON.stringify(Object.fromEntries(Object.entries(current).filter(([id]) => followed.includes(id)))));
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

monitorInbox().then(renderWatches).catch(error => { byId("inbox-watch-status").textContent = error.message; });
renderFollows().catch(error => { byId("inbox-follow-status").textContent = error.message; });
