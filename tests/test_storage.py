import json
from pathlib import Path
import pytest
import storage

def snapshot(root,name):
 p=root/'published'/name;p.mkdir(parents=True);(p/'file').write_bytes(b'1234');return p

def test_retention_protects_current_unknown_and_links(tmp_path):
 names=[f'2026101{i}T000000Z-1234abcd' for i in range(4)]
 for name in names:snapshot(tmp_path,name)
 (tmp_path/'published/current').symlink_to(names[-1])
 snapshot(tmp_path,'personal-folder')
 (tmp_path/'published/20260101T000000Z-1234abcd').symlink_to(tmp_path)
 assert storage.retention_preview(tmp_path,2)['delete']==names[:2]
 storage.prune_snapshots(tmp_path,2)
 assert (tmp_path/'published/current/file').read_bytes()==b'1234'
 assert (tmp_path/'published/personal-folder').exists()

def test_missing_current_prevents_prune(tmp_path):
 snapshot(tmp_path,'20261010T000000Z-1234abcd')
 with pytest.raises(ValueError):storage.prune_snapshots(tmp_path,1)

def test_reservations_account_consumption_and_release(tmp_path,monkeypatch):
 from types import SimpleNamespace
 free=[1000];monkeypatch.setattr(storage.shutil,'disk_usage',lambda _:SimpleNamespace(free=free[0],total=2000))
 with storage.reserve_space(tmp_path,'one',600,100) as lease:
  with pytest.raises(OSError):
   with storage.reserve_space(tmp_path,'two',400,100):pass
  free[0]-=300;lease.consume(300)
  assert storage.reserved_bytes(tmp_path)==300
 assert storage.reserved_bytes(tmp_path)==0

def test_dead_owner_reservation_is_recovered(tmp_path):
 root=tmp_path/'state/reservations';root.mkdir(parents=True)
 (root/'dead.json').write_text(json.dumps({'remaining':999999}))
 (root/'dead.lock').touch()
 assert storage.reserved_bytes(tmp_path)==0

def test_snapshot_reader_blocks_retention(tmp_path):
 import subprocess,sys
 with storage.snapshot_access(tmp_path,False):
  script='import storage,pathlib;\nwith storage.snapshot_access(pathlib.Path('+repr(str(tmp_path))+'),True,blocking=False): pass'
  result=subprocess.run([sys.executable,'-c',script],capture_output=True)
  assert result.returncode!=0 and b'BlockingIOError' in result.stderr

def test_http_admission_rejects_before_reading_large_body(tmp_path,monkeypatch):
 import socket,threading
 from types import SimpleNamespace
 from waitress import create_server
 from upload_server import upload_channel
 monkeypatch.setattr(storage.shutil,'disk_usage',lambda _:SimpleNamespace(free=1000,total=2000))
 listener=create_server(lambda e,s:[],host='127.0.0.1',port=0)
 listener.channel_class=upload_channel(tmp_path,'Basic test',10000,100)
 def run():
  try:listener.run()
  except OSError:pass
 thread=threading.Thread(target=run,daemon=True);thread.start()
 try:
  with socket.create_connection(('127.0.0.1',int(listener.effective_port)),timeout=2) as sock:
   sock.sendall(b'POST /import HTTP/1.1\r\nHost: localhost\r\nAuthorization: Basic test\r\nContent-Length: 500\r\nExpect: 100-continue\r\nConnection: close\r\n\r\n')
   assert b'413' in sock.recv(4096)
  assert storage.reserved_bytes(tmp_path)==0
 finally:listener.close()
