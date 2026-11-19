import assert from 'node:assert/strict';
import test from 'node:test';
import { clearReadingData, dataCounts, hasVisitHistory, readBrowserData } from '../../public/privacy-data.js';
import { openVisit, VISIT_HISTORY_KEY } from '../../public/visit-history.js';

const start = Date.parse('2026-11-18T07:00:00Z');
const minute = 60_000;
const mockStorage = () => {
  const entries = new Map();
  return { getItem: (key) => entries.get(key) ?? null, setItem: (key, value) => entries.set(key, String(value)),
    removeItem: (key) => entries.delete(key) };
};

test('distinct Reading Room visits keep the same prior cutoff across tabs, activity, and reloads', () => {
  const storage = mockStorage();
  const first = openVisit({ storage, now: start });
  assert.equal(first.persistent, true);
  assert.equal(first.previousVisit, null);
  assert.equal(first.touch({ now: start + 12 * minute }), true);
  assert.equal(openVisit({ storage, now: start + 40 * minute }).previousVisit, null);
  const second = openVisit({ storage, now: start + 70 * minute });
  assert.equal(second.previousVisit, '2026-11-18T07:40:00.000Z');
  assert.equal(second.touch({ now: start + 73 * minute }), true);
  assert.equal(openVisit({ storage, now: start + 92 * minute }).previousVisit, second.previousVisit);
  assert.equal(second.previousVisit, '2026-11-18T07:40:00.000Z');
});

test('an older or expired tab cannot overwrite the active visit or extend its own expired visit', () => {
  const storage = mockStorage();
  const first = openVisit({ storage, now: start });
  assert.equal(first.touch({ now: start + 30 * minute }), false);
  const second = openVisit({ storage, now: start + 40 * minute });
  assert.equal(first.touch({ now: start + 41 * minute }), false);
  assert.equal(second.touch({ now: start + 42 * minute }), true);
  const third = openVisit({ storage, now: start + 72 * minute });
  assert.equal(third.previousVisit, '2026-11-18T07:42:00.000Z');
});

test('stale, malformed and future-dated records do not become cutoffs', () => {
  for (const invalid of [
    '{not json', '[]', 'x'.repeat(257),
    JSON.stringify({ startedAt: start - 1000, lastActivityAt: start - 1, previousAt: start + 1 }),
    JSON.stringify({ startedAt: start + 30 * minute, lastActivityAt: start + 50 * minute, previousAt: null }),
    JSON.stringify({ startedAt: start - 91 * 1440 * minute, lastActivityAt: start - 91 * 1440 * minute, previousAt: null }),
  ]) {
    const storage = mockStorage();
    storage.setItem(VISIT_HISTORY_KEY, invalid);
    const visit = openVisit({ storage, now: start });
    assert.equal(visit.previousVisit, null);
    assert.equal(visit.persistent, true);
    assert.deepEqual(JSON.parse(storage.getItem(VISIT_HISTORY_KEY)), { startedAt: start, lastActivityAt: start, previousAt: null });
  }
});

test('storage and clock failures return a stable, non-persistent fallback', () => {
  const fail = () => { throw new Error('Browser storage unavailable'); };
  for (const options of [{}, { storage: { getItem: fail }, now: start },
    { storage: { getItem: () => null, setItem: fail }, now: start }, { storage: mockStorage(), now: Infinity }]) {
    const visit = openVisit(options);
    assert.equal(visit.previousVisit, null);
    assert.equal(visit.persistent, false);
    assert.equal(visit.touch({ now: start }), false);
  }
});

test('visit timing exports and clears with read history without counting it as a read story', () => {
  const storage = mockStorage();
  const now = Date.now() - minute;
  const visit = openVisit({ storage, now });
  const before = readBrowserData(storage);
  assert.equal(hasVisitHistory(before), true);
  assert.equal(dataCounts(before).history, 0);
  storage.setItem('informa-saved-v1', '[]');
  clearReadingData(storage, ['bookmarks']);
  assert.equal(hasVisitHistory(readBrowserData(storage)), true);
  clearReadingData(storage, ['history']);
  assert.equal(hasVisitHistory(readBrowserData(storage)), false);
  assert.equal(visit.touch({ now: now + minute }), false);
  assert.equal(storage.getItem(VISIT_HISTORY_KEY), null);
});
