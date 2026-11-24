import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';

const NOW = Date.parse('2026-11-24T12:00:00Z');
const src = (title, extra = {}) => ({ id: title, title, url: 'https://example.com/' + encodeURIComponent(title), publisher: 'Example',
  published_at: '2026-11-24T10:00:00Z', official: false, ...extra });
const DATA = {
  'ai-models': { days: 30, notice: 'Detected automatically.', items: [{ name: 'Gemini 4 Neon', official: true, outlets: 2,
    first_seen: '2026-11-23T12:00:00Z', latest: '2026-11-24T10:00:00Z', headline: src('Introducing Gemini 4 Neon', { official: true }),
    sources: [src('Introducing Gemini 4 Neon', { official: true }), src('Google launches Gemini 4 Neon')] }] },
  incidents: { days: 7, notice: 'n', items: { providers: [{ provider: 'Cloudflare', open: true, updates: [{ ...src('Workers delays'), state: 'investigating' }] }],
    reporting: [src('Big outage hits region')] } },
  security: { days: 14, notice: 'n', items: { cves: [
    { cve: 'CVE-2026-1111', exploited: true, outlets: 2, latest: '2026-11-24T10:00:00Z', headline: src('a'), sources: [src('Router flaw exploited')] },
    { cve: 'CVE-2026-2222', exploited: false, outlets: 1, latest: '2026-11-24T09:00:00Z', headline: src('b'), sources: [src('Mail server patch')] }],
    advisories: [{ ...src('USN-1: fix'), exploited: false }] } },
  releases: { days: 21, notice: 'n', items: [
    { project: 'vercel/next.js', version: '16.0.0', level: 'major', release: src('v16.0.0') },
    { project: 'django/django', version: '5.2.3', level: 'patch', release: src('5.2.3') }] },
};

test('relative times read naturally', async () => {
  const { relativeTime } = await import('../../public/trackers-page.js');
  assert.equal(relativeTime('2026-11-24T11:59:30Z', NOW), 'just now');
  assert.equal(relativeTime('2026-11-24T11:15:00Z', NOW), '45 min ago');
  assert.equal(relativeTime('2026-11-24T07:00:00Z', NOW), '5 h ago');
  assert.equal(relativeTime('2026-11-23T10:00:00Z', NOW), 'yesterday');
  assert.equal(relativeTime('2026-11-20T12:00:00Z', NOW), '4 days ago');
  assert.equal(relativeTime('garbage', NOW), '');
});

async function page(fetcher, url = 'https://getinformdaily.com/trackers.html') {
  const html = readFileSync(new URL('../../public/trackers.html', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url });
  for (const key of ['document', 'location']) globalThis[key] = dom.window[key];
  const module = await import(`../../public/trackers-page.js?t=${Math.random()}`);
  const started = module.startTrackers({ fetcher, win: dom.window });
  await started;
  return { dom, doc: dom.window.document, cleanup() { for (const key of ['document', 'location']) delete globalThis[key]; dom.window.close(); } };
}

const api = (calls = []) => async (url) => {
  calls.push(url);
  const kind = url.split('/').pop();
  return { ok: true, status: 200, json: async () => ({ kind, ...DATA[kind] }) };
};

test('tabs load each tracker once, keep the tab in the URL and support arrow keys', async () => {
  const calls = [];
  const { dom, doc, cleanup } = await page(api(calls), 'https://getinformdaily.com/trackers.html?tab=security');
  try {
    assert.equal(doc.querySelector('[aria-selected="true"]').dataset.tracker, 'security');
    assert.match(doc.getElementById('tracker-summary').textContent, /2 CVEs in the news, 1 reported as exploited/);
    assert.equal(doc.querySelectorAll('.tracker-card').length, 3);
    const toggle = doc.querySelector('#tracker-controls input[type=checkbox]');
    toggle.checked = true; toggle.dispatchEvent(new dom.window.Event('change'));
    assert.deepEqual([...doc.querySelectorAll('.tracker-card h3')].map((h) => h.textContent), ['CVE-2026-1111']);
    doc.getElementById('tab-security').dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'ArrowRight' }));
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(doc.querySelector('[aria-selected="true"]').dataset.tracker, 'releases');
    assert.equal(new URL(dom.window.location.href).searchParams.get('tab'), 'releases');
    assert.deepEqual([...doc.querySelectorAll('.tracker-release-name')].map((a) => a.textContent), ['vercel/next.js 16.0.0']);
    const patches = [...doc.querySelectorAll('#tracker-controls input[type=checkbox]')].at(-1);
    patches.checked = true; patches.dispatchEvent(new dom.window.Event('change'));
    assert.equal(doc.querySelectorAll('.tracker-release').length, 2);
    doc.getElementById('tab-security').click();
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.deepEqual(calls, ['/api/trackers/security', '/api/trackers/releases']);
  } finally { cleanup(); }
});

test('model and incident boards show official sources and states, links open safely', async () => {
  const { doc, cleanup } = await page(api());
  try {
    const cardNode = doc.querySelector('.tracker-card');
    assert.equal(cardNode.querySelector('h3').textContent, 'Gemini 4 Neon');
    assert.match(cardNode.textContent, /Official announcement/);
    const link = cardNode.querySelector('a');
    assert.equal(link.rel, 'noopener noreferrer');
    assert.equal(link.target, '_blank');
    doc.getElementById('tab-incidents').click();
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.match(doc.querySelector('.tracker-card').textContent, /Ongoing.*Investigating/s);
    assert.match(doc.getElementById('tracker-summary').textContent, /1 provider with an ongoing incident/);
  } finally { cleanup(); }
});

test('a failed load offers a retry', async () => {
  let fail = true;
  const fetcher = async (url) => (fail ? { ok: false, status: 503, json: async () => ({}) } : api()(url));
  const { doc, cleanup } = await page(fetcher);
  try {
    assert.equal(doc.getElementById('tracker-summary').textContent, "This tracker couldn't load.");
    fail = false;
    doc.querySelector('#tracker-content button').click();
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(doc.querySelector('.tracker-card h3').textContent, 'Gemini 4 Neon');
  } finally { cleanup(); }
});
