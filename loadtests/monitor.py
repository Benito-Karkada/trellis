#!/usr/bin/env python3
"""Read-only local queue and Docker metrics sampler. Outputs private JSONL for a test run."""
import argparse,json,subprocess,sys,tempfile,time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def docker_metrics():
    ids = subprocess.check_output(['docker', 'compose', 'ps', '-q'], cwd=ROOT, text=True).split()
    if not ids:
        return []
    result = subprocess.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}', *ids],
                            capture_output=True, text=True, timeout=20, check=True)
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


class ApiQueue:
    """Course-scoped REST sampling; uses a temporary scoped token."""
    def __init__(self,fixture):
        import requests
        self.fixture=fixture;self.base=fixture['url'];self.session=requests.Session();self.session.trust_env=False
        self.token=None
        self.session.get(self.base+'/api/session/',timeout=30).raise_for_status()
        credentials=fixture.get('staff') or json.loads((ROOT/fixture['staff_credentials_file']).read_text())
        self.post('/api/auth/login/',{k:credentials[k] for k in ('email','password')})
        issued=self.post('/api/settings/api-tokens/',{'name':'Synthetic load-test monitor','scopes':['submissions:read'],'expires_in_days':1})
        self.token=issued['id'];self.bearer=issued['token']
    def post(self,path,body):
        r=self.session.post(self.base+path,json=body,headers={'Referer':self.base+'/','X-CSRFToken':self.session.cookies.get('csrftoken','')},timeout=30)
        r.raise_for_status();return r.json()
    def read(self):
        from collections import Counter
        rows=[];path=f"/api/v1/courses/{self.fixture['course_id']}/execution-jobs/?limit=200"
        if self.fixture.get('enrollment_ids'):path+='&enrollment_ids='+','.join(map(str,self.fixture['enrollment_ids']))
        while path:
            r=self.session.get(self.base+path,headers={'Authorization':'Bearer '+self.bearer},timeout=30);r.raise_for_status()
            data=r.json();rows.extend(data['results']);path=data.get('next')
        now=datetime.now(timezone.utc)
        def dt(v):return datetime.fromisoformat(v.replace('Z','+00:00')) if v else None
        pending=[dt(r['submitted_at']) for r in rows if r['status']=='pending']
        def timing(start,end):
            values=sorted((dt(r[end])-dt(r[start])).total_seconds() for r in rows if r[start] and r[end])
            return {'count':len(values),'p50_seconds':round(values[(len(values)-1)//2],3) if values else None,
                    'p95_seconds':round(values[min(len(values)-1,int(len(values)*.95))],3) if values else None,'max_seconds':round(max(values),3) if values else None}
        counts=dict(Counter(r['status'] for r in rows))
        return {'at':now.isoformat(),'scope':'tagged synthetic enrollments in actual course' if self.fixture.get('live_course') else 'synthetic course only','course_id':self.fixture['course_id'],'jobs':counts,
            'test_active_jobs':{k:v for k,v in counts.items() if k in {'pending','running'}},
            'test_oldest_pending_seconds':round((now-min(pending)).total_seconds(),1) if pending else 0,
            'queue_wait':timing('submitted_at','claimed_at'),'grading':timing('claimed_at','completed_at'),
            'end_to_end':timing('submitted_at','completed_at'),'review_observations':sum(bool(r['review_signals']) for r in rows)}
    def close(self):
        try:
            if self.token:self.post(f'/api/settings/api-tokens/{self.token}/revoke/',{})
            self.post('/api/auth/logout/',{})
        finally:self.session.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--duration',type=int,default=420);p.add_argument('--interval',type=int,default=30);p.add_argument('--once',action='store_true');a=p.parse_args()
    if a.interval<15 or not 1<=a.duration<=900:raise ValueError('Use interval >=15s and duration 1–900s.')
    fixture=json.loads(a.fixture.read_text());target=a.fixture.parent/'monitor.jsonl'
    deadline=time.monotonic()+a.duration
    api_queue=ApiQueue(fixture)
    try:
        with target.open('a') as output, ThreadPoolExecutor(max_workers=4) as pool:
            target.chmod(0o600)
            while time.monotonic()<deadline:
                started=time.monotonic();sample={'at':datetime.now(timezone.utc).isoformat()}
                tasks={'queue':pool.submit(api_queue.read), 'containers':pool.submit(docker_metrics)}
                for key,task in tasks.items():
                    try:sample[key]=task.result()
                    except Exception:sample[key]={'error':'Read-only sample unavailable'}
                output.write(json.dumps(sample)+'\n');output.flush()
                q=sample.get('queue',{});print(sample['at'], 'test jobs:',q.get('jobs','unavailable'),'test active:',q.get('test_active_jobs',q.get('global_active_jobs','unavailable')),
                    'oldest queued:',q.get('test_oldest_pending_seconds',q.get('global_oldest_pending_seconds','?')),'seconds',flush=True)
                if a.once:break
                time.sleep(max(0,min(a.interval-(time.monotonic()-started),deadline-time.monotonic())))
    finally:
        if api_queue:api_queue.close()
    print('Monitoring saved:',target,flush=True)
if __name__=='__main__':main()
