// Only these application-owned keys can be exported or reset. Never clear an origin wholesale.
export const readingGroups = Object.freeze({
  bookmarks: { label: "Saved stories", key: "informa-saved-v1" },
  history: { label: "Read history", key: "informa-read-v1" },
  interests: { label: "Interests & followed lists", key: "informa-interests-v1" },
  views: { label: "Monitoring views", key: "informa-saved-views-v1" },
  alerts: { label: "Research topic alerts", key: "informa-research-alerts-v1" },
  radar: { label: "Technology radar preferences", key: "informa-radar-v1" },
  checkpoint: { label: "Catch-up checkpoint", key: "informa-catchup-checkpoint" },
  impact: { label: "Personal impact targets", key: "informa-impact-v1" },
  inbox: { label: "Developments marked seen", key: "informa-inbox-seen-v1" },
});
const exportKeys = [...Object.values(readingGroups).map(({ key }) => key),
  "informa-theme", "informa-story-layout", "informa-hide-read", "informa-analytics-consent", "informa-performance-consent"];

export function readBrowserData(storage) {
  return Object.fromEntries(exportKeys.flatMap((key) => {
    const raw = storage.getItem(key);
    if (raw === null) return [];
    let value = raw;
    try { value = JSON.parse(raw); } catch { /* Appearance preferences can be plain strings. */ }
    return [[key, value]];
  }));
}

export function clearReadingData(storage, groups) {
  const selected = [...new Set(groups)];
  if (!selected.length || selected.some((group) => !Object.hasOwn(readingGroups, group)))
    throw new Error("Choose at least one reading data category.");
  for (const group of selected) storage.removeItem(readingGroups[group].key);
  // Other Reading Room tabs must discard their old in-memory copies as well.
  storage.setItem("informa-reader-reset", String(Date.now()));
  return selected.map((group) => readingGroups[group].label);
}

export function dataCounts(data) {
  const count = (key) => Array.isArray(data[key]) ? data[key].length : 0;
  const interests = data[readingGroups.interests.key];
  return {
    bookmarks: count(readingGroups.bookmarks.key), history: count(readingGroups.history.key),
    views: count(readingGroups.views.key),
    alerts: count(readingGroups.alerts.key), radar: data[readingGroups.radar.key] ? 1 : 0,
    interests: ["topics", "subjects", "sources", "authors"].reduce((sum, key) =>
      sum + (Array.isArray(interests?.[key]) ? interests[key].length : 0), 0),
  };
}
