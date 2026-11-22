import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { HUBS, arcPoints, isLand, rotate, toVector } from '../../public/globe.js';

const near = (a, b, epsilon = 1e-9) => Math.abs(a - b) < epsilon;

test('globe geometry: coordinates, land mask, rotation and arcs', () => {
  const [x, y, z] = toVector(0, 0);
  assert.ok(near(x, 0) && near(y, 0) && near(z, 1), 'lat 0, lon 0 faces the viewer');
  assert.ok(near(toVector(90, 0)[1], 1), 'the north pole is up');
  assert.equal(isLand(48.8, 2.3), true, 'Paris is land');
  assert.equal(isLand(-25, 134), true, 'central Australia is land');
  assert.equal(isLand(0, -30), false, 'the mid-Atlantic is sea');
  assert.equal(isLand(30, -150), false, 'the north Pacific is sea');
  // Turning by -longitude brings a hub to the front (largest z).
  const europe = HUBS.find((hub) => hub.id === 'EU');
  const front = rotate(toVector(europe.lat, europe.lon), -europe.lon * Math.PI / 180, 0);
  assert.ok(near(front[0], 0, 1e-9) && front[2] > 0.6);
  const path = arcPoints(toVector(40, -100), toVector(50, 10), 20);
  assert.equal(path.length, 21);
  assert.equal(path[0][3], 0);
  assert.equal(path.at(-1)[3], 1);
  const middle = path[10];
  assert.ok(Math.hypot(middle[0], middle[1], middle[2]) > 1.05, 'arcs lift off the surface');
});

function page(markup) {
  const dom = new JSDOM(markup, { url: 'https://informa.test/', pretendToBeVisual: true });
  for (const name of ['window', 'document', 'Event', 'MutationObserver', 'Intl']) {
    globalThis[name] = name === 'Intl' ? Intl : dom.window[name];
  }
  dom.window.HTMLElement.prototype.scrollIntoView = function () { this.dataset.scrolled = 'true'; };
  return dom;
}

test('region buttons drive the page filter when WebGL is unavailable', async () => {
  const dom = page(`<div id="signal-globe" class="signal-globe"><canvas></canvas><p class="signal-globe-tip" hidden></p></div>
    <ul id="signal-regions"></ul><p id="story-results-line"></p>
    <select id="region"><option value="">All regions (1,500)</option><option value="EU">Europe (233)</option>
    <option value="APAC">Asia-Pacific (198)</option><option value="NA">North America (412)</option></select>`);
  try {
    const { mountSignalGlobe, regionCounts } = await import(`../../public/globe-home.js?t=${Date.now()}`);
    const select = document.getElementById('region');
    assert.deepEqual(regionCounts(select), { EU: 233, APAC: 198, NA: 412 });
    const changes = [];
    select.addEventListener('change', () => changes.push(select.value));
    const mounted = mountSignalGlobe(document);
    assert.equal(mounted.globe, null, 'jsdom has no WebGL, so the globe falls back');
    assert.equal(document.getElementById('signal-globe').classList.contains('is-live'), false);
    const buttons = [...document.querySelectorAll('.signal-region')];
    assert.equal(buttons.length, HUBS.length);
    const europe = document.querySelector('.signal-region[data-region="EU"]');
    assert.equal(europe.querySelector('.signal-region-count').textContent, '233');
    europe.click();
    assert.deepEqual(changes, ['EU']);
    assert.equal(europe.getAttribute('aria-pressed'), 'true');
    assert.equal(document.getElementById('story-results-line').dataset.scrolled, 'true');
    europe.click();
    assert.deepEqual(changes, ['EU', ''], 'pressing the active region clears the filter');
    assert.equal(europe.getAttribute('aria-pressed'), 'false');
    // Regions the filter does not offer are ignored rather than setting an invalid value.
    document.querySelector('.signal-region[data-region="MENA"]').click();
    assert.deepEqual(changes, ['EU', '']);
    select.options[1].textContent = 'Europe (250)';
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(europe.querySelector('.signal-region-count').textContent, '250', 'counts follow the filter labels');
  } finally { dom.window.close(); }
});

test('pages wire the globe to their own region filter', () => {
  const index = readFileSync(new URL('../../public/index.html', import.meta.url), 'utf8');
  const sources = readFileSync(new URL('../../public/sources.html', import.meta.url), 'utf8');
  assert.match(index, /id="signal-globe"/);
  assert.match(index, /id="signal-regions"/);
  assert.match(index, /<script type="module" src="\/globe-home\.js"><\/script>/);
  assert.match(sources, /data-select="source-region" data-regions="source-signal-regions"/);
  assert.match(sources, /id="source-signal-regions"/);
  for (const html of [index, sources]) assert.match(html, /<canvas class="signal-globe-canvas" aria-hidden="true">/);
});
