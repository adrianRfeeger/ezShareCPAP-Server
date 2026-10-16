"""Disk accounting and locks for immutable snapshots and temporary archives."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
import uuid

RESERVE_BYTES=1024**3
SNAPSHOT=re.compile(r'\d{8}T\d{6}Z-[0-9a-f]{8}')
_cache={}
_cache_lock=threading.Lock()

def atomic(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_name('.'+uuid.uuid4().hex)
 try:
  temp.write_text(json.dumps(value));temp.replace(path)
 finally:temp.unlink(missing_ok=True)

@contextmanager
def file_lock(path,exclusive=True,blocking=True):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('a') as handle:
  fcntl.flock(handle,(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|(0 if blocking else fcntl.LOCK_NB))
  try:yield handle
  finally:fcntl.flock(handle,fcntl.LOCK_UN)

def snapshot_access(root,exclusive,blocking=True):
 return file_lock(Path(root)/'state/publication.lock',exclusive,blocking)

def _reservations(root):
 directory=Path(root)/'state/reservations';directory.mkdir(parents=True,exist_ok=True)
 return directory

def _reserved(directory):
 total=0
 for path in directory.glob('*.json'):
  lease=path.with_suffix('.lock')
  with lease.open('a') as handle:
   try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:
    total+=json.loads(path.read_text())['remaining'];continue
   path.unlink(missing_ok=True);lease.unlink(missing_ok=True)
 return total

def reserved_bytes(root):
 directory=_reservations(root)
 with file_lock(directory/'metadata.lock'):return _reserved(directory)

class Reservation:
 def __init__(self,root,operation,required,reserve):
  self.root=Path(root);self.directory=_reservations(root);self.reserve=reserve
  self.path=self.directory/(uuid.uuid4().hex+'.json');self.handle=None
  self.value={'operation':operation,'remaining':required}
 def __enter__(self):
  with file_lock(self.directory/'metadata.lock'):
   free=shutil.disk_usage(self.root).free
   if free-_reserved(self.directory)-self.reserve<self.value['remaining']:
    raise OSError('Not enough free space; reduce the upload size or free storage first')
   self.handle=self.path.with_suffix('.lock').open('a')
   fcntl.flock(self.handle,fcntl.LOCK_EX)
   atomic(self.path,self.value)
  return self
 def consume(self,count):
  with file_lock(self.directory/'metadata.lock'):
   self.value['remaining']=max(0,self.value['remaining']-count)
   atomic(self.path,self.value)
   if shutil.disk_usage(self.root).free-_reserved(self.directory)<self.reserve:
    raise OSError('Storage reserve reached; completed files have been preserved')
 def __exit__(self,*args):
  with file_lock(self.directory/'metadata.lock'):
   self.path.unlink(missing_ok=True)
   if self.handle:self.handle.close()
   self.path.with_suffix('.lock').unlink(missing_ok=True)

def reserve_space(root,operation,required_bytes,reserve_bytes=RESERVE_BYTES):
 return Reservation(root,operation,max(0,required_bytes),reserve_bytes)

def tree_size(path):
 total=count=0
 for base,dirs,files in os.walk(path,followlinks=False):
  dirs[:]=[d for d in dirs if not Path(base,d).is_symlink()]
  for name in files:
   item=Path(base,name)
   if item.is_symlink():continue
   try:total+=item.stat().st_size;count+=1
   except FileNotFoundError:pass
 return total,count

def refresh_inventory(root):
 root=Path(root)
 work,count=tree_size(root/'work/archive')
 snapshots,_=tree_size(root/'published')
 temporary=sum(tree_size(root/part)[0] for part in ('imports','exports'))
 value={'work_bytes':work,'working_files':count,'snapshot_bytes':snapshots,'temp_bytes':temporary,
        'updated_at':datetime.now(timezone.utc).isoformat()}
 atomic(root/'state/storage.json',value)
 return value

def storage_status(root):
 root=Path(root);root.mkdir(parents=True,exist_ok=True)
 try:value=json.loads((root/'state/storage.json').read_text())
 except (OSError,ValueError):value={'work_bytes':None,'working_files':None,'snapshot_bytes':None,'temp_bytes':None,'updated_at':None}
 usage=shutil.disk_usage(root)
 value.update(free_bytes=usage.free,total_bytes=usage.total,reserved_bytes=reserved_bytes(root))
 value['warning']='Storage is running low.' if usage.free<max(2*1024**3,usage.total*.15) else None
 return value

def inventory_loop(root,stop):
 while not stop.is_set():
  try:refresh_inventory(root)
  except OSError:pass
  stop.wait(60)

def retention_preview(root,keep):
 if type(keep) is not int or not 1<=keep<=10:raise ValueError('Keep between 1 and 10 snapshots')
 published=Path(root)/'published';current=published/'current'
 if not current.is_symlink():raise ValueError('No valid current snapshot; cleanup is disabled')
 target=current.resolve()
 if target.parent!=published.resolve() or not target.is_dir() or not SNAPSHOT.fullmatch(target.name):
  raise ValueError('Invalid current snapshot; cleanup is disabled')
 names=sorted(p.name for p in published.iterdir() if not p.is_symlink() and p.is_dir() and SNAPSHOT.fullmatch(p.name))
 retained={target.name}
 retained.update(n for n in reversed(names) if n!=target.name and len(retained)<keep)
 delete=[n for n in names if n not in retained]
 return {'delete':delete,'retain':sorted(retained),'reclaimable_bytes':sum(tree_size(published/n)[0] for n in delete)}

def prune_snapshots(root,keep):
 with snapshot_access(root,True):
  preview=retention_preview(root,keep)
  for name in preview['delete']:shutil.rmtree(Path(root)/'published'/name)
 refresh_inventory(root)
 return preview
