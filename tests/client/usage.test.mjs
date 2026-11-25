import assert from 'node:assert/strict';
import test from 'node:test';
import { countUse, flushUsage, noteReaderMilestone } from '../../public/usage.js';

test('reader milestones require opt-in and count distinct sessions within seven days', () => {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  const calls = [];
  const note = (action, sessionStartedAt, now, nav = {}) => noteReaderMilestone(action, {
    storage, nav, sessionStartedAt, now, track: (...args) => calls.push(args),
  });
  note('first_visit', 100, 100);
  assert.equal(values.size, 0);
  values.set('informa-analytics-consent', 'granted');
  note('first_visit', 100, 100, { globalPrivacyControl: true });
  assert.equal(calls.length, 0);
  note('first_visit', 100, 100);
  note('first_follow', 100, 102);
  note('first_follow', 100, 103);
  note('first_story', 200, 201);
  assert.deepEqual(calls.map(([, action]) => action), ['first_visit', 'first_follow', 'first_story', 'return_7d']);
});

test('usage counts are sent only with consent, batched, and carry only feature and action', () => {
  assert.equal(countUse('story_ask', 'open', { allowed: () => false }), false);
  assert.equal(countUse('story_ask', 'open', { allowed: () => true }), true);
  assert.equal(countUse('story_ask', 'question', { allowed: () => true }), true);
  const beacons = [];
  flushUsage({ sendBeacon: (url, blob) => { beacons.push({ url, blob }); return true; } });
  assert.equal(beacons.length, 1);
  assert.equal(beacons[0].url, '/api/usage/events');
  return beacons[0].blob.text().then((text) => {
    assert.deepEqual(JSON.parse(text), { events: [{ feature: 'story_ask', action: 'open' }, { feature: 'story_ask', action: 'question' }] });
  });
});

test('without a beacon the counts fall back to a keepalive fetch', () => {
  countUse('story_dossier', 'open', { allowed: () => true });
  const calls = [];
  flushUsage({}, (url, init) => { calls.push({ url, init }); return Promise.resolve(); });
  assert.equal(calls[0].url, '/api/usage/events');
  assert.equal(calls[0].init.keepalive, true);
  assert.deepEqual(JSON.parse(calls[0].init.body).events, [{ feature: 'story_dossier', action: 'open' }]);
});
