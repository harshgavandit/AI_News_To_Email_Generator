import { node, requestJSON, sourceList } from "./evidence-ui.js";

export function initRuleBuilder(save) {
  const builder = document.getElementById("rule-builder");
  const form = document.getElementById("watch-rule-form");
  const draft = document.getElementById("watch-rule-draft");
  const status = document.getElementById("watch-rule-status");
  const matches = document.getElementById("watch-rule-matches");
  const preview = document.getElementById("watch-rule-preview");
  const technology = form.elements.namedItem("technology");
  const trigger = form.elements.namedItem("event");
  const selected = new URLSearchParams(location.search).get("watch-tech");
  let busy = false;

  function setFilters() {
    for (const name of ["version", "region"]) {
      const field = form.elements.namedItem(name);
      field.disabled = name === "version" ? trigger.value === "status" : trigger.value !== "status";
      if (field.disabled) field.value = "";
    }
  }
  function watch() {
    const rule = Object.fromEntries(new FormData(form));
    const details = [rule.version && `version mentioned: ${rule.version}`, rule.region && `region mentioned: ${rule.region}`];
    const query = [technology.selectedOptions[0]?.textContent, trigger.selectedOptions[0]?.textContent, ...details].filter(Boolean).join(" · ");
    return { id: crypto.randomUUID(), topic: "all", query, rule };
  }
  async function perform(button, run) {
    if (busy) return;
    busy = true;
    button.disabled = true;
    try { await run(); }
    catch (error) { status.textContent = error.message; }
    finally { busy = false; button.disabled = false; }
  }
  trigger.addEventListener("change", setFilters);
  form.addEventListener("input", () => matches.replaceChildren());
  draft.addEventListener("submit", (event) => {
    event.preventDefault();
    perform(event.submitter || draft.querySelector("button"), async () => {
      status.textContent = "Preparing a draft…";
      const data = await requestJSON("/api/intelligence/watch-draft", { method: "POST", body: Object.fromEntries(new FormData(draft)) });
      if (data.rule) {
        for (const [name, value] of Object.entries(data.rule)) form.elements.namedItem(name).value = value;
        setFilters();
        technology.focus();
      }
      matches.replaceChildren();
      status.textContent = data.notice;
    });
  });
  preview.addEventListener("click", () => perform(preview, async () => {
    if (!form.reportValidity()) return;
    status.textContent = "Checking the last 48 hours…";
    matches.replaceChildren();
    const data = await requestJSON("/api/intelligence/watch", { method: "POST", body: { watches: [watch()] } });
    const rows = data.watches[0].evidence;
    status.textContent = rows.length ? `${rows.length} archive records match these filters.` : "No matching archive records in the last 48 hours.";
    if (rows.length) matches.append(sourceList(rows));
  }));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    perform(event.submitter || form.querySelector('button[type="submit"]'), async () => {
      status.textContent = await save(watch()) ? "Rule saved. Matching updates will appear with your watches." : "The rule was not saved. Check the watch status below.";
    });
  });
  for (const button of [draft.querySelector("button"), ...form.querySelectorAll("button")]) button.disabled = true;
  requestJSON("/api/intelligence/technologies").then(({ technologies, watch_events: triggers }) => {
    technology.replaceChildren(...technologies.map((row) => new Option(row.name, row.id)));
    trigger.replaceChildren(...Object.entries(triggers).map(([key, label]) => new Option(label, key)));
    if (technologies.some((row) => row.id === selected)) { technology.value = selected; builder.open = true; }
    setFilters();
    for (const button of [draft.querySelector("button"), ...form.querySelectorAll("button")]) button.disabled = false;
  }).catch(() => status.replaceChildren(node("span", "Technology rule options could not be loaded.")));
}
