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
let active;
let loading;
const noteDrafts = new Map();

function action(text, run, primary = false, feedback = status) {
  const button = node("button", text, `button ${primary ? "primary" : "secondary"}`);
  button.type = "button";
  button.addEventListener("click", () => perform(button, run, feedback));
  return button;
}

async function perform(button, run, feedback = status) {
  button.disabled = true;
  feedback.textContent = "Working…";
  try { feedback.textContent = await run() || ""; }
  catch (error) { feedback.textContent = error.message; }
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
    const key = `${project.id}:${source.id}`;
    const note = node("details", null, "project-note");
    note.open = noteDrafts.has(key);
    const summary = node("summary", source.note ? "Edit project note" : "Add a project note");
    const field = node("textarea");
    field.value = noteDrafts.get(key) ?? source.note;
    field.readOnly = !source.evidence;
    field.maxLength = 1500;
    field.rows = 2;
    const label = node("label", "Note for project collaborators");
    label.append(field);
    const form = node("form");
    const actions = node("div", null, "intelligence-actions");
    const submit = node("button", "Save note", "button secondary");
    submit.type = "submit";
    submit.disabled = !source.evidence;
    const feedback = node("p", "", "research-status");
    feedback.setAttribute("role", "status");
    field.addEventListener("input", () => noteDrafts.set(key, field.value));
    actions.append(submit, action("Remove source", async () => {
      if (!confirm("Remove this source and its note from the project?")) return;
      await requestJSON(`${root}/${project.id}/sources/${encodeURIComponent(source.id)}`, { method: "DELETE" });
      noteDrafts.delete(key);
      if (active === project.id) await openProject(project.id);
      return "Source removed.";
    }));
    if (!source.evidence) summary.textContent = "View note or remove source";
    form.append(label, node("p", "Notes are visible to collaborators in this project. Published brief links include the saved source evidence.", "research-meta"), actions, feedback);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      perform(submit, async () => {
        const saved = field.value;
        await requestJSON(`${root}/${project.id}/sources`, { method: "PUT", body: { article_id: source.id, note: saved } });
        if (noteDrafts.get(key) === saved) noteDrafts.delete(key);
        summary.textContent = saved ? "Edit project note" : "Add a project note";
        return "Project note saved.";
      }, feedback);
    });
    note.append(summary, form);
    row.append(note);
    section.append(row);
  }
}

async function saveSource(project, id) {
  await requestJSON(`${root}/${project.id}/sources`, { method: "PUT", body: { article_id: id } });
  if (active === project.id) await openProject(project.id);
  return "Source added to the project.";
}

function renderDiscover(project, section) {
  const matches = node("div");
  const feedback = node("p", "", "research-status");
  feedback.setAttribute("role", "status");
  section.append(action("Find new evidence", async () => {
    matches.replaceChildren();
    const data = await requestJSON(`${root}/${project.id}/discover`);
    if (!data.evidence.length) return "No unsaved archive records match these keywords in the past 30 days.";
    matches.append(sourceList(data.evidence, (item, row) => item.append(action("Add to project", () => saveSource(project, row.id)))));
    return `${data.evidence.length} unsaved records match the project’s keywords.`;
  }, false, feedback), feedback, matches);
  if (!incomingArticle || project.sources.some((row) => row.id === incomingArticle)) return;
  const importRow = node("div", null, "intelligence-actions");
  importRow.append(action("Save selected source here", () => saveSource(project, incomingArticle), true));
  section.append(importRow);
}

function renderBriefs(project, section) {
  section.append(node("p", "Anyone with a published link can read the project question and cited sources. Links expire after 90 days and can be revoked sooner.", "research-note"));
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
      if (active === project.id) await openProject(project.id);
      return "Brief link revoked.";
    }));
    row.append(link);
    if (brief.expires) row.append(node("p", `Expires ${dated(brief.expires)}`, "research-meta"));
    row.append(actions);
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
  if (submit.disabled) form.append(node("p", "Save an available source before publishing a brief.", "research-meta"));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    perform(submit, async () => {
      const data = await requestJSON(`${root}/${project.id}/brief`, { method: "POST", body: { audience: audience.value, window: window.value } });
      if (active === project.id) {
        await openProject(project.id);
        if (active === project.id) exposeLink(byId("project-brief-link"), "Read-only brief link", portableLink("brief", data.id));
      }
      return data.answer.status === "answered" ? "Cited brief published." : "Source brief published. AI analysis was unavailable or had insufficient evidence.";
    });
  });
  shareOutput.id = "project-brief-link";
  section.append(form, shareOutput);
}

function projectSection(title, id) {
  const section = node("section", null, "intelligence-section");
  section.setAttribute("aria-labelledby", id);
  const heading = node("h3", title);
  heading.id = id;
  section.append(heading);
  return section;
}

function projectHeading(text) {
  const heading = node("h2", text);
  heading.id = "project-detail-title";
  heading.tabIndex = -1;
  return heading;
}

function renderProject(project) {
  const heading = projectHeading(project.question);
  const summary = node("p", `${project.owner ? "Owner" : "Collaborator"} · ${project.sources.length} saved sources`, "project-role");
  const navigation = node("nav", null, "research-section-nav project-sections");
  navigation.setAttribute("aria-label", "Project sections");
  for (const [id, label] of [["project-discover-title", "Discover evidence"], ["project-sources-title", "Saved sources"], ["project-brief-title", "Team briefs"]]) {
    const anchor = node("a", label);
    anchor.href = `#${id}`;
    navigation.append(anchor);
  }
  detail.replaceChildren(summary, heading, node("p", `Archive keywords: ${project.keywords}`, "research-meta"), navigation);
  const discovery = projectSection("Related evidence", "project-discover-title");
  renderDiscover(project, discovery);
  const evidence = projectSection("Saved sources", "project-sources-title");
  renderSources(project, evidence);
  const team = projectSection("Team briefs", "project-brief-title");
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
    for (const key of noteDrafts.keys()) if (key.startsWith(`${project.id}:`)) noteDrafts.delete(key);
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

async function openProject(id, { focus = false } = {}) {
  loading?.abort();
  const controller = new AbortController();
  loading = controller;
  active = id;
  markActive();
  detail.inert = true;
  detail.setAttribute("aria-busy", "true");
  try {
    const project = await requestJSON(`${root}/${id}`, { signal: controller.signal });
    if (loading !== controller) return;
    renderProject(project);
  } catch (error) {
    if (!controller.signal.aborted) {
      active = undefined;
      markActive();
      detail.replaceChildren(projectHeading("Could not open this project"), node("p", "Select the project again to retry."));
      throw error;
    }
  } finally {
    if (loading === controller) {
      detail.inert = false;
      detail.setAttribute("aria-busy", "false");
      if (focus) byId("project-detail-title").focus();
    }
  }
}

async function loadProjects() {
  const data = await requestJSON(root);
  const list = byId("project-list");
  list.replaceChildren();
  for (const project of data.projects) {
    const button = action(project.question, () => openProject(project.id, { focus: true }));
    button.className = "project-directory-item";
    button.dataset.projectId = project.id;
    list.append(button);
  }
  const selected = data.projects.find((row) => row.id === active) || data.projects[0];
  if (selected) await openProject(selected.id);
  else {
    list.append(node("p", "No projects yet.", "research-meta"));
    detail.replaceChildren(projectHeading("Create your first project"), node("p", "Start with a question and keywords. Then gather sources, add notes, or create a cited brief."));
  }
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
  byId("project-context").textContent = "Shared research brief";
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
    try {
      const incoming = (await requestJSON(`/api/intelligence/source-history/${incomingArticle}`)).source;
      if (incoming) {
        const preview = byId("project-selected-source");
        const description = node("p", null, "research-meta");
        description.append(`${incoming.publisher} · `, sourceLink(incoming));
        preview.append(node("h2", "Source selected"), description,
          node("p", "Choose or create a project, then use Save selected source here in Related evidence."));
        preview.hidden = false;
      }
    }
    catch { /* The server checks availability again when saving. */ }
  }
  await Promise.all([technologies, initWorkspace()]);
}
initialize().catch((error) => { status.textContent = error.message; });
