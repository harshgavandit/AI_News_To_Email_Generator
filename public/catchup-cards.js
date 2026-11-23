// Catch-up cards: one card per new or updated development, with its source in view.
// Pure DOM construction; app.js supplies the helpers so the card stays testable.

const BARE_VERSION = /^v?\d+(?:\.\d+)+(?:[-+.][\w.]+)?$/i;

// Release feeds often title an entry with only its version; name the project as well.
export function cardTitle(event, story) {
  const title = String(event.title || story?.title || "").trim();
  const publisher = String(story?.publisher || "").replace(/\s+Releases?$/i, "").trim();
  return BARE_VERSION.test(title) && publisher ? `${publisher} ${title}` : title;
}

export function changeLabel(event) {
  return event.change === "updated" ? "Updated" : "New";
}

const initial = (name) => (String(name || "?").trim().match(/[\p{L}\p{N}]/u)?.[0] || "?").toUpperCase();

/**
 * Build one catch-up card. `helpers` provides: node(tag, className, text), externalLink(url, label),
 * openDossier(story, trigger), developmentLink(id), appendClaimEvidence(target, claim, evidence, link),
 * topicLabel(id), relativeTime(value), readableTime(value).
 */
export function catchupCard(event, helpers) {
  const { node, externalLink, openDossier, developmentLink, appendClaimEvidence, topicLabel, relativeTime, readableTime } = helpers;
  const story = event.articles?.[0];
  if (!story) return null;
  const card = node("article", "catchup-card");
  card.dataset.change = event.change === "updated" ? "updated" : "new";

  const head = node("div", "catchup-card-head");
  head.append(node("span", "catchup-badge", changeLabel(event)));
  const topic = topicLabel(event.topic);
  if (topic) head.append(node("span", "catchup-topic", topic));
  const when = node("time", "catchup-time", relativeTime(event.updated_at));
  if (event.updated_at) {
    when.dateTime = event.updated_at;
    when.title = readableTime(event.updated_at);
  }
  head.append(when);

  const heading = node("h3", "catchup-title");
  const open = node("button", "", cardTitle(event, story));
  open.type = "button";
  open.addEventListener("click", () => openDossier(story, open));
  heading.append(open);
  card.append(head, heading);

  if (event.change_sources?.length) {
    const changes = node("ul", "catchup-changes");
    changes.setAttribute("aria-label", "What changed");
    for (const change of event.change_sources.slice(0, 3)) {
      const item = node("li");
      item.append(node("span", "catchup-change-label", change.change_label));
      if (change.excerpt) item.append(node("p", "catchup-summary", change.excerpt));
      const source = externalLink(change.url, `${change.publisher} ↗`);
      source.className = "catchup-change-source";
      item.append(source);
      changes.append(item);
    }
    card.append(changes);
  } else if (story.cleanSummary) {
    card.append(node("p", "catchup-summary", story.cleanSummary));
  }

  if (event.explanation?.claims?.length) {
    const explained = node("details", "catchup-explanation");
    explained.append(node("summary", "", "Why it matters · AI explanation"));
    for (const claim of event.explanation.claims) {
      const finding = node("div", "catchup-claim");
      finding.append(node("p", "", claim.kind === "analysis" ? `Interpretation · ${claim.text}` : claim.text));
      appendClaimEvidence(finding, claim, event.explanation_evidence || [], externalLink);
      explained.append(finding);
    }
    if (event.explanation.limitations) explained.append(node("p", "small", event.explanation.limitations));
    card.append(explained);
  }

  const foot = node("div", "catchup-card-foot");
  const source = node("div", "catchup-source");
  source.append(node("span", "catchup-avatar", initial(story.publisher)));
  const names = node("div", "catchup-source-names");
  names.append(node("strong", "", story.publisher || "Publisher"));
  const count = Number(event.source_count) || 1;
  names.append(node("span", "", count === 1 ? "1 publisher" : `${count} publishers`));
  source.append(names);
  const actions = node("div", "catchup-actions");
  const read = externalLink(story.url, "Read original ↗");
  read.className = "catchup-read";
  read.setAttribute("aria-label", `Read “${cardTitle(event, story)}” at ${story.publisher || "the publisher"}`);
  actions.append(read);
  const timelineHref = developmentLink(event.id);
  if (timelineHref) {
    const timeline = node("a", "catchup-timeline", "Timeline");
    timeline.href = timelineHref;
    actions.append(timeline);
  }
  foot.append(source, actions);
  card.append(foot);
  return card;
}
