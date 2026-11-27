import { renderCheckedAnswer } from "./checked-answer.js";
import { countUse } from "./usage.js";

export function mountAsk(root, { fetcher = globalThis.fetch, track = countUse } = {}) {
  const form = root.querySelector("form");
  const question = form.elements.question;
  const days = form.elements.days;
  const submit = form.querySelector("button[type=submit]");
  const status = root.querySelector("[data-ask-status]");
  const answer = root.querySelector("[data-ask-answer]");
  for (const option of root.querySelectorAll("[data-ask-example]")) {
    option.addEventListener("click", () => {
      question.value = option.dataset.askExample;
      question.focus();
    });
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (submit.disabled || !question.value.trim()) return;
    const text = question.value.trim();
    submit.disabled = true;
    answer.replaceChildren();
    answer.setAttribute("aria-busy", "true");
    status.textContent = "Looking through the archive…";
    track("ask_informa", "question");
    try {
      const response = await fetcher("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text, days: Number(days?.value || 7) }),
      });
      if (response.status === 429) {
        status.textContent = "You’ve reached the question limit. Wait a few minutes and try again.";
        track("ask_informa", "error");
        return;
      }
      if (!response.ok) throw new Error("Ask Informa is temporarily unavailable.");
      const result = await response.json();
      const rendered = renderCheckedAnswer(answer, result, text);
      status.textContent = rendered ? "Answer ready." : result.answer || "Not enough coverage to answer this.";
      track("ask_informa", rendered ? "answered" : "unanswered");
    } catch {
      status.textContent = "Ask Informa is temporarily unavailable. You can still search the Reading Room.";
      track("ask_informa", "error");
    } finally {
      answer.removeAttribute("aria-busy");
      submit.disabled = false;
    }
  });
}

if (typeof document !== "undefined") {
  for (const root of document.querySelectorAll("[data-ask]")) mountAsk(root);
}
