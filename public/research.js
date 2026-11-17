import { readingGroups } from "/privacy-data.js";

const byId = (id) => document.getElementById(id);
const form = byId("research-form");
const question = byId("research-question");
const topic = byId("research-topic");
const mode = byId("research-mode");
const submit = byId("research-submit");
const status = byId("research-status");
const results = byId("research-results");
const watchList = byId("watch-list");
const watchStatus = byId("watch-status");
const alertKey = readingGroups.alerts.key;
let currentRequest;
let daily;
let checking = false;
let watchGeneration = 0;
let watches = loadWatches();

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function link(text, href) {
  const node = element("a", text);
  if (typeof href !== "string" || !href.trim()) return node;
  try {
    const url = new URL(href, location.href);
    if (["http:", "https:"].includes(url.protocol)) node.href = url.href;
  } catch { /* Keep the attribution as text if its URL is unavailable. */ }
  return node;
}

function dateLabel(value) {
  const date = new Date(value);
  return Number.isFinite(date.valueOf()) ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date) : "";
}

async function api(path, body, signal) {
  const response = await fetch(path, {
    cache: "no-store", signal,
    ...(body && { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  if (response.status === 429) throw new Error("Too many requests. Wait a moment and try again.");
  if (!response.ok) throw new Error(response.status === 404 ? "This story is no longer available in the archive." :
    "The archive could not complete this request. Please try again.");
  return response.json();
}

function panel(title) {
  const section = element("section", "", "research-panel");
  section.append(element("h2", title));
  return section;
}

function render(data, titles) {
  results.replaceChildren();
  const references = new Map(data.evidence.map((row, index) => [row.id, index + 1]));
  const cite = (id) => {
    const number = references.get(id);
    return link(String(number), `#research-source-${number}`);
  };
  if (data.answer) {
    const answer = panel(data.answer.status === "answered" ? titles.answer : "Evidence limits");
    if (data.answer.claims.length) {
      const claims = element("ol", "", "research-claims");
      for (const claim of data.answer.claims) {
        const item = element("li");
        const text = element("p", claim.text);
        if (claim.kind === "analysis") item.append(element("span", "Interpretation", "research-label"));
        for (const id of claim.source_ids.filter((value) => references.has(value))) {
          const citation = cite(id);
          citation.className = "research-cite";
          citation.setAttribute("aria-label", `Source ${references.get(id)}`);
          text.append(" ", citation);
        }
        item.append(text);
        claims.append(item);
      }
      answer.append(claims);
    }
    answer.append(element("p", data.answer.limitations, "research-note"));
    results.append(answer);
  }
  if (data.clusters?.length) {
    const section = panel("Stories covering the same development");
    const list = element("ul", "", "research-clusters");
    for (const cluster of data.clusters) {
      const item = element("li", cluster.title);
      for (const id of cluster.article_ids.filter((value) => references.has(value))) {
        const citation = cite(id);
        citation.className = "research-cite";
        citation.setAttribute("aria-label", `Source ${references.get(id)}`);
        item.append(" ", citation);
      }
      list.append(item);
    }
    section.append(list);
    results.append(section);
  }
  if (!data.evidence.length) return;
  const evidence = panel(titles.evidence);
  const list = element("ol", "", "research-evidence");
  for (const [index, row] of data.evidence.entries()) {
    const item = element("li");
    item.id = `research-source-${index + 1}`;
    item.tabIndex = -1;
    const heading = element("h3");
    const original = link(row.title, row.url);
    original.lang = row.language;
    original.dir = "auto";
    original.target = "_blank";
    original.rel = "noopener noreferrer";
    heading.append(original);
    const meta = [row.publisher, dateLabel(row.published_at), row.match?.includes("semantic") && "Meaning match"];
    const excerpt = element("p", row.excerpt || "Headline and source link only.");
    excerpt.dir = "auto";
    excerpt.lang = row.language;
    item.append(heading, element("p", meta.filter(Boolean).join(" · "), "research-meta"), excerpt,
      link("Open in Reading Room", `/?article=${encodeURIComponent(row.id)}#reading-room`));
    list.append(item);
  }
  evidence.append(list);
  results.append(evidence);
}

const taskLabels = { search: "Find sources", analyze: "Answer with sources", compare: "Compare coverage", brief: "Build a topic brief" };
mode.addEventListener("change", () => { submit.textContent = taskLabels[mode.value]; });

async function search(body) {
  currentRequest?.abort();
  const controller = new AbortController();
  currentRequest = controller;
  results.replaceChildren();
  results.setAttribute("aria-busy", "true");
  status.textContent = body.mode === "search" ? "Searching the archive…" : "Gathering evidence and checking citations…";
  submit.disabled = true;
  try {
    const data = await api("/api/intelligence/research", body, controller.signal);
    if (controller !== currentRequest) return;
    const label = data.retrieval === "hybrid" ? "Keyword and semantic search" : "Keyword search";
    status.textContent = data.evidence.length ?
      `${data.evidence.length} source${data.evidence.length === 1 ? "" : "s"} · ${label}` :
      "No matching sources. Try a different term, topic, or time range.";
    render(data, { answer: body.mode === "compare" ? "AI coverage comparison" :
      body.mode === "brief" ? "AI topic briefing" : "AI analysis", evidence: "Source evidence" });
    if (body.article_id && data.evidence.length) question.value = data.evidence[0].title.slice(0, 320);
  } catch (error) {
    if (controller === currentRequest && !controller.signal.aborted) status.textContent = error.message;
  } finally {
    if (controller === currentRequest) {
      results.setAttribute("aria-busy", "false");
      submit.disabled = false;
    }
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const q = question.value.trim();
  if (!q) { question.focus(); return; }
  search({ q, mode: mode.value, scope: { hours: Number(byId("research-hours").value), topic: topic.value } });
});

function loadWatches() {
  try {
    const saved = JSON.parse(localStorage.getItem(alertKey));
    if (Array.isArray(saved)) return saved.filter((watch) =>
      watch && /^[a-zA-Z0-9_-]{1,40}$/.test(watch.id) && typeof watch.query === "string" &&
      watch.query.length >= 2 && watch.query.length <= 150).slice(0, 6);
  } catch { /* Use session state when local storage is unavailable. */ }
  return [];
}

function saveWatches() {
  try { localStorage.setItem(alertKey, JSON.stringify(watches)); }
  catch { watchStatus.textContent = "Your browser could not save alerts after this session."; }
}

function renderWatches() {
  watchList.replaceChildren();
  for (const watch of watches) {
    const article = element("article", "", "watch-item");
    const title = element("h3", watch.query);
    const remove = element("button", "Remove", "text-button");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove watch for ${watch.query}`);
    remove.addEventListener("click", () => {
      watchGeneration++;
      watches = watches.filter((item) => item.id !== watch.id);
      saveWatches();
      renderWatches();
      byId("watch-query").focus();
    });
    const header = element("header");
    header.append(title, remove);
    article.append(header);
    const matching = Array.isArray(watch.matches) ? watch.matches : [];
    article.append(element("p", watch.seen === null ? "Waiting for the first check." :
      matching.length ? `${matching.length} recent development${matching.length === 1 ? "" : "s"}` :
      "No matches in the past 48 hours.", "research-meta"));
    const list = element("ul");
    for (const item of matching.slice(0, 5)) {
      const row = element("li");
      row.append(link(item.title, `/?article=${encodeURIComponent(item.id)}#reading-room`));
      if (item.count > 1) row.append(element("span", ` · ${item.count} sources`, "research-meta"));
      list.append(row);
    }
    if (matching.length) article.append(list);
    watchList.append(article);
  }
}

async function checkWatches() {
  if (checking || document.hidden || !watches.length) return;
  checking = true;
  const generation = watchGeneration;
  try {
    const data = await api("/api/intelligence/watch", {
      watches: watches.map(({ id, query }) => ({ id, query })),
    });
    if (generation !== watchGeneration) return;
    let newDevelopments = 0;
    for (const update of data.watches) {
      const watch = watches.find((item) => item.id === update.id);
      if (!watch) continue;
      const seen = Array.isArray(watch.seen) ? watch.seen : [];
      newDevelopments += watch.seen === null ? 0 : update.clusters.filter(
        (cluster) => cluster.article_ids.every((id) => !seen.includes(id))).length;
      watch.matches = update.clusters.map((cluster) =>
        ({ id: cluster.article_ids[0], title: cluster.title, count: cluster.coverage_count }));
      watch.seen = [...new Set([...update.evidence.map((row) => row.id), ...seen])].slice(0, 90);
    }
    watchStatus.textContent = newDevelopments ?
      `${newDevelopments} new development${newDevelopments === 1 ? "" : "s"} since the last check.` :
      "Checked for updates.";
    saveWatches();
    renderWatches();
  } catch (error) {
    watchStatus.textContent = error.message;
  } finally {
    checking = false;
    if (generation !== watchGeneration) checkWatches();
  }
}

byId("watch-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = byId("watch-query");
  const query = input.value.trim();
  if (query.length < 2 || !/[\p{L}\p{N}]/u.test(query)) { watchStatus.textContent = "Enter keywords to watch."; return; }
  if (watches.some((watch) => watch.query.toLowerCase() === query.toLowerCase())) {
    watchStatus.textContent = "You already watch these keywords.";
    return;
  }
  if (watches.length >= 6) { watchStatus.textContent = "Remove an alert before adding another."; return; }
  watchGeneration++;
  watches.push({ id: crypto.randomUUID(), query, seen: null, matches: [] });
  input.value = "";
  saveWatches();
  renderWatches();
  checkWatches();
});
window.addEventListener("storage", ({ key }) => {
  if (key === alertKey || key === "informa-reader-reset" || key === null) {
    watchGeneration++;
    watches = loadWatches();
    renderWatches();
  }
});
document.addEventListener("visibilitychange", checkWatches);
setInterval(checkWatches, 90000);
renderWatches();
checkWatches();

api("/api/intelligence/options").then((options) => {
  for (const [id, label] of Object.entries(options.topics || {})) topic.add(new Option(label, id));
}).catch(() => { /* All topics can still be searched. */ });

const dailyStatus = byId("research-daily-status");
api("/api/intelligence/daily").then(({ brief }) => {
  daily = brief;
  dailyStatus.textContent = brief ? `Generated ${dateLabel(brief.generated_at * 1000)} from archived sources.` :
    "A cited edition will appear when the next briefing is ready.";
  byId("show-daily").hidden = !brief;
  byId("daily-fallback").hidden = Boolean(brief);
}).catch(() => {
  dailyStatus.textContent = "The latest edition could not be loaded.";
  byId("daily-fallback").hidden = false;
});
byId("show-daily").addEventListener("click", () => {
  if (!daily) return;
  currentRequest?.abort();
  currentRequest = null;
  submit.disabled = false;
  results.setAttribute("aria-busy", "false");
  status.textContent = "Intelligence briefing · Past 24 hours";
  render(daily, { answer: "AI intelligence briefing", evidence: "Briefing sources" });
  results.scrollIntoView({ block: "nearest" });
});

api("/api/trending").then(({ trending }) => {
  const entries = trending?.slice(0, 5);
  if (!entries?.length) return;
  byId("research-trend-list").replaceChildren(...entries.map((trend) => {
    const row = element("li");
    const button = element("button", trend.tag, "text-button");
    button.type = "button";
    button.addEventListener("click", () => {
      question.value = trend.query;
      topic.value = "all";
      byId("research-hours").value = "168";
      question.focus();
      if (!submit.disabled) form.requestSubmit();
    });
    row.append(button, element("span", `${trend.source_count} sources`, "research-meta"));
    return row;
  }));
  byId("research-trends").hidden = false;
}).catch(() => { /* Core research works when trend data is unavailable. */ });

const article = new URLSearchParams(location.search).get("article");
if (article && /^[a-zA-Z0-9_-]{1,40}$/.test(article)) {
  mode.value = "analyze";
  byId("research-hours").value = "720";
  submit.textContent = taskLabels.analyze;
  search({ article_id: article, mode: "analyze" });
} else {
  try {
    question.value = (sessionStorage.getItem("informa-research-query") || "").slice(0, 150);
    sessionStorage.removeItem("informa-research-query");
  } catch { /* Start with an empty query when browser storage is unavailable. */ }
}
