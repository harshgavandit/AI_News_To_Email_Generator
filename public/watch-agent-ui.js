import { node } from "./evidence-ui.js";
import { monitorInbox } from "./monitor-inbox.js";

const lists = ["entities", "keywords", "must_have", "exclude"];

export function watchPrecision(watch) {
  const { useful = 0, rated = 0 } = watch.precision || {};
  return rated ? String(useful) + " of " + rated + " alerts marked useful" : "No alerts rated yet";
}

export function alertDetails(alert, onFeedback) {
  if (!alert.source_checked) return null;
  const details = node("div", null, "watch-agent-reason");
  const badge = node("span", "Source-checked", "research-meta watch-agent-badge");
  details.append(badge);
  if (alert.mode === "keyword") details.append(node("span", "Keyword fallback", "research-meta watch-agent-badge"));
  for (const reason of alert.reason || []) details.append(node("p", reason));
  const actions = node("div", null, "reader-actions");
  for (const [label, rating] of [["Good alert", "good"], ["Not relevant", "not_relevant"]]) {
    const button = node("button", label, "button secondary");
    button.type = "button";
    button.setAttribute("aria-pressed", String(alert.feedback === rating));
    button.addEventListener("click", async () => {
      button.disabled = true;
      try { await onFeedback(alert.id, rating); }
      finally { button.disabled = false; }
    });
    actions.append(button);
  }
  details.append(actions);
  return details;
}

export function initWatchAgent(root, save, draft = (sentence) => monitorInbox("/agent-draft", {
  method: "POST", body: { sentence },
})) {
  const input = root.querySelector("[data-agent-draft]");
  const confirm = root.querySelector("[data-agent-confirm]");
  const status = root.querySelector("[data-agent-status]");
  const cancel = root.querySelector("[data-agent-cancel]");
  let activeId = null;
  let busy = false;
  let selectedTopics = [];
  const field = (name) => confirm.elements.namedItem(name);
  const sentence = input.elements.namedItem("sentence");
  const draftButton = input.querySelector("button");
  const saveButton = confirm.querySelector("button");

  function show(spec) {
    field("summary").value = spec.summary;
    field("severity").value = spec.severity;
    selectedTopics = spec.topics;
    for (const option of field("topics").options) option.selected = selectedTopics.includes(option.value);
    for (const name of lists) field(name).value = spec[name].join(", ");
    confirm.hidden = false;
    field("summary").focus();
  }

  async function perform(button, operation) {
    if (busy) return;
    busy = true;
    draftButton.disabled = saveButton.disabled = cancel.disabled = true;
    try { await operation(); }
    catch (error) { status.textContent = error.message || "The watch could not be saved. Try again."; }
    finally {
      busy = false;
      draftButton.disabled = saveButton.disabled = cancel.disabled = false;
      if (button === draftButton && confirm.hidden) sentence.focus();
    }
  }

  input.addEventListener("input", () => {
    confirm.hidden = true;
    status.textContent = "";
  });
  input.addEventListener("submit", (event) => {
    event.preventDefault();
    perform(draftButton, async () => {
      status.textContent = "Drafting the watch…";
      confirm.hidden = true;
      const requested = sentence.value;
      const result = await draft(requested);
      if (sentence.value !== requested) return;
      if (result.watch) show(result.watch);
      status.textContent = result.notice || "Review the intent and conditions, then confirm.";
    });
  });
  confirm.addEventListener("submit", (event) => {
    event.preventDefault();
    perform(saveButton, async () => {
      const agent = {
        summary: field("summary").value.trim(),
        severity: field("severity").value,
        topics: [...field("topics").selectedOptions].map((option) => option.value),
      };
      for (const name of lists) agent[name] = field(name).value.split(",").map((value) => value.trim()).filter(Boolean);
      const limits = { topics: 5, entities: 8, keywords: 12, must_have: 6, exclude: 6 };
      for (const [name, allowed] of Object.entries(limits)) {
        if (agent[name].length > allowed || agent[name].some((phrase) => phrase.length > 90 || phrase.length < 2)) {
          throw new Error("Use up to " + allowed + " entries of 2–90 characters for " + name.replaceAll("_", " ") + ".");
        }
      }
      if (!agent.keywords.length && !agent.entities.length && !agent.must_have.length) {
        throw new Error("Add a search phrase, entity or required condition.");
      }
      const result = await save({ id: activeId || crypto.randomUUID(), query: agent.summary, topic: "all", agent });
      if (!result) throw new Error("The watch could not be saved. Check the watch list status below.");
      confirm.hidden = true;
      sentence.value = "";
      activeId = null;
      status.textContent = "Watch saved. New matches will appear in the alerts inbox.";
      sentence.focus();
    });
  });
  cancel.addEventListener("click", () => {
    activeId = null;
    sentence.value = "";
    confirm.hidden = true;
    status.textContent = "";
    sentence.focus();
  });
  return {
    edit(watch) {
      if (busy) return;
      activeId = watch.id;
      sentence.value = watch.query;
      root.open = true;
      show(watch.agent);
      status.textContent = "Update the conditions and confirm to save.";
    },
    topics(topics) {
      field("topics").replaceChildren(...Object.entries(topics).map(([id, label]) => new Option(label, id, false,
        selectedTopics.includes(id))));
    },
  };
}
