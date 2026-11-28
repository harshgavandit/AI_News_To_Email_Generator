import { node, readableError } from "./evidence-ui.js";

const titles = { duplicate: "Duplicate grouping", labels: "Classification", hide: "Hide story",
  source: "Source health", recap: "Weekly recap note", curiosity: "Curiosity candidate" };
const date = value => new Date(value * 1000).toLocaleString();

function link(text, href) {
  const element = node("a", text);
  try {
    const url = new URL(href, location.origin);
    if (["https:", "http:"].includes(url.protocol) && !url.username && !url.password) {
      element.href = url.href;
      if (url.origin !== location.origin) {
        element.target = "_blank";
        element.rel = "noopener noreferrer";
      }
    }
  } catch { /* Display the title without a link. */ }
  return element;
}

export function startEditor(doc = document, fetcher = globalThis.fetch) {
  const byId = id => doc.getElementById(id);
  const login = byId("editor-login");
  const work = byId("editor-work");
  const status = byId("editor-status");
  const filters = byId("editor-filters");
  const bulk = byId("editor-bulk");
  const selected = new Map();
  const list = byId("editor-items");
  const activity = byId("editor-activity");
  const feedback = byId("editor-feedback-panel");
  let token = "";
  let offset = 0;
  let activityOffset = 0;
  let busy = false;
  let generation = 0;
  let options = {};

  function button(text, run, emphasis = "secondary") {
    const element = node("button", text, "button " + emphasis);
    element.type = "button";
    element.addEventListener("click", run);
    return element;
  }

  function lock() {
    generation++;
    busy = false;
    token = "";
    activityOffset = offset = 0;
    work.hidden = true;
    login.hidden = false;
    list.replaceChildren();
    activity.replaceChildren();
    feedback.replaceChildren();
    feedback.hidden = true;
    selected.clear();
    login.reset();
    login.elements.key.focus();
  }

  async function api(path, body) {
    const initial = generation;
    const headers = { Authorization: "Bearer " + token };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetcher("/api/admin/" + path, {
      method: body === undefined ? "GET" : "POST", body: body === undefined ? undefined : JSON.stringify(body),
      headers, cache: "no-store", credentials: "same-origin", signal: AbortSignal.timeout(20000),
    });
    if (response.status === 401) {
      if (initial === generation) lock();
      throw new Error("Enter a valid owner access key.");
    }
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The request could not be completed.");
    return data;
  }

  async function perform(run) {
    if (busy || !token) return;
    const initial = generation;
    busy = true;
    work.setAttribute("aria-busy", "true");
    try { await run(initial); }
    catch (error) { if (initial === generation || !token) status.textContent = readableError(error); }
    finally {
      if (initial === generation || !token) {
        busy = false;
        work.removeAttribute("aria-busy");
      }
    }
  }

  function actionText(item) {
    const action = item.action;
    if (item.kind === "labels") return Object.entries(action.labels).map(([key, value]) =>
      key + " → " + (options[key === "language" ? "languages" : key + "s"]?.[value] || value)).join(" · ");
    if (item.kind === "source") return action.operation === "pause" ? "Pause this source" : "Acknowledge for source review";
    if (item.kind === "recap") return "Week " + action.week;
    if (item.kind === "curiosity") return "Keep this candidate on the private shortlist";
    if (item.kind === "hide") return "Hide this story from archive views";
    return "Group both reports under one development";
  }

  function field(label, input) {
    const wrapper = node("label");
    wrapper.append(doc.createTextNode(label), input);
    return wrapper;
  }

  function chooser(values, name, current, blank = false) {
    const input = node("select");
    input.name = name;
    if (blank) input.append(new Option("Keep current proposal", ""));
    for (const [id, text] of Object.entries(values)) input.append(new Option(text, id, false, id === current));
    return input;
  }

  function editor(item, submit) {
    const panel = node("details");
    panel.append(node("summary", "Edit then approve"));
    const form = node("form", null, "editor-edit");
    const action = item.action;
    if (item.kind === "duplicate") {
      form.append(field("Anchor story", chooser(Object.fromEntries(item.evidence.map(row => [row.id, row.title])),
        "anchor", action.stories[0])));
    } else if (item.kind === "labels") {
      for (const [key, label, values] of [["topic", "Topic", options.topics], ["region", "Region", options.regions],
        ["language", "Language", options.languages]]) {
        form.append(field(label, chooser(values, key, action.labels[key], true)));
      }
    } else if (item.kind === "source") {
      form.append(field("Action", chooser({ review: "Review", pause: "Pause" }, "operation", action.operation)));
    } else if (item.kind === "recap") {
      action.note.forEach((line, index) => {
        const input = node("textarea");
        input.name = "line-" + index;
        input.value = line.text;
        input.required = true;
        input.minLength = 8;
        input.maxLength = 240;
        form.append(field("Line " + (index + 1) + " · " + (item.evidence.find(row => row.id === line.story_id)?.publisher || "Source"), input));
      });
    } else if (item.kind === "curiosity") {
      const input = node("textarea");
      input.name = "pitch";
      input.value = item.reason[0];
      input.maxLength = 240;
      form.append(field("Private pitch", input));
    } else if (item.kind === "hide") {
      const input = node("textarea");
      input.name = "hide_reason";
      input.value = item.signal;
      input.minLength = 8;
      input.maxLength = 240;
      form.append(field("Owner rationale", input));
    }
    const save = node("button", "Approve edited action", "button primary");
    save.type = "submit";
    form.append(save);
    form.addEventListener("submit", event => {
      event.preventDefault();
      const values = Object.fromEntries([...new FormData(form)].filter(([, value]) => value));
      const edit = item.kind === "recap" ? { note: action.note.map((line, i) => ({ ...line, text: values["line-" + i] })) } : values;
      submit("approve", edit);
    });
    panel.append(form);
    return panel;
  }

  async function load(initial) {
    const params = new URLSearchParams(new FormData(filters));
    params.set("offset", String(offset));
    params.set("activity_offset", String(activityOffset));
    status.textContent = "Loading private review queue…";
    const data = await api("editor?" + params);
    if (initial !== generation) return;
    options = data.options;
    selected.clear();
    bulk.disabled = true;
    byId("editor-count").textContent = data.pending + " pending · " + data.items.length + " shown";
    byId("editor-previous").hidden = offset === 0;
    byId("editor-next").hidden = !data.more;
    list.replaceChildren();
    for (const item of data.items) {
      const card = node("article", null, "editor-card");
      card.append(node("h3", titles[item.kind]), node("p",
        Math.round(item.confidence * 100) + "% · " + (item.mode === "heuristic" ? "Heuristic only" : "AI reviewed") +
        " · " + item.status + " · " + date(item.created)), node("p", actionText(item), "editor-action"),
      node("p", item.signal), ...item.reason.map(line => node("p", line)));
      const evidence = node("ul");
      for (const row of item.evidence) {
        const entry = node("li");
        entry.append(link(row.title, row.url), node("span", " · " + row.publisher + " · " + row.date));
        if (row.excerpt) entry.append(node("p", row.excerpt));
        evidence.append(entry);
      }
      card.append(evidence);
      if (["pending", "snoozed"].includes(item.status)) {
        const submit = (action, edit) => perform(async current => {
          await api("editor/" + item.id, { action, revision: item.revision, ...(edit && { edit }) });
          await load(current);
          status.textContent = "Decision saved.";
          status.focus();
        });
        const actions = node("div", null, "editor-controls");
        actions.append(button("Approve", () => submit("approve"), "primary"), button("Reject", () => submit("reject")),
          button("Snooze 24 hours", () => submit("snooze")));
        card.append(actions);
        card.append(editor(item, submit));
        if (item.kind === "duplicate" && item.status === "pending" && item.confidence >= data.bulk_confidence) {
          const checkbox = node("input");
          checkbox.type = "checkbox";
          checkbox.addEventListener("change", () => {
            if (checkbox.checked && selected.size < 10) selected.set(item.id, item.revision);
            else { selected.delete(item.id); checkbox.checked = false; }
            bulk.disabled = !selected.size;
          });
          card.append(field("Select for bulk approval", checkbox));
        }
      }
      list.append(card);
    }
    activity.replaceChildren();
    byId("editor-newer-activity").hidden = activityOffset === 0;
    byId("editor-older-activity").hidden = !data.more_activity;
    if (!data.activity.length) activity.append(node("li", "No decisions yet."));
    for (const item of data.activity) {
      const row = node("li", titles[item.kind] + " · " + item.action + " · " + date(item.created));
      if (item.target) row.append(node("p", item.target));
      if (item.action === "approve" && item.status === "approved") row.append(button("Undo", () => perform(async current => {
        await api("editor/" + item.suggestion_id, { action: "undo", revision: item.revision });
        await load(current);
        status.textContent = "Decision undone.";
        status.focus();
      })));
      activity.append(row);
    }
    work.hidden = false;
    login.hidden = true;
    status.textContent = data.items.length ? "Review queue loaded." : "No suggestions match these filters.";
  }

  login.addEventListener("submit", event => {
    event.preventDefault();
    token = login.elements.key.value.trim();
    login.reset();
    perform(load);
  });
  filters.addEventListener("submit", event => { event.preventDefault(); offset = 0; perform(load); });
  byId("editor-lock").addEventListener("click", () => { lock(); status.textContent = "Queue locked."; });
  byId("editor-previous").addEventListener("click", () => { offset = Math.max(0, offset - 50); perform(load); });
  byId("editor-next").addEventListener("click", () => { offset += 50; perform(load); });
  byId("editor-newer-activity").addEventListener("click", () => { activityOffset = Math.max(0, activityOffset - 80); perform(load); });
  byId("editor-older-activity").addEventListener("click", () => { activityOffset += 80; perform(load); });
  bulk.addEventListener("click", () => perform(async initial => {
    if (selected.size && globalThis.confirm("Approve the selected duplicate groupings?")) {
      await api("editor/bulk", { items: Object.fromEntries(selected) });
      await load(initial);
      status.textContent = "Duplicate groupings approved.";
    }
  }));
  byId("editor-feedback").addEventListener("click", () => perform(async initial => {
    if (!feedback.hidden) { feedback.replaceChildren(); feedback.hidden = true; return; }
    const data = await api("feedback");
    if (initial !== generation) return;
    feedback.replaceChildren(node("h2", "Owner feedback"), node("p", data.editor_pending + " pending editor suggestions"));
    for (const row of data.feedback) feedback.append(node("p", row.kind + " · " + row.message));
    feedback.hidden = false;
  }));
}

if (typeof document !== "undefined" && document.getElementById("editor-login")) startEditor();
