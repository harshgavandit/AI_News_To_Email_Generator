import { readingGroups } from "./privacy-data.js";

const key = readingGroups.radar.key;
let sessionFeedback;

export function readFeedback(fallback) {
  let stored;
  try { stored = JSON.parse(localStorage.getItem(key) || "null")?.feedback; } catch { /* Use session data. */ }
  const feedback = sessionFeedback || stored || fallback || {};
  return Object.fromEntries(["liked_ids", "muted_topics", "companies"].map((field) => [field,
    Array.isArray(feedback[field]) ? feedback[field].filter((item) => typeof item === "string").slice(0, 12) : []]));
}

export function toggleFeedback(field, value) {
  const feedback = readFeedback();
  const existing = feedback[field].find((entry) => entry.toLowerCase() === value.toLowerCase());
  feedback[field] = existing ? feedback[field].filter((entry) => entry !== existing) : [...feedback[field], value].slice(-12);
  try {
    const previous = JSON.parse(localStorage.getItem(key) || "null") || {};
    localStorage.setItem(key, JSON.stringify({ ...previous, feedback }));
    sessionFeedback = undefined;
  } catch { sessionFeedback = feedback; }
  return !existing;
}
