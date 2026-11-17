import { readingGroups } from "/privacy-data.js";
import { monitorInbox } from "./monitor-inbox.js";
import { readFeedback } from "./reader-feedback.js";
import { followedTechnologies } from "./technology-follow.js";
import { historyControl } from "./source-history.js";
import { initRuleBuilder } from "./watch-rule-ui.js";

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
let inbox = null;
let inboxBusy = false;
let conversation = [];
let conversationIds = [];
const radarKey = readingGroups.radar.key;
let followedEvents = [];
let viewedRevisions = {};
let inboxFeedback;
let inboxTechnologies = [];

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

async function api(path, body, signal, method) {
  const response = await fetch(path, {
    cache: "no-store", signal,
    ...((body || method) && { method: method || (body ? "POST" : "GET") }),
    ...(body && { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
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

function markdownText(value) {
  return String(value || "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim()
    .replace(/[\\`*_{}\[\]()<>#!|]/g, "\\$&");
}

function downloadNotes(data, title, references) {
  const lines = ["# Informa AI research notes", "", markdownText(title), ""];
  if (data.answer?.claims?.length) {
    lines.push("## Findings", "");
    for (const claim of data.answer.claims) {
      const cited = claim.source_ids.map((id) => references.get(id)).filter(Boolean).join(", ");
      lines.push(`- ${claim.kind === "analysis" ? "Interpretation. " : ""}${markdownText(claim.text)} (Sources ${cited})`);
    }
    lines.push("");
  }
  if (data.answer?.limitations) lines.push("## Evidence limits", "", markdownText(data.answer.limitations), "");
  lines.push("## Source evidence", "");
  for (const row of data.evidence) {
    const href = link("", row.url).getAttribute("href");
    const label = markdownText(row.title);
    lines.push(`${references.get(row.id)}. ${href ? `[${label}](<${href}>)` : label} · ${markdownText(row.publisher)} · ${dateLabel(row.published_at)}`);
    if (row.excerpt) lines.push(`   > ${markdownText(row.excerpt)}`);
  }
  const file = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/markdown;charset=utf-8" }));
  const anchor = element("a");
  anchor.href = file;
  anchor.download = "informa-ai-research-notes.md";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(file), 1000);
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
        const label = { analysis: "Interpretation", shared: "Reported by multiple outlets", single_source: "Single-source detail",
          difference: "Difference in coverage", attributed: "Shared attribution" }[claim.kind];
        if (label) item.append(element("span", label, "research-label"));
        for (const id of claim.source_ids.filter((value) => references.has(value))) {
          const citation = cite(id);
          citation.className = "research-cite";
          citation.setAttribute("aria-label", `Source ${references.get(id)}`);
          text.append(" ", citation);
        }
        item.append(text);
        if (claim.quotes?.length) {
          const quotes = element("details", "", "research-meta");
          quotes.append(element("summary", "Read the original evidence"));
          for (const [index, quote] of claim.quotes.entries()) {
            const source = data.evidence[references.get(claim.source_ids[index]) - 1];
            const excerpt = element("blockquote", quote);
            excerpt.lang = source?.language || "";
            excerpt.dir = "auto";
            if (source) excerpt.append(element("footer", source.publisher));
            quotes.append(excerpt);
          }
          item.append(quotes);
        }
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
  const toolbar = element("header", "", "research-export");
  toolbar.append(evidence.firstElementChild);
  const exportButton = element("button", "Download notes", "button secondary");
  exportButton.type = "button";
  exportButton.addEventListener("click", () => {
    try { downloadNotes(data, titles.context || titles.evidence, references); }
    catch { status.textContent = "Research notes could not be downloaded in this browser."; }
  });
  toolbar.append(exportButton);
  evidence.append(toolbar);
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
    const meta = [row.publisher, row.region, row.language && languageName(row.language), dateLabel(row.published_at), row.match?.includes("semantic") && "Meaning match"];
    const excerpt = element("p", row.excerpt || "Headline and source link only.");
    excerpt.dir = "auto";
    excerpt.lang = row.language;
    const technical = ["release", "preprint", "journal"].includes(row.coverage);
    const explain = element("button", technical ? "Build technical brief" : "Explain this story", "text-button");
    explain.type = "button";
    explain.addEventListener("click", async () => {
      explain.disabled = true;
      const output = element("div", "", "explanation-result");
      item.append(output);
      output.setAttribute("role", "status");
      output.textContent = "Checking the publisher excerpt…";
      try {
        const answer = await api("/api/intelligence/explain", { article_id: row.id,
          language: byId("radar-language").value, depth: byId("radar-depth").value,
          ...(technical && { format: "technical_brief" }) });
        output.replaceChildren();
        for (const claim of answer.answer.claims || []) {
          const note = element("blockquote", claim.text);
          const label = answer.sections?.[claim.kind] || (claim.kind === "analysis" ? "Interpretation" : "");
          if (label) note.prepend(element("p", label, "research-label"));
          note.append(element("p", `Source quote: “${claim.quote}”`, "research-meta"));
          const source = answer.evidence.find((evidenceRow) => evidenceRow.id === claim.source_id);
          if (source) note.append(link(`Read ${source.publisher} ↗`, source.url));
          output.append(note);
        }
        output.append(element("p", answer.answer.limitations, "research-note"));
      } catch (error) { output.textContent = error.message; }
      finally { explain.disabled = false; }
    });
    item.append(heading, element("p", meta.filter(Boolean).join(" · "), "research-meta"), excerpt,
      link("Open in Reading Room", `/?article=${encodeURIComponent(row.id)}#reading-room`), explain,
      link("Save to a project", `/projects.html?source=${encodeURIComponent(row.id)}`), historyControl(row.id));
    list.append(item);
  }
  evidence.append(list);
  results.append(evidence);
  conversationIds = data.evidence.map((row) => row.id).slice(0, 8);
  byId("conversation-desk").hidden = !data.evidence.length;
}

function languageName(code) {
  try { return new Intl.DisplayNames(["en"], { type: "language" }).of(code); } catch { return code; }
}

const taskLabels = { search: "Find sources", analyze: "Answer with sources", compare: "Compare coverage", global_compare: "Compare across languages", brief: "Build a topic brief" };
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
    render(data, { answer: body.mode === "global_compare" ? "Cross-language coverage comparison" : body.mode === "compare" ? "AI coverage comparison" :
      body.mode === "brief" ? "AI topic briefing" : "AI analysis", evidence: "Source evidence",
      context: body.q || data.evidence[0]?.title });
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
  conversation = [];
  byId("conversation-transcript").replaceChildren();
  search({ q, mode: mode.value, ...(mode.value === "global_compare" && { language: byId("radar-language").value }),
    scope: { hours: Number(byId("research-hours").value), topic: topic.value } });
});

byId("conversation-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = byId("conversation-question"), button = event.currentTarget.querySelector("button[type=submit]");
  const prompt = input.value.trim();
  if (!prompt || button.disabled) return;
  button.disabled = true;
  status.textContent = "Finding the next answer in the linked source evidence…";
  try {
    const data = await api("/api/intelligence/converse", {
      question: prompt, history: conversation.slice(-8), context_ids: conversationIds.slice(0, 8),
      hours: Number(byId("research-hours").value), topic: topic.value || "all", language: byId("radar-language").value,
    });
    conversation.push({ role: "user", content: prompt });
    const exchange = element("article", "", "conversation-turn");
    exchange.append(element("h3", prompt));
    if (data.answer?.claims?.length) {
      const claims = element("ul");
      for (const claim of data.answer.claims) {
        const item = element("li", claim.text);
        for (const ident of claim.source_ids || []) {
          const source = data.evidence.find((entry) => entry.id === ident);
          if (source) item.append(" ", link(`[${source.publisher}] ↗`, source.url));
        }
        claims.append(item);
      }
      exchange.append(claims);
    }
    exchange.append(element("p", data.answer?.limitations || "No source excerpts support a follow-up answer.", "research-note"));
    byId("conversation-transcript").append(exchange);
    const answerText = (data.answer?.claims || []).map((claim) => claim.text).join(" ") || data.answer?.limitations || "No supported answer.";
    conversation.push({ role: "assistant", content: answerText.slice(0, 600) });
    conversation = conversation.slice(-8);
    conversationIds = [...new Set([...conversationIds, ...(data.evidence || []).map((entry) => entry.id)])].slice(0, 8);
    input.value = "";
    status.textContent = `${data.evidence?.length || 0} linked sources used for this follow-up.`;
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
});

function radarProfile() {
  return { name: "Reader", role: byId("radar-role").value,
    interests: byId("radar-interests").value.split(/[,;\n]/).map((term) => term.trim()).filter(Boolean).slice(0, 12),
    stack: byId("radar-stack").value.split(/[,;\n]/).map((term) => term.trim()).filter(Boolean).slice(0, 12),
    topics: topic.value && topic.value !== "all" ? [topic.value] : [], followed_events: followedEvents,
    feedback: readFeedback(inboxFeedback), followed_technologies: followedTechnologies(inboxTechnologies),
    language: byId("radar-language").value, depth: byId("radar-depth").value,
    length: Number(byId("radar-length").value) };
}

function loadRadarProfile(profile) {
  if (!profile || typeof profile !== "object") return;
  if ([...byId("radar-role").options].some((option) => option.value === profile.role)) byId("radar-role").value = profile.role;
  if ([...byId("radar-language").options].some((option) => option.value === profile.language)) byId("radar-language").value = profile.language;
  if ([...byId("radar-depth").options].some((option) => option.value === profile.depth)) byId("radar-depth").value = profile.depth;
  if ([...byId("radar-length").options].some((option) => Number(option.value) === profile.length)) byId("radar-length").value = String(profile.length);
  byId("radar-interests").value = (profile.interests || []).join(", ");
  byId("radar-stack").value = (profile.stack || []).join(", ");
  followedEvents = profile.followed_events || [];
  viewedRevisions = profile.viewedRevisions || viewedRevisions;
}

function rememberRadar() {
  try { localStorage.setItem(radarKey, JSON.stringify({ ...radarProfile(), viewedRevisions })); } catch { /* Session still works. */ }
}

function followButton(id) {
  const button = element("button", "", "text-button");
  button.type = "button";
  button.dataset.followEvent = id;
  const refresh = (control) => {
    const active = followedEvents.includes(id);
    control.textContent = active ? "Unfollow story" : "Follow story";
    control.setAttribute("aria-pressed", String(active));
  };
  refresh(button);
  button.addEventListener("click", () => {
    if (followedEvents.includes(id)) followedEvents = followedEvents.filter((value) => value !== id);
    else if (followedEvents.length < 40) followedEvents = [...followedEvents, id];
    else { byId("development-status").textContent = "You can follow up to 40 stories."; return; }
    rememberRadar();
    for (const control of document.querySelectorAll("[data-follow-event]")) if (control.dataset.followEvent === id) refresh(control);
  });
  return button;
}

function timelineList(items) {
  const entries = element("ol", "", "timeline-entries");
  for (const item of items) {
    const publisher = item.source?.publisher || item.publisher;
    const row = element("li");
    row.append(element("span", `${dateLabel(item.published_at)} · ${publisher} · `), link(item.title, item.source?.url || item.url));
    if (item.reason === "source_revision") row.append(element("span", " · Publisher revised this item", "research-meta"));
    if (item.excerpt) row.append(element("p", item.excerpt));
    entries.append(row);
  }
  return entries;
}

async function showTimeline(eventId, target) {
  const since = viewedRevisions[eventId];
  const query = /^\d{1,10}$/.test(since) ? `?since=${since}` : "";
  const history = await api(`/api/intelligence/events/${encodeURIComponent(eventId)}${query}`);
  if (history.changes?.length) target.append(element("h4", "New since your last visit"), timelineList(history.changes));
  else if (query && history.revision === since) target.append(element("p", "You’re up to date.", "research-meta"));
  target.append(timelineList(history.entries || []), element("p", history.notice, "research-meta"));
  if (history.revision) {
    delete viewedRevisions[eventId];
    viewedRevisions = Object.fromEntries([...Object.entries(viewedRevisions), [eventId, history.revision]].slice(-200));
    rememberRadar();
  }
}

async function catchMeUp(event) {
  event.preventDefault();
  const button = byId("radar-form").querySelector('[type="submit"]');
  const feedback = byId("radar-status");
  button.disabled = true;
  feedback.textContent = "Selecting new and updated stories…";
  try {
    await radarPreferencesReady;
    const profile = radarProfile();
    rememberRadar();
    const data = await api("/api/intelligence/catchup", { profile, seen: radarSeen,
      hours: Number(byId("radar-hours").value) });
    feedback.textContent = data.message || `${data.events?.length || 0} developments ready. AI explanations are linked to publisher evidence.`;
    const list = byId("radar-results");
    list.replaceChildren();
    for (const event of data.events || []) {
      const row = element("article", "", "radar-event");
      const heading = element("h3");
      const story = event.articles?.[0];
      if (story) heading.append(link(event.title, story.url));
      else heading.textContent = event.title;
      row.append(heading, element("p", `${event.change === "updated" ? "Updated" : "New development"} · ${event.source_count} publishers`, "research-meta"));
      if (event.reasons?.length) row.append(element("p", event.reasons.join(" · ")));
      row.append(followButton(event.id));
      if (event.change_sources?.length) row.append(element("h4", "New since your last brief"), timelineList(event.change_sources));
      const timeline = element("details");
      const summary = element("summary", "View publication timeline");
      timeline.append(summary);
      summary.addEventListener("click", async () => {
        if (timeline.dataset.loaded) return;
        timeline.dataset.loaded = "true";
        try {
          await showTimeline(event.id, timeline);
        } catch (error) { timeline.append(element("p", error.message, "research-note")); }
      });
      row.append(timeline);
      if (event.explanation?.claims?.length) {
        row.append(element("p", event.explanation.claims.map((claim) => claim.text).join(" ")));
        row.append(element("p", `Evidence quotes stay linked to the publisher. ${event.explanation.limitations || ""}`, "research-meta"));
      }
      list.append(row);
    }
    if (!data.events?.length) list.append(element("p", data.message || "No matching developments in this time range."));
    if (data.preview) {
      const handoff = element("a", "Email this catch-up ↗", "button primary");
      handoff.href = "/?ai-catchup=1#reading-room";
      handoff.addEventListener("click", () => {
        try { sessionStorage.setItem("informa-ai-catchup-preview", JSON.stringify(data.preview)); }
        catch { feedback.textContent = "This browser could not prepare the email preview. You can still read and share the source links above."; }
      });
      list.append(handoff);
    }
  } catch (error) { feedback.textContent = error.message; }
  finally { button.disabled = false; }
}

byId("radar-form").addEventListener("submit", catchMeUp);
byId("package-check-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('[type="submit"]');
  const feedback = byId("package-check-status");
  const output = byId("package-check-results");
  button.disabled = true;
  output.replaceChildren();
  feedback.textContent = "Checking published advisories…";
  try {
    const data = await api("/api/intelligence/package-check", Object.fromEntries(new FormData(form)));
    feedback.textContent = data.evidence.length ? `${data.evidence.length} matching advisories${data.partial ? " in the results checked" : ""}.` :
      `No matching advisories in the OSV results checked.${data.partial ? " Additional results may exist." : ""}`;
    const catalog = new Map(data.evidence.map((item) => [item.id, item]));
    for (const claim of data.answer?.claims || []) {
      const source = catalog.get(claim.source_id);
      if (source) output.append(element("p", claim.text), link(source.id, source.url));
    }
    if (data.evidence.length) output.append(timelineList(data.evidence));
  } catch (error) { feedback.textContent = error.message; }
  finally { button.disabled = false; }
});
byId("radar-save").addEventListener("click", async () => {
  const button = byId("radar-save");
  button.disabled = true;
  try {
    rememberRadar();
    const data = await api("/api/mail/radar", radarProfile(), undefined, "PUT");
    byId("radar-status").textContent = data.notice;
  } catch {
    byId("radar-status").textContent = "Verify your email from the home page first. Radar preferences stay in this browser until you save them to a verified inbox.";
  } finally { button.disabled = false; }
});

let radarSeen = {};
let radarHasLocalProfile = false;
let radarHasLocalFollows = false;
try {
  const saved = JSON.parse(localStorage.getItem(radarKey));
  radarHasLocalProfile = Boolean(saved?.role);
  radarHasLocalFollows = Array.isArray(saved?.followed_events);
  loadRadarProfile(saved);
} catch { /* Use the page defaults. */ }
const radarPreferencesReady = api("/api/mail/radar").then(({ profile, seen }) => {
  const localFollows = followedEvents;
  inboxFeedback = profile?.feedback;
  inboxTechnologies = profile?.followed_technologies || [];
  if (!radarHasLocalProfile) loadRadarProfile(profile);
  else if (!radarHasLocalFollows) followedEvents = profile?.followed_events || localFollows;
  radarSeen = seen || {};
}).catch(() => { /* Public visitors can build a catch-up without a mailbox account. */ });

let followedOnly = false;
let developmentsRequest = 0;
async function loadDevelopments() {
  const current = ++developmentsRequest;
  const list = byId("development-list");
  const feedback = byId("development-status");
  list.replaceChildren();
  feedback.textContent = followedOnly && !followedEvents.length ? "You haven’t followed a story yet." : "Loading developments…";
  if (followedOnly && !followedEvents.length) return;
  try {
  const path = followedOnly ? `/api/intelligence/events?limit=40&followed=${encodeURIComponent(followedEvents.join(","))}` : "/api/intelligence/events?hours=168&limit=8";
  const { events = [] } = await api(path);
  if (current !== developmentsRequest) return;
  feedback.textContent = "";
  for (const event of events) {
    const item = element("li", "", "development-item");
    item.append(element("strong", event.title), element("span", `${event.source_count} publishers · updated ${dateLabel(event.updated_at)}`, "research-meta"));
    const open = element("button", "Open timeline", "text-button");
    open.type = "button";
    open.addEventListener("click", async () => {
      try {
        open.disabled = true;
        await showTimeline(event.id, item);
        open.remove();
      } catch (error) { feedback.textContent = error.message; open.disabled = false; }
    });
    item.append(open, followButton(event.id));
    list.append(item);
  }
  if (!events.length) feedback.textContent = followedOnly ? "No followed stories are still in the archive." : "Developments are being indexed as new coverage arrives.";
  } catch { if (current === developmentsRequest) feedback.textContent = "Development timelines are temporarily unavailable."; }
}
byId("show-followed-developments").addEventListener("click", ({ currentTarget }) => {
  followedOnly = !followedOnly;
  currentTarget.setAttribute("aria-pressed", String(followedOnly));
  currentTarget.textContent = followedOnly ? "Show recent developments" : "Show followed stories";
  loadDevelopments();
});
radarPreferencesReady.then(loadDevelopments);

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
    remove.addEventListener("click", async () => {
      if (await replaceWatches(watches.filter((item) => item.id !== watch.id))) byId("watch-query").focus();
    });
    const header = element("header");
    header.append(title, remove);
    article.append(header);
    const matching = Array.isArray(watch.matches) ? watch.matches : [];
    article.append(element("p", inbox?.active
      ? (watch.checked ? `Checked ${dateLabel(watch.checked * 1000)}` : "Waiting for the first background check.")
      : watch.seen === null ? "Waiting for the first check." :
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
  if (inbox?.active) {
    if (!document.hidden) await refreshInbox();
    return;
  }
  if (checking || document.hidden || !watches.length) return;
  checking = true;
  const generation = watchGeneration;
  try {
    const data = await api("/api/intelligence/watch", {
      watches: settings(watches),
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
  const watchTopic = byId("watch-topic").value;
  if (watches.some((watch) => watch.query.toLowerCase() === query.toLowerCase() && (watch.topic || "all") === watchTopic)) {
    watchStatus.textContent = "You already watch these keywords in this topic.";
    return;
  }
  if (watches.length >= 6) { watchStatus.textContent = "Remove an alert before adding another."; return; }
  replaceWatches([...watches, { id: crypto.randomUUID(), query, topic: watchTopic, seen: null, matches: [] }]).then((saved) => {
    if (saved && input.value.trim() === query) input.value = "";
    if (saved && !inbox?.active) checkWatches();
  });
});

function syncInbox(data) {
  inbox = data;
  byId("monitor-opt-in").hidden = !data.available || data.active;
  byId("monitor-results").hidden = !data.active;
  byId("watch-description").textContent = data.active
    ? "New alerts appear here after the archive updates and your watches are checked."
    : "Watch up to six keyword queries or technology rules. Browser-only alerts check while this desk is open.";
  watches = data.active ? data.watches : loadWatches();
  renderWatches();
  if (!data.active) return;
  byId("monitor-unread").textContent = data.unread ? `${data.unread} unread` : "";
  byId("monitor-read").hidden = !data.unread;
  const list = byId("monitor-alerts");
  list.replaceChildren();
  if (!data.alerts.length) list.append(element("li", "New developments from your watches will appear here.", "monitor-empty"));
  const terms = new Map(watches.map((watch) => [watch.id, watch.query]));
  for (const alert of data.alerts) {
    const [lead, ...supporting] = alert.sources;
    if (!lead) continue;
    const row = element("li", "", alert.unread ? "monitor-unread-alert" : "");
    const label = element("p", [alert.unread && "New", terms.get(alert.watch_id),
      dateLabel(alert.updated * 1000)].filter(Boolean).join(" · "), "research-meta");
    const title = element("h4");
    title.append(link(lead.title, `/?article=${encodeURIComponent(lead.id)}#reading-room`));
    row.append(label, title, link(lead.publisher, lead.url));
    if (supporting.length) {
      const details = element("details");
      details.append(element("summary", `${supporting.length} more source${supporting.length === 1 ? "" : "s"}`));
      const sources = element("ul");
      for (const source of supporting) {
        const item = element("li");
        item.append(link(source.title, source.url), element("span", ` · ${source.publisher}`, "research-meta"));
        sources.append(item);
      }
      details.append(sources);
      row.append(details);
    }
    list.append(row);
  }
}

async function refreshInbox() {
  if (inboxBusy) return;
  inboxBusy = true;
  try {
    const data = await monitorInbox();
    if (!data) return;
    const newlyUnread = inbox?.active && data.active ? Math.max(0, data.unread - inbox.unread) : 0;
    // Preserve focus, expanded source lists, and announcement state on unchanged polls.
    if (JSON.stringify(data) !== JSON.stringify(inbox)) syncInbox(data);
    if (newlyUnread) watchStatus.textContent = `${newlyUnread} new intelligence alert${newlyUnread === 1 ? "" : "s"}.`;
  } catch (error) {
    if (inbox?.active) watchStatus.textContent = error.message;
  } finally { inboxBusy = false; }
}

const settings = (rows) => rows.map(({ id, query, topic: watchTopic, rule }) => ({ id, query, topic: watchTopic || "all", ...(rule && { rule }) }));

async function writeInbox(path, options, feedback) {
  if (inboxBusy) {
    watchStatus.textContent = "Finishing an alert check. Try again in a moment.";
    return false;
  }
  inboxBusy = true;
  watchGeneration++;
  try {
    syncInbox(await monitorInbox(path, options));
    watchStatus.textContent = feedback;
    return true;
  } catch (error) {
    if (error.status === 409) {
      try { syncInbox(await monitorInbox()); } catch { /* Leave the prior view available until another check. */ }
    }
    watchStatus.textContent = error.message;
    return false;
  } finally { inboxBusy = false; }
}

async function replaceWatches(next) {
  if (inbox?.active) return writeInbox("/watches", { method: "PUT",
    body: { watches: settings(next), revision: inbox.revision } }, "Background watches saved.");
  watchGeneration++;
  watches = next;
  saveWatches();
  renderWatches();
  return true;
}

byId("monitor-enable").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    if (await writeInbox("/enable", { method: "POST", body: { watches: settings(watches) } }, "Background monitoring is on.")) {
      byId("watch-query").focus();
    }
  } finally { button.disabled = false; }
});
byId("monitor-read").addEventListener("click", () =>
  writeInbox("/read", { method: "POST" }, "Alert inbox marked read."));
window.addEventListener("storage", ({ key }) => {
  if (key === alertKey || key === "informa-reader-reset" || key === null) {
    watchGeneration++;
    if (inbox?.active) refreshInbox();
    else { watches = loadWatches(); renderWatches(); }
  }
});
document.addEventListener("visibilitychange", checkWatches);
setInterval(checkWatches, 60000);
renderWatches();
refreshInbox().then(checkWatches);
initRuleBuilder(async (watch) => {
  if (watches.length >= 6) throw new Error("Remove an alert before adding another.");
  if (watches.some((existing) => existing.query === watch.query && existing.rule)) throw new Error("This technology rule is already saved.");
  const saved = await replaceWatches([...watches, { ...watch, seen: null, matches: [] }]);
  if (saved && !inbox?.active) checkWatches();
  return saved;
});

api("/api/intelligence/options").then((options) => {
  for (const [id, label] of Object.entries(options.topics || {})) {
    topic.add(new Option(label, id));
    byId("watch-topic").add(new Option(label, id));
  }
}).catch(() => { /* All topics can still be searched. */ });

const dailyStatus = byId("research-daily-status");
api("/api/intelligence/daily").then(({ brief, source_edition: sourceEdition }) => {
  daily = brief || sourceEdition;
  dailyStatus.textContent = brief ? `Generated ${dateLabel(brief.generated_at * 1000)} from archived sources.` :
    sourceEdition ? "Publisher evidence selected from the past 24 hours." : "The latest archive check returned no stories for this edition.";
  byId("show-daily").textContent = brief ? "Read the cited brief" : "Read the source brief";
  byId("show-daily").hidden = !daily;
  byId("daily-fallback").hidden = Boolean(daily);
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
  render(daily, { answer: "AI intelligence briefing", evidence: "Briefing sources", context: "Past 24 hours" });
  results.scrollIntoView({ block: "nearest" });
});

api("/api/trending").then(({ trending, momentum_window_hours }) => {
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
    const meta = element("span", trend.momentum === "rising"
      ? `Rising · ${trend.recent_source_count} sources` : `${trend.source_count} sources`, "research-meta");
    if (trend.momentum === "rising") meta.title =
      `${trend.recent_source_count} publishers in the last ${momentum_window_hours} hours, compared with ${trend.previous_source_count} in the prior window.`;
    row.append(button, meta);
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
