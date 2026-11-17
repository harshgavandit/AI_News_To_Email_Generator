import { node, requestJSON, sourceList, answerBlock } from "./evidence-ui.js";
import { historyControl } from "./source-history.js";
import { followedTechnologies, saveTechnologyFollow } from "./technology-follow.js";

const byId = (id) => document.getElementById(id);
const kinds = { release: "Releases", advisory: "Security advisories", status: "Service incidents",
  research: "Research", reporting: "Independent reporting", publisher: "Publisher updates", community: "Community and practitioner coverage" };
const matches = { registered_source: "Registered source for this technology", repository: "Linked project repository", mention: "Mentioned in publisher text" };
const range = byId("technology-window");
const status = byId("technology-status");
const records = byId("technology-records");
const follow = byId("technology-follow");
let active;
let loadRequest;
let askRequest;

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
  status.textContent = "Loading archive records…";
  records.replaceChildren();
  records.setAttribute("aria-busy", "true");
  try {
    const data = await requestJSON(`/api/intelligence/technologies/${active.id}?hours=${range.value}`, { signal: controller.signal });
    for (const [kind, label] of Object.entries(kinds)) {
      const selected = data.records.filter((row) => row.record_kind === kind);
      if (!selected.length) continue;
      const section = node("section", null, "intelligence-section");
      section.append(node("h3", label), sourceList(selected, (item, row) => {
        item.append(node("p", matches[row.entity_match], "research-meta"), historyControl(row.id));
      }));
      records.append(section);
    }
    status.textContent = data.records.length ? `${data.records.length} source records from the retained archive` : "No records in this window. Try a wider time range.";
  } catch (error) { if (!controller.signal.aborted) status.textContent = error.message; }
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
range.addEventListener("change", loadRecords);
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
    result.append(answerBlock(data.answer, data.evidence));
    if (data.evidence.length) {
      const sources = node("details");
      sources.append(node("summary", `${data.evidence.length} source records reviewed`), sourceList(data.evidence));
      result.append(sources);
    }
    feedback.textContent = "";
  } catch (error) { if (!controller.signal.aborted) feedback.textContent = error.message; }
  finally { if (askRequest === controller) button.disabled = false; }
});

requestJSON("/api/intelligence/technologies").then(({ technologies }) => {
  const selection = new URLSearchParams(location.search).get("tech");
  active = technologies.find((row) => row.id === selection) || technologies[0];
  if (!active) { status.textContent = "No technology pages are available."; return; }
  const links = byId("technology-directory");
  for (const row of technologies) {
    const link = node("a", row.name, "button secondary");
    link.href = `/technology.html?tech=${encodeURIComponent(row.id)}`;
    if (active === row) link.setAttribute("aria-current", "page");
    links.append(link);
  }
  byId("technology-title").textContent = active.name;
  byId("technology-home").href = active.homepage;
  byId("technology-watch-link").href = `/research.html?watch-tech=${encodeURIComponent(active.id)}#watch-title`;
  byId("technology-content").hidden = false;
  setFollowLabel();
  loadRecords();
}).catch((error) => { status.textContent = error.message; });
