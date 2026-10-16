"""Daily wall-clock scheduling shared by the scheduler and dashboard."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo

def _slot(date,cfg):
 hour,minute=map(int,cfg['time'].split(':'))
 local=datetime.combine(date,datetime.min.time()).replace(hour=hour,minute=minute)
 zone=ZoneInfo(cfg['timezone'])
 # A nonexistent local minute advances to the first representable local minute.
 for _ in range(1441):
  utc=local.replace(tzinfo=zone,fold=0).astimezone(timezone.utc)
  if utc.astimezone(zone).replace(tzinfo=None)==local:return utc
  local+=timedelta(minutes=1)
 raise ValueError('Could not resolve schedule time')

def schedule_decision(now,cfg,last_scheduled_date):
 today=now.astimezone(ZoneInfo(cfg['timezone'])).date()
 slot=_slot(today,cfg)
 if (not last_scheduled_date or today.isoformat()>last_scheduled_date) and now>=slot:
  return {'due_date':today.isoformat(),'next_run_at':slot}
 next_day=today
 if now>=slot or (last_scheduled_date and today.isoformat()<=last_scheduled_date):
  next_day=max(today,datetime.fromisoformat(last_scheduled_date).date() if last_scheduled_date else today)+timedelta(days=1)
 return {'due_date':None,'next_run_at':_slot(next_day,cfg)}

def schedule_status(now,cfg,status):
 decision=schedule_decision(now,cfg,status.get('last_scheduled_date'))
 failures=0
 for entry in reversed(status.get('history',[])):
  if entry.get('trigger')!='scheduled':continue
  if entry.get('result')=='Success':break
  if entry.get('result')=='Failed':failures+=1
 age=None
 try:
  if status.get('last_success'):age=max(0,int((now-datetime.fromisoformat(status['last_success'])).total_seconds()))
 except (ValueError,TypeError):pass
 warnings=[]
 if failures>=2:warnings.append(f'{failures} consecutive scheduled downloads failed. Check recent runs and the card connection.')
 if age is not None and age>129600:warnings.append('The latest completed snapshot is more than 36 hours old.')
 paused=bool(status.get('paused'))
 return {'next_run_at':None if paused else decision['next_run_at'].isoformat(),'timezone':cfg['timezone'],'paused':paused,
         'overdue':bool(decision['due_date']) and not paused,'snapshot_age_seconds':age,
         'consecutive_scheduled_failures':failures,'warnings':warnings}
