// Weekly recap page: last week's biggest stories plus model launches, exploited bugs, incidents and releases.
const byId = (id) => document.getElementById(id);
const WEEK = /^\d{4}-W\d{2}$/;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function anchor(text, href, external = true) {
  const link = el("a", "", text);
  try {
    const url = new URL(href, location.origin);
    link.href = ["https:", "http:"].includes(url.protocol) ? url.href : "#";
  } catch { link.href = "#"; }
  if (external && !link.href.startsWith(location.origin)) {
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
  return link;
}

function listItems(target, entries, empty) {
  const list = byId(target);
  list.replaceChildren(...(entries.length ? entries : [el("li", "muted", empty)]));
}

export function renderRecap(data) {
  byId("recap-title").textContent = data.title;
  byId("recap-range").textContent = data.complete === false
    ? `Notable headlines between ${data.start} and ${data.end}.`
    : `Stories between ${data.start} and ${data.end}, ranked by how many publishers reported them.`;
  document.title = `${data.title} | Informa AI`;
  const stats = byId("recap-stats");
  stats.replaceChildren(...[["AI models", data.stats.models], ["Exploited bugs", data.stats.exploited],
    ["Providers with incidents", data.stats.providers_with_incidents], ["Notable releases", data.stats.releases]]
    .map(([label, value]) => { const box = el("div"); box.append(el("dt", "", label), el("dd", "", String(value))); return box; }));
  stats.hidden = false;
  listItems("recap-top", data.top_stories.map((story) => {
    const item = el("li", "recap-story");
    const title = anchor(story.title, story.url, !story.url.startsWith("/"));
    title.className = "recap-story-title";
    const meta = el("p", "recap-meta",
      story.outlets > 1 ? `${story.topic_label} · ${story.outlets} publishers · first reported by ${story.first_publisher}`
        : `${story.topic_label} · ${story.first_publisher}`);
    item.append(title, meta);
    if (story.summary) item.append(el("p", "recap-summary", story.summary));
    return item;
  }), "No grouped stories were stored for this week.");
  const simple = (text, href, meta) => { const item = el("li"); item.append(anchor(text, href)); if (meta) item.append(el("span", "recap-meta", ` ${meta}`)); return item; };
  listItems("recap-models", data.models.map((model) => simple(model.name, model.url,
    `${model.official ? "official · " : ""}${model.outlets} outlet${model.outlets === 1 ? "" : "s"}`)), "No model launches detected.");
  listItems("recap-security", data.exploited.map((item) => simple(item.cve, item.url, item.title)), "No exploited vulnerabilities reported.");
  listItems("recap-incidents", data.incidents.map((item) => simple(item.provider, item.url,
    `${item.updates} update${item.updates === 1 ? "" : "s"} · ${item.latest}`)), "No status-page incidents.");
  listItems("recap-releases", data.releases.map((item) => simple(`${item.project} ${item.version}`, item.url, item.level)), "No major or minor releases.");
  byId("recap-topics").replaceChildren(...data.topics.map((topic) => {
    const box = el("section", "recap-topic");
    box.append(el("h3", "", topic.label));
    const list = el("ul", "recap-list");
    list.append(...topic.stories.map((story) => simple(story.title, story.url, `${story.outlets} publishers`)));
    box.append(list);
    return box;
  }));
  const section = byId("recap-postmortem-section");
  section.hidden = !data.postmortem;
  if (data.postmortem) byId("recap-postmortem").replaceChildren(anchor(data.postmortem.title, data.postmortem.url),
    el("span", "recap-meta", ` ${data.postmortem.company}`));
  byId("recap-notice").textContent = data.notice;
}

export async function startRecap({ fetcher = globalThis.fetch, win = window } = {}) {
  const status = byId("recap-status");
  const select = byId("recap-week");
  let loaded = false;

  async function load(week) {
    status.textContent = "Loading…";
    try {
      const response = await fetcher(week ? `/api/recap/${encodeURIComponent(week)}` : "/api/recap");
      if (response.status === 404) { status.textContent = "There's no recap for that week yet. Recaps start after a full week of coverage."; return; }
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      renderRecap(data);
      const weeks = data.weeks.some((entry) => entry.week === data.week) ? data.weeks : [{ week: data.week, title: data.title }, ...data.weeks];
      if (!loaded || select.options.length !== weeks.length) {
        select.replaceChildren(...weeks.map((entry) => Object.assign(el("option", "", entry.title.replace("This week in tech: ", "")), { value: entry.week })));
        loaded = true;
      }
      select.value = data.week;
      const url = new URL(win.location.href);
      url.searchParams.set("week", data.week);
      win.history.replaceState(null, "", url);
      status.textContent = "";
    } catch {
      status.textContent = "The recap couldn't load. Reload the page to try again.";
    }
  }

  select.addEventListener("change", () => load(select.value));
  const requested = new URLSearchParams(win.location.search).get("week");
  return load(WEEK.test(requested || "") ? requested : "");
}

if (typeof window !== "undefined" && byId("recap-top")) startRecap();
