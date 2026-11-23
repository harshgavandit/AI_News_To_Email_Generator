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
  assert.equal(MAX_CURIOSITY_CARDS, 160);
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

test('collection renders up to 160 cards with show-more paging', () => {
  const document = new JSDOM('<section id="cards"></section>').window.document;
  const container = document.querySelector('#cards');
  const cards = Array.from({ length: 170 }, (_, i) => ({ ...article, id: `card-${i}`, seed: true }));
  renderCuriosityCards(container, cards, { visibleCount: 200 });
  assert.equal(container.querySelectorAll('article').length, 160);
  renderCuriosityCards(container, cards, { visibleCount: 4 });
  assert.match(container.querySelector('[data-curiosity-show-more]').textContent, /Show 4 more/);
});

const rich = {
  id: 'riot-valorant-netcode', title: "Peeking into VALORANT's Netcode", company: 'Riot Games', publisher: 'Riot Games Tech Blog',
  published_at: '2020-07-28', year: 2020, summary: 'How the team approached peeker’s advantage.', summary_basis: 'editorial_source_summary',
  why_read: 'A first-party look at netcode trade-offs.', themes: ['game-engineering', 'distributed-systems'], theme: 'game-engineering',
  format: 'deep-dive', level: 'intermediate', technologies: ['Netcode'], tags: ['Netcode', 'Multiplayer'], read_minutes: 15, seed: true,
  url: 'https://www.riotgames.com/en/news/peeking-valorants-netcode',
};

test('cards show date, format, theme, technologies and a labelled reason to read', () => {
  const document = new JSDOM('<section id="cards"></section>').window.document;
  const container = document.querySelector('#cards');
  renderCuriosityCards(container, [rich], { actions: false });
  const card = container.querySelector('article');
  assert.equal(card.dataset.curiosityTheme, 'game-engineering');
  assert.equal(card.querySelector('time').dateTime, '2020-07-28');
  assert.equal(card.querySelector('time').textContent, 'Jul 28, 2020');
  assert.equal(card.querySelector('.curiosity-format').textContent, 'Deep dive');
  assert.equal(card.querySelector('.curiosity-theme').textContent, 'Game engineering');
  assert.equal(card.querySelector('.curiosity-level').textContent, 'Intermediate');
  assert.match(card.querySelector('.curiosity-why').textContent, /^Why read it A first-party look/);
  assert.equal(card.querySelector('.curiosity-question'), null, 'no question unless one was reviewed');
  renderCuriosityCards(container, [{ ...rich, question: 'How does VALORANT fight peeker’s advantage?' }], { actions: false });
  assert.match(container.querySelector('.curiosity-question').textContent, /^Answers How does VALORANT/);
  assert.deepEqual([...card.querySelectorAll('.curiosity-tag')].map((node) => node.textContent), ['Netcode', 'Multiplayer']);
  assert.equal(card.querySelectorAll('.curiosity-tech').length, 1);
  assert.equal(card.querySelector('[data-curiosity-pin]'), null, 'collection page cards carry no brief actions');
  assert.equal(card.querySelectorAll('a[href]').length, 1);
});

test('filters combine theme, format, company, search and newest-first sort', async () => {
  const { filterCuriosityCards } = await import('../../public/curiosity.js');
  const cards = [
    rich,
    { ...rich, id: 'roblox', title: 'Roblox Return to Service', company: 'Roblox', themes: ['reliability', 'game-engineering'], format: 'postmortem', technologies: ['Consul'], published_at: '2022-01-20' },
    { ...rich, id: 'rag', title: 'Introducing Contextual Retrieval', company: 'Anthropic', themes: ['ai'], format: 'deep-dive', technologies: ['RAG', 'BM25'], published_at: '2024-09-19' },
    { ...rich, id: 'old', title: 'Bigtable', company: 'Google', themes: ['databases'], format: 'paper', technologies: [], published_at: '', year: 2006 },
  ];
  const ids = (filter) => filterCuriosityCards(cards, filter).map((card) => card.id);
  assert.deepEqual(ids({ theme: 'game-engineering' }), ['riot-valorant-netcode', 'roblox']);
  assert.deepEqual(ids({ theme: 'game-engineering', format: 'postmortem' }), ['roblox']);
  assert.deepEqual(ids({ query: 'consul' }), ['roblox']);
  assert.deepEqual(ids({ query: 'bm25 anthropic' }), ['rag']);
  assert.deepEqual(ids({ query: 'reliability' }), ['roblox'], 'theme labels are searchable');
  assert.deepEqual(ids({ sort: 'newest' }), ['rag', 'roblox', 'riot-valorant-netcode', 'old']);
  assert.deepEqual(ids({ company: 'Google', theme: 'databases' }), ['old']);
  assert.deepEqual(ids({ level: 'intermediate' }), ['riot-valorant-netcode', 'roblox', 'rag', 'old']);
  assert.deepEqual(ids({ level: 'advanced' }), []);
});

test('homepage filters offer a theme select that reports the change', () => {
  const document = new JSDOM('<section id="cards"></section>').window.document;
  const container = document.querySelector('#cards');
  const cards = [rich, { ...rich, id: 'rag', company: 'Anthropic', themes: ['ai'] }];
  const filters = [];
  renderCuriosityCards(container, cards, { filter: { origin: 'all' }, onFilter: (f) => filters.push(f) });
  const select = container.querySelector('[data-curiosity-theme]');
  assert.deepEqual([...select.options].map((option) => option.value), ['all', 'game-engineering', 'ai', 'distributed-systems']);
  select.value = 'ai';
  select.dispatchEvent(new document.defaultView.Event('change'));
  assert.deepEqual(filters, [{ origin: 'all', theme: 'ai' }]);
});

test('collection page keeps filters in the URL and renders the API payload', async () => {
  const html = (await import('node:fs')).readFileSync(new URL('../../public/curiosity.html', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'https://getinformdaily.com/curiosity.html?theme=game-engineering&q=netcode' });
  const { window } = dom;
  for (const key of ['document', 'Option', 'Event']) globalThis[key] = window[key];
  const page = await import('../../public/curiosity-page.js');
  assert.deepEqual(page.readCuriosityState('?theme=bogus&format=talk&sort=newest&q=gpu'),
    { theme: 'all', format: 'talk', level: 'all', company: 'all', sort: 'newest', query: 'gpu' });
  assert.equal(page.readCuriosityState('?level=advanced').level, 'advanced');
  assert.equal(page.writeCuriosityState({ theme: 'ai', format: 'all', company: 'all', sort: 'featured', query: '' }), '?theme=ai');
  const urls = [];
  const replaced = [];
  await page.startCuriosityPage({
    fetcher: async (url) => { urls.push(url); return { ok: true, json: async () => ({ cards: [rich, { ...rich, id: 'rag', title: 'Contextual Retrieval', themes: ['ai'], technologies: ['RAG'], company: 'Anthropic' }] }) }; },
    history: { replaceState: (_, __, url) => replaced.push(url) },
    location: window.location,
  });
  assert.deepEqual(urls, ['/api/curiosity?limit=160']);
  const articles = [...window.document.querySelectorAll('#curiosity-collection article')].map((node) => node.dataset.curiosityId);
  assert.deepEqual(articles, ['riot-valorant-netcode']);
  assert.equal(window.document.querySelector('[data-theme="game-engineering"]').getAttribute('aria-pressed'), 'true');
  assert.match(window.document.getElementById('curiosity-result-status').textContent, /1 story in Game engineering/);
  assert.equal(window.document.getElementById('curiosity-stat-cards').textContent, '2');
  assert.equal(replaced.at(-1), '/curiosity.html?theme=game-engineering&q=netcode');
  window.document.querySelector('[data-theme="all"]').click();
  assert.equal(replaced.at(-1), '/curiosity.html?q=netcode');
  for (const key of ['document', 'Option', 'Event']) delete globalThis[key];
});
