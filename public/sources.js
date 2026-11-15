"use strict";

const element = (id) => document.getElementById(id);
const statusLabels = {
  fresh: "Up to date",
  stale: "Check overdue",
  failed: "Last check failed",
  pending: "Awaiting first check",
  paused: "Paused",
};
const sourceTypes = { status: "Official status", reporting: "Reporting", discussion: "Community discussion" };
let catalog = null;

function node(tag, className, label) {
  const result = document.createElement(tag);
  result.className = className;
  if (label) result.textContent = label;
  return result;
}

function render() {
  if (!catalog) return;
  const query = element("source-search").value.trim().toLowerCase();
  const filter = element("source-filter").value;
  const { sources, topics } = catalog;
  const rows = [];
  for (const source of sources) {
    const flag = Object.hasOwn(statusLabels, source.freshness) ? source.freshness : "pending";
    const meta = [sourceTypes[source.coverage] || "Publisher update", source.region, topics[source.topic]];
    if (filter !== "all" && filter !== flag) continue;
    if (![source.label, ...meta].join(" ").toLowerCase().includes(query)) continue;

    const row = node("article", "source-row");
    const identity = node("div", "source-identity");
    identity.append(node("h2", "", source.label), node("p", "muted", meta.filter(Boolean).join(" · ")));
    const timing = node("div", "source-timing");
    timing.append(node("span", `source-state source-state-${flag}`, statusLabels[flag]));
    if (source.checked_at) {
      const time = node("time", "muted", `Checked ${new Date(source.checked_at).toLocaleString()}`);
      time.dateTime = source.checked_at;
      if (source.last_success) time.title = `Last successful check ${new Date(source.last_success).toLocaleString()}`;
      timing.append(time);
    }
    const actions = node("div", "directory-actions");
    if (source.enabled) {
      const stories = node("a", "button secondary", "View stories");
      stories.href = `/?${new URLSearchParams({ publisher: source.id, window: "7d" })}#reading-room`;
      actions.append(stories);
    }
    const feed = node("a", "text-button", "RSS ↗");
    try {
      const url = new URL(source.feed_url);
      if (url.protocol === "https:") {
        feed.href = url.href;
        feed.title = `${source.label} feed`;
        feed.target = "_blank";
        feed.rel = "noopener noreferrer";
        actions.append(feed);
      }
    } catch {}
    row.append(identity, timing, actions);
    rows.push(row);
  }
  const status = rows.length ? `${rows.length} of ${sources.length} sources` : "No sources match your search.";
  element("source-status").textContent = status;
  element("source-rows").replaceChildren(...rows);
}

async function loadSources() {
  element("source-retry").hidden = true;
  element("source-status").textContent = "Loading sources…";
  try {
    const response = await fetch("/api/sources", { signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw new Error();
    catalog = await response.json();
    render();
  } catch {
    element("source-status").textContent = "Sources could not be loaded.";
    element("source-retry").hidden = false;
  }
}

element("source-search").addEventListener("input", render);
element("source-filter").addEventListener("change", render);
element("source-retry").addEventListener("click", loadSources);
loadSources();
