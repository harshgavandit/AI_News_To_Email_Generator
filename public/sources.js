import { coverageLabels, fillOptions, languageOptions, regionId, regionOptions, topicOptions } from "./catalog.js";

const element = (id) => document.getElementById(id);
const statusLabels = {
  fresh: "Check successful",
  stale: "Check overdue",
  failed: "Last check failed",
  pending: "Awaiting first check",
  paused: "Paused",
};
const filters = [
  ["format", "source-format", "All formats"],
  ["region", "source-region", "All regions"],
  ["topic", "source-topic", "All topics"],
  ["coverage", "source-coverage", "All source types"],
  ["freshness", "source-filter", "Any status"],
  ["language", "source-language", "All languages"],
];
const normalize = (value) => value.normalize("NFKD").replace(/(\p{Script=Latin})\p{Mark}+/gu, "$1").toLowerCase();
const recentDateTime = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const fullDateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const number = new Intl.NumberFormat();
const search = element("source-search");
const filterToggle = element("directory-filter-toggle");
let catalog = null;

function node(tag, className, label) {
  const result = document.createElement(tag);
  result.className = className;
  if (label) result.textContent = label;
  return result;
}

function prepareCatalog(data) {
  const labels = {
    format: {news: "News", blog: "Technical blogs", newsletter: "Newsletters", paper: "Research papers", release: "Project releases", video: "Video channels", podcast: "Podcasts"},
    region: regionOptions(data.regions),
    topic: topicOptions(data.topics),
    coverage: { ...(data.coverage_types || coverageLabels), creator: "Creator videos" },
    freshness: statusLabels,
    language: data.languages || languageOptions,
  };
  const sources = data.sources.map((source) => {
    const region = regionId(source);
    const coverage = source.kind === "video" ? "creator" : source.coverage;
    const freshness = Object.hasOwn(statusLabels, source.freshness) ? source.freshness : "pending";
    const regionLabel = region === "Global" ? "Global" :
      source.region && source.region !== region ? source.region : labels.region[region];
    const location = [regionLabel, labels.language[source.language]].filter(Boolean).join(" · ");
    const type = [labels.coverage[coverage], source.integration === "news-sitemap" ? "Publisher news sitemap" :
      source.integration === "publisher-metadata" ? "Publisher metadata" :
      source.integration && source.integration !== "rss" ? "Official API" : "RSS / Atom"].filter(Boolean).join(" · ");
    const focus = labels.topic[source.topic];
    const format = source.format || (source.kind === "video" ? "video" : source.kind === "podcast" ? "podcast" : "blog");
    const keywords = normalize([source.label, location, labels.region[region], type, focus, labels.format[format], source.collection, statusLabels[freshness]].join(" "));
    return { ...source, format, freshness, region, coverage, location, type, focus, keywords };
  }).sort((a, b) => a.label.localeCompare(b.label));
  return { labels, sources };
}

function showOverview(sources) {
  const fresh = sources.filter((source) => source.freshness === "fresh").length;
  element("source-fresh-count").textContent = `${number.format(fresh)} / ${number.format(sources.length)}`;
  element("source-region-count").textContent = number.format(new Set(sources.map((source) => source.region).filter(Boolean)).size);
  element("source-language-count").textContent = number.format(new Set(sources.map((source) => source.language).filter(Boolean)).size);
  element("directory-overview").hidden = !sources.length;
}

function timestamp(value, prefix) {
  if (!value) return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  const dateTime = date.getFullYear() === new Date().getFullYear() ? recentDateTime : fullDateTime;
  const time = node("time", "directory-timestamp", `${prefix} ${dateTime.format(date)}`);
  time.dateTime = value;
  time.title = `${prefix} ${fullDateTime.format(date)}`;
  return time;
}

function sourceRow(source) {
  const row = node("li", "directory-row");
  const identity = node("div", "directory-identity");
  identity.append(node("h2", "", source.label), node("p", "", source.location));

  const coverage = node("div", "directory-coverage");
  if (source.focus) coverage.append(node("strong", "", source.focus));
  if (source.type) coverage.append(node("span", "", source.type));
  if (source.format) coverage.append(node("span", "", `${source.format} · checks every ${source.refresh_minutes || 5} min`));

  const health = node("div", "directory-health");
  health.append(node("span", `directory-state directory-state-${source.freshness}`, statusLabels[source.freshness]));
  const checked = timestamp(source.checked_at, "Checked");
  if (checked) health.append(checked);
  if (source.last_success !== source.checked_at) {
    const successful = timestamp(source.last_success, "Last success");
    if (successful) health.append(successful);
  }
  const retry = source.retry_at && new Date(source.retry_at) > new Date() ? timestamp(source.retry_at, "Retry after") : null;
  if (retry) health.append(retry);
  const published = timestamp(source.latest_published_at, "Latest story");
  if (published) health.append(published);
  else if (source.checked_at && source.available) health.append(node("span", "directory-timestamp", "No retained stories"));
  if (source.content_status === "quiet") health.append(node("span", "directory-timestamp", "No new retained stories in 30 days"));
  const history = node("details", "source-history");
  history.append(node("summary", "", "Check history"));
  const historyText = node("p", "directory-timestamp");
  historyText.setAttribute("role", "status");
  history.append(historyText);
  let loaded = false;
  history.addEventListener("toggle", async () => {
    if (!history.open || loaded) return;
    historyText.textContent = "Loading recent checks…";
    try {
      const response = await fetch(`/api/discovery/sources/${encodeURIComponent(source.id)}/health`, {signal: AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error();
      const {history: data} = await response.json();
      historyText.textContent = data.checks ? `${data.successful} of ${data.checks} checks succeeded in ${data.hours}h${data.average_duration_ms !== null ? ` · average ${(data.average_duration_ms / 1000).toFixed(1)}s` : ""}.` : "No checks recorded in the last 24 hours.";
      loaded = true;
    } catch { historyText.textContent = "History is unavailable. Close and reopen to retry."; }
  });
  health.append(history);

  const links = node("div", "directory-links");
  if (source.enabled) {
    const stories = node("a", "button secondary", "View stories");
    stories.href = `/?${new URLSearchParams({ publisher: source.id, window: "7d" })}#reading-room`;
    stories.setAttribute("aria-label", `View stories from ${source.label}`);
    links.append(stories);
  }
  try {
    const url = new URL(source.feed_url);
    if (url.protocol === "https:" && !url.username && !url.password) {
      const feed = node("a", "text-button", source.integration && source.integration !== "rss" ? "API ↗" : "Feed ↗");
      feed.href = url.href;
      feed.setAttribute("aria-label", `Open ${source.label} feed in a new tab`);
      feed.target = "_blank";
      feed.rel = "noopener noreferrer";
      links.append(feed);
    }
  } catch { /* Skip malformed feed URLs. */ }
  row.append(identity, coverage, health, links);
  return row;
}

function showMessage(title, detail, action) {
  element("source-message-title").textContent = title;
  element("source-message-detail").textContent = detail;
  element("source-retry").hidden = action !== "retry";
  element("source-clear-empty").hidden = action !== "reset";
  element("source-message").hidden = !title;
}

function render() {
  if (!catalog) return;
  const { labels, sources } = catalog;
  const query = normalize(search.value.trim()).split(/\s+/).filter(Boolean);
  const selected = filters.map(([key, id]) => [key, element(id).value]);
  const filterCount = selected.filter(([, value]) => value).length;
  const filtered = query.length > 0 || filterCount > 0;
  filterToggle.textContent = filterCount ? `Filters (${filterCount})` : "Filters";
  const searchMatches = sources.filter((source) => query.every((term) => source.keywords.includes(term)));
  const matches = (source, omit) => selected.every(([key, value]) => key === omit || !value || source[key] === value);
  const rows = searchMatches.filter((source) => matches(source));

  for (const [key, id, allLabel] of filters) {
    const counts = Object.fromEntries(Object.keys(labels[key]).map((value) => [value, 0]));
    for (const source of searchMatches) {
      if (matches(source, key)) {
        counts[source[key]] = (counts[source[key]] || 0) + 1;
      }
    }
    fillOptions(element(id), labels[key], allLabel, counts);
  }

  const totalLabel = `${number.format(sources.length)} source${sources.length === 1 ? "" : "s"}`;
  element("source-status").textContent = filtered ? `${number.format(rows.length)} of ${totalLabel}` : totalLabel;
  element("source-reset").hidden = !filtered;
  element("source-columns").hidden = !rows.length;
  element("source-rows").hidden = !rows.length;
  element("source-rows").replaceChildren(...rows.map(sourceRow));
  if (rows.length) {
    showMessage("", "");
  } else if (filtered) {
    showMessage("No matching sources", "Try another search or clear your filters.", "reset");
  } else {
    showMessage("No sources available", "The directory did not return any feeds. Try loading it again.", "retry");
  }
}

function resetFilters() {
  search.value = "";
  for (const [, id] of filters) element(id).value = "";
  render();
  search.focus();
}

async function loadSources() {
  const retrying = document.activeElement === element("source-retry");
  element("source-status").textContent = "Loading sources…";
  element("directory-filters").disabled = true;
  element("source-results").setAttribute("aria-busy", "true");
  element("source-loading").hidden = false;
  showMessage("", "");
  try {
    const response = await fetch("/api/sources", { signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw new Error();
    catalog = prepareCatalog(await response.json());
    showOverview(catalog.sources);
    render();
    element("directory-filters").disabled = false;
    if (retrying) search.focus();
  } catch {
    element("source-status").textContent = "Could not load sources.";
    showMessage("The directory is unavailable", "Check your connection and try loading the sources again.", "retry");
    if (retrying) element("source-retry").focus();
  } finally {
    element("source-loading").hidden = true;
    element("source-results").setAttribute("aria-busy", "false");
  }
}

search.addEventListener("input", render);
filterToggle.addEventListener("click", () => {
  const expanded = filterToggle.getAttribute("aria-expanded") === "true";
  filterToggle.setAttribute("aria-expanded", String(!expanded));
});
for (const [, id] of filters) element(id).addEventListener("change", render);
element("source-reset").addEventListener("click", resetFilters);
element("source-clear-empty").addEventListener("click", resetFilters);
element("source-retry").addEventListener("click", loadSources);
loadSources();

async function loadCoverage() {
  try {
    const response = await fetch("/api/discovery/coverage", { signal: AbortSignal.timeout(20000) });
    if (!response.ok) throw new Error();
    const data = await response.json();
    element("coverage-formats").replaceChildren(...(data.formats || []).map((format) => {
      const button = node("button", "topic-chip", `${format.label} · ${format.sources}`);
      button.type = "button";
      button.addEventListener("click", () => {
        element("source-format").value = format.id;
        filterToggle.setAttribute("aria-expanded", "true");
        render();
        search.focus();
      });
      return button;
    }));
    element("coverage-topics").replaceChildren(...data.topics.map((topic) => {
      const card = node("a", "coverage-topic");
      card.href = `/?${new URLSearchParams({topic: topic.id, window: "24h"})}#reading-room`;
      card.append(node("strong", "", topic.label), node("span", "", `${number.format(topic.articles_24h)} stories · ${topic.fresh_feeds}/${topic.feeds} feeds current`));
      return card;
    }));
  } catch { element("coverage-status").textContent = "Coverage counts are temporarily unavailable."; }
}
loadCoverage();

element("story-check-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  element("story-check-status").textContent = "Checking the archive…";
  element("story-check-results").replaceChildren();
  try {
    const response = await fetch(`/api/discovery/check?${new URLSearchParams({url: element("story-check-url").value.trim()})}`, {signal: AbortSignal.timeout(20000)});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Coverage check is unavailable.");
    const labels = { indexed: "This story is indexed. Open it below; your reading filters may have hidden it.",
      unsupported_source: "This publisher is not currently integrated. Paste the original publisher URL if you used a sharing link.",
      awaiting_sync: "This publisher is integrated and awaiting its first synchronization.",
      source_unavailable: "The publisher is integrated, but its sources are currently unavailable or paused.",
      not_in_archive: "This article is not in the retained archive. The publisher’s feeds may omit it or it may be outside the 90-day window." };
    element("story-check-status").textContent = labels[data.status] || "Coverage check completed.";
    const content = element("story-check-results");
    for (const article of data.articles || []) {
      const link = node("a", "coverage-match", article.title);
      link.href = `/?${new URLSearchParams({article: article.id})}#reading-room`;
      content.append(link);
    }
    for (const source of data.sources || []) content.append(node("p", "muted", `${source.label}: ${statusLabels[source.freshness] || source.freshness}${source.retry_at ? ` · retry after ${fullDateTime.format(new Date(source.retry_at))}` : ""}`));
  } catch (error) { element("story-check-status").textContent = error.message || "Could not check coverage. Try again."; }
  finally { button.disabled = false; }
});
