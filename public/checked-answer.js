import { sendFeedback } from "./feedback.js";

function node(tag, text, className) {
  const item = document.createElement(tag);
  item.textContent = text;
  if (className) item.className = className;
  return item;
}

function sourceLink(source, label) {
  let url;
  try { url = new URL(source.url); } catch { return document.createTextNode(label); }
  if (!["http:", "https:"].includes(url.protocol)) return document.createTextNode(label);
  const link = node("a", label);
  link.href = url.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.setAttribute("aria-label", `${label} ${source.publisher}: ${source.title}`);
  return link;
}

function verified(result) {
  const { sourced, quotes_verified: quotes, links_clean: links } = result.checks || {};
  return result.status === "answered" && sourced && quotes && links;
}

function appendCitedText(output, text, byNumber) {
  for (const line of text.split("\n")) {
    const paragraph = node("p", "");
    for (const part of line.split(/(\[\d+\])/)) {
      const source = /^\[\d+\]$/.test(part) && byNumber.get(Number(part.slice(1, -1)));
      paragraph.append(source ? sourceLink(source, part) : document.createTextNode(part));
    }
    output.append(paragraph);
  }
}

function appendReferences(output, citations, question, { report = sendFeedback, storyIds = [], mode } = {}) {
  const sources = node("ul", "", "checked-sources");
  for (const source of citations) {
    const row = node("li", "");
    row.append(sourceLink(source, `[${source.n}] ${source.publisher} · ${source.title}`));
    sources.append(row);
  }
  output.append(sources);
  const button = node("button", "Report this answer", "text-button");
  button.type = "button";
  button.title = "Send the question and its story references to Informa";
  const status = node("span", "", "small");
  status.setAttribute("role", "status");
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "Sending report…";
    try {
      await report({ kind: "ai_answer", question, ...(mode && { mode }), story_ids: [...new Set([...storyIds, ...citations.map(source => source.id)])].slice(0, 10) });
      status.textContent = " Thanks for reporting this answer.";
    } catch {
      status.textContent = " The report could not be sent. Try again.";
      button.disabled = false;
    }
  });
  output.append(button, status);
}

export function renderCheckedAnswer(output, result, question, options) {
  output.replaceChildren();
  if (!verified(result)) return false;
  const citations = result.citations || [];
  const byNumber = new Map(citations.map(source => [source.n, source]));
  output.append(node("span", "Source-checked", "source-checked"));
  appendCitedText(output, result.answer, byNumber);
  appendReferences(output, citations, question, options);
  return true;
}

export function renderDeepReport(output, result, question, options) {
  output.replaceChildren();
  if (!verified(result)) return false;
  const citations = result.citations || [];
  const byNumber = new Map(citations.map(source => [source.n, source]));
  const report = node("article", "", "deep-report");
  report.append(node("span", "Source-checked", "source-checked"), node("h3", "Research summary"));
  appendCitedText(report, result.summary, byNumber);
  for (const section of result.sections) {
    report.append(node("h4", section.heading));
    appendCitedText(report, section.text, byNumber);
  }
  report.append(node("h4", "Timeline of coverage"));
  const timeline = node("ol", "", "deep-timeline");
  for (const entry of result.timeline) {
    const item = node("li", "");
    const date = node("time", entry.date);
    date.dateTime = entry.date;
    item.append(date);
    appendCitedText(item, entry.event, byNumber);
    timeline.append(item);
  }
  report.append(timeline, node("h4", "Sources"));
  appendReferences(report, citations, question, { ...options, mode: "deep" });
  output.append(report);
  return true;
}
