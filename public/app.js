"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  articles: [],
  total: 0,
  cursor: null,
  digest: null,
  sources: [],
  counts: {},
  controller: null,
  topic: "all",
  source: "all",
  publisher: "",
  hours: 12,
  view: "feed",
  pins: new Map(),
  digestSources: new Set(),
  interests: new Set(),
  composing: false,
  mail: null,
  pending: null,
  tab: "build",
  delivery: "email",
};
const categories = {
  all: "All stories",
  ai: "AI & LLMs",
  software: "Software",
  startups: "Startups",
  bigtech: "Big Tech",
  chips: "Chips & Hardware",
  industry: "Policy",
  security: "Security",
  outages: "Outages",
  video: "Video",
};
const sourceLabels = {
  status: "Official status",
  reporting: "Reporting",
  publisher: "Publisher update",
  discussion: "Community discussion",
};
const interestLabels = [
  "AI Agents & Tool Use",
  "RAG & Production Engineering",
  "Voice & Multimodal",
  "AI Security & Red Teaming",
  "Model Benchmarks & Pricing",
  "Enterprise Governance & Policy",
];
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
const saved = new Map();
try {
  const stored = JSON.parse(localStorage.getItem(savedKey) || "[]");
  for (const item of stored.slice(0, 100)) {
    if (typeof item.id === "string" && typeof item.title === "string" && typeof item.url === "string") saved.set(item.id, item);
  }
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
  if (removing) saved.delete(id);
  else saved.set(id, article);
  let persisted = false;
  try {
    localStorage.setItem(savedKey, JSON.stringify([...saved.values()]));
    persisted = true;
  } catch {}
  reflectSavedCount();
  renderStories();
  const replacement = [...$("stories").querySelectorAll(".save-button")].find((button) => button.dataset.storyId === id);
  (replacement || $("view-saved")).focus();
  status("news-status", removing ? `Story removed. ${saved.size} saved.` :
    persisted ? `Story saved. ${saved.size} saved on this browser.` : "Story saved for this session. Browser storage is unavailable.");
}
async function request(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("The server is temporarily unavailable. Please try again.");
  }
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "This request could not be completed. Check your settings and try again.",
    );
  return data;
}
const jsonPost = (url, data) =>
  request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
function syncURL() {
  const url = new URL(location.href);
  for (const [key, value] of Object.entries({
    source: state.source,
    window: { 12: "12h", 24: "24h", 168: "7d", 720: "30d" }[state.hours],
    q: $("search").value.trim(),
    topic: state.topic,
    region: $("region").value,
    publisher: state.publisher,
    kind: $("kind").value,
    sort: $("sort").value === "latest" ? "" : $("sort").value,
  })) {
    if (!value || value === "all") url.searchParams.delete(key);
    else url.searchParams.set(key, value);
  }
  history.replaceState(null, "", url);
  $("clear-search").hidden = !$("search").value;
  const count = Number(state.source !== "all") + Number(Boolean($("region").value)) + Number(Boolean(state.publisher)) + Number($("kind").value !== "all");
  $("filter-count").hidden = !count;
  $("filter-count").textContent = count;
  $("reset-filters").hidden = state.view !== "feed" || (!count && state.topic === "all" && state.hours === 12 && !$("search").value && $("sort").value === "latest");
}
function restoreURL() {
  const params = new URLSearchParams(location.search);
  state.source = params.get("source") || "all";
  state.publisher = params.get("publisher") || "";
  $("publisher").value = state.publisher;
  const windowValue =
    { "12h": 12, "24h": 24, "7d": 168, "30d": 720 }[params.get("window")] ||
    Number(params.get("window"));
  state.hours = [12, 24, 168, 720].includes(windowValue) ? windowValue : 12;
  state.topic = Object.hasOwn(categories, params.get("topic")) ? params.get("topic") : "all";
  $("search").value = (params.get("q") || "").slice(0, 150);
  $("region").value = params.get("region") || "";
  $("kind").value = params.get("kind") || "all";
  if ($("kind").selectedIndex === -1) $("kind").value = "all";
  $("sort").value = params.get("sort") || "latest";
  if ($("sort").selectedIndex === -1) $("sort").value = "latest";
  if ($("region").selectedIndex === -1) $("region").value = "";
  $("clear-search").hidden = !$("search").value;
  for (const button of $("window-controls").children)
    button.setAttribute(
      "aria-pressed",
      String(Number(button.dataset.hours) === state.hours),
    );
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
  const articles = isSaved ? [...saved.values()].reverse() : state.articles;
  if (!articles.length)
    container.append(
      node(
        "div",
        "empty",
        isSaved ? "You haven’t saved any stories. Use Save on any story to keep it in this browser." :
          "No stories match these filters. Try another source or a longer time window.",
      ),
    );
  for (const article of articles) {
    const card = node(
      "article",
      `story${state.pins.has(String(article.id)) ? " pinned" : ""}`,
    );
    const top = node("div", "story-top");
    const timestamp = article.publishedAt || article.published_at;
    const date = node("time", "", relativeTime(timestamp));
    date.title = readableTime(timestamp);
    if (timestamp) date.dateTime = timestamp;
    top.append(
      node(
        "span",
        `source-badge ${Object.hasOwn(categories, article.topic) ? article.topic : ""}`,
        categories[article.category || article.topic] ||
          article.topic_label ||
          "Technology",
      ),
      date,
    );
    const heading = node("h3");
    heading.append(
      externalLink(article.sourceUrl || article.url, article.title),
    );
    const bottom = node("div", "story-bottom");
    const publisher = article.sourceName || article.publisher || "Original source";
    const sourceMark = node("span", "source-mark", publisher.replace(/^The\s+/i, "").slice(0, 1).toUpperCase());
    sourceMark.setAttribute("aria-hidden", "true");
    const attribution = node("div", "story-attribution");
    attribution.append(
      node("strong", "", publisher),
      node("span", "", [sourceLabels[article.coverage], article.region && article.region !== "Global" ? article.region : ""].filter(Boolean).join(" · ")),
    );
    const byline = node("div", "story-byline");
    byline.append(sourceMark, attribution);
    bottom.append(byline);
    const pin = node(
      "button",
      "pin-button",
      state.pins.has(String(article.id)) ? "✓ Pinned" : "+ Pin",
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
    const actions = node("div", "story-actions");
    actions.append(save, pin);
    bottom.append(actions);
    card.append(top, heading);
    const summary = article.cleanSummary || article.description || article.summary;
    if (summary) card.append(node("p", "story-summary", summary));
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
      card.insertBefore(image, heading);
    }
    if (article.whyItMatters) {
      const why = node("p", "why-matters");
      why.append(node("strong", "", "Why it matters. "), document.createTextNode(article.whyItMatters));
      card.append(why);
    }
    card.append(bottom);
    container.append(card);
  }
  $("show-more").hidden = isSaved || !state.cursor;
  $("stories").classList.toggle("has-lead", !isSaved && state.source === "all" && state.topic === "all" && state.hours <= 24 &&
    !$("search").value && !$("region").value && !state.publisher && state.articles.length >= 3);
  status(
    "news-status",
    isSaved ? `${saved.size} ${saved.size === 1 ? "story" : "stories"} saved on this browser` :
      `${state.articles.length} of ${state.total} ${state.total === 1 ? "story" : "stories"}`,
  );
}
function togglePin(article) {
  const id = String(article.id);
  if (state.pins.has(id)) state.pins.delete(id);
  else {
    if (state.pins.size === 10) {
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
  if (restorePinFocus) $("stories").querySelector(`[data-pin-id="${CSS.escape(id)}"]`)?.focus({ preventScroll: true });
}
function renderPins() {
  const count = state.pins.size;
  $("selected-count").textContent = `${count} / 10`;
  $("mobile-pin-count").textContent = `${count} pinned`;
  $("pinned-bar-count").textContent =
    `${count} ${count === 1 ? "story" : "stories"} pinned`;
  $("pinned-bar").hidden = !count;
  $("clear-pins").hidden = !count;
  $("selected-stories").replaceChildren();
  if (!count)
    $("selected-stories").append(
      node("p", "small", "Pin stories from the news desk to include them."),
    );
  for (const article of state.pins.values()) {
    const row = node("div", "selected-item");
    row.append(node("span", "", article.title));
    const remove = node("button", "", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${article.title}`);
    remove.addEventListener("click", () => togglePin(article));
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
  });
function updateSourceCatalog(sources) {
  if (!sources?.length) return;
  state.sources = sources;
  const enabled = sources.filter((s) => s.enabled);
  for (const id of ["publisher", "digest-sources"]) {
    const select = $(id);
    const value = id === "publisher" ? state.publisher : select.value;
    if (select.options.length === enabled.length + 1 && enabled.every((s, index) =>
      select.options[index + 1].value === s.id && select.options[index + 1].text === s.label)) continue;
    select.replaceChildren();
    const option = node(
      "option",
      "",
      id === "publisher" ? "All publishers" : "All sources",
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
function renderHealth(freshness) {
  const sources = state.sources.filter((s) => s.enabled);
  const scoped = sources.filter((s) => (state.source === "all" || [s.id, s.source].includes(state.source)) &&
    (!state.publisher || s.id === state.publisher) && ($("kind").value === "all" || s.kind === $("kind").value));
  const failed = scoped.filter((s) => s.available === false);
  const fresh = sources.filter((s) => s.freshness === "fresh" || (!s.freshness && s.available === true)).length;
  const delayed = sources.some((s) => s.checked_at) && fresh === 0;
  $("source-health-label").textContent = fresh
    ? `${fresh} of ${sources.length} sources fresh`
    : delayed ? "Updates delayed" : "Sources awaiting check";
  $("source-health-button").classList.toggle("degraded", fresh < sources.length);
  $("updated").textContent = freshness?.checked_at
    ? `Selected feeds checked ${readableTime(freshness.checked_at)}`
    : "Individual source check times below.";
  $("source-health-list").className = "source-health-list";
  $("source-health-list").replaceChildren();
  for (const s of sources) {
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
  $("failed-alert").hidden = !failed.length && freshness?.status !== "stale";
  $("failed-message").textContent = failed.length
    ? `${failed.map((s) => s.label).join(", ")} ${failed.length === 1 ? "is" : "are"} temporarily unavailable. Saved stories remain readable.`
    : "Source checks are delayed. Showing the latest stories in the archive.";
}
async function loadNews(append = false, force = false, quiet = false) {
  if (state.view !== "feed") return;
  state.controller?.abort();
  const controller = new AbortController();
  state.controller = controller;
  $("stories").setAttribute("aria-busy", "true");
  $("show-more").disabled = $("refresh").disabled = true;
  if (!quiet) status("news-status", "Loading stories…");
  if (!state.articles.length) {
    $("stories").classList.remove("has-lead");
    $("stories").replaceChildren(...Array.from({ length: 3 }, () => {
      const card = node("div", "story-skeleton");
      card.setAttribute("aria-hidden", "true");
      card.append(node("span"), node("span"), node("span"));
      return card;
    }));
  }
  syncURL();
  try {
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
    if (append && state.cursor) params.set("cursor", state.cursor);
    if (force) params.set("force", "true");
    const data = await request(`/api/news?${params}`, {
      signal: controller.signal,
    });
    if (state.controller !== controller || state.view !== "feed") return;
    if (quiet && $("reading-room").contains(document.activeElement)) return;
    const focusMore = append && document.activeElement === $("show-more");
    const previousSize = append ? state.articles.length : 0;
    if (append) {
      const known = new Set(state.articles.map((article) => article.id));
      state.articles.push(...data.articles.filter((article) => !known.has(article.id)));
    } else state.articles = data.articles;
    state.cursor = data.next_cursor;
    state.total = data.total;
    state.counts = data.source_counts || {};
    updateSourceCatalog(data.sources);
    renderStories();
    renderSourceFilters();
    renderHealth(data.freshness);
    if (data.refresh_requested) {
      status("news-status", "Showing the archive while source checks are requested.");
      if (force) setTimeout(() => {
        if (state.controller === controller && state.view === "feed") loadNews(false, false, true);
      }, 9000);
    }
    if (focusMore) $("stories").children[previousSize]?.querySelector("h3 a")?.focus();
  } catch (error) {
    if (!quiet && error.name !== "AbortError") {
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
      }
      status("news-status", error.message, true);
    }
  } finally {
    if (state.controller === controller) {
      $("stories").setAttribute("aria-busy", "false");
      $("show-more").disabled = $("refresh").disabled = false;
    }
  }
}
for (const [topic, label] of Object.entries(categories)) {
  const button = node("button", "topic-chip", label);
  button.type = "button";
  button.dataset.topic = topic;
  button.addEventListener("click", () => {
    state.topic = topic;
    $("outage-links").hidden = topic !== "outages";
    for (const peer of $("topics").children)
      peer.setAttribute("aria-pressed", String(peer === button));
    loadNews();
  });
  $("topics").append(button);
}
for (const label of interestLabels) {
  const button = node("button", "topic-chip", label);
  button.type = "button";
  button.setAttribute("aria-pressed", "false");
  button.addEventListener("click", () => {
    if (state.interests.has(label)) state.interests.delete(label);
    else state.interests.add(label);
    button.setAttribute("aria-pressed", String(state.interests.has(label)));
  });
  $("interests").append(button);
}
for (const button of $("window-controls").children)
  button.addEventListener("click", () => {
    state.hours = Number(button.dataset.hours);
    for (const peer of $("window-controls").children)
      peer.setAttribute("aria-pressed", String(peer === button));
    loadNews();
  });
$("region").addEventListener("change", () => loadNews());
for (const id of ["kind", "sort"]) $(id).addEventListener("change", () => loadNews());
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
    state.view = view;
    for (const peer of ["feed", "saved"])
      $(`view-${peer}`).setAttribute("aria-pressed", String(peer === view));
    $("feed-controls").hidden = $("sort").hidden = view === "saved";
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
  for (const id of ["search", "region", "publisher"]) $(id).value = "";
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
$("clear-search").addEventListener("click", () => {
  clearTimeout(searchTimer);
  $("search").value = "";
  loadNews();
  $("search").focus();
});
$("show-more").addEventListener("click", () => loadNews(true));
setInterval(() => {
  // Avoid replacing an expanded page, interrupting a filter, or polling a hidden tab.
  if (state.view === "feed" && !document.hidden && state.articles.length <= 12 &&
      $("stories").getAttribute("aria-busy") === "false" &&
      !$("reading-room").contains(document.activeElement) && !$("mail-dialog").open) {
    loadNews(false, false, true);
  }
}, 60_000);
for (const id of ["refresh", "retry-sources"])
  $(id).addEventListener("click", () => loadNews(false, true));
let healthCloseTimer;
function showHealth(show) {
  clearTimeout(healthCloseTimer);
  $("source-popover").hidden = !show;
  $("source-health-button").setAttribute("aria-expanded", String(show));
}
$("source-health-button").addEventListener("click", () => showHealth(true));
$("source-health-button").addEventListener("focus", () => showHealth(true));
for (const id of ["source-health-button", "source-popover"]) {
  $(id).addEventListener("mouseenter", () => showHealth(true));
  $(id).addEventListener("mouseleave", () => {
    healthCloseTimer = setTimeout(() => {
      if (
        !$("source-popover").contains(document.activeElement) &&
        document.activeElement !== $("source-health-button")
      )
        showHealth(false);
    }, 180);
  });
}
$("source-popover-close").addEventListener("click", () => showHealth(false));
document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest(".source-health")) showHealth(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    showHealth(false);
    if ($("composer").classList.contains("open")) closeBuilder();
  }
});
const mobile = () => matchMedia("(max-width: 1023px)").matches;
function setTab(tab, focus = false) {
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
}
function openBuilder(tab = "build") {
  setTab(tab);
  if (mobile()) {
    $("composer").classList.add("open");
    $("sheet-backdrop").hidden = false;
    $("mobile-builder").setAttribute("aria-expanded", "true");
    document.body.classList.add("sheet-open");
    $("composer").setAttribute("role", "dialog");
    $("composer").setAttribute("aria-modal", "true");
    $("close-builder").focus();
  } else {
    $("composer-title").focus({ preventScroll: true });
    $("composer").scrollIntoView({ block: "start" });
  }
}
function closeBuilder() {
  $("composer").classList.remove("open");
  $("sheet-backdrop").hidden = true;
  $("mobile-builder").setAttribute("aria-expanded", "false");
  document.body.classList.remove("sheet-open");
  $("composer").removeAttribute("role");
  $("composer").removeAttribute("aria-modal");
  $("mobile-builder").focus();
}
for (const id of ["nav-builder", "mobile-builder", "pinned-build"])
  $(id).addEventListener("click", () => openBuilder());
for (const id of ["close-builder", "sheet-backdrop"])
  $(id).addEventListener("click", closeBuilder);
$("empty-build").addEventListener("click", () => setTab("build", true));
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
matchMedia("(max-width: 1023px)").addEventListener("change", () => {
  setTab(state.tab);
  if (!mobile()) {
    $("composer").classList.remove("open");
    $("sheet-backdrop").hidden = true;
    document.body.classList.remove("sheet-open");
    $("composer").removeAttribute("role");
    $("composer").removeAttribute("aria-modal");
  }
});
$("composer").addEventListener("keydown", (event) => {
  if (
    event.key !== "Tab" ||
    !mobile() ||
    !$("composer").classList.contains("open")
  )
    return;
  const items = [
    ...$("composer").querySelectorAll("button,a,input,select,textarea"),
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
function renderDigest() {
  const digest = state.digest.digest;
  $("copy-fallback").hidden = true;
  $("preview-empty").hidden = true;
  $("preview-content").hidden = false;
  $("preview").replaceChildren();
  $("preview-title").textContent =
    digest.edition === "world"
      ? "Today’s Global Top 5"
      : "Your personalized brief";
  $("preview-basis").textContent = digest.synthesis?.degraded
    ? "Some AI processing was unavailable. Publisher excerpts or headline-only entries are labeled below."
    : state.digest.source_basis || "Based on publisher feed titles and excerpts.";
  $("preview-count").textContent = `(${digest.articles.length})`;
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
    item.append(
      citation,
      node("h3", "", a.title),
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
  const label = button.textContent;
  $("world-brief").disabled = $("world-preview").disabled = $("generate").disabled = true;
  button.textContent = "Preparing your brief…";
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
    button.textContent = label;
  }
}
$("digest-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    edition: "personal",
    name: $("reader-name").value.trim() || "Reader",
    focus: $("focus").value.trim(),
    topics: [...state.interests],
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
    return;
  }
  const brief = await composeBrief(body, false);
  if (brief) $("preview-title").focus();
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
$("world-preview").addEventListener("click", async () => {
  if (await composeWorldBrief()) {
    openBuilder("preview");
    $("preview-title").focus();
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
function mailStep(step) {
  for (const id of ["request-code", "verify-code", "send-brief"])
    $(id).hidden = id !== step;
}
async function showCaptcha() {
  if (captchaWidget !== undefined) {
    window.turnstile.reset(captchaWidget);
    captchaToken = "";
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
  if (captchaWidget !== undefined) return;
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
  if ($("mail-dialog").open) $("mail-dialog").close();
  state.pending = null;
  return result;
}
async function beginDelivery(pending) {
  if (state.pending?.sending) return;
  state.pending = pending;
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
      pending.sending = true;
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
    $("mail-explanation").textContent =
      pending.kind === "webhook"
        ? "Verify your email once and we’ll post your prepared brief to your webhook automatically."
        : "Verify your email once and we’ll send your prepared brief automatically. No account or access key needed.";
    status("mail-status", "");
    $("mail-dialog").showModal();
    await showCaptcha();
  } catch (error) {
    pending.sending = false;
    status(
      $("mail-dialog").open ? "mail-status" : pending.statusId,
      error.message,
      true,
    );
  }
}
$("preview-send-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("send").disabled = true;
  try {
    await beginDelivery({
      kind: "email",
      email: $("preview-email").value.trim(),
      subscribe: $("preview-subscribe").checked,
      statusId: "email-status",
      preview: state.digest,
    });
  } finally {
    $("send").disabled = false;
  }
});
$("webhook-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = $("webhook-url").value.trim();
  if (!url.startsWith("https://")) {
    status("email-status", "Use an HTTPS webhook URL.", true);
    return;
  }
  $("webhook-send").disabled = true;
  try {
    await beginDelivery({
      kind: "webhook",
      email: $("webhook-email").value.trim(),
      url,
      statusId: "email-status",
      preview: state.digest,
    });
  } finally {
    $("webhook-send").disabled = false;
  }
});
$("mail-close").addEventListener("click", () => $("mail-dialog").close());
$("mail-dialog").addEventListener("close", () => {
  $("mail-code").value = "";
  $("owner-key").value = "";
  if (state.pending && !state.pending.sending) {
    status(
      state.pending.statusId,
      "Your brief is ready. Verify your email when you want to send it.",
    );
    state.pending = null;
  }
});
async function submitMail(event, task) {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  status("mail-status", "Working…");
  try {
    await task();
  } catch (error) {
    if (state.pending) state.pending.sending = false;
    status("mail-status", error.message, true);
  } finally {
    button.disabled = false;
  }
}
$("request-code").addEventListener("submit", (event) =>
  submitMail(event, async () => {
    if (!captchaToken) throw new Error("Complete the bot check first.");
    const token = captchaToken;
    captchaToken = "";
    try {
      await jsonPost("/api/mail/challenge", {
        email: $("mail-address").value.trim(),
        captcha: token,
      });
      if (state.pending) state.pending.email = $("mail-address").value.trim();
      mailStep("verify-code");
      $("mail-code").focus();
      status(
        "mail-status",
        "Check your inbox for the six-digit verification code.",
      );
    } catch (error) {
      await showCaptcha();
      throw error;
    }
  }),
);
$("verify-code").addEventListener("submit", (event) =>
  submitMail(event, async () => {
    await jsonPost("/api/mail/verify", { code: $("mail-code").value });
    $("mail-code").value = "";
    mailStep("send-brief");
    status("mail-status", "Inbox verified. Sending your prepared brief…");
    if (state.pending) state.pending.sending = true;
    await performDelivery();
  }),
);
$("send-brief").addEventListener("submit", (event) =>
  submitMail(event, async () => {
    if (state.pending) state.pending.sending = true;
    await performDelivery();
  }),
);
$("different-email").addEventListener("click", async () => {
  try {
    await jsonPost("/api/mail/logout", {});
    $("mail-code").value = "";
    mailStep("request-code");
    await showCaptcha();
    status("mail-status", "");
  } catch (error) {
    status("mail-status", error.message, true);
  }
});
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
  }),
);
function reflectFilters() {
  for (const button of $("topics").children)
    button.setAttribute("aria-pressed", String(button.dataset.topic === state.topic));
  for (const button of $("window-controls").children)
    button.setAttribute("aria-pressed", String(Number(button.dataset.hours) === state.hours));
  $("outage-links").hidden = state.topic !== "outages";
  renderSourceFilters();
}
restoreURL();
reflectFilters();
reflectSavedCount();
setTab("build");
loadNews();
window.addEventListener("popstate", () => {
  clearTimeout(searchTimer);
  restoreURL();
  reflectFilters();
  loadNews();
});
