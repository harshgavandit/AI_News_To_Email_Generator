export function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text != null) result.textContent = text;
  if (className) result.className = className;
  return result;
}

export function sourceLink(row) {
  const link = node("a", row.title);
  try {
    const url = new URL(row.url);
    if (url.protocol === "https:" && !url.username && !url.password) link.href = url.href;
  } catch { /* A malformed record is displayed without a link. */ }
  link.rel = "noreferrer";
  return link;
}

export function sourceList(rows, decorate) {
  const list = node("ol", null, "research-evidence");
  for (const row of rows) {
    const entry = node("li");
    const heading = node("h3");
    heading.append(sourceLink(row));
    const date = new Date(row.published_at);
    const stamp = Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date) : "";
    entry.append(heading, node("p", [row.publisher, stamp, ...(row.references || [])].filter(Boolean).join(" · "), "research-meta"));
    if (row.excerpt) {
      const excerpt = node("p", row.excerpt);
      excerpt.lang = row.language || "";
      excerpt.dir = "auto";
      entry.append(excerpt);
    }
    decorate?.(entry, row);
    list.append(entry);
  }
  return list;
}

export function answerBlock(answer, evidence) {
  const panel = node("div", null, "intelligence-answer");
  const rows = new Map(evidence.map((row) => [row.id, row]));
  for (const claim of answer?.claims || []) {
    const item = node("article");
    if (claim.kind === "analysis") item.append(node("p", "Interpretation", "research-label"));
    item.append(node("p", claim.text));
    const citations = node("ul", null, "intelligence-citations");
    for (const id of claim.source_ids) {
      const source = rows.get(id);
      if (!source) continue;
      const citation = node("li");
      citation.append(sourceLink({ ...source, title: source.publisher }));
      citations.append(citation);
    }
    item.append(citations);
    if (claim.quotes?.length) {
      const quotes = node("details");
      quotes.append(node("summary", "Read original quotes"));
      for (const [index, quote] of claim.quotes.entries()) {
        const excerpt = node("blockquote", quote);
        excerpt.dir = "auto";
        excerpt.lang = rows.get(claim.source_ids[index])?.language || "";
        quotes.append(excerpt);
      }
      item.append(quotes);
    }
    panel.append(item);
  }
  if (answer?.limitations) panel.append(node("p", answer.limitations, "research-note"));
  return panel;
}

export async function requestJSON(path, { method = "GET", body, signal } = {}) {
  const response = await fetch(path, { method, signal, cache: "no-store", ...(body != null && {
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The request could not be completed. Check your inputs and try again.");
  return data;
}

// Server errors carry a reader-facing detail; programming and network errors do not.
export function readableError(error, fallback = "This information is temporarily unavailable. Try again in a moment.") {
  if (!error?.message || error instanceof TypeError || error instanceof ReferenceError || error instanceof SyntaxError || error instanceof RangeError) return fallback;
  return error.message;
}
