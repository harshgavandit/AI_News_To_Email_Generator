"use strict";
import { coverageLabels, fillOptions, languageOptions, optionLabel, originalLanguage, regionId, regionOptions, topicOptions } from "./catalog.js";

const $ = (id) => document.getElementById(id);
const state = {
  articles: [],
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
const windows = { 12: "12h", 24: "24h", 168: "7d", 720: "30d" };
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
function relativeTime(value) {
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
}

function toggleSaved(article) {
  const id = String(article.id);
  const removing = saved.has(id);
  if (!removing && saved.size >= 100) {
    status("news-status", "You can save up to 100 stories. Remove one to save another.", true);
    return;
  }
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
  (replacement || $("view-saved")).focus({ preventScroll: Boolean(replacement) });
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
        const date = node("time", "", relativeTime(article.published_at));
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
function syncURL() {
  const url = new URL(location.href);
  for (const [key, value] of Object.entries({
    source: state.source,
    window: windows[state.hours],
    q: $("search").value.trim(),
    topic: state.topic,
    region: $("region").value,
    publisher: state.publisher,
    kind: $("kind").value,
    coverage: $("coverage").value,
    language: $("language").value,
    sort: $("sort").value === defaultSort(state.searching) ? "" : $("sort").value,
  })) {
    if (!value || value === "all") url.searchParams.delete(key);
    else url.searchParams.set(key, value);
  }
  history.replaceState(null, "", url);
  $("clear-search").hidden = !$("search").value;
  const count = Number(state.source !== "all") + Number(Boolean(state.publisher)) +
    Number($("kind").value !== "all") + Number(Boolean($("coverage").value)) + Number(Boolean($("language").value));
  $("filter-count").hidden = !count;
  $("filter-count").textContent = count;
  $("reset-filters").hidden = state.view !== "feed" ||
    (!count && !$("region").value && state.topic === "all" && state.hours === 12 && !state.searching && $("sort").value === "latest");
  renderActiveFilters();
}

function renderActiveFilters() {
  const filters = $("active-filters");
  const selectLabel = (id) => $(id).selectedOptions[0]?.textContent;
  const publisher = state.sources.find((source) => source.id === state.publisher)?.label || state.publisher;
  const group = state.sources.find((source) => source.id === state.source)?.label ||
    ({ openai: "OpenAI", anthropic: "Anthropic", youtube: "YouTube" })[state.source] || state.source;
  const active = [
    [state.source !== "all" && group, () => { state.source = "all"; }],
    [state.publisher && publisher, () => { state.publisher = $("publisher").value = ""; }],
    [$("kind").value !== "all" && selectLabel("kind"), () => { $("kind").value = "all"; }],
    [$("coverage").value && selectLabel("coverage"), () => { $("coverage").value = ""; }],
    [$("language").value && selectLabel("language"), () => { $("language").value = ""; }],
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
  state.hours = Number(Object.keys(windows).find((hours) => windows[hours] === windowValue || hours === windowValue)) || 12;
  state.topic = Object.hasOwn(state.topics, params.get("topic")) ? params.get("topic") : "all";
  $("search").value = (params.get("q") || "").slice(0, 150);
  state.searching = Boolean($("search").value.trim());
  $("region").value = params.get("region") || "";
  $("kind").value = params.get("kind") || "all";
  $("coverage").value = params.get("coverage") || "";
  $("language").value = params.get("language") || "";
  if ($("kind").selectedIndex === -1) $("kind").value = "all";
  if ($("coverage").selectedIndex === -1) $("coverage").value = "";
  if ($("language").selectedIndex === -1) $("language").value = "";
  $("sort").value = params.get("sort") || defaultSort(state.searching);
  if ($("sort").selectedIndex === -1) $("sort").value = defaultSort(state.searching);
  if ($("region").selectedIndex === -1) $("region").value = "";
  $("clear-search").hidden = !$("search").value;
}
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
function renderStories() {
  $("outage-links").hidden = state.topic !== "outages";
  const container = $("stories");
  container.replaceChildren();
  const isSaved = state.view === "saved";
  $("export-saved-md").hidden = !isSaved || !saved.size;
  $("pin-all-saved").hidden = !isSaved || !saved.size;
  let articles = isSaved ? [...saved.values()].reverse() : state.articles;
  if (state.highSignalOnly && !isSaved) {
    articles = articles.filter((a) => a.coverage === "reporting" || a.coverage === "preprint" || a.coverage === "advisory" || a.research_status === "preprint");
  }
  if (!articles.length) {
    const empty = node("div", "empty reading-empty");
    const query = $("search").value.trim();
    empty.append(node("strong", "", isSaved ? "No saved stories" : "No matching stories"));
    empty.append(node("p", "", isSaved ? "Save an article to keep it in this browser." :
      query ? `Try a different search for “${query}”, or widen the time window.` :
        state.highSignalOnly ? "No high-signal stories found in this window. Try toggling off the High Signal filter." :
        "Try a longer time window or a different topic, publisher region, or source."));
    const nextWindow = Object.keys(windows).map(Number).find((hours) => hours > state.hours);
    if (isSaved) {
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
    const date = node("time", "", relativeTime(timestamp));
    date.title = readableTime(timestamp);
    if (timestamp) date.dateTime = timestamp;
    const summary = article.cleanSummary || article.description || article.summary || "";
    const wordCount = (article.title + " " + summary).split(/\s+/).length;
    const readingMinutes = article.readingTimeMinutes || Math.max(1, Math.ceil(wordCount / 65));
    const badges = node("div", "story-meta-badges");
    badges.append(
      node(
        "span",
        `source-badge ${Object.hasOwn(state.topics, topic) ? topic : ""}`,
        state.topics[topic] || article.topic_label || "Technology",
      ),
      node("span", "meta-pill region-pill", publisherRegion(article)),
      node("span", "meta-pill read-time-pill", `${readingMinutes}m read`),
    );
    top.append(badges, date);
    const heading = node("h3");
    if (article.language) heading.lang = article.language;
    const storyLink = externalLink(article.sourceUrl || article.url, article.title);
    storyLink.title = "Click to inspect Intelligence Dossier (⌘/Ctrl+click to open original URL)";
    storyLink.addEventListener("click", (e) => {
      if (!e.metaKey && !e.ctrlKey && !e.shiftKey) {
        e.preventDefault();
        openDossier(article);
      }
    });
    const externalMark = node("span", "story-external-mark", "↗");
    externalMark.setAttribute("aria-hidden", "true");
    storyLink.append(" ", externalMark);
    heading.append(storyLink);
    const bottom = node("div", "story-bottom");
    const publisher = article.sourceName || article.publisher || "Original source";
    const sourceMark = node("span", "source-mark", publisher.replace(/^The\s+/i, "").slice(0, 1).toUpperCase());
    sourceMark.setAttribute("aria-hidden", "true");
    const attribution = node("div", "story-attribution");
    const sourceType = article.kind === "video" ? "Creator video" :
      state.coverageTypes[article.coverage] || coverageLabels[article.coverage];
    attribution.append(
      node("strong", "", publisher),
      node("span", "", [sourceType, publisherRegion(article), originalLanguage(article.language)].filter(Boolean).join(" · ")),
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

    const dossierBtn = node("button", "card-dossier-btn", "Dossier");
    dossierBtn.type = "button";
    dossierBtn.title = "Open full intelligence dossier (Enter)";
    dossierBtn.addEventListener("click", () => openDossier(article));

    const audioBtn = node("button", "card-audio-btn", "🎧");
    audioBtn.type = "button";
    audioBtn.title = "Listen to audio narration";
    audioBtn.setAttribute("aria-label", `Listen to ${article.title}`);
    audioBtn.addEventListener("click", () => playStoryAudio(article));

    const actions = node("div", "story-actions");
    actions.append(audioBtn, dossierBtn, save, pin);
    bottom.append(actions);
    main.append(top, heading);
    card.append(main);
    const storySummary = article.cleanSummary || article.description || article.summary;
    if (article.whyItMatters) {
      const perspectiveWrap = node("div", "story-perspectives");
      const tabGroup = node("div", "perspective-tabs");
      const tabSummary = node("button", "perspective-tab active", "Summary");
      tabSummary.type = "button";
      const tabWhy = node("button", "perspective-tab", "Why It Matters");
      tabWhy.type = "button";
      tabGroup.append(tabSummary, tabWhy);

      const paragraph = node("p", "story-summary", storySummary || "Read original source for coverage details.");
      if (article.language && article.has_excerpt) paragraph.lang = article.language;

      const why = node("div", "why-matters-box");
      why.hidden = true;
      why.append(node("span", "why-tag", "✦ STRATEGIC CONTEXT"), document.createTextNode(article.whyItMatters));

      tabSummary.addEventListener("click", () => {
        tabSummary.classList.add("active");
        tabWhy.classList.remove("active");
        paragraph.hidden = false;
        why.hidden = true;
      });
      tabWhy.addEventListener("click", () => {
        tabWhy.classList.add("active");
        tabSummary.classList.remove("active");
        paragraph.hidden = true;
        why.hidden = false;
      });

      perspectiveWrap.append(tabGroup, paragraph, why);
      main.append(perspectiveWrap);
    } else if (storySummary) {
      const paragraph = node("p", "story-summary", storySummary);
      if (article.language && article.has_excerpt) paragraph.lang = article.language;
      main.append(paragraph);
    }
    if (article.thumbnail_url && /^https:\/\/i\.ytimg\.com\/vi\/[\w-]{11}\/mqdefault\.jpg$/.test(article.thumbnail_url)) {
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
  $("show-more").hidden = isSaved || !state.cursor;
  $("brief-from-view").hidden = isSaved || !state.articles.length || !(state.topic !== "all" ||
    $("region").value || $("language").value || state.publisher || state.source !== "all" || state.hours !== 12 || state.searching);
  const context = [
    state.topics[state.topic],
    $("region").value && state.regions[$("region").value],
    $("language").value && state.languages[$("language").value],
  ].filter(Boolean);
  status(
    "news-status",
    isSaved ? `${saved.size} ${saved.size === 1 ? "story" : "stories"} saved on this browser` :
      [`${state.articles.length ? `${state.articles.length} of ` : ""}${state.total.toLocaleString()} ${state.total === 1 ? "story" : "stories"}`, ...context].join(" · "),
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
    (state.source === "all" || state.source === source.source || state.source === source.id) &&
    (!state.publisher || state.publisher === source.id) &&
    (!$("region").value || $("region").value === regionId(source)) &&
    (!$("language").value || $("language").value === source.language) &&
    ($("kind").value === "all" || $("kind").value === source.kind) &&
    (!$("coverage").value || $("coverage").value === source.coverage));
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
    if (controller.signal.aborted || state.view !== "feed" || state.feedKey !== newsParams().toString()) return;
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

async function loadNews(append = false, force = false) {
  if (state.view !== "feed") return;
  clearTimeout(searchTimer);
  const searching = Boolean($("search").value.trim());
  if ($("sort").value === defaultSort(state.searching)) $("sort").value = defaultSort(searching);
  state.searching = searching;
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
    if (state.controller !== controller || state.view !== "feed") return;
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
    if (data.refresh_requested) {
      if (force) setTimeout(() => {
        if (state.controller === controller) checkForUpdates();
      }, 9000);
    }
    if (focusMore) $("stories").children[previousSize]?.querySelector("h3 a")?.focus();
  } catch (error) {
    if (state.controller === controller && error.name !== "AbortError" && state.view === "feed") {
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
for (const button of $("window-controls").children)
  button.addEventListener("click", () => {
    state.hours = Number(button.dataset.hours);
    for (const peer of $("window-controls").children)
      peer.setAttribute("aria-pressed", String(peer === button));
    loadNews();
  });
for (const id of ["region", "kind", "coverage", "language"]) $(id).addEventListener("change", () => loadNews());
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
for (const view of ["feed", "saved"]) {
  $(`view-${view}`).addEventListener("click", () => {
    if (state.view === view) return;
    clearTimeout(searchTimer);
    state.controller?.abort();
    state.updateCheck?.abort();
    state.view = view;
    for (const peer of ["feed", "saved"])
      $(`view-${peer}`).setAttribute("aria-pressed", String(peer === view));
    $("feed-controls").hidden = $("sort").hidden = $("refresh").hidden = view === "saved";
    $("stories").setAttribute("aria-busy", "false");
    syncURL();
    renderStories();
    if (view === "feed") loadNews();
  });
}
$("reset-filters").addEventListener("click", () => {
  clearTimeout(searchTimer);
  state.topic = state.source = "all";
  state.publisher = "";
  state.hours = 12;
  state.searching = false;
  for (const id of ["search", "region", "publisher", "coverage", "language"]) $(id).value = "";
  $("kind").value = "all";
  $("sort").value = "latest";
  reflectFilters();
  $("search").focus();
  loadNews();
});
$("search").addEventListener("input", () => {
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
$("brief-from-view").addEventListener("click", () => {
  $("digest-topic").value = state.topic === "all" ? "" : state.topic;
  $("digest-region").value = $("region").value;
  $("digest-language").value = $("language").value;
  $("digest-window").value = String(state.hours);
  const source = state.publisher || (state.source !== "all" ? state.source : "");
  state.digestSources.clear();
  if (source) state.digestSources.add(source);
  renderDigestSources();
  const query = $("search").value.trim();
  if (query) $("focus").value = query;
  if (source || query || $("language").value) $("coverage-options").open = true;
  openBuilder();
});
$("show-updates").addEventListener("click", async () => {
  await loadNews();
  ($("stories").querySelector("h3 a") || $("search")).focus();
});
setInterval(checkForUpdates, 60_000);
for (const id of ["refresh", "retry-sources"])
  $(id).addEventListener("click", () => loadNews(false, true));
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
  if (mobile()) {
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
  } else {
    $("composer-title").focus({ preventScroll: true });
    $("composer").scrollIntoView({ block: "start" });
  }
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
  if (!mobile()) closeBuilder(false);
});
$("composer").addEventListener("keydown", (event) => {
  if (!mobile() || !$("composer").classList.contains("open") || $("mail-dialog").open) return;
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
  const eml = `Subject: Your Informa AI\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=UTF-8\r\nContent-Transfer-Encoding: base64\r\n\r\n${encoded.match(/.{1,76}/g).join("\r\n")}\r\n`;
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
  $("topic-mobile").value = state.topic === "all" ? "" : state.topic;
  $("outage-links").hidden = state.topic !== "outages";
}
function reflectFilters() {
  reflectTopic();
  for (const button of $("window-controls").children)
    button.setAttribute("aria-pressed", String(Number(button.dataset.hours) === state.hours));
  renderSourceFilters();
}
renderCoverageControls();
restoreURL();
reflectFilters();
reflectSavedCount();
setTab("build");
if (location.hash === "#composer")
  window.addEventListener("load", () => openBuilder("build", $("nav-builder")), { once: true });
loadNews();
loadHeadlines();
window.addEventListener("hashchange", () => {
  if (location.hash === "#composer") openBuilder("build", $("nav-builder"));
});
window.addEventListener("popstate", () => {
  clearTimeout(searchTimer);
  restoreURL();
  reflectFilters();
  loadNews();
});

let activeStoryIndex = -1;
function updateActiveStory(index) {
  const cards = Array.from($("stories").querySelectorAll(".story"));
  if (!cards.length) return;
  activeStoryIndex = Math.max(0, Math.min(index, cards.length - 1));
  cards.forEach((card, i) => {
    card.classList.toggle("keyboard-active", i === activeStoryIndex);
  });
  cards[activeStoryIndex]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* High-Signal Filter & Read All Status (Feedly Inspired) */
state.highSignalOnly = false;
$("filter-high-signal")?.addEventListener("click", () => {
  state.highSignalOnly = !state.highSignalOnly;
  $("filter-high-signal").setAttribute("aria-pressed", String(state.highSignalOnly));
  renderStories();
});

$("mark-all-read")?.addEventListener("click", () => {
  for (const a of state.articles) readStories.add(String(a.id));
  try {
    localStorage.setItem(readKey, JSON.stringify([...readStories].slice(-300)));
  } catch {}
  renderStories();
  status("story-action-status", "All visible stories marked as read.");
});

/* Saved Stories Markdown Export & Pin All (Trace Inspired) */
$("export-saved-md")?.addEventListener("click", async () => {
  if (!saved.size) return;
  const lines = ["# Informa AI — Saved Intelligence Brief", ""];
  for (const art of saved.values()) {
    lines.push(`## ${art.title}`);
    lines.push(`*Publisher:* ${art.publisher || art.sourceName || "Source"} (${publisherRegion(art)})`);
    lines.push(`*Source:* ${art.url || art.sourceUrl}`);
    const sum = art.cleanSummary || art.description || art.summary || "";
    if (sum) lines.push(`\n${sum}`);
    if (art.whyItMatters) lines.push(`\n*Why It Matters:* ${art.whyItMatters}`);
    if (art.keyTakeaway) lines.push(`*Key Takeaway:* ${art.keyTakeaway}`);
    lines.push("\n---\n");
  }
  try {
    await navigator.clipboard.writeText(lines.join("\n"));
    status("story-action-status", `Copied ${saved.size} saved stories as Markdown to clipboard!`);
  } catch {
    status("story-action-status", "Clipboard access unavailable.");
  }
});

$("pin-all-saved")?.addEventListener("click", () => {
  let count = 0;
  for (const art of saved.values()) {
    if (state.pins.size < 10 && !state.pins.has(String(art.id))) {
      state.pins.set(String(art.id), art);
      count++;
    }
  }
  renderPins();
  renderStories();
  status("story-action-status", `Pinned ${count} saved stories to your brief.`);
});

/* Slide-Over Intelligence Dossier (Particle + Trace Inspired) */
let currentDossierStory = null;
let currentDossierList = [];
let currentDossierIndex = 0;

function openDossier(article) {
  if (!article) return;
  currentDossierStory = article;
  markAsRead(article.id);
  const isSavedView = state.view === "saved";
  currentDossierList = isSavedView ? [...saved.values()].reverse() : state.articles;
  currentDossierIndex = currentDossierList.findIndex((a) => String(a.id) === String(article.id));
  if (currentDossierIndex === -1) currentDossierIndex = 0;

  $("dossier-index").textContent = `Story ${currentDossierIndex + 1} of ${currentDossierList.length}`;
  $("dossier-prev").disabled = currentDossierIndex <= 0;
  $("dossier-next").disabled = currentDossierIndex >= currentDossierList.length - 1;

  const topic = article.category || article.topic;
  $("dossier-topic").textContent = state.topics[topic] || article.topic_label || "Technology";
  $("dossier-topic").className = `source-badge ${Object.hasOwn(state.topics, topic) ? topic : ""}`;
  $("dossier-region").textContent = publisherRegion(article);

  const summary = article.cleanSummary || article.description || article.summary || "";
  const wordCount = (article.title + " " + summary).split(/\s+/).length;
  const readingMinutes = article.readingTimeMinutes || Math.max(1, Math.ceil(wordCount / 65));
  $("dossier-read-time").textContent = `${readingMinutes}m read`;

  const covLabel = state.coverageTypes[article.coverage] || coverageLabels[article.coverage] || "Primary Reporting";
  $("dossier-coverage").textContent = covLabel;

  $("dossier-title").textContent = article.title;
  const publisher = article.sourceName || article.publisher || "Original source";
  $("dossier-source-mark").textContent = publisher.replace(/^The\s+/i, "").slice(0, 1).toUpperCase();
  $("dossier-publisher").textContent = publisher;
  $("dossier-provenance").textContent = [covLabel, publisherRegion(article), originalLanguage(article.language)].filter(Boolean).join(" · ");

  const timestamp = article.publishedAt || article.published_at;
  $("dossier-time").textContent = relativeTime(timestamp);
  $("dossier-time").title = readableTime(timestamp);

  const rawUrl = article.sourceUrl || article.url || "#";
  $("dossier-external-link").href = rawUrl;
  $("dossier-summary").textContent = summary || "Read original publication for details.";

  if (article.whyItMatters) {
    $("dossier-why-section").hidden = false;
    $("dossier-why-text").textContent = article.whyItMatters;
  } else {
    $("dossier-why-section").hidden = true;
  }

  const takeaways = article.keyTakeaway ? [article.keyTakeaway] : [];
  if (takeaways.length) {
    $("dossier-takeaways-section").hidden = false;
    $("dossier-takeaways-list").replaceChildren();
    for (const t of takeaways) {
      const li = node("li", "", t);
      $("dossier-takeaways-list").append(li);
    }
  } else {
    $("dossier-takeaways-section").hidden = true;
  }

  try {
    const domain = new URL(rawUrl).hostname;
    $("dossier-audit-url").textContent = domain;
  } catch {
    $("dossier-audit-url").textContent = rawUrl;
  }
  $("dossier-audit-region").textContent = publisherRegion(article);
  $("dossier-audit-coverage").textContent = covLabel;
  $("dossier-audit-status").textContent = "Verified Feed Ingestion";

  const isPinned = state.pins.has(String(article.id));
  $("dossier-pin-btn").textContent = isPinned ? "Unpin from brief" : "Pin to brief";

  const isBookmarked = saved.has(String(article.id));
  $("dossier-save-btn").textContent = isBookmarked ? "Saved" : "Save story";

  $("dossier-backdrop").hidden = false;
  $("dossier-drawer").hidden = false;
  $("dossier-title").focus();
}

function closeDossier() {
  $("dossier-backdrop").hidden = true;
  $("dossier-drawer").hidden = true;
  currentDossierStory = null;
}

$("dossier-close")?.addEventListener("click", closeDossier);
$("dossier-backdrop")?.addEventListener("click", closeDossier);

$("dossier-prev")?.addEventListener("click", () => {
  if (currentDossierIndex > 0) openDossier(currentDossierList[currentDossierIndex - 1]);
});
$("dossier-next")?.addEventListener("click", () => {
  if (currentDossierIndex < currentDossierList.length - 1) openDossier(currentDossierList[currentDossierIndex + 1]);
});

$("dossier-pin-btn")?.addEventListener("click", () => {
  if (!currentDossierStory) return;
  togglePin(currentDossierStory);
  const isPinned = state.pins.has(String(currentDossierStory.id));
  $("dossier-pin-btn").textContent = isPinned ? "Unpin from brief" : "Pin to brief";
});

$("dossier-save-btn")?.addEventListener("click", () => {
  if (!currentDossierStory) return;
  toggleSaved(currentDossierStory);
  const isBookmarked = saved.has(String(currentDossierStory.id));
  $("dossier-save-btn").textContent = isBookmarked ? "Saved" : "Save story";
});

$("dossier-copy-btn")?.addEventListener("click", async () => {
  if (!currentDossierStory) return;
  const art = currentDossierStory;
  const lines = [
    `# ${art.title}`,
    `*Publisher:* ${art.publisher || art.sourceName || "Source"} (${publisherRegion(art)})`,
    `*Source:* ${art.url || art.sourceUrl}`,
    "",
    art.cleanSummary || art.description || art.summary || "",
  ];
  if (art.whyItMatters) lines.push(`\n**Strategic Context:** ${art.whyItMatters}`);
  if (art.keyTakeaway) lines.push(`**Key Takeaway:** ${art.keyTakeaway}`);
  try {
    await navigator.clipboard.writeText(lines.join("\n"));
    $("dossier-copy-btn").textContent = "Copied! ✓";
    setTimeout(() => { $("dossier-copy-btn").textContent = "Copy Markdown"; }, 2000);
  } catch {}
});

$("dossier-listen-btn")?.addEventListener("click", () => {
  if (currentDossierStory) playStoryAudio(currentDossierStory);
});

/* Native Web Speech Audio Engine (Particle-Inspired) */
const audioNarrator = {
  activeStory: null,
  playlist: [],
  playlistIndex: 0,
  synth: typeof window !== "undefined" && window.speechSynthesis,
  utterance: null,
};

function playStoryAudio(article) {
  if (!audioNarrator.synth) {
    status("news-status", "Speech synthesis is not supported on this browser.", true);
    return;
  }
  audioNarrator.activeStory = article;
  audioNarrator.playlist = [article];
  audioNarrator.playlistIndex = 0;
  speakStory(article);
}

function speakStory(article) {
  if (!audioNarrator.synth || !article) return;
  audioNarrator.synth.cancel();

  const title = article.title || "";
  const publisher = article.publisher || article.sourceName || "Source";
  const why = article.whyItMatters ? ` Strategic context: ${article.whyItMatters}.` : "";
  const summary = article.cleanSummary || article.description || article.summary || "";
  const text = `${title}. Reported by ${publisher}.${why} ${summary}`;

  const utter = new SpeechSynthesisUtterance(text);
  utter.rate = 1.05;
  utter.pitch = 1.0;
  utter.onend = () => {
    if (audioNarrator.playlistIndex < audioNarrator.playlist.length - 1) {
      audioNarrator.playlistIndex++;
      const nextStory = audioNarrator.playlist[audioNarrator.playlistIndex];
      speakStory(nextStory);
    } else {
      stopAudio();
    }
  };
  utter.onerror = () => stopAudio();

  audioNarrator.utterance = utter;
  $("audio-story-title").textContent = title;
  $("audio-player-bar").hidden = false;
  $("audio-play-pause-btn").textContent = "⏸";
  $("audio-play-pause-btn").setAttribute("aria-label", "Pause narration");
  document.querySelector(".audio-wave")?.classList.remove("paused");
  audioNarrator.synth.speak(utter);
}

function stopAudio() {
  if (audioNarrator.synth) audioNarrator.synth.cancel();
  $("audio-player-bar").hidden = true;
  audioNarrator.activeStory = null;
  audioNarrator.playlist = [];
  audioNarrator.playlistIndex = 0;
}

function toggleAudioPause() {
  if (!audioNarrator.synth) return;
  if (audioNarrator.synth.paused) {
    audioNarrator.synth.resume();
    $("audio-play-pause-btn").textContent = "⏸";
    document.querySelector(".audio-wave")?.classList.remove("paused");
  } else {
    audioNarrator.synth.pause();
    $("audio-play-pause-btn").textContent = "▶";
    document.querySelector(".audio-wave")?.classList.add("paused");
  }
}

$("audio-play-pause-btn")?.addEventListener("click", toggleAudioPause);
$("audio-stop-btn")?.addEventListener("click", stopAudio);
$("audio-prev-btn")?.addEventListener("click", () => {
  if (audioNarrator.playlistIndex > 0) {
    audioNarrator.playlistIndex--;
    speakStory(audioNarrator.playlist[audioNarrator.playlistIndex]);
  }
});
$("audio-next-btn")?.addEventListener("click", () => {
  if (audioNarrator.playlistIndex < audioNarrator.playlist.length - 1) {
    audioNarrator.playlistIndex++;
    speakStory(audioNarrator.playlist[audioNarrator.playlistIndex]);
  }
});

$("world-audio-btn")?.addEventListener("click", () => {
  const stories = state.articles.slice(0, 5);
  if (!stories.length) {
    status("world-status", "Loading stories to narrate...", false);
    return;
  }
  audioNarrator.playlist = stories;
  audioNarrator.playlistIndex = 0;
  speakStory(stories[0]);
});

/* Trace-Inspired Command Palette */
let commandActiveIndex = 0;
let commandItems = [];

function getBaseCommands() {
  const actions = [
    { id: "act-listen-top5", label: "🎧 Listen to Global Top 5 Brief", category: "Actions", run: () => $("world-audio-btn")?.click() },
    { id: "act-send-top5", label: "📬 1-Click Send Global Top 5 Brief", category: "Actions", run: () => { $("hero-email")?.focus(); $("hero-email")?.scrollIntoView({ behavior: "smooth" }); } },
    { id: "act-build", label: "⚙️ Open Brief Builder", category: "Actions", run: () => $("nav-builder")?.click() },
    { id: "act-cards", label: "🗂️ Switch to Editorial Cards View", category: "Layout", run: () => setLayout("cards", true) },
    { id: "act-list", label: "📋 Switch to Compact List View", category: "Layout", run: () => setLayout("list", true) },
    { id: "act-high-signal", label: "✦ Toggle High-Signal Only Stories", category: "Filters", run: () => $("filter-high-signal")?.click() },
    { id: "act-mark-read", label: "✓ Mark All Stories as Read", category: "Actions", run: () => $("mark-all-read")?.click() },
    { id: "act-export-saved", label: "📋 Export Saved Stories as Markdown", category: "Actions", run: () => $("export-saved-md")?.click() },
    { id: "act-theme", label: "🌓 Toggle Light / Dark Theme", category: "Actions", run: () => {
      const current = document.documentElement.dataset.theme;
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("informa-theme", next); } catch {}
      $("site-theme").value = next;
    }},
  ];

  const topics = Object.entries(state.topics).map(([id, label]) => ({
    id: `topic-${id}`,
    label: `✦ Channel: ${label}`,
    category: "Topics",
    run: () => chooseTopic(id),
  }));

  const regions = Object.entries(state.regions).map(([id, label]) => ({
    id: `region-${id}`,
    label: `🌐 Region: ${label}`,
    category: "Regions",
    run: () => {
      $("region").value = id;
      syncURL();
      loadNews();
    },
  }));

  return [...actions, ...topics, ...regions];
}

function openCommandPalette() {
  const dialog = $("command-dialog");
  if (!dialog) return;
  $("command-input").value = "";
  renderCommandResults("");
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.hidden = false;
  $("command-input").focus();
}

function closeCommandPalette() {
  const dialog = $("command-dialog");
  if (!dialog) return;
  if (typeof dialog.close === "function") dialog.close();
  else dialog.hidden = true;
}

$("cmd-palette-btn")?.addEventListener("click", openCommandPalette);
$("command-close")?.addEventListener("click", closeCommandPalette);

function renderCommandResults(query) {
  const cleanQ = query.trim().toLowerCase();
  const base = getBaseCommands();
  const matchedBase = cleanQ ? base.filter((c) => c.label.toLowerCase().includes(cleanQ) || c.category.toLowerCase().includes(cleanQ)) : base;

  const matchedStories = cleanQ ? state.articles.filter((a) => a.title.toLowerCase().includes(cleanQ)).slice(0, 5).map((a) => ({
    id: `story-${a.id}`,
    label: `📰 ${a.title}`,
    category: "Stories",
    run: () => openDossier(a),
  })) : [];

  commandItems = [...matchedBase, ...matchedStories];
  commandActiveIndex = 0;

  const container = $("command-results");
  container.replaceChildren();

  if (!commandItems.length) {
    const empty = node("div", "command-item", "No matching commands or headlines.");
    empty.style.color = "var(--muted)";
    container.append(empty);
    return;
  }

  let lastCategory = "";
  commandItems.forEach((item, idx) => {
    if (item.category !== lastCategory) {
      lastCategory = item.category;
      container.append(node("div", "command-group-heading", lastCategory));
    }
    const row = node("button", `command-item${idx === 0 ? " active" : ""}`);
    row.type = "button";
    row.dataset.cmdIdx = String(idx);
    const left = node("div", "command-item-left");
    left.append(node("span", "command-item-label", item.label));
    row.append(left);
    row.addEventListener("click", () => {
      closeCommandPalette();
      item.run();
    });
    row.addEventListener("mouseenter", () => {
      container.querySelectorAll(".command-item").forEach((el) => el.classList.remove("active"));
      row.classList.add("active");
      commandActiveIndex = idx;
    });
    container.append(row);
  });
}

$("command-input")?.addEventListener("input", (e) => {
  renderCommandResults(e.target.value);
});

$("command-input")?.addEventListener("keydown", (e) => {
  const rows = Array.from($("command-results").querySelectorAll(".command-item"));
  if (e.key === "ArrowDown") {
    e.preventDefault();
    if (commandItems.length) {
      commandActiveIndex = (commandActiveIndex + 1) % commandItems.length;
      rows.forEach((r, i) => r.classList.toggle("active", i === commandActiveIndex));
      rows[commandActiveIndex]?.scrollIntoView({ block: "nearest" });
    }
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    if (commandItems.length) {
      commandActiveIndex = (commandActiveIndex - 1 + commandItems.length) % commandItems.length;
      rows.forEach((r, i) => r.classList.toggle("active", i === commandActiveIndex));
      rows[commandActiveIndex]?.scrollIntoView({ block: "nearest" });
    }
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (commandItems[commandActiveIndex]) {
      closeCommandPalette();
      commandItems[commandActiveIndex].run();
    }
  } else if (e.key === "Escape") {
    closeCommandPalette();
  }
});

/* Keyboard Navigation (Trace & Power-Reader Workflows) */
window.addEventListener("keydown", (e) => {
  const activeEl = document.activeElement;
  const isInput = activeEl && (activeEl.tagName === "INPUT" || activeEl.tagName === "TEXTAREA" || activeEl.tagName === "SELECT" || activeEl.isContentEditable);

  if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
    e.preventDefault();
    openCommandPalette();
    return;
  }

  if (e.key === "Escape") {
    if (!$("command-dialog")?.hidden && $("command-dialog")?.open) {
      closeCommandPalette();
      return;
    }
    if (!$("dossier-drawer")?.hidden) {
      closeDossier();
      return;
    }
    if ($("mail-dialog")?.open) return;
    if (isInput) activeEl.blur();
    return;
  }
  if (isInput) return;

  const cards = Array.from($("stories").querySelectorAll(".story"));
  if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    $("search")?.focus();
    $("search")?.select();
  } else if (e.key === "j" || e.key === "J") {
    e.preventDefault();
    updateActiveStory(activeStoryIndex + 1);
  } else if (e.key === "k" || e.key === "K") {
    e.preventDefault();
    updateActiveStory(activeStoryIndex - 1);
  } else if (e.key === "Enter" && activeStoryIndex >= 0 && activeStoryIndex < cards.length && $("dossier-drawer")?.hidden) {
    e.preventDefault();
    cards[activeStoryIndex]?.querySelector(".card-dossier-btn")?.click();
  } else if ((e.key === "p" || e.key === "P") && activeStoryIndex >= 0 && activeStoryIndex < cards.length) {
    e.preventDefault();
    cards[activeStoryIndex]?.querySelector(".pin-button")?.click();
  } else if ((e.key === "s" || e.key === "S") && activeStoryIndex >= 0 && activeStoryIndex < cards.length) {
    e.preventDefault();
    cards[activeStoryIndex]?.querySelector(".save-button")?.click();
  } else if (e.key === "b" || e.key === "B") {
    e.preventDefault();
    $("nav-builder")?.click();
  }
});
