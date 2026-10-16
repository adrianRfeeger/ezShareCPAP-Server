import {availabilityMessage,formatTimestamp} from './status-view.mjs';
const el = id => document.getElementById(id);
const size = value => value == null ? 'calculating' : `${(value / 1024 ** 3).toFixed(2)} GiB`;
window.addEventListener('sync-state', ({detail: state}) => {
  const diagnostic = state.diagnostics || {};
  const wifi = diagnostic.wifi || {};
  const card = diagnostic.card || {};
  const transfer = state.progress?.transfer || {};
  const inactive = !transfer.last_activity_at || Date.now() - Date.parse(transfer.last_activity_at) > 60000;
  el('card-status').textContent = card.checked_at ? `Last card check: ${card.reachable ? 'reachable' : (card.error || 'unreachable')} at ${formatTimestamp(card.checked_at,state.schedule?.timezone)}` : 'Card status: no manual check yet';
  el('wifi-status').textContent = !wifi.available ? 'Wi-Fi details unavailable' : wifi.error || (wifi.stale ? `Wi-Fi sample is stale (${wifi.age_seconds}s old).` : `Wi-Fi: ${wifi.connected ? 'connected' : 'disconnected'}, signal ${wifi.signal_dbm ?? 'unknown'} dBm. Link rates: receive ${wifi.rx_mbps ?? 'unknown'}, transmit ${wifi.tx_mbps ?? 'unknown'} Mbit/s. Updated ${wifi.age_seconds}s ago.`);
  el('transfer-status').textContent = state.running && state.progress?.phase === 'downloading' ? (inactive ? 'No recent transfer activity.' : transfer.bytes_per_second == null ? 'Calculating recent transfer speed…' : `Recent SD-card transfer: ${(transfer.bytes_per_second / 1024).toFixed(1)} KiB/s.`) : '';
  el('card-check').disabled = !!state.busy;
  const schedule = state.schedule || {};
  el('next-run').textContent = schedule.paused ? 'Schedule paused' : schedule.overdue ? 'Next run is due; waiting for the current operation or scheduler.' : `Next run: ${formatTimestamp(schedule.next_run_at,schedule.timezone)} (${schedule.timezone || 'local time'})`;
  el('schedule-warnings').textContent = (schedule.warnings || []).join(' ');
  el('history-zone').textContent = schedule.timezone || 'local time';
  el('stop-run-id').value = state.last_attempt || '';
  el('stop-button').disabled = !state.running || state.run_state === 'stop_requested';
  el('resume-button').disabled = !state.resume_available;
  el('pause-status').textContent = state.run_state === 'stop_requested' ? 'Stopping after the current file…' : state.paused ? 'Scheduled runs are paused. Select Resume to continue.' : '';
  el('availability-message').textContent = availabilityMessage(state);
  const archive = state.archive || {};
  const inv = state.progress?.inventory || {};
  el('archive-counts').textContent = `Last import: ${archive.last_import_added ?? 'unknown'} files added, ${archive.last_import_kept ?? 'unknown'} existing files kept. This attempt: ${inv.downloaded ?? 'calculating'} downloaded, ${inv.remaining ?? 'calculating'} remaining. Working archive: ${archive.working_files ?? 'calculating'} files.`;
  const storage = state.storage || {};
  el('storage-summary').textContent = `${size(storage.free_bytes)} free of ${size(storage.total_bytes)}. Working files: ${size(storage.work_bytes)}. Snapshots: ${size(storage.snapshot_bytes)}.`;
  el('storage-warning').textContent = state.storage_warning || storage.warning || '';
  el('cleanup-button').disabled = !!state.busy || !state.snapshot;
});
el('retention-preview').addEventListener('click', async () => {
  try {
    const response = await fetch(`/api/storage/preview?keep=${encodeURIComponent(el('retention-keep').value)}`);
    const data = await response.json();
    el('retention-result').textContent = data.error || (data.delete.length ? `Will remove ${data.delete.join(', ')}; reclaim ${size(data.reclaimable_bytes)}.` : 'No snapshots will be removed.');
  } catch { el('retention-result').textContent = 'Could not load cleanup preview.'; }
});
el('cleanup-button').form.addEventListener('submit', event => {
  if (!confirm('Remove older snapshots using the saved retention count? Preview cleanup first.')) event.preventDefault();
});

el('schedule-preview').addEventListener('click', async () => {
  const form = el('schedule-preview').form;
  const params = new URLSearchParams({time:form.elements.time.value,timezone:form.elements.timezone.value});
  try {
    const data = await (await fetch(`/api/schedule/preview?${params}`)).json();
    el('schedule-preview-result').textContent = data.error || `Unsaved preview: ${data.paused ? 'schedule is paused' : formatTimestamp(data.next_run_at,data.timezone)}. Save settings to apply.`;
  } catch { el('schedule-preview-result').textContent = 'Could not preview schedule.'; }
});
