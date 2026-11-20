function element(document, tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function sourceHref(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : "";
  } catch {
    return "";
  }
}

export function renderCuriosityCards(container, cards, options = {}) {
  const document = container.ownerDocument;
  const pinnedIds = new Set(options.pinnedIds || []);
  const scheduledIds = new Set(options.scheduledIds || []);
  const list = element(document, "div", "curiosity-grid");
  const eligible = Array.isArray(cards) ? cards.slice(0, 24) : [];
  const visibleCount = Math.max(1, Math.min(eligible.length, Number(options.visibleCount) || eligible.length));

  if (!eligible.length) {
    const empty = element(document, "p", "curiosity-empty", options.message ||
      "No Curiosity Cards are available right now. The collection will update with the next content sync.");
    container.replaceChildren(empty);
    return;
  }

  for (const card of eligible.slice(0, visibleCount)) {
    if (!card || typeof card.id !== "string" || typeof card.title !== "string") continue;
    const article = element(document, "article", "curiosity-card");
    article.dataset.curiosityId = card.id;

    const top = element(document, "div", "curiosity-card-top");
    top.append(element(document, "span", "curiosity-company", card.company || card.publisher || "Technology"));
    const year = card.year || (card.published_at && String(card.published_at).slice(0, 4));
    if (year) top.append(element(document, "time", "curiosity-year", String(year)));
    article.append(top);

    article.append(element(document, "h3", "curiosity-card-title", card.title));
    const byline = [card.author, card.publisher_detail || card.publisher].filter(Boolean).join(" · ");
    if (byline) article.append(element(document, "p", "curiosity-byline", byline));
    const basis = card.summary_basis === "ai_feed_summary" ? "AI summary from the publisher excerpt" :
      card.summary_basis === "editorial_source_summary" ? "Curated source summary" :
      card.summary_basis === "publisher_excerpt" ? "Publisher excerpt summary" : "Source summary";
    article.append(element(document, "span", "curiosity-summary-basis", basis));
    article.append(element(document, "p", "curiosity-summary", card.summary || card.description ||
      "Open the original source for the publisher’s technical context."));

    const tags = element(document, "ul", "curiosity-tags");
    tags.setAttribute("aria-label", "Topics");
    for (const tag of (Array.isArray(card.tags) ? card.tags : []).slice(0, 5))
      tags.append(element(document, "li", "curiosity-tag", String(tag)));
    if (tags.childElementCount) article.append(tags);

    const footer = element(document, "div", "curiosity-card-footer");
    const minutes = Number.isInteger(card.read_minutes) && card.read_minutes > 0 ? card.read_minutes : 8;
    footer.append(element(document, "span", "curiosity-reading-time", `${minutes} min read`));
    const link = element(document, "a", "curiosity-link", `Read at ${card.publisher || "original source"}`);
    const href = sourceHref(card.url);
    if (href) link.href = href;
    else link.setAttribute("aria-disabled", "true");
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    footer.append(link);
    article.append(footer);

    const actions = element(document, "div", "curiosity-card-actions");
    const pinned = pinnedIds.has(card.id);
    const pin = element(document, "button", "button secondary curiosity-action",
      pinned ? "Remove from Brief Builder" : "Add to Brief Builder");
    pin.type = "button";
    pin.dataset.curiosityPin = "";
    pin.setAttribute("aria-pressed", String(pinned));
    pin.addEventListener("click", () => options.onPin?.(card));
    actions.append(pin);

    const scheduled = scheduledIds.has(card.id);
    const schedule = element(document, "button", "text-button curiosity-schedule",
      options.verified ? (scheduled ? "Remove from scheduled brief" : "Add to scheduled brief") : "Verify to schedule");
    schedule.type = "button";
    schedule.dataset.curiosityScheduled = "";
    schedule.setAttribute("aria-pressed", String(scheduled));
    schedule.setAttribute("aria-label", options.verified
      ? `${scheduled ? "Remove" : "Add"} ${card.title} ${scheduled ? "from" : "to"} scheduled brief`
      : `Verify your inbox to schedule ${card.title}`);
    schedule.addEventListener("click", () => options.onToggleScheduled?.(card, scheduled));
    actions.append(schedule);
    article.append(actions);
    list.append(article);
  }

  if (!list.childElementCount) {
    container.replaceChildren(element(document, "p", "curiosity-empty", "No Curiosity Cards are available right now."));
    return;
  }
  const content = [list];
  if (visibleCount < eligible.length) {
    const more = element(document, "button", "text-button curiosity-show-more",
      `Show ${Math.min(4, eligible.length - visibleCount)} more Curiosity Cards`);
    more.type = "button";
    more.dataset.curiosityShowMore = "";
    more.addEventListener("click", () => options.onShowMore?.());
    content.push(more);
  }
  container.replaceChildren(...content);
}
