#!/usr/bin/env python3
"""Start a bounded local Locust dashboard, or a timed headless test with reports."""
import argparse,json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixture',required=True,type=Path)
    p.add_argument('--profile',choices=['mixed','burst'],default='mixed');p.add_argument('--users',type=int,default=10);p.add_argument('--minutes',type=int,default=5);p.add_argument('--dashboard',action='store_true');a=p.parse_args()
    if not 1<=a.users<=20 or not 1<=a.minutes<=10:raise ValueError('Use 1–20 students for 1–10 minutes.')
    data=json.loads(a.fixture.read_text())
    if a.users>len(data['accounts']):raise ValueError('The fixture has fewer unique test accounts than requested users.')
    fixture=a.fixture.resolve();prefix=fixture.parent/'locust'
    env={**os.environ,'TRELLIS_LOAD_FIXTURE':str(fixture),'TRELLIS_LOAD_PROFILE':a.profile,'TRELLIS_LOAD_USERS':str(a.users)}
    command=[str(ROOT/'.venv-loadtest/bin/locust'),'-f',str(ROOT/'loadtests/locustfile.py'),'--host',data['url'],
        '--users',str(a.users),'--spawn-rate','1','--run-time',str(a.minutes)+'m','--stop-timeout','65',
        '--csv',str(prefix),'--csv-full-history','--html',str(prefix)+'.html']
    if a.dashboard:command+=['--web-host','127.0.0.1','--web-port','8089','--autostart','--autoquit','5']
    else:command+=['--headless']
    (fixture.parent/'run-metadata.json').write_text(json.dumps({'users':a.users,'minutes':a.minutes,'profile':a.profile,'started_at':datetime.now(timezone.utc).isoformat()},indent=2))
    print(f"Testing {data['url']} with {a.users} students for {a.minutes} minutes. Reports: {prefix}",flush=True)
    raise SystemExit(subprocess.call(command,cwd=ROOT,env=env))
if __name__=='__main__':main()
