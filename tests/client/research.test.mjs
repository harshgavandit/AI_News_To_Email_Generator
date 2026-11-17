import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { readingGroups } from '../../public/privacy-data.js';

const markup = readFileSync(new URL('../../public/research.html', import.meta.url), 'utf8');
const script = readFileSync(new URL('../../public/research.js', import.meta.url), 'utf8').replace(/^import[^\n]+\n/gm, '');
const inboxScript = readFileSync(new URL('../../public/monitor-inbox.js', import.meta.url), 'utf8').replace('export async', 'async');
const flush = () => new Promise(resolve => setImmediate(resolve));

test('article analysis keeps citations in the Research Desk and preserves original attribution', async () => {
  const dom = new JSDOM(markup, { url: 'https://informa.test/research.html?article=s1', runScripts: 'outside-only' });
  const { window } = dom;
  const requests = [];
  window.readingGroups = readingGroups;
  window.fetch = async (path, options = {}) => {
    if (options.body) requests.push(JSON.parse(options.body));
    const data = path === '/api/intelligence/research' ? {
      retrieval: 'keyword', clusters: [],
      evidence: [{ id: 's1', title: 'Security patch issued', excerpt: 'An update is available.',
        publisher: 'Official advisory', url: 'https://example.org/advisory', published_at: '2026-11-14', language: 'en' }],
      answer: { status: 'answered', claims: [{ text: 'A patch is available.', kind: 'fact', source_ids: ['s1'] }],
        limitations: 'Publisher excerpt only.' },
    } : {};
    return { ok: true, json: async () => data };
  };
  try {
    window.eval(inboxScript);
    window.eval(script);
    await flush();
    assert.deepEqual(requests, [{ article_id: 's1', mode: 'analyze' }]);
    const citation = window.document.querySelector('a[aria-label="Source 1"]');
    assert.equal(citation.href, 'https://informa.test/research.html?article=s1#research-source-1');
    const evidence = window.document.querySelector(citation.hash);
    assert.match(evidence.textContent, /Official advisory/);
    assert.equal(evidence.querySelector('h3 > a').href, 'https://example.org/advisory');
    assert.equal(evidence.querySelector('a[href*="reading-room"]').href, 'https://informa.test/?article=s1#reading-room');
  } finally {
    window.close();
  }
});

test('Research Desk opts in, renders private source-linked alerts and marks the inbox read', async () => {
  const dom = new JSDOM(markup, { url: 'https://informa.test/research.html', runScripts: 'outside-only' });
  const { window } = dom;
  const { document } = window;
  window.readingGroups = readingGroups;
  const watch = { id: 'old-watch', query: 'Kubernetes security', topic: 'all' };
  window.localStorage.setItem(readingGroups.alerts.key, JSON.stringify([watch]));
  const readTime = Date.now() / 1000;
  const state = { available: true, active: false, alerts: [], watches: [], unread: 0 };
  let consented = false, marked = false;
  window.fetch = async (path, options = {}) => {
    if (path.endsWith('/enable')) {
      assert.deepEqual(JSON.parse(options.body).watches, [watch]);
      consented = true;
      Object.assign(state, { active: true, revision: 0, watches: [{ ...watch, checked: readTime }], unread: 1,
        alerts: [{ id: 'alert1', watch_id: watch.id, unread: true, updated: readTime, created: readTime,
          sources: [{ id: 'one', title: 'An advisory for Kubernetes', publisher: 'Official advisory', url: 'https://example.org/advisory' }] }] });
    }
    if (path.endsWith('/read')) {
      marked = true;
      state.unread = 0;
      state.alerts[0].unread = false;
    }
    return { ok: true, json: async () => structuredClone(path.includes('/inbox') ? state : {}) };
  };
  try {
    window.eval(inboxScript);
    window.eval(script);
    await flush();
    assert.equal(document.getElementById('monitor-opt-in').hidden, false);
    assert.equal(consented, false);
    document.getElementById('monitor-enable').click();
    await flush();
    assert.equal(consented, true);
    assert.equal(document.getElementById('monitor-unread').textContent, '1 unread');
    assert.equal(document.querySelector('#monitor-alerts h4 a').href, 'https://informa.test/?article=one#reading-room');
    document.getElementById('monitor-read').click();
    await flush();
    assert.equal(marked, true);
    assert.equal(document.getElementById('monitor-read').hidden, true);
  } finally {
    window.close();
  }
});

test('technology radar prepares a personalized preview with an attributable update timeline', async () => {
  const dom = new JSDOM(markup, { url: 'https://informa.test/research.html', runScripts: 'outside-only' });
  const { window } = dom, { document } = window;
  window.readingGroups = readingGroups;
  let submitted;
  const preview = { preview_id: 'p'.repeat(32), expires: Date.now() / 1000 + 300,
    signature: '', source_basis: 'Publisher evidence', digest: { edition: 'catchup', articles: [] } };
  window.fetch = async (path, options = {}) => {
    if (path === '/api/intelligence/catchup') submitted = JSON.parse(options.body);
    const data = path === '/api/intelligence/catchup' ? {
      status: 'ready', message: 'One updated development is ready.', preview,
      events: [{ id: 'e'.repeat(32), title: 'Cloud disruption has new reporting', change: 'updated', source_count: 2,
        reasons: ['Matches cloud'], articles: [{ url: 'https://example.org/outage', publisher: 'Newsroom' }] }],
    } : path.includes('/api/intelligence/events/') ? { entries: [], notice: 'Source timeline.' } : {};
    return { ok: true, json: async () => data };
  };
  try {
    window.eval(inboxScript);
    window.eval(script);
    document.getElementById('radar-role').value = 'engineer';
    document.getElementById('radar-interests').value = 'cloud, Kubernetes';
    document.getElementById('radar-form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    await flush();
    assert.equal(submitted.profile.role, 'engineer');
    assert.deepEqual(submitted.profile.interests, ['cloud', 'Kubernetes']);
    assert.match(document.getElementById('radar-results').textContent, /Cloud disruption has new reporting/);
    const handoff = document.querySelector('#radar-results a[href="/?ai-catchup=1#reading-room"]');
    assert.ok(handoff);
    handoff.click();
    assert.equal(JSON.parse(window.sessionStorage.getItem('informa-ai-catchup-preview')).preview_id, preview.preview_id);
  } finally { window.close(); }
});
