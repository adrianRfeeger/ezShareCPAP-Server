"""Import a local card archive and export immutable completed snapshots."""
from datetime import datetime, timezone
import hashlib
import os
from contextlib import contextmanager, ExitStack
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import time
import uuid
import zipfile

import server
import storage
from file_ops import local_case_path

MAX_ZIP_BYTES = 4 * 1024**3
MAX_EXPANDED_BYTES = 8 * 1024**3
MAX_ENTRIES = 50000
RESERVE_BYTES = 256 * 1024**2


@contextmanager
def transfer_lock(root):
    """Serialize archive construction and recover files from interrupted requests."""
    root=Path(root)
    with server.run_lock(root/'state/transfers'):
        for pattern in ('imports/upload-*.zip','imports/seed-*','exports/*.zip'):
            for path in root.glob(pattern):
                if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
                else: path.unlink(missing_ok=True)
        yield


def _entries(archive):
    infos=archive.infolist()
    if len(infos)>MAX_ENTRIES:
        raise ValueError('ZIP contains too many entries')
    result=[]
    for info in infos:
        name=info.filename.replace('\\','/')
        parts=PurePosixPath(name).parts
        mode=info.external_attr >> 16
        if name.startswith('/') or not parts or '..' in parts or ':' in parts[0] or '\x00' in name:
            raise ValueError('ZIP contains an unsafe path')
        if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or info.flag_bits & 1:
            raise ValueError('Links, special files and encrypted ZIPs are unsupported')
        if info.is_dir() or any(p.startswith('.') or p=='__MACOSX' for p in parts):
            continue
        result.append((info,parts))
    if result and len({parts[0] for _,parts in result})==1 and all(len(parts)>1 for _,parts in result):
        result=[(info,parts[1:]) for info,parts in result]
    seen=set()
    for info,parts in result:
        key='/'.join(parts).casefold()
        if key in seen:
            raise ValueError('ZIP contains duplicate file paths')
        seen.add(key)
    if 'identification.tgt' not in seen:
        raise ValueError('Include the full SD folder with Identification.tgt at its root')
    if sum(info.file_size for info,_ in result)>MAX_EXPANDED_BYTES:
        raise ValueError('Expanded ZIP exceeds the 8 GB limit')
    return result


def _hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').digest()


def import_seed_zip(zip_path, root):
    root=Path(root)
    with server.run_lock(root/'state'):
        state={'running':True,'phase':'validating','action':'Checking the uploaded SD folder',
               'imported':0,'kept':0,'error':None}
        record=root/'state/import.json'
        server.atomic_json(record,state)
        staging=None
        try:
            if Path(zip_path).stat().st_size>MAX_ZIP_BYTES:
                raise ValueError('ZIP exceeds the 4 GB upload limit')
            with ExitStack() as stack, zipfile.ZipFile(zip_path) as archive:
                entries=_entries(archive)
                expanded=sum(info.file_size for info,_ in entries)
                lease=stack.enter_context(storage.reserve_space(root,'import extraction',expanded))
                directory=root/'imports';directory.mkdir(parents=True,exist_ok=True)
                staging=Path(tempfile.mkdtemp(prefix='seed-',dir=directory))
                extracted=0
                for info,parts in entries:
                    if server.STOP.is_set(): raise RuntimeError('Import was interrupted')
                    destination=staging.joinpath(*parts)
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(info) as source,destination.open('xb') as target:
                        while block:=source.read(1024*1024):
                            if server.STOP.is_set(): raise RuntimeError("Import was interrupted")
                            extracted+=len(block)
                            if extracted>MAX_EXPANDED_BYTES: raise ValueError('Expanded ZIP exceeds limit')
                            target.write(block)
                            target.flush()
                            lease.consume(len(block))
                    # ZIP stores wall-clock dates. The server's card parser uses UTC wall time.
                    stamp=datetime(*info.date_time,tzinfo=timezone.utc).timestamp()
                    os.utime(destination,(stamp,stamp))
            work=root/'work/archive'
            identity=next(staging.joinpath(*parts) for _,parts in entries if '/'.join(parts).casefold()=='identification.tgt')
            existing_identity=local_case_path(work/'Identification.tgt')
            if existing_identity.is_symlink():
                raise ValueError('Working archive contains a symlink')
            if existing_identity.is_file() and _hash(existing_identity)!=_hash(identity):
                raise ValueError('Device identification differs from the server archive; use the same device')
            state.update(phase='importing',action='Adding local files to the working archive')
            server.atomic_json(record,state)
            last_write=0
            for info,parts in entries:
                if server.STOP.is_set(): raise RuntimeError('Import was interrupted')
                destination=work
                for part in parts:
                    destination=local_case_path(destination/part)
                    if destination.is_symlink(): raise ValueError('Working archive contains a symlink')
                if destination.exists():
                    state['kept']+=1
                else:
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    staging.joinpath(*parts).replace(destination)
                    state['imported']+=1
                if time.monotonic()-last_write>0.5:
                    server.atomic_json(record,state);last_write=time.monotonic()
            state.update(phase='completed',action='Local files imported. Sync to fetch missing or changed files.')
            return {'imported':state['imported'],'kept':state['kept']}
        except (OSError,ValueError,RuntimeError,zipfile.BadZipFile) as exc:
            state.update(phase='failed',error=str(exc),action='Import failed')
            raise
        finally:
            if staging: shutil.rmtree(staging,ignore_errors=True)
            state['running']=False
            server.atomic_json(record,state)


def build_snapshot_zip(root):
    with storage.snapshot_access(root,False):
        return _build_snapshot_zip(root)

def _build_snapshot_zip(root):
    root=Path(root)
    published=(root/'published').resolve()
    current=published/'current'
    if not current.exists(): raise FileNotFoundError('No completed snapshot is available yet')
    snapshot=current.resolve()
    if snapshot.parent!=published or not snapshot.is_dir():
        raise ValueError('Invalid snapshot path')
    files=[p for p in snapshot.rglob('*') if p.is_file() and not p.is_symlink()]
    if shutil.disk_usage(root).free < sum(p.stat().st_size for p in files)+RESERVE_BYTES:
        raise ValueError('Not enough free space to prepare the download')
    exports=root/'exports';exports.mkdir(parents=True,exist_ok=True)
    output=exports/(uuid.uuid4().hex+'.zip')
    try:
        with storage.reserve_space(root,'ZIP export',sum(p.stat().st_size for p in files)+len(files)*256) as lease, zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
            for path in sorted(files):
                info=zipfile.ZipInfo.from_file(path,path.relative_to(snapshot).as_posix())
                with path.open('rb') as source, archive.open(info,'w',force_zip64=True) as target:
                    while block:=source.read(1024*1024):
                        if server.STOP.is_set(): raise RuntimeError('Download preparation was interrupted')
                        target.write(block)
                        lease.consume(len(block))
        return output
    except Exception:
        output.unlink(missing_ok=True)
        raise
