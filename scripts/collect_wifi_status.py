#!/usr/bin/env python3
"""Collect link information inside the Linux guest without changing the interface."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import subprocess
import uuid

def parse_link(link,power):
 def number(pattern):
  match=re.search(pattern,link);return float(match.group(1)) if match else None
 return {'connected':'Connected to ' in link,'signal_dbm':number(r'signal:\s*(-?[\d.]+)'),
         'rx_mbps':number(r'rx bitrate:\s*([\d.]+)'), 'tx_mbps':number(r'tx bitrate:\s*([\d.]+)'),
         'power_save':'off' if 'off' in power else 'on' if 'on' in power else None}

def collect(interface):
 result={'sampled_at':datetime.now(timezone.utc).isoformat(),'interface':interface,'error':None}
 try:
  link=subprocess.run(['iw','dev',interface,'link'],capture_output=True,text=True,timeout=2,check=True)
  power=subprocess.run(['iw','dev',interface,'get','power_save'],capture_output=True,text=True,timeout=2,check=True)
  result.update(parse_link(link.stdout,power.stdout))
 except (OSError,subprocess.SubprocessError):result.update(connected=None,error='Wi-Fi information unavailable; check the guest collector')
 return result

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--interface',required=True);parser.add_argument('--output',required=True)
 args=parser.parse_args()
 if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}',args.interface):raise SystemExit('Invalid interface')
 path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_name('.'+uuid.uuid4().hex);temp.write_text(json.dumps(collect(args.interface)));temp.replace(path)
