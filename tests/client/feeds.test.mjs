import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { searchFeedUrl } from '../../public/feeds-page.js';

test('search feed links are encoded and bounded', () => {
  assert.equal(searchFeedUrl('  Nvidia   Blackwell ', 'https://getinformdaily.com'),
    'https://getinformdaily.com/feeds/search.xml?q=Nvidia%20Blackwell');
  assert.equal(searchFeedUrl('a&b=<c>', 'https://x.test'), 'https://x.test/feeds/search.xml?q=a%26b%3D%3Cc%3E');
  assert.equal(searchFeedUrl('x'), '');
  assert.equal(new URL(searchFeedUrl('y'.repeat(200), 'https://x.test')).searchParams.get('q').length, 80);
});

test('the feeds page lists topic and technology feeds and builds a search feed', async () => {
  const html = readFileSync(new URL('../../public/feeds.html', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'https://getinformdaily.com/feeds.html' });
  globalThis.document = dom.window.document;
  globalThis.location = dom.window.location;
  try {
    const { startFeedsPage } = await import(`../../public/feeds-page.js?page=${Date.now()}`);
    await startFeedsPage({ fetcher: async () => ({ ok: true, json: async () => ({
      topics: [{ title: 'AI & Machine Learning', path: '/feeds/topic/ai.xml' }],
      technologies: [{ title: 'Kubernetes', path: '/feeds/technology/kubernetes.xml' }] }) }) });
    const doc = dom.window.document;
    assert.equal(doc.querySelector('#feeds-topics a').getAttribute('href'), '/feeds/topic/ai.xml');
    assert.equal(doc.querySelector('#feeds-technologies a').textContent, 'Kubernetes');
    doc.getElementById('feeds-search-input').value = 'OpenAI';
    doc.getElementById('feeds-search-form').dispatchEvent(new dom.window.Event('submit', { cancelable: true }));
    assert.equal(doc.querySelector('#feeds-search-result a').href, 'https://getinformdaily.com/feeds/search.xml?q=OpenAI');
  } finally {
    delete globalThis.document;
    delete globalThis.location;
    dom.window.close();
  }
});
