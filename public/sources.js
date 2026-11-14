"use strict";
const sourceDescriptions = {
  status: "Official status",
  reporting: "Reporting",
  discussion: "Community discussion",
};
const element = (id) => document.getElementById(id);
const msg = (message) => {
  element("source-status").textContent = message;
};
async function render() {
  const response = await fetch("/api/sources");
  if (!response.ok)
    throw new Error("Sources could not be loaded. Please try again.");
  const { sources, topics } = await response.json();
  const list = element("source-rows");
  list.replaceChildren();
  for (const source of sources) {
    const row = document.createElement("article");
    row.className = "source-row";
    const name = document.createElement("a");
    const url = new URL(source.feed_url);
    if (["https:", "http:"].includes(url.protocol)) name.href = url.href;
    name.textContent = source.label;
    name.target = "_blank";
    name.rel = "noopener noreferrer";
    const info = document.createElement("span");
    const type = sourceDescriptions[source.coverage] || "Publisher update";
    const health = !source.enabled
      ? "Paused"
      : source.available === null
        ? "Not checked yet"
        : source.freshness === "stale"
          ? "Check overdue"
        : source.available
          ? "Available"
          : "Last check failed";
    info.textContent = [type, source.region, topics[source.topic], health]
      .filter(Boolean)
      .join(" · ");
    if (source.checked_at)
      info.textContent +=
        " · Checked " + new Date(source.checked_at).toLocaleString();
    if (source.last_success)
      info.textContent +=
        " · Last successful fetch " +
        new Date(source.last_success).toLocaleString();
    row.append(name, info);
    list.append(row);
  }
  msg(sources.length + " sources");
}
render().catch((error) => msg(error.message));
