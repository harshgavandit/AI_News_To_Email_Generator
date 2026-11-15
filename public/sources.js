"use strict";
import { coverageLabels, fillOptions, languageOptions, regionId, regionOptions, topicOptions } from "./catalog.js";

const element = (id) => document.getElementById(id);
const statusLabels = {
  fresh: "Up to date",
  stale: "Check overdue",
  failed: "Last check failed",
  pending: "Awaiting first check",
  paused: "Paused",
};
const filters = ["source-search", "source-region", "source-topic", "source-coverage", "source-filter", "source-language"];
const normalize = (value) => value.normalize("NFKD").replace(/(\p{Script=Latin})\p{Mark}+/gu, "$1").toLowerCase();
let catalog = null;

function node(tag, className, label) {
  const result = document.createElement(tag);
  result.className = className;
  if (label) result.textContent = label;
  return result;
}

function render() {
  if (!catalog) return;
  const query = normalize(element("source-search").value.trim());
  const status = element("source-filter").value;
  const region = element("source-region").value;
  const topic = element("source-topic").value;
  const coverage = element("source-coverage").value;
  const language = element("source-language").value;
  const { sources, topics, regions, coverageTypes, languages } = catalog;
  const rows = [];
  for (const source of sources) {
    const flag = Object.hasOwn(statusLabels, source.freshness) ? source.freshness : "pending";
    const sourceRegion = regionId(source);
    const regionLabel = sourceRegion === "Global" ? "Global" :
      source.region && source.region !== sourceRegion ? source.region : regions[sourceRegion] || sourceRegion;
    const sourceType = source.kind === "video" ? "Creator video" : coverageTypes[source.coverage];
    const meta = [sourceType, regionLabel, topics[source.topic], languages[source.language]];
    if ((status && status !== flag) || (region && region !== sourceRegion) ||
        (topic && topic !== source.topic) || (coverage && coverage !== source.coverage) ||
        (language && language !== source.language)) continue;
    if (!normalize([source.label, regions[sourceRegion], ...meta].join(" ")).includes(query)) continue;

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
      stories.setAttribute("aria-label", `View stories from ${source.label}`);
      actions.append(stories);
    }
    const feed = node("a", "text-button", "Feed ↗");
    try {
      const url = new URL(source.feed_url);
      if (url.protocol === "https:" && !url.username && !url.password) {
        feed.href = url.href;
        feed.setAttribute("aria-label", `Open ${source.label} feed`);
        feed.target = "_blank";
        feed.rel = "noopener noreferrer";
        actions.append(feed);
      }
    } catch {}
    row.append(identity, timing, actions);
    rows.push(row);
  }
  element("source-status").textContent = rows.length ?
    `${rows.length} of ${sources.length} sources` : "No sources match these filters.";
  element("source-reset").hidden = !query && !status && !region && !topic && !coverage && !language;
  element("source-rows").replaceChildren(...rows);
}

async function loadSources() {
  element("source-retry").hidden = true;
  element("source-status").textContent = "Loading sources…";
  element("source-rows").setAttribute("aria-busy", "true");
  try {
    const response = await fetch("/api/sources", { signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw new Error();
    const data = await response.json();
    catalog = {
      sources: data.sources.sort((a, b) => a.label.localeCompare(b.label)),
      topics: topicOptions(data.topics),
      regions: regionOptions(data.regions),
      coverageTypes: data.coverage_types || coverageLabels,
      languages: data.languages || languageOptions,
    };
    fillOptions(element("source-region"), catalog.regions, "All regions");
    fillOptions(element("source-topic"), catalog.topics, "All topics");
    fillOptions(element("source-coverage"), catalog.coverageTypes, "All source types");
    fillOptions(element("source-language"), catalog.languages, "All languages");
    render();
  } catch {
    element("source-status").textContent = "Sources could not be loaded.";
    element("source-retry").hidden = false;
  } finally {
    element("source-rows").setAttribute("aria-busy", "false");
  }
}

for (const [index, id] of filters.entries())
  element(id).addEventListener(index ? "change" : "input", render);
element("source-reset").addEventListener("click", () => {
  for (const id of filters) element(id).value = "";
  render();
  element("source-search").focus();
});
element("source-retry").addEventListener("click", loadSources);
loadSources();
