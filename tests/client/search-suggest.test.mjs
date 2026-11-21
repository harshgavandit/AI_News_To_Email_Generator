import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import { JSDOM } from 'jsdom';

const SUGGESTIONS = [
  { kind: 'topic', id: 'security', label: 'Cybersecurity & Privacy' },
  { kind: 'publisher', id: 'securityweek', label: 'SecurityWeek', detail: 'Global' },
  { kind: 'author', id: 'author-1', label: 'Sec Writer', detail: 'DEV Community' },
];

async function setup(request) {
  const dom = new JSDOM('<input id="search"><ul id="search-suggestions" hidden></ul>', { url: 'https://informa.test/' });
  globalThis.document = dom.window.document;
  const { createSearchSuggestions } = await import(`../../public/search-suggest.js?t=${Date.now()}${Math.random()}`);
  const input = dom.window.document.getElementById('search');
  const list = dom.window.document.getElementById('search-suggestions');
  const picked = [];
  createSearchSuggestions({ input, list, request, onSelect: item => picked.push(item), delay: 0 });
  input.focus();
  const type = async (value) => {
    input.value = value;
    input.dispatchEvent(new dom.window.Event('input'));
    await delay(15);
  };
  const key = (name) => input.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true }));
  return { dom, input, list, picked, type, key, close() { dom.window.close(); delete globalThis.document; } };
}

test('suggestions render as a grouped, accessible listbox and support keyboard selection', async () => {
  const requests = [];
  const env = await setup(async url => { requests.push(url); return { suggestions: SUGGESTIONS }; });
  try {
    await env.type('sec');
    assert.equal(requests[0], '/api/search/suggest?q=sec');
    assert.equal(env.list.hidden, false);
    assert.equal(env.input.getAttribute('role'), 'combobox');
    assert.equal(env.input.getAttribute('aria-expanded'), 'true');
    assert.deepEqual([...env.list.querySelectorAll('.suggest-group')].map(node => node.textContent), ['Topics', 'Publishers', 'Authors']);
    assert.equal(env.list.querySelectorAll('[role="option"]').length, 3);
    env.key('ArrowDown');
    env.key('ArrowDown');
    assert.equal(env.input.getAttribute('aria-activedescendant'), 'search-suggestions-1');
    env.key('Enter');
    assert.equal(env.picked[0].id, 'securityweek');
    assert.equal(env.list.hidden, true);
    assert.equal(env.input.getAttribute('aria-expanded'), 'false');
    await env.type('sec');
    assert.equal(requests.length, 1, 'repeat queries come from the cache');
    env.key('ArrowUp');
    assert.equal(env.input.getAttribute('aria-activedescendant'), 'search-suggestions-2');
    env.key('Escape');
    assert.equal(env.list.hidden, true);
  } finally { env.close(); }
});

test('short queries, failed requests and stale responses never show suggestions', async () => {
  let release;
  const unexpected = [];
  const env = await setup(async url => {
    if (url.includes('restored')) unexpected.push(url);
    if (url.endsWith('q=fail')) throw new Error('offline');
    if (url.endsWith('q=slow')) await new Promise(resolve => { release = resolve; });
    return { suggestions: SUGGESTIONS };
  });
  try {
    await env.type('s');
    assert.equal(env.list.hidden, true);
    env.input.blur();
    await env.type('restored view');
    assert.equal(env.list.hidden, true);
    assert.deepEqual(unexpected, [], 'programmatic values set while the box is unfocused do not fetch suggestions');
    env.input.focus();
    await env.type('fail');
    assert.equal(env.list.hidden, true);
    await env.type('slow');
    await env.type('');
    release();
    await delay(10);
    assert.equal(env.list.hidden, true, 'a response for text the reader already removed is discarded');
    env.list.querySelector('[role="option"]')?.click();
    assert.equal(env.picked.length, 0);
  } finally { env.close(); }
});
