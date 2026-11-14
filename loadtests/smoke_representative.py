"""Validate copied real graders using only the isolated fixture's student login."""
import json,sys,time
from pathlib import Path
import requests
p=Path(sys.argv[1]);f=json.loads(p.read_text());base=f['url'];s=requests.Session();s.trust_env=False

def call(method,path,body=None):
 r=s.request(method,base+path,json=body,headers={'Referer':base+'/','X-CSRFToken':s.cookies.get('csrftoken','')},timeout=30)
 assert r.status_code==200,f'{method} {path}: HTTP {r.status_code}'
 return r.json()
try:
 call('GET','/api/session/');call('POST','/api/auth/login/',f['accounts'][-1]);call('POST',f"/api/assignments/{f['lesson_id']}/open/",{})
 count=0
 for item in f['workloads']:
  call('POST',f"/api/assignments/{item.get('lesson_id',f['lesson_id'])}/open/",{})
  for operation,correct in [('run',False),('run',True),('submit',False),('submit',True)]:
   data=call('GET',f"/api/studio/{item['activity']}/");files=data['workspace'];files[item['entrypoint']]=item['correct_source' if correct else 'wrong_source']
   job=call('POST',f"/api/execute/{item['revision']}/",{'operation':operation,'entrypoint':item['entrypoint'],'files':files});deadline=time.monotonic()+60
   while time.monotonic()<deadline:
    time.sleep(2);state=call('GET',f"/api/jobs/{job['id']}/")
    if state['status'] in {'completed','failed'}:break
   assert state['status']=='completed' and not state['result'].get('error'),'Execution failed/stalled'
   result=state['result']
   if operation=='submit':assert bool(result['passed'])==correct,'Unexpected grade for '+item['name']
   else:
    assert result['execution_status']=='ok','Run failed for '+item['name']
    item['correct_stdout' if correct else 'wrong_stdout']=result['stdout']
   count+=1;print('Verified',item['name'],item['case_count'],'cases:',operation,correct,flush=True)
 f['preflight_jobs']=count;p.write_text(json.dumps(f,indent=2));p.chmod(0o600)
 print('All copied grader controls passed.',flush=True)
finally:
 try:call('POST','/api/auth/logout/',{})
 except Exception:pass
 s.close()
