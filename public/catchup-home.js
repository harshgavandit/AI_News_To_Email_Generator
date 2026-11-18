import { readingGroups } from "./privacy-data.js";

const visitKey = readingGroups.checkpoint.key;

export function catchupCheckpoint(storage, now = Date.now()) {
  try {
    const value = Number(storage.getItem(visitKey));
    return Number.isSafeInteger(value) && value > 0 && value <= now ? value : 0;
  } catch {
    return 0;
  }
}

export function markCatchupCheckpoint(storage, now = Date.now()) {
  try { storage.setItem(visitKey, String(Math.max(now, catchupCheckpoint(storage)))); }
  catch { /* Reading still works when browser storage is unavailable. */ }
}

export function entryView(params, previousVisit) {
  const explicit = params.get("view");
  if (["feed", "briefing", "catchup", "for-you", "saved"].includes(explicit)) return explicit;
  if ([...params.keys()].some(key => !key.startsWith("utm_"))) return "feed";
  return previousVisit ? "catchup" : "briefing";
}

export function homeCatchupRequest(storage, since, feedback, technologies) {
  let saved = {};
  try { saved = JSON.parse(storage.getItem(readingGroups.radar.key)) || {}; } catch {}
  const { role, interests, stack, topics, followed_events, language, depth } = saved;
  const profile = { role, interests, stack, topics, followed_events, language, depth,
    feedback, followed_technologies: technologies, length: 10 };
  return { profile, hours: 720, since: since / 1000, summary_only: true };
}
