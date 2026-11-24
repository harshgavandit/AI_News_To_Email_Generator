import { CURIOSITY_FORMATS, CURIOSITY_LEVELS, CURIOSITY_PROBLEMS, CURIOSITY_THEMES, MAX_CURIOSITY_CARDS, cardProblems,
  cardThemes, curiosityCompanies, filterCuriosityCards, renderCuriosityCards } from "./curiosity.js";

import { mountConstellation, themeGraph } from "./curiosity-constellation.js";

const PAGE = 24;
const byId = (id) => document.getElementById(id);
const number = new Intl.NumberFormat("en-US");

export function readCuriosityState(search) {
  const params = new URLSearchParams(search);
  const pick = (key, allowed) => (allowed.includes(params.get(key)) ? params.get(key) : "all");
  return {
    theme: pick("theme", Object.keys(CURIOSITY_THEMES)),
    format: pick("format", Object.keys(CURIOSITY_FORMATS)),
    level: pick("level", Object.keys(CURIOSITY_LEVELS)),
    problem: pick("problem", Object.keys(CURIOSITY_PROBLEMS)),
    company: (params.get("company") || "all").slice(0, 80),
    sort: params.get("sort") === "newest" ? "newest" : "featured",
    query: (params.get("q") || "").slice(0, 80),
    list: /^[a-z0-9-]{1,80}$/.test(params.get("list") || "") ? params.get("list") : "",
  };
}

export function writeCuriosityState(state) {
  const params = new URLSearchParams();
  for (const key of ["theme", "problem", "format", "level", "company"]) if (state[key] && state[key] !== "all") params.set(key, state[key]);
  if (state.sort === "newest") params.set("sort", "newest");
  if (state.query) params.set("q", state.query);
  if (state.list) params.set("list", state.list);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function renderReadingLists(grid, collections, onOpen) {
  const doc = grid.ownerDocument;
  const make = (tag, className, text) => {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  grid.replaceChildren(...collections.map((list) => {
    const item = make("article", "curiosity-list-card");
    item.dataset.list = list.id;
    item.append(make("h3", "", list.title), make("p", "curiosity-list-summary", list.summary));
    const count = Array.isArray(list.cards) ? list.cards.length : 0;
    const companies = Array.isArray(list.companies) ? list.companies.slice(0, 4).join(", ") : "";
    item.append(make("p", "curiosity-list-meta",
      [`${count} ${count === 1 ? "story" : "stories"}`, Number(list.read_minutes) > 0 ? `${list.read_minutes} min` : "", companies]
        .filter(Boolean).join(" · ")));
    const actions = make("div", "curiosity-list-actions");
    const open = make("button", "button secondary", "Read the list");
    open.type = "button";
    open.setAttribute("aria-label", `Read the list: ${list.title}`);
    open.addEventListener("click", () => onOpen(list.id));
    const brief = make("a", "text-button curiosity-list-brief", "Add all to a brief");
    brief.href = `/?brief-list=${encodeURIComponent(list.id)}#composer`;
    brief.setAttribute("aria-label", `Add all ${count} stories in ${list.title} to a brief`);
    actions.append(open, brief);
    item.append(actions);
    return item;
  }));
}

export function themeCounts(cards) {
  const counts = new Map();
  for (const card of cards) for (const theme of cardThemes(card)) counts.set(theme, (counts.get(theme) || 0) + 1);
  return counts;
}

function fill(select, entries, value) {
  const first = select.options[0];
  select.replaceChildren(first, ...entries.map(([id, label]) => new Option(label, id)));
  select.value = entries.some(([id]) => id === value) ? value : "all";
}

export function startCuriosityPage({ fetcher = fetch, history = window.history, location = window.location } = {}) {
  const state = { ...readCuriosityState(location.search), cards: [], collections: [], visible: PAGE };
  const collection = byId("curiosity-collection");
  const themes = byId("curiosity-themes");
  const query = byId("curiosity-query");
  const format = byId("curiosity-format");
  const level = byId("curiosity-level");
  const problem = byId("curiosity-problem");
  const company = byId("curiosity-company");
  const sort = byId("curiosity-sort");
  const status = byId("curiosity-result-status");
  const sky = byId("curiosity-constellation");
  const lists = byId("curiosity-lists");
  const listGrid = byId("curiosity-list-grid");
  const banner = byId("curiosity-list-banner");
  const controls = byId("curiosity-controls");
  let constellation = null;

  function persist() {
    history.replaceState(null, "", `${location.pathname}${writeCuriosityState(state)}`);
  }

  function renderThemes() {
    const counts = themeCounts(state.cards);
    const entries = [["all", "All stories", state.cards.length],
      ...Object.entries(CURIOSITY_THEMES).filter(([id]) => counts.get(id)).map(([id, label]) => [id, label, counts.get(id)])];
    themes.replaceChildren(...entries.map(([id, label, count]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "curiosity-theme-tab";
      button.dataset.theme = id;
      button.setAttribute("aria-pressed", String(state.theme === id));
      const name = document.createElement("span");
      name.textContent = label;
      const total = document.createElement("span");
      total.className = "curiosity-theme-count";
      total.textContent = number.format(count);
      button.append(name, total);
      button.addEventListener("click", () => {
        state.theme = id;
        state.visible = PAGE;
        update();
        themes.querySelector(`[data-theme="${id}"]`)?.focus();
      });
      return button;
    }));
  }

  function openList(id) {
    state.list = id;
    state.visible = PAGE;
    update();
    byId("curiosity-browser")?.scrollIntoView?.({ block: "start" });
    byId("curiosity-list-clear")?.focus({ preventScroll: true });
  }

  function update() {
    persist();
    const list = state.collections.find((item) => item.id === state.list);
    banner.hidden = !list;
    themes.hidden = controls.hidden = Boolean(list);
    if (list) {
      // A reading list is shown whole and in reading order; theme and filter controls step aside.
      byId("curiosity-list-name").textContent = list.title;
      byId("curiosity-list-brief").href = `/?brief-list=${encodeURIComponent(list.id)}#composer`;
      status.textContent = `${number.format(list.cards.length)} stories in reading order`;
      renderCuriosityCards(collection, list.cards, { filters: false, actions: false, step: PAGE, visibleCount: list.cards.length });
      return;
    }
    renderThemes();
    constellation?.setActive(state.theme);
    const filter = { theme: state.theme, problem: state.problem, format: state.format, level: state.level, company: state.company,
      sort: state.sort, query: state.query };
    const matches = filterCuriosityCards(state.cards, filter);
    status.textContent = state.cards.length
      ? `${number.format(matches.length)} ${matches.length === 1 ? "story" : "stories"}${state.theme !== "all" ? ` in ${CURIOSITY_THEMES[state.theme]}` : ""}${state.problem !== "all" ? ` about ${CURIOSITY_PROBLEMS[state.problem].toLocaleLowerCase()}` : ""}`
      : "";
    renderCuriosityCards(collection, state.cards, {
      filter, filters: false, actions: false, step: PAGE, visibleCount: state.visible,
      emptyMessage: "No stories match. Try another theme or a broader search.",
      onShowMore: () => {
        const first = state.visible;
        state.visible += PAGE;
        update();
        collection.querySelectorAll("article")[first]?.querySelector("a")?.focus();
      },
    });
  }

  query.value = state.query;
  sort.value = state.sort;
  let typing;
  query.addEventListener("input", () => {
    clearTimeout(typing);
    typing = setTimeout(() => {
      state.query = query.value.trim().slice(0, 80);
      state.visible = PAGE;
      update();
    }, 150);
  });
  byId("curiosity-controls").addEventListener("submit", (event) => event.preventDefault());
  byId("curiosity-list-clear").addEventListener("click", () => {
    const id = state.list;
    state.list = "";
    update();
    listGrid.querySelector(`[data-list="${id}"] button`)?.focus();
  });
  // Reading lists load alongside the collection; the page works without them.
  const listsLoaded = Promise.resolve()
    .then(() => fetcher("/api/curiosity/collections", { headers: { Accept: "application/json" } }))
    .then((response) => (response?.ok ? response.json() : { collections: [] }))
    .then((payload) => {
      state.collections = (Array.isArray(payload?.collections) ? payload.collections : [])
        .filter((list) => list && typeof list.id === "string" && Array.isArray(list.cards) && list.cards.length);
      renderReadingLists(listGrid, state.collections, openList);
      lists.hidden = !state.collections.length;
    })
    .catch(() => { state.collections = []; });
  for (const [select, key] of [[problem, "problem"], [format, "format"], [level, "level"], [company, "company"], [sort, "sort"]]) {
    select.addEventListener("change", () => {
      state[key] = select.value;
      state.visible = PAGE;
      update();
    });
  }

  const collectionLoaded = fetcher(`/api/curiosity?limit=${MAX_CURIOSITY_CARDS}`, { headers: { Accept: "application/json" } })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((payload) => {
      state.cards = Array.isArray(payload.cards) ? payload.cards : [];
      for (const item of payload.themes || []) if (item?.id && item?.label) CURIOSITY_THEMES[item.id] ??= item.label;
      for (const item of payload.problems || []) if (item?.id && item?.label) CURIOSITY_PROBLEMS[item.id] ??= item.label;
      const problems = new Set(state.cards.flatMap(cardProblems));
      fill(problem, Object.entries(CURIOSITY_PROBLEMS).filter(([id]) => problems.has(id)), state.problem);
      state.problem = problem.value;
      fill(format, Object.entries(CURIOSITY_FORMATS).filter(([id]) => state.cards.some((card) => card.format === id)), state.format);
      fill(company, curiosityCompanies(state.cards).map((name) => [name, name]), state.company);
      fill(level, Object.entries(CURIOSITY_LEVELS).filter(([id]) => state.cards.some((card) => card.level === id)), state.level);
      state.format = format.value;
      state.level = level.value;
      state.company = company.value;
      byId("curiosity-stat-cards").textContent = number.format(state.cards.length);
      byId("curiosity-stat-companies").textContent = number.format(curiosityCompanies(state.cards).length);
      const fresh = state.cards.filter((card) => !card.seed).length;
      byId("curiosity-stat-fresh").textContent = number.format(fresh);
      byId("curiosity-stat-fresh").parentElement.hidden = !fresh;
      collection.setAttribute("aria-busy", "false");
      if (sky && globalThis.matchMedia?.("(min-width: 900px)").matches) {
        sky.parentElement.hidden = false;  // Measure the real size before the first layout.
        constellation = mountConstellation(sky, themeGraph(state.cards, CURIOSITY_THEMES), {
          motion: globalThis.informaMotion,
          onSelect: (id) => themes.querySelector(`[data-theme="${state.theme === id ? "all" : id}"]`)?.click(),
        });
        sky.parentElement.hidden = !constellation;
      }
    })
    .catch(() => {
      state.failed = true;
      collection.setAttribute("aria-busy", "false");
      renderCuriosityCards(collection, [], { message: "Curiosity Cards could not load. Refresh the page to try again." });
    });
  return Promise.all([collectionLoaded, listsLoaded]).then(() => {
    if (state.list && !state.collections.some((item) => item.id === state.list)) state.list = "";
    if (!state.failed || state.list) update();
  });
}

if (typeof window !== "undefined" && window.document?.getElementById("curiosity-collection")) startCuriosityPage();
