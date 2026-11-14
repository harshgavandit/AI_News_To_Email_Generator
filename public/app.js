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
  hours: 12,
  pins: new Map(),
  interests: new Set(),
  appendedInterests: new Set(),
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
  industry: "Policy",
  security: "Security",
  outages: "Outages",
  video: "Video",
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
    if (["http:", "https:"].includes(target.protocol)) a.href = target.href;
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
    publisher: $("publisher").value,
  })) {
    if (!value || value === "all") url.searchParams.delete(key);
    else url.searchParams.set(key, value);
  }
  history.replaceState(null, "", url);
  $("clear-search").hidden = !$("search").value;
}
function restoreURL() {
  const params = new URLSearchParams(location.search);
  state.source = params.get("source") || "all";
  const windowValue =
    { "12h": 12, "24h": 24, "7d": 168, "30d": 720 }[params.get("window")] ||
    Number(params.get("window"));
  state.hours = [12, 24, 168, 720].includes(windowValue) ? windowValue : 12;
  state.topic = categories[params.get("topic")] ? params.get("topic") : "all";
  $("search").value = (params.get("q") || "").slice(0, 150);
  $("region").value = ["Global", "APAC", "EU"].includes(params.get("region"))
    ? params.get("region")
    : "";
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
  $("source-filters").replaceChildren();
  for (const [id, label] of Object.entries(names)) {
    const count = state.counts[id];
    const button = node(
      "button",
      "topic-chip",
      `${label}${Number.isInteger(count) ? ` (${count})` : ""}`,
    );
    button.type = "button";
    button.setAttribute("aria-pressed", String(state.source === id));
    button.addEventListener("click", () => {
      state.source = id;
      renderSourceFilters();
      loadNews();
    });
    $("source-filters").append(button);
  }
}
function renderStories() {
  $("outage-links").hidden = state.topic !== "outages";
  const container = $("stories");
  container.replaceChildren();
  if (!state.articles.length)
    container.append(
      node(
        "div",
        "empty",
        "No stories match these filters. Try another source or a longer time window.",
      ),
    );
  for (const article of state.articles) {
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
        "source-badge",
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
    const why = node("p", "why-matters");
    why.append(
      node("strong", "", "Why it matters: "),
      document.createTextNode(
        article.whyItMatters ||
          article.reasoning ||
          "Read the original reporting for context and details.",
      ),
    );
    const bottom = node("div", "story-bottom");
    bottom.append(
      node(
        "span",
        "",
        `${article.sourceName || article.publisher || "Original source"} · ${article.region || "Global"}${article.readingTimeMinutes ? ` · ${article.readingTimeMinutes} min` : ""}`,
      ),
    );
    const pin = node(
      "button",
      "pin-button",
      state.pins.has(String(article.id)) ? "✓ Pinned" : "+ Pin",
    );
    pin.type = "button";
    pin.setAttribute(
      "aria-pressed",
      String(state.pins.has(String(article.id))),
    );
    pin.setAttribute(
      "aria-label",
      `${state.pins.has(String(article.id)) ? "Unpin" : "Pin"} ${article.title}`,
    );
    pin.addEventListener("click", () => togglePin(article));
    bottom.append(pin);
    card.append(
      top,
      heading,
      node(
        "p",
        "story-summary",
        article.cleanSummary ||
          article.description ||
          article.summary ||
          "Read the original story for details.",
      ),
      why,
      bottom,
    );
    container.append(card);
  }
  $("show-more").hidden = !state.cursor;
  status(
    "news-status",
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
  renderStories();
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
  for (const id of ["publisher", "digest-sources"]) {
    const select = $(id);
    const value = select.value;
    select.replaceChildren();
    const option = node(
      "option",
      "",
      id === "publisher" ? "All publishers" : "All sources",
    );
    option.value = id === "publisher" ? "" : "all";
    select.append(option);
    for (const source of sources.filter((s) => s.enabled)) {
      const item = node("option", "", source.label);
      item.value = source.id;
      select.append(item);
    }
    select.value = value;
    if (!select.value) select.value = id === "publisher" ? "" : "all";
  }
  renderHealth();
  renderSourceFilters();
}
function renderHealth(freshness) {
  const sources = state.sources.filter((s) => s.enabled);
  const failed = sources.filter((s) => s.available === false);
  const healthy = sources.filter((s) => s.available === true);
  const delayed = freshness?.status === "stale";
  $("source-health-label").textContent = delayed
    ? "Updates delayed"
    : failed.length
    ? `${failed.length} source${failed.length === 1 ? "" : "s"} delayed`
    : healthy.length
      ? `${healthy.length} sources available`
      : "Sources awaiting check";
  $("source-health-button").classList.toggle("degraded", delayed || failed.length > 0);
  $("updated").textContent = freshness?.checked_at
    ? `Last checked ${readableTime(freshness.checked_at)}`
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
        `${s.available === true ? "Available" : s.available === false ? "Last check failed" : "Waiting for first check"} · Checked ${readableTime(s.checked_at)}${s.last_success ? ` · Last success ${readableTime(s.last_success)}` : ""}`,
      ),
    );
    $("source-health-list").append(row);
  }
  $("failed-alert").hidden = !failed.length;
  $("failed-message").textContent = failed.length
    ? `${failed.map((s) => s.label).join(", ")} ${failed.length === 1 ? "is" : "are"} temporarily unavailable. Saved stories remain readable.`
    : "";
}
async function loadNews(append = false, force = false, quiet = false) {
  state.controller?.abort();
  const controller = new AbortController();
  state.controller = controller;
  $("stories").setAttribute("aria-busy", "true");
  $("show-more").disabled = true;
  if (!quiet) status("news-status", "Loading stories…");
  syncURL();
  try {
    const params = new URLSearchParams({
      hours: String(state.hours),
      source: state.source,
      topic: state.topic,
      region: $("region").value,
      publisher: $("publisher").value,
      q: $("search").value.trim(),
      limit: "12",
    });
    if (append && state.cursor) params.set("cursor", state.cursor);
    if (force) params.set("force", "true");
    const data = await request(`/api/news?${params}`, {
      signal: controller.signal,
    });
    if (state.controller !== controller) return;
    if (quiet && $("reading-room").contains(document.activeElement)) return;
    state.articles = append
      ? [...state.articles, ...data.articles]
      : data.articles;
    state.cursor = data.next_cursor;
    state.total = data.total;
    state.counts = data.source_counts || {};
    updateSourceCatalog(data.sources);
    renderStories();
    renderSourceFilters();
    renderHealth(data.freshness);
  } catch (error) {
    if (!quiet && error.name !== "AbortError") status("news-status", error.message, true);
  } finally {
    if (state.controller === controller) {
      $("stories").setAttribute("aria-busy", "false");
      $("show-more").disabled = false;
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
    if (state.interests.has(label)) {
      state.interests.delete(label);
      if (state.appendedInterests.has(label)) {
        $("focus").value = $("focus")
          .value.split("; ")
          .filter((part) => part !== label)
          .join("; ");
        state.appendedInterests.delete(label);
      }
    } else {
      state.interests.add(label);
      const text = $("focus").value.trim();
      const next = text ? `${text}; ${label}` : label;
      if (!text.includes(label) && next.length <= 400) {
        $("focus").value = next;
        state.appendedInterests.add(label);
      }
    }
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
for (const id of ["region", "publisher"])
  $(id).addEventListener("change", () => loadNews());
let searchTimer;
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
  if (!document.hidden && state.articles.length <= 12 &&
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
  } else $("composer").scrollIntoView({ behavior: "smooth", block: "start" });
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
  $("preview-empty").hidden = true;
  $("preview-content").hidden = false;
  $("preview").replaceChildren();
  $("preview-title").textContent =
    digest.edition === "world"
      ? "Today’s global top stories."
      : "Your personal tech brief.";
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
      node("span", "", `${String(index + 1).padStart(2, "0")} / `),
      externalLink(a.sourceUrl || a.url, `${a.publisher || a.sourceName || a.article_type || "Source"} ↗`),
    );
    item.append(
      citation,
      node("h3", "", a.title),
      node("p", "", a.cleanSummary || a.summary || ""),
    );
    if (a.whyItMatters || a.reasoning)
      item.append(
        node("p", "reason", `${digest.edition === "world" ? "Why it matters" : "Why this matters to you"}: ${a.reasoning || a.whyItMatters}`),
      );
    if (a.keyTakeaway) {
      const takeaway = node("p", "reason");
      takeaway.append(node("strong", "", "Key takeaway. "), document.createTextNode(a.keyTakeaway));
      item.append(takeaway);
    }
    item.append(externalLink(a.sourceUrl || a.url, "Read original source ↗"));
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
      "Ranking stories for your persona and interests…",
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
  $("world-brief").disabled = $("generate").disabled = true;
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
    status(message, error.message, true);
    return null;
  } finally {
    state.composing = false;
    $("world-brief").disabled = $("generate").disabled = false;
    button.textContent = label;
  }
}
$("digest-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const source = $("digest-sources").value;
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
    ...(source === "all" ? {} : { sources: [source] }),
  };
  if (body.pinned_ids.length > body.top_n) {
    status(
      "digest-status",
      "Choose a brief length large enough for your pinned stories.",
      true,
    );
    return;
  }
  await composeBrief(body, false);
});
$("world-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = $("hero-email").value.trim(),
    subscribe = $("hero-subscribe").checked;
  const digest = await composeBrief(
    {
      edition: "world",
      hours: 24,
      top_n: 5,
      persona: "executive",
      style: "executive",
    },
    true,
  );
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
  try {
    await navigator.clipboard.writeText(state.digest.digest.markdown);
    status("email-status", "Markdown copied to your clipboard.");
  } catch {
    status(
      "email-status",
      "Clipboard access was unavailable. Download the brief instead.",
      true,
    );
  }
});
$("download").addEventListener("click", () => {
  download(
    state.digest.digest.html,
    "text/html;charset=utf-8",
    "world-tech-brief.html",
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
  const eml = `Subject: Your World Tech Brief\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=UTF-8\r\nContent-Transfer-Encoding: base64\r\n\r\n${encoded.match(/.{1,76}/g).join("\r\n")}\r\n`;
  download(eml, "message/rfc822", "world-tech-brief.eml");
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
restoreURL();
for (const button of $("topics").children)
  button.setAttribute(
    "aria-pressed",
    String(button.dataset.topic === state.topic),
  );
renderSourceFilters();
setTab("build");
request("/api/sources")
  .then(({ sources }) => {
    updateSourceCatalog(sources);
    const publisher = new URLSearchParams(location.search).get("publisher");
    if (publisher && sources.some((s) => s.id === publisher))
      $("publisher").value = publisher;
    loadNews();
  })
  .catch(() => loadNews());
window.addEventListener("popstate", () => {
  restoreURL();
  for (const button of $("topics").children)
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.topic === state.topic),
    );
  renderSourceFilters();
  loadNews();
});
