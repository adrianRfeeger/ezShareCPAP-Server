"""Linux headless service: scheduled downloads and completed card snapshots."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
STOP = threading.Event()
CHILD = None
ACTIVE_APP = None


def load_config(path):
    try:
        cfg = json.loads(Path(path).read_text())
        if not isinstance(cfg, dict):
            raise ValueError('Configuration must be an object')
        from urllib.parse import urlparse
        url = urlparse(cfg['url'])
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            raise ValueError('url must be HTTP(S) without embedded credentials')
        cfg.setdefault('root', '/data')
        if not Path(cfg['root']).is_absolute():
            raise ValueError('root must be absolute')
        cfg.setdefault('time', '10:00')
        if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', cfg['time']):
            raise ValueError('time must be HH:MM')
        cfg.setdefault('timezone', 'Australia/Melbourne')
        ZoneInfo(cfg['timezone'])
        for name, default, low, high in [('timeout', 1800, 1, 86400),
                                        ('attempts', 3, 1, 10), ('retry_delay', 60, 0, 3600)]:
            cfg.setdefault(name, default)
            if type(cfg[name]) is not int or not low <= cfg[name] <= high:
                raise ValueError(f'{name} must be an integer from {low} to {high}')
        cfg.setdefault('run_on_startup', True)
        if type(cfg['run_on_startup']) is not bool:
            raise ValueError('run_on_startup must be boolean')
        return cfg
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'Invalid server configuration: {exc}') from exc


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}')
    try:
        with tmp.open('w') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def read_state(root):
    path = root / 'state/status.json'
    if not path.exists():
        return {}
    return json.loads(path.read_text())


@contextmanager
def run_lock(state):
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'sync.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def download_archive(work, cfg):
    global CHILD
    CHILD = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                              '--config', cfg['_config_path'], 'download'],
                             start_new_session=True)
    try:
        return CHILD.wait(timeout=cfg['timeout']) == 0 and not STOP.is_set()
    except subprocess.TimeoutExpired:
        log.error('Download exceeded total run timeout')
        return False
    finally:
        if CHILD.poll() is None:
            os.killpg(CHILD.pid, signal.SIGTERM)
            try:
                CHILD.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(CHILD.pid, signal.SIGKILL)
                CHILD.wait()
        CHILD = None


def download_child(cfg):
    global ACTIVE_APP
    from ezshare import ezShare
    app = ezShare()
    ACTIVE_APP = app
    app.network_mode = 'existing'
    app.set_params(str(Path(cfg['root']) / 'work/archive'), cfg['url'], None,
                   False, True, False, False, None, None, [], 3, 5, False)
    app.set_status_callback(lambda message, kind='info': log.log(
        logging.ERROR if kind == 'error' else logging.INFO, '%s', message))
    return 0 if app.run() else 1


def copy_archive(source, destination, deadline):
    def check():
        if STOP.is_set() or time.monotonic() >= deadline:
            raise RuntimeError('Stopped or timed out while building snapshot')
    def copy_file(src, dst):
        check()
        if Path(src).is_symlink():
            raise ValueError('Working archive contains a symlink')
        with open(src, 'rb') as reader, open(dst, 'wb') as writer:
            while True:
                check()
                block = reader.read(1024 * 1024)
                if not block:
                    break
                writer.write(block)
        shutil.copystat(src, dst)
        return dst
    check()
    shutil.copytree(source, destination, copy_function=copy_file,
                    ignore=shutil.ignore_patterns('.ezshare-part-*'))
    check()


def run_once(cfg, download=download_archive, schedule_date=None):
    root = Path(cfg['root'])
    try:
        with run_lock(root / 'state'):
            status = read_state(root)
            if schedule_date and status.get('last_scheduled_date', '') >= schedule_date:
                return 0
            started = time.monotonic()
            status.update(last_attempt=datetime.now(timezone.utc).isoformat(), running=True)
            if schedule_date:
                status['last_scheduled_date'] = schedule_date
            atomic_json(root / 'state/status.json', status)
            work = root / 'work/archive'
            work.mkdir(parents=True, exist_ok=True)
            for leftover in work.rglob('.ezshare-part-*'):
                if leftover.is_file():
                    leftover.unlink()
            staging = None
            try:
                success = False
                deadline = started + cfg['timeout']
                for attempt in range(cfg['attempts']):
                    if STOP.is_set():
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    attempt_cfg = dict(cfg, timeout=remaining)
                    if download(work, attempt_cfg):
                        success = True
                        break
                    if attempt + 1 < cfg['attempts'] and STOP.wait(min(cfg['retry_delay'], max(0, deadline-time.monotonic()))):
                        break
                if not success or STOP.is_set():
                    raise RuntimeError('Download failed, timed out, or was stopped; previous snapshot retained')
                published = root / 'published'
                published.mkdir(parents=True, exist_ok=True)
                for abandoned in published.glob('.staging-*'):
                    if abandoned.is_dir():
                        shutil.rmtree(abandoned)
                name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
                staging = published / ('.staging-' + name)
                # Copies, never hard links: later downloads cannot mutate a published snapshot.
                copy_archive(work, staging, deadline)
                count = 0
                for item in staging.rglob('*'):
                    if STOP.is_set() or time.monotonic() >= deadline:
                        raise RuntimeError('Stopped or timed out before publication')
                    count += int(item.is_file())
                if STOP.is_set():
                    raise RuntimeError('Stopped before publication')
                snapshot = published / name
                staging.rename(snapshot)
                staging = None
                pointer = published / ('.current-' + name)
                pointer.symlink_to(name, target_is_directory=True)
                pointer.replace(published / 'current')
                status.update(last_success=datetime.now(timezone.utc).isoformat(),
                              snapshot=name, files=count, error=None)
                return_code = 0
            except Exception as exc:
                log.exception('Sync failed')
                status['error'] = str(exc)
                return_code = 1
            finally:
                if staging and staging.exists():
                    shutil.rmtree(staging)
                status.update(running=False, duration_seconds=round(time.monotonic()-started, 2))
                status['history'] = (status.get('history', []) + [{
                    'finished': datetime.now(timezone.utc).isoformat(),
                    'result': 'Success' if return_code == 0 else 'Failed',
                    'duration_seconds': status['duration_seconds']}])[-20:]
                atomic_json(root / 'state/status.json', status)
            return return_code
    except BlockingIOError:
        log.warning('A sync is already running')
        return 75


def scheduled_date(now, cfg, last_date):
    local = now.astimezone(ZoneInfo(cfg['timezone']))
    date = local.date().isoformat()
    if last_date and date <= last_date:
        return None
    hour, minute = map(int, cfg['time'].split(':'))
    # Wall-clock comparison runs at the first valid minute after a spring gap.
    if (local.hour, local.minute) >= (hour, minute):
        return date
    return None


def serve(cfg):
    root = Path(cfg['root'])
    atomic_json(root / 'state/heartbeat.json', {'time': time.time()})
    if cfg['run_on_startup']:
        due = scheduled_date(datetime.now(timezone.utc), cfg,
                             read_state(root).get('last_scheduled_date'))
        run_once(cfg, schedule_date=due)
    while not STOP.is_set():
        if cfg.get('_config_path'):
            try:
                fresh = load_config(cfg['_config_path'])
                fresh['_config_path'] = cfg['_config_path']
                cfg = fresh
            except ValueError:
                log.exception('Schedule configuration invalid; retaining previous settings')
        atomic_json(root / 'state/heartbeat.json', {'time': time.time()})
        date = scheduled_date(datetime.now(timezone.utc), cfg,
                              read_state(root).get('last_scheduled_date'))
        if date:
            run_once(cfg, schedule_date=date)
        STOP.wait(15)
    return 0


def stop(signum, frame):
    STOP.set()
    if ACTIVE_APP:
        ACTIVE_APP._is_running = False
    if CHILD and CHILD.poll() is None:
        try:
            os.killpg(CHILD.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/config/server.json')
    parser.add_argument('command', choices=['serve', 'sync', 'download', 'status', 'health'])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        cfg = load_config(args.config)
        cfg['_config_path'] = str(Path(args.config).resolve())
        root = Path(cfg['root'])
        for name in ('SIGTERM', 'SIGINT'):
            signal.signal(getattr(signal, name), stop)
        if args.command == 'download':
            return download_child(cfg)
        if args.command == 'sync':
            return run_once(cfg)
        if args.command == 'serve':
            return serve(cfg)
        if args.command == 'status':
            print(json.dumps(read_state(root), indent=2))
            return 0
        heartbeat = json.loads((root / 'state/heartbeat.json').read_text())
        status = read_state(root)
        # During a download the child is bounded; allow its retry window.
        allowed = cfg['timeout'] + 120
        return 0 if time.time() - heartbeat['time'] < allowed else 1
    except (ValueError, OSError) as exc:
        log.error('%s', exc)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
