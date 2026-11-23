import assert from 'node:assert/strict';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { cardTitle, catchupCard, changeLabel } from '../../public/catchup-cards.js';

function helpers(document, opened = []) {
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  return {
    node, opened,
    externalLink: (url, label) => Object.assign(node('a', '', label), { href: url, target: '_blank', rel: 'noopener noreferrer' }),
    openDossier: (story) => opened.push(story.id),
    developmentLink: (id) => `/development.html#${id}`,
    appendClaimEvidence: (target, claim) => target.append(node('blockquote', '', claim.evidence || '')),
    topicLabel: (id) => ({ security: 'Cybersecurity & Privacy', software: 'Software & Cloud' })[id] || '',
    relativeTime: () => '42 minutes ago',
    readableTime: () => 'Nov 23, 3:39 PM',
  };
}

test('release entries titled with a bare version name their project', () => {
  assert.equal(cardTitle({ title: 'v3.277.0' }, { publisher: 'pulumi/pulumi Releases' }), 'pulumi/pulumi v3.277.0');
  assert.equal(cardTitle({ title: 'Apollo and Microsoft partner' }, { publisher: 'YourStory' }), 'Apollo and Microsoft partner');
  assert.equal(changeLabel({ change: 'updated' }), 'Updated');
  assert.equal(changeLabel({}), 'New');
});

test('a catch-up card shows the change, topic, time, summary, publisher and actions', () => {
  const { window } = new JSDOM('<body></body>');
  const opened = [];
  const card = catchupCard({ id: 'evt-1', change: 'new', topic: 'software', title: 'v3.277.0', source_count: 1,
    updated_at: '2026-11-23T10:09:00Z',
    articles: [{ id: 'a1', publisher: 'pulumi/pulumi Releases', url: 'https://github.com/pulumi/pulumi/releases/tag/v3.277.0',
      cleanSummary: 'Adds a preview delivery register command.' }] }, helpers(window.document, opened));
  assert.equal(card.dataset.change, 'new');
  assert.equal(card.querySelector('.catchup-badge').textContent, 'New');
  assert.equal(card.querySelector('.catchup-topic').textContent, 'Software & Cloud');
  assert.equal(card.querySelector('time').dateTime, '2026-11-23T10:09:00Z');
  assert.equal(card.querySelector('time').title, 'Nov 23, 3:39 PM');
  assert.equal(card.querySelector('.catchup-title button').textContent, 'pulumi/pulumi v3.277.0');
  assert.equal(card.querySelector('.catchup-summary').textContent, 'Adds a preview delivery register command.');
  assert.equal(card.querySelector('.catchup-avatar').textContent, 'P');
  assert.equal(card.querySelector('.catchup-source-names span').textContent, '1 publisher');
  const read = card.querySelector('.catchup-read');
  assert.equal(read.href, 'https://github.com/pulumi/pulumi/releases/tag/v3.277.0');
  assert.match(read.getAttribute('aria-label'), /at pulumi\/pulumi Releases$/);
  assert.equal(card.querySelector('.catchup-timeline').getAttribute('href'), '/development.html#evt-1');
  card.querySelector('.catchup-title button').click();
  assert.deepEqual(opened, ['a1']);
});

test('updated developments list what changed with each source, and explanations stay folded', () => {
  const { window } = new JSDOM('<body></body>');
  const card = catchupCard({ id: 'evt-2', change: 'updated', topic: 'security', title: 'VPN appliance patched', source_count: 4,
    articles: [{ id: 'a2', publisher: 'BleepingComputer', url: 'https://bleepingcomputer.com/x', cleanSummary: 'Old summary' }],
    change_sources: [1, 2, 3, 4].map((n) => ({ change_label: `Detail ${n}`, excerpt: `Excerpt ${n}`, publisher: `Pub ${n}`, url: `https://pub${n}.example/x` })),
    explanation: { claims: [{ kind: 'analysis', text: 'Exploitation is spreading.', evidence: 'quote' }], limitations: 'Excerpts only.' } },
  helpers(window.document));
  assert.equal(card.querySelector('.catchup-badge').textContent, 'Updated');
  assert.equal(card.querySelectorAll('.catchup-changes li').length, 3, 'at most three changes per card');
  assert.equal(card.querySelector('.catchup-change-source').textContent, 'Pub 1 ↗');
  assert.equal(card.querySelector(':scope > .catchup-summary'), null, 'changes replace the stale summary');
  const details = card.querySelector('details.catchup-explanation');
  assert.equal(details.open, false);
  assert.match(details.textContent, /Interpretation · Exploitation is spreading\./);
  assert.equal(card.querySelector('.catchup-source-names span').textContent, '4 publishers');
});

test('events without a story render nothing', () => {
  const { window } = new JSDOM('<body></body>');
  assert.equal(catchupCard({ id: 'x', articles: [] }, helpers(window.document)), null);
});
