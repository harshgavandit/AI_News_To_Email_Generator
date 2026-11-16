const KEY = "informa-interests-v1";
const limits = { topics: 10, subjects: 12, sources: 20 };

export function createPreferences(container, onChange) {
  let preferences = { topics: [], subjects: [], sources: [] };
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) || "null");
    for (const key of Object.keys(limits)) {
      if (Array.isArray(stored?.[key])) preferences[key] = [...new Set(stored[key]
        .filter((value) => typeof value === "string" && /^[a-z0-9-]{1,64}$/.test(value)))].slice(0, limits[key]);
    }
  } catch { /* Private browsing can disable storage. */ }
  const form = container.querySelector("form");
  const feedback = container.querySelector("[role=status]");
  let catalog = { topics: {}, subjects: {}, sources: {} };
  const draft = () => Object.fromEntries(Object.keys(limits).map((key) => [key,
    [...form.querySelectorAll(`input[name="${key}"]:checked`)].map((input) => input.value)]));

  function update(data) {
    const sources = {};
    for (const source of data.sources || []) {
      if (source.enabled && !sources[source.source]) sources[source.source] = source.source === "medium" ? "Medium" :
        source.source === "dev" ? "DEV Community" : source.label;
    }
    catalog = { topics: data.topics || catalog.topics, subjects: data.subjects || catalog.subjects,
      sources: Object.keys(sources).length ? sources : catalog.sources };
    for (const [key, entries] of Object.entries(catalog)) {
      const field = form.querySelector(`[data-preferences="${key}"]`);
      const selected = field.children.length ? draft()[key] : preferences[key];
      field.replaceChildren(...Object.entries(entries).map(([value, text]) => {
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.name = key;
        input.value = value;
        input.checked = selected.includes(value);
        label.append(input, document.createTextNode(text));
        return label;
      }));
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const selected = draft();
    for (const key of Object.keys(limits)) {
      if (selected[key].length > limits[key]) {
        feedback.textContent = `Choose up to ${limits[key]} ${key}.`;
        return;
      }
    }
    preferences = selected;
    try {
      localStorage.setItem(KEY, JSON.stringify(preferences));
      feedback.textContent = "Preferences saved in this browser.";
    } catch {
      feedback.textContent = "Preferences applied for this session. Browser storage is unavailable.";
    }
    onChange();
  });
  container.querySelector("[data-clear-preferences]").addEventListener("click", () => {
    preferences = { topics: [], subjects: [], sources: [] };
    for (const input of form.querySelectorAll("input")) input.checked = false;
    try { localStorage.removeItem(KEY); } catch { /* Session preferences still reset. */ }
    feedback.textContent = "Interests reset. Showing a diverse selection of recent stories.";
    onChange();
  });
  return { update, request() {
    return Object.fromEntries(Object.keys(limits).map((key) => [key,
      preferences[key].filter((value) => Object.hasOwn(catalog[key], value))]));
  } };
}
