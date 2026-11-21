import assert from 'node:assert/strict';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { renderCuriosityCards } from '../../public/curiosity.js';

const article = {
  id: 'attention-is-all-you-need',
  title: 'Attention Is All You Need',
  company: 'Google',
  publisher: 'Google Research',
  author: 'Ashish Vaswani and co-authors',
  year: 2017,
  summary: 'The Transformer paper presents an attention-based sequence model.',
  summary_basis: 'publisher_excerpt',
  tags: ['Transformers', 'Attention', 'Machine learning'],
  read_minutes: 15,
  url: 'https://research.google/pubs/attention-is-all-you-need/',
  kind: 'research',
};

test('curiosity cards present source context, tags, reading time, and safe original links', () => {
  const document = new JSDOM('<section id="cards"></section>').window.document;
  const container = document.querySelector('#cards');
  renderCuriosityCards(container, [article], { pinnedIds: [], scheduledIds: [], verified: true });

  const card = container.querySelector('[data-curiosity-id="attention-is-all-you-need"]');
  assert.ok(card);
  assert.match(card.textContent, /Google Research/);
  assert.match(card.textContent, /Ashish Vaswani/);
  assert.match(card.textContent, /Publisher excerpt/);
  assert.match(card.textContent, /Transformers/);
  assert.match(card.textContent, /15 min read/);
  const link = card.querySelector('a[href]');
  assert.equal(link.href, article.url);
  assert.equal(link.target, '_blank');
  assert.match(link.rel, /noopener/);
  assert.match(link.rel, /noreferrer/);
});

test('manual and scheduled selection controls expose state and invoke callbacks', () => {
  const document = new JSDOM('<section id="cards"></section>').window.document;
  const container = document.querySelector('#cards');
  const events = [];
  renderCuriosityCards(container, [article], {
    pinnedIds: [], scheduledIds: [article.id], verified: true, scheduledEnabled: true,
    onPin: (card) => events.push(['pin', card.id]),
    onToggleScheduled: (card, selected) => events.push(['scheduled', card.id, selected]),
  });

  const card = container.querySelector('article');
  const pin = card.querySelector('[data-curiosity-pin]');
  const scheduled = card.querySelector('[data-curiosity-scheduled]');
  assert.equal(pin.getAttribute('aria-pressed'), 'false');
  assert.equal(scheduled.getAttribute('aria-pressed'), 'true');
  pin.click();
  scheduled.click();
  assert.deepEqual(events, [['pin', article.id], ['scheduled', article.id, true]]);
});

test('unverified schedule control requests verification and text remains inert', () => {
  const document = new JSDOM('<section id="cards"></section>').window.document;
  const container = document.querySelector('#cards');
  const unsafe = { ...article, summary: '<img src=x onerror=alert(1)> literal publisher text' };
  let requested;
  renderCuriosityCards(container, [unsafe], {
    pinnedIds: [], scheduledIds: [], verified: false,
    onToggleScheduled: (card) => { requested = card.id; },
  });
  container.querySelector('[data-curiosity-scheduled]').click();

  assert.equal(requested, article.id);
  assert.equal(container.querySelector('img'), null);
  assert.match(container.textContent, /literal publisher text/);
  assert.match(container.textContent, /Verify to schedule/);
});

test('empty state explains the collection without rendering a fake card', () => {
  const document = new JSDOM('<section id="cards"></section>').window.document;
  const container = document.querySelector('#cards');
  renderCuriosityCards(container, [], {});
  assert.match(container.textContent, /No Curiosity Cards are available/);
  assert.equal(container.querySelector('article'), null);
});

test('longer collections reveal additional cards on demand', () => {
  const document = new JSDOM('<section id="cards"></section>').window.document;
  const container = document.querySelector('#cards');
  const cards = Array.from({ length: 6 }, (_, index) => ({ ...article, id: `card-${index}`, title: `Engineering case study ${index}` }));
  let visibleCount = 2;
  const render = () => renderCuriosityCards(container, cards, { visibleCount, onShowMore: () => { visibleCount += 4; render(); } });
  render();
  assert.equal(container.querySelectorAll('article').length, 2);
  container.querySelector('[data-curiosity-show-more]').click();
  assert.equal(container.querySelectorAll('article').length, 6);
  assert.equal(container.querySelector('[data-curiosity-show-more]'), null);
});

test('filters narrow cards by origin and company and report the selection', async () => {
  const { filterCuriosityCards, curiosityCompanies, MAX_CURIOSITY_CARDS } = await import('../../public/curiosity.js');
  const cards = [
    { ...article, id: 'seed-google', seed: true },
    { ...article, id: 'seed-stripe', company: 'Stripe', publisher: 'Stripe', seed: true },
    { ...article, id: 'fresh-stripe', company: 'Stripe', publisher: 'Stripe', seed: false },
  ];
  assert.equal(MAX_CURIOSITY_CARDS, 72);
  assert.deepEqual(curiosityCompanies(cards), ['Google', 'Stripe']);
  assert.deepEqual(filterCuriosityCards(cards, { origin: 'fresh' }).map((c) => c.id), ['fresh-stripe']);
  assert.deepEqual(filterCuriosityCards(cards, { origin: 'classic', company: 'Stripe' }).map((c) => c.id), ['seed-stripe']);

  const document = new JSDOM('<section id="cards"></section>').window.document;
  const container = document.querySelector('#cards');
  const filters = [];
  renderCuriosityCards(container, cards, { filter: { origin: 'all', company: 'Stripe' }, onFilter: (f) => filters.push(f) });
  assert.deepEqual([...container.querySelectorAll('article')].map((n) => n.dataset.curiosityId), ['seed-stripe', 'fresh-stripe']);
  assert.equal(container.querySelector('[data-curiosity-origin="all"]').getAttribute('aria-pressed'), 'true');
  assert.match(container.querySelector('[data-curiosity-id="fresh-stripe"]').textContent, /Fresh/);
  assert.doesNotMatch(container.querySelector('[data-curiosity-id="seed-stripe"] .curiosity-card-top').textContent, /Fresh/);
  container.querySelector('[data-curiosity-origin="fresh"]').click();
  const select = container.querySelector('[data-curiosity-company]');
  select.value = 'Google';
  select.dispatchEvent(new document.defaultView.Event('change'));
  assert.deepEqual(filters, [{ origin: 'fresh', company: 'Stripe' }, { origin: 'all', company: 'Google' }]);

  renderCuriosityCards(container, cards, { filter: { origin: 'fresh', company: 'Google' } });
  assert.match(container.textContent, /No Curiosity Cards match this filter/);
  assert.ok(container.querySelector('[data-curiosity-origin]'), 'filters stay available on an empty result');
});

test('collection renders up to 72 cards with show-more paging', () => {
  const document = new JSDOM('<section id="cards"></section>').window.document;
  const container = document.querySelector('#cards');
  const cards = Array.from({ length: 80 }, (_, i) => ({ ...article, id: `card-${i}`, seed: true }));
  renderCuriosityCards(container, cards, { visibleCount: 72 });
  assert.equal(container.querySelectorAll('article').length, 72);
  renderCuriosityCards(container, cards, { visibleCount: 4 });
  assert.match(container.querySelector('[data-curiosity-show-more]').textContent, /Show 4 more/);
});
