import { renderCheckedAnswer, renderDeepReport } from "./checked-answer.js";
import { countUse } from "./usage.js";

export async function readDeepResponse(response, onStep) {
  if (!response.headers.get("Content-Type")?.includes("text/event-stream")) return response.json();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) throw new Error("Research stream ended without a report.");
      pending += decoder.decode(value, { stream: true });
      const frames = pending.split(/\r?\n\r?\n/);
      pending = frames.pop();
      for (const frame of frames) {
        const lines = frame.split(/\r?\n/);
        const type = lines.find(line => line.startsWith("event:"))?.slice(6).trim();
        const data = lines.filter(line => line.startsWith("data:")).map(line => line.slice(5)).join("\n");
        if (!data || !type) continue;
        const payload = JSON.parse(data);
        if (type === "step") onStep(payload.message);
        if (type === "done" || type === "error") return payload;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function mountAsk(root, { fetcher = globalThis.fetch, track = countUse, report } = {}) {
  const form = root.querySelector("form");
  const question = form.elements.question;
  const days = form.elements.days;
  const submit = form.querySelector("button[type=submit]");
  const status = root.querySelector("[data-ask-status]");
  const answer = root.querySelector("[data-ask-answer]");
  const modes = root.querySelector("[data-ask-mode]");
  const deepWindow = form.querySelector("[data-deep-window]");
  const windows = { quick: days?.value || "7", deep: "30" };
  let mode = "quick";

  modes?.addEventListener("change", () => {
    if (days) windows[mode] = days.value;
    mode = form.elements.mode.value;
    if (deepWindow) deepWindow.disabled = deepWindow.hidden = mode !== "deep";
    if (days) days.value = windows[mode];
    submit.textContent = mode === "deep" ? "Research the archive" : "Find an answer";
  });
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
    const deep = mode === "deep";
    const feature = deep ? "deep_ask" : "ask_informa";
    submit.disabled = true;
    if (modes) modes.disabled = true;
    answer.replaceChildren();
    answer.setAttribute("aria-busy", "true");
    status.textContent = deep ? "Planning…" : "Looking through the archive…";
    track(feature, "question");
    try {
      const response = await fetcher(deep ? "/api/ask/deep" : "/api/ask", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(deep && { Accept: typeof ReadableStream === "function" ? "text/event-stream" : "application/json" }),
        },
        body: JSON.stringify({ question: text, days: Number(days?.value || windows[mode]) }),
      });
      if (response.status === 429) {
        status.textContent = "You’ve reached the question limit. Wait a few minutes and try again.";
        track(feature, "error");
        return;
      }
      if (!response.ok) throw new Error("Ask Informa is temporarily unavailable.");
      const result = deep
        ? await readDeepResponse(response, message => { status.textContent = message; })
        : await response.json();
      const rendered = (deep ? renderDeepReport : renderCheckedAnswer)(answer, result, text, { report });
      status.textContent = rendered
        ? (deep ? "Research report ready." : "Answer ready.")
        : (deep ? result.summary : result.answer) || "Not enough coverage to answer this.";
      track(feature, rendered ? "answered" : result.reason === "unavailable" ? "error" : "unanswered");
    } catch {
      status.textContent = deep
        ? "Deep research is temporarily unavailable. Try a quick answer or search the Reading Room."
        : "Ask Informa is temporarily unavailable. You can still search the Reading Room.";
      track(feature, "error");
    } finally {
      answer.removeAttribute("aria-busy");
      submit.disabled = false;
      if (modes) modes.disabled = false;
    }
  });
}

if (typeof document !== "undefined") {
  for (const root of document.querySelectorAll("[data-ask]")) mountAsk(root);
}
