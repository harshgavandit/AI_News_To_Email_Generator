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

test('coverage comparison shows available evidence and sorts publication timestamps without reordering the results', () => {
  const env = mount();
  const dialog = document.getElementById('coverage-dialog');
  const trigger = document.getElementById('masthead-briefing');
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
  const env = mount();
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

test('the Saved view searches and filters bookmarks locally without replacing the feed filters', async () => {
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
      publisher: 'Revista Técnica', source: 'engineering', topic: 'software', category: 'software',
      published_at: new Date().toISOString(),
    }, {
      id: 'outage', title: 'A saved outage story', url: 'https://example.org/status',
      publisher: 'Other publisher', source: 'engineering', topic: 'outages', category: 'outages',
      published_at: new Date().toISOString(),
    }]));
    localStorage.setItem('informa-read-v1', JSON.stringify(['outage']));
    await import(`../../public/app.js?saved=${Date.now()}`);
    assert.equal(document.querySelectorAll('#stories .story').length, 2);
    const find = document.getElementById('saved-search');
    find.value = 'tecnica engineering';
    find.dispatchEvent(new window.Event('input', { bubbles: true }));
    assert.equal(document.querySelector('#stories h3')?.textContent, 'A saved engineering story');
    const reading = document.getElementById('saved-read-filter');
    reading.value = 'read';
    reading.dispatchEvent(new window.Event('change', { bubbles: true }));
    assert.equal(document.querySelectorAll('#stories .story').length, 0);
    assert.match(document.querySelector('#stories').textContent, /No saved stories match/);
    document.querySelector('#stories .reading-empty button').click();
    assert.equal(document.querySelectorAll('#stories .story').length, 2);
    assert.equal(document.activeElement, find);
    assert.equal(document.getElementById('search').value, '');
    assert.equal(document.getElementById('view-saved').getAttribute('aria-pressed'), 'true');
    assert(!requests.some(path => path.startsWith('/api/news')));
  } finally { globalThis.fetch = fetchBefore; globalThis.setInterval = intervalBefore; env.close(); }
});

test('daily briefing navigation, read state and modal brief pins work together', async () => {
  const env = mount();
  const fetchBefore = globalThis.fetch, intervalBefore = globalThis.setInterval;
  globalThis.setInterval = () => 0;
  const articles = [1, 2].map(index => ({ id: `brief-${index}`, title: `An attributed technology update ${index}`,
    description: 'The publisher supplied this excerpt.', cleanSummary: 'The publisher supplied this excerpt.',
    publisher: 'Original publisher', source: 'medium', source_id: 'medium-codex', topic: 'software', category: 'software',
    published_at: new Date().toISOString(), url: `https://example.org/update-${index}`, has_excerpt: true,
    coverage_count: 2, coverage_publishers: ['Original publisher', 'Other publisher'] }));
  globalThis.fetch = async url => {
    const path = String(url);
    const data = path === '/api/briefing' ? { articles, publishers: 8 } : path.startsWith('/api/news') ?
      { ...catalog, articles, total: 2, sources: catalog.sources, facets: {} } : {};
    return new Response(JSON.stringify(data), { status: 200 });
  };
  try {
    await import(`../../public/app.js?briefing=${Date.now()}`);
    await until(() => document.querySelector('#stories .story'));
    document.querySelector('[data-workspace-view="briefing"]').click();
    await until(() => document.getElementById('stories').getAttribute('aria-busy') === 'false');
    assert.equal(document.getElementById('reading-title').textContent, 'Daily briefing');
    assert.equal(document.getElementById('briefing-intro').hidden, false);
    assert.equal(new URL(location.href).searchParams.get('view'), 'briefing');
    assert.equal(document.querySelector('#stories .coverage-count').textContent, '2 publishers');
    assert.equal(document.getElementById('briefing-progress-meter').max, 2);
    assert.equal(document.getElementById('briefing-progress-meter').value, 0);
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
    assert.equal(document.getElementById('briefing-progress-meter').value, 2);
    assert(document.getElementById('stories').textContent.includes('up to date'));
    assert.equal(localStorage.getItem('informa-hide-read'), 'true');
    assert.equal(document.activeElement.id, 'undo-mark-read');
    document.getElementById('undo-mark-read').click();
    assert.equal(document.querySelectorAll('#stories .story').length, 2);
    assert.equal(document.getElementById('briefing-progress-meter').value, 0);
    assert.equal(document.activeElement.id, 'mark-all-read');
    document.getElementById('hide-read').click();
    assert.equal(document.querySelectorAll('#stories .story').length, 2);
  } finally { globalThis.fetch = fetchBefore; globalThis.setInterval = intervalBefore; env.close(); }
});

test('last-visit catch-up uses the browser cutoff, cites reports and returns to the original feed', async () => {
  const env = mount(html, 'https://informa.test/?q=network&view=catchup#reading-room');
  const fetchBefore = globalThis.fetch, intervalBefore = globalThis.setInterval;
  globalThis.setInterval = () => 0;
  const cutoff = new Date(Date.now() - 2 * 3600_000);
  const asOf = new Date();
  const story = { id: 'new-network', title: 'Publisher confirms a network recovery', publisher: 'Infrastructure Journal',
    url: 'https://publisher.example/network-recovery', description: 'The publisher reports connections were restored.',
    source: 'medium', kind: 'news', topic: 'software', published_at: new Date(cutoff.getTime() + 1800_000).toISOString() };
  const requests = [];
  localStorage.setItem('informa-visit-history-v1', JSON.stringify({
    startedAt: cutoff.getTime() - 1000, lastActivityAt: cutoff.getTime(), previousAt: null,
  }));
  globalThis.fetch = async (url, options) => {
    const path = String(url);
    if (path.endsWith('/visit-catchup')) {
      const body = JSON.parse(options.body);
      requests.push(body);
      const data = {
        since: cutoff.toISOString(), as_of: asOf.toISOString(), window: 'since_visit',
        evidence: [{
          id: story.id, title: story.title, publisher: story.publisher, url: story.url,
          published_at: story.published_at, excerpt: story.description, change_type: 'published',
        }],
        answer: body.analyze ? { claims: [{ text: 'Connections were restored.', source_ids: [story.id],
          quotes: [story.description], kind: 'fact' }] } : null,
      };
      return new Response(JSON.stringify(data), { status: 200 });
    }
    if (path.endsWith('/articles/' + story.id)) return new Response(JSON.stringify({ article: story }), { status: 200 });
    return new Response(JSON.stringify({ ...catalog, articles: [story], total: 1 }), { status: 200 });
  };
  try {
    await import(`../../public/app.js?visit-catchup=${Date.now()}`);
    await until(() => document.querySelector('#visit-catchup-content a[href="' + story.url + '"]'));
    assert.equal(requests.length, 1);
    assert.equal(requests[0].since, cutoff.toISOString());
    assert.equal(requests[0].analyze, false);
    assert.equal(document.getElementById('reading-title').textContent, 'Since your last visit');
    assert.equal(document.getElementById('stories').hidden, true);
    const aiButton = [...document.querySelectorAll('#visit-catchup-content button')].find(button => button.textContent === 'Summarize with AI');
    aiButton.click();
    await until(() => document.querySelector('#visit-catchup-content .visit-catchup-answer a'));
    assert.deepEqual(requests[1], { since: cutoff.toISOString(), as_of: asOf.toISOString(), analyze: true });
    assert.equal(document.querySelector('#visit-catchup-content .visit-catchup-answer a').href, story.url);
    const withinReader = document.querySelector('#visit-catchup-content a[href*="article=new-network"]');
    withinReader.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
    await until(() => document.getElementById('dossier-drawer').open);
    assert.equal(document.getElementById('dossier-title').textContent, story.title);
    document.getElementById('dossier-drawer').close();
    document.getElementById('view-feed').click();
    assert.equal(document.getElementById('visit-catchup').hidden, true);
    assert.equal(document.getElementById('stories').hidden, false);
    assert.equal(document.getElementById('search').value, 'network');
    assert.equal(new URL(location.href).searchParams.has('view'), false);
    await until(() => document.getElementById('stories').getAttribute('aria-busy') === 'false' &&
      document.querySelector('#stories [data-story-card-id="new-network"]'));
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
  const env = mount(page, 'https://informa.test/contribute.html');
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
    const lookup = document.getElementById('article-lookup');
    const input = document.getElementById('contribution-article');
    await until(() => !document.getElementById('contribution-identity').hidden);
    assert.equal(document.getElementById('contribution-fields').hidden, true);
    input.value = 'https://publisher.example/?article=listed-article';
    lookup.dispatchEvent(new window.Event('submit', { cancelable: true }));
    assert.equal(requests.some(({path}) => path.startsWith('/api/articles/')), false);
    input.value = 'https://informa.test/?article=listed-article#reading-room';
    lookup.dispatchEvent(new window.Event('submit', { cancelable: true }));
    await until(() => !document.getElementById('contribution-fields').disabled);
    assert.equal(document.getElementById('contribution-fields').hidden, false);
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
