export function availabilityMessage(state) {
  return ({
    empty: 'No completed snapshot yet. Start a sync or import local files.',
    seeded_pending: 'Local files imported. The network share will be ready after the first sync completes.',
    first_sync: 'First sync in progress. Files appear in the share after verification completes.',
    ready: 'The completed snapshot is ready for OSCAR.',
    ready_syncing: 'The previous completed snapshot is ready for OSCAR while sync continues.',
    interrupted_pending: 'Sync was interrupted. Resume to complete verification and publish your files.'
  })[state.availability] || 'Checking snapshot availability.';
}
export function formatTimestamp(value, timezone) {
  if (!value) return 'Not available';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return 'Not available';
  return new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short',timeZone:timezone || 'Australia/Melbourne'}).format(date);
}

export function formatElapsed(seconds) {
  if (!Number.isFinite(seconds)) return 'Not available';
  let remaining = Math.max(0, Math.floor(seconds));
  const parts = [];
  const units = [[86400,'day'],[3600,'hour'],[60,'minute'],[1,'second']];
  const first = Math.max(0, units.findIndex(([size]) => remaining >= size));
  for (const [size, label] of units.slice(first, first + 2)) {
    const count = Math.floor(remaining / size);
    remaining %= size;
    if (count) parts.push(`${count} ${label}${count === 1 ? '' : 's'}`);
    if (parts.length === 2) break;
  }
  return parts.join(' ') || '0 seconds';
}

export function formatUpdated(timestamp, now = Date.now()) {
  if (!timestamp) return '';
  const seconds = (now - Date.parse(timestamp)) / 1000;
  if (!Number.isFinite(seconds)) return '';
  return seconds < 5 ? 'Updated just now' : `Updated ${formatElapsed(seconds)} ago`;
}
