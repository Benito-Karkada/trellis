#!/usr/bin/env python3
"""Export synthetic student grades/review metrics and a compact load-test report."""
import argparse,csv,html,json
from decimal import Decimal
from datetime import datetime,timezone,timedelta
from pathlib import Path
import requests


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixture',required=True,type=Path);a=p.parse_args()
    f=json.loads(a.fixture.read_text());folder=a.fixture.parent;s=requests.Session();s.trust_env=False;base=f['url']
    def call(method,path,body=None):
        r=s.request(method,base+path,json=body,headers={'Referer':base+'/','X-CSRFToken':s.cookies.get('csrftoken','')},timeout=45);r.raise_for_status();return r.json()
    try:
        credentials=f.get('staff') or json.loads((Path(__file__).resolve().parents[1]/f['staff_credentials_file']).read_text())
        call('GET','/api/session/');call('POST','/api/auth/login/',{k:credentials[k] for k in ('email','password')})
        grades=call('GET','/api/gradebook/');review=call('GET','/api/settings/submission-review/?search=loadtest-'+f['run_id'])
        permitted={a['email'] for a in f['accounts']}
        grades['students']=[r for r in grades['students'] if r['email'] in permitted]
        review['results']=[r for r in review['results'] if r['email'] in permitted]
        assert len(grades['students'])==len(permitted)==len(review['results'])
        assert grades['course']==f.get('expected_title','Trellis load test '+f['run_id'])
        tokens=call('GET','/api/settings/api-tokens/')['tokens']
        assert all(t['revoked_at'] for t in tokens if t['name']=='Synthetic load-test monitor'), 'Monitoring token is still active.'
        issued=call('POST','/api/settings/api-tokens/',{'name':'Load-test report '+f['run_id'],'scopes':['submissions:read'],'expires_in_days':1})
        jobs=[]
        try:
            path=f"/api/v1/courses/{f['course_id']}/execution-jobs/?limit=200"
            if f.get('enrollment_ids'):path+='&enrollment_ids='+','.join(map(str,f['enrollment_ids']))
            while path:
                response=s.get(base+path,headers={'Authorization':'Bearer '+issued['token']},timeout=45);response.raise_for_status()
                page=response.json()
                for job in page['results']:
                    row={k:job[k] for k in ('id','user_id','part_id','operation','status','submitted_at','claimed_at','completed_at')}
                    row.update({k:job.get('result',{}).get(k) for k in ('passed','score','maximum','practice')});jobs.append(row)
                path=page.get('next')
        finally:call('POST',f"/api/settings/api-tokens/{issued['id']}/revoke/",{})
        for name,data in [('grades.json',grades),('submission-review.json',review),('execution-jobs.json',jobs)]:
            file=folder/name;file.write_text(json.dumps(data,indent=2));file.chmod(0o600)
    finally:
        try:call('POST','/api/auth/logout/',{})
        except Exception:pass
        s.close()
    metadata=json.loads((folder/'run-metadata.json').read_text()) if (folder/'run-metadata.json').exists() else {'users':len(f['accounts']),'minutes':5}
    stats=list(csv.DictReader((folder/'locust_stats.csv').open()))
    samples=[json.loads(line) for line in (folder/'monitor.jsonl').read_text().splitlines()]
    http_rows=[r for r in stats if r['Type'] not in {'','WORKFLOW','CHECK'}]
    def find(name):return next((r for r in stats if r['Name']==name),{})
    container_samples=[{'at':s['at'],'containers':s['containers']} for s in samples if isinstance(s.get('containers'),list)]
    queue_samples=[s['queue'] for s in samples if 'jobs' in s.get('queue',{})]
    students=[];reviews={r['email']:r for r in review['results']}
    tested_lessons={f['lesson_id'],f['native'].get('lesson_id',f['lesson_id']),f['reading'].get('lesson_id',f['lesson_id'])}|{w.get('lesson_id',f['lesson_id']) for w in f.get('workloads',[])}
    for row in grades['students']:
        selected={k:v for k,v in row['assignments'].items() if int(k) in tested_lessons}
        assignment={'earned':str(sum((Decimal(v['earned']) for v in selected.values()),Decimal(0))), 'maximum':str(sum((Decimal(v['maximum']) for v in selected.values()),Decimal(0))), 'completed_parts':sum(v['completed_parts'] for v in selected.values())};r=reviews[row['email']]
        students.append({'email':row['email'],'earned':assignment['earned'],'maximum':assignment['maximum'],
            'completed_parts':assignment['completed_parts'],'assignment_scores':selected,'review_index':r['index'],'components':r['components'],'reasons':r['reasons'],
            'runs':r['runs'],'submits':r['submits'],'focus_changes':r['focus_changes']})
    burst_waves=[]
    if metadata.get('profile')=='burst':
        from collections import defaultdict
        started=datetime.fromisoformat(metadata['started_at']);groups=defaultdict(list)
        for job in jobs:
            arrival=datetime.fromisoformat(job['submitted_at'].replace('Z','+00:00'))
            offset=(arrival-started).total_seconds()
            if offset<0:continue
            slot=max(0,round((offset-35)/90));groups[slot].append((arrival,job))
        for slot,group in sorted(groups.items()):
            arrivals=[x[0] for x in group]
            waits=sorted((datetime.fromisoformat(j['claimed_at'].replace('Z','+00:00'))-at).total_seconds() for at,j in group if j['claimed_at'])
            burst_waves.append({'wave':slot+1,'requests':len(group),'run':sum(j['operation']=='run' for _,j in group),
                'submit':sum(j['operation']=='submit' for _,j in group),'arrival_spread_seconds':round((max(arrivals)-min(arrivals)).total_seconds(),3),
                'max_queue_wait_seconds':round(max(waits),3) if waits else None,'completed':sum(j['status']=='completed' for _,j in group)})
    summary={'run_id':f['run_id'],'created_at':datetime.now(timezone.utc).isoformat(),'users':metadata['users'],'requested_minutes':metadata['minutes'],'preflight_execution_jobs':f.get('preflight_jobs',0),
        'profile':metadata.get('profile','mixed'),'live_course':f.get('live_course',False),'burst_waves':burst_waves,'outline_parts':f['copied_parts'],'http_requests':sum(int(r['Request Count']) for r in http_rows),
        'http_failures':sum(int(r['Failure Count']) for r in http_rows),'workflow_checks':{name:find(name) for name in ('run end-to-end','submit end-to-end')},
        'course_outline':find('course outline'),'container_metrics':container_samples,
        'last_queue_snapshot':queue_samples[-1] if queue_samples else None,
        'monitoring_tokens_revoked':True,'post_run_focus_check':f.get('post_run_focus_check'),'queue_sample_errors':sum('error' in s.get('queue',{}) for s in samples),'students':students}
    path=folder/'summary.json';path.write_text(json.dumps(summary,indent=2));path.chmod(0o600)
    esc=html.escape
    rows=''.join(f"<tr><td>{esc(r['email'])}</td><td>{r['earned']} / {r['maximum']}</td><td>{r['runs']}</td><td>{r['submits']}</td><td>{esc(str(r['review_index']))}</td><td>{r['focus_changes']}</td></tr>" for r in students)
    timing=''.join(f"<tr><td>{esc(r['Name'])}</td><td>{r['Request Count']}</td><td>{r['Failure Count']}</td><td>{float(r['50%']):,.0f} ms</td><td>{float(r['95%']):,.0f} ms</td><td>{float(r['Max Response Time']):,.0f} ms</td></tr>" for r in stats if r['Type'])
    focus_note='The original timed run omitted the initial away event; a separate post-run check verified one complete focus episode.' if f.get('post_run_focus_check') else 'Complete away/hidden/back focus episodes are included in this run.'
    workload_note=', '.join(str(w['case_count'])+'-case '+w['name'] for w in f.get('workloads',[])) or 'one synthetic three-case Python grader'
    course_note='actual CS 1301 course' if f.get('live_course') else 'isolated synthetic course'
    burst_html=('''<h2>Simultaneous arrival waves</h2><pre>'''+esc(json.dumps(burst_waves,indent=2))+'''</pre>''') if burst_waves else ''
    document=f'''<!doctype html><html><meta charset="utf-8"><title>Trellis load test</title><style>
    body{{font:15px system-ui;color:#233744;background:#f3f6f8;max-width:1200px;margin:40px auto;padding:0 24px}}h1{{font-size:32px}}h2{{margin-top:32px}}table{{width:100%;border-collapse:collapse;background:white;border-radius:10px}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #e2e9ed}}pre{{white-space:pre-wrap;background:white;padding:20px}}.cards{{display:flex;gap:20px}}.cards div{{background:white;padding:20px;flex:1;border-radius:12px}}strong{{display:block;font-size:26px}}</style>
    <h1>Trellis · {metadata["users"]}-student load test</h1><p>{esc(f['run_id'])} · {metadata["minutes"]}-minute paced HTTP simulation · {f['copied_parts']:,} outline parts · {course_note}</p>
    <div class="cards"><div>HTTP requests<strong>{summary['http_requests']:,}</strong></div><div>HTTP failures<strong>{summary['http_failures']}</strong></div><div>Simulated students<strong>{len(students)}</strong></div></div>
    <h2>Request and grading latency</h2><table><tr><th>Operation</th><th>Count</th><th>Failed</th><th>Median</th><th>95th percentile</th><th>Maximum</th></tr>{timing}</table>
    {burst_html}
    <h2>Synthetic students</h2><p>Review indices reflect scripted behavior; they are not evidence of AI use. Only selected parts were attempted; totals include all parts of each visited assignment. Full component values and reasons are in submission-review.json. {focus_note}</p><table><tr><th>Test account</th><th>Tested assignment totals</th><th>Runs</th><th>Submits</th><th>Review index</th><th>Focus events</th></tr>{rows}</table>
    <h2>Queue snapshot</h2><p>Includes {f.get("preflight_jobs",0)} preflight execution jobs before the timed Locust run.</p><pre>{esc(json.dumps(summary['last_queue_snapshot'],indent=2))}</pre>
    <h2>Local container metrics</h2><p>Docker CPU and memory snapshots for this checkout's services. The host execution worker is monitored separately in its terminal.</p><pre>{esc(json.dumps(container_samples,indent=2))}</pre>
    <h2>Scope and limits</h2><p>This tests API traffic and these workloads: {esc(workload_note)}. It does not render React/Monaco, stream Kaltura, test every grader, validate exam/proctoring flows, or exercise Canvas. It cannot establish capacity for a full class. Only tagged synthetic accounts generated load. Existing student records and course content are excluded from cleanup. Use only disposable local demo data.</p>
    <p>Locust charts: <a href="locust.html">open full report</a>. Raw metrics: monitor.jsonl. Queue sampler gaps: {summary['queue_sample_errors']}.</p></html>'''
    (folder/'report.html').write_text(document)
    print('HTTP requests:',summary['http_requests'],'failures:',summary['http_failures'])
    print('Synthetic student grades and review metrics saved for',len(students),'students.')
    print('Report:',folder/'report.html')
if __name__=='__main__':main()
