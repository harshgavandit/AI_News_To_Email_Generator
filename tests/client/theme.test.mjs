import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';

const theme = readFileSync(new URL('../../public/theme.js', import.meta.url), 'utf8');

async function mount(markup, { saved, systemDark = false, blockedStorage = false } = {}) {
  const dom = new JSDOM(markup, { url: 'https://informa.test/', runScripts: 'outside-only' });
  let listener;
  const media = { matches: systemDark, addEventListener(event, callback) { listener = callback; } };
  dom.window.matchMedia = () => media;
  if (saved) dom.window.localStorage.setItem('informa-theme', saved);
  if (blockedStorage) Object.defineProperty(dom.window, 'localStorage', { get() { throw new Error('Storage unavailable'); } });
  dom.window.eval(theme);
  // The initial theme must be applied before DOMContentLoaded to prevent flashing.
  assert.equal(dom.window.document.documentElement.dataset.theme, saved === 'light' ? 'light' : saved === 'dark' || systemDark ? 'dark' : 'light');
  await new Promise(resolve => dom.window.document.addEventListener('DOMContentLoaded', resolve, { once: true }));
  return { dom, system(value) { media.matches = value; listener(); } };
}

for (const page of ['index.html', 'sources.html', 'contribute.html', 'about.html', 'privacy.html', 'trust.html', 'research.html', 'curiosity.html']) {
  test(`${page} offers only light and dark, and remembers the reader's choice`, async () => {
    const html = readFileSync(new URL(`../../public/${page}`, import.meta.url), 'utf8');
    assert.doesNotMatch(html, /value="system"/);
    const { dom, system } = await mount(html, { saved: 'dark' });
    try {
      const { document, Event, localStorage } = dom.window;
      const select = document.getElementById('site-theme');
      assert.equal(select.disabled, false);
      assert.deepEqual([...select.options].map((option) => option.value), ['light', 'dark']);
      assert.equal(select.value, 'dark');
      assert.equal(document.querySelector('meta[name="theme-color"]').content, '#040b19');
      select.value = 'light';
      select.dispatchEvent(new Event('change'));
      assert.equal(document.documentElement.dataset.theme, 'light');
      assert.equal(localStorage.getItem('informa-theme'), 'light');
      assert.equal(document.querySelector('meta[name="theme-color"]').content, '#f3f7fc');
      // A chosen theme stays put when the device switches.
      system(true);
      assert.equal(document.documentElement.dataset.theme, 'light');
      dom.window.dispatchEvent(new dom.window.StorageEvent('storage', { key: 'informa-theme', newValue: 'dark' }));
      assert.equal(select.value, 'dark');
      assert.equal(document.documentElement.dataset.theme, 'dark');
    } finally { dom.window.close(); }
  });
}

test('first visit and older "system" choices start from the device look and show it as light or dark', async () => {
  for (const saved of [undefined, 'system']) {
    const html = readFileSync(new URL('../../public/index.html', import.meta.url), 'utf8');
    const { dom, system } = await mount(html, { saved, systemDark: true });
    try {
      const { document } = dom.window;
      const select = document.getElementById('site-theme');
      assert.equal(select.value, 'dark');
      assert.equal(document.documentElement.dataset.theme, 'dark');
      system(false);
      assert.equal(select.value, 'light', 'until the reader chooses, the control mirrors the device');
      assert.equal(document.documentElement.dataset.theme, 'light');
    } finally { dom.window.close(); }
  }
});

test('theme controls work when browser storage is unavailable', async () => {
  const { dom } = await mount('<meta name="theme-color"><select id="site-theme"><option value="light">Light</option><option value="dark">Dark</option></select>', { systemDark: true, blockedStorage: true });
  try {
    const select = dom.window.document.getElementById('site-theme');
    select.value = 'light';
    assert.doesNotThrow(() => select.dispatchEvent(new dom.window.Event('change')));
    assert.equal(dom.window.document.documentElement.dataset.theme, 'light');
  } finally { dom.window.close(); }
});

test('shared theme initialization tolerates pages without optional theme elements', async () => {
  const { dom, system } = await mount('<title>Minimal page</title>');
  try {
    system(true);
    assert.equal(dom.window.document.documentElement.dataset.theme, 'dark');
    dom.window.dispatchEvent(new dom.window.StorageEvent('storage', { key: 'informa-theme', newValue: 'light' }));
    assert.equal(dom.window.document.documentElement.dataset.theme, 'light');
  } finally { dom.window.close(); }
});
