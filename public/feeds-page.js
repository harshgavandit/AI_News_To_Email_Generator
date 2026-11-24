// RSS feed directory: topic and technology feeds from /api/feeds, and a feed link for any search.
const byId = (id) => document.getElementById(id);

export function searchFeedUrl(terms, origin = globalThis.location?.origin || "") {
  const clean = String(terms || "").replace(/\s+/g, " ").trim().slice(0, 80);
  return clean.length >= 2 ? `${origin}/feeds/search.xml?q=${encodeURIComponent(clean)}` : "";
}

function feedItem(title, path) {
  const item = document.createElement("li");
  const link = Object.assign(document.createElement("a"), { href: path, textContent: title });
  const copy = Object.assign(document.createElement("button"), { type: "button", className: "text-button", textContent: "Copy link" });
  copy.setAttribute("aria-label", `Copy the ${title} feed link`);
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(new URL(path, location.origin).href);
      copy.textContent = "Copied";
    } catch { copy.textContent = "Select the link to copy"; }
    setTimeout(() => { copy.textContent = "Copy link"; }, 2000);
  });
  item.append(link, " ", copy);
  return item;
}

export async function startFeedsPage({ fetcher = globalThis.fetch } = {}) {
  byId("feeds-search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const url = searchFeedUrl(byId("feeds-search-input").value);
    const result = byId("feeds-search-result");
    if (!url) { result.textContent = "Enter at least two characters."; return; }
    result.replaceChildren("Your feed: ", Object.assign(document.createElement("a"), { href: url, textContent: url }));
  });
  try {
    const response = await fetcher("/api/feeds");
    if (!response.ok) throw new Error();
    const data = await response.json();
    byId("feeds-topics").replaceChildren(...data.topics.map((topic) => feedItem(topic.title, topic.path)));
    byId("feeds-technologies").replaceChildren(...data.technologies.map((tech) => feedItem(tech.title, tech.path)));
  } catch {
    byId("feeds-status").textContent = "The feed list couldn't load. Reload the page to try again.";
  }
}

if (typeof document !== "undefined" && byId("feeds-search-form")) startFeedsPage();
