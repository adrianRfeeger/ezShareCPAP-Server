// Estimates download time only; card checks and snapshot publication follow.
export class DownloadETA {
  constructor() { this.samples = []; this.key = null; }
  observe(progress, now = performance.now() / 1000) {
    const {run_id, phase, files_done: done, files_total: total} = progress;
    const key = JSON.stringify([run_id, phase, total]);
    if (key !== this.key || (this.samples.length && done < this.samples.at(-1).done)) {
      this.samples = []; this.key = key;
    }
    if (phase !== 'downloading' || !Number.isFinite(done) || !Number.isFinite(total) || done < 0 || done >= total) {
      this.samples = []; return null;
    }
    if (this.samples.length && now <= this.samples.at(-1).time) return null;
    this.samples.push({done, time: now});
    while (this.samples.length > 2 && this.samples[1].time <= now - 300) this.samples.shift();
    const start = this.samples[0];
    const elapsed = now - start.time;
    const finished = done - start.done;
    if (elapsed < 30 || finished < 5) return null;
    return Math.ceil((total - done) * elapsed / finished);
  }
}
export function formatDuration(seconds) {
  if (seconds < 60) return 'less than a minute';
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = Math.round((minutes % 60) / 5) * 5;
  if (remainder === 60) return `${hours + 1} h`;
  return `${hours} h${remainder ? ` ${remainder} min` : ''}`;
}
