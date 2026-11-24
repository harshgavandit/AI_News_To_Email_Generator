import assert from 'node:assert/strict';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { coverageSummaryNode, firstReportedText, leadText, regionsText } from '../../public/coverage-summary.js';

const summary = { publishers: 4, first_reported_by: 'TechCrunch', lead_minutes: 40,
  regions: [{ id: 'Global', label: 'Global publishers', count: 2 }, { id: 'EU', label: 'Europe', count: 1 }, { id: 'Africa', label: 'Africa', count: 1 }] };

test('coverage lines read naturally', () => {
  assert.equal(leadText(40), '40 min before the next publisher');
  assert.equal(leadText(150), '3 h before the next publisher');
  assert.equal(leadText(4000), '3 days before the next publisher');
  assert.equal(leadText(0), '');
  assert.equal(firstReportedText(summary), 'First reported by TechCrunch, 40 min before the next publisher');
  assert.equal(firstReportedText({ ...summary, lead_minutes: null }), 'First reported by TechCrunch');
  assert.equal(regionsText(summary), 'Global 2 · Europe 1 · Africa 1');
});

test('the summary node renders text only and skips single-publisher stories', () => {
  const { window } = new JSDOM('');
  const node = coverageSummaryNode({ ...summary, first_reported_by: '<b>X</b>' }, window.document);
  assert.equal(node.querySelector('b'), null);
  assert.match(node.textContent, /First reported by <b>X<\/b>.* · 4 publishers · By region: Global 2/);
  assert.equal(coverageSummaryNode({ publishers: 1 }, window.document), null);
  assert.equal(coverageSummaryNode(null, window.document), null);
});
