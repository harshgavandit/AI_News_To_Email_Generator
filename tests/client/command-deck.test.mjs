import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { orbitalPosition, orbitals, ringAround, shortestAngle, toVector } from '../../public/globe.js';
import { parseFeedHealth, pickTransmissions, relativeAge, renderWire, safeLink } from '../../public/command-center.js';

const root = new URL('../../public/', import.meta.url);

test('globe motion helpers: shortest turns, ripples on the surface and bounded orbits', () => {
  assert.ok(Math.abs(shortestAngle(0.1, Math.PI * 2 - 0.1) + 0.2) < 1e-9, 'turns the short way across zero');
  assert.ok(Math.abs(shortestAngle(-3, 3) - (6 - Math.PI * 2)) < 1e-9);
  const ring = ringAround(toVector(50, 10), 0.2, 12);
  assert.equal(ring.length, 12);
  for (const point of ring) assert.ok(Math.abs(Math.hypot(...point) - 1) < 1e-9, 'ripple points stay on the sphere');
  const center = toVector(50, 10);
  for (const point of ring) {
    const dot = point[0] * center[0] + point[1] * center[1] + point[2] * center[2];
    assert.ok(Math.abs(Math.acos(Math.min(1, dot)) - 0.2) < 1e-9, 'ripple radius is the requested angle');
  }
  const sats = orbitals(40);
  assert.deepEqual(orbitals(40), sats, 'orbits are deterministic');
  for (const orbit of sats) {
    const radius = Math.hypot(...orbitalPosition(orbit, 12.5));
    assert.ok(radius > 1.1 && radius < 1.6 && Math.abs(radius - orbit.radius) < 1e-9, 'satellites fly above the surface');
  }
});

test('transmissions use one safe, region-tagged headline per publisher and alternate regions', () => {
  const articles = [
    { id: 1, title: 'EU chip rules', url: 'https://a.example/1', publisher: 'A', region_id: 'EU' },
    { id: 2, title: 'Second from A', url: 'https://a.example/2', publisher: 'A', region_id: 'EU' },
    { id: 3, title: 'Lagos fintech', url: 'https://b.example/3', publisher: 'B', region_id: 'Africa' },
    { id: 4, title: 'Bad link', url: 'javascript:alert(1)', publisher: 'C', region_id: 'NA' },
    { id: 5, title: 'No region', url: 'https://d.example/5', publisher: 'D', region_id: 'Moon' },
    { id: 6, title: 'Paris AI lab', url: 'https://e.example/6', publisher: 'E', region_id: 'EU' },
    { id: 7, title: '   ', url: 'https://f.example/7', publisher: 'F', region_id: 'NA' },
    { id: 8, title: 'Insecure', url: 'http://g.example/8', publisher: 'G', region_id: 'APAC' },
  ];
  const picked = pickTransmissions(articles);
  assert.deepEqual(picked.map((item) => item.id), ['1', '3', '6']);
  assert.equal(picked[1].region, 'Africa');
  assert.equal(safeLink('https://user:pw@x.example/'), '');
  assert.equal(pickTransmissions(null).length, 0);
});

test('telemetry parsing and relative ages', () => {
  assert.deepEqual(parseFeedHealth('1,204 of 1,310 feeds up to date'), { fresh: 1204, total: 1310 });
  assert.equal(parseFeedHealth('Checking sources'), null);
  const now = Date.parse('2026-11-23T12:00:00Z');
  assert.equal(relativeAge('2026-11-23T11:40:00Z', now), '20 min ago');
  assert.equal(relativeAge('2026-11-23T02:00:00Z', now), '10 h ago');
  assert.equal(relativeAge('2026-11-19T12:00:00Z', now), '4 d ago');
  assert.equal(relativeAge('not a date', now), '');
});

test('the live wire is a real list of publisher links with an inert looping copy', () => {
  const dom = new JSDOM('<div id="deck-wire" hidden><div class="deck-wire-track"></div></div>');
  globalThis.document = dom.window.document;
  try {
    const wire = dom.window.document.getElementById('deck-wire');
    renderWire(wire, [
      { id: '1', title: 'Chip rules <b>tighten</b>', url: 'https://a.example/1', publisher: 'A', region: 'EU', published: '' },
      { id: '2', title: 'Lagos fintech', url: 'https://b.example/2', publisher: 'B', region: 'Africa', published: '' },
    ]);
    assert.equal(wire.hidden, false);
    const [list, echo] = wire.querySelectorAll('ul');
    assert.equal(list.getAttribute('aria-label'), 'Latest headlines');
    assert.equal(echo.getAttribute('aria-hidden'), 'true');
    const links = [...list.querySelectorAll('a')];
    assert.deepEqual(links.map((a) => a.href), ['https://a.example/1', 'https://b.example/2']);
    assert.ok(links.every((a) => a.target === '_blank' && /noopener/.test(a.rel)));
    assert.match(links[0].textContent, /Chip rules <b>tighten<\/b>/, 'titles are text, never markup');
    assert.equal(list.querySelector('b'), null);
    assert.ok([...echo.querySelectorAll('a')].every((a) => a.tabIndex === -1));
    renderWire(wire, []);
    assert.equal(wire.hidden, true);
  } finally { delete globalThis.document; dom.window.close(); }
});

test('the homepage carries the deck markup and loads the deck after the globe', () => {
  const html = readFileSync(new URL('index.html', root), 'utf8');
  for (const id of ['command-deck', 'deck-telemetry', 'deck-transmission', 'deck-beam', 'deck-wire', 'deck-wire-toggle']) {
    assert.match(html, new RegExp(`id="${id}"`), `index.html needs #${id}`);
  }
  assert.ok(html.indexOf('/globe-home.js') < html.indexOf('/command-center.js'));
  assert.match(html, /id="deck-wire-toggle"[^>]*aria-pressed="false"/);
});

function ambientPage({ reduce = false, stored = null, width = 1280 } = {}) {
  const dom = new JSDOM('<html><body><header><div class="site-tools"><select></select></div></header></body></html>',
    { url: 'https://informa.test/', runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;
  window.matchMedia = (query) => ({
    matches: query.includes('reduced-motion') ? reduce : query.includes('max-width: 560px') ? width <= 560 : false,
    media: query, addEventListener() {}, removeEventListener() {},
  });
  if (stored) window.localStorage.setItem('informa-motion', stored);
  window.eval(readFileSync(new URL('ambient.js', root), 'utf8'));
  return dom;
}

test('ambient layer: one motion switch, honouring system settings and the stored choice', () => {
  let dom = ambientPage();
  let { document } = dom.window;
  const button = document.getElementById('motion-toggle');
  assert.ok(button && button.parentElement.classList.contains('site-tools'));
  assert.equal(document.documentElement.dataset.motion, 'on');
  assert.equal(button.getAttribute('aria-pressed'), 'false');
  const seen = [];
  dom.window.informaMotion.onChange((on) => seen.push(on));
  button.click();
  assert.equal(document.documentElement.dataset.motion, 'off');
  assert.equal(button.getAttribute('aria-label'), 'Play animations');
  assert.equal(dom.window.localStorage.getItem('informa-motion'), 'off');
  assert.deepEqual(seen, [false]);
  dom.window.close();

  dom = ambientPage({ reduce: true });
  assert.equal(dom.window.document.documentElement.dataset.motion, 'off', 'reduced-motion readers start paused');
  dom.window.close();
  dom = ambientPage({ reduce: true, stored: 'on' });
  assert.equal(dom.window.document.documentElement.dataset.motion, 'on', 'an explicit choice wins');
  dom.window.close();
  dom = ambientPage({ width: 390 });
  ({ document } = dom.window);
  assert.equal(document.getElementById('motion-toggle').parentElement, document.body, 'narrow screens float the switch');
  dom.window.close();
});
