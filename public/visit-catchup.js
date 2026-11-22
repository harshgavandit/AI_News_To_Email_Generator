const endpoint = "/api/intelligence/visit-catchup";
const rangeDate = new Intl.DateTimeFormat(undefined, {
  month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
});
const publicationDate = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const dayPrecision = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" });
const changeLabels = {
  published: "New publication",
  newly_observed: "New on Informa",
  event_update: "Developing story",
};
const updateLabels = {
  source_revision: "The publisher revised this report.",
  additional_reporting: "New reporting in a tracked development.",
};

function publisherURL(value) {
  try {
    const url = new URL(value);
    if (url.protocol === "https:" && !url.username && !url.password) return url.href;
  } catch { /* Keep the attribution as text when a publisher link is invalid. */ }
  return "";
}

export function createVisitCatchup({ region, request, openArticle }) {
  const document = region.ownerDocument;
  const heading = region.querySelector("#visit-catchup-title");
  const content = region.querySelector("#visit-catchup-content");
  const sectionHeading = heading.tagName === "H3" ? "h4" : "h3";
  const articleHeading = heading.tagName === "H3" ? "h5" : "h4";
  const element = (tag, className, value) => {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (value) item.textContent = value;
    return item;
  };
  const makeButton = (label) => {
    const button = element("button", "button secondary", label);
    button.type = "button";
    return button;
  };
  const range = element("p", "visit-catchup-range");
  const description = element("p", "visit-catchup-note");
  const status = element("p", "visit-catchup-status");
  status.setAttribute("role", "status");
  const actions = element("div", "visit-catchup-actions");
  const analyze = makeButton("Summarize with AI");
  const retry = makeButton("Retry catch-up");
  const refresh = makeButton("Check for updates");
  const answer = element("div", "visit-catchup-answer");
  const sources = element("div", "visit-catchup-sources");
  const notice = element("p", "visit-catchup-note");
  actions.append(analyze, retry, refresh);
  content.replaceChildren(range, description, status, actions, answer, sources, notice);

  let input, activeRequest, period, snapshot;

  function timestamp(value, formatter, prefix = "") {
    const date = Date.parse(value);
    if (!Number.isFinite(date)) return null;
    const stamp = element("time", "", prefix + formatter.format(date));
    stamp.dateTime = value;
    return stamp;
  }

  function publishTime(row) {
    const formatter = row.date_precision === "day" || row.publication_date_precision === "day" ? dayPrecision : publicationDate;
    return timestamp(row.published_at, formatter, "Published ");
  }

  function sourceAttribution(row) {
    const source = element("div", "visit-catchup-attribution");
    const link = publisherURL(row.url);
    const publisher = element(link ? "a" : "span", "", row.publisher || "Original publisher");
    publisher.dir = "auto";
    if (link) {
      publisher.href = link;
      publisher.rel = "noopener noreferrer";
      publisher.target = "_blank";
      if (row.title) publisher.title = row.title;
    }
    source.append(publisher);
    const date = publishTime(row);
    if (date) source.append(date);
    return source;
  }

  function renderPeriod() {
    heading.textContent = !input.persistent ? "Your 24-hour catch-up" :
      period?.window === "first_visit" || (!period && !input.since) ? "Your first catch-up" : "What changed";
    range.replaceChildren();
    if (period) {
      const start = timestamp(period.since, rangeDate);
      const end = timestamp(period.as_of, rangeDate);
      if (start && end) range.append(start, " to ", end);
    }
    description.textContent = !input.persistent ? "This browser could not save visit history. Showing the latest 24 hours." :
      period?.window === "clamped" ? "Your last visit was outside the seven-day limit. Showing the most recent seven days." :
      period?.window === "first_visit" || (!period && !input.since) ? "Start with developments from the past 24 hours." :
        "New and updated stories since your last visit.";
  }

  function readerLink(row, readerStatus) {
    if (!/^[a-z\d_-]{1,40}$/i.test(row.id || "")) return null;
    const url = new URL(document.URL);
    url.searchParams.set("article", row.id);
    url.hash = "reading-room";
    const link = element("a", "visit-catchup-reader", "Open in reader");
    link.href = url.href;
    link.setAttribute("aria-label", `Open in reader: ${row.title}`);
    if (openArticle) link.addEventListener("click", async (event) => {
      if (event.defaultPrevented || event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      event.preventDefault();
      if (link.getAttribute("aria-busy") === "true") return;
      link.setAttribute("aria-busy", "true");
      readerStatus.textContent = "";
      try { await openArticle(row.id, link); }
      catch { readerStatus.textContent = "The reader could not be opened. Try the publisher link or retry."; }
      finally { link.removeAttribute("aria-busy"); }
    });
    return link;
  }

  function renderSources(rows) {
    if (!rows.length) {
      const browse = element("a", "visit-catchup-reader", "Browse All stories");
      browse.href = "/#reading-room";
      sources.replaceChildren(browse);
      return;
    }
    const list = element("ul", "visit-catchup-list");
    for (const row of rows) {
      const entry = element("li", "visit-catchup-entry");
      const title = element(articleHeading, "visit-catchup-story-title", row.title);
      title.dir = "auto";
      if (row.language) title.lang = row.language;
      const change = changeLabels[row.change_type];
      if (change) entry.append(element("span", "visit-catchup-change", change));
      entry.append(title, sourceAttribution(row));
      if (row.change_type !== "published") {
        const observed = timestamp(row.observed_at, rangeDate, "Added to Informa ");
        if (observed) {
          observed.className = "visit-catchup-observed";
          entry.append(observed);
        }
      }
      if (Object.hasOwn(updateLabels, row.update_reason)) entry.append(element("p", "visit-catchup-note", updateLabels[row.update_reason]));
      if (row.excerpt) {
        const excerpt = element("p", "visit-catchup-excerpt", row.excerpt);
        excerpt.dir = "auto";
        if (row.language) excerpt.lang = row.language;
        entry.append(excerpt);
      }
      const readerStatus = element("p", "visit-catchup-reader-status");
      readerStatus.setAttribute("role", "status");
      const reader = readerLink(row, readerStatus);
      if (reader) entry.append(reader, readerStatus);
      list.append(entry);
    }
    sources.replaceChildren(element(sectionHeading, "visit-catchup-subheading", "Source evidence"), list);
  }

  function renderAnswer(result, rows) {
    answer.replaceChildren();
    if (!result) return false;
    const records = new Map(rows.map(row => [row.id, row]));
    const list = element("ol", "visit-catchup-claims");
    for (const claim of result.claims || []) {
      const ids = claim.source_ids || [];
      const citations = ids.map(id => records.get(id));
      if (!claim.text || !citations.length || new Set(ids).size !== ids.length || citations.some(row => !row || !publisherURL(row.url))) continue;
      const item = element("li", "visit-catchup-claim");
      if (claim.kind === "analysis") item.append(element("p", "visit-catchup-change", "Interpretation"));
      const text = element("p", "", claim.text);
      text.dir = "auto";
      item.append(text);
      for (const [index, row] of citations.entries()) {
        const attribution = sourceAttribution(row);
        const quote = claim.quotes?.[index];
        if (!quote) {
          item.append(attribution);
          continue;
        }
        const citation = element("div", "visit-catchup-citation");
        const excerpt = element("blockquote", "", quote);
        excerpt.dir = "auto";
        if (row.language) excerpt.lang = row.language;
        citation.append(attribution, excerpt);
        item.append(citation);
      }
      list.append(item);
    }
    if (!list.childElementCount) return false;
    answer.append(element(sectionHeading, "visit-catchup-subheading", "AI summary"), list);
    if (result.limitations) answer.append(element("p", "visit-catchup-note", result.limitations));
    return true;
  }

  function renderSnapshot() {
    renderPeriod();
    const rows = snapshot?.evidence || [];
    const summarized = renderAnswer(snapshot?.answer, rows);
    renderSources(rows);
    analyze.hidden = !rows.some(row => row.excerpt);
    analyze.disabled = false;
    analyze.setAttribute("aria-disabled", String(summarized));
    analyze.textContent = summarized ? "AI summary ready" : "Summarize with AI";
    retry.hidden = true;
    refresh.hidden = false;
    notice.textContent = snapshot?.notice || "";
    status.textContent = summarized ? "Cited AI summary ready." : rows.length ?
      `${rows.length} ${rows.length === 1 ? "development" : "developments"} in this period.` :
      "No developments from the archive in this period.";
    return summarized;
  }

  async function load(useAI = false) {
    if (activeRequest || !input || (useAI && (analyze.hidden || analyze.getAttribute("aria-disabled") === "true"))) return;
    const controller = new AbortController();
    activeRequest = controller;
    actions.setAttribute("aria-busy", "true");
    status.textContent = useAI ? "Preparing a cited AI summary…" : "Checking the archive for developments…";
    analyze.disabled = retry.disabled = refresh.disabled = true;
    try {
      const data = await request(endpoint, {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
        body: JSON.stringify({ since: useAI ? period.since : input.since,
          as_of: useAI ? period.as_of : input.until, analyze: useAI }),
      });
      if (controller.signal.aborted) return;
      if (!Array.isArray(data?.evidence) || !Number.isFinite(Date.parse(data.since)) || !Number.isFinite(Date.parse(data.as_of))) {
        throw new Error("Unexpected catch-up response");
      }
      if (!useAI) period = { since: data.since, as_of: data.as_of, window: data.window };
      if (useAI && !data.answer?.claims?.length) {
        status.textContent = data.answer?.limitations || "An AI summary is unavailable. You can still explore the source evidence.";
        analyze.disabled = false;
        return;
      }
      snapshot = data;
      const summarized = renderSnapshot();
      if (useAI && !summarized) status.textContent = "No cited AI summary was available for these sources.";
    } catch {
      if (controller.signal.aborted) return;
      status.textContent = useAI ? "The AI summary could not be prepared. The source evidence is still available." :
        snapshot ? "The catch-up could not be refreshed. The previous results are still shown." :
          "The catch-up could not be loaded. Try again shortly.";
      if (useAI) analyze.disabled = false;
      else if (snapshot) analyze.disabled = false;
      else retry.hidden = false;
    } finally {
      if (activeRequest === controller) {
        actions.removeAttribute("aria-busy");
        retry.disabled = refresh.disabled = false;
        activeRequest = null;
      }
    }
  }

  const abort = () => {
    activeRequest?.abort();
    activeRequest = null;
    actions.removeAttribute("aria-busy");
  };
  analyze.addEventListener("click", () => load(true));
  retry.addEventListener("click", () => load());
  refresh.addEventListener("click", () => load());

  return {
    show({ since = null, until, persistent = true }) {
      if (!persistent) since = null;
      region.hidden = false;
      if (input && input.since === since && input.until === until && input.persistent === persistent) {
        if (snapshot && !activeRequest) renderSnapshot();
        else load();
        return;
      }
      abort();
      input = { since, until, persistent };
      period = snapshot = null;
      answer.replaceChildren();
      sources.replaceChildren();
      notice.textContent = "";
      analyze.hidden = retry.hidden = refresh.hidden = true;
      renderPeriod();
      load();
    },
    hide() {
      abort();
      region.hidden = true;
    },
  };
}
