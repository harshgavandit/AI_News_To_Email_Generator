const KEY = "informa-interests-v1";
const limits = { topics: 10, subjects: 12, sources: 50, authors: 30 };
const valid = (key, value) => typeof value === "string" && (key === "authors" ? /^author-[a-f0-9]{32}$/ : /^[a-z0-9-]{1,64}$/).test(value);

export function createPreferences(container, onChange) {
  let preferences = Object.fromEntries(Object.keys(limits).map((key) => [key, []]));
  let useSaved = false;
  const authorLabels = {};
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) || "null");
    useSaved = stored?.useSaved === true;
    for (const key of Object.keys(limits)) if (Array.isArray(stored?.[key]))
      preferences[key] = [...new Set(stored[key].filter((value) => valid(key, value)))].slice(0, limits[key]);
    for (const key of preferences.authors) if (typeof stored?.authorLabels?.[key] === "string")
      authorLabels[key] = stored.authorLabels[key].slice(0, 180);
  } catch { /* Session preferences remain available if storage is disabled. */ }
  const form = container.querySelector("form");
  const savedOption = form.elements.namedItem("use-saved-stories");
  if (savedOption) savedOption.checked = useSaved;
  const feedback = container.querySelector("[role=status]");
  let catalog = { topics: {}, subjects: {}, sources: {}, authors: { ...authorLabels } };
  const draft = () => Object.fromEntries(Object.keys(limits).map((key) => [key,
    [...form.querySelectorAll(`input[name="${key}"]:checked`)].map((input) => input.value)]));

  function filterOptions() {
    for (const input of container.querySelectorAll("[data-search-preferences]")) {
      const key = input.dataset.searchPreferences;
      const search = input.value.trim().toLocaleLowerCase();
      for (const label of form.querySelector(`[data-preferences="${key}"]`).children)
        label.hidden = Boolean(search && !label.textContent.toLocaleLowerCase().includes(search));
    }
  }

  function render(selected = preferences) {
    for (const [key, entries] of Object.entries(catalog)) {
      const field = form.querySelector(`[data-preferences="${key}"]`);
      if (!field) continue;
      field.replaceChildren(...Object.entries(entries).map(([value, text]) => {
        const label = document.createElement("label"), input = document.createElement("input");
        input.type = "checkbox";
        input.name = key;
        input.value = value;
        input.checked = selected[key].includes(value);
        label.append(input, document.createTextNode(text));
        return label;
      }));
    }
    filterOptions();
  }

  function update(data) {
    const selected = draft();
    for (const key of Object.keys(limits)) if (!form.querySelector(`input[name="${key}"]`)) selected[key] = preferences[key];
    const sources = {};
    for (const source of data.sources || []) {
      if (!source.enabled) continue;
      if (source.id !== source.source && !sources[source.source]) sources[source.source] =
        `${source.source === "medium" ? "Medium" : source.source === "dev" ? "DEV Community" : source.source === "hashnode" ? "Hashnode" : source.label} · all reviewed feeds`;
      sources[source.id] = source.label;
    }
    for (const author of data.authors || []) if (valid("authors", author.id))
      catalog.authors[author.id] = `${author.name} · ${author.publisher || author.source}`;
    for (const article of data.articles || []) if (valid("authors", article.author_key))
      catalog.authors[article.author_key] = `${article.author} · ${article.publisher}`;
    catalog = { topics: data.topics || catalog.topics, subjects: data.subjects || catalog.subjects,
      sources: Object.keys(sources).length ? sources : catalog.sources, authors: catalog.authors };
    render(selected);
  }

  function persist(message) {
    for (const key of preferences.authors) authorLabels[key] = catalog.authors[key] || authorLabels[key] || "Followed author";
    const labels = Object.fromEntries(preferences.authors.map((key) => [key, authorLabels[key]]));
    try {
      localStorage.setItem(KEY, JSON.stringify({ ...preferences, authorLabels: labels, useSaved }));
      feedback.textContent = message + " Saved in this browser.";
    } catch { feedback.textContent = message + " Applied for this session; browser storage is unavailable."; }
    onChange();
  }

  function toggle(key, value, label) {
    if (!valid(key, value)) return "This record does not identify a followable author or publication.";
    const following = preferences[key].includes(value);
    if (!following && preferences[key].length >= limits[key]) return `You can follow up to ${limits[key]} ${key}.`;
    if (following) preferences[key] = preferences[key].filter((item) => item !== value);
    else preferences[key].push(value);
    catalog[key][value] = label;
    render();
    const message = following ? "Removed from your followed list." : "Added to your followed list.";
    persist(message);
    return message;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const selected = draft();
    for (const key of Object.keys(limits)) if (selected[key].length > limits[key]) {
      feedback.textContent = `Choose up to ${limits[key]} ${key}.`;
      return;
    }
    preferences = selected;
    useSaved = savedOption?.checked === true;
    persist("Preferences updated.");
  });
  for (const input of container.querySelectorAll("[data-search-preferences]")) input.addEventListener("input", filterOptions);
  container.querySelector("[data-clear-preferences]").addEventListener("click", () => {
    preferences = Object.fromEntries(Object.keys(limits).map((key) => [key, []]));
    useSaved = false;
    if (savedOption) savedOption.checked = false;
    render();
    persist("Interests and followed lists reset.");
  });
  return { update, request() { return Object.fromEntries(Object.keys(limits).map((key) => [key,
    key === "authors" ? [...preferences[key]] : preferences[key].filter((id) => Object.hasOwn(catalog[key], id))])); },
    usesSavedStories() { return useSaved; },
    follows(key, value) { return preferences[key]?.includes(value) || false; },
    toggleAuthor(article) { return toggle("authors", article.author_key, `${article.author} · ${article.publisher}`); },
    togglePublication(article) { return toggle("sources", article.source_id || article.source, article.publisher); },
  };
}
