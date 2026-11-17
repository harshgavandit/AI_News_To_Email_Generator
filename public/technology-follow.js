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
