// Type-ahead scope suggestions for the Reading Room search box.
// Picking a suggestion narrows the feed by topic, subject, publisher feed or author
// instead of leaving the reader to find the matching filter by hand.

const KIND_LABELS = { interpretation: "Smart search", topic: "Topic", subject: "Subject", publisher: "Publisher", author: "Author" };

// The server's reading of a natural-language query becomes the first option, so one choice applies every filter.
export function withInterpretation(data) {
  const suggestions = Array.isArray(data?.suggestions) ? data.suggestions : [];
  const reading = data?.interpretation;
  if (!reading || typeof reading !== "object" || !reading.filters || typeof reading.summary !== "string") return suggestions;
  return [{ kind: "interpretation", label: reading.summary, detail: "Apply these filters", terms: String(reading.terms || ""),
    filters: reading.filters, labels: Array.isArray(reading.labels) ? reading.labels : [] }, ...suggestions];
}

export function createSearchSuggestions({ input, list, request, onSelect, delay = 140 }) {
  let items = [];
  let active = -1;
  let timer;
  let sequence = 0;
  const cache = new Map();

  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", list.id);
  input.setAttribute("aria-expanded", "false");
  list.setAttribute("role", "listbox");
  list.hidden = true;

  function close() {
    items = [];
    active = -1;
    list.hidden = true;
    list.replaceChildren();
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  function highlight(index) {
    active = index;
    for (const [position, option] of [...list.querySelectorAll('[role="option"]')].entries()) {
      option.setAttribute("aria-selected", String(position === index));
      if (position === index) {
        input.setAttribute("aria-activedescendant", option.id);
        option.scrollIntoView?.({ block: "nearest" });
      }
    }
    if (index < 0) input.removeAttribute("aria-activedescendant");
  }

  function choose(index) {
    const item = items[index];
    if (!item) return;
    close();
    onSelect(item);
  }

  function render(suggestions) {
    items = suggestions;
    active = -1;
    list.replaceChildren();
    if (!items.length) return close();
    let lastKind = "";
    items.forEach((item, index) => {
      if (item.kind !== lastKind) {
        const heading = document.createElement("li");
        heading.className = "suggest-group";
        heading.setAttribute("role", "presentation");
        heading.textContent = item.kind === "interpretation" ? "Smart search" : `${KIND_LABELS[item.kind] || item.kind}s`;
        list.append(heading);
        lastKind = item.kind;
      }
      const option = document.createElement("li");
      option.id = `${list.id}-${index}`;
      option.className = "suggest-option";
      option.dataset.kind = item.kind;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", "false");
      const label = document.createElement("span");
      label.className = "suggest-label";
      label.textContent = item.label;
      const meta = document.createElement("span");
      meta.className = "suggest-meta";
      meta.textContent = item.kind === "interpretation" ? item.detail
        : [KIND_LABELS[item.kind], item.detail].filter(Boolean).join(" · ");
      option.append(label, meta);
      // mousedown keeps focus in the input so the list does not close before the click lands.
      option.addEventListener("mousedown", (event) => event.preventDefault());
      option.addEventListener("click", () => choose(index));
      option.addEventListener("mousemove", () => { if (active !== index) highlight(index); });
      list.append(option);
    });
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  async function lookup(query) {
    const key = query.toLocaleLowerCase();
    const current = ++sequence;
    try {
      if (!cache.has(key)) {
        const data = await request(`/api/search/suggest?q=${encodeURIComponent(query)}`);
        cache.set(key, withInterpretation(data));
        if (cache.size > 60) cache.delete(cache.keys().next().value);
      }
    } catch {
      cache.set(key, []);
    }
    if (current !== sequence || document.activeElement !== input || input.value.trim().toLocaleLowerCase() !== key) return;
    render(cache.get(key));
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const query = input.value.trim();
    // Saved views and URL restores set the value programmatically; only a reader typing needs suggestions.
    if (query.length < 2 || document.activeElement !== input) {
      sequence++;
      return close();
    }
    timer = setTimeout(() => lookup(query), delay);
  });
  input.addEventListener("keydown", (event) => {
    if (list.hidden || !items.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      // Cycle through the options and back to the typed text (-1).
      let next = active + step;
      if (next >= items.length) next = -1;
      else if (next < -1) next = items.length - 1;
      highlight(next);
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      choose(active);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  });
  input.addEventListener("blur", () => setTimeout(close, 120));
  return { close, lookup };
}
