import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';

const recap = (week, title) => ({
  week, title, start: '2026-11-16', end: '2026-11-22', notice: 'Built from publisher coverage.',
  stats: { developments: 40, models: 3, providers_with_incidents: 2, cves: 9, exploited: 1, releases: 12 },
  top_stories: [{ id: 'a'.repeat(32), title: 'CrowdStrike agrees to acquire Zscaler', url: `/development.html?id=${'a'.repeat(32)}`,
    topic_label: 'Cybersecurity & Privacy', outlets: 7, first_publisher: 'TechCrunch', summary: 'A record security deal.' }],
  topics: [{ id: 'ai', label: 'AI & Machine Learning', stories: [{ title: 'Gemini 4 Neon', url: '/development.html?id=' + 'b'.repeat(32), outlets: 3 }] }],
  models: [{ name: 'Gemini 4 Neon', official: true, outlets: 3, url: 'https://deepmind.google/x' }],
  exploited: [{ cve: 'CVE-2026-1111', title: 'Router flaw exploited', url: 'javascript:alert(1)' }],
  incidents: [], releases: [{ project: 'vercel/next.js', version: '16.0.0', level: 'major', url: 'https://github.com/vercel/next.js' }],
  postmortem: { title: 'How we lost a region', url: 'https://example.com/pm', company: 'Example' },
  weeks: [{ week: '2026-W47', title: 'This week in tech: Nov 16 – Nov 22, 2026' }, { week: '2026-W46', title: 'This week in tech: Nov 9 – Nov 15, 2026' }],
});

test('the recap page renders the week, switches weeks and keeps links safe', async () => {
  const html = readFileSync(new URL('../../public/recap.html', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'https://getinformdaily.com/recap.html' });
  for (const key of ['document', 'location']) globalThis[key] = dom.window[key];
  const calls = [];
  try {
    const { startRecap } = await import(`../../public/recap-page.js?t=${Date.now()}`);
    const fetcher = async (url) => {
      calls.push(url);
      if (url === '/api/recap/2026-W40') return { ok: false, status: 404, json: async () => ({}) };
      const week = url.endsWith('W46') ? '2026-W46' : '2026-W47';
      return { ok: true, status: 200, json: async () => recap(week, `This week in tech: ${week}`) };
    };
    await startRecap({ fetcher, win: dom.window });
    const doc = dom.window.document;
    assert.equal(doc.getElementById('recap-title').textContent, 'This week in tech: 2026-W47');
    assert.match(doc.querySelector('#recap-top li').textContent, /7 publishers · first reported by TechCrunch/);
    assert.equal(doc.querySelector('#recap-top a').getAttribute('href'), `https://getinformdaily.com/development.html?id=${'a'.repeat(32)}`);
    assert.equal(doc.querySelector('#recap-security a').getAttribute('href'), '#');
    assert.equal(doc.querySelector('#recap-models a').rel, 'noopener noreferrer');
    assert.equal(doc.getElementById('recap-week').options.length, 2);
    assert.equal(doc.getElementById('recap-postmortem-section').hidden, false);
    assert.equal(doc.querySelector('#recap-incidents li').textContent, 'No status-page incidents.');
    const select = doc.getElementById('recap-week');
    select.value = '2026-W46';
    select.dispatchEvent(new dom.window.Event('change'));
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(new URL(dom.window.location.href).searchParams.get('week'), '2026-W46');
    assert.deepEqual(calls, ['/api/recap', '/api/recap/2026-W46']);
    dom.window.history.replaceState(null, '', '/recap.html?week=2026-W40');
    await startRecap({ fetcher, win: dom.window });
    assert.match(doc.getElementById('recap-status').textContent, /no recap for that week/);
  } finally {
    for (const key of ['document', 'location']) delete globalThis[key];
    dom.window.close();
  }
});
