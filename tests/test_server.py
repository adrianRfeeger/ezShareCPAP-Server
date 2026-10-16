import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
import server


def config(tmp_path):
    return {'url': 'http://card/dir?dir=A:', 'root': str(tmp_path),
            'time': '10:00', 'timezone': 'Australia/Melbourne',
            'timeout': 60, 'attempts': 1, 'retry_delay': 0, 'run_on_startup': True}


def test_invalid_config_does_not_get_replaced(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text('{bad')
    with pytest.raises(ValueError):
        server.load_config(path)
    assert path.read_text() == '{bad'


def test_failed_run_preserves_published_data(tmp_path):
    cfg = config(tmp_path)
    def download(work, cfg):
        (work / 'STR.EDF').write_bytes(b'good')
        return True
    assert server.run_once(cfg, download=download) == 0
    old = (tmp_path / 'published/current').resolve()
    def fail(work, cfg):
        (work / 'STR.EDF').write_bytes(b'bad')
        return False
    assert server.run_once(cfg, download=fail) == 1
    assert (tmp_path / 'published/current').resolve() == old
    assert (old / 'STR.EDF').read_bytes() == b'good'
    assert json.loads((tmp_path / 'state/status.json').read_text())['last_success']


def test_overlap_cannot_download(tmp_path):
    cfg = config(tmp_path)
    with server.run_lock(tmp_path / 'state'):
        assert server.run_once(cfg, download=lambda *_: pytest.fail('overlap')) == 75


def test_snapshot_is_independent_of_working_archive(tmp_path):
    cfg = config(tmp_path)
    def download(work, cfg):
        (work / 'file').write_bytes(b'first')
        return True
    assert server.run_once(cfg, download=download) == 0
    (tmp_path / 'work/archive/file').write_bytes(b'changed')
    assert (tmp_path / 'published/current/file').read_bytes() == b'first'


def test_dst_gap_and_repeat():
    cfg = {'time': '02:30', 'timezone': 'Australia/Melbourne'}
    # 02:30 does not exist at spring transition; run at 03:00.
    assert server.scheduled_date(datetime(2026,10,3,16,0,tzinfo=timezone.utc), cfg, None) == '2026-10-04'
    # Both occurrences of 02:30 share one persisted scheduled date.
    assert server.scheduled_date(datetime(2026,4,4,16,30,tzinfo=timezone.utc), cfg, '2026-04-05') is None


def test_catch_up_once_not_every_missed_day():
    cfg = {'time': '10:00', 'timezone': 'Australia/Melbourne'}
    now = datetime(2026,10,16,2,0,tzinfo=timezone.utc)
    assert server.scheduled_date(now, cfg, '2026-10-01') == '2026-10-16'
    assert server.scheduled_date(now, cfg, '2026-10-16') is None


def test_copy_respects_deadline_and_does_not_publish(tmp_path):
    cfg = config(tmp_path)
    original = server.copy_archive
    def expired_copy(source, destination, deadline):
        return original(source, destination, 0)
    def download(work, cfg):
        (work / 'file').write_bytes(b'card-data')
        return True
    from unittest.mock import patch
    with patch('server.copy_archive', side_effect=expired_copy):
        assert server.run_once(cfg, download=download) == 1
    assert not (tmp_path / 'published/current').exists()
    assert not list((tmp_path / 'published').glob('.staging-*'))


def test_abandoned_partial_files_are_not_published(tmp_path):
    cfg = config(tmp_path)
    archive = tmp_path / 'work/archive'
    archive.mkdir(parents=True)
    (archive / '.ezshare-part-abandoned').write_bytes(b'partial')
    def download(work, cfg):
        (work / 'file').write_bytes(b'complete')
        return True
    assert server.run_once(cfg, download=download) == 0
    assert [p.name for p in (tmp_path / 'published/current').iterdir()] == ['file']
