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
