import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DownloadETA, formatDuration } from '../static/eta.mjs';
const frame = (done, extra = {}) => ({run_id:'run',phase:'downloading',files_done:done,files_total:100, ...extra});
test('waits for enough observed download activity', () => {
  const eta = new DownloadETA();
  assert.equal(eta.observe(frame(10), 0), null);
  assert.equal(eta.observe(frame(15), 10), null);
  assert.equal(eta.observe(frame(16), 30), 420);
});
test('resets when run, phase or total changes', () => {
  const eta = new DownloadETA();
  eta.observe(frame(10), 0);
  assert.equal(eta.observe(frame(20), 60), 480);
  assert.equal(eta.observe(frame(21, {run_id:'next'}), 65), null);
  assert.equal(eta.observe(frame(30, {phase:'verifying'}), 80), null);
});
test('includes waiting time and resets on backward counts', () => {
  const eta = new DownloadETA();
  eta.observe(frame(10), 0);
  assert.equal(eta.observe(frame(20), 60), 480);
  assert.equal(eta.observe(frame(20), 120), 960);
  assert.equal(eta.observe(frame(5), 130), null);
});
test('uses a bounded recent window and does not estimate other phases', () => {
  const eta = new DownloadETA();
  eta.observe(frame(0), 0);
  eta.observe(frame(10), 200);
  eta.observe(frame(20), 350);
  assert.equal(eta.observe(frame(30), 500), 1050);
  assert.equal(eta.observe(frame(100, {phase:'completed'}), 510), null);
});
test('formats hours and rounds rather than promises exact seconds', () => {
  assert.equal(formatDuration(7100), '2 h');
  assert.equal(formatDuration(1800), '30 min');
  assert.equal(formatDuration(20), 'less than a minute');
});
