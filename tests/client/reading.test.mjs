import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { createPreferences } from '../../public/preferences.js';
import { readingContent } from '../../public/reading-content.js';

const html = readFileSync(new URL('../../public/index.html', import.meta.url), 'utf8');
const authorKey = `author-${'a'.repeat(32)}`;
const catalog = { topics: { software: 'Software' }, subjects: { cloud: 'Cloud' }, sources: [
  { id: 'medium-codex', source: 'medium', label: 'CodeX on Medium', enabled: true },
], authors: [{ id: authorKey, name: 'A Writer', publisher: 'CodeX on Medium' }] };

function mount(markup = html, url = 'https://informa.test/') {
  const dom = new JSDOM(markup, { url });
  dom.window.matchMedia = query => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} });
  const previous = new Map();
  for (const name of ['window', 'document', 'localStorage', 'DOMParser', 'Node', 'location', 'history', 'navigator', 'getComputedStyle', 'CSS', 'matchMedia']) {
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
  let permitted = true;
  globalThis.fetch = async (url) => {
    const path = String(url);
    const data = path.startsWith('/api/news') ? { ...catalog, articles: [article], total: 1, sources: catalog.sources, facets: {} } :
      path.startsWith('/api/articles/') ? { article: { ...article, reading_access: { mode: permitted ? 'full_text' : 'excerpt', label: permitted ? 'Full article · with permission' : 'Publisher excerpt' } }, related: [],
        reading: permitted ? { html: '<p>Licensed body supplied by the author.</p>', attribution: 'A Writer' } : null,
        reading_notice: permitted ? 'Shared with permission.' : 'Publisher-supplied excerpt.' } :
      path === '/api/headlines' ? { articles: [], coverage: [] } : path === '/api/trending' ? { trending: [] } : {};
    return new Response(JSON.stringify(data), { status: 200 });
  };
  try {
    await import(`../../public/app.js?test=${Date.now()}`);
    await until(() => document.querySelector('.card-dossier-btn'));
    document.querySelector('.card-dossier-btn').click();
    await until(() => document.getElementById('dossier-full-body').textContent.includes('Licensed body'));
    document.getElementById('dossier-follow-author').click();
    assert.equal(JSON.parse(localStorage.getItem('informa-interests-v1')).authors[0], authorKey);
    document.getElementById('dossier-close').click();
    permitted = false;
    document.querySelector('.card-dossier-btn').click();
    await until(() => document.getElementById('dossier-reading-access').textContent === 'Publisher excerpt');
    assert.equal(document.getElementById('dossier-full-body').hidden, true);
    assert.equal(document.getElementById('dossier-full-body').textContent, '');
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
