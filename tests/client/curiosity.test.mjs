import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';

const html = readFileSync(new URL('../../public/index.html', import.meta.url), 'utf8');

test('Google Research monorepo paper appears as an attributed 2016 curiosity', () => {
  const document = new JSDOM(html).window.document;
  const card = document.querySelector('#curiosity-spotlight');

  assert.ok(card, 'the feed includes a Curiosity card');
  assert.equal(card.hidden, false);
  assert.match(card.textContent, /Curiosity/i);
  assert.match(card.querySelector('h2').textContent,
    /Why Google Stores Billions of Lines of Code in a Single Repository/);
  assert.equal(card.querySelector('time').getAttribute('datetime'), '2016');
  assert.match(card.querySelector('time').textContent, /2016/);
  assert.match(card.textContent, /Rachel Potvin/);
  assert.match(card.textContent, /Josh Levenberg/);
  assert.match(card.textContent, /Communications of the ACM/);
  assert.match(card.textContent, /common source of truth/i);
  assert.match(card.textContent, /trade-offs/i);

  const link = card.querySelector('a[href]');
  assert.equal(link.href,
    'https://research.google/pubs/why-google-stores-billions-of-lines-of-code-in-a-single-repository/');
  assert.equal(link.target, '_blank');
  assert.match(link.rel, /noopener/);
  assert.match(link.rel, /noreferrer/);
});
