import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';

const home = readFileSync(new URL('../../public/index.html', import.meta.url), 'utf8');
const stylesheets = [...home.matchAll(/<link rel="stylesheet" href="\/(.*?)"/g)]
  .map(([, file]) => readFileSync(new URL(`../../public/${file}`, import.meta.url), 'utf8'));
const coverage = '<article class="coverage-lead"><div class="coverage-meta"><span class="source-badge">Research</span><time>Updated today</time></div><h3>A developing technology story</h3><p>An attributed overview of reporting from several publishers.</p><div class="coverage-actions"><details><summary>Sources (2)</summary><ul class="coverage-links"><li>Publisher source</li></ul></details><a href="/?q=research">Browse coverage</a></div></article>';
const headlines = '<ul class="headline-list"><li><h3>A recent industry development</h3><p>Publisher · Today</p></li><li><h3>Another recent development</h3><p>Publisher · Today</p></li></ul>';

for (const [label, content] of [['coverage and headlines', coverage + headlines], ['headlines only', headlines], ['coverage only', coverage]]) {
  test(`Developing stories uses the full rail width with ${label}`, () => {
    const dom = new JSDOM(`<aside class="intelligence-rail"><section class="headlines"><div class="headlines-content${content.includes('coverage-lead') ? ' with-coverage' : ''}">${content}</div></section></aside>`);
    try {
      for (const css of stylesheets) {
        const style = dom.window.document.createElement('style');
        style.textContent = css;
        dom.window.document.head.append(style);
      }
      const panel = dom.window.document.querySelector('.headlines-content');
      const computed = dom.window.getComputedStyle(panel);
      assert.equal(computed.display, 'grid');
      assert.equal(computed.gridTemplateColumns, 'minmax(0px, 1fr)', 'Coverage and headlines must stack instead of splitting a narrow rail');
      assert.equal(computed.alignItems, 'start', 'The overview must not stretch its sibling headline list');
      if (panel.querySelector('.headline-list')) {
        assert.equal(dom.window.getComputedStyle(panel.querySelector('.headline-list')).gridTemplateColumns, 'minmax(0px, 1fr)');
        assert.equal(dom.window.getComputedStyle(panel.querySelector('.headline-list')).alignContent, 'start');
      }
    } finally { dom.window.close(); }
  });
}
