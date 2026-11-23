import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { isLand, landCellsGrid, orbitRing, subsolarPoint } from '../../public/globe.js';
import { MASK_HEIGHT, MASK_WIDTH } from '../../public/land-mask.js';

const root = new URL('../../public/', import.meta.url);

test('the land mask places continents and oceans where they are', () => {
  assert.equal(landCellsGrid().length, MASK_WIDTH * MASK_HEIGHT);
  const land = [[23, 13, 'the Sahara'], [72, -40, 'Greenland'], [-15, -55, 'the Amazon'], [55, 90, 'Siberia'],
    [39, -98, 'Kansas'], [-80, 30, 'Antarctica'], [20, 78, 'central India'], [36, 138, 'Honshu']];
  for (const [lat, lon, place] of land) assert.equal(isLand(lat, lon), true, `${place} is land`);
  const sea = [[-20, 75, 'the Indian Ocean'], [0, -150, 'the central Pacific'], [35, -40, 'the north Atlantic'],
    [-50, 0, 'the Southern Ocean'], [15, 160, 'the Philippine Sea']];
  for (const [lat, lon, place] of sea) assert.equal(isLand(lat, lon), false, `${place} is sea`);
  // Longitudes wrap and latitudes clamp instead of reading outside the grid.
  assert.equal(isLand(23, 13 + 360), true);
  assert.equal(typeof isLand(95, 0), 'boolean');
});

test('the terminator follows the real sun', () => {
  const june = subsolarPoint(new Date(Date.UTC(2026, 5, 21, 12, 0)));
  assert.ok(Math.abs(june.lat - 23.44) < 0.6, `June solstice declination ${june.lat}`);
  assert.ok(Math.abs(june.lon) < 2.5, `noon UTC puts the sun over Greenwich (${june.lon})`);
  const december = subsolarPoint(new Date(Date.UTC(2026, 11, 21, 0, 0)));
  assert.ok(Math.abs(december.lat + 23.44) < 0.6, `December solstice declination ${december.lat}`);
  assert.ok(Math.abs(Math.abs(december.lon) - 180) < 2.5, `midnight UTC puts the sun over the date line (${december.lon})`);
  const india = subsolarPoint(new Date(Date.UTC(2026, 2, 20, 6, 30)));  // Noon in India.
  assert.ok(Math.abs(india.lon - 82.5) < 3, `sun over India at 12:00 IST (${india.lon})`);
  assert.ok(Math.abs(india.lat) < 1, 'equinox sun is over the equator');
});

test('orbit rings stay at their radius', () => {
  const ring = orbitRing(1.4, 0.5, 1.1, 64);
  assert.equal(ring.length, 64);
  for (const [x, y, z, t] of ring) {
    assert.ok(Math.abs(Math.hypot(x, y, z) - 1.4) < 1e-9);
    assert.ok(t >= 0 && t < 1);
  }
});

function load({ motion = 'on', saveData = false } = {}) {
  const dom = new JSDOM(`<!doctype html><html data-motion="${motion}"><body>
    <header class="site-tools"><button id="nav-builder" class="button primary">Build a brief</button></header>
    <h1 id="hero-title">The technology desk.</h1>
    <article class="story"><button class="pin-button" data-pin-id="a1">Pin</button><button class="pin-button save-button">Save</button></article>
    <form id="ask"><button type="submit">Ask</button></form></body></html>`,
  { url: 'https://informa.test/', runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;
  window.matchMedia = (query) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} });
  Object.defineProperty(window.navigator, 'connection', { value: { saveData }, configurable: true });
  window.informaMotion = { allowed: () => window.document.documentElement.dataset.motion !== 'off', onChange() {} };
  window.HTMLCanvasElement.prototype.getContext = () => null;  // jsdom has no canvas or WebGL.
  window.eval(readFileSync(new URL('orbital.js', root), 'utf8'));
  return dom;
}

test('decoding headlines settle on the real text and keep word breaks', () => {
  const dom = load();
  try {
    const { decodeFrame } = dom.window.informaAurora;
    const text = 'Research Desk';
    assert.equal(decodeFrame(text, 1), text);
    const noisy = decodeFrame(text, 0, () => 0);
    assert.equal(noisy.length, text.length);
    assert.equal(noisy[8], ' ', 'spaces never scramble');
    assert.notEqual(noisy, text);
    // Characters resolve from the start of the title toward the end.
    const halfway = decodeFrame(text, 0.5, () => 0);
    assert.equal(halfway[0], 'R');
    assert.notEqual(halfway.at(-1), 'k');
  } finally { dom.window.close(); }
});

test('the orbital layer is decoration only: actions still work without canvas or WebGL', () => {
  const dom = load();
  try {
    const { document } = dom.window;
    const clicks = [];
    document.querySelector('[data-pin-id]').addEventListener('click', () => clicks.push('pin'));
    document.querySelector('.save-button').addEventListener('click', () => clicks.push('save'));
    document.querySelector('[data-pin-id]').click();
    document.querySelector('.save-button').click();
    assert.deepEqual(clicks, ['pin', 'save'], 'the page\'s own handlers still run');
    assert.equal(document.querySelector('.aurora-field'), null, 'no WebGL, no field');
    assert.equal(document.querySelector('.orbital-overlay'), null, 'no 2D canvas, no overlay');
    assert.equal(typeof dom.window.informaAurora.surge, 'function');
  } finally { dom.window.close(); }
});

test('motion off or Save-Data leaves titles untouched', async () => {
  for (const options of [{ motion: 'off' }, { saveData: true }]) {
    const dom = load(options);
    try {
      await new Promise((resolve) => setTimeout(resolve, 50));
      const title = dom.window.document.getElementById('hero-title');
      assert.equal(title.textContent, 'The technology desk.');
      assert.equal(title.hasAttribute('aria-label'), false);
      assert.equal(title.hasAttribute('data-decoding'), false);
    } finally { dom.window.close(); }
  }
});

test('the orbital stylesheet gates every effect', () => {
  const css = readFileSync(new URL('orbital.css', root), 'utf8');
  assert.match(css, /:root\[data-motion="off"\] \.aurora-field \{ display: none; \}/);
  assert.match(css, /prefers-reduced-motion: reduce[\s\S]*\.aurora-field, \.orbital-overlay \{ display: none !important; \}/);
  assert.match(css, /@media print/);
  assert.match(css, /\.orbital-overlay \{[^}]*pointer-events: none/);
  assert.match(css, /\.aurora-field \{[^}]*pointer-events: none/);
});
