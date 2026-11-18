import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { readingGroups } from '../../public/privacy-data.js';
import { coverageLabels } from '../../public/catalog.js';

const markup = readFileSync(new URL('../../public/research.html', import.meta.url), 'utf8');
const script = readFileSync(new URL('../../public/research.js', import.meta.url), 'utf8').replace(/^import[^\n]+\n/gm, '');
const inboxScript = readFileSync(new URL('../../public/monitor-inbox.js', import.meta.url), 'utf8').replace('export async', 'async');
const feedbackScript = readFileSync(new URL('../../public/reader-feedback.js', import.meta.url), 'utf8')
  .replace(/^import[^\n]+\n/gm, '').replace(/^export /gm, '');
function mountResearch(window) {
  window.coverageLabels = coverageLabels;
  window.eval(inboxScript);
  window.eval(`(() => { ${feedbackScript}\nwindow.readFeedback = readFeedback; })()`);
  for (const [file, bindings] of [
    ['technology-follow.js', ['followedTechnologies', 'followedStories']],
    ['evidence-ui.js', ['node', 'requestJSON', 'answerBlock', 'sourceLink', 'sourceList']],
    ['source-history.js', ['historyControl']],
    ['watch-rule-ui.js', ['initRuleBuilder']],
    ['claim-evidence.js', ['appendClaimEvidence']],
    ['search-context.js', ['searchLink']],
  ]) {
    const code = readFileSync(new URL(`../../public/${file}`, import.meta.url), 'utf8')
      .replace(/^import[^\n]+\n/gm, '').replace(/^export /gm, '');
    window.eval(`(() => { ${code}\nObject.assign(window, { ${bindings.join(', ')} }); })()`);
  }
  window.eval(script);
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('a scoped search opens development results and can save the followed-updates mode', async () => {
  const dom = new JSDOM(markup, { url: 'https://informa.test/research.html?q=cloud+outage&hours=12&topic=software&mode=developments',
    runScripts: 'outside-only' });
  const { window } = dom;
  const calls = [];
  window.readingGroups = readingGroups;
  window.fetch = async (path, options = {}) => {
    calls.push([path, options.method, options.body]);
    const data = path === '/api/intelligence/options' ? { topics: { software: 'Software' } } :
      path.startsWith('/api/intelligence/events?hours=12') ? { events: [{ id: 'd'.repeat(32),
        title: 'Cloud outage recovered', source_count: 2, updated_at: '2026-11-18' }] } :
      options.method === 'PUT' ? { notice: 'Followed updates saved.' } : {};
    return { ok: true, json: async () => data };
  };
  try {
    mountResearch(window);
    await flush();
    const { document } = window;
    assert.match(document.getElementById('research-results').textContent, /Cloud outage recovered/);
    assert.ok(calls.some(([path]) => path.includes('hours=12&topic=software&q=cloud+outage')));
    const articles = new URL(document.getElementById('search-articles').href);
    assert.deepEqual([articles.searchParams.get('q'), articles.searchParams.get('window'), articles.searchParams.get('topic')],
      ['cloud outage', '12h', 'software']);
    const ask = new URL(document.getElementById('search-ask').href);
    assert.equal(ask.searchParams.get('mode'), 'analyze');
    document.getElementById('radar-delivery-mode').value = 'material_updates';
    document.getElementById('radar-save').click();
    await flush();
    const saved = calls.find(([path, method]) => path === '/api/mail/radar' && method === 'PUT');
    assert.equal(JSON.parse(saved[2]).delivery_mode, 'material_updates');
    assert.equal(document.getElementById('radar-status').textContent, 'Followed updates saved.');
  } finally {
    window.close();
  }
});

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
      answer: { status: 'answered', claims: [{ text: 'A patch is available.', kind: 'fact', source_ids: ['s1'], quotes: ['An update is available.'] }],
        limitations: 'Publisher excerpt only.' },
    } : {};
    return { ok: true, json: async () => data };
  };
  try {
    mountResearch(window);
    await flush();
    assert.deepEqual(requests, [{ article_id: 's1', mode: 'analyze' }]);
    const citation = window.document.querySelector('a[aria-label="Source 1"]');
    assert.equal(citation.href, 'https://informa.test/research.html?article=s1#research-source-1');
    const evidence = window.document.querySelector(citation.hash);
    assert.match(evidence.textContent, /Official advisory/);
    const claim = window.document.querySelector('.claim-evidence');
    claim.querySelector('summary').click();
    assert.equal(claim.querySelector('blockquote').textContent, 'An update is available.');
    assert.equal(claim.querySelector('a').href, 'https://example.org/advisory');
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
    mountResearch(window);
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
    mountResearch(window);
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

test('followed story revisions, package results, and multilingual technical evidence render from API responses', async () => {
  const dom = new JSDOM(markup, { url: 'https://informa.test/research.html', runScripts: 'outside-only' });
  const { window } = dom;
  const { document } = window;
  window.readingGroups = readingGroups;
  const eventId = 'e'.repeat(32);
  window.localStorage.setItem(readingGroups.radar.key, JSON.stringify({ viewedRevisions: { [eventId]: '1' } }));
  const source = { id: 'release', title: 'uv removes an adapter', excerpt: 'The release removes its old adapter.',
    publisher: 'uv Releases', language: 'en', coverage: 'release', url: 'https://example.org/release', published_at: '2026-11-17' };
  const requests = [];
  window.fetch = async (path, options = {}) => {
    requests.push({ path, body: options.body && JSON.parse(options.body) });
    let data = {};
    if (path.includes(`/events/${eventId}`)) data = { revision: '2', entries: [source], changes: [source] };
    else if (path.includes('/events?')) data = { events: [{ id: eventId, title: source.title, source_count: 1, updated_at: source.published_at }] };
    else if (path.endsWith('/package-check')) data = { evidence: [source], partial: false };
    else if (path.endsWith('/research')) data = { evidence: [source], answer: { status: 'answered', limitations: 'One excerpt.',
      claims: [{ kind: 'single_source', source_ids: [source.id], quotes: [source.excerpt], text: source.excerpt }] } };
    else if (path.endsWith('/explain')) data = { evidence: [source], sections: { breaking: 'Breaking changes' },
      answer: { claims: [{ kind: 'breaking', text: source.excerpt, quote: source.excerpt, source_id: source.id }] } };
    return { ok: true, json: async () => data };
  };
  try {
    mountResearch(window);
    await flush();
    document.querySelector('[data-follow-event]').click();
    assert.equal(document.querySelector('[data-follow-event]').textContent, 'Unfollow story');
    document.getElementById('show-followed-developments').click();
    await flush();
    assert.ok(requests.some(({ path }) => path.includes(`followed=${eventId}`)));
    [...document.querySelectorAll('#development-list button')].find((button) => button.textContent === 'Open timeline').click();
    await flush();
    assert.match(document.getElementById('development-list').textContent, /New since your last visit/);
    assert.ok(requests.some(({ path }) => path.endsWith(`${eventId}?since=1`)));

    const form = document.getElementById('package-check-form');
    form.elements.namedItem('name').value = 'uv';
    form.elements.namedItem('version').value = '0.5.0';
    form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    await flush();
    assert.match(document.getElementById('package-check-status').textContent, /1 matching advisor/);
    assert.equal(requests.find(({ path }) => path.endsWith('/package-check')).body.version, '0.5.0');

    document.getElementById('research-question').value = 'uv changes';
    document.getElementById('research-mode').value = 'global_compare';
    document.getElementById('research-form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    await flush();
    assert.match(document.getElementById('research-results').textContent, /Cross-language coverage comparison/);
    assert.match(document.getElementById('research-results').textContent, /Evidence from uv Releases/);
    [...document.querySelectorAll('#research-results button')].find((button) => button.textContent === 'Build technical brief').click();
    await flush();
    assert.match(document.getElementById('research-results').textContent, /Breaking changes/);
    assert.equal(requests.find(({ path }) => path.endsWith('/explain')).body.format, 'technical_brief');
  } finally { window.close(); }
});
