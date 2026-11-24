import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { JSDOM } from 'jsdom';
import {
  PUSH_KEY, alertProfile, alertSupport, applicationServerKey, disableAlerts, enableAlerts, followSummary,
  mountAlertPanel, syncAlerts,
} from '../../public/push-alerts.js';

const RADAR = 'informa-radar-v1';
const STORY = 'a'.repeat(32);
const CONFIG = { enabled: true, public_key: 'BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U' };

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial).map(([key, value]) => [key, typeof value === 'string' ? value : JSON.stringify(value)]));
  return { getItem: (key) => (data.has(key) ? data.get(key) : null), setItem: (key, value) => data.set(key, String(value)),
    removeItem: (key) => data.delete(key), data };
}

function fakeRegistration(existing = null) {
  const log = [];
  let current = existing;
  const make = (endpoint) => ({ endpoint, toJSON: () => ({ endpoint, keys: { p256dh: 'p', auth: 'a' } }),
    unsubscribe: async () => { log.push('unsubscribe'); current = null; return true; } });
  if (typeof existing === 'string') current = make(existing);
  return { log, pushManager: {
    getSubscription: async () => current,
    subscribe: async (options) => { log.push(['subscribe', options.userVisibleOnly, options.applicationServerKey.length]);
      current = make('https://fcm.googleapis.com/fcm/send/new'); return current; },
  } };
}

function fakeFetch(handler = () => ({ status: 200, body: { status: 'on' } })) {
  const calls = [];
  const fetcher = async (url, init = {}) => {
    calls.push({ url, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : undefined });
    const { status = 200, body = {} } = handler(url, init) || {};
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  };
  return { fetcher, calls };
}

test('alert profile keeps only valid follow fields from the Tech Radar profile', () => {
  const storage = memoryStorage({ [RADAR]: { name: 'Asha', language: 'hi', viewedRevisions: { x: 1 },
    followed_events: [STORY, 'not-an-id', STORY], followed_technologies: ['kubernetes'], stack: [' Postgres ', ''],
    topics: ['ai'], interests: [], feedback: { companies: ['Nvidia', 7], liked_ids: ['x'], muted_topics: ['security'] } } });
  const profile = alertProfile(storage);
  assert.deepEqual(profile, { interests: [], stack: ['Postgres'], topics: ['ai'], followed_events: [STORY],
    followed_technologies: ['kubernetes'], feedback: { companies: ['Nvidia'], muted_topics: ['security'] } });
  assert.deepEqual(followSummary(profile), { total: 5,
    text: '1 story, 1 technology, 1 company, 1 topic, 1 stack or interest term' });
  assert.equal(followSummary(alertProfile(memoryStorage())).total, 0);
  assert.equal(followSummary(alertProfile(memoryStorage({ [RADAR]: '{broken' }))).total, 0);
});

test('application server key decodes base64url to the 65-byte P-256 point', () => {
  const key = applicationServerKey(CONFIG.public_key);
  assert.equal(key.length, 65);
  assert.equal(key[0], 4);
});

test('turning alerts on asks for permission before waiting on the service worker, then saves follows', async () => {
  const storage = memoryStorage({ [RADAR]: { feedback: { companies: ['Nvidia'] } } });
  const order = [];
  const registration = fakeRegistration();
  const { fetcher, calls } = fakeFetch();
  await enableAlerts({ config: CONFIG, storage, fetcher,
    registration: new Promise((resolve) => setTimeout(() => { order.push('worker'); resolve(registration); }, 5)),
    requestPermission: async () => { order.push('permission'); return 'granted'; },
    settings: { max_per_day: 1, quiet_hours: true, timezone: 'Asia/Kolkata' } });
  assert.deepEqual(order, ['permission', 'worker']);
  assert.deepEqual(registration.log[0], ['subscribe', true, 65]);
  const put = calls.find((call) => call.method === 'PUT');
  assert.equal(put.url, '/api/push/subscription');
  assert.deepEqual(put.body.profile.feedback.companies, ['Nvidia']);
  assert.equal(put.body.settings.max_per_day, 1);
  assert.equal(JSON.parse(storage.getItem(PUSH_KEY)).endpoint, 'https://fcm.googleapis.com/fcm/send/new');
});

test('turning alerts on explains missing follows, blocked permission and server errors', async () => {
  const registration = fakeRegistration();
  await assert.rejects(enableAlerts({ config: CONFIG, registration, storage: memoryStorage(), fetcher: fakeFetch().fetcher,
    requestPermission: async () => 'granted' }), /Follow a story/);
  const storage = memoryStorage({ [RADAR]: { followed_technologies: ['kubernetes'] } });
  await assert.rejects(enableAlerts({ config: CONFIG, registration, storage, fetcher: fakeFetch().fetcher,
    requestPermission: async () => 'denied' }), /blocked/);
  await assert.rejects(enableAlerts({ config: { enabled: false }, registration, storage, fetcher: fakeFetch().fetcher,
    requestPermission: async () => 'granted' }), /aren't available/);
  const failing = fakeFetch(() => ({ status: 422, body: { detail: 'This browser sent an unusable push key.' } }));
  await assert.rejects(enableAlerts({ config: CONFIG, registration, storage, fetcher: failing.fetcher,
    requestPermission: async () => 'granted' }), /unusable push key/);
  assert.equal(storage.getItem(PUSH_KEY), null);
});

test('page-load sync updates the server only when follows change, and cleans up when alerts end', async () => {
  const endpoint = 'https://fcm.googleapis.com/fcm/send/old';
  const storage = memoryStorage({ [RADAR]: { feedback: { companies: ['Nvidia'] } } });
  const registration = fakeRegistration(endpoint);
  const { fetcher, calls } = fakeFetch();
  await enableAlerts({ config: CONFIG, registration, storage, fetcher, requestPermission: async () => 'granted' });
  calls.length = 0;
  assert.equal(await syncAlerts({ registration, storage, fetcher, permission: 'granted' }), 'current');
  assert.equal(calls.length, 0);
  storage.setItem(RADAR, JSON.stringify({ feedback: { companies: ['Nvidia', 'AMD'] } }));
  assert.equal(await syncAlerts({ registration, storage, fetcher, permission: 'granted' }), 'synced');
  assert.deepEqual(calls.at(-1).body.profile.feedback.companies, ['Nvidia', 'AMD']);
  storage.setItem(RADAR, JSON.stringify({}));
  assert.equal(await syncAlerts({ registration, storage, fetcher, permission: 'granted' }), 'no-follows');
  assert.deepEqual(calls.at(-1), { url: '/api/push/subscription/remove', method: 'POST', body: { endpoint } });
  assert.equal(storage.getItem(PUSH_KEY), null);
  assert.ok(registration.log.includes('unsubscribe'));
  assert.equal(await syncAlerts({ registration, storage, fetcher, permission: 'granted' }), 'off');
});

test('sync moves the subscription when the browser replaced its push address, and removes it when permission is revoked', async () => {
  const storage = memoryStorage({ [RADAR]: { feedback: { companies: ['Nvidia'] } },
    [PUSH_KEY]: { endpoint: 'https://fcm.googleapis.com/fcm/send/previous', settings: { max_per_day: 3, quiet_hours: true, timezone: 'UTC' }, synced: '' } });
  const registration = fakeRegistration('https://fcm.googleapis.com/fcm/send/current');
  const { fetcher, calls } = fakeFetch();
  assert.equal(await syncAlerts({ registration, storage, fetcher, permission: 'granted' }), 'synced');
  assert.deepEqual(calls[0].body.old_endpoint, 'https://fcm.googleapis.com/fcm/send/previous');
  assert.equal(calls[0].url, '/api/push/subscription/rotate');
  assert.equal(JSON.parse(storage.getItem(PUSH_KEY)).endpoint, 'https://fcm.googleapis.com/fcm/send/current');
  assert.equal(await syncAlerts({ registration, storage, fetcher, permission: 'denied' }), 'removed');
  assert.equal(storage.getItem(PUSH_KEY), null);
});

test('turning alerts off removes the server copy even if the browser lost its subscription', async () => {
  const storage = memoryStorage({ [PUSH_KEY]: { endpoint: 'https://fcm.googleapis.com/fcm/send/x', settings: {} } });
  const { fetcher, calls } = fakeFetch();
  await disableAlerts({ registration: fakeRegistration(), storage, fetcher });
  assert.deepEqual(calls[0].body, { endpoint: 'https://fcm.googleapis.com/fcm/send/x' });
  assert.equal(storage.getItem(PUSH_KEY), null);
});

test('support detection points iPhone visitors to Add to Home Screen', () => {
  const iphone = { navigator: { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)' }, matchMedia: () => ({ matches: false }) };
  assert.deepEqual(alertSupport(iphone), { supported: false, reason: 'ios-home-screen' });
  const chrome = { navigator: { serviceWorker: {}, userAgent: 'Chrome' }, PushManager: function () {}, Notification: function () {} };
  assert.deepEqual(alertSupport(chrome), { supported: true });
  assert.deepEqual(alertSupport({ navigator: { userAgent: 'Old' } }), { supported: false, reason: 'unsupported' });
});

test('alert panel renders states and turns alerts on from the button', async () => {
  const dom = new JSDOM('<div id="panel"></div>', { url: 'https://getinformdaily.com/' });
  globalThis.document = dom.window.document;
  try {
    const root = dom.window.document.getElementById('panel');
    const storage = memoryStorage({ [RADAR]: { followed_technologies: ['kubernetes'] } });
    const registration = fakeRegistration();
    const { fetcher, calls } = fakeFetch((url) => (url === '/api/push/config' ? { body: CONFIG } : { body: { status: 'on' } }));
    const win = { navigator: { serviceWorker: {}, userAgent: 'Chrome' }, PushManager: function () {}, Notification: function () {} };
    const panel = mountAlertPanel(root, { win, storage, fetcher, ready: async () => registration, requestPermission: async () => 'granted' });
    await panel.loaded;
    const [toggle, testButton] = root.querySelectorAll('button');
    assert.equal(toggle.textContent, 'Turn on alerts');
    assert.equal(toggle.disabled, false);
    assert.equal(testButton.hidden, true);
    assert.match(root.querySelector('.alert-follows').textContent, /You follow 1 technology/);
    root.querySelector('select').value = '5';
    toggle.click();
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal(toggle.textContent, 'Turn off alerts');
    assert.equal(testButton.hidden, false);
    assert.equal(calls.find((call) => call.method === 'PUT').body.settings.max_per_day, 5);
    assert.match(root.querySelector('[role=status]').textContent, /Alerts are on/);
    assert.equal(mountAlertPanel(root, { win, storage, fetcher }), null, 'mounting twice is ignored');

    const offRoot = dom.window.document.createElement('div');
    const off = mountAlertPanel(offRoot, { win, storage: memoryStorage(), fetcher: fakeFetch(() => ({ body: { enabled: false } })).fetcher });
    await off.loaded;
    assert.equal(offRoot.querySelector('.alert-state').textContent, "Alerts aren't available yet.");
    assert.equal(offRoot.querySelector('button').hidden, true);
  } finally {
    delete globalThis.document;
    dom.window.close();
  }
});

function loadWorker() {
  const listeners = {};
  const shown = [];
  const opened = [];
  const self = {
    location: { origin: 'https://getinformdaily.com' },
    addEventListener: (type, listener) => { listeners[type] = listener; },
    registration: { showNotification: async (title, options) => shown.push({ title, options }) },
    clients: { matchAll: async () => [], openWindow: async (url) => opened.push(url), claim: async () => {} },
    skipWaiting: async () => {},
  };
  vm.runInNewContext(readFileSync(new URL('../../public/sw.js', import.meta.url), 'utf8'),
    { self, URL, Response, caches: { open: async () => ({ addAll: async () => {} }), keys: async () => [], match: async () => undefined },
      fetch: async () => { throw new Error('offline'); } });
  return { listeners, shown, opened };
}

test('service worker shows alerts with same-site links only and opens them on click', async () => {
  const { listeners, shown, opened } = loadWorker();
  const fire = async (type, event) => { let wait; listeners[type]({ ...event, waitUntil: (promise) => { wait = promise; } }); await wait; };
  await fire('push', { data: { json: () => ({ title: 'Kubernetes 1.36 released', body: 'Technology you follow', url: '/development.html?id=abc', tag: 'informa-abc' }) } });
  await fire('push', { data: { json: () => ({ title: 'x'.repeat(500), url: 'https://evil.example/phish' }) } });
  assert.equal(shown[0].title, 'Kubernetes 1.36 released');
  assert.equal(shown[0].options.data.url, '/development.html?id=abc');
  assert.equal(shown[0].options.icon, '/icons/icon-192.png');
  assert.equal(shown[1].title.length, 140);
  assert.equal(shown[1].options.data.url, '/');
  await fire('notificationclick', { notification: { close() {}, data: { url: '/development.html?id=abc' } } });
  assert.deepEqual(opened, ['https://getinformdaily.com/development.html?id=abc']);
});

test('service worker serves the offline page only for failed navigations', async () => {
  const { listeners } = loadWorker();
  let response;
  listeners.fetch({ request: { method: 'GET', url: 'https://getinformdaily.com/api/news', mode: 'cors' }, respondWith: (value) => { response = value; } });
  assert.equal(response, undefined, 'API requests are never intercepted');
  listeners.fetch({ request: { method: 'GET', url: 'https://getinformdaily.com/', mode: 'navigate' }, respondWith: (value) => { response = value; } });
  assert.equal((await response).status, 503);
});

test('every page links the manifest and loads the app script; the manifest is installable', () => {
  const pages = ['index', 'about', 'contribute', 'curiosity', 'development', 'inbox', 'privacy', 'projects', 'research',
    'sources', 'technology', 'trust'];
  for (const page of pages) {
    const html = readFileSync(new URL(`../../public/${page}.html`, import.meta.url), 'utf8');
    assert.match(html, /<link rel="manifest" href="\/manifest.webmanifest" \/>/, page);
    assert.match(html, /<script type="module" src="\/pwa.js"><\/script>/, page);
  }
  const manifest = JSON.parse(readFileSync(new URL('../../public/manifest.webmanifest', import.meta.url), 'utf8'));
  assert.equal(manifest.display, 'standalone');
  assert.ok(manifest.icons.some((icon) => icon.sizes === '512x512' && icon.purpose === 'maskable'));
  assert.ok(manifest.icons.some((icon) => icon.sizes === '192x192'));
});
