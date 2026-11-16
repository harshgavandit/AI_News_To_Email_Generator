import { coverageLabels, fillOptions, languageOptions, regionId, regionOptions, topicOptions } from "./catalog.js";

const element = (id) => document.getElementById(id);
const statusLabels = {
  fresh: "Up to date",
  stale: "Check overdue",
  failed: "Last check failed",
  pending: "Awaiting first check",
  paused: "Paused",
};
const filters = [
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
    const type = [labels.coverage[coverage], source.integration && source.integration !== "rss" ? "Official API" : "RSS / Atom"].filter(Boolean).join(" · ");
    const focus = labels.topic[source.topic];
    const keywords = normalize([source.label, location, labels.region[region], type, focus, statusLabels[freshness]].join(" "));
    return { ...source, freshness, region, coverage, location, type, focus, keywords };
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
