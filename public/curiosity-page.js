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
  };
}

export function writeCuriosityState(state) {
  const params = new URLSearchParams();
  for (const key of ["theme", "problem", "format", "level", "company"]) if (state[key] && state[key] !== "all") params.set(key, state[key]);
  if (state.sort === "newest") params.set("sort", "newest");
  if (state.query) params.set("q", state.query);
  const text = params.toString();
  return text ? `?${text}` : "";
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
  const state = { ...readCuriosityState(location.search), cards: [], visible: PAGE };
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

  function update() {
    persist();
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
  for (const [select, key] of [[problem, "problem"], [format, "format"], [level, "level"], [company, "company"], [sort, "sort"]]) {
    select.addEventListener("change", () => {
      state[key] = select.value;
      state.visible = PAGE;
      update();
    });
  }

  return fetcher(`/api/curiosity?limit=${MAX_CURIOSITY_CARDS}`, { headers: { Accept: "application/json" } })
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
      update();
    })
    .catch(() => {
      collection.setAttribute("aria-busy", "false");
      renderCuriosityCards(collection, [], { message: "Curiosity Cards could not load. Refresh the page to try again." });
    });
}

if (typeof window !== "undefined" && window.document?.getElementById("curiosity-collection")) startCuriosityPage();
