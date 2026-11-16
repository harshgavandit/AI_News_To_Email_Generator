const storageKey = "informa-saved-views-v1";
const maxViews = 12;
const maxNameLength = 60;
const maxParametersLength = 2000;
const nameKey = (name) => name.normalize("NFKC").toLowerCase();

function readStoredViews() {
  const decoded = JSON.parse(localStorage.getItem(storageKey) ?? "[]");
  if (!Array.isArray(decoded)) return [];

  const views = [];
  const names = new Set();
  for (const view of decoded) {
    if (typeof view?.name !== "string" || typeof view.parameters !== "string" ||
        view.parameters.length > maxParametersLength) continue;
    const name = view.name.trim();
    if (!name || name.length > maxNameLength || names.has(nameKey(name))) continue;
    views.push({ name, parameters: view.parameters });
    names.add(nameKey(name));
    if (views.length === maxViews) break;
  }
  return views;
}

export function initSavedViews(root, { readView, applyView }) {
  const form = root.querySelector("#saved-view-form");
  const nameInput = root.querySelector("#saved-view-name");
  const list = root.querySelector("#saved-views-list");
  const empty = root.querySelector("#saved-views-empty");
  const status = root.querySelector("#saved-views-status");
  const summary = root.querySelector("summary");
  const memoryNote = "Changes will last until you close or reload this page.";
  let views = [];
  let useStorage = true;

  function refresh() {
    if (!useStorage) return;
    try {
      views = readStoredViews();
    } catch {
      useStorage = false;
      status.textContent = "Saved views could not be loaded from this browser. " + memoryNote;
    }
  }

  function save(nextViews) {
    views = nextViews;
    if (!useStorage) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify(views));
    } catch {
      useStorage = false;
    }
  }

  function feedback(message) {
    status.textContent = useStorage ? message : `${message} ${memoryNote}`;
  }

  function remove(view) {
    refresh();
    const key = nameKey(view.name);
    const index = views.findIndex((stored) => nameKey(stored.name) === key);
    if (index === -1) {
      render();
      nameInput.focus();
      feedback("This view was already removed.");
      return;
    }
    save(views.filter((stored) => nameKey(stored.name) !== key));
    render();
    const nextButton = list.children[Math.min(index, views.length - 1)]?.querySelector(".saved-view-remove");
    (nextButton || nameInput).focus();
    feedback(`Removed “${view.name}”.`);
  }

  function render() {
    empty.hidden = views.length > 0;
    const rows = views.map((view) => {
      const row = document.createElement("li");
      const open = document.createElement("button");
      open.type = "button";
      open.className = "saved-view-open";
      open.textContent = view.name;
      open.setAttribute("aria-label", `Open saved view ${view.name}`);
      open.addEventListener("click", () => {
        applyView(new URLSearchParams(view.parameters));
        feedback(`Opened “${view.name}”.`);
      });

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "saved-view-remove";
      removeButton.textContent = "Remove";
      removeButton.setAttribute("aria-label", `Remove saved view ${view.name}`);
      removeButton.addEventListener("click", () => remove(view));
      row.append(open, removeButton);
      return row;
    });
    list.replaceChildren(...rows);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    refresh();
    const name = nameInput.value.trim();
    if (!name || name.length > maxNameLength) {
      feedback(`Enter a name of up to ${maxNameLength} characters.`);
      nameInput.focus();
      return;
    }
    if (views.some((view) => nameKey(view.name) === nameKey(name))) {
      feedback("A view with this name is already saved.");
      nameInput.focus();
      return;
    }
    if (views.length >= maxViews) {
      feedback(`You can save up to ${maxViews} views. Remove one before saving a new view.`);
      return;
    }
    const parameters = readView().toString();
    if (parameters.length > maxParametersLength) {
      feedback("These filters are too long to save.");
      return;
    }
    save([...views, { name, parameters }]);
    nameInput.value = "";
    render();
    nameInput.focus();
    feedback(`Saved “${name}”.`);
  });

  root.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !root.open) return;
    event.stopPropagation();
    root.open = false;
    summary.focus();
  });

  window.addEventListener("storage", (event) => {
    if (!useStorage || (event.key !== storageKey && event.key !== null)) return;
    refresh();
    render();
  });
  refresh();
  render();
}
