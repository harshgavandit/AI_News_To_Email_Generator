import { appendClaimEvidence } from "./claim-evidence.js";

export function createStoryQuestion(request, context, externalLink) {
  const byId = id => document.getElementById(id);
  const panel = byId("story-question-panel"), opener = byId("dossier-ask");
  const form = byId("story-question-form"), input = byId("story-question");
  const output = byId("story-question-answer"), status = byId("story-question-status");
  const button = form.querySelector("button[type=submit]");
  let controller;
  opener.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    opener.setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) input.focus();
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const { article, coverage } = context();
    const question = input.value.trim();
    if (!article || !question || button.disabled) return;
    const active = controller = new AbortController();
    button.disabled = true;
    output.replaceChildren();
    output.setAttribute("aria-busy", "true");
    status.classList.remove("error");
    status.textContent = "Checking this story and its supporting sources…";
    try {
      const data = await request("/api/intelligence/converse", {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: active.signal,
        body: JSON.stringify({ question, history: [],
          context_ids: [...new Set([article.id, ...coverage.map(story => story.id)])].slice(0, 8), context_only: true,
          hours: 720, topic: "all", language: "en" }),
      });
      if (controller !== active) return;
      const claims = document.createElement("ul");
      claims.className = "story-answer-claims";
      for (const claim of data.answer?.claims || []) {
        const item = document.createElement("li");
        const text = document.createElement("p");
        text.textContent = claim.text;
        if (claim.kind === "analysis") {
          const label = document.createElement("strong");
          label.textContent = "Interpretation · ";
          text.prepend(label);
        }
        item.append(text);
        appendClaimEvidence(item, claim, data.evidence || [], externalLink);
        claims.append(item);
      }
      output.append(claims);
      if (data.answer?.limitations) {
        const note = document.createElement("p");
        note.className = "small";
        note.textContent = data.answer.limitations;
        output.append(note);
      }
      status.textContent = claims.children.length ? "Answer with linked sources. Review the original reporting for context." :
        "The available source evidence cannot answer this question yet.";
    } catch (error) {
      if (controller === active && !active.signal.aborted) {
        status.classList.add("error");
        status.textContent = error.message;
      }
    } finally {
      if (controller === active) {
        controller = null;
        button.disabled = false;
        output.removeAttribute("aria-busy");
      }
    }
  });
  return { reset() {
    controller?.abort();
    controller = null;
    panel.hidden = true;
    opener.setAttribute("aria-expanded", "false");
    input.value = "";
    output.replaceChildren();
    output.removeAttribute("aria-busy");
    button.disabled = false;
    status.textContent = "";
    status.classList.remove("error");
  } };
}
