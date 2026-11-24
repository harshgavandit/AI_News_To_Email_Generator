import { CURIOSITY_FORMATS, CURIOSITY_LEVELS, CURIOSITY_PROBLEMS, CURIOSITY_THEMES, cardThemes, curiosityCardsQuery,
  popularSearches, renderCuriosityCards } from "./curiosity.js";

import { mountConstellation, themeGraphFromFacets } from "./curiosity-constellation.js";
import { bindCardTracking, track } from "./curiosity-events.js";
import { shareCard, shareMessage } from "./curiosity-share.js";

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

export function renderReadingLists(grid, collections, onOpen, { action = "Read the list" } = {}) {
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
    const count = Number.isInteger(list.card_count) ? list.card_count : Array.isArray(list.cards) ? list.cards.length : 0;
    const companies = Array.isArray(list.companies) ? list.companies.slice(0, 4).join(", ") : "";
    item.append(make("p", "curiosity-list-meta",
      [`${count} ${count === 1 ? "story" : "stories"}`, Number(list.read_minutes) > 0 ? `${list.read_minutes} min` : "", companies]
        .filter(Boolean).join(" · ")));
    const actions = make("div", "curiosity-list-actions");
    const open = make("button", "button secondary", action);
    open.type = "button";
    open.setAttribute("aria-label", `${action}: ${list.title}`);
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
  // cards: the pages loaded so far for the current filters; facets count the whole collection.
  const state = { ...readCuriosityState(location.search), cards: [], total: 0, nextCursor: null, facets: null,
    collections: [], loading: false, failed: false };
  let controller = null;
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
  const lessons = byId("curiosity-lessons");
  const lessonGrid = byId("curiosity-lesson-grid");
  const suggestions = byId("curiosity-suggestions");
  const controls = byId("curiosity-controls");
  let constellation = null;

  function persist() {
    history.replaceState(null, "", `${location.pathname}${writeCuriosityState(state)}`);
  }

  function renderThemes() {
    const counts = new Map(Object.entries(state.facets?.themes || {}).map(([id, count]) => [id, Number(count)]));
    const entries = [["all", "All stories", Number(state.facets?.total) || 0],
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
        void refresh();
        themes.querySelector(`[data-theme="${id}"]`)?.focus();
      });
      return button;
    }));
  }

  function openList(id) {
    state.list = id;
    const list = state.collections.find((item) => item.id === id);
    if (list) track(list.kind === "lesson" ? "lesson_open" : "list_open", { listId: id, surface: "collection" });
    update();
    byId("curiosity-browser")?.scrollIntoView?.({ block: "start" });
    byId("curiosity-list-clear")?.focus({ preventScroll: true });
    return loadListCards(id);
  }

  // A list's cards load the first time it is opened, then stay in memory for this visit.
  async function loadListCards(id) {
    const list = state.collections.find((item) => item.id === id);
    if (!list || Array.isArray(list.cards) || list.loading) return;
    list.loading = true;
    list.failed = false;
    update();
    try {
      const response = await fetcher(`/api/curiosity/collections/${encodeURIComponent(id)}`, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      list.cards = Array.isArray(payload?.list?.cards) ? payload.list.cards : [];
    } catch {
      list.failed = true;
    } finally {
      list.loading = false;
    }
    if (state.list === id) update();
  }

  function update() {
    persist();
    const list = state.collections.find((item) => item.id === state.list);
    banner.hidden = !list;
    themes.hidden = controls.hidden = Boolean(list);
    if (suggestions) suggestions.hidden = Boolean(list) || !suggestions.childElementCount;
    if (list) {
      // A reading list or lesson is shown whole and in order; theme and filter controls step aside.
      byId("curiosity-list-kind").textContent = list.kind === "lesson" ? "Lesson" : "Reading list";
      byId("curiosity-list-name").textContent = list.title;
      byId("curiosity-list-brief").href = `/?brief-list=${encodeURIComponent(list.id)}#composer`;
      if (!Array.isArray(list.cards)) {
        collection.setAttribute("aria-busy", String(Boolean(list.loading)));
        status.textContent = list.failed ? "" : `Loading ${number.format(list.card_count || 0)} stories…`;
        if (list.failed) {
          const message = document.createElement("p");
          message.className = "curiosity-empty";
          message.textContent = "This list could not load. Check your connection and try again.";
          const retry = document.createElement("button");
          retry.type = "button";
          retry.className = "button secondary";
          retry.textContent = "Try again";
          retry.addEventListener("click", () => void loadListCards(list.id));
          collection.replaceChildren(message, retry);
        } else {
          const message = document.createElement("p");
          message.className = "curiosity-empty";
          message.textContent = "Loading the stories in this list…";
          collection.replaceChildren(message);
        }
        return;
      }
      collection.setAttribute("aria-busy", "false");
      status.textContent = `${number.format(list.cards.length)} stories in reading order`;
      renderCuriosityCards(collection, list.cards, { filters: false, actions: false, step: PAGE, visibleCount: list.cards.length, onShare });
      return;
    }
    renderThemes();
    constellation?.setActive(state.theme);
    status.textContent = state.failed ? "" : state.facets
      ? `${number.format(state.total)} ${state.total === 1 ? "story" : "stories"}${state.theme !== "all" ? ` in ${CURIOSITY_THEMES[state.theme]}` : ""}${state.problem !== "all" ? ` about ${CURIOSITY_PROBLEMS[state.problem].toLocaleLowerCase()}` : ""}`
      : "";
    if (state.failed) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "button secondary";
      retry.textContent = "Try again";
      retry.addEventListener("click", () => void refresh());
      const message = document.createElement("p");
      message.className = "curiosity-empty";
      message.textContent = "Curiosity Cards could not load. Check your connection and try again.";
      collection.replaceChildren(message, retry);
      return;
    }
    if (!state.facets) return;
    renderCuriosityCards(collection, state.cards, {
      prefiltered: true, facets: state.facets, total: state.total, filters: false, actions: false, step: PAGE, onShare,
      visibleCount: state.cards.length, loadingMore: state.loading && state.cards.length > 0,
      emptyMessage: "No stories match. Try another theme or a broader search.",
      onShowMore: () => {
        const first = state.cards.length;
        void loadPage({ append: true }).then(() => collection.querySelectorAll("article")[first]?.querySelector("a")?.focus());
      },
    });
  }

  function renderPopular(cards) {
    const section = byId("curiosity-popular");
    const list = byId("curiosity-popular-list");
    if (!section || !list) return;
    const items = cards.filter((card) => card && typeof card.id === "string" && typeof card.title === "string").slice(0, 6);
    list.replaceChildren(...items.map((card) => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = `/cards/${encodeURIComponent(card.id)}`;
      link.textContent = card.title;
      item.append(link);
      if (card.company) {
        const company = document.createElement("span");
        company.className = "curiosity-popular-company";
        company.textContent = ` · ${card.company}`;
        item.append(company);
      }
      return item;
    }));
    section.hidden = !items.length;
  }

  async function onShare(card) {
    status.textContent = shareMessage(await shareCard(card));
  }

  function currentFilter() {
    return { theme: state.theme, problem: state.problem, format: state.format, level: state.level, company: state.company,
      sort: state.sort, query: state.query };
  }

  // Load the first page for the current filters, or the next page. A newer request cancels an older one.
  async function loadPage({ append = false, retried = false } = {}) {
    if (append && !state.nextCursor) return;
    controller?.abort();
    const ownController = new AbortController();
    controller = ownController;
    state.loading = true;
    state.failed = false;
    collection.setAttribute("aria-busy", "true");
    if (append) update();
    const url = `/api/curiosity/cards?${curiosityCardsQuery(currentFilter(), { limit: PAGE, cursor: append ? state.nextCursor : "" })}`;
    try {
      const response = await fetcher(url, { headers: { Accept: "application/json" }, signal: ownController.signal });
      if (response.status === 409 && !retried) {
        // The collection was rebuilt since this page link was issued: start again from the first page.
        state.cards = [];
        state.nextCursor = null;
        return loadPage({ retried: true });
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (controller !== ownController) return undefined;
      for (const [id, label] of Object.entries(payload.labels?.themes || {})) CURIOSITY_THEMES[id] ??= label;
      for (const [id, label] of Object.entries(payload.labels?.problems || {})) CURIOSITY_PROBLEMS[id] ??= label;
      const page = Array.isArray(payload.cards) ? payload.cards : [];
      const seen = new Set(append ? state.cards.map((card) => card.id) : []);
      state.cards = append ? [...state.cards, ...page.filter((card) => card && !seen.has(card.id))] : page;
      state.total = Number(payload.total) || state.cards.length;
      state.nextCursor = typeof payload.next_cursor === "string" ? payload.next_cursor : null;
      const firstFacets = !state.facets;
      state.facets = payload.facets || state.facets;
      if (firstFacets) setupFacets();
    } catch (error) {
      if (error?.name === "AbortError" || controller !== ownController) return undefined;
      state.failed = !append || !state.cards.length;
      if (append) status.textContent = "More stories could not load. Try again.";
    } finally {
      if (controller === ownController) {
        state.loading = false;
        collection.setAttribute("aria-busy", "false");
      }
    }
    if (controller === ownController) update();
    return undefined;
  }

  function refresh() {
    state.cards = [];
    state.nextCursor = null;
    persist();
    return loadPage();
  }

  // Selects, stats, suggestions and the constellation come from whole-collection facets, built once.
  function setupFacets() {
    const facets = state.facets;
    fill(problem, Object.entries(CURIOSITY_PROBLEMS).filter(([id]) => facets.problems?.[id]), state.problem);
    fill(format, Object.entries(CURIOSITY_FORMATS).filter(([id]) => facets.formats?.[id]), state.format);
    fill(level, Object.entries(CURIOSITY_LEVELS).filter(([id]) => facets.levels?.[id]), state.level);
    const names = (facets.companies || []).map((entry) => (Array.isArray(entry) ? entry[0] : entry)).filter((name) => typeof name === "string");
    fill(company, names.map((name) => [name, name]), state.company);
    state.problem = problem.value;
    state.format = format.value;
    state.level = level.value;
    state.company = company.value;
    byId("curiosity-stat-cards").textContent = number.format(Number(facets.total) || 0);
    byId("curiosity-stat-companies").textContent = number.format(names.length);
    byId("curiosity-stat-fresh").textContent = number.format(Number(facets.fresh) || 0);
    byId("curiosity-stat-fresh").parentElement.hidden = !Number(facets.fresh);
    if (suggestions) {
      const popular = Array.isArray(facets.technologies) ? facets.technologies.filter((label) => typeof label === "string").slice(0, 8)
        : popularSearches(state.cards);
      suggestions.replaceChildren(...popular.map((label) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "curiosity-chip";
        chip.textContent = label;
        chip.setAttribute("aria-label", `Search for ${label}`);
        chip.addEventListener("click", () => {
          query.value = state.query = label;
          void refresh();
        });
        return chip;
      }));
      suggestions.hidden = !suggestions.childElementCount;
    }
    if (sky && !constellation && globalThis.matchMedia?.("(min-width: 900px)").matches) {
      sky.parentElement.hidden = false;  // Measure the real size before the first layout.
      constellation = mountConstellation(sky, themeGraphFromFacets(facets, CURIOSITY_THEMES), {
        motion: globalThis.informaMotion,
        onSelect: (id) => themes.querySelector(`[data-theme="${state.theme === id ? "all" : id}"]`)?.click(),
      });
      sky.parentElement.hidden = !constellation;
    }
  }

  bindCardTracking(collection, "collection");
  query.value = state.query;
  sort.value = state.sort;
  let typing;
  query.addEventListener("input", () => {
    clearTimeout(typing);
    // Debounced: the server searches the whole collection, so wait until typing pauses.
    typing = setTimeout(() => {
      const next = query.value.trim().slice(0, 80);
      if (next === state.query) return;
      state.query = next;
      void refresh();
    }, 250);
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
      const usable = (items) => (Array.isArray(items) ? items : [])
        .filter((list) => list && typeof list.id === "string"
          && (Number(list.card_count) > 0 || (Array.isArray(list.cards) && list.cards.length > 0)));
      const readingLists = usable(payload?.collections);
      const lessonLists = usable(payload?.lessons).map((list) => ({ ...list, kind: "lesson" }));
      state.collections = [...readingLists, ...lessonLists];
      renderReadingLists(listGrid, readingLists, openList);
      lists.hidden = !readingLists.length;
      if (lessons && lessonGrid) {
        renderReadingLists(lessonGrid, lessonLists, openList, { action: "See the stories" });
        lessons.hidden = !lessonLists.length;
      }
      // A shared ?list= link opens as soon as the index arrives, without waiting for the whole collection.
      if (state.list && state.collections.some((item) => item.id === state.list)) {
        update();
        return loadListCards(state.list);
      }
      return undefined;
    })
    .catch(() => { state.collections = []; });
  for (const [select, key] of [[problem, "problem"], [format, "format"], [level, "level"], [company, "company"], [sort, "sort"]]) {
    select.addEventListener("change", () => {
      state[key] = select.value;
      void refresh();
    });
  }

  // Most-opened cards, shown only once enough readers have shared anonymous counts.
  const popularLoaded = Promise.resolve()
    .then(() => fetcher("/api/curiosity/popular", { headers: { Accept: "application/json" } }))
    .then((response) => (response?.ok ? response.json() : { cards: [] }))
    .then((payload) => renderPopular(Array.isArray(payload?.cards) ? payload.cards : []))
    .catch(() => renderPopular([]));
  const collectionLoaded = loadPage();
  return Promise.all([collectionLoaded, listsLoaded, popularLoaded]).then(() => {
    if (state.list && !state.collections.some((item) => item.id === state.list)) state.list = "";
    update();
  });
}

if (typeof window !== "undefined" && window.document?.getElementById("curiosity-collection")) startCuriosityPage();
