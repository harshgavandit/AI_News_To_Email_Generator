const windows = { 12: "12h", 24: "24h", 168: "7d", 720: "30d", 2160: "90d" };

export function searchLink(target, { q, hours, topic }) {
  const query = new URLSearchParams();
  const limit = ["articles", "developments"].includes(target) ? 150 : 320;
  if (q?.trim()) query.set("q", q.trim().slice(0, limit));
  query.set("topic", topic || "all");
  if (target === "articles") {
    query.set("window", windows[hours] || "7d");
    query.set("view", "feed");
    return `/?${query}#reading-room`;
  }
  query.set("hours", hours || 168);
  query.set("mode", target);
  return `/research.html?${query}#research-title`;
}
