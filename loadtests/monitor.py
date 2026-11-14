#!/usr/bin/env python3
"""Read-only queue and Azure metrics sampler. Outputs private JSONL for a test run."""
import argparse,json,subprocess,sys,tempfile,time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SUB='75f0c79c-0712-4558-955b-b78bfe006946'
GROUP='CoC-inst-OMSCS-RG'
PREFIX=f'/subscriptions/{SUB}/resourceGroups/{GROUP}/providers/'
RESOURCES={
 'autograder_vm':(PREFIX+'Microsoft.Compute/virtualMachines/cs1301-poc-grader-vm',['Percentage CPU','CPU Credits Remaining','Available Memory Bytes']),
 'web':(PREFIX+'Microsoft.App/containerApps/cs1301-poc-web-v2',['UsageNanoCores','WorkingSetBytes','Requests','RestartCount']),
 'postgres':(PREFIX+'Microsoft.DBforPostgreSQL/flexibleServers/cs1301-poc-db27',['cpu_percent','memory_percent','active_connections']),
}

def queue(course,azure):
    source=(ROOT/'loadtests/fixtures.py').read_text()
    code="import django,json\ndjango.setup()\nexec("+repr(source)+")\nprint('TRELLIS_QUEUE:'+json.dumps(queue_snapshot("+str(course)+")),flush=True)\n"
    with tempfile.TemporaryDirectory() as temp:
        file=Path(temp)/'queue.py';file.write_text(code)
        cmd=[sys.executable,str(ROOT/'scripts/azure-private-exec.py'),'--python-file',str(file)] if azure else [sys.executable,str(file)]
        r=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=70)
    if r.returncode or 'TRELLIS_QUEUE:' not in r.stdout:raise RuntimeError('Queue snapshot unavailable')
    return json.loads(r.stdout.split('TRELLIS_QUEUE:',1)[1].splitlines()[0])


def azure_metrics(pair):
    resource,names=pair
    start=(datetime.now(timezone.utc)-timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
    r=subprocess.run(['az','monitor','metrics','list','--resource',resource,'--metric',*names,
        '--start-time',start,'--interval','PT1M','--aggregation','Average','Maximum','--only-show-errors','-o','json'],capture_output=True,text=True,timeout=30)
    if r.returncode:return {'error':'Azure metrics unavailable (permissions or unsupported metric).'}
    result={}
    for metric in json.loads(r.stdout).get('value',[]):
        series=[]
        for item in metric.get('timeseries',[]):
            values=[v for v in item.get('data',[]) if v.get('average') is not None or v.get('maximum') is not None]
            series.append({'dimensions':item.get('metadatavalues',[]),'points':values})
        result[metric['name']['value']]={'unit':metric.get('unit'),'series':series}
    return result


class ApiQueue:
    """Course-scoped REST sampling; avoids Azure exec's control-plane throttles."""
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
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixture',type=Path,required=True);p.add_argument('--azure',action='store_true')
    p.add_argument('--duration',type=int,default=420);p.add_argument('--interval',type=int,default=30);p.add_argument('--once',action='store_true');a=p.parse_args()
    if a.interval<15 or not 1<=a.duration<=900:raise ValueError('Use interval >=15s and duration 1–900s.')
    fixture=json.loads(a.fixture.read_text());target=a.fixture.parent/'monitor.jsonl'
    deadline=time.monotonic()+a.duration
    api_queue=ApiQueue(fixture) if a.azure else None
    try:
        with target.open('a') as output, ThreadPoolExecutor(max_workers=4) as pool:
            target.chmod(0o600)
            while time.monotonic()<deadline:
                started=time.monotonic();sample={'at':datetime.now(timezone.utc).isoformat()}
                tasks={'queue':pool.submit(api_queue.read) if api_queue else pool.submit(queue,fixture['course_id'],False)}
                if a.azure:tasks.update({key:pool.submit(azure_metrics,pair) for key,pair in RESOURCES.items()})
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
