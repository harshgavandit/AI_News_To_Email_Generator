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

export const MAX_CURIOSITY_CARDS = 240;
const ORIGINS = [["all", "All"], ["fresh", "Fresh"], ["classic", "Classics"]];

// Labels mirror app/curiosity.py; the API also returns them so new themes appear without a client change.
export const CURIOSITY_THEMES = {
  "game-engineering": "Game engineering",
  agents: "AI agents",
  "ai-engineering": "AI-native engineering",
  ai: "AI & LLMs",
  "distributed-systems": "Distributed systems",
  databases: "Databases & storage",
  cloud: "Cloud & infrastructure",
  security: "Security",
  performance: "Performance",
  reliability: "Reliability & postmortems",
  "engineering-practice": "Engineering practice",
};
export const CURIOSITY_FORMATS = {
  postmortem: "Postmortem",
  "case-study": "Case study",
  paper: "Research paper",
  talk: "Conference talk",
  "deep-dive": "Deep dive",
};

// Real-world problems a story is about (mirrors PROBLEMS in app/curiosity.py; the API sends labels too).
export const CURIOSITY_PROBLEMS = {
  outages: "Outages & incidents",
  "scaling-data": "Scaling databases & storage",
  migrations: "Migrations & rewrites",
  performance: "Latency & performance",
  "scaling-traffic": "Scaling traffic & real-time",
  "data-integrity": "Data loss & consistency",
  cost: "Cost & efficiency",
  "security-incidents": "Security incidents",
  "dev-productivity": "Developer productivity",
};

export function cardProblems(card) {
  return Array.isArray(card?.problems) ? card.problems.filter((id) => typeof id === "string") : [];
}

export const CURIOSITY_LEVELS = {
  introductory: "Introductory",
  intermediate: "Intermediate",
  advanced: "Advanced",
};

function companyOf(card) {
  return card?.company || card?.publisher || "";
}

export function curiosityCompanies(cards) {
  const counts = new Map();
  for (const card of Array.isArray(cards) ? cards : []) {
    const name = companyOf(card);
    if (typeof name === "string" && name) counts.set(name, (counts.get(name) || 0) + 1);
  }
  return [...counts.keys()].sort((a, b) => a.localeCompare(b));
}

export function cardThemes(card) {
  if (Array.isArray(card?.themes) && card.themes.length) return card.themes;
  return card?.theme ? [card.theme] : [];
}

function searchable(card) {
  return [card.title, card.question, companyOf(card), card.publisher, CURIOSITY_LEVELS[card.level], card.publisher_detail, card.author, card.summary, card.why_read,
    ...(Array.isArray(card.technologies) ? card.technologies : []), ...(Array.isArray(card.tags) ? card.tags : []),
    ...cardThemes(card).map((theme) => CURIOSITY_THEMES[theme] || theme),
    ...cardProblems(card).map((problem) => CURIOSITY_PROBLEMS[problem] || problem),
    ...Object.values(card.breakdown && typeof card.breakdown === "object" ? card.breakdown : {})]
    .filter((value) => typeof value === "string").join(" ").toLocaleLowerCase();
}

// The technologies most cards mention, offered as one-tap searches.
export function popularSearches(cards, limit = 8) {
  const counts = new Map();
  for (const card of Array.isArray(cards) ? cards : []) {
    const seen = new Set();
    for (const label of Array.isArray(card?.technologies) ? card.technologies : []) {
      const key = String(label).trim();
      if (!key || key.length > 24 || seen.has(key.toLowerCase())) continue;
      seen.add(key.toLowerCase());
      counts.set(key, (counts.get(key) || 0) + 1);
    }
  }
  return [...counts.entries()].filter(([, count]) => count >= 3)
    .sort(([a, x], [b, y]) => y - x || a.localeCompare(b)).slice(0, limit).map(([label]) => label);
}

export function curiosityDate(card) {
  const value = String(card?.published_at || "");
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
    const date = new Date(`${value.slice(0, 10)}T00:00:00Z`);
    if (!Number.isNaN(date.getTime())) {
      return { iso: value.slice(0, 10), label: date.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) };
    }
  }
  const year = Number(card?.year) || Number(value.slice(0, 4));
  return year ? { iso: String(year), label: String(year) } : null;
}

function sortKey(card) {
  const date = curiosityDate(card);
  return date ? date.iso : "";
}

export function filterCuriosityCards(cards, filter = {}) {
  const origin = filter.origin || "all";
  const company = filter.company || "all";
  const theme = filter.theme || "all";
  const format = filter.format || "all";
  const level = filter.level || "all";
  const problem = filter.problem || "all";
  const terms = String(filter.query || "").toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const result = (Array.isArray(cards) ? cards : []).filter((card) => {
    if (!card) return false;
    if (origin === "fresh" && card.seed) return false;
    if (origin === "classic" && !card.seed) return false;
    if (company !== "all" && companyOf(card) !== company) return false;
    if (theme !== "all" && !cardThemes(card).includes(theme)) return false;
    if (format !== "all" && card.format !== format) return false;
    if (level !== "all" && card.level !== level) return false;
    if (problem !== "all" && !cardProblems(card).includes(problem)) return false;
    if (terms.length) {
      const text = searchable(card);
      if (!terms.every((term) => text.includes(term))) return false;
    }
    return true;
  });
  if (filter.sort === "newest") {
    return result.map((card, index) => [card, index])
      .sort(([a, ai], [b, bi]) => sortKey(b).localeCompare(sortKey(a)) || ai - bi)
      .map(([card]) => card);
  }
  return result;
}

function renderFilters(document, all, filter, onFilter) {
  const bar = element(document, "div", "curiosity-filters");
  bar.setAttribute("role", "group");
  bar.setAttribute("aria-label", "Filter Curiosity Cards");
  const origins = element(document, "div", "curiosity-origin-chips");
  for (const [value, label] of ORIGINS) {
    const count = filterCuriosityCards(all, { origin: value }).length;
    if (value !== "all" && !count) continue;
    const chip = element(document, "button", "curiosity-chip", `${label} · ${count}`);
    chip.type = "button";
    chip.dataset.curiosityOrigin = value;
    chip.setAttribute("aria-pressed", String((filter.origin || "all") === value));
    chip.addEventListener("click", () => onFilter?.({ ...filter, origin: value }));
    origins.append(chip);
  }
  bar.append(origins);
  const selects = element(document, "div", "curiosity-filter-selects");
  const themes = Object.keys(CURIOSITY_THEMES).filter((theme) => all.some((card) => cardThemes(card).includes(theme)));
  if (themes.length > 1) {
    const label = element(document, "label", "curiosity-company-filter");
    label.append(element(document, "span", "", "Theme"));
    const select = element(document, "select", "curiosity-company-select");
    select.dataset.curiosityTheme = "";
    select.append(new document.defaultView.Option("All themes", "all"));
    for (const theme of themes) select.append(new document.defaultView.Option(CURIOSITY_THEMES[theme], theme));
    select.value = themes.includes(filter.theme) ? filter.theme : "all";
    select.addEventListener("change", () => onFilter?.({ ...filter, theme: select.value }));
    label.append(select);
    selects.append(label);
  }
  const companies = curiosityCompanies(all);
  if (companies.length > 1) {
    const label = element(document, "label", "curiosity-company-filter");
    label.append(element(document, "span", "", "Company"));
    const select = element(document, "select", "curiosity-company-select");
    select.dataset.curiosityCompany = "";
    select.append(new document.defaultView.Option("All companies", "all"));
    for (const name of companies) select.append(new document.defaultView.Option(name, name));
    select.value = companies.includes(filter.company) ? filter.company : "all";
    select.addEventListener("change", () => onFilter?.({ ...filter, company: select.value }));
    label.append(select);
    selects.append(label);
  }
  if (selects.childElementCount) bar.append(selects);
  return bar;
}

function renderCard(document, card, options, pinnedIds, scheduledIds) {
  const article = element(document, "article", "curiosity-card");
  article.dataset.curiosityId = card.id;
  const themes = cardThemes(card);
  if (themes[0]) article.dataset.curiosityTheme = themes[0];

  const top = element(document, "div", "curiosity-card-top");
  top.append(element(document, "span", "curiosity-company", companyOf(card) || "Technology"));
  if (!card.seed) top.append(element(document, "span", "curiosity-fresh", "Fresh"));
  const date = curiosityDate(card);
  if (date) {
    const time = element(document, "time", "curiosity-year", date.label);
    time.dateTime = date.iso;
    top.append(time);
  }
  article.append(top);

  const meta = element(document, "div", "curiosity-card-meta");
  if (CURIOSITY_FORMATS[card.format]) meta.append(element(document, "span", "curiosity-format", CURIOSITY_FORMATS[card.format]));
  if (CURIOSITY_THEMES[themes[0]]) meta.append(element(document, "span", "curiosity-theme", CURIOSITY_THEMES[themes[0]]));
  if (CURIOSITY_LEVELS[card.level]) meta.append(element(document, "span", `curiosity-level curiosity-level-${card.level}`, CURIOSITY_LEVELS[card.level]));
  const problem = cardProblems(card).find((id) => CURIOSITY_PROBLEMS[id]);
  if (problem) meta.append(element(document, "span", "curiosity-problem", CURIOSITY_PROBLEMS[problem]));
  if (meta.childElementCount) article.append(meta);

  article.append(element(document, "h3", "curiosity-card-title", card.title));
  if (typeof card.question === "string" && card.question.trim()) {
    const question = element(document, "p", "curiosity-question");
    question.append(element(document, "span", "", "Answers "), document.createTextNode(card.question.trim()));
    article.append(question);
  }
  const byline = [card.author, card.publisher_detail || card.publisher].filter(Boolean).join(" · ");
  if (byline) article.append(element(document, "p", "curiosity-byline", byline));
  const basis = card.summary_basis === "ai_feed_summary" ? "AI summary from the publisher excerpt" :
    card.summary_basis === "editorial_source_summary" ? "Curated source summary" :
    card.summary_basis === "publisher_excerpt" ? "Publisher excerpt summary" : "Source summary";
  article.append(element(document, "span", "curiosity-summary-basis", basis));
  article.append(element(document, "p", "curiosity-summary", card.summary || card.description ||
    "Open the original source for the publisher’s technical context."));
  // Reviewed cards say what went wrong, what the team did and how it turned out, in one line each.
  const steps = card.breakdown && typeof card.breakdown === "object" ? card.breakdown : null;
  if (steps && ["problem", "approach", "result"].every((key) => typeof steps[key] === "string" && steps[key].trim())) {
    const list = element(document, "dl", "curiosity-breakdown");
    for (const [key, label] of [["problem", "The problem"], ["approach", "What they did"], ["result", "The result"]]) {
      const row = element(document, "div", `curiosity-breakdown-row curiosity-breakdown-${key}`);
      row.append(element(document, "dt", "", label), element(document, "dd", "", steps[key].trim()));
      list.append(row);
    }
    article.append(list);
  }
  if (typeof card.why_read === "string" && card.why_read.trim()) {
    const why = element(document, "p", "curiosity-why");
    why.append(element(document, "strong", "", "Why read it "), document.createTextNode(card.why_read.trim()));
    article.append(why);
  }

  // Reviewed cards suggest what to read next: the next stop on a reading list, then the closest match.
  const related = (Array.isArray(card.related) ? card.related : [])
    .filter((item) => item && typeof item.title === "string" && sourceHref(item.url)).slice(0, 2);
  if (related.length) {
    const next = element(document, "div", "curiosity-related");
    next.append(element(document, "p", "curiosity-related-label", "Read next"));
    const items = element(document, "ul", "curiosity-related-list");
    for (const item of related) {
      const entry = element(document, "li");
      const link = element(document, "a", "curiosity-related-link", item.title);
      link.href = sourceHref(item.url);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      if (item.company) link.setAttribute("aria-label", `${item.title}, ${item.company} (opens the original source)`);
      entry.append(link);
      if (item.company) entry.append(element(document, "span", "curiosity-related-company", ` · ${item.company}`));
      items.append(entry);
    }
    next.append(items);
    article.append(next);
  }

  // Named technologies first, then the reviewed topic tags, without repeating a label.
  const seen = new Set();
  const labels = [...(Array.isArray(card.technologies) ? card.technologies : []), ...(Array.isArray(card.tags) ? card.tags : [])]
    .map(String).filter((label) => label && !seen.has(label.toLowerCase()) && seen.add(label.toLowerCase()));
  const tags = element(document, "ul", "curiosity-tags");
  tags.setAttribute("aria-label", "Technologies and topics");
  for (const [index, tag] of labels.slice(0, 6).entries()) {
    const item = element(document, "li", "curiosity-tag", tag);
    if (index < (card.technologies?.length || 0)) item.classList.add("curiosity-tech");
    tags.append(item);
  }
  if (tags.childElementCount) article.append(tags);

  const footer = element(document, "div", "curiosity-card-footer");
  const minutes = Number.isInteger(card.read_minutes) && card.read_minutes > 0 ? card.read_minutes : 8;
  footer.append(element(document, "span", "curiosity-reading-time", `${minutes} min read`));
  const link = element(document, "a", "curiosity-link", `Read at ${card.publisher || "original source"} ↗`);
  const href = sourceHref(card.url);
  if (href) link.href = href;
  else link.setAttribute("aria-disabled", "true");
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  footer.append(link);
  article.append(footer);

  if (options.actions === false) return article;
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
  return article;
}

export function renderCuriosityCards(container, cards, options = {}) {
  const document = container.ownerDocument;
  const pinnedIds = new Set(options.pinnedIds || []);
  const scheduledIds = new Set(options.scheduledIds || []);
  const list = element(document, "div", "curiosity-grid");
  const all = Array.isArray(cards) ? cards.slice(0, MAX_CURIOSITY_CARDS) : [];
  const filter = options.filter || {};
  const eligible = filterCuriosityCards(all, filter);
  const visibleCount = Math.max(1, Math.min(eligible.length, Number(options.visibleCount) || eligible.length));
  const filters = all.length > 1 && options.filters !== false ? [renderFilters(document, all, filter, options.onFilter)] : [];

  if (!all.length) {
    const empty = element(document, "p", "curiosity-empty", options.message ||
      "No Curiosity Cards are available right now. The collection will update with the next content sync.");
    container.replaceChildren(empty);
    return;
  }
  if (!eligible.length) {
    container.replaceChildren(...filters,
      element(document, "p", "curiosity-empty", options.emptyMessage || "No Curiosity Cards match this filter."));
    return;
  }

  for (const card of eligible.slice(0, visibleCount)) {
    if (!card || typeof card.id !== "string" || typeof card.title !== "string") continue;
    list.append(renderCard(document, card, options, pinnedIds, scheduledIds));
  }

  if (!list.childElementCount) {
    container.replaceChildren(...filters,
      element(document, "p", "curiosity-empty", "No Curiosity Cards are available right now."));
    return;
  }
  const content = [...filters, list];
  if (visibleCount < eligible.length) {
    const step = Math.max(1, Number(options.step) || 4);
    const more = element(document, "button", "text-button curiosity-show-more",
      `Show ${Math.min(step, eligible.length - visibleCount)} more Curiosity Cards`);
    more.type = "button";
    more.dataset.curiosityShowMore = "";
    more.addEventListener("click", () => options.onShowMore?.());
    content.push(more);
  }
  container.replaceChildren(...content);
}
