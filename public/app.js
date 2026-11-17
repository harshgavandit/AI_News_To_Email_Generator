"use strict";
import { coverageLabels, fillOptions, languageOptions, optionLabel, originalLanguage, regionId, regionOptions, topicOptions, subjectLabels } from "./catalog.js";
import { initSavedViews } from "./saved-views.js";
import { createPreferences } from "./preferences.js";
import { readingContent } from "./reading-content.js";

const $ = (id) => document.getElementById(id);
const state = {
  articles: [],
  recommendations: [],
  briefing: [],
  recommendationCandidates: 0,
  total: 0,
  cursor: null,
  digest: null,
  sources: [],
  healthSources: [],
  counts: {},
  topics: topicOptions(),
  regions: regionOptions(),
  languages: languageOptions,
  coverageTypes: coverageLabels,
  facets: {},
  controller: null,
  updateCheck: null,
  feedKey: "",
  topic: "all",
  source: "all",
  publisher: "",
  searching: false,
  hours: 12,
  view: "feed",
  pins: new Map(),
  digestSources: new Set(),
  composing: false,
  mail: null,
  pending: null,
  tab: "build",
  delivery: "email",
};
const windows = { 12: "12h", 24: "24h", 168: "7d", 720: "30d", 2160: "90d" };
const defaultSort = (searching) => searching ? "relevance" : "latest";
const node = (tag, className, text) => {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
};
const status = (id, message, error = false) => {
  $(id).textContent = message;
  $(id).classList.toggle("error", error);
};
const readableTime = (value) =>
  value && !Number.isNaN(Date.parse(value))
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "Not checked yet";
const storyAge = new Intl.RelativeTimeFormat(undefined, { numeric: "always" });
function relativeTime(value, precision) {
  if (precision === "day") return new Date(value).toLocaleDateString(undefined, {dateStyle: "medium"});
  const minutes = Math.floor((Date.now() - Date.parse(value)) / 60_000);
  if (!Number.isFinite(minutes) || minutes < 0) return readableTime(value);
  if (minutes === 0) return "Just now";
  if (minutes < 60) return storyAge.format(-minutes, "minute");
  if (minutes < 1440) return storyAge.format(-Math.floor(minutes / 60), "hour");
  return storyAge.format(-Math.floor(minutes / 1440), "day");
}
const externalLink = (url, label) => {
  const a = node("a", "", label);
  try {
    const target = new URL(url);
    if (target.protocol === "https:" && !target.username && !target.password) a.href = target.href;
  } catch {}
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
};
function publisherRegion(record) {
  const id = regionId(record);
  return id === "Global" ? "Global" :
    record.region && record.region !== id ? record.region : state.regions[id] || id;
}
function permittedImage(value) {
  try {
    const image = new URL(value);
    return image.protocol === "https:" && !image.username && !image.password &&
      ["i.ytimg.com", "media.dev.to", "media2.dev.to", "cdn.hashnode.com", "images.unsplash.com",
        "techcrunch.com", "theverge.com", "arstechnica.com", "cdn.arstechnica.net", "media.wired.com",
        "cdn.vox-cdn.com", "platform.theverge.com"].some((host) => image.hostname === host);
  } catch { return false; }
}
function deriveWhyItMatters(article) {
  return article.summary_basis === "ai_feed_summary" ? article.whyItMatters || "" : "";
}
function deriveKeyTakeaway(article) {
  return article.summary_basis === "ai_feed_summary" ? article.keyTakeaway || "" : "";
}
function normalizeEmail(value) {
  let [local, domain] = String(value || "")
    .trim()
    .toLowerCase()
    .split("@");
  if (domain === "gmail.com" || domain === "googlemail.com") {
    local = local.split("+")[0].replaceAll(".", "");
    domain = "gmail.com";
  }
  return `${local}@${domain}`;
}
const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
$("timezone-label").textContent = `(${timezone.replaceAll("_", " ")})`;
const date = new Date();
$("edition-date").dateTime = date.toLocaleDateString("sv-SE");
$("edition-date").textContent = new Intl.DateTimeFormat(undefined, { dateStyle: "full" }).format(date);

const savedKey = "informa-saved-v1";
const readKey = "informa-read-v1";
const layoutKey = "informa-story-layout";
window.addEventListener("storage", (event) => {
  if (event.key === "informa-reader-reset") location.reload();
});
const preferences = createPreferences($("personalization"), () => {
  if (state.view === "for-you") loadNews();
  syncFollowActions();
});
const saved = new Map();
const readStories = new Set();
try {
  const stored = JSON.parse(localStorage.getItem(savedKey) || "[]");
  for (const item of stored.slice(0, 100)) {
    if (typeof item.id === "string" && typeof item.title === "string" && typeof item.url === "string") saved.set(item.id, item);
  }
} catch {}
try {
  const storedRead = JSON.parse(localStorage.getItem(readKey) || "[]");
  for (const id of storedRead) readStories.add(String(id));
} catch {}

function markAsRead(storyId) {
  readStories.add(String(storyId));
  try {
    localStorage.setItem(readKey, JSON.stringify([...readStories].slice(-300)));
  } catch {}
  const card = $("stories")?.querySelector(`[data-story-card-id="${CSS.escape(String(storyId))}"]`);
  if (card) {
    card.classList.add("is-read");
    card.classList.remove("is-unread");
    card.querySelector(".unread-dot")?.remove();
  }
}

function setLayout(layout, persist = false) {
  $("stories").classList.toggle("story-list", layout === "list");
  for (const option of ["cards", "list"])
    $(`layout-${option}`).setAttribute("aria-pressed", String(option === layout));
  if (persist) {
    try { localStorage.setItem(layoutKey, layout); } catch {}
  }
}
for (const option of ["cards", "list"])
  $(`layout-${option}`).addEventListener("click", () => setLayout(option, true));
try {
  setLayout(localStorage.getItem(layoutKey) === "list" ? "list" : "cards");
} catch {}

function reflectSavedCount() {
  $("saved-count").textContent = saved.size;
  $("saved-count").hidden = !saved.size;
  $("sidebar-saved-count").textContent = saved.size || "";
}

function toggleSaved(article) {
  const id = String(article.id);
  const removing = saved.has(id);
  if (!removing && saved.size >= 100) {
    status("news-status", "You can save up to 100 stories. Remove one to save another.", true);
    return;
  }
  const restoreFocus = document.activeElement?.dataset.storyId === id;
  const previousIndex = Array.from($("stories").querySelectorAll(".save-button")).findIndex((button) => button.dataset.storyId === id);
  if (removing) saved.delete(id);
  else saved.set(id, article);
  let persisted = false;
  try {
    localStorage.setItem(savedKey, JSON.stringify([...saved.values()]));
    persisted = true;
  } catch {}
  reflectSavedCount();
  renderStories();
  const actions = Array.from($("stories").querySelectorAll(".save-button"));
  const replacement = actions.find((button) => button.dataset.storyId === id) || actions[Math.min(previousIndex, actions.length - 1)];
  if (restoreFocus) (replacement || $("view-saved")).focus({ preventScroll: Boolean(replacement) });
  status("story-action-status", removing ? `Story removed. ${saved.size} saved.` :
    persisted ? `Story saved. ${saved.size} saved on this browser.` : "Story saved for this session. Browser storage is unavailable.");
}
async function request(url, options = {}) {
  const timeout = AbortSignal.timeout(65_000);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  const response = await fetch(url, { ...options, signal });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("The server is temporarily unavailable. Please try again.");
  }
  if (!response.ok) {
    const error = new Error(
      typeof data.detail === "string"
        ? data.detail
        : "This request could not be completed. Check your settings and try again.",
    );
    error.status = response.status;
    throw error;
  }
  return data;
}
const jsonPost = (url, data) =>
  request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

async function loadHeadlines() {
  try {
    const { coverage, articles } = await request("/api/headlines");
    if (!coverage.length && !articles.length) return;
    const container = $("headlines-content");
    container.classList.toggle("with-coverage", coverage.length > 0);
    container.replaceChildren();
    for (const story of coverage) {
      const feature = node("article", "coverage-lead");
      const updated = node("time", "muted", `Updated ${readableTime(story.updated_at)}`);
      updated.dateTime = story.updated_at;
      const meta = node("div", "coverage-meta");
      meta.append(node("span", "source-badge chips", story.topic), updated);
      const links = node("ul", "coverage-links");
      for (const source of story.sources) {
        const item = node("li");
        const link = externalLink(source.url, source.publisher);
        link.setAttribute("aria-label", `${source.publisher} — ${source.label}`);
        item.append(link, node("span", "muted", source.label));
        links.append(item);
      }
      const search = node("a", "coverage-search", `Browse ${story.query} coverage →`);
      search.href = `/?${new URLSearchParams({ q: story.query, window: "7d", sort: "relevance" })}#reading-room`;
      const actions = node("div", "coverage-actions");
      const sources = node("details");
      sources.append(node("summary", "", `Sources (${story.sources.length})`), links);
      actions.append(sources, search);
      feature.append(meta, node("h3", "", story.title), node("p", "", story.summary), actions);
      container.append(feature);
    }
    if (articles.length) {
      const list = node("ul", "headline-list");
      for (const article of articles) {
        const item = node("li");
        const heading = node("h3");
        if (article.language) heading.lang = article.language;
        heading.append(externalLink(article.url, article.title));
        const date = node("time", "", relativeTime(article.published_at, article.publication_date_precision));
        date.dateTime = article.published_at;
        date.title = readableTime(article.published_at);
        const attribution = node("p", "muted", `${[article.publisher, publisherRegion(article)].filter(Boolean).join(" · ")} · `);
        attribution.append(date);
        item.append(node("span", "headline-topic", article.topic_label), heading, attribution);
        list.append(item);
      }
      container.append(list);
    }
    const readingRoom = $("reading-room");
    const previousTop = readingRoom.getBoundingClientRect().top;
    $("headlines").hidden = false;
    const anchorTop = Number.parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
    if (location.hash === "#reading-room" && Math.abs(previousTop - anchorTop) < 40) {
      const offset = readingRoom.getBoundingClientRect().top - previousTop;
      if (offset > 0) window.scrollBy({ top: offset, behavior: "instant" });
    }
  } catch {
    // Browsing and search still work when the optional headlines request fails.
  }
}

async function loadSignals() {
  try {
    const data = await request("/api/signals");
    const articles = data.articles || [];
    $("signals-content").replaceChildren(...articles.slice(0, 6).map((article) => {
      const item = node("article", "priority-signal");
      const open = node("button", "", article.title);
      open.type = "button";
      open.dir = "auto";
      open.addEventListener("click", () => openDossier(article, open));
      item.append(node("span", "signal-type", article.signal_reason), open,
        node("p", "muted", `${article.publisher} · ${relativeTime(article.published_at, article.publication_date_precision)}`));
      return item;
    }));
    $("priority-signals").hidden = !articles.length;
  } catch { /* Optional; search and reading continue when signals are unavailable. */ }
}
function readingFilters() {
  return {
    source: state.source,
    window: windows[state.hours],
    q: $("search").value.trim(),
    topic: state.topic,
    region: $("region").value,
    publisher: state.publisher,
    kind: $("kind").value,
    coverage: $("coverage").value,
    language: $("language").value,
    subject: $("subject").value,
    sort: $("sort").value === defaultSort(state.searching) ? "" : $("sort").value,
  };
}

function syncURL() {
  $("archive-search").hidden = !$("search").value.trim() || state.hours === 2160 || state.view === "saved";
  const url = new URL(location.href);
  for (const [key, value] of Object.entries(readingFilters())) {
    if (!value || value === "all") url.searchParams.delete(key);
    else url.searchParams.set(key, value);
  }
  if (state.view !== "feed") url.searchParams.set("view", state.view);
  else url.searchParams.delete("view");
  history.replaceState(null, "", url);
  reflectWorkspace();
  $("clear-search").hidden = !$("search").value;
  const currentQuery = $("search").value.trim().toLowerCase();
  for (const chip of $("trending-chips")?.children || []) {
    chip.setAttribute("aria-pressed", String(currentQuery && chip.dataset.query?.toLowerCase() === currentQuery));
  }
  const count = Number(state.source !== "all") + Number(Boolean(state.publisher)) +
    Number($("kind").value !== "all") + Number(Boolean($("coverage").value)) + Number(Boolean($("language").value)) + Number(Boolean($("subject").value));
  $("filter-count").hidden = !count;
  $("filter-count").textContent = count;
  $("filter-high-signal").setAttribute("aria-pressed", String($("coverage").value === "reporting"));
  $("filter-articles").setAttribute("aria-pressed", String($("coverage").value === "article"));
  $("filter-releases").setAttribute("aria-pressed", String($("coverage").value === "release"));
  const baseHours = state.view === "for-you" ? 168 : 12;
  $("reset-filters").hidden = ["saved", "briefing"].includes(state.view) ||
    (!count && !$("region").value && state.topic === "all" && state.hours === baseHours && !state.searching && $("sort").value === "latest");
  renderActiveFilters();
}

function renderActiveFilters() {
  const filters = $("active-filters");
  const selectLabel = (id) => $(id).selectedOptions[0]?.textContent;
  const publisher = state.sources.find((source) => source.id === state.publisher)?.label || state.publisher;
  const group = state.sources.find((source) => source.id === state.source)?.label ||
    ({ openai: "OpenAI", anthropic: "Anthropic", youtube: "YouTube", medium: "Medium", dev: "DEV Community" })[state.source] || state.source;
  const active = [
    [state.source !== "all" && group, () => { state.source = "all"; }],
    [state.publisher && publisher, () => { state.publisher = $("publisher").value = ""; }],
    [$("kind").value !== "all" && selectLabel("kind"), () => { $("kind").value = "all"; }],
    [$("coverage").value && selectLabel("coverage"), () => { $("coverage").value = ""; }],
    [$("language").value && selectLabel("language"), () => { $("language").value = ""; }],
    [$("subject").value && selectLabel("subject"), () => { $("subject").value = ""; }],
  ].filter(([label]) => label);
  filters.replaceChildren();
  filters.hidden = !active.length;
  for (const [label, reset] of active) {
    const button = node("button", "topic-chip", `${label} ×`);
    button.type = "button";
    button.setAttribute("aria-label", `Remove ${label} filter`);
    button.addEventListener("click", () => {
      reset();
      $("filter-toggle").focus();
      loadNews();
    });
    filters.append(button);
  }
}
function restoreURL() {
  const params = new URLSearchParams(location.search);
  state.source = params.get("source") || "all";
  state.publisher = params.get("publisher") || "";
  $("publisher").value = state.publisher;
  const windowValue = params.get("window");
  state.hours = Number(Object.keys(windows).find((hours) => windows[hours] === windowValue || hours === windowValue)) ||
    (params.get("view") === "for-you" ? 168 : 12);
  state.topic = Object.hasOwn(state.topics, params.get("topic")) ? params.get("topic") : "all";
  $("search").value = (params.get("q") || "").slice(0, 150);
  state.searching = Boolean($("search").value.trim());
  $("region").value = params.get("region") || "";
  $("kind").value = params.get("kind") || "all";
  $("coverage").value = params.get("coverage") || "";
  $("language").value = params.get("language") || "";
  $("subject").value = params.get("subject") || "";
  if ($("kind").selectedIndex === -1) $("kind").value = "all";
  if ($("coverage").selectedIndex === -1) $("coverage").value = "";
  if ($("language").selectedIndex === -1) $("language").value = "";
  $("sort").value = params.get("sort") || defaultSort(state.searching);
  if ($("sort").selectedIndex === -1) $("sort").value = defaultSort(state.searching);
  if ($("region").selectedIndex === -1) $("region").value = "";
  $("clear-search").hidden = !$("search").value;
  const viewParam = params.get("view");
  state.view = ["saved", "for-you", "briefing"].includes(viewParam) ? viewParam : "feed";
  for (const peer of ["feed", "for-you", "saved", "briefing"])
    $(`view-${peer}`).setAttribute("aria-pressed", String(peer === state.view));
  $("feed-controls").hidden = ["saved", "briefing"].includes(state.view);
  $("sort").hidden = state.view !== "feed";
  $("refresh").hidden = ["saved", "briefing"].includes(state.view);
  $("personalization").hidden = state.view !== "for-you";
  $("briefing-intro").hidden = state.view !== "briefing";
  reflectWorkspace();
}

function reflectWorkspace() {
  const labels = { feed: "All stories", "briefing": "Daily briefing", "for-you": "For you", saved: "Saved stories" };
  $("reading-title").textContent = labels[state.view];
  for (const button of document.querySelectorAll("[data-workspace-view]")) {
    if (button.dataset.workspaceView === state.view) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  for (const button of $("sidebar-topics").children)
    button.setAttribute("aria-pressed", String(state.view === "feed" && state.topic === button.dataset.topic));
}

function renderWorkspaceTopics() {
  $("sidebar-topics").replaceChildren(...Object.entries(state.topics).filter(([id]) => id !== "video").map(([id, label]) => {
    const button = node("button", "", label);
    button.type = "button";
    button.dataset.topic = id;
    button.addEventListener("click", () => {
      state.topic = id;
      if (state.view !== "feed") $("view-feed").click();
      else chooseTopic(id);
      closeWorkspaceMenu();
      $("reading-title").focus({ preventScroll: true });
      $("reading-title").scrollIntoView({ block: "start" });
    });
    return button;
  }));
  reflectWorkspace();
}

function closeWorkspaceMenu() {
  document.body.classList.remove("workspace-menu-open");
  $("workspace-menu").setAttribute("aria-expanded", "false");
}

$("workspace-menu").addEventListener("click", () => {
  const open = !document.body.classList.contains("workspace-menu-open");
  document.body.classList.toggle("workspace-menu-open", open);
  $("workspace-menu").setAttribute("aria-expanded", String(open));
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && document.body.classList.contains("workspace-menu-open")) {
    closeWorkspaceMenu();
    $("workspace-menu").focus();
  }
});
for (const button of document.querySelectorAll("[data-workspace-view]")) {
  button.addEventListener("click", () => {
    $(`view-${button.dataset.workspaceView}`).click();
    closeWorkspaceMenu();
    $("reading-title").focus({ preventScroll: true });
  });
}
$("masthead-briefing").addEventListener("click", () => $("view-briefing").click());
$("sidebar-save-view").addEventListener("click", () => {
  if (["saved", "briefing"].includes(state.view)) $("view-feed").click();
  closeWorkspaceMenu();
  $("saved-views").open = true;
  $("saved-view-name").focus();
});

function chooseTopic(topic) {
  state.topic = topic;
  reflectFilters();
  loadNews();
}

function renderCoverageControls(data = {}) {
  if (data.topics) state.topics = topicOptions(data.topics);
  if (data.regions) state.regions = regionOptions(data.regions);
  if (data.coverage_types) state.coverageTypes = data.coverage_types;
  if (data.languages) state.languages = data.languages;
  fillOptions($("subject"), data.subjects || subjectLabels, "All subjects");
  fillOptions($("digest-subject"), data.subjects || subjectLabels, "All subjects");
  preferences.update(data.topics ? data : { topics: state.topics, subjects: subjectLabels });
  state.facets = data.facets || {};
  const counts = state.facets.topics;
  const topics = { all: "All topics", ...state.topics };
  for (const button of [...$("topics").children]) {
    if (!Object.hasOwn(topics, button.dataset.topic)) button.remove();
  }
  for (const [id, label] of Object.entries(topics)) {
    let button = $("topics").querySelector(`[data-topic="${CSS.escape(id)}"]`);
    if (!button) {
      button = node("button", "topic-chip");
      button.type = "button";
      button.dataset.topic = id;
      button.addEventListener("click", () => chooseTopic(id));
      $("topics").append(button);
    }
    const count = counts?.[id];
    button.setAttribute("aria-label", optionLabel(label, count));
    button.replaceChildren(document.createTextNode(label));
    if (Number.isInteger(count)) {
      const total = node("span", "topic-result-count", count.toLocaleString());
      total.setAttribute("aria-hidden", "true");
      button.append(total);
    }
  }
  fillOptions($("topic-mobile"), state.topics, "All topics", counts, state.topic);
  fillOptions($("region"), state.regions, "All regions", state.facets.regions);
  fillOptions($("language"), state.languages, "All languages", state.facets.languages);
  fillOptions($("digest-language"), state.languages, "All languages");
  fillOptions($("coverage"), state.coverageTypes, "All source types");
  fillOptions($("digest-coverage"), state.coverageTypes, "All source types");
  fillOptions($("digest-topic"), state.topics, "All topics");
  fillOptions($("digest-region"), state.regions, "All regions");
  reflectTopic();
}
function renderSourceFilters() {
  const names = {
    all: "All sources",
    openai: "OpenAI",
    anthropic: "Anthropic",
    youtube: "YouTube",
    medium: "Medium",
    dev: "DEV Community",
  };
  for (const [id, label] of Object.entries(names)) {
    const count = state.counts[id] ?? (Object.hasOwn(state.counts, "all") ? 0 : null);
    let button = $("source-filters").querySelector(`[data-source="${id}"]`);
    if (!button) {
      button = node("button", "topic-chip");
      button.dataset.source = id;
      button.type = "button";
      button.addEventListener("click", () => {
        state.source = id;
        renderSourceFilters();
        loadNews();
      });
      $("source-filters").append(button);
    }
    button.textContent = `${label}${Number.isInteger(count) ? ` (${count})` : ""}`;
    button.setAttribute("aria-pressed", String(state.source === id));
  }
}
const visibleStories = () => {
  if (state.view === "saved") return [...saved.values()].reverse();
  if (state.view === "briefing") return state.briefing;
  if (state.view === "for-you") return state.recommendations;
  return state.articles;
};

function renderStories() {
  $("outage-links").hidden = state.topic !== "outages";
  const container = $("stories");
  container.replaceChildren();
  const isSaved = state.view === "saved";
  const isForYou = state.view === "for-you";
  const isBriefing = state.view === "briefing";
  $("export-saved-md").hidden = !isSaved || !saved.size;
  $("pin-all-saved").hidden = !isSaved || !saved.size;
  const allArticles = visibleStories();
  const hideRead = $("hide-read").getAttribute("aria-pressed") === "true" && !isSaved;
  const articles = hideRead ? allArticles.filter(article => !readStories.has(String(article.id))) : allArticles;
  $("hide-read").hidden = isSaved;
  $("filter-high-signal").hidden = state.view !== "feed";
  $("filter-articles").hidden = state.view !== "feed";
  $("filter-releases").hidden = state.view !== "feed";
  $("mark-all-read").hidden = isSaved || !articles.length;
  if (!articles.length) {
    const empty = node("div", "empty reading-empty");
    const query = $("search").value.trim();
    empty.append(node("strong", "", hideRead && allArticles.length ? "You’re up to date with this selection" :
      isSaved ? "No saved stories" : isBriefing ? "Your briefing is waiting for recent coverage" :
        (isForYou ? "No stories in your personalized feed" : "No matching stories")));
    if (hideRead && allArticles.length) {
      const showRead = node("button", "button secondary", "Show read stories");
      showRead.type = "button";
      showRead.addEventListener("click", () => $("hide-read").click());
      empty.append(showRead);
    }
    empty.append(node("p", "", hideRead && allArticles.length ? "Show read stories to revisit this selection." :
      isBriefing ? "Browse all stories to explore other time windows and source types." :
      isSaved ? "Save an article to keep it in this browser." :
      isForYou ? "Try a different search or widen your filters. For You also skips stories you have already opened." :
      query ? `Try a different search for “${query}”, or widen the time window.` :
        "Try a longer time window or a different topic, publisher region, or source."));
    const nextWindow = Object.keys(windows).map(Number).find((hours) => hours > state.hours);
    if (isSaved || isBriefing || (isForYou && !nextWindow)) {
      const browse = node("button", "button secondary", "Browse latest stories");
      browse.type = "button";
      browse.addEventListener("click", () => {
        $("view-feed").focus();
        $("view-feed").click();
      });
      empty.append(browse);
    } else if (nextWindow) {
      const expand = node("button", "button secondary", `Search the last ${windows[nextWindow]}`);
      expand.type = "button";
      expand.addEventListener("click", () => {
        const windowButton = $("window-controls").querySelector(`[data-hours="${nextWindow}"]`);
        windowButton.focus();
        windowButton.click();
      });
      empty.append(expand);
    }
    container.append(empty);
  }
  for (const article of articles) {
    const isRead = readStories.has(String(article.id));
    const card = node(
      "article",
      `story${state.pins.has(String(article.id)) ? " pinned" : ""}${isRead ? " is-read" : " is-unread"}`,
    );
    card.dataset.storyCardId = String(article.id);
    const main = node("div", "story-main");
    const top = node("div", "story-top");
    if (!isRead) {
      const dot = node("span", "unread-dot");
      dot.title = "Unread story";
      dot.setAttribute("aria-hidden", "true");
      top.append(dot);
    }
    const timestamp = article.publishedAt || article.published_at;
    const topic = article.category || article.topic;
    const date = node("time", "", relativeTime(timestamp, article.publication_date_precision));
    date.title = article.publication_date_precision === "day" ? relativeTime(timestamp, "day") : readableTime(timestamp);
    if (timestamp) date.dateTime = timestamp;
    const storySummary = article.cleanSummary || article.description || article.summary;
    const titleDirection = article.language === "ar" ? "rtl" : "auto";
    const excerptDirection = article.has_excerpt && article.summary_basis !== "ai_feed_summary" ? titleDirection : "auto";
    const whyItMatters = deriveWhyItMatters(article);
    const wordCount = (article.title + " " + (storySummary || "")).split(/\s+/).length;
    const readingTime = article.readingTimeMinutes || Math.max(1, Math.ceil(wordCount / 65));

    const badges = node("div", "story-meta-badges");
    if (state.view === "for-you" && article.recommendation_reasons?.length) {
      badges.append(node("span", "for-you-badge", article.recommendation_reasons[0]));
    }
    badges.append(
      node(
        "span",
        `source-badge ${Object.hasOwn(state.topics, topic) ? topic : ""}`,
        state.topics[topic] || article.topic_label || "Technology",
      ),
      node("span", "meta-pill region-pill", publisherRegion(article)),
      node("span", "meta-pill read-time-pill", article.reading_access?.mode === "full_text" ? "Full article · permitted" :
        article.reading_time_basis === "publisher" ? `${readingTime} min read · excerpt` : article.has_excerpt ? "Excerpt" : "Headline & link"),
    );
    top.append(badges, date);
    if (article.coverage_count > 1) {
      const coverage = node("button", "coverage-count", `${article.coverage_count} publishers`);
      coverage.type = "button";
      coverage.title = (article.coverage_publishers || []).join(" · ");
      coverage.addEventListener("click", () => openDossier(article, coverage));
      badges.append(coverage);
    }
    const heading = node("h3");
    heading.dir = titleDirection;
    if (article.language) heading.lang = article.language;
    const storyLink = node("a", "", article.title);
    storyLink.href = `/?article=${encodeURIComponent(article.id)}#reading-room`;
    storyLink.addEventListener("click", (event) => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      openDossier(article, storyLink);
    });
    heading.append(storyLink);
    const bottom = node("div", "story-bottom");
    const publisher = article.sourceName || article.publisher || "Original source";
    const sourceMark = node("span", "source-mark", publisher.replace(/^The\s+/i, "").slice(0, 1).toUpperCase());
    sourceMark.setAttribute("aria-hidden", "true");
    const attribution = node("div", "story-attribution");
    const sourceType = article.kind === "video" ? "Creator video" : article.kind === "podcast" ? "Podcast episode" : article.content_format === "newsletter" ? "Newsletter article" :
      state.coverageTypes[article.coverage] || coverageLabels[article.coverage];
    attribution.append(
      node("strong", "", publisher),
      node("span", "", [article.author, sourceType, publisherRegion(article), originalLanguage(article.language)].filter(Boolean).join(" · ")),
    );
    const byline = node("div", "story-byline");
    byline.append(sourceMark, attribution);
    bottom.append(byline);
    const pin = node(
      "button",
      "pin-button",
      state.pins.has(String(article.id)) ? "Pinned" : "Pin",
    );
    pin.type = "button";
    pin.dataset.pinId = String(article.id);
    pin.setAttribute(
      "aria-pressed",
      String(state.pins.has(String(article.id))),
    );
    pin.setAttribute(
      "aria-label",
      `${state.pins.has(String(article.id)) ? "Unpin" : "Pin"} ${article.title}`,
    );
    pin.addEventListener("click", () => togglePin(article));
    const isBookmarked = saved.has(String(article.id));
    const save = node("button", "pin-button save-button", isBookmarked ? "Saved" : "Save");
    save.type = "button";
    save.dataset.storyId = String(article.id);
    save.setAttribute("aria-pressed", String(isBookmarked));
    save.setAttribute("aria-label", `${isBookmarked ? "Remove saved story" : "Save story"}: ${article.title}`);
    save.title = isBookmarked ? "Remove from saved stories" : "Save in this browser";
    save.addEventListener("click", () => toggleSaved(article));
    pin.title = "Include in your next brief";

    const dossierBtn = node("button", "card-dossier-btn", "Details");
    dossierBtn.type = "button";
    dossierBtn.setAttribute("aria-label", `Details: ${article.title}`);
    dossierBtn.setAttribute("aria-haspopup", "dialog");
    dossierBtn.addEventListener("click", () => openDossier(article, dossierBtn));

    const actions = node("div", "story-actions");
    const original = externalLink(article.original_url || article.url, "Original ↗");
    original.className = "card-original-link";
    actions.append(original);
    actions.append(dossierBtn, save, pin);
    bottom.append(actions);
    main.append(top, heading);
    card.append(main);
    if (whyItMatters) {
      const perspectiveWrap = node("div", "story-perspectives");
      const tabGroup = node("div", "perspective-tabs");
      const tabSummary = node("button", "perspective-tab active", "Summary");
      tabSummary.type = "button";
      tabSummary.setAttribute("aria-pressed", "true");
      const tabWhy = node("button", "perspective-tab", "Why It Matters");
      tabWhy.type = "button";
      tabWhy.setAttribute("aria-pressed", "false");
      tabGroup.setAttribute("role", "group");
      tabGroup.setAttribute("aria-label", "Story perspective");
      tabGroup.append(tabSummary, tabWhy);

      const paragraph = node("p", "story-summary", storySummary || "Read original source for coverage details.");
      paragraph.dir = excerptDirection;
      if (article.language && article.has_excerpt) paragraph.lang = article.language;

      const why = node("div", "why-matters-box");
      why.hidden = true;
      why.textContent = whyItMatters;

      tabSummary.addEventListener("click", () => {
        tabSummary.classList.add("active");
        tabWhy.classList.remove("active");
        tabSummary.setAttribute("aria-pressed", "true");
        tabWhy.setAttribute("aria-pressed", "false");
        paragraph.hidden = false;
        why.hidden = true;
      });
      tabWhy.addEventListener("click", () => {
        tabWhy.classList.add("active");
        tabSummary.classList.remove("active");
        tabWhy.setAttribute("aria-pressed", "true");
        tabSummary.setAttribute("aria-pressed", "false");
        paragraph.hidden = true;
        why.hidden = false;
      });

      perspectiveWrap.append(tabGroup, paragraph, why);
      main.append(perspectiveWrap);
    } else if (storySummary) {
      const paragraph = node("p", "story-summary", storySummary);
      paragraph.dir = excerptDirection;
      if (article.language && article.has_excerpt) paragraph.lang = article.language;
      main.append(paragraph);
    }
    if (permittedImage(article.thumbnail_url)) {
      const image = node("img", "story-thumbnail");
      image.alt = "";
      image.width = 320;
      image.height = 180;
      image.loading = "lazy";
      image.decoding = "async";
      image.referrerPolicy = "no-referrer";
      image.addEventListener("error", () => image.remove(), { once: true });
      image.src = article.thumbnail_url;
      card.append(image);
    }
    card.append(bottom);
    container.append(card);
  }
  $("show-more").hidden = state.view !== "feed" || !state.cursor;
  $("brief-from-view").hidden = state.view !== "feed" || !state.articles.length || !(state.topic !== "all" ||
    $("region").value || $("language").value || $("coverage").value || $("subject").value || state.publisher || state.source !== "all" || state.hours !== 12 || state.searching);
  const context = [
    state.topics[state.topic],
    $("region").value && state.regions[$("region").value],
    $("language").value && state.languages[$("language").value],
  ].filter(Boolean);
  status(
    "news-status",
    state.view === "briefing" ? `${articles.length} stories to catch up on${hideRead ? " · Read stories hidden" : ""}` :
    isSaved ? `${saved.size} ${saved.size === 1 ? "story" : "stories"} saved on this browser` :
      isForYou ? `${state.recommendations.length} recommendations from ${state.recommendationCandidates.toLocaleString()} matching candidates · Last ${windows[state.hours]}` :
      [`${state.articles.length ? `${state.articles.length} of ` : ""}${state.total.toLocaleString()} ${state.total === 1 ? "story" : "stories"}`, ...context,
        hideRead ? `${allArticles.length - articles.length} read stories hidden on this page` : ""].filter(Boolean).join(" · "),
  );
}
function togglePin(article) {
  const id = String(article.id);
  if (state.pins.has(id)) state.pins.delete(id);
  else {
    if (state.pins.size === 10) {
      status("news-status", "You can pin up to 10 stories. Remove one to add another.", true);
      status(
        "pin-status",
        "You can pin up to 10 stories. Remove one to add another.",
        true,
      );
      return;
    }
    state.pins.set(id, article);
  }
  if (state.pins.size > Number($("article-count").value))
    $("article-count").value = state.pins.size <= 5 ? "5" : "10";
  status("pin-status", "");
  renderPins();
  const restorePinFocus = document.activeElement?.dataset.pinId === id;
  renderStories();
  status("story-action-status", state.pins.has(id) ? `Story pinned. ${state.pins.size} in this brief.` : `Story unpinned. ${state.pins.size} in this brief.`);
  if (restorePinFocus) $("stories").querySelector(`[data-pin-id="${CSS.escape(id)}"]`)?.focus({ preventScroll: true });
}
function renderPins() {
  const count = state.pins.size;
  $("selected-count").textContent = `${count} / 10`;
  $("mobile-pin-count").textContent = `${count} pinned`;
  $("mobile-builder").hidden = !count;
  $("pinned-bar-count").textContent =
    `${count} ${count === 1 ? "story" : "stories"} pinned`;
  $("pinned-bar").hidden = !count;
  $("clear-pins").hidden = !count;
  $("selected-stories").replaceChildren();
  if (!count)
    $("selected-stories").append(
      node("p", "small", "Pin stories in the Reading Room to include them here."),
    );
  for (const article of state.pins.values()) {
    const row = node("div", "selected-item");
    row.append(node("span", "", article.title));
    const remove = node("button", "", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${article.title}`);
    remove.addEventListener("click", () => {
      togglePin(article);
      ($("selected-stories").querySelector("button") || $("article-count")).focus();
    });
    row.append(remove);
    $("selected-stories").append(row);
  }
}
for (const id of ["clear-pins", "pinned-clear"])
  $(id).addEventListener("click", () => {
    state.pins.clear();
    renderPins();
    renderStories();
    status("pin-status", "Pinned selection cleared.");
    if (id === "clear-pins") $("article-count").focus();
    else $("nav-builder").focus({ preventScroll: true });
  });
renderPins();
function updateSourceCatalog(sources) {
  if (!sources?.length) return;
  state.sources = sources;
  const enabled = sources.filter((s) => s.enabled).sort((a, b) => a.label.localeCompare(b.label));
  for (const id of ["publisher", "digest-sources"]) {
    const select = $(id);
    const value = id === "publisher" ? state.publisher : select.value;
    if (select.options.length === enabled.length + 1 && enabled.every((s, index) =>
      select.options[index + 1].value === s.id && select.options[index + 1].text === s.label)) continue;
    select.replaceChildren();
    const option = node(
      "option",
      "",
      id === "publisher" ? "All publisher feeds" : "All sources",
    );
    option.value = id === "publisher" ? "" : "all";
    select.append(option);
    for (const source of enabled) {
      const item = node("option", "", source.label);
      item.value = source.id;
      select.append(item);
    }
    select.value = value;
    if (!select.value) select.value = id === "publisher" ? "" : "all";
  }
  renderDigestSources();
}
function renderDigestSources() {
  const selection = $("digest-source-selection");
  selection.hidden = state.digestSources.size === 0;
  selection.replaceChildren();
  for (const id of state.digestSources) {
    const label = state.sources.find((source) => source.id === id)?.label || id;
    const remove = node("button", "topic-chip", `${label} ×`);
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${label} from brief sources`);
    remove.addEventListener("click", () => {
      state.digestSources.delete(id);
      renderDigestSources();
      $("digest-sources").focus();
    });
    selection.append(remove);
  }
  $("digest-sources").options[0].textContent = state.digestSources.size ? "Choose another source" : "All sources";
}
$("digest-sources").addEventListener("change", (event) => {
  if (event.target.value !== "all") state.digestSources.add(event.target.value);
  event.target.value = "all";
  renderDigestSources();
});
function renderHealth(freshness, catalog = state.sources) {
  state.healthSources = catalog.filter((source) => source.enabled &&
    (state.view === "briefing" || (state.source === "all" || state.source === source.source || state.source === source.id) &&
    (!state.publisher || state.publisher === source.id) &&
    (!$("region").value || $("region").value === regionId(source)) &&
    (!$("language").value || $("language").value === source.language) &&
    ($("kind").value === "all" || $("kind").value === source.kind) &&
    (!$("coverage").value || $("coverage").value === source.coverage)));
  const { enabled = 0, fresh = 0, failed = 0, stale = 0 } = freshness?.counts || {};
  const checkedLabel = fresh === enabled ? `${fresh} ${fresh === 1 ? "feed" : "feeds"}` : `${fresh} of ${enabled} feeds`;
  $("source-health-label").textContent = fresh ? `${checkedLabel} up to date` :
    failed || stale ? "Updates delayed" : enabled ? "Awaiting source checks" : "No feeds selected";
  $("source-health-button").classList.toggle("degraded", fresh < enabled);
  $("updated").textContent = freshness?.checked_at
    ? `Selected feeds checked ${readableTime(freshness.checked_at)}`
    : state.healthSources.length ? "Individual source check times below." : "No enabled feeds in this selection.";
  if (!$("source-popover").hidden) renderHealthList();
  $("failed-alert").hidden = freshness?.status !== "stale";
  $("failed-message").textContent = "Feed updates are delayed. Showing the latest stories in the archive.";
}

function renderHealthList() {
  $("source-health-list").className = "source-health-list";
  $("source-health-list").replaceChildren();
  for (const s of state.healthSources) {
    const row = node("div", "health-source");
    row.append(
      node("strong", "", s.label),
      node(
        "span",
        "",
        `${s.freshness === "stale" ? "Check overdue" : s.available === true ? "Available" : s.available === false ? "Last check failed" : "Waiting for first check"}${s.checked_at ? ` · Checked ${readableTime(s.checked_at)}` : ""}${s.last_success ? ` · Last success ${readableTime(s.last_success)}` : ""}`,
      ),
    );
    $("source-health-list").append(row);
  }
}

function newsParams() {
  const params = new URLSearchParams({
    hours: String(state.hours),
    source: state.source,
    topic: state.topic,
    region: $("region").value,
    publisher: state.publisher,
    q: $("search").value.trim(),
    kind: $("kind").value,
    sort: $("sort").value,
    limit: "12",
  });
  if ($("coverage").value) params.set("coverage", $("coverage").value);
  if ($("language").value) params.set("language", $("language").value);
  if ($("subject").value) params.set("subject", $("subject").value);
  return params;
}

async function checkForUpdates() {
  if (state.view !== "feed" || document.hidden || $("mail-dialog").open || state.updateCheck ||
      $("stories").getAttribute("aria-busy") === "true" || !state.feedKey) return;
  const params = newsParams();
  if (state.feedKey !== params.toString()) return;
  const controller = new AbortController();
  state.updateCheck = controller;
  try {
    const data = await request(`/api/news?${params}`, { signal: controller.signal });
    if (controller.signal.aborted || state.view === "saved" || state.feedKey !== newsParams().toString()) return;
    if ($("source-popover").hidden) renderHealth(data.freshness, data.sources);
    const visible = new Set(state.articles.map((story) => story.id));
    const currentIds = new Set(state.articles.slice(0, 12).map((story) => story.id));
    const different = data.articles.length !== currentIds.size || data.articles.some((story) => !currentIds.has(story.id));
    const unseen = data.articles.filter((story) => !visible.has(story.id)).length;
    $("news-update").hidden = !different;
    $("news-update-text").textContent = unseen ? "New stories are available." : "The story list has been updated.";
  } catch {
    // A background check must not replace the stories already on screen.
  } finally {
    if (state.updateCheck === controller) state.updateCheck = null;
  }
}

let authorCatalogLoaded = false;
async function loadBriefing() {
  state.controller?.abort();
  state.updateCheck?.abort();
  const controller = state.controller = new AbortController();
  $("stories").setAttribute("aria-busy", "true");
  $("briefing-pin").hidden = true;
  status("news-status", "Preparing your daily briefing…");
  syncURL();
  try {
    const [data, catalog] = await Promise.all([
      request("/api/briefing", { signal: controller.signal }),
      state.sources.length ? null : request("/api/sources", { signal: controller.signal }),
    ]);
    if (state.controller !== controller || state.view !== "briefing") return;
    if (catalog) {
      renderCoverageControls(catalog);
      updateSourceCatalog(catalog.sources);
    }
    state.briefing = data.articles;
    if (data.freshness) renderHealth(data.freshness);
    $("briefing-context").textContent = data.articles.length ?
      `${data.articles.length} stories selected from ${data.publishers} publishers. Based on source headlines and excerpts.` :
      "There is no recent publisher reporting in this window. Browse all stories or check source status.";
    $("briefing-pin").hidden = !data.articles.length;
    renderStories();
  } catch (error) {
    if (state.controller !== controller || error.name === "AbortError") return;
    state.briefing = [];
    const retry = node("button", "button secondary", "Try again");
    retry.type = "button";
    retry.addEventListener("click", loadBriefing);
    const empty = node("div", "empty reading-empty");
    empty.append(node("strong", "", "The briefing is temporarily unavailable"), retry);
    $("stories").replaceChildren(empty);
    status("news-status", error.message, true);
  } finally {
    if (state.controller === controller) $("stories").setAttribute("aria-busy", "false");
  }
}

$("briefing-pin").addEventListener("click", () => {
  const candidates = state.briefing.filter(article => !state.pins.has(String(article.id)));
  if (candidates.length + state.pins.size > 10) {
    status("story-action-status", "Free up pin slots to include the entire briefing.", true);
    return;
  }
  for (const article of candidates) state.pins.set(String(article.id), article);
  if (state.pins.size > Number($("article-count").value))
    $("article-count").value = state.pins.size <= 5 ? "5" : "10";
  renderPins();
  renderStories();
  openBuilder("build", $("briefing-pin"));
});

$("hide-read").addEventListener("click", () => {
  const active = $("hide-read").getAttribute("aria-pressed") !== "true";
  $("hide-read").setAttribute("aria-pressed", String(active));
  try { localStorage.setItem("informa-hide-read", String(active)); } catch {}
  renderStories();
});
try { $("hide-read").setAttribute("aria-pressed", String(localStorage.getItem("informa-hide-read") === "true")); } catch {}

async function loadRecommendations() {
  state.controller?.abort();
  state.updateCheck?.abort();
  const controller = new AbortController();
  state.controller = controller;
  $("stories").setAttribute("aria-busy", "true");
  $("refresh").disabled = true;
  $("show-more").hidden = true;
  status("news-status", "Finding stories that match your filters…");
  syncURL();
  try {
    if (!state.sources.length) {
      const catalog = await request("/api/sources", { signal: controller.signal });
      if (state.controller !== controller) return;
      renderCoverageControls(catalog);
      updateSourceCatalog(catalog.sources);
    }
    if (!authorCatalogLoaded) request("/api/authors", { signal: controller.signal }).then((authors) => {
      if (state.controller !== controller) return;
      preferences.update(authors);
      authorCatalogLoaded = true;
    }).catch(() => {});
    const { q, sort, limit, hours, ...filters } = Object.fromEntries(newsParams());
    const selected = preferences.request();
    const data = await request("/api/recommendations", { method: "POST",
      headers: { "Content-Type": "application/json" }, signal: controller.signal,
      body: JSON.stringify({ ...selected, q, scope: { ...filters, hours: Number(hours) }, exclude_ids: [...readStories].slice(-100),
        ...(preferences.usesSavedStories() && { saved_ids: [...saved.keys()].slice(-8) }) }) });
    if (state.controller !== controller || state.view !== "for-you") return;
    state.recommendations = data.articles;
    state.recommendationCandidates = data.total_candidates;
    renderStories();
  } catch (error) {
    if (state.controller === controller && error.name !== "AbortError") {
      const empty = node("div", "empty reading-empty");
      const retry = node("button", "button secondary", "Try again");
      retry.type = "button";
      retry.addEventListener("click", () => loadRecommendations());
      empty.append(node("strong", "", "Recommendations are temporarily unavailable"), retry);
      $("stories").replaceChildren(empty);
      status("news-status", error.message, true);
    }
  } finally {
    if (state.controller === controller) {
      $("stories").setAttribute("aria-busy", "false");
      $("refresh").disabled = false;
    }
  }
}

async function loadNews(append = false, force = false) {
  if (state.view === "briefing") return loadBriefing();
  if (state.view === "saved") {
    state.controller?.abort();
    state.updateCheck?.abort();
    $("stories").setAttribute("aria-busy", "false");
    renderStories();
    return;
  }
  clearTimeout(searchTimer);
  const searching = Boolean($("search").value.trim());
  if ($("sort").value === defaultSort(state.searching)) $("sort").value = defaultSort(searching);
  state.searching = searching;
  if (state.view === "for-you") return loadRecommendations();
  const params = newsParams();
  const feedKey = params.toString();
  state.controller?.abort();
  state.updateCheck?.abort();
  const controller = new AbortController();
  state.controller = controller;
  $("stories").setAttribute("aria-busy", "true");
  $("show-more").disabled = $("refresh").disabled = true;
  status("news-status", append ? "Loading more stories…" : "Loading stories…");
  if (!append) {
    $("news-update").hidden = true;
    $("show-more").hidden = true;
    if (state.feedKey !== feedKey) {
      state.articles = [];
      $("brief-from-view").hidden = true;
    }
  }
  if (!state.articles.length) {
    $("stories").replaceChildren(...Array.from({ length: 3 }, () => {
      const card = node("div", "story-skeleton");
      card.setAttribute("aria-hidden", "true");
      card.append(node("span"), node("span"), node("span"));
      return card;
    }));
  }
  syncURL();
  try {
    if (append && state.cursor) params.set("cursor", state.cursor);
    if (force) params.set("force", "true");
    const data = await request(`/api/news?${params}`, {
      signal: controller.signal,
    });
    if (state.controller !== controller || state.view === "saved") return;
    const focusMore = append && (document.activeElement === $("show-more") || document.activeElement === document.body);
    const previousSize = append ? state.articles.length : 0;
    if (append) {
      const known = new Set(state.articles.map((article) => article.id));
      state.articles.push(...data.articles.filter((article) => !known.has(article.id)));
    } else state.articles = data.articles;
    state.cursor = data.next_cursor;
    state.feedKey = feedKey;
    state.total = data.total;
    state.counts = data.source_counts || {};
    renderCoverageControls(data);
    updateSourceCatalog(data.sources);
    renderStories();
    renderSourceFilters();
    renderActiveFilters();
    renderHealth(data.freshness);
    if (focusMore) $("stories").children[previousSize]?.querySelector("h3 a")?.focus();
  } catch (error) {
    if (state.controller === controller && error.name !== "AbortError" && state.view !== "saved") {
      if (!append && force && state.articles.length) $("show-more").hidden = !state.cursor;
      if (!append && (!force || !state.articles.length)) {
        const retry = node("button", "button secondary", "Try again");
        retry.type = "button";
        retry.addEventListener("click", () => loadNews());
        const empty = node("div", "empty news-empty");
        empty.append(node("strong", "", "Stories are temporarily unavailable"), retry);
        $("stories").replaceChildren(empty);
        $("show-more").hidden = true;
        state.articles = [];
        state.cursor = null;
        state.feedKey = "";
      }
      if (append && error.status === 400) {
        state.cursor = null;
        $("show-more").hidden = true;
        $("news-update").hidden = false;
        $("news-update-text").textContent = "This page expired. Reload the story list to continue.";
        $("show-updates").focus();
      }
      status("news-status", error.name === "TimeoutError" ? "Stories took too long to load. Try again." : error.message, true);
    }
  } finally {
    if (state.controller === controller) {
      $("stories").setAttribute("aria-busy", "false");
      $("show-more").disabled = $("refresh").disabled = false;
    }
  }
}
$("topic-mobile").addEventListener("change", () => chooseTopic($("topic-mobile").value || "all"));
for (const chip of document.querySelectorAll(".domain-chip")) {
  chip.addEventListener("click", () => {
    const domain = chip.dataset.domain;
    if (state.view !== "feed") $("view-feed").click();
    chooseTopic(state.topic === domain ? "all" : domain);
    $("reading-room").scrollIntoView({ block: "start", behavior: "smooth" });
  });
}
for (const button of $("window-controls").children)
  button.addEventListener("click", () => {
    state.hours = Number(button.dataset.hours);
    for (const peer of $("window-controls").children)
      peer.setAttribute("aria-pressed", String(peer === button));
    loadNews();
  });
for (const id of ["region", "kind", "coverage", "language", "subject"]) $(id).addEventListener("change", () => loadNews());
$("sort").addEventListener("change", () => {
  state.searching = Boolean($("search").value.trim());
  loadNews();
});
$("publisher").addEventListener("change", () => {
  state.publisher = $("publisher").value;
  loadNews();
});
$("filter-toggle").addEventListener("click", () => {
  $("extra-filters").hidden = !$("extra-filters").hidden;
  $("filter-toggle").setAttribute("aria-expanded", String(!$("extra-filters").hidden));
});
let searchTimer;
for (const view of ["feed", "for-you", "saved", "briefing"]) {
  $(`view-${view}`).addEventListener("click", () => {
    if (state.view === view) return;
    clearTimeout(searchTimer);
    state.controller?.abort();
    state.updateCheck?.abort();
    state.view = view;
    for (const peer of ["feed", "for-you", "saved", "briefing"])
      $(`view-${peer}`).setAttribute("aria-pressed", String(peer === view));
    $("feed-controls").hidden = ["saved", "briefing"].includes(view);
    $("sort").hidden = view !== "feed";
    $("refresh").hidden = ["saved", "briefing"].includes(view);
    $("personalization").hidden = view !== "for-you";
    $("briefing-intro").hidden = view !== "briefing";
    $("stories").setAttribute("aria-busy", "false");
    syncURL();
    renderStories();
    if (view !== "saved" && (view === "for-you" || view === "briefing" || state.feedKey !== newsParams().toString())) loadNews();
  });
}
$("reset-filters").addEventListener("click", () => {
  clearTimeout(searchTimer);
  state.topic = state.source = "all";
  state.publisher = "";
  state.hours = state.view === "for-you" ? 168 : 12;
  state.searching = false;
  for (const id of ["search", "region", "publisher", "coverage", "language", "subject"]) $(id).value = "";
  $("kind").value = "all";
  $("sort").value = "latest";
  reflectFilters();
  $("search").focus();
  loadNews();
});
$("search").addEventListener("input", () => {
  $("archive-search").hidden = !$("search").value.trim() || state.hours === 2160 || state.view === "saved";
  clearTimeout(searchTimer);
  $("clear-search").hidden = !$("search").value;
  searchTimer = setTimeout(() => loadNews(), 250);
});
$("story-search").addEventListener("submit", (event) => {
  event.preventDefault();
  loadNews();
});
$("clear-search").addEventListener("click", () => {
  clearTimeout(searchTimer);
  $("search").value = "";
  loadNews();
  $("search").focus();
});
$("show-more").addEventListener("click", () => loadNews(true));
$("archive-search").addEventListener("click", () => {
  state.hours = 2160;
  reflectFilters();
  loadNews();
});
$("brief-from-view").addEventListener("click", () => {
  $("digest-topic").value = state.topic === "all" ? "" : state.topic;
  $("digest-region").value = $("region").value;
  $("digest-language").value = $("language").value;
  $("digest-coverage").value = $("coverage").value;
  $("digest-subject").value = $("subject").value;
  $("digest-window").value = String(state.hours);
  const source = state.publisher || (state.source !== "all" ? state.source : "");
  state.digestSources.clear();
  if (source) state.digestSources.add(source);
  renderDigestSources();
  const query = $("search").value.trim();
  if (query) $("focus").value = query;
  if (source || query || $("language").value || $("coverage").value) $("coverage-options").open = true;
  openBuilder();
});
$("show-updates").addEventListener("click", async () => {
  await loadNews();
  ($("stories").querySelector("h3 a") || $("search")).focus();
});
async function loadTrending() {
  try {
    const res = await fetch("/api/trending");
    if (!res.ok) return;
    const data = await res.json();
    const items = data?.trending || [];
    state.trending = items;
    if (!items.length) {
      $("trending-bar").hidden = true;
      return;
    }
    const container = $("trending-chips");
    container.replaceChildren();
    for (const item of items) {
      const chip = node("button", "trending-chip", item.tag);
      chip.type = "button";
      chip.dataset.query = item.query || item.tag;
      chip.dataset.topic = item.category || "";
      chip.setAttribute("aria-pressed", String($("search").value.toLowerCase() === (item.query || item.tag).toLowerCase()));
      const countSpan = node("span", "trending-count", String(item.count));
      chip.append(countSpan);
      chip.addEventListener("click", () => {
        const query = item.query || item.tag;
        const isActive = $("search").value.toLowerCase() === query.toLowerCase();
        if (isActive) {
          $("search").value = "";
          $("clear-search").hidden = true;
          chip.setAttribute("aria-pressed", "false");
        } else {
          $("search").value = query;
          $("clear-search").hidden = false;
          for (const c of container.children) c.setAttribute("aria-pressed", "false");
          chip.setAttribute("aria-pressed", "true");
        }
        state.searching = Boolean($("search").value.trim());
        if (state.view === "saved") $("view-feed").click();
        loadNews();
      });
      container.append(chip);
    }
    $("trending-bar").hidden = false;
  } catch {
    // Optional enhancement
  }
}

setInterval(checkForUpdates, 60_000);
for (const id of ["refresh", "retry-sources"])
  $(id).addEventListener("click", () => {
    loadNews(false, true);
    loadTrending();
  });
function showHealth(show) {
  $("source-popover").hidden = !show;
  $("source-health-button").setAttribute("aria-expanded", String(show));
  if (show) renderHealthList();
}
$("source-health-button").addEventListener("click", () => showHealth($("source-popover").hidden));
$("source-popover-close").addEventListener("click", () => {
  showHealth(false);
  $("source-health-button").focus();
});
document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest(".source-health")) showHealth(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    const restoreHealthFocus = $("source-popover").contains(document.activeElement);
    showHealth(false);
    if (restoreHealthFocus) $("source-health-button").focus();
  }
});
const builderMedia = matchMedia("(max-width: 1023px)");
const mobile = () => builderMedia.matches;
const drawerIsolation = new Set();
let drawerOpener;
function isolateBuilder() {
  for (let child = $("composer"); child !== document.body; child = child.parentElement) {
    for (const sibling of child.parentElement.children) {
      if (sibling === child || sibling.inert || ["sheet-backdrop", "mail-dialog"].includes(sibling.id)) continue;
      sibling.inert = true;
      drawerIsolation.add(sibling);
    }
  }
}
function setTab(tab, focus = false) {
  const changed = state.tab !== tab;
  state.tab = tab;
  for (const name of ["build", "preview"]) {
    const selected = name === tab;
    const button = $(`${name}-tab`);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    if (selected && focus) button.focus();
  }
  $("build-panel").hidden = mobile() && tab !== "build";
  $("preview-section").hidden = mobile() && tab !== "preview";
  if (mobile() && changed) $("composer").scrollTop = 0;
}
function openBuilder(tab = "build", trigger = document.activeElement) {
  setTab(tab);
  if (!$("composer").classList.contains("open")) {
    drawerOpener = trigger;
    $("composer").scrollTop = 0;
  }
  $("composer").classList.add("open");
  $("sheet-backdrop").hidden = false;
  for (const id of ["mobile-builder", "nav-builder"])
    $(id).setAttribute("aria-expanded", "true");
  document.body.classList.add("sheet-open");
  $("composer").setAttribute("role", "dialog");
  $("composer").setAttribute("aria-modal", "true");
  isolateBuilder();
  $("close-builder").focus({ preventScroll: true });
}
function closeBuilder(restoreFocus = true) {
  if (!$("composer").classList.contains("open")) return;
  $("composer").classList.remove("open");
  $("sheet-backdrop").hidden = true;
  for (const id of ["mobile-builder", "nav-builder"])
    $(id).setAttribute("aria-expanded", "false");
  document.body.classList.remove("sheet-open");
  $("composer").removeAttribute("role");
  $("composer").removeAttribute("aria-modal");
  for (const sibling of drawerIsolation) sibling.inert = false;
  drawerIsolation.clear();
  if (restoreFocus)
    (drawerOpener?.getClientRects().length ? drawerOpener : $("nav-builder")).focus({ preventScroll: true });
  drawerOpener = null;
}
for (const id of ["nav-builder", "mobile-builder", "pinned-build"])
  $(id).addEventListener("click", (event) => openBuilder("build", event.currentTarget));
for (const link of document.querySelectorAll('a[href="#composer"]'))
  link.addEventListener("click", event => {
    event.preventDefault();
    openBuilder("build", link);
  });
for (const id of ["close-builder", "sheet-backdrop"])
  $(id).addEventListener("click", () => closeBuilder());
$("empty-build").addEventListener("click", () => {
  setTab("build");
  $("digest-topic").focus();
});
for (const tab of ["build", "preview"])
  $(`${tab}-tab`).addEventListener("click", () => setTab(tab));
document.querySelector(".builder-tabs").addEventListener("keydown", (event) => {
  if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
    event.preventDefault();
    setTab(
      event.key === "Home"
        ? "build"
        : event.key === "End"
          ? "preview"
          : state.tab === "build"
            ? "preview"
            : "build",
      true,
    );
  }
});
builderMedia.addEventListener("change", () => {
  setTab(state.tab);
});
$("composer").addEventListener("keydown", (event) => {
  if (!$("composer").classList.contains("open") || $("mail-dialog").open) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeBuilder();
    return;
  }
  if (event.key !== "Tab") return;
  const items = [
    ...$("composer").querySelectorAll("button,a[href],input,select,textarea,summary"),
  ].filter(
    (el) => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length,
  );
  const first = items[0],
    last = items.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});
function focusPreview() {
  if (mobile() && !$("composer").classList.contains("open")) return;
  $("preview-title").focus({ preventScroll: true });
  $("preview-title").scrollIntoView({ block: "nearest" });
}
function renderDigest() {
  const digest = state.digest.digest;
  $("copy-fallback").hidden = true;
  $("preview-empty").hidden = true;
  $("preview-content").hidden = false;
  $("preview").replaceChildren();
  $("preview-title").textContent =
    digest.edition === "world"
      ? "Global tech brief"
      : "Personalized tech brief";
  const count = digest.articles.length;
  $("preview-tab").setAttribute("aria-label", count === 1 ? "Preview, 1 story" : "Preview, " + count + " stories");
  $("preview-basis").textContent = digest.synthesis?.degraded
    ? "Some AI processing was unavailable. Publisher excerpts or headline-only entries are labeled below."
    : state.digest.source_basis || "Based on publisher feed titles and excerpts.";
  $("preview-count").textContent = String(count);
  if (digest.introduction) {
    $("preview").append(
      node("p", "email-greeting", digest.introduction.greeting),
      node("p", "email-intro", digest.introduction.introduction),
    );
  }
  for (const [index, a] of digest.articles.entries()) {
    const item = node("section", "digest-item");
    const citation = node("div", "digest-meta");
    citation.append(
      node("span", "digest-rank", String(index + 1)),
      node("span", "", a.publisher || a.sourceName || a.article_type || "Source"),
      node("span", "digest-topic", a.topic_label || "Technology"),
    );
    const region = publisherRegion(a);
    if (region) citation.append(node("span", "", region));
    const heading = node("h3", "", a.title);
    if (a.language) heading.lang = a.language;
    item.append(
      citation,
      heading,
      node("p", "", a.cleanSummary || a.summary || ""),
    );
    if (a.whyItMatters && !a.keyTakeaway)
      item.append(
        node("p", "reason", `Why it matters · ${a.whyItMatters}`),
      );
    if (a.keyTakeaway) {
      const takeaway = node("p", "reason");
      takeaway.append(node("strong", "", "Key takeaway. "), document.createTextNode(a.keyTakeaway));
      item.append(takeaway);
    }
    const provenance = { ai_feed_summary: "AI summary of publisher feed", publisher_excerpt: "Publisher excerpt", headline_only: "Headline only" };
    const sourceRow = node("div", "digest-source-row");
    sourceRow.append(externalLink(a.sourceUrl || a.url, "Read source ↗"));
    if (provenance[a.summary_basis]) sourceRow.append(node("span", "", provenance[a.summary_basis]));
    item.append(sourceRow);
    $("preview").append(item);
  }
  if (digest.quick_hits?.length) {
    const section = node("section", "digest-item");
    const links = node("ul", "quick-hits");
    for (const hit of digest.quick_hits) {
      const row = node("li");
      row.append(externalLink(hit.url, hit.title), document.createTextNode(` · ${hit.publisher}`));
      links.append(row);
    }
    section.append(node("h3", "", "Quick hits"), links);
    $("preview").append(section);
  }
  setTab("preview");
  status("email-status", "");
}
function generationStage(stage) {
  $("generation-stages").hidden = false;
  for (const item of $("generation-stages").children) {
    const current = Number(item.dataset.stage);
    item.classList.toggle("complete", current < stage);
    item.classList.toggle("active", current === stage);
    if (current === stage) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  }
  status(
    "digest-status",
    [
      "",
      "Filtering and deduplicating stories…",
      "Summarizing and ranking the selected stories…",
      "Formatting the preview…",
    ][stage] || "Preparing your brief…",
  );
}
async function streamDigest(body) {
  const response = await fetch("/api/digest?stream=true", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/x-ndjson",
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(115_000),
  });
  if (!response.ok) {
    let data;
    try {
      data = await response.json();
    } catch {}
    throw new Error(
      data?.detail || "Could not prepare your brief. Please try again.",
    );
  }
  if (!response.headers.get("content-type")?.includes("ndjson"))
    return response.json();
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "",
    result;
  function consume(line) {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.error) throw new Error(event.error);
    if (event.stage) generationStage(event.stage);
    if (event.result) result = event.result;
  }
  while (true) {
    const chunk = await reader.read();
    buffer += decoder.decode(chunk.value || new Uint8Array(), {
      stream: !chunk.done,
    });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) consume(line);
    if (chunk.done) break;
  }
  if (buffer) consume(buffer);
  if (!result)
    throw new Error(
      "The connection ended before your brief was ready. Please try again.",
    );
  return result;
}
async function composeBrief(body, isWorld) {
  if (state.composing) return null;
  state.composing = true;
  const button = $(isWorld ? "world-brief" : "generate"),
    message = isWorld ? "world-status" : "digest-status";
  const label = [...button.childNodes];
  $("world-brief").disabled = $("world-preview").disabled = $("generate").disabled = true;
  button.textContent = "Preparing your brief…";
  button.setAttribute("aria-busy", "true");
  status(
    message,
    isWorld ? "Selecting today’s global stories…" : "Preparing your selection…",
  );
  if (!isWorld) {
    $("generation-stages").hidden = false;
    for (const item of $("generation-stages").children) {
      item.classList.remove("active", "complete");
      item.removeAttribute("aria-current");
    }
  }
  try {
    state.digest = isWorld
      ? await jsonPost("/api/digest", body)
      : await streamDigest(body);
    renderDigest();
    if (!isWorld) {
      for (const item of $("generation-stages").children) {
        item.classList.remove("active");
        item.classList.add("complete");
        item.removeAttribute("aria-current");
      }
    }
    status(
      message,
      `${state.digest.digest.articles.length} stories, ready to read.`,
    );
    return state.digest;
  } catch (error) {
    status(message, error.name === "TimeoutError" ? "The brief took too long to prepare. Please try again." : error.message, true);
    return null;
  } finally {
    state.composing = false;
    $("world-brief").disabled = $("world-preview").disabled = $("generate").disabled = false;
    button.replaceChildren(...label);
    button.removeAttribute("aria-busy");
  }
}
$("digest-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    edition: "personal",
    name: $("reader-name").value.trim() || "Reader",
    focus: $("focus").value.trim(),
    ...($("digest-topic").value ? { topic: $("digest-topic").value } : {}),
    ...($("digest-region").value ? { region: $("digest-region").value } : {}),
    ...($("digest-language").value ? { language: $("digest-language").value } : {}),
    ...($("digest-coverage").value ? { coverage: $("digest-coverage").value } : {}),
    ...($("digest-subject").value ? { subject: $("digest-subject").value } : {}),
    persona: $("persona").value,
    style: $("digest-style").value,
    pinned_ids: [...state.pins.keys()],
    top_n: Number($("article-count").value),
    hours: Number($("digest-window").value),
    ...(state.digestSources.size ? { sources: [...state.digestSources] } : {}),
  };
  if (body.pinned_ids.length > body.top_n) {
    status(
      "digest-status",
      "Choose a brief length large enough for your pinned stories.",
      true,
    );
    $("article-count").focus();
    return;
  }
  const brief = await composeBrief(body, false);
  if (brief) focusPreview();
});
function composeWorldBrief() {
  return composeBrief(
    {
      edition: "world",
      hours: 24,
      top_n: 5,
      persona: "executive",
      style: "executive",
    },
    true,
  );
}
$("world-preview").addEventListener("click", async (event) => {
  const trigger = event.currentTarget;
  if (await composeWorldBrief()) {
    openBuilder("preview", trigger);
    focusPreview();
  }
});
$("world-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = $("hero-email").value.trim(),
    subscribe = $("hero-subscribe").checked;
  const digest = await composeWorldBrief();
  if (!digest) return;
  $("preview-email").value = email;
  $("preview-subscribe").checked = subscribe;
  await beginDelivery({
    kind: "email",
    email,
    subscribe,
    statusId: "world-status",
    preview: digest,
  });
});
function download(content, type, filename) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = node("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("copy").addEventListener("click", async () => {
  const markdown = state.digest.digest.markdown;
  try {
    await navigator.clipboard.writeText(markdown);
  } catch {
    const fallback = $("copy-fallback");
    fallback.value = markdown;
    fallback.hidden = false;
    fallback.focus();
    fallback.select();
    status("email-status", "Clipboard access was unavailable. Copy the selected Markdown manually.");
    return;
  }
  $("copy-fallback").hidden = true;
  status("email-status", "Markdown copied to your clipboard.");
});
$("download").addEventListener("click", () => {
  download(
    state.digest.digest.html,
    "text/html;charset=utf-8",
    "informa-ai.html",
  );
  status("email-status", "HTML downloaded.");
});
$("download-eml").addEventListener("click", () => {
  const html = state.digest.digest.html;
  const encoded = btoa(
    Array.from(new TextEncoder().encode(html), (byte) =>
      String.fromCharCode(byte),
    ).join(""),
  );
  const eml = `Subject: Informa AI Technology Brief\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=UTF-8\r\nContent-Transfer-Encoding: base64\r\n\r\n${encoded.match(/.{1,76}/g).join("\r\n")}\r\n`;
  download(eml, "message/rfc822", "informa-ai.eml");
  status("email-status", "Email file downloaded. Open it in your email app.");
});
for (const mode of ["desktop", "mobile"])
  $(`preview-${mode}`).addEventListener("click", () => {
    $("preview").classList.toggle("preview-narrow", mode === "mobile");
    for (const peer of ["desktop", "mobile"])
      $(`preview-${peer}`).setAttribute("aria-pressed", String(peer === mode));
  });
$("preview-theme").addEventListener("click", () => {
  const dark = $("preview").classList.toggle("preview-dark");
  $("preview-theme").setAttribute("aria-pressed", String(dark));
  $("preview-theme").textContent = dark ? "Light preview" : "Dark preview";
});
for (const mode of ["email", "webhook"])
  $(`delivery-${mode}`).addEventListener("click", () => {
    state.delivery = mode;
    $("preview-send-form").hidden = mode !== "email";
    $("webhook-form").hidden = mode !== "webhook";
    for (const peer of ["email", "webhook"])
      $(`delivery-${peer}`).setAttribute("aria-pressed", String(peer === mode));
  });
let captchaWidget,
  captchaToken = "",
  captchaLoader;
let mailBusy = false;
let mailOpener;
const deliveryButtons = ["send", "webhook-send", "delivery-owner"];
function toggleDeliveryButtons(disabled) {
  for (const id of deliveryButtons) $(id).disabled = disabled;
}
function mailStep(step) {
  for (const id of ["request-code", "verify-code", "send-brief", "owner-email-form"])
    $(id).hidden = id !== step;
  const owner = step === "owner-email-form";
  const destination = state.pending?.kind === "webhook" ? "your webhook" : "your inbox";
  $("mail-title").textContent = owner ? "Send to owner inbox" : step === "send-brief" ? "Deliver your brief" : "Verify your inbox";
  $("mail-explanation").textContent = owner
    ? "Delivery goes to the server owner’s configured inbox."
    : step === "request-code"
      ? "We’ll send a six-digit code to this address before delivering the brief to " + destination + "."
      : step === "verify-code"
        ? "Enter the code sent to " + state.pending?.email + ". It expires after 10 minutes."
        : "Your inbox is verified. Retry delivery to " + destination + ".";
}
async function showCaptcha() {
  captchaToken = "";
  if (captchaWidget !== undefined) {
    window.turnstile.reset(captchaWidget);
    return;
  }
  captchaLoader ??= new Promise((resolve, reject) => {
    const script = node("script");
    const fail = () => {
      clearTimeout(timer);
      delete window.onBriefTurnstileLoad;
      script.remove();
      captchaLoader = undefined;
      reject(new Error("The bot check could not load. Please try again."));
    };
    const timer = setTimeout(fail, 12000);
    window.onBriefTurnstileLoad = () => {
      clearTimeout(timer);
      delete window.onBriefTurnstileLoad;
      resolve();
    };
    script.src =
      "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=onBriefTurnstileLoad";
    script.onerror = fail;
    document.head.append(script);
  });
  await captchaLoader;
  if (captchaWidget !== undefined || !$("mail-dialog").open || $("request-code").hidden) return;
  captchaWidget = window.turnstile.render("#mail-captcha", {
    sitekey: state.mail.site_key,
    action: "verify_email",
    callback: (token) => {
      captchaToken = token;
    },
    "expired-callback": () => {
      captchaToken = "";
    },
    "error-callback": () => {
      captchaToken = "";
    },
  });
}
async function loadCaptcha() {
  $("retry-captcha").hidden = true;
  try {
    await showCaptcha();
  } catch (error) {
    $("retry-captcha").hidden = false;
    status("mail-status", error.message, true);
  }
}
async function performDelivery() {
  const pending = state.pending;
  if (!pending) throw new Error("Prepare a brief before sending.");
  const result = await jsonPost(
    pending.kind === "webhook" ? "/api/deliver/webhook" : "/api/mail/send",
    pending.kind === "webhook"
      ? { preview_id: pending.preview.preview_id, url: pending.url }
      : {
          preview_id: pending.preview.preview_id,
          email: pending.email,
          subscribe: pending.subscribe,
          timezone,
        },
  );
  const message =
    result.message ||
    (pending.kind === "webhook"
      ? "Your webhook accepted the brief."
      : "Your brief was accepted for delivery.");
  const schedule = result.subscribed
    ? ` Daily delivery is enabled for 8 AM (${timezone}).`
    : "";
  status(pending.statusId, message + schedule);
  status("email-status", message + schedule);
  state.pending = null;
  if ($("mail-dialog").open) $("mail-dialog").close();
  return result;
}
async function beginDelivery(pending) {
  if (state.pending || $("mail-dialog").open) return;
  mailOpener = pending.trigger || document.activeElement;
  state.pending = pending;
  toggleDeliveryButtons(true);
  status(pending.statusId, "Checking inbox verification…");
  try {
    state.mail = await request("/api/mail/config");
    if (!state.mail.enabled || !pending.preview?.preview_id) {
      throw new Error(
        "Email verification is currently unavailable. You can copy or download your brief.",
      );
    }
    if (
      state.mail.verified &&
      normalizeEmail(state.mail.verified_email) ===
        normalizeEmail(pending.email)
    ) {
      status(
        pending.statusId,
        pending.kind === "webhook"
          ? "Posting your brief…"
          : "Sending your brief…",
      );
      await performDelivery();
      return;
    }
    mailStep("request-code");
    $("mail-address").value = pending.email;
    status("mail-status", "");
    $("mail-dialog").showModal();
    $("mail-address").focus();
    await loadCaptcha();
  } catch (error) {
    status(
      $("mail-dialog").open ? "mail-status" : pending.statusId,
      error.message,
      true,
    );
  } finally {
    if (!$("mail-dialog").open) {
      state.pending = null;
      toggleDeliveryButtons(false);
    }
  }
}
$("preview-send-form").addEventListener("submit", (event) => {
  event.preventDefault();
  beginDelivery({
    kind: "email",
    email: $("preview-email").value.trim(),
    subscribe: $("preview-subscribe").checked,
    statusId: "email-status",
    preview: state.digest,
    trigger: event.submitter,
  });
});
$("webhook-form").addEventListener("submit", (event) => {
  event.preventDefault();
  let url;
  try {
    url = new URL($("webhook-url").value.trim());
  } catch {}
  if (url?.protocol !== "https:" || url.username || url.password) {
    status("email-status", "Use an HTTPS webhook URL without embedded credentials.", true);
    $("webhook-url").focus();
    return;
  }
  beginDelivery({
    kind: "webhook",
    email: $("webhook-email").value.trim(),
    url: url.href,
    statusId: "email-status",
    preview: state.digest,
    trigger: event.submitter,
  });
});
$("delivery-owner").addEventListener("click", (event) => {
  if (state.pending || $("mail-dialog").open) return;
  mailOpener = event.currentTarget;
  mailStep("owner-email-form");
  status("mail-status", "");
  $("mail-dialog").showModal();
  $("owner-key").focus();
});
$("mail-close").addEventListener("click", () => $("mail-dialog").close());
$("mail-dialog").addEventListener("cancel", (event) => {
  if (mailBusy) event.preventDefault();
});
$("mail-dialog").addEventListener("close", () => {
  if ($("mail-dialog").open) return;
  $("mail-code").value = "";
  $("owner-key").value = "";
  captchaToken = "";
  if (state.pending) {
    status(
      state.pending.statusId,
      "Your brief is ready. Verify your email when you want to send it.",
    );
    state.pending = null;
  }
  toggleDeliveryButtons(false);
  if (mailOpener?.getClientRects().length && !mailOpener.disabled) mailOpener.focus({ preventScroll: true });
  mailOpener = null;
});
async function runMailAction(task, message) {
  if (mailBusy) return;
  mailBusy = true;
  const buttons = $("mail-dialog").querySelectorAll("button");
  for (const button of buttons) button.disabled = true;
  status("mail-status", message);
  try {
    await task();
  } catch (error) {
    status("mail-status", error.message, true);
  } finally {
    for (const button of buttons) button.disabled = false;
    mailBusy = false;
  }
}
function submitMail(event, task, message) {
  event.preventDefault();
  return runMailAction(task, message);
}
$("retry-captcha").addEventListener("click", () =>
  runMailAction(loadCaptcha, "Loading security check…"),
);
$("request-code").addEventListener("submit", (event) =>
  submitMail(event, async () => {
    if (!captchaToken) throw new Error("Complete the security check first.");
    const token = captchaToken;
    const email = $("mail-address").value.trim();
    captchaToken = "";
    try {
      await jsonPost("/api/mail/challenge", {
        email,
        captcha: token,
      });
      if (state.pending) state.pending.email = email;
      $("mail-address").value = email;
      mailStep("verify-code");
      $("mail-code").focus();
      status(
        "mail-status",
        "Check your inbox for the six-digit verification code.",
      );
    } catch (error) {
      await loadCaptcha();
      throw error;
    }
  }, "Requesting verification code…"),
);
$("verify-code").addEventListener("submit", (event) =>
  submitMail(event, async () => {
    await jsonPost("/api/mail/verify", { code: $("mail-code").value });
    $("mail-code").value = "";
    mailStep("send-brief");
    status("mail-status", "Inbox verified. Sending your prepared brief…");
    await performDelivery();
  }, "Verifying code…"),
);
$("send-brief").addEventListener("submit", (event) =>
  submitMail(event, performDelivery, "Delivering your brief…"),
);
for (const id of ["different-email", "resend-code"])
  $(id).addEventListener("click", () => runMailAction(async () => {
    await jsonPost("/api/mail/logout", {});
    $("mail-code").value = "";
    mailStep("request-code");
    $("mail-address").focus();
    if (id === "different-email") $("mail-address").select();
    status("mail-status", "");
    await loadCaptcha();
  }, "Resetting verification…"));
$("owner-email-form").addEventListener("submit", (event) =>
  submitMail(event, async () => {
    const preview = state.pending?.preview || state.digest;
    if (!preview) throw new Error("Prepare a brief first.");
    const result = await request("/api/email", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${$("owner-key").value}`,
      },
      body: JSON.stringify({
        digest: preview.digest,
        signature: preview.signature,
        expires: preview.expires,
      }),
    });
    state.pending = null;
    $("owner-key").value = "";
    $("mail-dialog").close();
    status(
      "email-status",
      result.message || "The brief was accepted for delivery.",
    );
  }, "Sending to owner inbox…"),
);
function reflectTopic() {
  for (const button of $("topics").children)
    button.setAttribute("aria-pressed", String(button.dataset.topic === state.topic));
  for (const chip of document.querySelectorAll(".domain-chip"))
    chip.setAttribute("aria-pressed", String(chip.dataset.domain === state.topic));
  $("topic-mobile").value = state.topic === "all" ? "" : state.topic;
  $("outage-links").hidden = state.topic !== "outages";
}
function reflectFilters() {
  $("archive-search").hidden = !$("search").value.trim() || state.hours === 2160 || state.view === "saved";
  reflectTopic();
  reflectWorkspace();
  for (const button of $("window-controls").children)
    button.setAttribute("aria-pressed", String(Number(button.dataset.hours) === state.hours));
  renderSourceFilters();
}
renderCoverageControls();
renderWorkspaceTopics();
restoreURL();
reflectFilters();
reflectSavedCount();
initSavedViews($("saved-views"), {
  onChange(views) {
    $("sidebar-saved-views").replaceChildren(...views.map((view, index) => {
      const button = node("button", "", view.name);
      button.type = "button";
      button.title = view.name;
      button.addEventListener("click", () => {
        if (state.view !== "feed") $("view-feed").click();
        $("saved-views-list").querySelectorAll(".saved-view-open")[index]?.click();
        closeWorkspaceMenu();
        $("reading-title").focus({ preventScroll: true });
      });
      return button;
    }));
    $("sidebar-save-view").textContent = views.length ? "+ Save current view" : "+ Create a monitoring view";
  },
  readView() {
    return new URLSearchParams(Object.entries(readingFilters()).filter(([, value]) => value && value !== "all"));
  },
  applyView(params) {
    clearTimeout(searchTimer);
    const url = new URL(location.href);
    for (const key of Object.keys(readingFilters())) {
      const value = params.get(key);
      if (value) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    }
    for (const key of ["source", "publisher"]) {
      const value = url.searchParams.get(key);
      const available = state.sources.some((source) => source.id === value || (key === "source" && source.source === value));
      if (value && state.sources.length && !available) url.searchParams.delete(key);
    }
    url.hash = "reading-room";
    history.pushState(null, "", url);
    restoreURL();
    reflectFilters();
    loadNews();
  },
});
setTab("build");
if (location.hash === "#composer")
  window.addEventListener("load", () => openBuilder("build", $("nav-builder")), { once: true });
loadNews().then(() => openLinkedArticle());
loadHeadlines();
loadSignals();
loadTrending();
window.addEventListener("hashchange", () => {
  if (location.hash === "#composer") openBuilder("build", $("nav-builder"));
});
window.addEventListener("popstate", () => {
  clearTimeout(searchTimer);
  restoreURL();
  reflectFilters();
  loadNews().then(() => openLinkedArticle());
});

for (const [id, type] of [["filter-high-signal", "reporting"], ["filter-articles", "article"], ["filter-releases", "release"]]) {
  $(id).addEventListener("click", () => {
    $("coverage").value = $("coverage").value === type ? "" : type;
    loadNews();
  });
}

$("mark-all-read").addEventListener("click", () => {
  const page = visibleStories();
  for (const article of page) readStories.add(String(article.id));
  try {
    localStorage.setItem(readKey, JSON.stringify([...readStories].slice(-300)));
  } catch {}
  renderStories();
  status("story-action-status", `${page.length} displayed stories marked as read.`);
});

function publishedExcerpt(article) {
  if (article.summary_basis === "headline_only" || article.has_excerpt === false) return "";
  return (article.cleanSummary || article.description || article.summary || "").trim();
}

function storyMarkdown(article) {
  const href = externalLink(article.sourceUrl || article.url, "").getAttribute("href");
  const publisher = article.sourceName || article.publisher || "Source";
  const lines = [`## ${article.title}`, `Publisher: ${publisher}`];
  if (href) lines.push(`Source: <${href}>`);
  const excerpt = publishedExcerpt(article);
  if (excerpt) lines.push("", excerpt);
  const why = deriveWhyItMatters(article);
  if (why) lines.push("", `Why it matters: ${why}`);
  const takeaway = deriveKeyTakeaway(article);
  if (takeaway) lines.push(`Key takeaway: ${takeaway}`);
  return lines.join("\n");
}

$("export-saved-md").addEventListener("click", () => {
  if (!saved.size) return;
  download(
    ["# Informa AI saved stories", ...[...saved.values()].reverse().map(storyMarkdown)].join("\n\n"),
    "text/markdown;charset=utf-8",
    "informa-ai-saved-stories.md",
  );
  status("story-action-status", `Exported ${saved.size} saved stories.`);
});

$("pin-all-saved").addEventListener("click", () => {
  const newPins = [...saved.values()].reverse()
    .filter((article) => !state.pins.has(String(article.id))).slice(0, 10 - state.pins.size);
  for (const article of newPins) state.pins.set(String(article.id), article);
  if (state.pins.size > Number($("article-count").value))
    $("article-count").value = state.pins.size <= 5 ? "5" : "10";
  renderPins();
  renderStories();
  status("story-action-status", newPins.length ? `Pinned ${newPins.length} saved stories. ${state.pins.size} of 10 pins in use.` :
    state.pins.size === 10 ? "All 10 pin slots are in use." : "Your saved stories are already pinned.");
});

const dossier = { article: null, articles: [], index: 0, trigger: null, openerId: "", controller: null };

function syncFollowActions() {
  if (!dossier.article) return;
  const article = dossier.article;
  const followed = preferences.follows("authors", article.author_key);
  $("dossier-follow-author").hidden = !article.author_key;
  $("dossier-follow-author").textContent = followed ? "Following author" : "Follow author";
  $("dossier-follow-author").setAttribute("aria-pressed", String(followed));
  const publication = preferences.follows("sources", article.source_id || article.source);
  $("dossier-follow-publication").textContent = publication ? "Following publication" : "Follow publication";
  $("dossier-follow-publication").setAttribute("aria-pressed", String(publication));
}

function renderDossierLinks(id, stories) {
  $(id).replaceChildren(...stories.map((story) => {
    const button = node("button", "related-story");
    button.type = "button";
    const title = node("strong", "", story.title);
    title.lang = story.language || "";
    title.dir = story.language === "ar" ? "rtl" : "auto";
    button.append(title, node("span", "", `${story.publisher} · ${relativeTime(story.published_at, story.publication_date_precision)}`));
    if (story.related_reason) button.append(node("span", "related-reason", story.related_reason));
    button.addEventListener("click", () => {
      const existing = dossier.articles.findIndex((item) => item.id === story.id);
      if (existing < 0) dossier.articles.push(story);
      dossier.index = existing < 0 ? dossier.articles.length - 1 : existing;
      renderDossier();
      $("dossier-title").focus({ preventScroll: true });
    });
    return button;
  }));
  $(`${id}-section`).hidden = !stories.length;
}

async function loadArticleDetails(article, details) {
  dossier.controller?.abort();
  const controller = dossier.controller = new AbortController();
  dossier.coverage = [];
  renderDossierLinks("dossier-related", []);
  renderDossierLinks("dossier-matches", []);
  try {
    const data = details || await request(`/api/articles/${encodeURIComponent(article.id)}`, { signal: controller.signal });
    if (dossier.controller !== controller || dossier.article?.id !== article.id) return;
    Object.assign(article, { author: data.article.author, author_key: data.article.author_key,
      author_url: data.article.author_url, reading_access: data.article.reading_access });
    preferences.update({ articles: [data.article] });
    syncFollowActions();
    $("dossier-reading-access").textContent = data.article.reading_access?.label || "Publisher excerpt";
    $("dossier-reading-notice").textContent = data.reading_notice;
    const highlights = data.summary?.highlights || [];
    $("dossier-highlights").hidden = !highlights.length;
    $("dossier-highlights-basis").textContent = data.summary?.limited_source ?
      "Selected sentences from the publisher excerpt" : "Selected sentences from the article shared with permission";
    $("dossier-highlights-list").replaceChildren(...highlights.map((text) => {
      const line = node("li", "", text);
      line.lang = data.article.language || "";
      line.dir = "auto";
      return line;
    }));
    $("dossier-indexed-by").textContent = (data.also_indexed_by || []).map((entry) => entry.label).join(", ");
    $("dossier-indexed-by-row").hidden = !$("dossier-indexed-by").textContent;
    const references = (data.article.references || []).filter((reference) => reference.url !== data.article.url);
    $("dossier-references").hidden = !references.length;
    $("dossier-reference-list").replaceChildren(...references.map((reference) => {
      const line = node("li");
      line.append(externalLink(reference.url, reference.label));
      return line;
    }));
    const body = $("dossier-full-body");
    body.replaceChildren();
    body.hidden = !data.reading?.html;
    if (data.reading?.html) {
      body.append(node("h3", "dossier-section-title", "Full article"),
        node("p", "dossier-reading-notice", `Shared with permission · ${data.reading.attribution}`),
        ...readingContent(data.reading.html));
    }
    dossier.coverage = data.coverage || [];
    const coverageIds = new Set(dossier.coverage.map((story) => story.id));
    renderDossierLinks("dossier-matches", dossier.coverage);
    renderDossierLinks("dossier-related", (data.related || []).filter((story) => !coverageIds.has(story.id)));
  } catch (error) {
    if (error.name !== "AbortError" && dossier.article?.id === article.id)
      status("dossier-feedback", "Related coverage could not be loaded. The original source remains available.");
  }
}

async function openLinkedArticle() {
  const id = new URLSearchParams(location.search).get("article");
  if (!id || $("dossier-drawer").open) return;
  const local = [...state.articles, ...state.recommendations, ...saved.values()].find((article) => article.id === id);
  if (local) return openDossier(local, $("cmd-palette-btn"));
  try {
    const data = await request(`/api/articles/${encodeURIComponent(id)}`);
    if (new URLSearchParams(location.search).get("article") === id)
      openDossier(data.article, $("cmd-palette-btn"), data);
  } catch (error) {
    status("news-status", error.message, true);
  }
}

function openDossier(article, trigger, details) {
  if (!article || $("dossier-drawer").open) return;
  dossier.trigger = trigger;
  dossier.openerId = String(article.id);
  dossier.articles = visibleStories().slice();
  dossier.index = dossier.articles.findIndex((story) => String(story.id) === String(article.id));
  if (dossier.index < 0) {
    dossier.articles = [article];
    dossier.index = 0;
  }
  renderDossier(details);
  $("dossier-drawer").showModal();
  $("dossier-title").focus({ preventScroll: true });
}

function renderDossier(details) {
  $("dossier-references").hidden = true;
  const article = dossier.article = dossier.articles[dossier.index];
  markAsRead(article.id);
  const topic = article.category || article.topic;
  const coverage = article.kind === "video" ? "Creator video" : article.kind === "podcast" ? "Podcast episode" : article.content_format === "newsletter" ? "Newsletter article" : state.coverageTypes[article.coverage] || coverageLabels[article.coverage];
  const publisher = article.sourceName || article.publisher || "Original source";
  const region = publisherRegion(article);
  const timestamp = article.publishedAt || article.published_at;
  const href = externalLink(article.original_url || article.sourceUrl || article.url, "").getAttribute("href");
  const summary = publishedExcerpt(article);
  const basis = article.summary_basis === "ai_feed_summary" ? "AI summary of publisher feed" : "Publisher excerpt";

  $("dossier-index").textContent = `Story ${dossier.index + 1} of ${dossier.articles.length}`;
  $("dossier-prev").disabled = dossier.index === 0;
  $("dossier-next").disabled = dossier.index === dossier.articles.length - 1;
  $("dossier-topic").textContent = state.topics[topic] || article.topic_label || "Technology";
  $("dossier-topic").className = `source-badge ${Object.hasOwn(state.topics, topic) ? topic : ""}`;
  $("dossier-coverage").textContent = coverage || "";
  $("dossier-coverage").hidden = !coverage;
  $("dossier-reading-access").textContent = article.reading_access?.label || (article.has_excerpt ? "Publisher excerpt" : "Headline & link");
  $("dossier-contribute").href = `/contribute.html?article=${encodeURIComponent(article.id)}`;
  $("dossier-research").href = `/research.html?article=${encodeURIComponent(article.id)}`;
  syncFollowActions();

  $("dossier-title").textContent = article.title;
  $("dossier-title").lang = article.language || "";
  $("dossier-title").dir = article.language === "ar" ? "rtl" : "auto";
  $("dossier-source-mark").textContent = publisher.replace(/^The\s+/i, "").slice(0, 1).toUpperCase();
  $("dossier-publisher").textContent = publisher;
  $("dossier-provenance").textContent = originalLanguage(article.language);
  $("dossier-author").textContent = article.author ? `By ${article.author}` : "";
  $("dossier-author").hidden = !article.author;
  $("dossier-tags").replaceChildren(...(article.subjects || []).filter((id) => subjectLabels[id]).map((id) => {
    const link = node("a", "meta-pill", subjectLabels[id]);
    link.href = `/?${new URLSearchParams({ subject: id, window: "7d" })}#reading-room`;
    return link;
  }));
  const discussion = externalLink(article.discussion_url, "").getAttribute("href");
  $("dossier-discussion").hidden = !discussion;
  if (discussion) $("dossier-discussion").href = discussion;
  else $("dossier-discussion").removeAttribute("href");
  $("dossier-time").textContent = timestamp ? relativeTime(timestamp, article.publication_date_precision) : "";
  $("dossier-time").dateTime = timestamp || "";
  $("dossier-time").title = timestamp ? readableTime(timestamp) : "";
  $("dossier-external-link").hidden = !href;
  if (href) $("dossier-external-link").href = href;
  else $("dossier-external-link").removeAttribute("href");

  $("dossier-basis").textContent = summary ? basis : "Headline only";
  $("dossier-summary").textContent = summary || "Open the original publication for details.";
  $("dossier-reading-notice").textContent = summary ?
    "Publisher-supplied excerpt. Read the original for the complete article, images, and any subscriber content." :
    "Headline and source link only. The full article has not been retrieved or summarized.";
  $("dossier-summary").lang = summary && article.summary_basis !== "ai_feed_summary" ? article.language || "" : "";
  $("dossier-summary").dir = $("dossier-summary").lang === "ar" ? "rtl" : "auto";
  $("dossier-full-body").hidden = true;
  $("dossier-full-body").replaceChildren();
  $("dossier-highlights").hidden = true;
  $("dossier-highlights").open = false;
  $("dossier-highlights-list").replaceChildren();
  $("dossier-indexed-by-row").hidden = true;
  $("dossier-indexed-by").textContent = "";
  const effectiveWhy = deriveWhyItMatters(article);
  $("dossier-why-section").hidden = !effectiveWhy;
  $("dossier-why-text").textContent = effectiveWhy || "";
  const effectiveTakeaway = deriveKeyTakeaway(article);
  $("dossier-takeaways-section").hidden = !effectiveTakeaway;
  $("dossier-takeaways-list").replaceChildren(...(effectiveTakeaway ? [node("li", "", effectiveTakeaway)] : []));
  $("dossier-audit-url").textContent = href ? new URL(href).hostname : "Unavailable";
  $("dossier-audit-region").textContent = region || "Unspecified";
  $("dossier-topic-link").hidden = !Object.hasOwn(state.topics, topic);
  $("dossier-topic-link").href = `/?${new URLSearchParams({ topic, window: "7d" })}#reading-room`;
  status("dossier-feedback", "");
  syncDossierActions();
  $("dossier-drawer").querySelector(".dossier-body").scrollTop = 0;
  const url = new URL(location.href);
  url.searchParams.set("article", article.id);
  history.replaceState(null, "", url);
  loadArticleDetails(article, details);
}

function syncDossierActions() {
  if (!dossier.article) return;
  const isPinned = state.pins.has(String(dossier.article.id));
  const isSaved = saved.has(String(dossier.article.id));
  $("dossier-pin-btn").setAttribute("aria-pressed", String(isPinned));
  $("dossier-save-btn").setAttribute("aria-pressed", String(isSaved));
  $("dossier-pin-btn").textContent = isPinned ? "Pinned" : "Pin to brief";
  $("dossier-save-btn").textContent = isSaved ? "Saved" : "Save story";
  syncDossierAudio();
}

function moveDossier(offset) {
  const next = dossier.index + offset;
  if (next < 0 || next >= dossier.articles.length) return;
  dossier.index = next;
  renderDossier();
  $("dossier-title").focus({ preventScroll: true });
}

$("dossier-close").addEventListener("click", () => $("dossier-drawer").close());
$("dossier-drawer").addEventListener("close", () => {
  dossier.controller?.abort();
  if ($("hide-read").getAttribute("aria-pressed") === "true" && state.view !== "saved") renderStories();
  const url = new URL(location.href);
  url.searchParams.delete("article");
  history.replaceState(null, "", url);
  const fallback = $("stories").querySelector(`[data-story-card-id="${CSS.escape(dossier.openerId)}"] .card-dossier-btn`);
  const trigger = dossier.trigger?.isConnected && dossier.trigger.getClientRects().length ? dossier.trigger : fallback;
  (trigger || $("cmd-palette-btn")).focus({ preventScroll: true });
  dossier.article = null;
  dossier.articles = [];
  dossier.trigger = null;
});
$("dossier-drawer").addEventListener("keydown", (event) => {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.isComposing) return;
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    moveDossier(event.key === "ArrowLeft" ? -1 : 1);
  }
});
$("dossier-prev").addEventListener("click", () => moveDossier(-1));
$("dossier-next").addEventListener("click", () => moveDossier(1));
$("dossier-follow-author").addEventListener("click", () => {
  status("dossier-feedback", preferences.toggleAuthor(dossier.article));
  syncFollowActions();
});
$("dossier-follow-publication").addEventListener("click", () => {
  status("dossier-feedback", preferences.togglePublication(dossier.article));
  syncFollowActions();
});
$("dossier-coverage-brief").addEventListener("click", () => {
  if (!dossier.article || !dossier.coverage.length) return;
  const newPins = [dossier.article, ...dossier.coverage].filter((story) => !state.pins.has(String(story.id)));
  if (state.pins.size + newPins.length > 10) {
    status("dossier-feedback", "Free up pin slots in your brief to add this coverage.", true);
    return;
  }
  for (const story of newPins) state.pins.set(String(story.id), story);
  if (state.pins.size > Number($("article-count").value))
    $("article-count").value = state.pins.size <= 5 ? "5" : "10";
  renderPins();
  renderStories();
  $("dossier-drawer").close();
  openBuilder("build", $("nav-builder"));
  status("pin-status", `${state.pins.size} stories pinned to your brief.`);
});
$("dossier-summarize").addEventListener("click", async () => {
  const article = dossier.article;
  if (!article || state.composing) return;
  $("dossier-drawer").close();
  openBuilder("build", $("nav-builder"));
  const brief = await composeBrief({ edition: "personal", pinned_ids: [String(article.id)], top_n: 1,
    hours: 720, persona: "engineer", style: "technical",
    focus: "Summarize the supplied publisher excerpt. Preserve source attribution and state what cannot be established from this limited material." }, false);
  if (brief) focusPreview();
});
$("dossier-pin-btn").addEventListener("click", () => {
  if (!state.pins.has(String(dossier.article.id)) && state.pins.size >= 10) {
    status("dossier-feedback", "All 10 pin slots are in use.", true);
    return;
  }
  togglePin(dossier.article);
  syncDossierActions();
});
$("dossier-save-btn").addEventListener("click", () => {
  if (!saved.has(String(dossier.article.id)) && saved.size >= 100) {
    status("dossier-feedback", "You can keep up to 100 saved stories.", true);
    return;
  }
  toggleSaved(dossier.article);
  syncDossierActions();
});
$("dossier-copy-btn").addEventListener("click", async () => {
  const article = dossier.article;
  try {
    await navigator.clipboard.writeText(storyMarkdown(article));
    if (dossier.article === article) status("dossier-feedback", "Copied story as Markdown.");
  } catch {
    if (dossier.article === article) status("dossier-feedback", "Clipboard access was unavailable.", true);
  }
});
$("dossier-share-btn")?.addEventListener("click", async () => {
  const article = dossier.article;
  if (!article) return;
  const href = `${location.origin}/?article=${encodeURIComponent(article.id)}#reading-room`;
  const title = article.title;
  if (navigator.share) {
    try {
      await navigator.share({ title, url: href });
      if (dossier.article === article) status("dossier-feedback", "Story shared.");
      return;
    } catch (err) {
      if (err.name === "AbortError") return;
    }
  }
  try {
    await navigator.clipboard.writeText(href);
    if (dossier.article === article) status("dossier-feedback", "Story link copied to clipboard.");
  } catch {
    if (dossier.article === article) status("dossier-feedback", "Clipboard access was unavailable.", true);
  }
});
$("dossier-font-btn")?.addEventListener("click", () => {
  const isLarge = $("dossier-summary").classList.toggle("large-reading-text");
  $("dossier-why-text")?.classList.toggle("large-reading-text", isLarge);
  $("dossier-full-body")?.classList.toggle("large-reading-text", isLarge);
  $("dossier-font-btn").setAttribute("aria-pressed", String(isLarge));
  status("dossier-feedback", isLarge ? "Reading font enlarged." : "Standard font size.");
});

const audio = { playlist: [], index: 0, origin: null, utterance: null, timer: null, status: "", generation: 0 };
const speechAvailable = Boolean(window.speechSynthesis) && typeof window.SpeechSynthesisUtterance === "function";

function syncDossierAudio() {
  const current = audio.playlist[audio.index];
  const isActive = Boolean(dossier.article && current && String(dossier.article.id) === String(current.id) &&
    ["starting", "playing", "paused"].includes(audio.status));
  $("dossier-listen-btn").hidden = !speechAvailable;
  $("dossier-listen-btn").textContent = isActive ? (audio.status === "paused" ? "Resume" : "Pause") : "Listen";
  $("dossier-listen-btn").disabled = isActive && audio.status === "starting";
  $("dossier-stop-btn").hidden = !isActive;
}

function renderAudio() {
  const article = audio.playlist[audio.index];
  $("audio-player-bar").hidden = !article;
  $("audio-story-title").textContent = article?.title || "";
  $("audio-story-title").lang = article?.language || "";
  const labels = { starting: "Starting audio", playing: "Playing", paused: "Paused",
    error: "Narration is unavailable for this story" };
  $("audio-status").textContent = article && labels[audio.status] ?
    `${labels[audio.status]}${audio.playlist.length > 1 ? ` · ${audio.index + 1} of ${audio.playlist.length}` : ""}` : "";
  $("audio-prev-btn").hidden = $("audio-next-btn").hidden = audio.playlist.length < 2;
  $("audio-prev-btn").disabled = audio.index === 0;
  $("audio-next-btn").disabled = audio.index >= audio.playlist.length - 1;
  $("audio-play-pause-btn").hidden = audio.status === "error";
  $("audio-play-pause-btn").disabled = audio.status === "starting";
  $("audio-play-pause-btn").textContent = audio.status === "paused" ? "Resume" : "Pause";
  syncDossierAudio();
}

function cancelSpeech() {
  clearTimeout(audio.timer);
  audio.utterance = null;
  window.speechSynthesis?.cancel();
}

function stopAudio() {
  const currentFocus = document.activeElement;
  const restoreFocus = $("audio-player-bar").contains(currentFocus);
  const stoppedInDossier = currentFocus === $("dossier-stop-btn");
  audio.generation++;
  cancelSpeech();
  audio.playlist = [];
  audio.status = "";
  renderAudio();
  if (stoppedInDossier) $("dossier-listen-btn").focus();
  if (restoreFocus) {
    const trigger = audio.origin?.getClientRects().length ? audio.origin : $("cmd-palette-btn");
    trigger.focus({ preventScroll: true });
  }
}

function speakStory(index) {
  cancelSpeech();
  audio.index = index;
  const article = audio.playlist[index];
  const excerpt = publishedExcerpt(article);
  const publisher = article.sourceName || article.publisher;
  const utterance = new SpeechSynthesisUtterance([article.title, publisher, excerpt].filter(Boolean).join(". "));
  utterance.lang = article.language || document.documentElement.lang;
  audio.utterance = utterance;
  audio.status = "starting";
  renderAudio();

  function fail() {
    if (audio.utterance !== utterance) return;
    cancelSpeech();
    audio.status = "error";
    renderAudio();
    if (dossier.article && String(dossier.article.id) === String(article.id)) {
      status("dossier-feedback", "Your browser could not narrate this story. A speech voice may be unavailable.", true);
      $("dossier-listen-btn").focus();
    }
  }

  audio.timer = setTimeout(fail, 9_000);
  utterance.onstart = () => {
    if (audio.utterance !== utterance) return;
    clearTimeout(audio.timer);
    audio.status = "playing";
    renderAudio();
  };
  utterance.onend = () => {
    if (audio.utterance !== utterance) return;
    if (audio.index + 1 < audio.playlist.length) speakStory(audio.index + 1);
    else stopAudio();
  };
  utterance.onerror = fail;
  try {
    window.speechSynthesis.speak(utterance);
  } catch {
    fail();
  }
}

function startAudio(articles, trigger) {
  const playlist = articles.filter((article) => article?.title);
  if (!playlist.length) return;
  audio.generation++;
  audio.playlist = playlist;
  audio.origin = trigger;
  speakStory(0);
}

function toggleAudioPause() {
  if (audio.status === "paused") {
    window.speechSynthesis.resume();
    audio.status = "playing";
  } else if (audio.status === "playing") {
    window.speechSynthesis.pause();
    audio.status = "paused";
  }
  renderAudio();
}

$("dossier-listen-btn").addEventListener("click", (event) => {
  const article = dossier.article;
  if (String(audio.playlist[audio.index]?.id) === String(article.id) && ["playing", "paused"].includes(audio.status)) {
    toggleAudioPause();
  } else {
    status("dossier-feedback", "");
    startAudio([article], event.currentTarget);
  }
});
$("dossier-stop-btn").addEventListener("click", stopAudio);
$("audio-play-pause-btn").addEventListener("click", toggleAudioPause);
$("audio-stop-btn").addEventListener("click", stopAudio);
$("audio-prev-btn").addEventListener("click", () => { if (audio.index > 0) speakStory(audio.index - 1); });
$("audio-next-btn").addEventListener("click", () => { if (audio.index + 1 < audio.playlist.length) speakStory(audio.index + 1); });

$("world-audio-btn").hidden = !speechAvailable;
$("world-audio-btn").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const generation = ++audio.generation;
  button.disabled = true;
  status("world-status", "Preparing today's audio brief…");
  try {
    const result = await jsonPost("/api/digest", { edition: "world", hours: 24, top_n: 5 });
    if (generation !== audio.generation) return;
    startAudio(result.digest.articles, button);
    status("world-status", "");
  } catch (error) {
    if (generation === audio.generation) status("world-status", error.message || "Audio brief unavailable. Try again.", true);
  } finally {
    if (generation !== audio.generation && $("world-status").textContent === "Preparing today's audio brief…")
      status("world-status", "");
    button.disabled = false;
  }
});

const commandInput = $("command-input");
let commandItems = [];
let commandIndex = 0;

function openFeedCommand(configure) {
  if (state.view !== "feed") $("view-feed").click();
  configure();
  reflectFilters();
  loadNews();
  $("search").focus({ preventScroll: true });
  $("reading-room").scrollIntoView({ block: "start", behavior: "instant" });
}

function listCommands() {
  const actions = [
    { label: "Open Research Desk", run: () => { location.href = "/research.html"; } },
    { label: "Build a personalized brief", run: () => $("nav-builder").click() },
    { label: "Read the daily briefing", run: () => $("view-briefing").click() },
    { label: "Preview the Global Top 5", run: () => $("world-preview").click() },
    { label: "Email the Global Top 5", run: () => {
      $("world-form").closest("details").open = true;
      $("hero-email").focus();
    } },
    { label: "Switch to For You recommendations", run: () => {
      $("view-for-you").click();
      $("reading-title").focus({ preventScroll: true });
      $("reading-room").scrollIntoView({ block: "start", behavior: "instant" });
    }},
    { label: "Browse saved stories", run: () => {
      $("view-saved").click();
      $("reading-title").focus({ preventScroll: true });
      $("reading-room").scrollIntoView({ block: "start", behavior: "instant" });
    }},
    { label: "Browse sources", run: () => { location.href = "/sources.html"; } },
    { label: "Switch between light and dark", run: () => {
      const theme = $("site-theme");
      theme.value = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      theme.dispatchEvent(new Event("change"));
    }},
    { label: "Browse independent reporting", run: () => openFeedCommand(() => { $("coverage").value = "reporting"; }) },
  ];
  if (saved.size) actions.push({ label: "Export saved stories as Markdown", run: () => $("export-saved-md").click() });
  if (speechAvailable && !$("world-audio-btn").disabled) {
    actions.push({ label: "Listen to the Global Top 5", run: () => $("world-audio-btn").click() });
  }
  const topics = Object.entries(state.topics).map(([id, label]) => ({
    label, run: () => openFeedCommand(() => { state.topic = id; }),
  }));
  const regions = Object.entries(state.regions).map(([id, label]) => ({
    label, run: () => openFeedCommand(() => { $("region").value = id; }),
  }));
  const layouts = [
    { label: "Show story cards", run: () => setLayout("cards", true) },
    { label: "Show compact story list", run: () => setLayout("list", true) },
  ];
  const commands = [["Actions", actions], ["Layout", layouts], ["Topics", topics], ["Publisher regions", regions]];
  if (state.trending?.length) {
    const trendingCommands = state.trending.map((item) => ({
      label: `#${item.tag} (${item.count} stories)`,
      run: () => openFeedCommand(() => {
        $("search").value = item.query || item.tag;
        state.searching = true;
      }),
    }));
    commands.splice(3, 0, ["Trending topics", trendingCommands]);
  }
  return commands;
}

function normalizeCommand(value) {
  return value.normalize("NFKD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

function renderCommandResults(query) {
  const terms = normalizeCommand(query).split(/\s+/).filter(Boolean);
  const matches = (label) => terms.every((term) => normalizeCommand(label).includes(term));
  const groups = listCommands().map(([group, items]) => [group, items.filter((item) => matches(`${group} ${item.label}`))]);
  if (query) {
    const stories = visibleStories().filter((article) => matches(article.title)).slice(0, 5).map((article) => ({
      label: article.title, language: article.language, run: () => openDossier(article, $("cmd-palette-btn")),
    }));
    groups.unshift(["Current stories", stories]);
    groups.push(["Archive", [{ label: `Search all stories for “${query}”`, run: () => openFeedCommand(() => {
      state.topic = state.source = "all";
      state.publisher = "";
      for (const id of ["region", "publisher", "coverage", "language"]) $(id).value = "";
      $("kind").value = "all";
      $("sort").value = "relevance";
      $("search").value = query;
      state.hours = 168;
    }) }]]);
  }

  const results = $("command-results");
  results.replaceChildren();
  commandItems = [];
  for (const [name, items] of groups) {
    if (!items.length) continue;
    const group = node("div");
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", name);
    const heading = node("p", "command-group-heading", name);
    heading.setAttribute("aria-hidden", "true");
    group.append(heading);
    for (const item of items) {
      const option = node("div", "command-item", item.label);
      const index = commandItems.length;
      option.id = `command-option-${index}`;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", "false");
      if (item.language) option.lang = item.language;
      option.addEventListener("click", () => runCommand(item));
      option.addEventListener("pointermove", (event) => {
        if (event.pointerType === "mouse") selectCommand(index);
      });
      commandItems.push({ ...item, option });
      group.append(option);
    }
    results.append(group);
  }
  commandInput.setAttribute("aria-expanded", String(commandItems.length > 0));
  selectCommand(0);
}

function selectCommand(index, scroll = false) {
  commandItems[commandIndex]?.option.setAttribute("aria-selected", "false");
  commandIndex = index;
  const option = commandItems[index]?.option;
  if (!option) {
    commandInput.removeAttribute("aria-activedescendant");
    return;
  }
  option.setAttribute("aria-selected", "true");
  commandInput.setAttribute("aria-activedescendant", option.id);
  if (scroll) option.scrollIntoView({ block: "nearest" });
}

function openCommandPalette() {
  const dialog = $("command-dialog");
  if (dialog.open) return;
  commandInput.value = "";
  renderCommandResults("");
  dialog.showModal();
  commandInput.focus();
}

function runCommand(item) {
  $("command-dialog").close();
  item.run();
}

$("cmd-palette-btn").querySelector("kbd").textContent = /Mac/i.test(navigator.platform) ? "⌘ K" : "Ctrl K";
$("research-search-link").addEventListener("click", () => {
  try { sessionStorage.setItem("informa-research-query", $("search").value.trim().slice(0, 150)); } catch { /* The desk can open without a query. */ }
});
$("cmd-palette-btn").addEventListener("click", openCommandPalette);
$("command-close").addEventListener("click", () => $("command-dialog").close());
$("command-dialog").addEventListener("close", () => {
  commandInput.setAttribute("aria-expanded", "false");
  commandInput.removeAttribute("aria-activedescendant");
});

for (const id of ["command-dialog", "dossier-drawer"]) {
  $(id).addEventListener("click", (event) => {
    const dialog = event.currentTarget;
    if (event.target !== dialog) return;
    const { left, right, top, bottom } = dialog.getBoundingClientRect();
    if (event.clientX < left || event.clientX > right || event.clientY < top || event.clientY > bottom) dialog.close();
  });
}

commandInput.addEventListener("input", () => renderCommandResults(commandInput.value.trim()));
commandInput.addEventListener("keydown", (event) => {
  if (event.isComposing || !commandItems.length) return;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const increment = event.key === "ArrowDown" ? 1 : -1;
    selectCommand((commandIndex + increment + commandItems.length) % commandItems.length, true);
  } else if (event.key === "Enter") {
    event.preventDefault();
    runCommand(commandItems[commandIndex]);
  }
});

window.addEventListener("keydown", (event) => {
  if (event.defaultPrevented || event.isComposing) return;
  const key = event.key.toLowerCase();
  const palette = $("command-dialog");
  if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && key === "k") {
    if ($("mail-dialog").open || $("dossier-drawer").open || $("composer").classList.contains("open")) return;
    event.preventDefault();
    if (palette.open) palette.close();
    else openCommandPalette();
    return;
  }
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || palette.open) return;
  const card = event.target.closest?.(".story[data-story-card-id]");
  if (!card || !$("stories").contains(card)) return;
  if (key === "j" || key === "k") {
    const next = key === "j" ? card.nextElementSibling : card.previousElementSibling;
    if (next?.classList.contains("story")) {
      event.preventDefault();
      next.querySelector(".card-dossier-btn")?.focus();
    }
  } else if (key === "p" || key === "s") {
    event.preventDefault();
    const storyId = CSS.escape(card.dataset.storyCardId);
    card.querySelector(key === "p" ? "[data-pin-id]" : ".save-button").click();
    if (!card.isConnected) {
      const replacement = $("stories").querySelector(`[data-story-card-id="${storyId}"] .card-dossier-btn`);
      (replacement || $("view-saved")).focus({ preventScroll: true });
    }
  }
});
