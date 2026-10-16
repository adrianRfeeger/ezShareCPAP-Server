import json
from unittest.mock import patch
from pathlib import Path
import server
from test_server import config


def test_run_publishes_completed_progress(tmp_path):
    assert server.run_once(config(tmp_path), download=lambda *_: True) == 0
    status = server.read_live_state(tmp_path)
    assert status['progress']['phase'] == 'completed'
    assert status['progress']['percent'] == 100
    assert status['progress']['run_id'] == status['last_attempt']


def test_failed_run_cannot_retain_success_percentage(tmp_path):
    assert server.run_once(config(tmp_path), download=lambda *_: False) == 1
    progress = server.read_live_state(tmp_path)['progress']
    assert progress['phase'] == 'failed'
    assert progress['percent'] is None


def test_stale_progress_is_ignored(tmp_path):
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'status.json').write_text(json.dumps({'last_attempt':'new', 'running':True}))
    (state / 'progress.json').write_text(json.dumps({'run_id':'old','percent':100}))
    assert server.read_live_state(tmp_path)['progress']['percent'] is None


def test_engine_reports_scanning_and_download_counts(tmp_path):
    from ezshare import ezShare
    from test_connect_sync import FakeSession
    app = ezShare()
    events = []
    app.activity_callback = events.append
    app.network_mode = 'existing'
    app.set_params(str(tmp_path), 'http://card/dir?dir=A:', None, False, False,
                   False, False, None, None, [], 1, 0, False)
    with patch('ezshare.requests.Session', return_value=FakeSession()):
        assert app.run()
    assert any(e['phase']=='scanning' for e in events)
    assert any(e['phase']=='verifying' for e in events)
    assert any(e.get('files_done')==1 and e.get('files_total')==1 for e in events)


def test_progress_disk_failure_does_not_stop_sync_or_leave_running(tmp_path):
    original = server.atomic_json
    def fail_progress(path, value):
        if path.name == 'progress.json':
            raise OSError('disk full')
        return original(path, value)
    with patch('server.atomic_json', side_effect=fail_progress):
        assert server.run_once(config(tmp_path), download=lambda *_: True) == 0
    assert server.read_state(tmp_path)['running'] is False


def test_unlocked_abandoned_run_is_recoverable(tmp_path):
    state = tmp_path / 'state'
    state.mkdir()
    (state/'sync.lock').touch()
    server.atomic_json(state/'status.json', {'running':True,'last_attempt':'abandoned'})
    server.atomic_json(state/'progress.json', {'run_id':'abandoned','phase':'downloading','percent':50})
    result = server.read_live_state(tmp_path)
    assert result['running'] is False
    assert result['progress']['phase'] == 'interrupted'
    assert result['progress']['percent'] is None
