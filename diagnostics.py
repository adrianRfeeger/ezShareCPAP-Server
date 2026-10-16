"""Bounded card checks and optional read-only connection telemetry."""
from collections import deque
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time

class TransferRate:
 def __init__(self):self.run=None;self.file=None;self.last=0;self.total=0;self.samples=deque();self.last_activity=None
 def observe(self,run_id,filename,received,now=None):
  now=time.monotonic() if now is None else now
  if self.run!=run_id:
   self.__init__();self.run=run_id
  delta=max(0,received-self.last) if self.file==filename and received>=self.last else received
  self.file=filename;self.last=received;self.total+=delta
  if delta:self.last_activity=now
  if not self.samples or now-self.samples[-1][0]>=1:self.samples.append((now,self.total))
  while len(self.samples)>1 and self.samples[1][0]<now-60:self.samples.popleft()
  rate=None
  if self.samples and now-self.samples[0][0]>=1:rate=(self.total-self.samples[0][1])/(now-self.samples[0][0])
  return {'bytes_per_second':rate,'received_bytes':self.total,'last_activity_at':datetime.now(timezone.utc).isoformat() if delta else None}

def read_wifi_status(path,now):
 try:
  path=Path(path)
  if path.stat().st_size>16384:raise ValueError('Sample too large')
  data=json.loads(path.read_text())
  timestamp=datetime.fromisoformat(data['sampled_at'])
  age=(now-timestamp).total_seconds()
  result={key:data.get(key) for key in ('sampled_at','interface','connected','signal_dbm','rx_mbps','tx_mbps','power_save','error')}
  for key in ('signal_dbm','rx_mbps','tx_mbps'):
   if result[key] is not None and (type(result[key]) not in (int,float) or not -200<=result[key]<=100000):raise ValueError('Invalid numeric sample')
  result.update(available=True,stale=age>60 or age< -5,age_seconds=max(0,int(age)))
  return result
 except (OSError,ValueError,TypeError,KeyError):return {'available':False,'stale':True,'error':'Wi-Fi details unavailable'}

def check_card(cfg):
 started=time.monotonic()
 try:
  completed=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--probe',cfg['url']],capture_output=True,text=True,timeout=5)
  data=json.loads(completed.stdout)
 except subprocess.TimeoutExpired:data={'reachable':False,'error':'Card check timed out'}
 except (OSError,ValueError):data={'reachable':False,'error':'Card check could not complete'}
 data.update(elapsed_ms=round((time.monotonic()-started)*1000),checked_at=datetime.now(timezone.utc).isoformat())
 return data

if __name__=='__main__':
 import requests
 result={'reachable':False,'error':'Card is unreachable'}
 try:
  with requests.get(sys.argv[2],timeout=4,stream=True,allow_redirects=False) as response:
   result={'reachable':response.status_code==200,'error':None if response.status_code==200 else 'Card returned an unexpected response'}
 except requests.RequestException:pass
 print(json.dumps(result))
