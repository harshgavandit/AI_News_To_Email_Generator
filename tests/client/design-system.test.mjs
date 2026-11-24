import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';

const root = new URL('../../public/', import.meta.url);
// offline.html is the service worker's standalone fallback and deliberately loads no site stylesheets.
const pages = readdirSync(root).filter(name => name.endsWith('.html') && name !== 'offline.html');

test('every page loads the design-system layer after the legacy stylesheets', () => {
  assert.ok(pages.length >= 11);
  for (const page of pages) {
    const html = readFileSync(new URL(page, root), 'utf8');
    const sheets = [...html.matchAll(/<link rel="stylesheet" href="([^"]+)"/g)].map(match => match[1]);
    assert.deepEqual(sheets.slice(-4), ['/system.css', '/command.css', '/orbital.css', '/signature.css'],
      `${page} must load system.css, command.css, orbital.css, then the signature finishing layer last`);
    assert.match(html, /<script defer src="\/system\.js"><\/script>/, `${page} must load system.js`);
    assert.match(html, /<script defer src="\/ambient\.js"><\/script>/, `${page} must load ambient.js`);
    assert.ok(html.indexOf('/ambient.js') < html.indexOf('/orbital.js'), `${page} must load orbital.js after ambient.js`);
  }
});

test('the design-system stylesheets gate motion and avoid external resources', () => {
  for (const sheet of ['system.css', 'command.css', 'orbital.css', 'signature.css']) {
    const css = readFileSync(new URL(sheet, root), 'utf8');
    assert.match(css, /prefers-reduced-motion: reduce/);
    assert.match(css, /forced-colors: active/);
    for (const match of css.matchAll(/url\(["']?(https?:)/g)) assert.fail(`External resource ${match[1]}`);
  }
  const command = readFileSync(new URL('command.css', root), 'utf8');
  assert.match(command, /:root\[data-motion="off"\]/, 'the motion switch must stop decorative animation');
  assert.match(command, /@media print/);
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

test('reader-facing errors hide programming and network failures but keep server details', async () => {
  const { readableError } = await import('../../public/evidence-ui.js');
  const fallback = 'This information is temporarily unavailable. Try again in a moment.';
  assert.equal(readableError(new TypeError("Cannot read properties of undefined (reading 'find')")), fallback);
  assert.equal(readableError(new TypeError('Failed to fetch')), fallback);
  assert.equal(readableError(new ReferenceError('x is not defined')), fallback);
  assert.equal(readableError(new Error('Verify your inbox to continue.')), 'Verify your inbox to continue.');
  assert.equal(readableError(undefined, 'Try later.'), 'Try later.');
});

test('workspace pages share one navigation that includes the Inbox', () => {
  for (const page of ['research.html', 'technology.html', 'projects.html', 'inbox.html', 'development.html']) {
    const html = readFileSync(new URL(page, root), 'utf8');
    const nav = html.match(/<nav class="site-nav research-nav"[^>]*>([\s\S]*?)<\/nav>/)?.[1] || '';
    for (const href of ['/#reading-room', '/research.html', '/technology.html', '/projects.html', '/inbox.html']) {
      assert.match(nav, new RegExp(`href="${href.replace(/[.#/]/g, '\\$&')}"`), `${page} links ${href}`);
    }
    assert.match(html, /id="site-theme"/, `${page} offers the theme control`);
  }
});

function depthWindow({ top = 0, reduce = false } = {}) {
  const dom = new JSDOM(`<body><section class="desk-masthead"><div><h1>Desk</h1></div></section>
    <div id="stories"></div><section class="research-panel" id="below">Panel</section></body>`,
  { url: 'https://informa.test/', runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;
  window.matchMedia = query => ({ matches: query.includes('reduce') ? reduce : true, media: query, addEventListener() {}, removeEventListener() {} });
  window.scrollTo = () => {};
  const observed = [];
  window.IntersectionObserver = class { constructor(callback) { this.callback = callback; } observe(element) { observed.push([this, element]); } unobserve() {} };
  window.document.getElementById('below').getBoundingClientRect = () => ({ top, bottom: top + 100, left: 0, right: 100, width: 100, height: 100 });
  window.eval(readFileSync(new URL('system.js', root), 'utf8'));
  return { window, observed };
}

test('only content that starts below the fold waits for a scroll reveal', async () => {
  const visible = depthWindow({ top: 10 });
  await new Promise(resolve => setTimeout(resolve, 40));
  assert.equal(visible.window.document.getElementById('below').dataset.sysReveal, undefined);
  visible.window.close();

  const below = depthWindow({ top: 5000 });
  await new Promise(resolve => setTimeout(resolve, 40));
  const panel = below.window.document.getElementById('below');
  assert.equal(panel.dataset.sysReveal, 'pending');
  const [[observer, element]] = below.observed;
  observer.callback([{ isIntersecting: true, target: element }]);
  assert.equal(panel.dataset.sysReveal, 'shown');
  below.window.close();
});

test('reduced motion never hides content for a reveal', async () => {
  const { window } = depthWindow({ top: 5000, reduce: true });
  await new Promise(resolve => setTimeout(resolve, 40));
  assert.equal(window.document.getElementById('below').dataset.sysReveal, undefined);
  window.close();
});

test('the depth layer removes its motion under reduced motion and forced colours', () => {
  const css = readFileSync(new URL('system.css', root), 'utf8');
  const reduced = [...css.matchAll(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/g)].map(match => match[1]).join('\n');
  for (const selector of ['body::before', '.desk-masthead::before', '.research-header::before', '[data-sys-reveal]', '.dossier-drawer[open]'])
    assert.ok(reduced.includes(selector), `${selector} must be disabled under reduced motion`);
});

test('reveal animation never hides tall panels or waits for a fraction of a long list', () => {
  const script = readFileSync(new URL('system.js', root), 'utf8');
  assert.match(script, /threshold: 0 \}/);
  assert.match(script, /box\.height > innerHeight \* 1\.2/);
});
