import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { clearReadingData, dataCounts, readBrowserData, readingGroups } from '../../public/privacy-data.js';

const analytics = readFileSync(new URL('../../public/analytics.js', import.meta.url), 'utf8');
const markup = readFileSync(new URL('../../public/privacy.html', import.meta.url), 'utf8');
const controls = readFileSync(new URL('../../public/privacy.js', import.meta.url), 'utf8').replace(/^import[^\n]+\n/, '');

function mount({ consent, signal, blocked = false } = {}) {
  const dom = new JSDOM(markup, { url: 'https://informa.test/privacy.html?private=hidden', runScripts: 'outside-only' });
  const { window } = dom;
  if (consent) window.localStorage.setItem('informa-analytics-consent', consent);
  if (signal === 'gpc') Object.defineProperty(window.navigator, 'globalPrivacyControl', { value: true });
  if (signal === 'dnt') Object.defineProperty(window.navigator, 'doNotTrack', { value: '1' });
  if (blocked) Object.defineProperty(window, 'localStorage', { get() { throw new Error('Unavailable'); } });
  return dom;
}

test('browser export only includes reading data and documented appearance choices', () => {
  const dom = mount();
  try {
    const storage = dom.window.localStorage;
    storage.setItem('informa-saved-v1', '[{"id":"story","title":"Saved story"}]');
    storage.setItem('informa-interests-v1', '{"topics":["security"],"authors":["author-1"]}');
    storage.setItem('informa-theme', 'dark');
    storage.setItem('unrelated-private-key', 'must-not-export');
    storage.setItem('owner-token', 'must-not-export');
    const data = readBrowserData(storage);
    assert.equal(data['informa-theme'], 'dark');
    assert.deepEqual(dataCounts(data), { bookmarks: 1, history: 0, interests: 2, views: 0 });
    assert.equal(JSON.stringify(data).includes('must-not-export'), false);
  } finally { dom.window.close(); }
});

test('selective reset preserves unrelated data, appearance, consent, and other reading lists', () => {
  const dom = mount({ consent: 'denied' });
  try {
    const storage = dom.window.localStorage;
    for (const { key } of Object.values(readingGroups)) storage.setItem(key, '[]');
    storage.setItem('informa-theme', 'dark');
    storage.setItem('unrelated-private-key', 'keep');
    assert.deepEqual(clearReadingData(storage, ['history', 'history']), ['Read history']);
    assert.equal(storage.getItem('informa-read-v1'), null);
    for (const key of ['informa-saved-v1', 'informa-interests-v1', 'informa-saved-views-v1']) assert.equal(storage.getItem(key), '[]');
    assert.equal(storage.getItem('informa-theme'), 'dark');
    assert.equal(storage.getItem('informa-analytics-consent'), 'denied');
    assert.equal(storage.getItem('unrelated-private-key'), 'keep');
    assert.ok(storage.getItem('informa-reader-reset'));
    assert.throws(() => clearReadingData(storage, ['history', 'owner-token']));
    assert.throws(() => clearReadingData(storage, []));
  } finally { dom.window.close(); }
});

test('clear controls require selection and explicit confirmation, and cancellation keeps data', () => {
  const dom = mount();
  try {
    const { window } = dom, { document, localStorage } = window;
    Object.assign(window, { clearReadingData, dataCounts, readBrowserData, readingGroups });
    const dialog = document.getElementById('clear-data-dialog');
    dialog.showModal = () => dialog.setAttribute('open', '');
    dialog.close = () => dialog.removeAttribute('open');
    localStorage.setItem('informa-saved-v1', '[{"id":"fixture"}]');
    window.eval(controls);
    assert.equal(document.getElementById('count-bookmarks').textContent, '1');
    document.getElementById('clear-browser-data').click();
    assert.equal(dialog.hasAttribute('open'), false);
    document.querySelector('[value=bookmarks]').checked = true;
    document.getElementById('clear-browser-data').click();
    assert.equal(dialog.hasAttribute('open'), true);
    assert.ok(localStorage.getItem('informa-saved-v1'));
    document.getElementById('cancel-clear-data').click();
    assert.ok(localStorage.getItem('informa-saved-v1'));
    document.getElementById('clear-browser-data').click();
    document.getElementById('confirm-clear-data').click();
    assert.equal(localStorage.getItem('informa-saved-v1'), null);
    assert.equal(document.getElementById('count-bookmarks').textContent, '0');
  } finally { dom.window.close(); }
});

for (const options of [{}, { consent: 'denied' }, { consent: 'granted', signal: 'gpc' }, { consent: 'granted', signal: 'dnt' }, { blocked: true }]) {
  test(`optional analytics does not load without effective consent: ${JSON.stringify(options)}`, () => {
    const dom = mount(options);
    try {
      dom.window.eval(analytics);
      assert.equal(dom.window.document.querySelector('script[src="/_vercel/insights/script.js"]'), null);
    } finally { dom.window.close(); }
  });
}

test('opt-in loads analytics with URL redaction and drops events after consent withdrawal', () => {
  const dom = mount({ consent: 'granted' });
  try {
    const { window } = dom;
    window.eval(analytics);
    assert.ok(window.document.querySelector('script[src="/_vercel/insights/script.js"]'));
    const redact = window.vaq.find(([name]) => name === 'beforeSend')[1];
    const event = { type: 'pageview', url: 'https://informa.test/?q=private&token=secret#details' };
    assert.equal(redact(event).url, 'https://informa.test/');
    assert.equal(event.url.includes('secret'), true);
    window.localStorage.setItem('informa-analytics-consent', 'denied');
    assert.equal(redact(event), null);
    assert.equal(redact({ url: 'invalid' }), null);
  } finally { dom.window.close(); }
});

test('privacy controls explain unavailable browser storage instead of claiming success', () => {
  const dom = mount({ blocked: true });
  try {
    Object.assign(dom.window, { clearReadingData, dataCounts, readBrowserData, readingGroups });
    assert.doesNotThrow(() => dom.window.eval(controls));
    assert.equal(dom.window.document.getElementById('export-browser-data').disabled, true);
    assert.equal(dom.window.document.getElementById('clear-browser-data').disabled, true);
    assert.match(dom.window.document.getElementById('privacy-storage-note').textContent, /unavailable/);
  } finally { dom.window.close(); }
});

test('all public pages expose the information pages without loading analytics unconditionally', () => {
  for (const page of ['index', 'sources', 'contribute', 'about', 'privacy', 'trust']) {
    const html = readFileSync(new URL(`../../public/${page}.html`, import.meta.url), 'utf8');
    const dom = new JSDOM(html);
    try {
      for (const target of ['about', 'privacy', 'trust']) assert.ok(dom.window.document.querySelector(`footer a[href="/${target}.html"]`));
      assert.equal(dom.window.document.querySelector('script[src="/_vercel/insights/script.js"]'), null);
    } finally { dom.window.close(); }
  }
});
