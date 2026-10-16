import { DownloadETA, formatDuration } from './eta.mjs';
(() => {
  const el = id => document.getElementById(id);
  const text = (id, value) => { el(id).textContent = value; };
  const seconds = value => Math.max(0, Math.floor(value));
  const bytes = value => value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${Math.round(value / 1024)} KB`;
  const estimate = new DownloadETA();
  let fetching = false;
  let historyKey = '';
  async function refresh() {
    if (fetching || document.hidden) return;
    fetching = true;
    try {
      const response = await fetch('/api/status', {credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(8000)});
      if (!response.ok) throw new Error('Status request failed');
      const state = await response.json();
      const progress = state.progress || {};
      text('run-badge', state.running ? 'Running' : state.error ? 'Needs attention' : state.last_success ? 'Ready' : 'Waiting for first sync');
      text('current-action', progress.action || 'No sync is running.');
      el('sync-progress').hidden = !state.running && progress.phase !== 'completed';
      if (Number.isFinite(progress.percent)) el('sync-progress').value = progress.percent;
      else el('sync-progress').removeAttribute('value');
      let detail = '';
      if (progress.phase === 'downloading' && progress.files_total != null) {
        detail = `${progress.files_done || 0} of ${progress.files_total} files downloaded`;
        if (Number.isFinite(progress.percent)) detail += ` (${progress.percent}%)`;
        if (progress.current_file && progress.file_bytes != null) {
          detail += ` · Current file: ${bytes(progress.file_bytes)}`;
          if (progress.file_size != null) detail += ` of ${bytes(progress.file_size)}`;
        }
      } else if (state.running) {
        detail = progress.directories_scanned != null ? `${progress.directories_scanned} directories checked` : 'Working';
        if (progress.files_found != null) detail += ` · ${progress.files_found} files found`;
        detail += ' · Percentage available during download';
      } else if (progress.phase === 'completed') detail = 'Completed';
      text('progress-detail', detail);
      const eta = estimate.observe(progress);
      const stale = progress.updated_at && Date.now() - Date.parse(progress.updated_at) > 30000;
      let etaText = '';
      const estimateLabel = estimate.preliminary ? 'Early download estimate' : 'Download ETA';
      if (state.running && progress.phase === 'downloading') {
        etaText = stale ? 'Download ETA: waiting for an update' :
          eta == null ? 'Download ETA: calculating from recent downloads' :
          `${estimateLabel}: ${eta < 60 ? '' : 'about '}${formatDuration(eta)} remaining`;
      } else if (state.running) {
        etaText = ['scanning', 'planning', 'starting', 'retrying'].includes(progress.phase) ?
          'Download ETA will appear once files are downloading.' :
          'Finishing checks. Download ETA no longer applies.';
      }
      text('download-eta', etaText);
      if (eta != null && !stale && estimate.filesPerMinute != null) {
        text('progress-detail', `${detail} · Recent pace: about ${estimate.filesPerMinute.toFixed(1)} files/min`);
      }
      const elapsed = state.running && state.last_attempt ? `Elapsed ${seconds((Date.now() - Date.parse(state.last_attempt))/1000)} s` : '';
      const age = progress.updated_at ? `Updated ${seconds((Date.now() - Date.parse(progress.updated_at))/1000)} s ago` : '';
      text('progress-freshness', [elapsed, age].filter(Boolean).join(' · '));
      text('live-connection', '');
      text('last-success', state.last_success || 'No completed downloads yet');
      text('last-attempt', state.last_attempt || 'Not started');
      text('snapshot-files', state.files ?? 'Not available');
      el('sync-button').disabled = !!state.running;
      text('run-error', state.error || '');
      el('run-error').hidden = !state.error;
      text('snapshot-name', state.snapshot || '');
      el('snapshot-row').hidden = !state.snapshot;
      const history = state.history || [];
      const key = JSON.stringify(history);
      if (key !== historyKey) {
        historyKey = key;
        el('history-body').replaceChildren(...[...history].reverse().map(run => {
          const row = document.createElement('tr');
          for (const value of [run.finished, run.result, `${run.duration_seconds} s`]) {
            const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
          }
          return row;
        }));
        el('history-table').hidden = history.length === 0;
        el('empty-history').hidden = history.length !== 0;
      }
    } catch (_) {
      text('live-connection', 'Live status is unavailable. Reconnecting automatically.');
      text('download-eta', 'Download ETA: waiting for a live update');
    } finally { fetching = false; }
  }
  refresh();
  setInterval(refresh, 2000);
  document.addEventListener('visibilitychange', refresh);
})();
