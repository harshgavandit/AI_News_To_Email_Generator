import { node, requestJSON, sourceList, answerBlock, readableError } from "./evidence-ui.js";
import { historyControl } from "./source-history.js";
import { followedTechnologies, saveTechnologyFollow } from "./technology-follow.js";

const byId = (id) => document.getElementById(id);
const kinds = { release: "Releases", advisory: "Security advisories", status: "Service incidents",
  research: "Research", reporting: "Independent reporting", publisher: "Publisher updates", community: "Community and practitioner coverage" };
const matches = { registered_source: "Registered source for this technology", repository: "Linked project repository", mention: "Mentioned in publisher text" };
const range = byId("technology-window");
const status = byId("technology-status");
const records = byId("technology-records");
const filters = byId("technology-record-filters");
const recordStatus = byId("technology-record-status");
const retry = byId("technology-record-retry");
const follow = byId("technology-follow");
const params = new URLSearchParams(location.search);
let active;
let loadRequest;
let askRequest;
let timeline = [];
let filter = Object.hasOwn(kinds, params.get("type")) ? params.get("type") : "all";

if ([...range.options].some((option) => option.value === params.get("hours"))) range.value = params.get("hours");

function updateLocation() {
  const url = new URL(location.href);
  url.searchParams.set("tech", active.id);
  if (range.value === "720") url.searchParams.delete("hours");
  else url.searchParams.set("hours", range.value);
  if (filter === "all") url.searchParams.delete("type");
  else url.searchParams.set("type", filter);
  history.replaceState(null, "", url);
  for (const link of byId("technology-directory").querySelectorAll("a")) {
    const destination = new URL(link.href);
    if (range.value === "720") destination.searchParams.delete("hours");
    else destination.searchParams.set("hours", range.value);
    link.href = destination.href;
  }
}

function renderTimeline() {
  const selected = filter === "all" ? timeline : timeline.filter((row) => row.record_kind === filter);
  records.replaceChildren();
  for (const [kind, label] of Object.entries(kinds)) {
    const group = selected.filter((row) => row.record_kind === kind);
    if (!group.length) continue;
    const section = node("section", null, "intelligence-section");
    section.append(node("h3", label), sourceList(group, (item, row) => {
      item.append(node("p", matches[row.entity_match], "technology-provenance"), historyControl(row.id));
    }));
    records.append(section);
  }
  for (const button of filters.querySelectorAll("button")) button.setAttribute("aria-pressed", String(button.dataset.kind === filter));
  const publishers = new Set(selected.map((row) => row.publisher).filter(Boolean));
  recordStatus.textContent = selected.length ? `${selected.length} ${selected.length === 1 ? "record" : "records"} · ${publishers.size} ${publishers.size === 1 ? "publisher" : "publishers"}` :
    filter === "all" ? "No archive records in this window. Try a wider time range." : `No ${kinds[filter].toLowerCase()} in this window. Show all records or widen the time range.`;
}

function renderFilters() {
  filters.replaceChildren();
  if (!timeline.length && filter === "all") return;
  for (const [kind, label] of Object.entries({ all: "All records", ...kinds })) {
    const count = kind === "all" ? timeline.length : timeline.filter((row) => row.record_kind === kind).length;
    if (kind !== "all" && kind !== filter && !count) continue;
    const button = node("button", `${label} (${count})`, "research-pill");
    button.type = "button";
    button.dataset.kind = kind;
    button.addEventListener("click", () => {
      filter = kind;
      updateLocation();
      renderTimeline();
    });
    filters.append(button);
  }
}

function setFollowLabel() {
  const enabled = followedTechnologies().includes(active.id);
  follow.setAttribute("aria-pressed", String(enabled));
  follow.textContent = enabled ? `Unfollow ${active.name}` : `Follow ${active.name}`;
}

async function loadRecords() {
  loadRequest?.abort();
  askRequest?.abort();
  byId("technology-answer").replaceChildren();
  byId("technology-answer-status").textContent = "";
  const controller = new AbortController();
  loadRequest = controller;
  recordStatus.textContent = "Loading archive records…";
  retry.hidden = true;
  filters.replaceChildren();
  records.replaceChildren();
  records.setAttribute("aria-busy", "true");
  try {
    const data = await requestJSON(`/api/intelligence/technologies/${active.id}?hours=${range.value}`, { signal: controller.signal });
    if (controller.signal.aborted) return;
    timeline = data.records;
    renderFilters();
    renderTimeline();
  } catch (error) {
    if (!controller.signal.aborted) {
      recordStatus.textContent = readableError(error);
      retry.hidden = false;
    }
  }
  finally { if (loadRequest === controller) records.setAttribute("aria-busy", "false"); }
}

follow.addEventListener("click", () => {
  const enabled = !followedTechnologies().includes(active.id);
  const feedback = byId("technology-follow-status");
  try {
    saveTechnologyFollow(active.id, enabled);
    setFollowLabel();
    feedback.textContent = enabled ? "Followed in this browser. Save your Tech Radar to include it in opted-in email." : "Removed from this browser’s Tech Radar. Save Tech Radar to update opted-in email.";
  } catch { feedback.textContent = "This browser could not save the follow preference."; }
});
range.addEventListener("change", () => {
  updateLocation();
  loadRecords();
});
retry.addEventListener("click", loadRecords);
byId("technology-ask").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const feedback = byId("technology-answer-status");
  const result = byId("technology-answer");
  askRequest?.abort();
  const controller = new AbortController();
  askRequest = controller;
  button.disabled = true;
  result.replaceChildren();
  feedback.textContent = "Reviewing the sources…";
  try {
    const data = await requestJSON(`/api/intelligence/technologies/${active.id}/ask`, { method: "POST", signal: controller.signal,
      body: { hours: Number(range.value), question: byId("technology-question").value.trim() } });
    if (controller.signal.aborted) return;
    result.append(answerBlock(data.answer, data.evidence));
    if (data.evidence.length) {
      const sources = node("details");
      sources.append(node("summary", `${data.evidence.length} source records reviewed`), sourceList(data.evidence));
      result.append(sources);
    }
    feedback.textContent = "";
  } catch (error) { if (!controller.signal.aborted) feedback.textContent = readableError(error); }
  finally { if (askRequest === controller) button.disabled = false; }
});

requestJSON("/api/intelligence/technologies").then(({ technologies }) => {
  const selection = params.get("tech");
  active = technologies.find((row) => row.id === selection) || technologies[0];
  if (!active) { status.textContent = "No technology pages are available."; return; }
  const links = byId("technology-directory");
  for (const row of technologies) {
    const link = node("a", row.name);
    link.href = `/technology.html?tech=${encodeURIComponent(row.id)}`;
    if (active === row) link.setAttribute("aria-current", "page");
    links.append(link);
  }
  byId("technology-title").textContent = active.name;
  document.title = `${active.name} · Informa AI`;
  byId("technology-home").href = active.homepage;
  byId("technology-watch-link").href = `/research.html?watch-tech=${encodeURIComponent(active.id)}#watch-title`;
  byId("technology-content").hidden = false;
  status.textContent = "";
  setFollowLabel();
  updateLocation();
  loadRecords();
}).catch((error) => { status.textContent = readableError(error); });
