import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { readingGroups } from '../../public/privacy-data.js';

const markup = readFileSync(new URL('../../public/research.html', import.meta.url), 'utf8');
const script = readFileSync(new URL('../../public/research.js', import.meta.url), 'utf8').replace(/^import[^\n]+\n/, '');

test('article analysis keeps citations in the Research Desk and preserves original attribution', async () => {
  const dom = new JSDOM(markup, { url: 'https://informa.test/research.html?article=s1', runScripts: 'outside-only' });
  const { window } = dom;
  const requests = [];
  window.readingGroups = readingGroups;
  window.fetch = async (path, options) => {
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
    window.eval(script);
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(requests, [{ article_id: 's1', mode: 'analyze' }]);
    const citation = window.document.querySelector('a[aria-label="Source 1"]');
    assert.equal(citation.href, 'https://informa.test/research.html?article=s1#research-source-1');
    const evidence = window.document.querySelector(citation.hash);
    assert.match(evidence.textContent, /Official advisory/);
    assert.equal(evidence.querySelector('h3 > a').href, 'https://example.org/advisory');
    assert.equal(evidence.lastElementChild.href, 'https://informa.test/?article=s1#reading-room');
  } finally {
    window.close();
  }
});
