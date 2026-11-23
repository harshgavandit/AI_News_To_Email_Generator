import assert from 'node:assert/strict';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { layoutStep, nodeAt, seedLayout, themeGraph } from '../../public/curiosity-constellation.js';
import { orbLabel, storyAtReadingLine } from '../../public/signal-orb.js';

const labels = { 'game-engineering': 'Game engineering', ai: 'AI & LLMs', databases: 'Databases & storage', security: 'Security' };

test('constellation counts each theme once per card and links themes that share stories', () => {
  const graph = themeGraph([
    { themes: ['game-engineering', 'ai'] },
    { themes: ['game-engineering', 'ai', 'game-engineering'] },
    { themes: ['databases'] },
    { theme: 'ai' },
    { themes: ['unknown-theme'] },
  ], labels);
  assert.deepEqual(graph.nodes.map((node) => [node.id, node.count]), [['game-engineering', 2], ['ai', 3], ['databases', 1]]);
  assert.deepEqual(graph.links, [{ a: 'ai', b: 'game-engineering', weight: 2 }]);
});

test('the spring layout settles inside the frame, keeps stars apart and finds them under the pointer', () => {
  const graph = seedLayout(themeGraph([
    { themes: ['game-engineering', 'ai'] }, { themes: ['ai', 'databases'] }, { themes: ['security'] }, { themes: ['ai'] },
  ], labels), 400, 300);
  for (let i = 0; i < 400; i += 1) layoutStep(graph, 400, 300);
  for (const node of graph.nodes) {
    assert.ok(node.x >= node.r && node.x <= 400 - node.r, node.id);
    assert.ok(node.y >= node.r && node.y <= 300 - node.r, node.id);
  }
  for (let i = 0; i < graph.nodes.length; i += 1) {
    for (let j = i + 1; j < graph.nodes.length; j += 1) {
      const a = graph.nodes[i], b = graph.nodes[j];
      assert.ok(Math.hypot(a.x - b.x, a.y - b.y) > 30, `${a.id} and ${b.id} overlap`);
    }
  }
  const ai = graph.nodes.find((node) => node.id === 'ai');
  assert.equal(nodeAt(graph, ai.x + 2, ai.y - 2).id, 'ai');
  assert.equal(nodeAt(graph, -50, -50), null);
  const before = { x: ai.x, y: ai.y };
  for (let i = 0; i < 10; i += 1) layoutStep(graph, 400, 300, { x: ai.x + 20, y: ai.y });
  assert.ok(ai.x < before.x, 'the pointer pushes a star away');
});

test('the Signal Orb follows the story at the reading line and names its region and publisher', () => {
  const { document } = new JSDOM('<div id="s"></div>').window;
  const story = (region, top, height, publisher) => {
    const node = document.createElement('article');
    node.className = 'story';
    if (region) node.dataset.region = region;
    if (publisher) node.dataset.publisher = publisher;
    node.getBoundingClientRect = () => ({ top, bottom: top + height });
    return node;
  };
  const stories = [story('NA', -400, 300), story('EU', 120, 260, 'Heise'), story('APAC', 400, 260), story(null, 300, 50), story('Nowhere', 330, 40)];
  assert.equal(storyAtReadingLine(stories, 800).dataset.region, 'EU');
  assert.equal(storyAtReadingLine(stories, 1200).dataset.region, 'APAC');
  assert.equal(storyAtReadingLine([story('EU', 900, 100)], 800), null);
  assert.equal(orbLabel('EU', 'Heise'), 'Europe · Heise');
  assert.equal(orbLabel('APAC'), 'Asia-Pacific');
  assert.equal(orbLabel('Nowhere', 'X'), '');
});
