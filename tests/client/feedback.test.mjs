import assert from 'node:assert/strict';
import test from 'node:test';
import { JSDOM } from 'jsdom';

async function setup(body) {
  const dom = new JSDOM(`<!doctype html><body>${body}</body>`, { url: 'https://getinformdaily.com/recap.html' });
  globalThis.document = dom.window.document;
  globalThis.location = dom.window.location;
  globalThis.FormData = dom.window.FormData;
  const module = await import(`../../public/feedback.js?t=${Math.random()}`);
  const calls = [];
  const reply = { status: 204, body: {} };
  const fetcher = async (url, init) => { calls.push({ url, body: JSON.parse(init.body) });
    return { ok: reply.status < 300, status: reply.status, json: async () => reply.body }; };
  return { dom, module, calls, reply, fetcher, cleanup() { for (const key of ['document', 'location', 'FormData']) delete globalThis[key]; dom.window.close(); } };
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 10));

test('a feedback button joins the footer and sends the message with the page path', async () => {
  const { dom, module, calls, reply, fetcher, cleanup } = await setup('<footer class="site-footer"><nav class="footer-nav"><a href="/">Home</a></nav></footer>');
  try {
    module.mountFeedback({ fetcher });
    const doc = dom.window.document;
    const trigger = doc.querySelector('.footer-nav [data-feedback-open]');
    assert.equal(trigger.textContent, 'Send feedback');
    trigger.click();
    const form = doc.querySelector('.feedback-form');
    form.querySelector('textarea').value = 'ok';
    form.dispatchEvent(new dom.window.Event('submit', { cancelable: true }));
    assert.match(form.querySelector('[role=status]').textContent, /few words/);
    form.querySelector('textarea').value = 'Please add a Rust tracker';
    form.querySelector('input[value=bug]').checked = true;
    form.querySelector('input[type=email]').value = 'me@example.com';
    form.dispatchEvent(new dom.window.Event('submit', { cancelable: true }));
    await settle();
    assert.deepEqual(calls[0], { url: '/api/feedback', body: { page: '/recap.html', kind: 'bug', message: 'Please add a Rust tracker',
      contact: 'me@example.com', website: '' } });
    assert.equal(form.querySelector('[role=status]').textContent, 'Thank you. Your feedback was sent.');
    reply.status = 422; reply.body = { detail: [{ msg: 'Value error, Enter a valid email address, or leave it empty.' }] };
    form.querySelector('textarea').value = 'Another note';
    form.dispatchEvent(new dom.window.Event('submit', { cancelable: true }));
    await settle();
    assert.equal(form.querySelector('[role=status]').textContent, 'Enter a valid email address, or leave it empty.');
  } finally { cleanup(); }
});

test('pages without a footer get the button in the header tools; "Was this useful?" sends one answer', async () => {
  const { dom, module, calls, fetcher, cleanup } = await setup('<div class="site-tools"></div><div data-useful></div>');
  try {
    module.mountFeedback({ fetcher });
    const doc = dom.window.document;
    assert.ok(doc.querySelector('.site-tools [data-feedback-open]'));
    const [yes, no] = doc.querySelectorAll('[data-useful] button');
    no.click();
    await settle();
    assert.deepEqual(calls.map((call) => call.body.kind), ['not_useful']);
    assert.equal(yes.disabled, true);
    assert.match(doc.querySelector('.useful-status').textContent, /What was missing\?/);
  } finally { cleanup(); }
});

test('missing coverage opens the reporting category and catch-up votes are distinct', async () => {
  const { dom, module, calls, fetcher, cleanup } = await setup(
    '<button data-feedback-open data-feedback-kind="coverage">Missing coverage?</button><div data-useful="update"></div>');
  try {
    module.mountFeedback({ fetcher });
    const doc = dom.window.document;
    doc.querySelector('[data-feedback-kind=coverage]').click();
    assert.equal(doc.querySelector('input[name=kind]:checked').value, 'coverage');
    assert.match(doc.querySelector('textarea').placeholder, /original link/);
    doc.querySelector('[data-useful] button').click();
    await settle();
    assert.equal(calls[0].body.kind, 'update_yes');
  } finally { cleanup(); }
});
