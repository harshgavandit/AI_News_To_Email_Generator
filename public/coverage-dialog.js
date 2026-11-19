import { coverageLabels } from "./catalog.js";

function element(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text) item.textContent = text;
  return item;
}

export function createCoverageDialog(dialog, { externalLink, readableTime }) {
  const heading = dialog.querySelector("#coverage-dialog-title");
  const note = dialog.querySelector("#coverage-dialog-note");
  const list = dialog.querySelector("#coverage-dialog-sources");
  const compareButton = dialog.querySelector("#coverage-compare");
  const timelineButton = dialog.querySelector("#coverage-timeline");
  const archive = dialog.querySelector("#coverage-archive");
  let activeStory;
  let trigger;

  function render(timeline) {
    if (!activeStory) return;
    compareButton.setAttribute("aria-pressed", String(!timeline));
    timelineButton.setAttribute("aria-pressed", String(timeline));
    list.classList.toggle("coverage-timeline", timeline);
    const sources = [...activeStory.sources];
    if (timeline) sources.sort((a, b) => (Date.parse(a.published_at) || Infinity) - (Date.parse(b.published_at) || Infinity));
    list.replaceChildren(...sources.map((source) => {
      const item = element("li", "coverage-publication");
      const metadata = element("div", "coverage-publication-meta");
      metadata.append(element("strong", "", source.publisher));
      if (Object.hasOwn(coverageLabels, source.coverage)) {
        metadata.append(element("span", "meta-pill", coverageLabels[source.coverage]));
      }
      if (Number.isFinite(Date.parse(source.published_at))) {
        const dateText = source.date_precision === "day" ?
          new Date(source.published_at).toLocaleDateString(undefined, { dateStyle: "medium", timeZone: "UTC" }) :
          readableTime(source.published_at);
        const date = element("time", "muted", dateText);
        date.dateTime = source.published_at;
        metadata.append(date);
      }
      const title = element("h3", "", source.label);
      title.dir = "auto";
      if (source.language) title.lang = source.language;
      const excerpt = element("p", "coverage-excerpt", source.excerpt || "Headline and source link available.");
      excerpt.dir = "auto";
      if (source.excerpt && source.language) excerpt.lang = source.language;
      const actions = element("div", "coverage-publication-actions");
      const original = externalLink(source.url, "Original ↗");
      if (original.hasAttribute("href")) {
        original.setAttribute("aria-label", `Open original from ${source.publisher}`);
        actions.append(original);
      }
      if (source.article_id) {
        const reader = element("a", "button secondary", "Open in reader");
        const readerUrl = new URL(location.href);
        readerUrl.searchParams.set("article", source.article_id);
        readerUrl.hash = "reading-room";
        reader.href = readerUrl.href;
        reader.setAttribute("aria-label", `Open ${source.publisher} in reader`);
        actions.prepend(reader);
      }
      item.append(metadata, title, excerpt, actions);
      return item;
    }));
  }

  compareButton.addEventListener("click", () => render(false));
  timelineButton.addEventListener("click", () => render(true));
  dialog.addEventListener("close", () => {
    if (trigger?.isConnected) trigger.focus({ preventScroll: true });
    activeStory = trigger = null;
  });

  return (story, opener) => {
    if (dialog.open || !story.sources?.length) return;
    activeStory = story;
    trigger = opener;
    heading.textContent = story.title;
    const count = story.source_count || story.sources.length;
    const countText = count > story.sources.length ? `Showing ${story.sources.length} of ${count} matched publisher groups.` :
      `${count} matched publisher groups.`;
    note.textContent = `${countText} Headline matches are drawn from the recent archive.`;
    const query = story.query || story.title.slice(0, 150);
    archive.href = `/?${new URLSearchParams({ q: query, window: "7d", sort: "relevance" })}#reading-room`;
    render(false);
    dialog.showModal();
    heading.focus({ preventScroll: true });
  };
}
