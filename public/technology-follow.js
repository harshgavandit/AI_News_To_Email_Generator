import { readingGroups } from "./privacy-data.js";

const radarKey = readingGroups.radar.key;

export function followedTechnologies(fallback = []) {
  try {
    const profile = JSON.parse(localStorage.getItem(radarKey));
    if (Array.isArray(profile?.followed_technologies)) return profile.followed_technologies;
  } catch { /* Browser storage may be unavailable. */ }
  return fallback;
}

export function saveTechnologyFollow(id, active) {
  const profile = JSON.parse(localStorage.getItem(radarKey)) || {};
  const followed = followedTechnologies();
  profile.followed_technologies = active ? [...new Set([...followed, id])] : followed.filter((item) => item !== id);
  localStorage.setItem(radarKey, JSON.stringify(profile));
}

export function followedStories() {
  try {
    const profile = JSON.parse(localStorage.getItem(radarKey));
    return Array.isArray(profile?.followed_events) ? profile.followed_events : [];
  } catch { return []; }
}

export function saveStoryFollow(id, active) {
  const profile = JSON.parse(localStorage.getItem(radarKey)) || {};
  const followed = followedStories();
  if (active && followed.length >= 40 && !followed.includes(id)) throw new Error("You can follow up to 40 stories.");
  profile.followed_events = active ? [...new Set([...followed, id])] : followed.filter(value => value !== id);
  localStorage.setItem(radarKey, JSON.stringify(profile));
}
