(() => {
  const form = document.getElementById('seed-form');
  const action = document.getElementById('seed-action');
  const progress = document.getElementById('seed-progress');
  const submit = document.getElementById('seed-submit');
  const download = document.getElementById('download-button');
  let uploading = false;
  let busy = submit.disabled;
  window.addEventListener('sync-state', event => {
    const state = event.detail;
    busy = !!state.busy;
    submit.disabled = uploading || busy;
    download.disabled = !state.snapshot;
    const status = state.import_status || {};
    if (status.running) action.textContent = `${status.action} · ${status.imported || 0} added, ${status.kept || 0} existing files kept`;
    else if (!uploading && status.phase === 'completed') action.textContent = `${status.imported} files added; ${status.kept} existing files kept. Sync to fetch missing or changed files.`;
    else if (!uploading && status.error) action.textContent = status.error;
  });
  form.addEventListener('submit', event => {
    event.preventDefault();
    const file = document.getElementById('seed-archive').files[0];
    if (!file || uploading || busy) return;
    if (file.size > 4 * 1024 ** 3) {
      action.textContent = 'Choose a ZIP smaller than 4 GB.'; return;
    }
    uploading = true; submit.disabled = true;
    progress.hidden = false; progress.value = 0;
    action.textContent = 'Uploading the ZIP to your server…';
    const request = new XMLHttpRequest();
    request.open('POST', '/import');
    request.responseType = 'json';
    request.upload.onprogress = event => {
      if (event.lengthComputable) {
        const percent = Math.round(event.loaded / event.total * 100);
        progress.value = percent;
        action.textContent = percent === 100 ? 'Upload complete. Validating and importing files…' : `Uploading ZIP: ${percent}%`;
      }
    };
    request.onload = () => {
      uploading = false; submit.disabled = busy;
      if (request.status === 200) {
        action.textContent = `${request.response.imported} files added; ${request.response.kept} existing files kept. Sync to fetch missing or changed files.`;
        progress.value = 100;
      } else {
        action.textContent = request.response?.error || 'Import failed. Check the server status before retrying.';
        progress.hidden = true;
      }
    };
    request.onerror = () => {
      uploading = false; submit.disabled = busy;
      action.textContent = 'Connection lost. Check import status before retrying.';
      progress.hidden = true;
    };
    request.send(new FormData(form));
  });
})();
