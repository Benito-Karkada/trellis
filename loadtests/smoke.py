"""Single synthetic student verifies expected grades before a load run."""
import json,sys,time
from pathlib import Path
import requests
f=json.loads(Path(sys.argv[1]).read_text());base=f['url'];s=requests.Session();s.trust_env=False

def call(method,path,body=None):
 r=s.request(method,base+path,json=body,headers={'Referer':base+'/','X-CSRFToken':s.cookies.get('csrftoken','')},timeout=30)
 assert r.status_code==200,f'{method} {path}: HTTP {r.status_code}'
 return r.json()
try:
 call('GET','/api/session/');call('POST','/api/auth/login/',f['accounts'][1])
 assert call('GET','/api/outline/')['term']=='loadtest-'+f['run_id']
 call('POST',f"/api/assignments/{f['lesson_id']}/open/",{})
 n=f['native'];result=call('POST',f"/api/submit-native/{n['revision']}/",{'responses':{'q1':'a'}})
 assert result['passed'] and result['score']=='1'
 c=f['coding']
 for operation,correct in [('run',False),('submit',False),('run',True),('submit',True)]:
  data=call('GET',f"/api/studio/{c['activity']}/");files=data['workspace'];files['main.py']=f['correct_source' if correct else 'wrong_source']
  job=call('POST',f"/api/execute/{c['revision']}/",{'operation':operation,'entrypoint':'main.py','files':files});deadline=time.monotonic()+60
  while time.monotonic()<deadline:
   time.sleep(2);state=call('GET',f"/api/jobs/{job['id']}/")
   if state['status'] in {'completed','failed'}:break
  assert state['status']=='completed' and not state['result'].get('error'),'Execution failed/stalled'
  r=state['result']
  assert (r['passed']==correct and r['score']==('3' if correct else '0')) if operation=='submit' else r['stdout']==('5\n' if correct else '-1\n')
  print('Verified:',operation,'correct' if correct else 'incorrect',flush=True)
 f['preflight_jobs']=f.get('preflight_jobs',0)+4
 Path(sys.argv[1]).write_text(json.dumps(f,indent=2));Path(sys.argv[1]).chmod(0o600)
 print('Local preflight passed: login, full outline, native points, Run, wrong/correct grading, read-only feedback.',flush=True)
finally:
 try:call('POST','/api/auth/logout/',{})
 except Exception:pass
 s.close()
