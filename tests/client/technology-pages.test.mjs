import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { readingGroups } from '../../public/privacy-data.js';

const asset = (name) => readFileSync(new URL(`../../public/${name}`, import.meta.url), 'utf8');
const script = (name) => asset(name).replace(/^import[^\n]+\n/gm, '').replace(/^export /gm, '');
const tick = () => new Promise((resolve) => setImmediate(resolve));
const source = { id: 'release', title: 'Sample release', publisher: 'Kubernetes Releases', language: 'en',
  url: 'https://example.org/release', published_at: '2026-11-17T00:00:00+00:00', excerpt: 'The prior networking API has been removed.' };
const tech = { id: 'kubernetes', name: 'Kubernetes', homepage: 'https://kubernetes.io/' };

function mount(html, destination, entry, fetch) {
  const dom = new JSDOM(asset(html), { url: `https://informa.test/${destination}`, runScripts: 'outside-only' });
  const { window } = dom;
  window.fetch = fetch;
  window.readingGroups = readingGroups;
  for (const [file, bindings] of [
    ['evidence-ui.js', 'node, requestJSON, sourceList, sourceLink, answerBlock'],
    ['source-history.js', 'historyControl'],
    ['technology-follow.js', 'followedTechnologies, saveTechnologyFollow'],
    ['monitor-inbox.js', 'monitorInbox'],
  ]) window.eval(`(() => { ${script(file)}\nObject.assign(window, { ${bindings} }); })()`);
  window.eval(script(entry));
  return dom;
}

test('technology page renders archive groups and follows a technology before asking a cited question', async () => {
  const requests = [];
  const dom = mount('technology.html', 'technology.html?tech=kubernetes', 'technology-pages.js', async (path, options) => {
    requests.push([path, options.body]);
    const data = path.endsWith('/technologies') ? { technologies: [tech] } : path.endsWith('/ask') ? {
      evidence: [source], answer: { claims: [{ text: source.excerpt, kind: 'fact', source_ids: [source.id], quotes: [source.excerpt] }] },
    } : { records: [{ ...source, record_kind: 'release', entity_match: 'registered_source' }] };
    return { ok: true, json: async () => data };
  });
  try {
    const { document, localStorage } = dom.window;
    await tick();
    assert.equal(document.getElementById('technology-title').textContent, 'Kubernetes');
    assert.match(document.getElementById('technology-records').textContent, /Releases.*Sample release/s);
    document.getElementById('technology-follow').click();
    const profile = JSON.parse(localStorage.getItem(readingGroups.radar.key));
    assert.deepEqual(profile.followed_technologies, ['kubernetes']);
    document.getElementById('technology-ask').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
    await tick();
    assert.ok(requests.find(([url]) => url.endsWith('/kubernetes/ask')));
    assert.equal(document.querySelector('#technology-answer .intelligence-citations a').href, source.url);
    assert.equal(document.querySelector('#technology-answer blockquote').textContent, source.excerpt);
  } finally { dom.window.close(); }
});

test('brief opens from its fragment without loading the private workspace', async () => {
  const token = 'a'.repeat(43);
  const requests = [];
  const dom = mount('projects.html', `projects.html#brief=${token}`, 'research-projects.js', async (path, options) => {
    requests.push([path, JSON.parse(options.body)]);
    return { ok: true, json: async () => ({ question: 'How has Kubernetes changed?', audience: 'engineering',
      period: 'Past 7 days', created: Date.now() / 1000, evidence_changed: true, answer: { claims: [] }, evidence: [source] }) };
  });
  try {
    const { document } = dom.window;
    await tick();
    assert.deepEqual(requests, [['/api/intelligence/briefs/open', { token }]]);
    assert.match(document.getElementById('project-title').textContent, /How has Kubernetes changed/);
    assert.match(document.getElementById('shared-brief').textContent, /sources were revised/);
    assert.equal(document.getElementById('project-workspace').hidden, true);
  } finally { dom.window.close(); }
});
