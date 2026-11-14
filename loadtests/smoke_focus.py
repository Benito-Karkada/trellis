"""Separate post-run check of the real away/hidden/back telemetry protocol."""
import json,sys,time,uuid
from pathlib import Path
import requests
p=Path(sys.argv[1]);f=json.loads(p.read_text());s=requests.Session();s.trust_env=False;base=f['url']
def call(method,path,body=None):
 r=s.request(method,base+path,json=body,headers={'Referer':base+'/','X-CSRFToken':s.cookies.get('csrftoken','')},timeout=30);r.raise_for_status();return r.json()
try:
 call('GET','/api/session/');call('POST','/api/auth/login/',f['accounts'][0]);call('POST',f"/api/assignments/{f['lesson_id']}/open/",{})
 episode=str(uuid.uuid4());tab=str(uuid.uuid4())
 for state in ('away','hidden','back'):
  if state=='back':time.sleep(3)
  result=call('POST',f"/api/assignments/{f['lesson_id']}/focus/",{'event_id':str(uuid.uuid4()),'episode_id':episode,'tab_id':tab,'state':state,'reason':'tab','elapsed_ms':3000 if state=='back' else 0,'part_id':f['coding']['activity']})
  assert result['recorded']
 call('POST','/api/auth/logout/',{});call('GET','/api/session/');call('POST','/api/auth/login/',f['staff'])
 report=call('GET','/api/settings/submission-review/');student=next(r for r in report['results'] if r['email']==f['accounts'][0]['email'])
 assert student['focus_changes']>=1
 f['post_run_focus_check']={'email':student['email'],'verified_episodes':1};p.write_text(json.dumps(f,indent=2));p.chmod(0o600)
 print('Post-run focus protocol and review contribution verified; separate from timed Locust statistics.')
finally:
 try:call('POST','/api/auth/logout/',{})
 except Exception:pass
 s.close()
