import io,json,stat,zipfile
from datetime import datetime,timezone
from pathlib import Path
import pytest
import archive_io
import server


def seed(path, entries=None):
    entries=entries or {'Identification.tgt':b'device-one','DATALOG/night.edf':b'local-data'}
    with zipfile.ZipFile(path,'w') as archive:
        for name,data in entries.items():
            info=zipfile.ZipInfo(name,date_time=(2024,6,1,10,0,0))
            archive.writestr(info,data)
    return path


def test_import_preserves_server_files_and_normalizes_zip_wall_time(tmp_path):
    work=tmp_path/'work/archive'
    (work/'DATALOG').mkdir(parents=True)
    (work/'Identification.tgt').write_bytes(b'device-one')
    (work/'DATALOG/NIGHT.EDF').write_bytes(b'server-data')
    zip_path=seed(tmp_path/'seed.zip',{'SD_card/Identification.tgt':b'device-one',
            'SD_card/DATALOG/night.edf':b'old-local-data','SD_card/DATALOG/new.edf':b'new'})
    result=archive_io.import_seed_zip(zip_path,tmp_path)
    assert result['imported']==1
    assert (work/'DATALOG/NIGHT.EDF').read_bytes()==b'server-data'
    assert (work/'DATALOG/new.edf').stat().st_mtime==datetime(2024,6,1,10,tzinfo=timezone.utc).timestamp()


@pytest.mark.parametrize('unsafe',['../escape','/absolute','DATALOG/../../escape','DATALOG\\..\\..\\escape'])
def test_bad_path_rejects_entire_import(tmp_path,unsafe):
    path=seed(tmp_path/'seed.zip',{'Identification.tgt':b'device-one','DATALOG/good.edf':b'good',unsafe:b'bad'})
    with pytest.raises(ValueError): archive_io.import_seed_zip(path,tmp_path)
    assert not (tmp_path/'work/archive/DATALOG/good.edf').exists()


def test_different_device_is_rejected_without_mutation(tmp_path):
    work=tmp_path/'work/archive';work.mkdir(parents=True)
    (work/'Identification.tgt').write_bytes(b'other-device')
    with pytest.raises(ValueError,match='device'):
        archive_io.import_seed_zip(seed(tmp_path/'seed.zip'),tmp_path)
    assert not (work/'DATALOG').exists()


def test_symlink_and_duplicate_case_paths_rejected(tmp_path):
    path=tmp_path/'seed.zip'
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('Identification.tgt',b'device-one')
        info=zipfile.ZipInfo('link');info.external_attr=(stat.S_IFLNK|0o777)<<16
        archive.writestr(info,'/etc/passwd')
    with pytest.raises(ValueError): archive_io.import_seed_zip(path,tmp_path)
    path=seed(path,{'Identification.tgt':b'device-one','DATALOG/a.edf':b'one','DATALOG/A.EDF':b'two'})
    with pytest.raises(ValueError): archive_io.import_seed_zip(path,tmp_path)


def test_import_uses_shared_sync_lock(tmp_path):
    with server.run_lock(tmp_path/'state'):
        with pytest.raises(BlockingIOError):
            archive_io.import_seed_zip(seed(tmp_path/'seed.zip'),tmp_path)


def test_download_exports_only_completed_snapshot(tmp_path):
    published=tmp_path/'published'; snapshot=published/'completed';snapshot.mkdir(parents=True)
    (snapshot/'Identification.tgt').write_bytes(b'device-one')
    (published/'current').symlink_to('completed')
    archive=archive_io.build_snapshot_zip(tmp_path)
    with zipfile.ZipFile(archive) as content:
        assert content.namelist()==['Identification.tgt']
        assert content.read('Identification.tgt')==b'device-one'
    archive.unlink()


def test_bad_crc_is_rejected_before_any_merge(tmp_path):
    path=seed(tmp_path/'seed.zip')
    with zipfile.ZipFile(path) as archive:
        info=archive.getinfo('Identification.tgt')
        offset=info.header_offset+30+len(info.filename.encode())+len(info.extra)
    raw=bytearray(path.read_bytes());raw[offset]^=1;path.write_bytes(raw)
    with pytest.raises(zipfile.BadZipFile): archive_io.import_seed_zip(path,tmp_path)
    assert not (tmp_path/'work/archive/Identification.tgt').exists()


def test_expansion_limit_is_checked_before_extracting(tmp_path,monkeypatch):
    path=seed(tmp_path/'seed.zip')
    monkeypatch.setattr(archive_io,'MAX_EXPANDED_BYTES',1)
    with pytest.raises(ValueError,match='limit'): archive_io.import_seed_zip(path,tmp_path)
    assert not (tmp_path/'work/archive').exists()


def test_snapshot_link_cannot_export_outside_published(tmp_path):
    published=tmp_path/'published';published.mkdir()
    (published/'current').symlink_to(tmp_path)
    with pytest.raises(ValueError): archive_io.build_snapshot_zip(tmp_path)


def test_transfer_lock_rejects_overlap_without_cleaning_active_files(tmp_path):
    with archive_io.transfer_lock(tmp_path):
        active = tmp_path / 'imports/upload-active.zip'
        active.parent.mkdir(parents=True, exist_ok=True)
        active.write_bytes(b'active upload')
        with pytest.raises(BlockingIOError):
            with archive_io.transfer_lock(tmp_path):
                pytest.fail('A competing transfer acquired the lock')
        assert active.read_bytes() == b'active upload'


def test_transfer_lock_cleans_abandoned_artifacts_only(tmp_path):
    for name in ('imports/upload-old.zip', 'imports/seed-old/data', 'exports/old.zip',
                 'imports/keep.zip', 'work/archive/Identification.tgt'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'preserved')
    with archive_io.transfer_lock(tmp_path):
        assert not (tmp_path / 'imports/upload-old.zip').exists()
        assert not (tmp_path / 'imports/seed-old').exists()
        assert not (tmp_path / 'exports/old.zip').exists()
        assert (tmp_path / 'imports/keep.zip').read_bytes() == b'preserved'
        assert (tmp_path / 'work/archive/Identification.tgt').read_bytes() == b'preserved'


def test_import_cancels_within_a_file_before_merge(tmp_path, monkeypatch):
    path = seed(tmp_path / 'seed.zip', {'Identification.tgt': b'x' * (2 * 1024**2)})
    original_read = zipfile.ZipExtFile.read
    def interrupt_read(stream, *args, **kwargs):
        block = original_read(stream, *args, **kwargs)
        if block:
            server.STOP.set()
        return block
    monkeypatch.setattr(zipfile.ZipExtFile, 'read', interrupt_read)
    try:
        with pytest.raises(RuntimeError, match='interrupted'):
            archive_io.import_seed_zip(path, tmp_path)
        assert not (tmp_path / 'work/archive').exists()
        assert not list((tmp_path / 'imports').glob('seed-*'))
        state = json.loads((tmp_path / 'state/import.json').read_text())
        assert state['running'] is False and state['phase'] == 'failed'
    finally:
        server.STOP.clear()


def test_export_cancels_between_chunks_and_removes_partial_zip(tmp_path, monkeypatch):
    snapshot = tmp_path / 'published/complete'
    snapshot.mkdir(parents=True)
    (snapshot / 'large.edf').write_bytes(b'x' * (3 * 1024**2))
    (snapshot.parent / 'current').symlink_to('complete')
    original_write = zipfile._ZipWriteFile.write
    def interrupt_write(stream, block):
        result = original_write(stream, block)
        server.STOP.set()
        return result
    monkeypatch.setattr(zipfile._ZipWriteFile, 'write', interrupt_write)
    try:
        with pytest.raises(RuntimeError, match='interrupted'):
            archive_io.build_snapshot_zip(tmp_path)
        assert not list((tmp_path / 'exports').glob('*.zip'))
        assert (snapshot / 'large.edf').stat().st_size == 3 * 1024**2
    finally:
        server.STOP.clear()
