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

const settle = () => new Promise((resolve) => setTimeout(resolve, 20));

// A stand-in for GET /api/curiosity/cards: filters like the server, pages by cursor, counts facets over all cards.
async function cardsApi(cards, url, limitOverride) {
  const { filterCuriosityCards } = await import('../../public/curiosity.js');
  const params = new URL(url, 'https://informa.test').searchParams;
  const filter = Object.fromEntries(['theme', 'problem', 'format', 'level', 'company', 'origin', 'sort'].map((key) => [key, params.get(key) || 'all']));
  filter.query = params.get('q') || '';
  const matches = filterCuriosityCards(cards, filter);
  const offset = Number(params.get('cursor') || 0);
  const limit = limitOverride || Number(params.get('limit') || 24);
  const themes = {};
  const pairs = {};
  for (const card of cards) {
    const ids = [...new Set(card.themes || [card.theme])];
    for (const id of ids) themes[id] = (themes[id] || 0) + 1;
  }
  const companies = [...new Set(cards.map((card) => card.company))].sort().map((name) => [name, cards.filter((card) => card.company === name).length]);
  const fresh = cards.filter((card) => !card.seed).length;
  const technologies = {};
  for (const card of cards) for (const label of new Set(card.technologies || [])) technologies[label] = (technologies[label] || 0) + 1;
  return {
    cards: matches.slice(offset, offset + limit), total: matches.length, version: 'v1',
    next_cursor: offset + limit < matches.length ? String(offset + limit) : null,
    facets: { total: cards.length, fresh, classic: cards.length - fresh, themes, problems: {}, formats: {}, levels: {}, companies,
      theme_pairs: Object.entries(pairs), technologies: Object.entries(technologies).filter(([, n]) => n >= 3).map(([label]) => label) },
    labels: {},
  };
}

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
  assert.equal(MAX_CURIOSITY_CARDS, 240);
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

test('collection renders up to 240 cards with show-more paging', () => {
  const document = new JSDOM('<section id="cards"></section>').window.document;
  const container = document.querySelector('#cards');
  const cards = Array.from({ length: 250 }, (_, i) => ({ ...article, id: `card-${i}`, seed: true }));
  renderCuriosityCards(container, cards, { visibleCount: 300 });
  assert.equal(container.querySelectorAll('article').length, 240);
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
    { theme: 'all', format: 'talk', level: 'all', problem: 'all', company: 'all', sort: 'newest', query: 'gpu', list: '' });
  assert.equal(page.readCuriosityState('?level=advanced').level, 'advanced');
  assert.equal(page.writeCuriosityState({ theme: 'ai', format: 'all', company: 'all', sort: 'featured', query: '' }), '?theme=ai');
  const urls = [];
  const replaced = [];
  await page.startCuriosityPage({
    fetcher: async (url) => {
      urls.push(url);
      const all = [rich, { ...rich, id: 'rag', title: 'Contextual Retrieval', themes: ['ai'], technologies: ['RAG'], company: 'Anthropic' }];
      return { ok: true, status: 200, json: async () => (url === '/api/curiosity/collections' ? { collections: [] } : cardsApi(all, url)) };
    },
    history: { replaceState: (_, __, url) => replaced.push(url) },
    location: window.location,
  });
  assert.deepEqual(urls.sort(), ['/api/curiosity/cards?limit=24&theme=game-engineering&q=netcode', '/api/curiosity/collections', '/api/curiosity/popular'],
    'the server receives the filters; the page never downloads the whole collection');
  const articles = [...window.document.querySelectorAll('#curiosity-collection article')].map((node) => node.dataset.curiosityId);
  assert.deepEqual(articles, ['riot-valorant-netcode']);
  assert.equal(window.document.querySelector('[data-theme="game-engineering"]').getAttribute('aria-pressed'), 'true');
  assert.match(window.document.getElementById('curiosity-result-status').textContent, /1 story in Game engineering/);
  assert.equal(window.document.getElementById('curiosity-stat-cards').textContent, '2');
  assert.equal(replaced.at(-1), '/curiosity.html?theme=game-engineering&q=netcode');
  window.document.querySelector('[data-theme="all"]').click();
  assert.equal(replaced.at(-1), '/curiosity.html?q=netcode');
  await settle();
  assert.equal(urls.at(-1), '/api/curiosity/cards?limit=24&q=netcode', 'changing a filter asks the server for the first page again');
  for (const key of ['document', 'Option', 'Event']) delete globalThis[key];
});


test('real-world problems: filter, label, URL state and the reviewed three-line breakdown', async () => {
  const curiosity = await import('../../public/curiosity.js');
  const outage = { ...rich, id: 'gitlab', title: 'Postmortem of database outage', company: 'GitLab', seed: true,
    problems: ['outages', 'data-integrity'],
    breakdown: { problem: 'Data was removed from the primary.', approach: 'Restored from an LVM snapshot.', result: 'About six hours of changes were lost.' } };
  const fresh = { ...rich, id: 'fresh', title: 'Scaling ML inference', company: 'CRED', seed: false, problems: ['performance'] };
  const cards = [rich, outage, fresh];
  assert.deepEqual(curiosity.filterCuriosityCards(cards, { problem: 'outages' }).map((card) => card.id), ['gitlab']);
  assert.deepEqual(curiosity.filterCuriosityCards(cards, { problem: 'performance' }).map((card) => card.id), ['fresh']);
  assert.deepEqual(curiosity.filterCuriosityCards(cards, { query: 'lvm snapshot' }).map((card) => card.id), ['gitlab'],
    'search covers the breakdown lines');
  assert.deepEqual(curiosity.filterCuriosityCards(cards, { query: 'data loss' }).map((card) => card.id), ['gitlab'],
    'search covers problem labels');

  const document = new JSDOM('<section id="cards"></section>').window.document;
  const container = document.querySelector('#cards');
  curiosity.renderCuriosityCards(container, cards, { filters: false });
  const card = container.querySelector('[data-curiosity-id="gitlab"]');
  assert.equal(card.querySelector('.curiosity-problem').textContent, 'Outages & incidents');
  const rows = [...card.querySelectorAll('.curiosity-breakdown div')].map((row) => [row.querySelector('dt').textContent, row.querySelector('dd').textContent]);
  assert.deepEqual(rows, [['The problem', 'Data was removed from the primary.'], ['What they did', 'Restored from an LVM snapshot.'],
    ['The result', 'About six hours of changes were lost.']]);
  assert.equal(container.querySelector('[data-curiosity-id="fresh"] .curiosity-breakdown'), null, 'no breakdown without reviewed lines');
  curiosity.renderCuriosityCards(container, [{ ...outage, breakdown: { problem: 'x', approach: '', result: 'y' } }], { filters: false });
  assert.equal(container.querySelector('.curiosity-breakdown'), null, 'incomplete breakdowns are not shown');
  curiosity.renderCuriosityCards(container, [{ ...outage, breakdown: { problem: '<img src=x onerror=alert(1)>', approach: 'a', result: 'b' } }], { filters: false });
  assert.equal(container.querySelector('img'), null, 'breakdown text is never parsed as markup');

  const page = await import('../../public/curiosity-page.js');
  assert.equal(page.readCuriosityState('?problem=outages').problem, 'outages');
  assert.equal(page.readCuriosityState('?problem=bogus').problem, 'all');
  assert.equal(page.writeCuriosityState({ theme: 'all', problem: 'migrations', format: 'all', company: 'all', sort: 'featured', query: '' }),
    '?problem=migrations');
});


test('reading lists: rendered from the API, shown whole in reading order, and handed to the Brief Builder', async () => {
  const html = (await import('node:fs')).readFileSync(new URL('../../public/curiosity.html', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'https://getinformdaily.com/curiosity.html?list=anatomy&theme=ai' });
  const { window } = dom;
  for (const key of ['document', 'Option', 'Event']) globalThis[key] = window[key];
  try {
    const page = await import(`../../public/curiosity-page.js?lists=${Date.now()}`);
    assert.equal(page.readCuriosityState('?list=anatomy').list, 'anatomy');
    assert.equal(page.readCuriosityState('?list=<script>').list, '', 'list ids are slugs');
    assert.equal(page.writeCuriosityState({ theme: 'all', problem: 'all', format: 'all', company: 'all', sort: 'featured', query: '', list: 'anatomy' }),
      '?list=anatomy');
    const second = { ...rich, id: 'second', title: 'Second in the list', company: 'Meta' };
    const lists = { collections: [
      { id: 'anatomy', title: 'Anatomy of a global outage', summary: 'How outages unfold.', read_minutes: 30,
        companies: ['Riot Games', 'Meta'], cards: [second, rich] },
      { id: 'empty', title: 'Nothing here', summary: 'x', cards: [] },
    ] };
    const replaced = [];
    await page.startCuriosityPage({
      fetcher: async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/curiosity/collections' ? lists : cardsApi([rich], url)) }),
      history: { replaceState: (_, __, url) => replaced.push(url) },
      location: window.location,
    });
    const doc = window.document;
    assert.equal(doc.getElementById('curiosity-lists').hidden, false);
    const listCards = [...doc.querySelectorAll('#curiosity-list-grid article')];
    assert.deepEqual(listCards.map((node) => node.dataset.list), ['anatomy'], 'empty lists are not shown');
    assert.match(listCards[0].textContent, /2 stories · 30 min · Riot Games, Meta/);
    assert.equal(listCards[0].querySelector('a').getAttribute('href'), '/?brief-list=anatomy#composer');
    // The ?list= link opens the list whole, in reading order, and hides the theme and filter controls.
    assert.deepEqual([...doc.querySelectorAll('#curiosity-collection article')].map((node) => node.dataset.curiosityId), ['second', 'riot-valorant-netcode']);
    assert.equal(doc.getElementById('curiosity-list-banner').hidden, false);
    assert.equal(doc.getElementById('curiosity-list-name').textContent, 'Anatomy of a global outage');
    assert.equal(doc.getElementById('curiosity-controls').hidden, true);
    assert.match(doc.getElementById('curiosity-result-status').textContent, /2 stories in reading order/);
    assert.match(replaced.at(-1), /list=anatomy/);
    doc.getElementById('curiosity-list-clear').click();
    assert.equal(doc.getElementById('curiosity-list-banner').hidden, true);
    assert.equal(doc.getElementById('curiosity-controls').hidden, false);
    assert.doesNotMatch(replaced.at(-1), /list=/);
    listCards[0].querySelector('button').click();
    assert.equal(doc.getElementById('curiosity-list-banner').hidden, false);
  } finally {
    for (const key of ['document', 'Option', 'Event']) delete globalThis[key];
    window.close();
  }
});

test('the collection page still works when reading lists cannot load', async () => {
  const html = (await import('node:fs')).readFileSync(new URL('../../public/curiosity.html', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'https://getinformdaily.com/curiosity.html?list=gone' });
  const { window } = dom;
  for (const key of ['document', 'Option', 'Event']) globalThis[key] = window[key];
  try {
    const page = await import(`../../public/curiosity-page.js?nolists=${Date.now()}`);
    await page.startCuriosityPage({
      fetcher: async (url) => (url === '/api/curiosity/collections' ? { ok: false } : { ok: true, status: 200, json: async () => cardsApi([rich], url) }),
      history: { replaceState() {} }, location: window.location,
    });
    assert.equal(window.document.getElementById('curiosity-lists').hidden, true);
    assert.equal(window.document.getElementById('curiosity-list-banner').hidden, true, 'an unknown ?list= falls back to the collection');
    assert.equal(window.document.querySelectorAll('#curiosity-collection article').length, 1);
  } finally {
    for (const key of ['document', 'Option', 'Event']) delete globalThis[key];
    window.close();
  }
});

test('read next links, popular searches and lessons on the collection page', async () => {
  const { popularSearches } = await import('../../public/curiosity.js');
  const withRelated = { ...rich, id: 'with-related', related: [
    { id: 'next-one', title: 'The next story', company: 'Meta', url: 'https://engineering.fb.com/next/' },
    { id: 'bad', title: 'Unsafe', company: 'X', url: 'javascript:alert(1)' },
  ] };
  const plain = new JSDOM('<section id="cards"></section>').window.document;
  renderCuriosityCards(plain.querySelector('#cards'), [withRelated], { actions: false });
  const related = [...plain.querySelectorAll('.curiosity-related-link')];
  assert.deepEqual(related.map((link) => link.textContent), ['The next story'], 'only safe https links are offered');
  assert.equal(related[0].target, '_blank');
  assert.match(plain.querySelector('.curiosity-related').textContent, /Read next.*Meta/s);

  const tech = (id, technologies) => ({ ...rich, id, technologies });
  assert.deepEqual(popularSearches([tech('a', ['Postgres', 'DNS']), tech('b', ['Postgres', 'DNS']), tech('c', ['Postgres', 'DNS', 'Rust']),
    tech('d', ['Postgres'])]), ['Postgres', 'DNS'], 'technologies named on at least three cards, most common first');

  const html = (await import('node:fs')).readFileSync(new URL('../../public/curiosity.html', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'https://getinformdaily.com/curiosity.html' });
  const { window } = dom;
  for (const key of ['document', 'Option', 'Event']) globalThis[key] = window[key];
  try {
    const page = await import(`../../public/curiosity-page.js?lessons=${Date.now()}`);
    const cards = ['a', 'b', 'c'].map((id) => tech(id, ['Kubernetes']));
    const payload = { collections: [], lessons: [
      { id: 'lesson-stage-every-rollout', title: 'Roll out every change in stages', summary: 'Small slices first.', kind: 'lesson',
        read_minutes: 20, companies: ['Riot Games'], cards: [cards[1], cards[0]] }] };
    await page.startCuriosityPage({
      fetcher: async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/curiosity/collections' ? payload : cardsApi(cards, url)) }),
      history: { replaceState() {} }, location: window.location,
    });
    const doc = window.document;
    assert.equal(doc.getElementById('curiosity-lists').hidden, true, 'no reading lists in this payload');
    assert.equal(doc.getElementById('curiosity-lessons').hidden, false);
    const lesson = doc.querySelector('#curiosity-lesson-grid article');
    assert.equal(lesson.querySelector('a').getAttribute('href'), '/?brief-list=lesson-stage-every-rollout#composer');
    const chips = [...doc.querySelectorAll('#curiosity-suggestions button')];
    assert.deepEqual(chips.map((chip) => chip.textContent), ['Kubernetes']);
    chips[0].click();
    assert.equal(doc.getElementById('curiosity-query').value, 'Kubernetes');
    await settle();
    lesson.querySelector('button').click();
    assert.equal(doc.getElementById('curiosity-list-kind').textContent, 'Lesson');
    assert.deepEqual([...doc.querySelectorAll('#curiosity-collection article')].map((node) => node.dataset.curiosityId), ['b', 'a']);
    assert.equal(doc.getElementById('curiosity-suggestions').hidden, true, 'search suggestions step aside with the filters');
  } finally {
    for (const key of ['document', 'Option', 'Event']) delete globalThis[key];
    window.close();
  }
});

test('the collection page pages through the server with a cursor, restarts on a stale cursor and offers a retry', async () => {
  const html = (await import('node:fs')).readFileSync(new URL('../../public/curiosity.html', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'https://getinformdaily.com/curiosity.html' });
  const { window } = dom;
  for (const key of ['document', 'Option', 'Event']) globalThis[key] = window[key];
  try {
    const page = await import(`../../public/curiosity-page.js?paging=${Date.now()}`);
    const cards = Array.from({ length: 30 }, (_, index) => ({ ...rich, id: `card-${index}`, title: `Story ${index}` }));
    const urls = [];
    let staleOnce = true;
    let failing = false;
    await page.startCuriosityPage({
      fetcher: async (url, init) => {
        urls.push(url);
        assert.ok(init?.signal, 'every card request can be cancelled');
        if (url === '/api/curiosity/collections') return { ok: true, status: 200, json: async () => ({ collections: [] }) };
        if (failing) return { ok: false, status: 503, json: async () => ({}) };
        if (url.includes('cursor=') && staleOnce) {
          staleOnce = false;
          return { ok: false, status: 409, json: async () => ({ detail: 'stale' }) };
        }
        return { ok: true, status: 200, json: async () => cardsApi(cards, url) };
      },
      history: { replaceState() {} }, location: window.location,
    });
    const doc = window.document;
    const ids = () => [...doc.querySelectorAll('#curiosity-collection article')].map((node) => node.dataset.curiosityId);
    assert.equal(ids().length, 24, 'the first page only');
    assert.match(doc.getElementById('curiosity-result-status').textContent, /30 stories/);
    assert.match(doc.querySelector('[data-curiosity-show-more]').textContent, /Show 6 more/);
    doc.querySelector('[data-curiosity-show-more]').click();
    await settle();
    // The collection was rebuilt, so the page started again from the first page instead of mixing versions.
    assert.ok(urls.some((url) => url.includes('cursor=24')));
    assert.equal(ids().length, 24);
    doc.querySelector('[data-curiosity-show-more]').click();
    await settle();
    assert.equal(ids().length, 30);
    assert.equal(new Set(ids()).size, 30, 'no card repeats across pages');
    assert.equal(doc.querySelector('[data-curiosity-show-more]'), null);

    failing = true;
    doc.getElementById('curiosity-sort').value = 'newest';
    doc.getElementById('curiosity-sort').dispatchEvent(new window.Event('change'));
    await settle();
    const retry = [...doc.querySelectorAll('#curiosity-collection button')].find((button) => button.textContent === 'Try again');
    assert.ok(retry, 'a failed load offers a retry');
    failing = false;
    retry.click();
    await settle();
    assert.equal(ids().length, 24);
    assert.match(urls.at(-1), /sort=newest/);
  } finally {
    for (const key of ['document', 'Option', 'Event']) delete globalThis[key];
    window.close();
  }
});

test('usage counts are sent only with analytics consent and no privacy signal, batched and anonymous', async () => {
  const events = await import(`../../public/curiosity-events.js?consent=${Date.now()}`);
  const granted = { getItem: (key) => (key === 'informa-analytics-consent' ? 'granted' : null) };
  assert.equal(events.trackingAllowed({}, granted), true);
  assert.equal(events.trackingAllowed({ globalPrivacyControl: true }, granted), false, 'Global Privacy Control wins');
  assert.equal(events.trackingAllowed({ doNotTrack: '1' }, granted), false, 'Do Not Track wins');
  assert.equal(events.trackingAllowed({}, { getItem: () => null }), false, 'off by default');
  assert.equal(events.trackingAllowed({}, { getItem: () => { throw new Error('blocked'); } }), false);

  const store = new Map([['informa-analytics-consent', 'granted']]);
  globalThis.localStorage = { getItem: (key) => store.get(key) ?? null };
  try {
    const document = new JSDOM('<section id="cards"></section>').window.document;
    const container = document.querySelector('#cards');
    renderCuriosityCards(container, [{ ...rich, id: 'card-a', related: [{ id: 'card-b', title: 'Next', company: 'X', url: 'https://example.com/b' }] }],
      { actions: false, onShare: () => {} });
    events.bindCardTracking(container, 'collection');
    events.bindCardTracking(container, 'collection');  // Binding twice must not double count.
    container.querySelector('.curiosity-link').dispatchEvent(new document.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
    container.querySelector('.curiosity-related-link').dispatchEvent(new document.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
    container.querySelector('[data-curiosity-share]').click();
    assert.deepEqual(events.pendingEvents(), [
      { type: 'open_source', surface: 'collection', card_id: 'card-a' },
      { type: 'read_next', surface: 'collection', card_id: 'card-b' },
      { type: 'share', surface: 'collection', card_id: 'card-a' },
    ]);
    const beacons = [];
    events.flushEvents({ sendBeacon: (url, blob) => { beacons.push([url, blob]); return true; } });
    assert.equal(beacons.length, 1);
    assert.equal(beacons[0][0], '/api/curiosity/events');
    assert.deepEqual(JSON.parse(await beacons[0][1].text()).events.map((event) => event.type), ['open_source', 'read_next', 'share']);
    assert.deepEqual(events.pendingEvents(), []);
    store.delete('informa-analytics-consent');
    assert.equal(events.track('card_view', { cardId: 'card-a', surface: 'card_page' }), false);
  } finally {
    delete globalThis.localStorage;
  }
});

test('share uses the system sheet, falls back to copying, and points at the card page', async () => {
  const share = await import('../../public/curiosity-share.js');
  assert.equal(share.cardPageUrl('dream11 ipl', 'https://getinformdaily.com'), 'https://getinformdaily.com/cards/dream11%20ipl');
  const shared = [];
  assert.equal((await share.shareCard({ id: 'a', title: 'A' }, { nav: { share: async (data) => shared.push(data) }, origin: 'https://x.test' })).outcome, 'shared');
  assert.deepEqual(shared, [{ title: 'A', url: 'https://x.test/cards/a' }]);
  const copied = [];
  const fallback = await share.shareCard({ id: 'a' }, { nav: { clipboard: { writeText: async (text) => copied.push(text) } }, origin: 'https://x.test' });
  assert.equal(fallback.outcome, 'copied');
  assert.deepEqual(copied, ['https://x.test/cards/a']);
  const cancelled = await share.shareCard({ id: 'a' }, { nav: { share: async () => { const e = new Error('x'); e.name = 'AbortError'; throw e; } }, origin: '' });
  assert.equal(cancelled.outcome, 'cancelled');
  assert.match(share.shareMessage({ outcome: 'manual', url: 'u' }), /Copy this link/);
});


test('reading lists load as a light index and fetch a list\'s cards only when it is opened', async () => {
  const html = (await import('node:fs')).readFileSync(new URL('../../public/curiosity.html', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'https://getinformdaily.com/curiosity.html?list=anatomy' });
  const { window } = dom;
  for (const key of ['document', 'Option', 'Event']) globalThis[key] = window[key];
  try {
    const page = await import(`../../public/curiosity-page.js?lazy=${Date.now()}`);
    const second = { ...rich, id: 'second', title: 'Second in the list', company: 'Meta' };
    const index = { collections: [
      { id: 'anatomy', title: 'Anatomy of a global outage', summary: 'How outages unfold.', read_minutes: 30, companies: ['Meta'], card_count: 2 },
      { id: 'retries', title: 'Retries and overload', summary: 'Load feeds on itself.', read_minutes: 20, companies: ['AWS'], card_count: 1 },
    ], lessons: [] };
    const urls = [];
    let failRetries = true;
    await page.startCuriosityPage({
      fetcher: async (url) => {
        urls.push(url);
        if (url === '/api/curiosity/collections') return { ok: true, status: 200, json: async () => index };
        if (url === '/api/curiosity/collections/anatomy') return { ok: true, status: 200, json: async () => ({ list: { ...index.collections[0], cards: [second, rich] } }) };
        if (url === '/api/curiosity/collections/retries') {
          if (failRetries) return { ok: false, status: 503, json: async () => ({}) };
          return { ok: true, status: 200, json: async () => ({ list: { ...index.collections[1], cards: [rich] } }) };
        }
        return { ok: true, status: 200, json: async () => cardsApi([rich], url) };
      },
      history: { replaceState() {} }, location: window.location,
    });
    const doc = window.document;
    const ids = () => [...doc.querySelectorAll('#curiosity-collection article')].map((node) => node.dataset.curiosityId);
    assert.match(doc.querySelector('#curiosity-list-grid article').textContent, /2 stories · 30 min · Meta/, 'counts come from the index');
    assert.deepEqual(ids(), ['second', 'riot-valorant-netcode'], 'a shared ?list= link opens with its cards');
    assert.equal(urls.filter((url) => url === '/api/curiosity/collections/anatomy').length, 1);

    doc.getElementById('curiosity-list-clear').click();
    doc.querySelector('[data-list="retries"] button').click();
    await settle();
    const retry = [...doc.querySelectorAll('#curiosity-collection button')].find((button) => button.textContent === 'Try again');
    assert.ok(retry, 'a list that fails to load offers a retry');
    failRetries = false;
    retry.click();
    await settle();
    assert.deepEqual(ids(), ['riot-valorant-netcode']);
    assert.match(doc.getElementById('curiosity-result-status').textContent, /1 stories in reading order|1 story/);

    doc.getElementById('curiosity-list-clear').click();
    doc.querySelector('[data-list="anatomy"] button').click();
    await settle();
    assert.equal(urls.filter((url) => url === '/api/curiosity/collections/anatomy').length, 1, 'opened lists are not fetched again');
  } finally {
    for (const key of ['document', 'Option', 'Event']) delete globalThis[key];
    window.close();
  }
});

test('a shared reading-list link opens before the rest of the collection has loaded', async () => {
  const html = (await import('node:fs')).readFileSync(new URL('../../public/curiosity.html', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'https://getinformdaily.com/curiosity.html?list=anatomy' });
  const { window } = dom;
  for (const key of ['document', 'Option', 'Event']) globalThis[key] = window[key];
  let releaseCards;
  try {
    const page = await import(`../../public/curiosity-page.js?early=${Date.now()}`);
    const index = { collections: [{ id: 'anatomy', title: 'Anatomy', summary: 'x', read_minutes: 5, companies: [], card_count: 1 }], lessons: [] };
    const cardsPending = new Promise((resolve) => { releaseCards = resolve; });
    const started = page.startCuriosityPage({
      fetcher: async (url) => {
        if (url === '/api/curiosity/collections') return { ok: true, status: 200, json: async () => index };
        if (url === '/api/curiosity/collections/anatomy') return { ok: true, status: 200, json: async () => ({ list: { ...index.collections[0], cards: [rich] } }) };
        if (url.startsWith('/api/curiosity/cards')) { await cardsPending; return { ok: true, status: 200, json: async () => cardsApi([rich], url) }; }
        return { ok: true, status: 200, json: async () => ({ cards: [] }) };
      },
      history: { replaceState() {} }, location: window.location,
    });
    await settle();
    assert.deepEqual([...window.document.querySelectorAll('#curiosity-collection article')].map((node) => node.dataset.curiosityId),
      ['riot-valorant-netcode'], 'the list shows while the collection is still loading');
    releaseCards();
    await started;
    assert.equal(window.document.getElementById('curiosity-list-name').textContent, 'Anatomy');
  } finally {
    releaseCards?.();
    for (const key of ['document', 'Option', 'Event']) delete globalThis[key];
    window.close();
  }
});
