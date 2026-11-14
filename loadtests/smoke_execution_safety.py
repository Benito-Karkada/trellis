"""Bounded live safety check: tagged accounts only; no course or Canvas edits.

Use a newly prepared live fixture. All duplicate/conflict responses are expected
protections, not errors. Save summary before cleanup_live.py removes the accounts.
"""
import concurrent.futures
import json
from pathlib import Path
import sys
import time
import requests

path=Path(sys.argv[1]); fixture=json.loads(path.read_text()); base=fixture['url'].rstrip('/')
assert fixture.get('live_course') and 2<=len(fixture['accounts'])<=5
sessions=[]; jobs=[]; report={'run_id':fixture['run_id'],'checks':[]}
def call(session,method,url,body=None):
    response=session.request(method,base+url,json=body,headers={'Referer':base+'/',
        'X-CSRFToken':session.cookies.get('csrftoken','')},timeout=30)
    return response

def wait(session,job):
    end=time.monotonic()+60
    while time.monotonic()<end:
        response=call(session,'GET',f"/api/jobs/{job['id']}/");response.raise_for_status();state=response.json()
        if state['status'] in ('completed','failed'):return state
        time.sleep(.4)
    raise AssertionError('Job did not finish within the bounded test window')

try:
    item=fixture['coding']
    for account in fixture['accounts']:
        assert account['email'].startswith('loadtest-'+fixture['run_id']+'-')
        session=requests.Session();session.trust_env=False;sessions.append(session)
        call(session,'GET','/api/session/').raise_for_status()
        call(session,'POST','/api/auth/login/',{'email':account['email'],'password':account['password']}).raise_for_status()
        call(session,'POST',f"/api/assignments/{item['lesson_id']}/open/",{}).raise_for_status()
    files=[]
    for session in sessions:
        data=call(session,'GET',f"/api/studio/{item['activity']}/").json()
        source=dict(data['workspace']);source[item['entrypoint']]='while True:\n    pass\n';files.append(source)
    # Queue the last account first so simultaneous clicks race on first-workspace
    # creation, while other accounts occupy the worker with bounded busy loops.
    for session,source in zip(sessions[:-1],files[:-1]):
        response=call(session,'POST',f"/api/execute/{item['revision']}/",{'operation':'submit','files':source,'entrypoint':item['entrypoint']})
        response.raise_for_status();jobs.append((session,response.json(),time.monotonic()))
    session=sessions[-1];source=files[-1]
    cookies=session.cookies.get_dict()
    def click(index):
        client=requests.Session();client.trust_env=False;client.cookies.update(cookies)
        try:
            return call(client,'POST',f"/api/execute/{item['revision']}/",{
                'operation':'run' if index%2 else 'submit','files':source,'entrypoint':item['entrypoint']})
        finally:client.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        responses=list(pool.map(click,range(12)))
    accepted=[response for response in responses if response.status_code==200]
    assert len(accepted)==1,[r.status_code for r in responses]
    assert sum(r.status_code==409 for r in responses)==11
    job=accepted[0].json();jobs.append((session,job,time.monotonic()))
    # A reload or a second tab cannot reset a workspace owned by an active job.
    reset=call(session,'POST',f"/api/workspaces/{item['revision']}/",{'action':'reset'})
    assert reset.status_code==409,reset.status_code
    report['checks'].append({'simultaneous_run_submit_requests':12,'accepted':1,'blocked_duplicates':11,'mid_job_reset_http':409})
    for session,job,start in jobs:
        state=wait(session,job);assert state['status']=='completed',state
        result=state['result'];assert not result.get('error'),result
        assert result.get('execution_status')=='timeout' or 'stopping condition' in result.get('full_output',''),result
        if 'checks' in result:
            assert result['score_fraction']=='0'
            assert sum('Not run because' in check['message'] for check in result['checks'])>=item['case_count']-1
        report['checks'].append({'job_id':job['id'],'status':'safely_stopped','observed_completion_seconds':round(time.monotonic()-start,2)})
    # Measure a timeout without queue waiting, for both actions.
    session=sessions[-1]
    for operation in ('run','submit'):
        source=call(session,'GET',f"/api/studio/{item['activity']}/").json()['workspace']
        source[item['entrypoint']]='while True:\n    pass\n'
        start=time.monotonic()
        response=call(session,'POST',f"/api/execute/{item['revision']}/",{'operation':operation,'files':source,'entrypoint':item['entrypoint']})
        response.raise_for_status();job=response.json()
        # Verify reset protection after the worker has actually claimed the job.
        running=False
        for _ in range(40):
            state=call(session,'GET',f"/api/jobs/{job['id']}/").json()
            if state['status']=='running':
                running=True
                reset=call(session,'POST',f"/api/workspaces/{item['revision']}/",{'action':'reset'})
                assert reset.status_code==409,reset.status_code
                report['checks'].append({'running_reset_operation':operation,'http':409})
                break
            assert state['status']=='pending',state['status']
            time.sleep(.1)
        assert running,'Worker did not claim the timeout test job'
        state=wait(session,job);elapsed=time.monotonic()-start
        assert state['status']=='completed' and elapsed<10
        result=state['result'];message=result.get('stdout','') if operation=='run' else result.get('full_output','')
        assert 'stopping condition' in message and 'Traceback' not in message
        report['checks'].append({'timeout_operation':operation,'end_to_end_seconds':round(elapsed,2),'friendly_feedback':True})
    # Confirm service recovery and reset after completion, then a normal grade.
    session=sessions[-1]
    reset=call(session,'POST',f"/api/workspaces/{item['revision']}/",{'action':'reset'});reset.raise_for_status()
    source=reset.json()['workspace'];source[item['entrypoint']]=item['correct_source']
    for operation in ('run','submit'):
        response=call(session,'POST',f"/api/execute/{item['revision']}/",{'operation':operation,'files':source,'entrypoint':item['entrypoint']})
        response.raise_for_status();state=wait(session,response.json());assert state['status']=='completed'
        result=state['result'];assert result.get('execution_status')=='ok' if operation=='run' else result.get('passed')
        report['checks'].append({'recovery_operation':operation,'passed':True})
    report['passed']=True
    print('Safety stress passed: 12 simultaneous clicks, 1 job, 11 conflicts; reset blocked; timeout and recovery verified.',flush=True)
finally:
    for session in sessions:
        try:call(session,'POST','/api/auth/logout/',{})
        except requests.RequestException:pass
        session.close()
    (path.parent/'summary.json').write_text(json.dumps(report,indent=2))
