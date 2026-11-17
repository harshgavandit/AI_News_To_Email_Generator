import { node, requestJSON, sourceLink, sourceList } from "./evidence-ui.js";

const relationships = { same_original: "Links to the same original", matching_excerpt: "Repeats the same excerpt",
  related_coverage: "Related coverage in the archive" };
const notices = { correction: "Publisher correction", retraction: "Publisher retraction" };

export function historyControl(id) {
  const disclosure = node("details", null, "source-history");
  disclosure.append(node("summary", "Source history"));
  disclosure.addEventListener("toggle", async () => {
    if (!disclosure.open || disclosure.dataset.loaded) return;
    disclosure.dataset.loaded = "true";
    const panel = node("div", "Loading source history…");
    panel.setAttribute("role", "status");
    disclosure.append(panel);
    try {
      const data = await requestJSON(`/api/intelligence/source-history/${encodeURIComponent(id)}`);
      panel.replaceChildren();
      if (data.editorial_notice) panel.append(node("p", notices[data.editorial_notice], "research-label"));
      if (data.coverage.length > 1) {
        panel.append(node("p", "Related reports in publication order. The earliest available report may not be the original.", "research-note"));
        panel.append(sourceList(data.coverage, (row, source) => {
          row.append(node("p", [relationships[source.relationship], notices[source.editorial_notice]].filter(Boolean).join(" · "), "research-meta"));
        }));
      }
      if (data.revisions.length > 1 || data.revisions.some((row) => row.reason === "source_revision")) {
        panel.append(node("p", "Publisher versions observed by Informa AI", "research-label"));
        const history = node("ol", null, "revision-list");
        for (const entry of data.revisions) {
          const item = node("li");
          item.append(sourceLink(entry), node("p", [new Date(entry.observed_at * 1000).toLocaleString(),
            entry.publisher, notices[entry.editorial_notice]].filter(Boolean).join(" · "), "research-meta"));
          if (entry.excerpt) item.append(node("p", entry.excerpt));
          history.append(item);
        }
        panel.append(history);
      }
      if (!panel.children.length) panel.append(node("p", "The archive has no additional source history for this item.", "research-note"));
    } catch (error) {
      panel.textContent = error.message;
      disclosure.dataset.loaded = "";
    }
  });
  return disclosure;
}
