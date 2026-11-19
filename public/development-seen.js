import { readingGroups } from "./privacy-data.js";

const key = readingGroups.inbox.key;
const limit = 320;
const valid = ([id, version]) => typeof version === "string" && /^[a-f0-9]{32}$/.test(id) && /^\d{1,10}$/.test(version);

export function seenDevelopments(storage = window.localStorage) {
  try {
    const saved = JSON.parse(storage.getItem(key)) || {};
    return Object.fromEntries(Object.entries(saved).filter(valid).slice(-limit));
  } catch { return {}; }
}

export function markDevelopmentsSeen(events, storage = window.localStorage) {
  const previous = new Map(Object.entries(seenDevelopments(storage)));
  for (const event of events) {
    const entry = [event.id, event.digest_version];
    if (!valid(entry)) continue;
    const version = Number(previous.get(event.id)) > Number(event.digest_version) ? previous.get(event.id) : event.digest_version;
    previous.delete(event.id);
    previous.set(event.id, version);
  }
  storage.setItem(key, JSON.stringify(Object.fromEntries([...previous].slice(-limit))));
}
