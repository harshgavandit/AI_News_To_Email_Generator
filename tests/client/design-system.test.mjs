import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';

const root = new URL('../../public/', import.meta.url);
const pages = readdirSync(root).filter(name => name.endsWith('.html'));

test('every page loads the design-system layer after the legacy stylesheets', () => {
  assert.ok(pages.length >= 11);
  for (const page of pages) {
    const html = readFileSync(new URL(page, root), 'utf8');
    const sheets = [...html.matchAll(/<link rel="stylesheet" href="([^"]+)"/g)].map(match => match[1]);
    assert.equal(sheets.at(-1), '/system.css', `${page} must load system.css last`);
    assert.match(html, /<script defer src="\/system\.js"><\/script>/, `${page} must load system.js`);
  }
});

test('the design-system stylesheet gates motion and avoids external resources', () => {
  const css = readFileSync(new URL('system.css', root), 'utf8');
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /forced-colors: active/);
  for (const match of css.matchAll(/url\(["']?(https?:)/g)) assert.fail(`External resource ${match[1]}`);
});

test('story cards get stagger indexes and action toasts mirror the status region', async () => {
  const dom = new JSDOM('<body><main><div id="stories"></div><input id="search"><p id="story-action-status" role="status"></p></main></body>',
    { url: 'https://informa.test/', runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;
  window.matchMedia = query => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} });
  window.scrollTo = () => {};
  window.eval(readFileSync(new URL('system.js', root), 'utf8'));
  const stories = window.document.getElementById('stories');
  for (let i = 0; i < 3; i++) stories.append(Object.assign(window.document.createElement('article'), { className: 'story' }));
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual([...stories.children].map(card => card.style.getPropertyValue('--sys-i')), ['0', '1', '2']);
  window.document.getElementById('story-action-status').textContent = 'Story saved. 1 saved on this browser.';
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(window.document.querySelector('.sys-toast')?.textContent, 'Story saved. 1 saved on this browser.');
  const press = new window.KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true });
  window.document.body.dispatchEvent(press);
  window.close();
});
