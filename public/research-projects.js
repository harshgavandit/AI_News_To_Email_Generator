import { answerBlock, node, requestJSON, sourceLink, sourceList } from "./evidence-ui.js";
import { historyControl } from "./source-history.js";
import { monitorInbox } from "./monitor-inbox.js";
import { readingGroups } from "./privacy-data.js";

const byId = (id) => document.getElementById(id);
const root = "/api/intelligence/inbox/projects";
const status = byId("project-status");
const detail = byId("project-detail");
const params = new URLSearchParams(location.search);
const fragment = new URLSearchParams(location.hash.slice(1));
const tokenFormat = /^[A-Za-z0-9_-]{43}$/;
const articleFormat = /^[a-zA-Z0-9_-]{1,40}$/;
const incomingArticle = articleFormat.test(params.get("source") || "") ? params.get("source") : "";
let incoming;
let active;
let loading;

function action(text, run, primary = false) {
  const button = node("button", text, `button ${primary ? "primary" : "secondary"}`);
  button.type = "button";
  button.addEventListener("click", () => perform(button, run));
  return button;
}

async function perform(button, run) {
  button.disabled = true;
  status.textContent = "Working…";
  try { status.textContent = await run() || ""; }
  catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
}

function dated(timestamp) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(timestamp * 1000));
}

function portableLink(kind, token) {
  const url = new URL("/projects.html", location.origin);
  url.hash = new URLSearchParams({ [kind]: token });
  return url.href;
}

function exposeLink(section, label, url) {
  const address = node("input");
  address.setAttribute("aria-label", label);
  address.value = url;
  address.readOnly = true;
  address.addEventListener("focus", () => address.select());
  const copy = action("Copy link", async () => {
    try { await navigator.clipboard.writeText(url); return "Link copied."; }
    catch { address.focus(); address.select(); return "Select and copy the link from the field."; }
  });
  const row = node("div", null, "intelligence-actions");
  row.append(address, copy);
  section.replaceChildren(node("p", label, "research-meta"), row);
  address.focus();
}

function renderSources(project, section) {
  if (!project.sources.length) section.append(node("p", "Save sources from the Research Desk or discover related evidence here."));
  for (const source of project.sources) {
    const row = node("article", null, "intelligence-section");
    if (source.evidence) row.append(sourceList([source.evidence], (item) => item.append(historyControl(source.id))));
    else row.append(node("p", "This saved source is no longer available in the retained archive.", "research-note"));
    const field = node("textarea");
    field.value = source.note;
    field.maxLength = 1500;
    field.rows = 2;
    const label = node("label", "Private project note");
    label.append(field);
    const form = node("form");
    const actions = node("div", null, "intelligence-actions");
    const submit = node("button", "Save note", "button secondary");
    submit.type = "submit";
    submit.disabled = !source.evidence;
    actions.append(submit, action("Remove source", async () => {
      if (!confirm("Remove this source and its note from the project?")) return;
      await requestJSON(`${root}/${project.id}/sources/${encodeURIComponent(source.id)}`, { method: "DELETE" });
      await openProject(project.id);
      return "Source removed.";
    }));
    form.append(label, actions);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      perform(submit, async () => {
        await requestJSON(`${root}/${project.id}/sources`, { method: "PUT", body: { article_id: source.id, note: field.value } });
        return "Project note saved.";
      });
    });
    row.append(form);
    section.append(row);
  }
}

async function saveSource(project, id) {
  await requestJSON(`${root}/${project.id}/sources`, { method: "PUT", body: { article_id: id } });
  await openProject(project.id);
  return "Source added to the project.";
}

function renderDiscover(project, section) {
  const matches = node("div");
  section.append(action("Find new evidence", async () => {
    matches.replaceChildren();
    const data = await requestJSON(`${root}/${project.id}/discover`);
    if (!data.evidence.length) return "No unsaved archive records match these keywords in the past 30 days.";
    matches.append(sourceList(data.evidence, (item, row) => item.append(action("Add to project", () => saveSource(project, row.id)))));
    return `${data.evidence.length} unsaved records match the project’s keywords.`;
  }), matches);
  if (!incomingArticle || project.sources.some((row) => row.id === incomingArticle)) return;
  const importRow = node("div", null, "intelligence-actions");
  if (incoming) importRow.append(sourceLink(incoming));
  importRow.append(action("Save selected source here", () => saveSource(project, incomingArticle), true));
  section.append(importRow);
}

function renderBriefs(project, section) {
  section.append(node("h2", "Team briefs"), node("p", "A published link includes the question and cited sources. Anyone with the link can read it while it is active.", "research-note"));
  const history = node("ol", null, "research-evidence");
  const shareOutput = node("div");
  for (const brief of project.briefs) {
    const row = node("li");
    const link = node("a", `Brief from ${dated(brief.created)}`);
    link.href = portableLink("brief", brief.id);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const actions = node("div", null, "intelligence-actions");
    actions.append(action("Share link", () => exposeLink(shareOutput, "Read-only brief link", link.href)), action("Revoke link", async () => {
      if (!confirm("Revoke access to this brief link?")) return;
      await requestJSON(`${root}/${project.id}/briefs/${brief.id}`, { method: "DELETE" });
      await openProject(project.id);
      return "Brief link revoked.";
    }));
    row.append(link, actions);
    history.append(row);
  }
  if (history.children.length) section.append(history);
  const form = node("form");
  const audience = node("select");
  for (const name of ["Engineering", "Security", "Leadership"]) audience.add(new Option(name, name.toLowerCase()));
  const window = node("select");
  window.add(new Option("Past 7 days", "week"));
  window.add(new Option("All saved sources", "all"));
  const submit = node("button", "Publish brief link", "button primary");
  submit.type = "submit";
  submit.disabled = !project.sources.some((row) => row.evidence);
  const audienceLabel = node("label", "Audience");
  audienceLabel.append(audience);
  const windowLabel = node("label", "Source period");
  windowLabel.append(window);
  form.append(audienceLabel, windowLabel, submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    perform(submit, async () => {
      const data = await requestJSON(`${root}/${project.id}/brief`, { method: "POST", body: { audience: audience.value, window: window.value } });
      await openProject(project.id);
      exposeLink(byId("project-brief-link"), "Read-only brief link", portableLink("brief", data.id));
      return data.answer.status === "answered" ? "Cited brief published." : "Source brief published. AI analysis was unavailable or had insufficient evidence.";
    });
  });
  shareOutput.id = "project-brief-link";
  section.append(form, shareOutput);
}

function renderProject(project) {
  detail.replaceChildren(node("h2", project.question), node("p", `Archive keywords: ${project.keywords}`, "research-meta"));
  const discovery = node("section", null, "intelligence-section");
  discovery.append(node("h3", "Related evidence"));
  renderDiscover(project, discovery);
  const evidence = node("section", null, "intelligence-section");
  evidence.append(node("h3", "Saved sources"));
  renderSources(project, evidence);
  const team = node("section", null, "intelligence-section");
  renderBriefs(project, team);
  detail.append(discovery, evidence, team);
  if (!project.owner) return;
  const permissions = node("details");
  permissions.append(node("summary", "Manage collaborators and project"));
  const actions = node("div", null, "intelligence-actions");
  const inviteLink = node("div");
  actions.append(action("Create collaborator invitation", async () => {
    const data = await requestJSON(`${root}/${project.id}/invite`, { method: "POST" });
    exposeLink(inviteLink, "Single-use invitation, expires in 24 hours", portableLink("join", data.token));
    return "Invitation ready to share.";
  }), action("Revoke all collaborator access", async () => {
    if (!confirm("Remove all collaborators and revoke unused invitations?")) return;
    await requestJSON(`${root}/${project.id}/collaborators`, { method: "DELETE" });
    inviteLink.replaceChildren();
    return "Collaborator access revoked.";
  }), action("Delete project", async () => {
    if (!confirm("Delete this project, its notes, and all published brief links?")) return;
    await requestJSON(`${root}/${project.id}`, { method: "DELETE" });
    active = undefined;
    await loadProjects();
    return "Project deleted.";
  }));
  permissions.append(actions, inviteLink);
  detail.append(permissions);
}

function markActive() {
  for (const button of byId("project-list").querySelectorAll("button")) button.setAttribute("aria-pressed", String(button.dataset.projectId === active));
}

async function openProject(id) {
  loading?.abort();
  const controller = new AbortController();
  loading = controller;
  active = id;
  markActive();
  detail.setAttribute("aria-busy", "true");
  try {
    const project = await requestJSON(`${root}/${id}`, { signal: controller.signal });
    if (loading === controller) renderProject(project);
  } catch (error) { if (!controller.signal.aborted) throw error; }
  finally { if (loading === controller) detail.setAttribute("aria-busy", "false"); }
}

async function loadProjects() {
  const data = await requestJSON(root);
  const list = byId("project-list");
  list.replaceChildren();
  for (const project of data.projects) {
    const button = action(project.question, () => openProject(project.id));
    button.dataset.projectId = project.id;
    list.append(button);
  }
  const selected = data.projects.find((row) => row.id === active) || data.projects[0];
  if (selected) await openProject(selected.id);
  else detail.replaceChildren(node("h2", "Create your first project"), node("p", "Use the form to save a question and archive keywords."));
}

async function initWorkspace() {
  const current = await monitorInbox();
  if (!current.available) { status.textContent = "Research projects are temporarily unavailable."; return; }
  byId("project-enable").hidden = current.active;
  byId("project-workspace").hidden = !current.active;
  byId("project-invitation").hidden = !current.active || !tokenFormat.test(fragment.get("join") || "");
  if (current.active) await loadProjects();
  status.textContent = "";
}

async function showSharedBrief(token) {
  const data = await requestJSON("/api/intelligence/briefs/open", { method: "POST", body: { token } });
  byId("project-title").textContent = data.question;
  byId("project-intro").textContent = `${data.audience} brief · ${data.period} · ${dated(data.created)}`;
  const brief = byId("shared-brief");
  brief.hidden = false;
  if (data.evidence_changed) brief.append(node("p", "Some sources were revised or removed after this brief was published. Affected claims have been withdrawn from this view.", "research-note"));
  brief.append(answerBlock(data.answer, data.evidence), node("h2", "Sources"), sourceList(data.evidence));
  status.textContent = "";
}

const createForm = byId("project-create");
createForm.addEventListener("submit", (event) => {
  event.preventDefault();
  perform(event.submitter || createForm.querySelector("button"), async () => {
    const project = await requestJSON(root, { method: "POST", body: Object.fromEntries(new FormData(createForm)) });
    active = project.id;
    createForm.reset();
    await loadProjects();
    return "Research project created.";
  });
});
byId("project-enable-button").addEventListener("click", ({ currentTarget }) => perform(currentTarget, async () => {
  let watches = [];
  try {
    const local = JSON.parse(localStorage.getItem(readingGroups.alerts.key));
    if (Array.isArray(local)) watches = local.slice(0, 6).map(({ id, query, topic, rule }) => ({ id, query, topic: topic || "all", ...(rule && { rule }) }));
  } catch { /* Setup remains available without local storage. */ }
  await monitorInbox("/enable", { method: "POST", body: { watches } });
  await initWorkspace();
}));
byId("project-join").addEventListener("click", ({ currentTarget }) => perform(currentTarget, async () => {
  const data = await requestJSON(`${root}/join`, { method: "POST", body: { token: fragment.get("join") } });
  history.replaceState(null, "", `${location.pathname}${location.search}`);
  fragment.delete("join");
  active = data.id;
  await initWorkspace();
  return "You joined the research project.";
}));

async function initialize() {
  const token = fragment.get("brief") || "";
  if (tokenFormat.test(token)) { await showSharedBrief(token); return; }
  const technologies = requestJSON("/api/intelligence/technologies").then(({ technologies: rows }) => {
    for (const row of rows) createForm.elements.namedItem("technology").add(new Option(row.name, row.id));
  }).catch(() => {});
  if (incomingArticle) {
    try { incoming = (await requestJSON(`/api/intelligence/source-history/${incomingArticle}`)).source; }
    catch { /* The server checks availability again when saving. */ }
  }
  await Promise.all([technologies, initWorkspace()]);
}
initialize().catch((error) => { status.textContent = error.message; });
