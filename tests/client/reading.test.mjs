import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { createPreferences } from '../../public/preferences.js';
import { readingContent } from '../../public/reading-content.js';
import { createDeliveryStatus } from '../../public/delivery-status.js';
import { createStoryQuestion } from '../../public/story-question.js';
import { createCoverageDialog } from '../../public/coverage-dialog.js';

const html = readFileSync(new URL('../../public/index.html', import.meta.url), 'utf8');
const authorKey = `author-${'a'.repeat(32)}`;
const catalog = { topics: { software: 'Software' }, subjects: { cloud: 'Cloud' }, sources: [
  { id: 'medium-codex', source: 'medium', label: 'CodeX on Medium', enabled: true },
], authors: [{ id: authorKey, name: 'A Writer', publisher: 'CodeX on Medium' }] };

function mount(markup = html, url = 'https://informa.test/') {
  const dom = new JSDOM(markup, { url });
  dom.window.matchMedia = query => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} });
  const previous = new Map();
  for (const name of ['window', 'document', 'localStorage', 'sessionStorage', 'DOMParser', 'Node', 'location', 'history', 'navigator', 'getComputedStyle', 'CSS', 'matchMedia']) {
    previous.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
    Object.defineProperty(globalThis, name, { configurable: true, writable: true,
      value: name === 'getComputedStyle' ? dom.window.getComputedStyle.bind(dom.window) : name === 'CSS' ? { escape: value => String(value) } : dom.window[name] });
  }
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  if (!dom.window.HTMLDialogElement.prototype.showModal) dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  if (!dom.window.HTMLDialogElement.prototype.close) dom.window.HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new dom.window.Event('close')); };
  return { dom, close() { dom.window.close(); for (const [name, descriptor] of previous) { if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name]; } } };
}

async function until(check) {
  for (let i = 0; i < 100; i++) { if (check()) return; await delay(5); }
  assert.fail('Expected UI state did not arrive');
}

test('a development deep link renders its evidence, freshness, and personal impact check', async () => {
  const id = 'e'.repeat(32);
  const markup = readFileSync(new URL('../../public/development.html', import.meta.url), 'utf8');
  const env = mount(markup, `https://informa.test/development.html?id=${id}`);
  const previousFetch = globalThis.fetch;
  const target = { provider: 'google-cloud', service: 'Compute Engine', region: 'us-central1' };
  localStorage.setItem('informa-impact-v1', JSON.stringify({ cloud: [target], packages: [] }));
  const source = { id: 'provider', title: 'Service update', coverage: 'status', publisher: 'Google Cloud Status',
    url: 'https://status.cloud.google.com/', published_at: '2026-11-18T16:00:00Z', cleanSummary: 'Service has recovered.' };
  const entry = { ...source, source, excerpt: source.cleanSummary, change_label: 'Resolved', observed: 1795017900 };
  globalThis.fetch = async (path, options = {}) => {
    const payload = path === '/api/intelligence/personal-impact' ?
      { cloud: [{ target, status: 'match', message: 'Official report matches.', evidence: [source] }], packages: [] } :
      { title: 'Cloud service recovery', entries: [entry], latest_material: entry, notice: 'Source timeline',
        coverage_freshness: { scope: 'Feeds linked to this development', counts: { enabled: 1, stale: 1 },
          feeds: [{ label: source.publisher, freshness: 'stale', checked_at: source.published_at }] } };
    if (path === '/api/intelligence/personal-impact')
      assert.deepEqual(JSON.parse(options.body), { cloud: [target], packages: [], article_id: source.id, explain: false });
    return new Response(JSON.stringify(payload));
  };
  try {
    await import(`../../public/development.js?reader=${Date.now()}`);
    await until(() => document.getElementById('development-title').textContent === 'Cloud service recovery');
    assert.match(document.getElementById('development-content').textContent, /Resolved.*Timeline/);
    assert.match(document.querySelector('.reader-freshness').textContent, /1 overdue/);
    assert.equal(document.querySelector('.research-evidence a').href, source.url);
    [...document.querySelectorAll('button')].find(el => el.textContent === 'Follow development').click();
    assert.deepEqual(JSON.parse(localStorage.getItem('informa-radar-v1')).followed_events, [id]);
    document.querySelector('.impact-panel button').click();
    await until(() => document.querySelector('.impact-panel').textContent.includes('Official report matches.'));
  } finally { globalThis.fetch = previousFetch; env.close(); }
});

test('Inbox separates follow read state from server watch delivery controls', async () => {
  const markup = readFileSync(new URL('../../public/inbox.html', import.meta.url), 'utf8');
  const env = mount(markup, 'https://informa.test/inbox.html');
  const previousFetch = globalThis.fetch;
  const id = 'f'.repeat(32);
  const other = 'e'.repeat(32);
  localStorage.setItem('informa-radar-v1', JSON.stringify({ followed_events: [id] }));
  localStorage.setItem('informa-inbox-seen-v1', JSON.stringify({ [other]: '3' }));
  const calls = [];
  let snoozed = false;
  globalThis.fetch = async (path, options = {}) => {
    calls.push([path, options.method]);
    if (options.method === 'PUT') snoozed = JSON.parse(options.body).action === 'snooze';
    const payload = path.startsWith('/api/intelligence/events?') ?
      { events: [{ id, title: 'Followed cloud outage', digest_version: '2' }] } :
      { available: true, active: true, controls_ready: true, unread: 0, alerts: [],
        watches: [{ id: 'cloud', query: 'Cloud alerts', delivery: { muted: false, snoozed_until: snoozed ? 1893456000 : null } }] };
    return new Response(JSON.stringify(payload));
  };
  try {
    await import(`../../public/reader-inbox.js?reader=${Date.now()}`);
    await until(() => document.querySelector('#inbox-follows button'));
    assert.equal(document.querySelector('#inbox-follows a').search, `?id=${id}`);
    document.querySelector('#inbox-follows button').click();
    await until(() => document.getElementById('inbox-follow-status').textContent === '0 unread followed developments');
    assert.deepEqual(JSON.parse(localStorage.getItem('informa-inbox-seen-v1')), { [other]: '3', [id]: '2' });
    document.querySelector('#inbox-watches button').click();
    await until(() => document.querySelector('#inbox-watches button').textContent === 'Resume');
    assert.ok(calls.some(([path, method]) => path === '/api/intelligence/inbox/watches/cloud/delivery' && method === 'PUT'));
    assert.equal(document.querySelector('#inbox-email-label + p + a').pathname, '/research.html');
  } finally { globalThis.fetch = previousFetch; env.close(); }
});

test('delivery receipt refresh never sends a brief and clears private status after verification expires', async () => {
  const env = mount();
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  const requests = [];
  let expired = false;
  try {
    const receipt = createDeliveryStatus(async url => {
      requests.push(url);
      if (expired) throw Object.assign(new Error('Verify your inbox'), { status: 401 });
      return { status: 'delivered', remaining_today: 2, updated_at: '2026-11-17T10:00:00Z' };
    }, value => value);
    const preview = 'receipt-preview-123456789012345678';
    receipt.track(preview);
    await until(() => !document.getElementById('world-receipt').hidden);
    assert.match(document.querySelector('#world-receipt .receipt-state').textContent, /Delivery confirmed/);
    assert.match(document.querySelector('#email-receipt .receipt-detail').textContent, /2 of 3/);
    assert.equal(sessionStorage.getItem('informa-mail-receipt'), preview);
    expired = true;
    document.querySelector('#email-receipt button').click();
    await until(() => document.getElementById('world-receipt').hidden);
    assert.equal(document.getElementById('email-receipt').hidden, true);
    assert.equal(sessionStorage.getItem('informa-mail-receipt'), null);
    assert(requests.every(url => url === `/api/mail/delivery/${preview}`));
  } finally { env.close(); }
});

test('inline story questions cite source evidence and discard an answer after changing story', async () => {
  const env = mount();
  document.getElementById('dossier-drawer').showModal();
  let finish, body;
  const answer = { answer: { claims: [{ text: 'The publisher reported an API change.', source_ids: ['story-1'] }], limitations: 'Publisher excerpt only.' },
    evidence: [{ id: 'story-1', publisher: 'Original publisher', url: 'https://publisher.example/change' }] };
  try {
    const question = createStoryQuestion(async (url, options) => {
      assert.equal(url, '/api/intelligence/converse');
      body = JSON.parse(options.body);
      return new Promise(resolve => { finish = resolve; });
    }, () => ({ article: { id: 'story-1' }, coverage: [{ id: 'related-1' }] }), (url, text) => {
      const link = document.createElement('a'); link.href = url; link.textContent = text; return link;
    });
    const submit = () => document.getElementById('story-question-form').dispatchEvent(new window.Event('submit', { cancelable: true }));
    document.getElementById('dossier-ask').click();
    assert.equal(document.activeElement.id, 'story-question');
    document.getElementById('story-question').value = 'What changed?';
    submit();
    assert.deepEqual(body.context_ids, ['story-1', 'related-1']);
    assert.equal(body.context_only, true);
    finish(answer);
    await until(() => document.querySelector('#story-question-answer a'));
    assert.equal(document.querySelector('#story-question-answer a').href, answer.evidence[0].url);
    submit();
    question.reset();
    finish(answer);
    await delay(0);
    assert.equal(document.getElementById('story-question-answer').textContent, '');
    assert.equal(document.getElementById('story-question-panel').hidden, true);
  } finally { env.close(); }
});

test('followed authors and individual feeds survive reload and incremental catalogue updates', () => {
  const env = mount();
  try {
    const root = document.getElementById('personalization');
    const prefs = createPreferences(root, () => {});
    prefs.update(catalog);
    const article = { author_key: authorKey, author: 'A Writer', publisher: 'CodeX on Medium', source_id: 'medium-codex' };
    prefs.toggleAuthor(article); prefs.togglePublication(article);
    assert.deepEqual(prefs.request().authors, [authorKey]);
    assert.deepEqual(prefs.request().sources, ['medium-codex']);
    const saved = localStorage.getItem('informa-interests-v1');
    root.innerHTML = new JSDOM(html).window.document.getElementById('personalization').innerHTML;
    localStorage.setItem('informa-interests-v1', saved);
    const restored = createPreferences(root, () => {});
    restored.update({ topics: catalog.topics, subjects: catalog.subjects });
    restored.update(catalog);
    assert.equal(root.querySelector(`input[value="${authorKey}"]`).checked, true);
    assert.equal(root.querySelector('input[value="medium-codex"]').checked, true);
    root.querySelector('form').dispatchEvent(new window.Event('submit', { cancelable: true }));
    assert.deepEqual(restored.request().authors, [authorKey]);
    assert.deepEqual(restored.request().sources, ['medium-codex']);
  } finally { env.close(); }
});

test('licensed reading renderer keeps code and safe links while removing active content', () => {
  const env = mount();
  try {
    const body = document.createElement('div');
    body.append(...readingContent('<h2 onclick="bad()">Heading</h2><p>Article <a href="https://author.example/post" onmouseover="bad()">source</a></p><pre><code>print("safe")</code></pre><script>bad()</script><img src="https://tracking.example/pixel"><svg onload="bad()"></svg><a href="javascript:bad()">unsafe link</a>'));
    assert.equal(body.querySelector('h2').textContent, 'Heading');
    assert.equal(body.querySelector('code').textContent, 'print("safe")');
    assert.equal(body.querySelector('a').rel, 'noopener noreferrer');
    assert.equal(body.querySelectorAll('script,img,svg,iframe').length, 0);
    assert.equal(body.querySelectorAll('[onclick],[onmouseover]').length, 0);
    assert.equal(body.querySelectorAll('a')[1].hasAttribute('href'), false);
  } finally { env.close(); }
});

test('actual Reading Room module opens permitted text, follows its author and refreshes revoked access', async () => {
  const env = mount(html, 'https://informa.test/?view=feed');
  const fetchBefore = globalThis.fetch, intervalBefore = globalThis.setInterval;
  globalThis.setInterval = () => 0;
  const article = { id: 'test-article', title: 'A useful Python guide', description: 'The source excerpt.', cleanSummary: 'The source excerpt.',
    source: 'medium', source_id: 'medium-codex', publisher: 'CodeX on Medium', sourceName: 'CodeX on Medium',
    url: 'https://medium.com/codex/test', sourceUrl: 'https://medium.com/codex/test', published_at: new Date().toISOString(),
    topic: 'software', category: 'software', has_excerpt: true, author: 'A Writer', author_key: authorKey, subjects: ['cloud'] };
  const coverage = { ...article, id: 'comparison', title: 'The same project covered elsewhere',
    source: 'ars-technica', source_id: 'ars-technica', publisher: 'Ars Technica',
    url: 'https://arstechnica.com/comparison', related_reason: 'Closely matching headlines' };
  let permitted = true;
  globalThis.fetch = async (url) => {
    const path = String(url);
    const data = path.startsWith('/api/news') ? { ...catalog, articles: [article], total: 1, sources: catalog.sources, facets: {} } :
      path.startsWith('/api/articles/') ? { article: { ...article, reading_access: { mode: permitted ? 'full_text' : 'excerpt', label: permitted ? 'Full article · with permission' : 'Publisher excerpt' } }, related: [coverage], coverage: [coverage],
        reading: permitted ? { html: '<p>Licensed body supplied by the author.</p>', attribution: 'A Writer' } : null,
        development_id: 'a'.repeat(32),
        summary: { limited_source: !permitted, highlights: permitted ? ['Licensed body supplied by the author.'] : [] },
        also_indexed_by: [{ id: 'medium-codex', label: 'CodeX feed' }],
        reading_notice: permitted ? 'Shared with permission.' : 'Publisher-supplied excerpt.' } :
      path === '/api/headlines' ? { articles: [], coverage: [] } : path === '/api/trending' ? { trending: [] } : {};
    return new Response(JSON.stringify(data), { status: 200 });
  };
  try {
    await import(`../../public/app.js?test=${Date.now()}`);
    await until(() => document.querySelector('.card-dossier-btn'));
    document.querySelector('.card-dossier-btn').click();
    await until(() => document.getElementById('dossier-full-body').textContent.includes('Licensed body'));
    assert.equal(document.getElementById('dossier-highlights').hidden, false);
    assert.match(document.getElementById('dossier-highlights-basis').textContent, /shared with permission/);
    assert.equal(document.getElementById('dossier-indexed-by').textContent, 'CodeX feed');
    document.getElementById('dossier-follow-story').click();
    assert.deepEqual(JSON.parse(localStorage.getItem('informa-radar-v1')).followed_events, ['a'.repeat(32)]);
    document.getElementById('dossier-highlights').open = true;
    document.getElementById('dossier-follow-author').click();
    assert.equal(JSON.parse(localStorage.getItem('informa-interests-v1')).authors[0], authorKey);
    document.getElementById('dossier-close').click();
    permitted = false;
    document.querySelector('.card-dossier-btn').click();
    await until(() => document.getElementById('dossier-reading-access').textContent === 'Publisher excerpt');
    assert.equal(document.getElementById('dossier-full-body').hidden, true);
    assert.equal(document.getElementById('dossier-full-body').textContent, '');
    assert.equal(document.getElementById('dossier-highlights').hidden, true);
    assert.equal(document.getElementById('dossier-highlights').open, false);
    assert.equal(document.getElementById('dossier-highlights-list').textContent, '');
    assert.equal(document.querySelectorAll('#dossier-matches .related-story').length, 1);
    assert.equal(document.getElementById('dossier-related-section').hidden, true);
    document.getElementById('dossier-coverage-brief').click();
    assert.equal(document.getElementById('dossier-drawer').open, false);
    assert.match(document.getElementById('pin-status').textContent, /2 stories pinned/);
  } finally { globalThis.fetch = fetchBefore; globalThis.setInterval = intervalBefore; env.close(); }
});

test('For You sends the same search and filters shown in the Reading Room', async () => {
  const env = mount(html, 'https://informa.test/?view=for-you&language=ar&region=MENA&window=7d&q=تمويل');
  const fetchBefore = globalThis.fetch, intervalBefore = globalThis.setInterval;
  globalThis.setInterval = () => 0;
  const requests = [];
  const article = { id: 'arabic-fixture', title: 'ExampleCorp تعلن عن جولة تمويل',
    cleanSummary: 'ExampleCorp توسع عملياتها', language: 'ar', source: 'entarabi-ar', source_id: 'entarabi-ar',
    publisher: 'entARABI', url: 'https://entarabi.com/example-fixture', published_at: new Date().toISOString(),
    topic: 'startups', category: 'startups', has_excerpt: true, summary_basis: 'publisher_excerpt' };
  globalThis.fetch = async (url, options) => {
    const path = String(url);
    if (path === '/api/recommendations') requests.push(JSON.parse(options.body));
    const data = path === '/api/sources' ? { ...catalog } : path === '/api/authors' ? { authors: [] } :
      path === '/api/recommendations' ? { articles: [article], total_candidates: 1 } : {};
    return new Response(JSON.stringify(data), { status: 200 });
  };
  try {
    await import(`../../public/app.js?recommendations=${Date.now()}`);
    await until(() => requests.length > 0 && document.getElementById('stories').getAttribute('aria-busy') === 'false');
    assert.equal(document.getElementById('feed-controls').hidden, false);
    assert.equal(requests[0].q, 'تمويل');
    assert.equal(requests[0].scope.region, 'MENA');
    assert.equal(requests[0].scope.language, 'ar');
    assert.equal(requests[0].scope.hours, 168);
    assert.equal(document.querySelector('#stories h3').dir, 'rtl');
    assert.equal(document.querySelector('#stories .story-summary').dir, 'rtl');
    const search = document.getElementById('search');
    search.value = 'شركة ناشئة';
    document.getElementById('story-search').dispatchEvent(new window.Event('submit', { cancelable: true }));
    await until(() => requests.some(request => request.q === 'شركة ناشئة') &&
      document.getElementById('stories').getAttribute('aria-busy') === 'false');
    assert.equal(new URL(location.href).searchParams.get('q'), 'شركة ناشئة');
  } finally { globalThis.fetch = fetchBefore; globalThis.setInterval = intervalBefore; env.close(); }
});

test('opening the Saved view directly renders bookmarks from browser storage', async () => {
  const env = mount(html, 'https://informa.test/?view=saved#reading-room');
  const fetchBefore = globalThis.fetch, intervalBefore = globalThis.setInterval;
  globalThis.setInterval = () => 0;
  const requests = [];
  globalThis.fetch = async (url) => {
    requests.push(String(url));
    return new Response('{}', { status: 200 });
  };
  try {
    localStorage.setItem('informa-saved-v1', JSON.stringify([{
      id: 'saved-article', title: 'A saved engineering story', url: 'https://example.org/article',
      publisher: 'Example', source: 'engineering', topic: 'software', category: 'software',
      published_at: new Date().toISOString(),
    }]));
    await import(`../../public/app.js?saved=${Date.now()}`);
    assert.equal(document.querySelector('#stories h3')?.textContent, 'A saved engineering story');
    assert.equal(document.getElementById('view-saved').getAttribute('aria-pressed'), 'true');
    assert(!requests.some(path => path.startsWith('/api/news')));
    // Let start-up requests (headlines, curiosity, mail config) settle before the DOM is torn down.
    await delay(50);
  } finally { globalThis.fetch = fetchBefore; globalThis.setInterval = intervalBefore; env.close(); }
});

test('daily briefing navigation, read state and modal brief pins work together', async () => {
  const env = mount(html, 'https://informa.test/?view=feed');
  const fetchBefore = globalThis.fetch, intervalBefore = globalThis.setInterval;
  globalThis.setInterval = () => 0;
  const articles = [1, 2].map(index => ({ id: `brief-${index}`, title: `An attributed technology update ${index}`,
    description: 'The publisher supplied this excerpt.', cleanSummary: 'The publisher supplied this excerpt.',
    publisher: 'Original publisher', source: 'medium', source_id: 'medium-codex', topic: 'software', category: 'software',
    published_at: new Date().toISOString(), url: `https://example.org/update-${index}`, has_excerpt: true,
    coverage_count: 2, coverage_publishers: ['Original publisher', 'Other publisher'] }));
  const sources = [
    ...catalog.sources,
    { id: 'failed', label: 'Second publisher', enabled: true, available: false, freshness: 'failed' },
    { id: 'stale', label: 'Third publisher', enabled: true, available: true, freshness: 'stale' },
    { id: 'paused', label: 'Paused publisher', enabled: false },
  ];
  globalThis.fetch = async url => {
    const path = String(url);
    const data = path === '/api/briefing' ? { articles, publishers: 8 } : path.startsWith('/api/news') ?
      { ...catalog, articles, total: 2, sources, facets: {},
        freshness: { status: 'stale', counts: { enabled: 3, fresh: 0, failed: 1, stale: 2 } } } : {};
    return new Response(JSON.stringify(data), { status: 200 });
  };
  try {
    await import(`../../public/app.js?briefing=${Date.now()}`);
    await until(() => document.querySelector('#stories .story'));
    assert.equal(document.getElementById('source-health-label').textContent, '3 feeds tracked');
    document.getElementById('source-health-button').click();
    const popover = document.getElementById('source-popover');
    assert.match(popover.textContent, /Second publisher/);
    assert.doesNotMatch(popover.textContent, /Check overdue|Last check failed|Paused publisher/);
    assert.equal(document.getElementById('failed-alert'), null);
    document.getElementById('source-popover-close').click();
    document.querySelector('[data-workspace-view="briefing"]').click();
    await until(() => document.getElementById('stories').getAttribute('aria-busy') === 'false');
    assert.equal(document.getElementById('reading-title').textContent, 'Today');
    assert.equal(document.getElementById('briefing-intro').hidden, false);
    assert.equal(new URL(location.href).searchParams.get('view'), 'briefing');
    assert.equal(document.querySelector('#stories .coverage-count').textContent, '2 publishers');
    document.getElementById('briefing-pin').click();
    assert.equal(document.querySelectorAll('#selected-stories .selected-item').length, 2);
    assert.equal(document.getElementById('composer').getAttribute('aria-modal'), 'true');
    assert.equal(document.getElementById('workspace-navigation').inert, true);
    document.getElementById('composer').dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    assert.equal(document.getElementById('composer').classList.contains('open'), false);
    assert.equal(document.getElementById('workspace-navigation').inert, false);
    document.getElementById('hide-read').click();
    document.getElementById('mark-all-read').click();
    assert.equal(document.querySelectorAll('#stories .story').length, 0);
    assert(document.getElementById('stories').textContent.includes('up to date'));
    assert.equal(localStorage.getItem('informa-hide-read'), 'true');
    document.getElementById('hide-read').click();
    assert.equal(document.querySelectorAll('#stories .story').length, 2);
  } finally { globalThis.fetch = fetchBefore; globalThis.setInterval = intervalBefore; env.close(); }
});

test('the tracker email link opens and scrolls to the daily delivery form', async () => {
  const env = mount(html, 'https://informa.test/?view=briefing#daily-delivery');
  const fetchBefore = globalThis.fetch, intervalBefore = globalThis.setInterval;
  globalThis.setInterval = () => 0;
  let scrolled = false;
  const delivery = document.getElementById('daily-delivery');
  delivery.scrollIntoView = () => { scrolled = true; };
  globalThis.fetch = async path => new Response(JSON.stringify(
    path === '/api/briefing' ? { articles: [] } : path === '/api/sources' ? catalog : {},
  ), { status: 200 });
  try {
    await import(`../../public/app.js?delivery-link=${Date.now()}`);
    await until(() => scrolled);
    assert.equal(delivery.open, true);
    assert.equal(delivery.parentElement.hidden, false);
    assert.equal(location.hash, '#daily-delivery');
    await delay(50);
  } finally { globalThis.fetch = fetchBefore; globalThis.setInterval = intervalBefore; env.close(); }
});

test('returning readers open Catch up and can mark cited updates as read', async () => {
  const env = mount();
  const fetchBefore = globalThis.fetch, intervalBefore = globalThis.setInterval;
  globalThis.setInterval = () => 0;
  const lastVisit = Date.now() - 3600_000;
  localStorage.setItem('informa-catchup-checkpoint', String(lastVisit));
  localStorage.setItem('informa-interests-v1', JSON.stringify({ topics: ['software'] }));
  const requests = [];
  const article = { id: 'news', title: 'Regional network outage', publisher: 'Provider status',
    url: 'https://example.org/incident', cleanSummary: 'The provider is investigating.' };
  const first = 'a'.repeat(32), next = 'b'.repeat(32);
  globalThis.fetch = async (url, options) => {
    if (url === '/api/intelligence/catchup') {
      requests.push(JSON.parse(options.body));
      const events = requests.length > 2 ? [] : [{ id: requests.length === 1 ? first : next,
        digest_version: '2', title: requests.length === 1 ? article.title : 'Another development',
        updated_at: new Date().toISOString(), articles: [article], source_count: 2,
        change_sources: [{ change_label: 'Resolved', excerpt: 'Service has been restored.', url: article.url, publisher: article.publisher }],
      }];
      return new Response(JSON.stringify({ events, coverage_freshness: {
        counts: { enabled: 3, fresh: 2, failed: 1 }, checked_at: new Date().toISOString(),
        next_full_sweep_at: new Date(Date.now() + 3600_000).toISOString(),
      } }));
    }
    return new Response(JSON.stringify({ ...catalog, articles: [], coverage: [], trending: [] }));
  };
  try {
    await import(`../../public/app.js?returning=${Date.now()}`);
    const results = document.getElementById('home-catchup-results');
    await until(() => results.textContent.includes('Service has been restored.'));
    assert.equal(document.getElementById('reading-title').textContent, 'Catch up');
    assert.equal(requests[0].since, lastVisit / 1000);
    assert.equal(requests[0].summary_only, true);
    assert.deepEqual(requests[0].profile.preferred_topics, ['software']);
    assert.equal(document.getElementById('edition-start').dataset.editionView, 'catchup');
    assert.equal(document.getElementById('edition-followed').hidden, false);
    const edition = document.getElementById('edition-freshness');
    assert.match(edition.textContent, /Latest source check.*Next full sweep/);
    assert.doesNotMatch(edition.textContent, /Coverage partial|2 of 3/);
    assert.equal(results.querySelector('a').href, article.url);
    document.getElementById('home-catchup-mark').click();
    await until(() => results.textContent.includes('Another development'));
    assert.deepEqual(requests[1].seen, { [first]: '2' });
    document.getElementById('home-catchup-mark').click();
    await until(() => document.getElementById('home-catchup-status').textContent.includes('No new developments found in the available archive'));
    assert.deepEqual(requests[2].seen, { [first]: '2', [next]: '2' });
    assert.ok(requests.every(request => request.since === lastVisit / 1000));
    document.getElementById('home-catchup-browse').click();
    assert.equal(document.getElementById('reading-title').textContent, 'All stories');
    const input = document.getElementById('search');
    input.value = 'cloud outage';
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
    const link = new URL(document.getElementById('search-developments').href);
    assert.equal(link.searchParams.get('q'), 'cloud outage');
    assert.equal(link.searchParams.get('mode'), 'developments');
    await until(() => document.getElementById('stories').getAttribute('aria-busy') === 'false');
    document.getElementById('view-saved').click();
  } finally { globalThis.fetch = fetchBefore; globalThis.setInterval = intervalBefore; env.close(); }
});

test('a Research Desk catch-up opens in the existing verified email delivery flow', async () => {
  const env = mount(html, 'https://informa.test/?ai-catchup=1#reading-room');
  const fetchBefore = globalThis.fetch, intervalBefore = globalThis.setInterval;
  globalThis.setInterval = () => 0;
  const preview = { preview_id: 'catchup-preview-12345678901234567890', expires: Date.now() / 1000 + 600,
    source_basis: 'Publisher evidence', digest: { edition: 'catchup', introduction: { greeting: 'Your technology catch-up', introduction: 'New developments.' },
      articles: [{ title: 'Cloud outage update', publisher: 'Original publisher', topic_label: 'Cloud',
        cleanSummary: 'The provider reported a service disruption.', sourceUrl: 'https://example.org/outage',
        url: 'https://example.org/outage', summary_basis: 'publisher_excerpt' }], markdown: '# Catch-up', html: '<p>Catch-up</p>' } };
  sessionStorage.setItem('informa-ai-catchup-preview', JSON.stringify(preview));
  const deliveries = [];
  globalThis.fetch = async (url, options = {}) => {
    const path = String(url);
    let data = {};
    if (path === '/api/mail/config') data = { enabled: true, verified: true, verified_email: 'reader@example.org' };
    if (path === '/api/mail/send') { deliveries.push(JSON.parse(options.body)); data = { status: 'accepted', message: 'Accepted.' }; }
    if (path.startsWith('/api/news')) data = { ...catalog, articles: [], total: 0, facets: {} };
    return new Response(JSON.stringify(data), { status: 200 });
  };
  try {
    await import(`../../public/app.js?catchup=${Date.now()}`);
    await until(() => document.querySelector('#preview .digest-item h3')?.textContent === 'Cloud outage update');
    assert.equal(JSON.parse(sessionStorage.getItem('informa-ai-catchup-preview')), null);
    document.getElementById('preview-email').value = 'reader@example.org';
    document.getElementById('preview-send-form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    await until(() => deliveries.length === 1);
    assert.equal(deliveries[0].preview_id, preview.preview_id);
    assert.equal(document.getElementById('email-status').textContent, 'Accepted.');
  } finally { globalThis.fetch = fetchBefore; globalThis.setInterval = intervalBefore; env.close(); }
});

test('monitoring views appear in the workspace and restore their search', async () => {
  const env = mount(html, 'https://informa.test/?q=kubernetes&window=7d');
  const fetchBefore = globalThis.fetch, intervalBefore = globalThis.setInterval;
  globalThis.setInterval = () => 0;
  const requests = [];
  globalThis.fetch = async url => {
    const path = String(url);
    requests.push(path);
    const data = path.startsWith('/api/news') ? { ...catalog, articles: [], total: 0, facets: {} } : {};
    return new Response(JSON.stringify(data), { status: 200 });
  };
  try {
    await import(`../../public/app.js?monitoring=${Date.now()}`);
    await until(() => document.getElementById('stories').getAttribute('aria-busy') === 'false');
    document.getElementById('sidebar-save-view').click();
    document.getElementById('saved-view-name').value = 'Cloud watch';
    document.getElementById('saved-view-form').dispatchEvent(new window.Event('submit', { cancelable: true }));
    const monitor = document.querySelector('#sidebar-saved-views button');
    assert.equal(monitor.textContent, 'Cloud watch');
    document.getElementById('search').value = 'something else';
    monitor.click();
    await until(() => document.getElementById('stories').getAttribute('aria-busy') === 'false');
    assert.equal(document.getElementById('search').value, 'kubernetes');
    assert(requests.at(-1).includes('q=kubernetes'));
    assert.equal(JSON.parse(localStorage.getItem('informa-saved-views-v1'))[0].name, 'Cloud watch');
    document.getElementById('search').value = 'postgres';
    document.querySelector('[aria-label="Update saved view Cloud watch with current filters"]').click();
    const updated = JSON.parse(localStorage.getItem('informa-saved-views-v1'));
    assert.equal(updated.length, 1);
    assert.equal(new URLSearchParams(updated[0].parameters).get('q'), 'postgres');
    document.getElementById('search').value = '';
    document.querySelector('#sidebar-saved-views button').click();
    assert.equal(document.getElementById('search').value, 'postgres');
    await until(() => document.getElementById('stories').getAttribute('aria-busy') === 'false');
    document.getElementById('archive-search').click();
    await until(() => document.getElementById('stories').getAttribute('aria-busy') === 'false');
    assert(requests.at(-1).includes('hours=2160'));
  } finally { globalThis.fetch = fetchBefore; globalThis.setInterval = intervalBefore; env.close(); }
});

test('author workspace submits privately and owner review requires an explicit permission check', async () => {
  const page = readFileSync(new URL('../../public/contribute.html', import.meta.url), 'utf8');
  const env = mount(page, 'https://informa.test/contribute.html?article=listed-article');
  const fetchBefore = globalThis.fetch;
  let submitted = false, approved = false;
  let signedOut = false, delayList = false, finishList;
  const ident = 'b'.repeat(32), requests = [];
  const row = { id: ident, article_id: 'listed-article', article_url: 'https://author.example/article',
    author_name: 'A Writer', permission_evidence: 'The owner can verify my publishing and syndication permission.',
    state: 'pending', created: Date.now() / 1000, verified_email: 'writer@example.org' };
  globalThis.fetch = async (url, options = {}) => {
    const path = String(url); requests.push({ path, options });
    let data;
    if (path === '/api/mail/contributions/config') data = { enabled: !signedOut, verified: !signedOut, verified_email: signedOut ? null : 'writer@example.org', permission_statement: 'I have permission to share this text.', terms_version: 'test-version' };
    else if (path === '/api/mail/logout') { signedOut = true; data = {}; }
    else if (path.startsWith('/api/articles/')) data = { article: { id: 'listed-article', title: 'The original article', url: 'https://author.example/article', author: 'A Writer' } };
    else if (path === '/api/mail/contributions' && options.method === 'POST') {
      const body = JSON.parse(options.body); assert.equal(body.grant_permission, true);
      assert.equal(body.article_id, 'listed-article'); submitted = true;
      data = { id: ident, state: 'pending', message: 'Submitted for owner review.' };
    } else if (path === '/api/mail/contributions') {
      if (delayList) await new Promise(resolve => { finishList = resolve; });
      data = { submissions: submitted ? [row] : [] };
    }
    else if (path.startsWith('/api/admin/contributions?')) data = { submissions: submitted && !approved ? [row] : [], next_cursor: null };
    else if (path.endsWith('/review')) {
      assert.equal(options.headers.Authorization, 'Bearer test-owner-for-client');
      assert.equal(JSON.parse(options.body).permission_verified, true); approved = true;
      data = { id: ident, state: 'approved' };
    } else data = { ...row, body_markdown: 'The submitted Markdown text.', preview_html: '<p>The submitted article.</p><script>bad()</script>' };
    return new Response(JSON.stringify(data), { status: 200 });
  };
  try {
    await import(`../../public/contribute.js?test=${Date.now()}`);
    await until(() => !document.getElementById('contribution-fields').disabled);
    document.getElementById('contribution-body').value = 'A readable article about a working implementation. '.repeat(10);
    document.getElementById('contribution-evidence').value = 'The owner can verify my authorship and permission at the original publication.';
    document.getElementById('contribution-grant').checked = true;
    document.getElementById('contribution-form').dispatchEvent(new window.Event('submit', { cancelable: true }));
    await until(() => document.querySelector('#contribution-list .submission-card'));
    document.getElementById('editor-token').value = 'test-owner-for-client';
    document.getElementById('editor-login').dispatchEvent(new window.Event('submit', { cancelable: true }));
    await until(() => document.querySelector('#editor-list .submission-card'));
    document.querySelector('#editor-list .submission-actions button').click();
    await until(() => document.querySelector('#editor-list .submission-detail form'));
    assert.equal(document.querySelector('#editor-list .submission-preview script'), null);
    const review = document.querySelector('#editor-list .submission-detail form');
    review.querySelector('select').value = 'approve';
    review.querySelector('select').dispatchEvent(new window.Event('change'));
    review.querySelector('textarea').value = 'The rights holder permission has been checked.';
    assert.equal(review.checkValidity(), false);
    review.querySelector('input[type=checkbox]').checked = true;
    assert.equal(review.checkValidity(), true);
    review.dispatchEvent(new window.Event('submit', { cancelable: true }));
    await until(() => approved && !document.querySelector('#editor-list .submission-card'));
    assert.equal(localStorage.length, 0);
    assert.equal(document.getElementById('editor-token').value, '');
    assert.equal(requests.some(request => request.path === '/api/mail/send'), false);
    document.getElementById('editor-signout').click();
    assert.equal(document.getElementById('editor-controls').hidden, true);
    delayList = true;
    document.getElementById('contribution-reload').click();
    await until(() => finishList);
    document.getElementById('contribution-signout').click();
    await until(() => document.getElementById('contribution-identity').hidden);
    finishList();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(document.querySelector('#contribution-list .submission-card'), null);
    assert.equal(document.getElementById('contribution-body').value, '');
  } finally { globalThis.fetch = fetchBefore; env.close(); }
});


test('coverage comparison shows source evidence and sorts timestamps without reordering results', () => {
  const env = mount();
  const dialog = document.getElementById('coverage-dialog');
  const trigger = document.getElementById('view-briefing');
  const story = { title: 'A technology release', source_count: 4, sources: [
    { publisher: 'Later report', label: 'A release update', article_id: 'release-2', published_at: '2026-11-18T13:00:00Z',
      coverage: 'reporting', url: 'https://publisher.example/update', excerpt: 'The publisher excerpt.' },
    { publisher: 'Earlier report', label: 'A release announced', article_id: 'release-1', published_at: '2026-11-18T12:00:00Z',
      coverage: 'publisher', url: 'https://official.example/announcement' },
  ] };
  try {
    const open = createCoverageDialog(dialog, { readableTime: value => value, externalLink(url, text) {
      const link = document.createElement('a'); link.href = url; link.textContent = text; return link;
    } });
    open(story, trigger);
    assert.equal(dialog.open, true);
    assert.equal(document.activeElement.id, 'coverage-dialog-title');
    assert.match(dialog.querySelector('#coverage-dialog-note').textContent, /Showing 2 of 4 matched publisher groups/);
    assert.match(dialog.querySelector('.coverage-publication').textContent, /The publisher excerpt/);
    assert.match(dialog.querySelector('a[aria-label="Open Later report in reader"]').getAttribute('href'), /article=release-2/);
    dialog.querySelector('#coverage-timeline').click();
    assert.equal(dialog.querySelector('.coverage-publication strong').textContent, 'Earlier report');
    assert.match(dialog.querySelector('.coverage-publication').textContent, /Headline and source link available/);
    assert.equal(story.sources[0].publisher, 'Later report');
    dialog.close();
    assert.equal(document.activeElement, trigger);
  } finally { env.close(); }
});
