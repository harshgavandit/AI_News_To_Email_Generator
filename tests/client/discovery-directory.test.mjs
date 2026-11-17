import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';
import { JSDOM } from 'jsdom';

test('source coverage and article checks expose real results and recover after errors', async () => {
  const dom = new JSDOM(readFileSync(new URL('../../public/sources.html', import.meta.url), 'utf8'), {url: 'https://informa.test/sources.html'});
  const previous = new Map();
  for (const key of ['document', 'window', 'location', 'history', 'fetch']) previous.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
  for (const key of ['document', 'window', 'location', 'history']) globalThis[key] = dom.window[key];
  let fail = false, checks = 0;
  globalThis.fetch = async url => {
    let data;
    if (url === '/api/sources') data = {sources: [{id: 'practicalai', label: 'Practical AI', source: 'practicalai', kind: 'podcast',
      format: 'podcast', topic: 'ai', region: 'Global', language: 'en', coverage: 'article', freshness: 'fresh',
      enabled: true, available: true, refresh_minutes: 60, feed_url: 'https://publisher.example/feed'}]};
    else if (url === '/api/discovery/coverage') data = {topics: [{id: 'security', label: 'Cybersecurity', articles_24h: 12, feeds: 3, fresh_feeds: 2, gap: 'checks_overdue'}],
      formats: [{id: 'podcast', label: 'Podcasts', sources: 5}], attention: {failed_sources: 1, overdue_sources: 2, quiet_sources: 4}};
    else if (url.includes('/health')) data = {history: {checks: 4, successful: 3, hours: 24, average_duration_ms: 250}};
    else {
      checks++;
      assert.equal(new URL(url, 'https://informa.test').searchParams.get('url'), 'https://publisher.example/story');
      if (fail) return new Response(JSON.stringify({detail: 'Try again later.'}), {status: 503});
      data = {status: 'indexed', articles: [{id: 'real-id', title: '<img src=x onerror=bad()> Source title'}], sources: []};
    }
    return new Response(JSON.stringify(data), {status: 200});
  };
  async function until(check) { for (let n = 0; n < 100; n++) { if (check()) return; await delay(5); } assert.fail('UI did not settle'); }
  try {
    await import(`../../public/sources.js?coverage-test=${Date.now()}`);
    await until(() => document.querySelector('.coverage-topic'));
    assert.match(document.querySelector('.coverage-topic').textContent, /12 stories.*2\/3 feeds current/);
    assert.match(document.querySelector('.coverage-gap').textContent, /need attention/);
    assert.match(document.querySelector('#coverage-attention').textContent, /Failed checks: 1.*Overdue checks: 2.*Sources quiet for 30 days: 4/);
    assert.equal(document.querySelector('#coverage-attention').hidden, false);
    document.querySelector('#coverage-formats button').click();
    assert.equal(document.getElementById('source-format').value, 'podcast');
    const sourceHistory = document.querySelector('.source-history');
    sourceHistory.open = true;
    sourceHistory.dispatchEvent(new dom.window.Event('toggle'));
    await until(() => sourceHistory.textContent.includes('3 of 4 checks'));
    document.getElementById('story-check-url').value = 'https://publisher.example/story';
    const form = document.getElementById('story-check-form');
    form.dispatchEvent(new dom.window.Event('submit', {cancelable: true}));
    await until(() => !form.querySelector('button').disabled);
    assert.match(document.getElementById('story-check-status').textContent, /indexed/);
    assert.equal(document.querySelector('.coverage-match').getAttribute('href'), '/?article=real-id#reading-room');
    assert.equal(document.querySelector('#story-check-results img'), null);
    fail = true;
    form.dispatchEvent(new dom.window.Event('submit', {cancelable: true}));
    await until(() => !form.querySelector('button').disabled);
    assert.equal(document.getElementById('story-check-status').textContent, 'Try again later.');
    assert.equal(checks, 2);
  } finally {
    dom.window.close();
    for (const [key, descriptor] of previous) { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key]; }
  }
});
