"""A single bounded burst of real Run/Submit jobs from tagged synthetic students.

No Canvas, quizzes, course edits or retained test identities. Prepare a fresh
live fixture first, then remove it with cleanup_live.py after saving this report.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import sys
import threading
import time
import requests
from monitor import ApiQueue, azure_metrics, RESOURCES

path=Path(sys.argv[1]);fixture=json.loads(path.read_text());base=fixture['url'].rstrip('/')
assert fixture.get('live_course') and 2<=len(fixture['accounts'])<=10
report={'run_id':fixture['run_id'],'students':len(fixture['accounts']),'checks':[]};sessions=[];inputs=[]
def call(session,method,url,body=None):
    response=session.request(method,base+url,json=body,headers={'Referer':base+'/',
        'X-CSRFToken':session.cookies.get('csrftoken','')},timeout=30)
    response.raise_for_status();return response.json()
try:
    for index,account in enumerate(fixture['accounts']):
        assert account['email'].startswith('loadtest-'+fixture['run_id']+'-')
        session=requests.Session();session.trust_env=False;sessions.append(session)
        call(session,'GET','/api/session/');call(session,'POST','/api/auth/login/',{'email':account['email'],'password':account['password']})
        item=fixture['workloads'][(index//2)%len(fixture['workloads'])]
        call(session,'POST',f"/api/assignments/{item['lesson_id']}/open/",{})
        source=call(session,'GET',f"/api/studio/{item['activity']}/")['workspace']
        source[item['entrypoint']]=item['correct_source']
        inputs.append((session,item,source,'run' if index%2 else 'submit'))
    barrier=threading.Barrier(len(inputs))
    def execute(row):
        session,item,source,operation=row;barrier.wait(timeout=10);start=time.monotonic()
        job=call(session,'POST',f"/api/execute/{item['revision']}/",{'operation':operation,'entrypoint':item['entrypoint'],'files':source})
        while time.monotonic()-start<90:
            state=call(session,'GET',f"/api/jobs/{job['id']}/")
            if state['status'] in ('completed','failed'):
                assert state['status']=='completed' and not state['result'].get('error')
                assert state['result'].get('passed') if operation=='submit' else state['result'].get('execution_status')=='ok'
                return {'job_id':job['id'],'operation':operation,'cases':item['case_count'],
                        'client_seconds':round(time.monotonic()-start,3),'passed':True}
            time.sleep(1)
        raise AssertionError('Execution did not complete in the bounded test window')
    with ThreadPoolExecutor(max_workers=len(inputs)) as pool:report['checks']=list(pool.map(execute,inputs))
    queue=ApiQueue(fixture)
    try:
        snapshot=queue.read();assert not snapshot['test_active_jobs'];report['queue']=snapshot
        response=queue.session.get(base+f"/api/v1/courses/{fixture['course_id']}/execution-jobs/?limit=100&enrollment_ids="+','.join(map(str,fixture['enrollment_ids'])),headers={'Authorization':'Bearer '+queue.bearer},timeout=30)
        response.raise_for_status();jobs=response.json()['results'];assert len(jobs)==len(inputs)
        intervals=[];events=[]
        for job in jobs:
            start=datetime.fromisoformat(job['claimed_at']);end=datetime.fromisoformat(job['completed_at'])
            events.extend([(start,1),(end,-1)])
            intervals.append({key:job[key] for key in ('id','operation','status','submitted_at','claimed_at','completed_at')})
        active=0;peak=0
        for _,change in sorted(events,key=lambda event:(event[0],event[1])):active+=change;peak=max(peak,active)
        report['peak_simultaneous_jobs']=peak;report['job_intervals']=intervals
        assert peak==2,f'Expected two occupied worker slots; observed {peak}'
    finally:queue.close()
    report['azure_metrics']={key:azure_metrics(pair) for key,pair in RESOURCES.items()}
    report['passed']=True
    print('Parallel burst passed:',len(inputs),'jobs; peak overlap',peak,'; longest queue wait',snapshot['queue_wait']['max_seconds'],'seconds',flush=True)
finally:
    for session in sessions:
        try:call(session,'POST','/api/auth/logout/',{})
        except requests.RequestException:pass
        session.close()
    (path.parent/'summary.json').write_text(json.dumps(report,indent=2))
