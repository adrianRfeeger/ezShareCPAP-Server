import test from 'node:test';
import assert from 'node:assert/strict';
import {availabilityMessage, formatTimestamp} from '../static/status-view.mjs';
test('seeded status explains publication', () => assert.equal(availabilityMessage({availability:'seeded_pending'}),'Local files imported. The network share will be ready after the first sync completes.'));
test('completed data stays available after later failure', () => assert.match(availabilityMessage({availability:'ready',error:'failed'}),/ready for OSCAR/));
test('old servers and missing dates are readable', () => {assert.ok(availabilityMessage({}));assert.equal(formatTimestamp(null,'Australia/Melbourne'),'Not available');});

test('durations use readable units and at most two parts', async () => {
  const {formatElapsed} = await import('../static/status-view.mjs');
  for (const [seconds, expected] of [[0,'0 seconds'],[1,'1 second'],[59,'59 seconds'],[60,'1 minute'],[125,'2 minutes 5 seconds'],[3601,'1 hour'],[3661,'1 hour 1 minute'],[86461,'1 day'],[90061,'1 day 1 hour'],[172800,'2 days']]) {
    assert.equal(formatElapsed(seconds),expected);
  }
  assert.equal(formatElapsed(-10),'0 seconds');
  assert.equal(formatElapsed(null),'Not available');
  assert.equal(formatElapsed(NaN),'Not available');
});
test('updated labels handle fresh, old, missing and future timestamps', async () => {
  const {formatUpdated} = await import('../static/status-view.mjs');
  const now=Date.parse('2026-10-18T03:00:00Z');
  assert.equal(formatUpdated('2026-10-18T02:59:59Z',now),'Updated just now');
  assert.equal(formatUpdated('2026-10-16T00:00:00Z',now),'Updated 2 days 3 hours ago');
  assert.equal(formatUpdated('2026-10-18T04:00:00Z',now),'Updated just now');
  assert.equal(formatUpdated('invalid',now),'');
  assert.equal(formatUpdated(null,now),'');
});
