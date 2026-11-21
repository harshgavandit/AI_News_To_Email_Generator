import { node, readableError, requestJSON, sourceList } from "./evidence-ui.js";
import { developmentLink } from "./development-link.js";
import { impactPanel } from "./personal-impact.js";
import { followedStories, saveStoryFollow } from "./technology-follow.js";
import { freshnessNotice } from "./reader-freshness.js";

const id = new URLSearchParams(location.search).get("id");
const status = document.getElementById("development-page-status");
const content = document.getElementById("development-content");

function panel(title, ...items) {
  const section = node("section", null, "research-panel");
  section.append(node("h2", title), ...items);
  return section;
}

function render(data) {
  const heading = document.getElementById("development-title");
  document.title = `${data.title} · Informa AI`;
  heading.textContent = data.title;
  const sources = [...new Map(data.entries.map(row => [row.source.id, row.source])).values()];
  const official = sources.filter(row => ["status", "release", "advisory"].includes(row.coverage));
  const reporting = sources.filter(row => row.coverage === "reporting");
  const other = sources.filter(row => !official.includes(row) && !reporting.includes(row));
  const labels = { official: "Official status, advisories, and release notes",
    reporting: "Independent reporting", other: "Other publisher evidence" };
  const actions = node("div", null, "reader-actions");
  const follow = node("button", null, "button secondary");
  const share = node("button", "Copy development link", "button secondary");
  follow.type = share.type = "button";
  function reflectFollow() {
    const active = followedStories().includes(id);
    follow.setAttribute("aria-pressed", String(active));
    follow.textContent = active ? "Unfollow development" : "Follow development";
  }
  reflectFollow();
  follow.addEventListener("click", () => {
    try {
      saveStoryFollow(id, !followedStories().includes(id));
      reflectFollow();
      status.textContent = "Follow updated in this browser. Save your Tech Radar to sync it to your verified inbox.";
    } catch (error) { status.textContent = readableError(error); }
  });
  share.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(new URL(developmentLink(id), location.origin).href);
      status.textContent = "Development link copied.";
    } catch { status.textContent = "Copy the development link from your address bar."; }
  });
  actions.append(follow, share);
  content.append(actions);
  const freshness = freshnessNotice(data.coverage_freshness);
  if (freshness) content.append(freshness);
  const latest = data.latest_material || data.entries[0];
  if (latest) {
    const latestSource = { ...latest.source, title: latest.title, excerpt: latest.excerpt };
    const ask = node("a", "Analyze this evidence in Research Desk ↗");
    ask.href = `/research.html?article=${encodeURIComponent(latest.source.id)}`;
    content.append(panel("Latest reported change", node("p", latest.change_label, "research-meta"),
      sourceList([latestSource]), ask), impactPanel(latest.source.id));
  }
  const timeline = sourceList(data.entries.map(row => ({ ...row.source, title: row.title,
    published_at: row.published_at, excerpt: row.excerpt, change_label: row.change_label, observed: row.observed })),
  (entry, row) => {
    const observed = new Date(row.observed * 1000);
    entry.append(node("p", `${row.change_label} · Observed ${observed.toLocaleString()}`, "research-meta"));
  });
  content.append(panel("Timeline", node("p", data.notice, "research-meta"), timeline));
  for (const [key, rows] of Object.entries({ official, reporting, other })) {
    if (rows.length) content.append(panel(labels[key], sourceList(rows.map(row => ({ ...row, excerpt: row.cleanSummary })))));
  }
  content.append(panel("Open questions and evidence limits", node("p", official.length
    ? "Check each source for details beyond its excerpt. Grouping these reports does not establish publisher agreement."
    : "No official status report, advisory, or release note is linked to this development in the retained archive.")));
}

async function load() {
  if (!developmentLink(id)) {
    status.textContent = "Choose a development from Catch up or the Research Desk.";
    content.setAttribute("aria-busy", "false");
    return;
  }
  try {
    const data = await requestJSON(`/api/intelligence/events/${id}`, { signal: AbortSignal.timeout(15000) });
    render(data);
    status.textContent = "";
  } catch (error) {
    status.textContent = readableError(error);
    const retry = node("button", "Try again", "button secondary");
    retry.type = "button";
    retry.addEventListener("click", () => { status.textContent = "Loading the timeline…"; load(); });
    status.append(" ", retry);
  } finally { content.setAttribute("aria-busy", "false"); }
}

load();
