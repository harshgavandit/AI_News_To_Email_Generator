import { coverageLabels, fillOptions, languageOptions, regionId, regionOptions, topicOptions } from "./catalog.js";

const element = (id) => document.getElementById(id);
const statusLabels = {
  fresh: "Check successful",
  stale: "Check overdue",
  failed: "Last check failed",
  pending: "Awaiting first check",
  paused: "Paused",
};
// Feed health separates a working feed with nothing new from one that cannot be reached.
const healthLabels = {
  active: "Publishing",
  quiet: "Working · no recent posts",
  temporarily_unavailable: "Temporarily unavailable",
  broken: "Broken or discontinued",
  pending: "Awaiting first check",
  paused: "Paused",
};
const integrationLabels = {
  "news-sitemap": "Publisher news sitemap",
  "publisher-metadata": "Publisher metadata",
  "release-notes": "Official release notes",
  rss: "RSS / Atom",
};
const errorLabels = {
  access_denied: "Publisher denied feed access",
  api_unavailable: "Publisher API unavailable",
  rate_limited: "Publisher temporarily rate-limited checks",
  fetch_failed: "Feed could not be reached",
  parser_failed: "Feed response could not be read",
};
const pageSize = 36;
const filters = [
  ["format", "source-format", "All formats"],
  ["region", "source-region", "All regions"],
  ["topic", "source-topic", "All topics"],
  ["coverage", "source-coverage", "All source types"],
  ["freshness", "source-filter", "Any status"],
  ["health", "source-health", "Any health"],
  ["language", "source-language", "All languages"],
];
const normalize = (value) => value.normalize("NFKD").replace(/(\p{Script=Latin})\p{Mark}+/gu, "$1").toLowerCase();
const recentDateTime = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const fullDateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const number = new Intl.NumberFormat();
const search = element("source-search");
const filterToggle = element("directory-filter-toggle");
let catalog = null;
let matchingSources = [];
let shown = 0;

const refreshSchedules = {
  four_times_daily: "Checked 4× daily · 2:00, 8:00, 14:00, 20:00 IST",
  twice_daily: "Checked twice daily · 8:00 and 20:00 IST",
  daily: "Checked daily · 8:00 IST",
};

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
    health: healthLabels,
    language: data.languages || languageOptions,
  };
  const sources = data.sources.map((source) => {
    const region = regionId(source);
    const coverage = source.kind === "video" && source.topic === "video" ? "creator" : source.coverage;
    const freshness = Object.hasOwn(statusLabels, source.freshness) ? source.freshness : "pending";
    const health = Object.hasOwn(healthLabels, source.health) ? source.health : freshness === "paused" ? "paused" : "pending";
    const regionLabel = region === "Global" ? "Global" :
      source.region && source.region !== region ? source.region : labels.region[region];
    const location = [regionLabel, labels.language[source.language]].filter(Boolean).join(" · ");
    const integration = source.integration || "rss";
    const type = [labels.coverage[coverage], integrationLabels[integration] || "Official API"].filter(Boolean).join(" · ");
    const focus = labels.topic[source.topic];
    const format = source.format || (source.kind === "video" ? "video" : source.kind === "podcast" ? "podcast" : "blog");
    const keywords = normalize([source.label, location, labels.region[region], type, focus, labels.format[format], source.collection, statusLabels[freshness], healthLabels[health]].join(" "));
    return { ...source, format, freshness, health, region, coverage, location, type, focus, keywords };
  }).sort((a, b) => a.label.localeCompare(b.label));
  return { labels, sources };
}

function showOverview(sources) {
  const fresh = sources.filter((source) => source.freshness === "fresh").length;
  element("source-fresh-count").textContent = `${number.format(fresh)} / ${number.format(sources.filter((source) => source.enabled).length)}`;
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
  if (source.format) {
    const schedule = refreshSchedules[source.refresh_policy] || "Checked on a schedule";
    coverage.append(node("span", "", schedule));
  }

  const health = node("div", "directory-health");
  health.append(node("span", `directory-state directory-state-${source.freshness}`, statusLabels[source.freshness]));
  if (source.health && source.health !== "pending" && source.health !== "paused")
    health.append(node("span", `directory-health-state directory-health-${source.health}`, healthLabels[source.health]));
  if (source.error && errorLabels[source.error]) health.append(node("span", "directory-timestamp", errorLabels[source.error]));
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
  if (source.content_status === "quiet" && source.health === "quiet") health.append(node("span", "directory-timestamp", "No new retained stories in 30 days"));
  const history = node("details", "source-history");
  const historyLabel = node("summary", "", "Check history");
  historyLabel.setAttribute("aria-label", `Check history for ${source.label}`);
  history.append(historyLabel);
  const historyText = node("p", "directory-timestamp");
  historyText.setAttribute("role", "status");
  history.append(historyText);
  let loaded = false, loading = false;
  history.addEventListener("toggle", async () => {
    if (!history.open || loaded || loading) return;
    loading = true;
    historyText.textContent = "Loading recent checks…";
    try {
      const response = await fetch(`/api/discovery/sources/${encodeURIComponent(source.id)}/health`, {signal: AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error();
      const {history: data} = await response.json();
      historyText.textContent = data.checks ? `${data.successful} of ${data.checks} checks succeeded in ${data.hours}h${data.average_duration_ms !== null ? ` · average ${(data.average_duration_ms / 1000).toFixed(1)}s` : ""}.` : "No checks recorded in the last 24 hours.";
      const activity = node("ol", "source-check-activity");
      for (const record of (data.recent || []).slice(0, 5)) {
        const checked = new Date(Number(record.checked) * 1000);
        if (!Number.isFinite(checked.getTime())) continue;
        const entry = node("li", "");
        const time = timestamp(checked.toISOString(), "Checked");
        const outcome = record.available ? (record.unchanged ? "Unchanged" : "Succeeded") :
          (errorLabels[record.error] || "Check failed");
        entry.append(time, node("span", "", outcome));
        activity.append(entry);
      }
      if (activity.childElementCount) history.append(activity);
      loaded = true;
    } catch { historyText.textContent = "History is unavailable. Close and reopen to retry."; }
    finally { loading = false; }
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
      const feedLabel = { "publisher-metadata": "Publisher", "release-notes": "Notes", "news-sitemap": "Sitemap" }[source.integration] ||
        (!source.integration || source.integration === "rss" ? "Feed" : "API");
      const feed = node("a", "text-button", `${feedLabel} ↗`);
      feed.href = url.href;
      feed.setAttribute("aria-label", `Open ${source.label} ${feedLabel.toLowerCase()} in a new tab`);
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

function sourceCount(count) {
  return `${number.format(count)} source${count === 1 ? "" : "s"}`;
}

function showMoreSources({ focus = false } = {}) {
  const next = matchingSources.slice(shown, shown + pageSize).map(sourceRow);
  element("source-rows").append(...next);
  shown += next.length;
  element("directory-pagination").hidden = shown >= matchingSources.length;
  if (shown < matchingSources.length) {
    element("source-more").textContent = `Show ${sourceCount(Math.min(pageSize, matchingSources.length - shown))} more`;
  }
  const status = shown < matchingSources.length ? `${number.format(shown)} shown · ${sourceCount(matchingSources.length)}` : sourceCount(matchingSources.length);
  element("source-status").textContent = matchingSources.length === catalog.sources.length ? status : `${status} matched`;
  if (focus && next.length) {
    const heading = next[0].querySelector("h2");
    heading.tabIndex = -1;
    heading.focus();
  }
}

function reflectFilters() {
  const url = new URL(location.href);
  const items = [];
  const values = [["q", "source-search", search.value.trim()], ...filters.map(([key, id]) => [key, id, element(id).value])];
  for (const [key, id, value] of values) {
    if (!value) {
      url.searchParams.delete(key);
      continue;
    }
    url.searchParams.set(key, value);
    const label = key === "q" ? `Search: ${value}` : catalog.labels[key][value];
    const item = node("li", "");
    const remove = node("button", "topic-chip", `${label} ×`);
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove filter: ${label}`);
    remove.addEventListener("click", () => {
      element(id).value = "";
      render();
      search.focus();
    });
    item.append(remove);
    items.push(item);
  }
  const active = element("directory-active-filters");
  active.replaceChildren(...items);
  active.hidden = !items.length;
  if (url.href !== location.href) history.replaceState(history.state, "", url);
}

function restoreFilters() {
  const params = new URLSearchParams(location.search);
  search.value = (params.get("q") || "").slice(0, 120);
  let hasFilters = false;
  for (const [key, id, allLabel] of filters) {
    fillOptions(element(id), catalog.labels[key], allLabel, undefined, params.get(key) || "");
    hasFilters ||= Boolean(element(id).value);
  }
  filterToggle.setAttribute("aria-expanded", String(hasFilters));
  render();
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

  element("source-reset").hidden = !filtered;
  element("source-columns").hidden = !rows.length;
  element("source-rows").hidden = !rows.length;
  element("source-rows").replaceChildren();
  matchingSources = rows;
  shown = 0;
  showMoreSources();
  reflectFilters();
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

function browseFilter(key, value) {
  if (!catalog) {
    const url = new URL(location.href);
    url.search = "";
    url.searchParams.set(key, value);
    history.replaceState(history.state, "", url);
    return;
  }
  search.value = "";
  for (const [name, id] of filters) element(id).value = name === key ? value : "";
  filterToggle.setAttribute("aria-expanded", "true");
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
    restoreFilters();
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
element("source-more").addEventListener("click", () => showMoreSources({ focus: true }));
window.addEventListener("popstate", () => { if (catalog) restoreFilters(); });
filterToggle.addEventListener("click", () => {
  const expanded = filterToggle.getAttribute("aria-expanded") === "true";
  filterToggle.setAttribute("aria-expanded", String(!expanded));
});
for (const [, id] of filters) element(id).addEventListener("change", render);
element("source-reset").addEventListener("click", resetFilters);
element("source-clear-empty").addEventListener("click", resetFilters);
element("source-retry").addEventListener("click", loadSources);
loadSources();

function showLinkedPanel() {
  if (["#story-check", "#coverage-overview"].includes(location.hash)) {
    element(location.hash.slice(1)).open = true;
  }
}
let coverageLoaded = false, coverageLoading = false;
async function loadCoverage() {
  if (coverageLoaded || coverageLoading) return;
  coverageLoading = true;
  const status = element("coverage-status"), retry = element("coverage-retry");
  retry.hidden = true;
  status.textContent = "Loading coverage and health…";
  try {
    const response = await fetch("/api/discovery/coverage", { signal: AbortSignal.timeout(20000) });
    if (!response.ok) throw new Error();
    const data = await response.json();
    element("coverage-formats").replaceChildren(...(data.formats || []).map((format) => {
      const button = node("button", "topic-chip", `${format.label} · ${format.sources}`);
      button.type = "button";
      button.addEventListener("click", () => browseFilter("format", format.id));
      return button;
    }));
    element("coverage-topics").replaceChildren(...data.topics.map((topic) => {
      const card = node("a", "coverage-topic");
      card.href = `/?${new URLSearchParams({topic: topic.id, window: "24h"})}#reading-room`;
      card.append(node("strong", "", topic.label), node("span", "", `${number.format(topic.articles_24h)} stories · ${topic.fresh_feeds}/${topic.feeds} feeds current`));
      if (topic.gap) card.append(node("span", "coverage-gap", {
        no_sources: "Coverage gap: no reviewed feeds", checks_overdue: "Feed checks need attention",
        no_recent_stories: "No retained stories in the past 24h",
      }[topic.gap] || "Coverage needs review"));
      return card;
    }));
    element("coverage-subjects").replaceChildren(...(data.subjects || []).map((subject) => {
      const chip = node("a", subject.gap ? "topic-chip coverage-subject has-gap" : "topic-chip coverage-subject",
        `${subject.label} · ${number.format(subject.articles_7d)} this week`);
      chip.href = `/?${new URLSearchParams({subject: subject.id, window: "7d"})}#reading-room`;
      if (subject.gap) chip.title = subject.gap === "thin" ? "Few stories this week: a candidate for new sources" : "No stories this week";
      return chip;
    }));
    renderCoverageStatus(data);
    status.textContent = data.notice || "";
    coverageLoaded = true;
  } catch {
    status.textContent = "Coverage counts are temporarily unavailable.";
    retry.hidden = false;
  } finally { coverageLoading = false; }
}
const coverageOverview = element("coverage-overview");
coverageOverview.addEventListener("toggle", () => { if (coverageOverview.open) loadCoverage(); });
element("coverage-retry").addEventListener("click", loadCoverage);
window.addEventListener("hashchange", showLinkedPanel);
showLinkedPanel();
if (coverageOverview.open) loadCoverage();

function renderCoverageStatus(data) {
  const panel = element("coverage-attention"), attention = data.attention, health = data.ingestion;
  const gaps = (data.signals || []).filter(signal => signal.gap);
  panel.replaceChildren();
  panel.hidden = !attention && !health && !gaps.length;
  if (panel.hidden) return;
  panel.append(node("strong", "", "Source monitoring"));
  if (attention) {
    const metrics = node("div", "directory-health-metrics");
    for (const [label, count, filter, key = "freshness"] of [["Failed checks", attention.failed_sources, "failed"],
      ["Overdue checks", attention.overdue_sources, "stale"], ["Sources quiet for 30 days", attention.quiet_sources, "quiet", "health"],
      ["Temporarily unavailable", attention.temporarily_unavailable_sources, "temporarily_unavailable", "health"],
      ["Broken or discontinued", attention.broken_sources, "broken", "health"]]) {
      if (count === undefined) continue;
      const metric = node(filter && count ? "button" : "span", "directory-health-metric", `${label}: ${number.format(count)}`);
      if (metric.tagName === "BUTTON") {
        metric.type = "button";
        metric.addEventListener("click", () => browseFilter(key, filter));
      }
      metrics.append(metric);
    }
    panel.append(metrics);
  }
  if (health) {
    const status = {running: "Checks running", backlogged: "Checks behind schedule", stalled: "No recent checks"}[health.status] || "Synchronization status unavailable";
    panel.append(node("p", "", `${status} · ${sourceCount(health.due_sources)} due · ${number.format(health.priority_sources_overdue)} priority feeds past their refresh targets.`));
    const last = timestamp(health.last_check_at, "Latest check");
    if (last) panel.append(last);
  }
  if (gaps.length) panel.append(node("p", "", `Unrepresented in the latest headline sample: ${gaps.map(signal => signal.label).join(", ")}.`));
}

element("story-check-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  if (button.disabled) return;
  button.disabled = true;
  const status = element("story-check-status"), content = element("story-check-results");
  status.textContent = "Checking the archive…";
  content.replaceChildren();
  content.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(`/api/discovery/check?${new URLSearchParams({url: element("story-check-url").value.trim()})}`, {signal: AbortSignal.timeout(20000)});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Coverage check is unavailable.");
    const labels = { indexed: "This story is indexed. Open it below; your reading filters may have hidden it.",
      unsupported_source: "This publisher is not currently integrated. Paste the original publisher URL if you used a sharing link.",
      awaiting_sync: "This publisher is integrated and awaiting its first synchronization.",
      source_unavailable: "The publisher is integrated, but its sources are currently unavailable or paused.",
      not_in_archive: "This article is not in the retained archive. The publisher’s feeds may omit it or it may be outside the 90-day window." };
    status.textContent = labels[data.status] || "Coverage check completed.";
    for (const article of data.articles || []) {
      const link = node("a", "coverage-match", article.title);
      link.href = `/?${new URLSearchParams({article: article.id})}#reading-room`;
      content.append(link);
    }
    for (const source of data.sources || []) {
      const row = node("div", "story-check-source");
      const link = node("a", "", source.label);
      link.href = `/sources.html?${new URLSearchParams({q: source.label})}#source-search`;
      row.append(link, node("span", `directory-state directory-state-${Object.hasOwn(statusLabels, source.freshness) ? source.freshness : "pending"}`,
        statusLabels[source.freshness] || "Check status unavailable"));
      const retry = timestamp(source.retry_at, "Retry after");
      if (retry) row.append(retry);
      content.append(row);
    }
  } catch (error) { status.textContent = error.message || "Could not check coverage. Try again."; }
  finally { button.disabled = false; content.setAttribute("aria-busy", "false"); }
});
