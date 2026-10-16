import json
import pytest
import server,run_control

def test_pause_is_scoped_and_survives_restart(tmp_path):
 server.atomic_json(tmp_path/'state/status.json',{'running':True,'last_attempt':'one'})
 with server.run_lock(tmp_path/'state'):
  run_control.request_stop(tmp_path,'one')
  assert run_control.stop_requested(tmp_path,'one')
  assert not run_control.stop_requested(tmp_path,'two')
  with pytest.raises(ValueError):run_control.request_stop(tmp_path,'two')
 assert run_control.recovery_decision(tmp_path,server.read_state(tmp_path),{'resume_interrupted':True})=='paused'

def test_recovery_and_stopped_run_preserve_cache(tmp_path):
 from tests.test_server import config
 cfg=config(tmp_path)
 server.atomic_json(tmp_path/'state/status.json',{'running':True,'last_attempt':'dead'})
 assert run_control.recovery_decision(tmp_path,server.read_state(tmp_path),cfg)=='resume'
 def download(work,cfg):
  (work/'file').write_bytes(b'complete')
  run_control.request_stop(tmp_path,cfg['_run_id'])
  return True
 assert server.run_once(cfg,download=download)==0
 state=server.read_live_state(tmp_path)
 assert state['run_state']=='paused'
 assert state['history'][-1]['result']=='Stopped'
 assert not (tmp_path/'published/current').exists()
 assert (tmp_path/'work/archive/file').read_bytes()==b'complete'

def test_stop_during_transfer_finishes_one_file_only(tmp_path):
 from types import SimpleNamespace
 import file_ops
 stopped=[False]
 class Response:
  headers={'content-length':'4'}
  def raise_for_status(self):pass
  def iter_content(self,size):
   yield b'ab';stopped[0]=True;yield b'cd'
 class Session:
  def get(self,*a,**kw):return Response()
 app=SimpleNamespace(retries=1,connection_delay=0,_is_running=True,should_stop=lambda:stopped[0],session=Session())
 assert file_ops.download_file(app,'http://card/file',tmp_path/'one')
 assert (tmp_path/'one').read_bytes()==b'abcd'
 assert not file_ops.download_file(app,'http://card/file',tmp_path/'two')
 assert not (tmp_path/'two').exists()

def test_stop_during_snapshot_preserves_previous(tmp_path,monkeypatch):
 from tests.test_server import config
 cfg=config(tmp_path)
 def download(work,cfg):(work/'file').write_bytes(b'data');return True
 assert server.run_once(cfg,download=download)==0
 old=(tmp_path/'published/current').resolve()
 original=server.copy_archive
 def copy(src,dst,deadline):
  run_control.request_stop(tmp_path,server.read_state(tmp_path)['last_attempt'])
  return original(src,dst,deadline)
 monkeypatch.setattr(server,'copy_archive',copy)
 assert server.run_once(cfg,download=download)==0
 assert (tmp_path/'published/current').resolve()==old
 assert server.read_live_state(tmp_path)['run_state']=='paused'
