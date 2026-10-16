import test from 'node:test';
import assert from 'node:assert/strict';
import {availabilityMessage, formatTimestamp} from '../static/status-view.mjs';
test('seeded status explains publication', () => assert.equal(availabilityMessage({availability:'seeded_pending'}),'Local files imported. The network share will be ready after the first sync completes.'));
test('completed data stays available after later failure', () => assert.match(availabilityMessage({availability:'ready',error:'failed'}),/ready for OSCAR/));
test('old servers and missing dates are readable', () => {assert.ok(availabilityMessage({}));assert.equal(formatTimestamp(null,'Australia/Melbourne'),'Not available');});
