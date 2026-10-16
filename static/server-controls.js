import {availabilityMessage} from './status-view.mjs';
const el = id => document.getElementById(id);
const size = value => value == null ? 'calculating' : `${(value / 1024 ** 3).toFixed(2)} GiB`;
window.addEventListener('sync-state', ({detail: state}) => {
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
