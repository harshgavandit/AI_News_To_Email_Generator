export const VISIT_HISTORY_KEY = "informa-visit-history-v1";
const visitGap = 30 * 60 * 1000;
const archiveAge = 90 * 24 * 60 * 60 * 1000;
const latestDate = 253402300799999; // 9999-12-31T23:59:59.999Z
const unavailable = Object.freeze({ previousVisit: null, persistent: false, touch: () => false });

function validTime(time) {
  return Number.isSafeInteger(time) && time >= 0 && time <= latestDate;
}

export function isVisitRecord(record, now = Date.now()) {
  if (!record || !validTime(record.startedAt) || !validTime(record.lastActivityAt)) return false;
  const { startedAt, lastActivityAt, previousAt } = record;
  return startedAt <= lastActivityAt && lastActivityAt <= now && (previousAt === null ||
    (validTime(previousAt) && previousAt < startedAt && startedAt - previousAt <= archiveAge));
}

function readVisit(storage, now) {
  const raw = storage.getItem(VISIT_HISTORY_KEY);
  if (typeof raw !== "string" || raw.length > 256) return null;
  let record;
  try { record = JSON.parse(raw); } catch { return null; }
  if (!isVisitRecord(record, now)) return null;
  const { startedAt, lastActivityAt, previousAt } = record;
  return { startedAt, lastActivityAt, previousAt };
}

export function openVisit({ storage, now = Date.now() } = {}) {
  if (!storage || !validTime(now)) return unavailable;
  try {
    const saved = readVisit(storage, now);
    const continuing = saved && now - saved.lastActivityAt < visitGap;
    const startedAt = continuing ? saved.startedAt : now;
    const previousAt = continuing ? saved.previousAt :
      saved && now - saved.lastActivityAt <= archiveAge ? saved.lastActivityAt : null;
    storage.setItem(VISIT_HISTORY_KEY, JSON.stringify({ startedAt, lastActivityAt: now, previousAt }));
    return {
      startedAt,
      previousVisit: previousAt === null ? null : new Date(previousAt).toISOString(),
      persistent: true,
      touch({ now: activeAt = Date.now() } = {}) {
        if (!validTime(activeAt)) return false;
        try {
          const current = readVisit(storage, activeAt);
          // A tab from an older visit or a cleared history cannot restore the old record.
          if (!current || current.startedAt !== startedAt || current.previousAt !== previousAt ||
              activeAt === current.lastActivityAt || activeAt - current.lastActivityAt >= visitGap) return false;
          storage.setItem(VISIT_HISTORY_KEY, JSON.stringify({ ...current, lastActivityAt: activeAt }));
          return true;
        } catch { return false; }
      },
    };
  } catch { return unavailable; }
}
