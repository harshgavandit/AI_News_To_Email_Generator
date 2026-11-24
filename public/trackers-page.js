// Trackers page: AI model releases, incidents, security and releases, one tab at a time.
const byId = (id) => document.getElementById(id);
export const TRACKERS = ["ai-models", "incidents", "security", "releases"];
const LABELS = { "ai-models": "AI models", incidents: "Incidents", security: "Security", releases: "Releases" };
const STATE_LABELS = { resolved: "Resolved", monitoring: "Monitoring", identified: "Identified", investigating: "Investigating", update: "Update" };
const LEVEL_LABELS = { major: "Major", minor: "Minor", patch: "Patch", calendar: "Dated" };

export function relativeTime(iso, now = Date.now()) {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const minutes = Math.max(0, Math.round((now - then) / 60000));
  if (minutes < 60) return minutes <= 1 ? "just now" : `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function safeHref(url) {
  try {
    const parsed = new URL(url, location.origin);
    return ["https:", "http:"].includes(parsed.protocol) ? parsed.href : "#";
  } catch { return "#"; }
}

function sourceLink(source, now) {
  const row = el("li", "tracker-source");
  const link = el("a", "", source.title);
  link.href = safeHref(source.url);
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  const meta = el("span", "tracker-meta", ` ${source.publisher} · ${relativeTime(source.published_at, now)}`);
  if (source.official) meta.prepend(el("span", "tracker-chip official", "Official"), " ");
  row.append(link, meta);
  return row;
}

function sources(list, now) {
  const items = el("ul", "tracker-sources");
  items.append(...list.map((source) => sourceLink(source, now)));
  return items;
}

function card(title, chips, body) {
  const node = el("article", "tracker-card");
  const header = el("header", "tracker-card-head");
  header.append(el("h3", "", title), ...chips);
  node.append(header, ...body);
  return node;
}

const chip = (text, tone = "") => el("span", `tracker-chip ${tone}`.trim(), text);

export function renderModels(items, now = Date.now()) {
  return items.map((item) => card(item.name, [
    ...(item.official ? [chip("Official announcement", "official")] : []),
    chip(`${item.outlets} outlet${item.outlets === 1 ? "" : "s"}`),
    chip(`First seen ${relativeTime(item.first_seen, now)}`, "quiet"),
  ], [sources(item.sources, now)]));
}

export function renderIncidents(data, now = Date.now()) {
  const nodes = data.providers.map((provider) => card(provider.provider, [
    chip(provider.open ? "Ongoing" : "No open incident", provider.open ? "alert" : "ok"),
  ], [(() => {
    const list = el("ul", "tracker-sources");
    list.append(...provider.updates.map((update) => {
      const row = sourceLink({ ...update, official: false }, now);
      row.prepend(chip(STATE_LABELS[update.state] || "Update", update.state === "resolved" ? "ok" : update.state === "update" ? "quiet" : "alert"), " ");
      return row;
    }));
    return list;
  })()]));
  if (data.reporting.length) nodes.push(card("In the news", [], [sources(data.reporting, now)]));
  return nodes;
}

export function renderSecurity(data, { exploitedOnly = false } = {}, now = Date.now()) {
  const cves = data.cves.filter((item) => !exploitedOnly || item.exploited);
  const nodes = cves.map((item) => card(item.cve, [
    ...(item.exploited ? [chip("Exploited", "alert")] : []),
    chip(`${item.outlets} source${item.outlets === 1 ? "" : "s"}`),
    chip(relativeTime(item.latest, now), "quiet"),
  ], [sources(item.sources, now)]));
  const advisories = data.advisories.filter((item) => !exploitedOnly || item.exploited);
  if (advisories.length) nodes.push(card("Other advisories", [], [sources(advisories, now)]));
  return nodes;
}

export function renderReleases(items, { patches = false, query = "" } = {}, now = Date.now()) {
  const needle = query.trim().toLowerCase();
  const shown = items.filter((item) => (patches || item.level !== "patch") && (!needle || item.project.toLowerCase().includes(needle)));
  const list = el("ul", "tracker-releases");
  list.append(...shown.map((item) => {
    const row = el("li", "tracker-release");
    const link = el("a", "tracker-release-name", `${item.project} ${item.version}`);
    link.href = safeHref(item.release.url);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    row.append(link, chip(LEVEL_LABELS[item.level] || item.level, item.level === "major" ? "alert" : item.level === "minor" ? "official" : "quiet"),
      el("span", "tracker-meta", relativeTime(item.release.published_at, now)));
    return row;
  }));
  return shown.length ? [list] : [];
}

export function summaryText(kind, data) {
  if (kind === "ai-models") return `${data.items.length} models announced or covered in the last ${data.days} days`;
  if (kind === "incidents") {
    const open = data.items.providers.filter((provider) => provider.open).length;
    return `${open ? `${open} provider${open === 1 ? "" : "s"} with an ongoing incident` : "No ongoing incidents"} · ${data.items.providers.length} providers posted in the last ${data.days} days`;
  }
  if (kind === "security") {
    const exploited = data.items.cves.filter((item) => item.exploited).length;
    return `${data.items.cves.length} CVEs in the news, ${exploited} reported as exploited · last ${data.days} days`;
  }
  const notable = data.items.filter((item) => item.level !== "patch").length;
  return `${data.items.length} projects released in the last ${data.days} days · ${notable} major or minor`;
}

export function startTrackers({ fetcher = globalThis.fetch, win = window } = {}) {
  const params = new URLSearchParams(win.location.search);
  const state = { kind: TRACKERS.includes(params.get("tab")) ? params.get("tab") : "ai-models", data: {},
    exploitedOnly: false, patches: false, query: "" };
  const tabs = [...document.querySelectorAll("[data-tracker]")];
  let request = 0;

  function controls() {
    const box = byId("tracker-controls");
    box.replaceChildren();
    if (state.kind === "security") {
      const label = el("label", "tracker-toggle");
      const input = Object.assign(el("input"), { type: "checkbox", checked: state.exploitedOnly });
      input.addEventListener("change", () => { state.exploitedOnly = input.checked; draw(); });
      label.append(input, " Exploited only");
      box.append(label);
    }
    if (state.kind === "releases") {
      const search = Object.assign(el("input", "tracker-search"), { type: "search", placeholder: "Filter projects", value: state.query });
      search.setAttribute("aria-label", "Filter projects");
      search.addEventListener("input", () => { state.query = search.value; draw(); });
      const label = el("label", "tracker-toggle");
      const input = Object.assign(el("input"), { type: "checkbox", checked: state.patches });
      input.addEventListener("change", () => { state.patches = input.checked; draw(); });
      label.append(input, " Include patch releases");
      box.append(search, label);
    }
  }

  function draw() {
    const data = state.data[state.kind];
    const content = byId("tracker-content");
    if (!data) return;
    const nodes = state.kind === "ai-models" ? renderModels(data.items)
      : state.kind === "incidents" ? renderIncidents(data.items)
        : state.kind === "security" ? renderSecurity(data.items, state)
          : renderReleases(data.items, state);
    content.replaceChildren(...(nodes.length ? nodes : [el("p", "tracker-empty", "Nothing to show for this filter yet.")]));
    content.setAttribute("aria-busy", "false");
    byId("tracker-summary").textContent = summaryText(state.kind, data);
    byId("tracker-notice").textContent = data.notice;
  }

  async function show(kind, { push = true } = {}) {
    state.kind = kind;
    for (const tab of tabs) {
      const active = tab.dataset.tracker === kind;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    }
    byId("tracker-panel").setAttribute("aria-labelledby", `tab-${kind}`);
    if (push) {
      const url = new URL(win.location.href);
      url.searchParams.set("tab", kind);
      win.history.replaceState(null, "", url);
    }
    document.title = `${LABELS[kind]} tracker · Informa AI`;
    controls();
    if (state.data[kind]) { draw(); return; }
    const ticket = ++request;
    byId("tracker-summary").textContent = "Loading…";
    byId("tracker-content").setAttribute("aria-busy", "true");
    try {
      const response = await fetcher(`/api/trackers/${kind}`);
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      state.data[kind] = data;
      if (ticket === request && state.kind === kind) draw();
    } catch {
      if (ticket !== request) return;
      byId("tracker-summary").textContent = "This tracker couldn't load.";
      const retry = el("button", "button secondary", "Try again");
      retry.type = "button";
      retry.addEventListener("click", () => show(kind, { push: false }));
      byId("tracker-content").replaceChildren(retry);
      byId("tracker-content").setAttribute("aria-busy", "false");
    }
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => show(tab.dataset.tracker));
    tab.addEventListener("keydown", (event) => {
      const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      event.preventDefault();
      const next = tabs[(index + step + tabs.length) % tabs.length];
      next.focus();
      show(next.dataset.tracker);
    });
  });
  return show(state.kind, { push: false });
}

if (typeof window !== "undefined" && byId("tracker-panel")) startTrackers();
