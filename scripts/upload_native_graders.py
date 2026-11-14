#!/usr/bin/env python3
"""Validate, upload, test, and optionally publish native Trellis grader bundles.

Default: read-only plan. --apply writes drafts and runs staff-copy tests.
--apply --publish publishes only bundles whose positive/negative tests pass.
Reads TRELLIS_URL and TRELLIS_API_TOKEN; never reads or uploads Ferb source.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote, urlsplit
import uuid

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runner'))
from grading.manifest import load_definition


class APIError(RuntimeError):
    pass


class Pending(APIError):
    pass


class JobFailed(APIError):
    pass


class API:
    def __init__(self, url, token):
        parsed = urlsplit(url)
        if not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.path not in {'', '/'}:
            raise ValueError('TRELLIS_URL must be the site origin, without credentials or an API path.')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'localhost','127.0.0.1'}):
            raise ValueError('Use HTTPS except for local development.')
        if not token:
            raise ValueError('Set TRELLIS_API_TOKEN to a staff token.')
        self.url = url.rstrip('/')
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers['Authorization'] = 'Bearer ' + token

    def request(self, method, path, body=None, revision=None, key=None):
        headers = {}
        if revision is not None: headers['If-Match'] = f'"{revision}"'
        if method != 'GET': headers['Idempotency-Key'] = key or str(uuid.uuid4())
        for attempt in range(5):
            try:
                response = self.session.request(method, self.url+'/api/v1'+path, json=body,
                                                headers=headers, timeout=60, allow_redirects=False)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 4: raise APIError('Connection failed; rerun with the same state file to resume.') from None
                time.sleep(min(2**attempt, 10)); continue
            if response.status_code in {429,502,503,504} and attempt < 4:
                delay = response.headers.get('Retry-After','')
                time.sleep(min(float(delay),30) if delay.isdigit() else min(2**attempt,10))
                continue
            try: data = response.json()
            except ValueError: raise APIError(f'HTTP {response.status_code}: expected a JSON API response.') from None
            if not response.ok:
                error = data.get('error',{})
                message = error.get('message','Request rejected.') if isinstance(error,dict) else 'Request rejected.'
                raise APIError(f'HTTP {response.status_code}: {message}')
            return data
        raise APIError('Request did not complete.')


def private_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    with open(temporary,'w',opener=lambda name, flags: os.open(name,flags,0o600)) as stream:
        json.dump(value,stream,indent=2);stream.write('\n')
    temporary.chmod(0o600);temporary.replace(path)


def artifact(root, value):
    if not isinstance(value,str):raise ValueError('Artifact paths must be relative strings.')
    path=(root/value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():raise ValueError('Bundle artifact is missing or outside its folder.')
    return path


def bundle_digest(row, definition, positive, negatives, reference=None):
    data={"part_id":row["part_id"],"assignment_id":row["assignment_id"],
        "entrypoint":row["entrypoint"],"definition":definition,"positive":positive,"negatives":negatives}
    if reference is not None:data["reference_source"]=reference
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def load_bundle(root, row):
    if type(row.get('part_id')) is not int or type(row.get('assignment_id')) is not int:
        raise ValueError('Use integer Trellis part_id and assignment_id values.')
    definition=json.loads(artifact(root,row['definition']).read_text())
    load_definition(definition)
    if not isinstance(row.get('entrypoint'),str) or not row['entrypoint'].endswith('.py'):
        raise ValueError('Choose an existing Python entrypoint.')
    validation=row.get('validation',{})
    if validation.get('status')!='passed':raise ValueError('Bundle has not passed local conversion validation.')
    positive=artifact(root,validation['positive']).read_text()
    negatives=[artifact(root,p).read_text() for p in validation.get('negatives',[])]
    if not negatives:raise ValueError('At least one deliberately incorrect solution is required.')
    reference=artifact(root,row.get('reference')).read_text() if definition.get('random_cases') else None
    digest=bundle_digest(row,definition,positive,negatives,reference)
    if validation.get('bundle_sha256')!=digest:raise ValueError('Bundle changed since validation; revalidate it first.')
    return definition,positive,negatives,digest,reference


def identity(part, row, course):
    if part['course_id']!=course or part['assignment_id']!=row['assignment_id'] or part['kind']!='coding':
        raise ValueError('Course/assignment/part identity does not match the bundle.')
    actual=part.get('metadata',{}).get('vocareum_part_id') or part.get('grading',{}).get('vocareum_part_id')
    if str(actual)!=str(row.get('vocareum_part_id')):
        raise ValueError('Vocareum source reference does not match the target part.')
    if part.get('metadata',{}).get('sandbox'):
        raise ValueError('Do not install graded tests in a sandbox.')


def public_workspace(api, part):
    files={}
    for item in part['files']:
        if item['visibility']!='student':continue
        data=api.request('GET',f"/parts/{part['id']}/files/{quote(item['path'],safe='/')}")
        if 'text' not in data:raise ValueError('A public binary file needs a separate execution-fixture review.')
        files[item['path']]=data['text']
    return files


def test_job(api, part_id, revision, files, key, old_job=None, timeout=600):
    job_id=old_job
    if not job_id:
        job=api.request('POST',f'/parts/{part_id}/test-runs/',{'operation':'submit','files':files},revision,key)
        job_id=job['id']
    return job_id


def poll_job(api, job_id, timeout):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        job=api.request('GET',f'/test-runs/{job_id}/')
        if job['status']=='failed':raise JobFailed('Isolated test execution failed; no learner grade was changed.')
        if job['status']=='completed':return job['result']
        time.sleep(2)
    raise Pending('Test is still pending. Rerun with the same state file to keep waiting.')


def process(api, root, row, state, save, args):
    definition,positive,negatives,digest,reference=load_bundle(root,row)
    pid=row['part_id'];part=api.request('GET',f'/parts/{pid}/');identity(part,row,args.course)
    previous=state['parts'].get(str(pid))
    if previous and previous.get('digest')!=digest:
        if not args.retry_failed or previous.get('phase')!='failed' or part['revision_id']!=previous.get('revision_id'):
            raise ValueError('Bundle/state differs. Review the existing draft; use --retry-failed only for a failed draft owned by this batch.')
        previous={'base_revision':part['revision_id'],'revision_id':part['revision_id']}
    if previous and previous.get('publish_key') and part['published_revision_id']==previous.get('revision_id'):
        if args.apply:
            previous['phase']='published';save()
        return 'already_published'
    if previous and previous.get('phase')=='published':
        return 'already_published'
    own=previous and part['revision_id']==previous.get('revision_id')
    in_flight=previous and previous.get('phase')=='uploading'
    expected=row.get('expected_revision_id')
    if part['published_revision_id']!=expected:
        raise ValueError('Published revision changed since the bundle was prepared; review and refresh the bundle baseline.')
    if part['revision_id']!=part['published_revision_id'] and not own and not in_flight:
        raise ValueError('Another draft already exists; it will not be overwritten.')
    grading=part.get('grading',{})
    if grading.get('definition') and not grading.get('review_required') and not own and not in_flight and not args.replace_existing:
        return 'already_has_grader'
    if not any(f['path']==row['entrypoint'] and f['visibility']=='student' for f in part['files']):
        raise ValueError('Entrypoint is not a public file on the target part.')
    if not args.apply:return 'planned'
    record=previous or {}
    record.setdefault('base_revision',part['revision_id']);record.setdefault('upload_key',str(uuid.uuid4()))
    record.update(digest=digest,title=row.get('title',''))
    state['parts'][str(pid)]=record
    if record.get('phase') not in {'testing','verified'}:
        if record.get('phase')=='failed' and not args.retry_failed:raise ValueError('Prior verification failed. Review the bundle before --retry-failed.')
        if record.get('phase')=='failed':
            record.update(base_revision=record['revision_id'],upload_key=str(uuid.uuid4()));record.pop('tests',None)
        record['phase']='uploading';save()
        payload={'definition':definition,'entrypoint':row['entrypoint'],'mark_reviewed':True}
        if reference is not None:payload['reference_source']=reference
        uploaded=api.request('PUT',f'/parts/{pid}/grader/',payload,record['base_revision'],record['upload_key'])
        record.update(revision_id=uploaded['revision_id'],phase='testing');save()
        print(f'[draft uploaded] {pid} revision {record["revision_id"]}',flush=True)
    part=api.request('GET',f'/parts/{pid}/');identity(part,row,args.course)
    if part['revision_id']!=record['revision_id'] or part['published_revision_id']!=expected:
        raise ValueError('The target changed during this batch. Its newer changes will not be published.')
    if record['phase']!='verified':
        baseline=public_workspace(api,part)
        fixtures=[('correct',positive,True)]+[(f'incorrect-{i}',source,False) for i,source in enumerate(negatives,1)]
        for name,source,expected_pass in fixtures:
            item=record.setdefault('tests',{}).setdefault(name,{'key':str(uuid.uuid4())});save()
            if 'passed' not in item:
                files={**baseline,row['entrypoint']:source}
                item['job_id']=test_job(api,pid,record['revision_id'],files,item['key'],item.get('job_id'));save()
                try:result=poll_job(api,item['job_id'],args.wait)
                except JobFailed:
                    record['phase']='failed';save();raise
                if result.get('passed') is not expected_pass:
                    record['phase']='failed';save()
                    raise ValueError(f'{name} validation returned the wrong verdict; draft kept unpublished.')
                item['passed']=True;save()
                print(f'[test passed] {pid} {name}',flush=True)
        record['phase']='verified';save()
    if args.publish:
        # The API enforces If-Match again; no later draft can be published by accident.
        record.setdefault('publish_key',str(uuid.uuid4()));save()
        api.request('POST',f'/parts/{pid}/publish/',{},record['revision_id'],record['publish_key'])
        record['phase']='published';save();return 'published'
    return 'verified_draft'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--course',type=int,required=True,help='Trellis course ID, not a Vocareum course ID')
    parser.add_argument('--url',default=os.environ.get('TRELLIS_URL',''))
    parser.add_argument('--check',action='store_true',help='Validate bundle artifacts offline without a token or API calls')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--retry-failed',action='store_true')
    parser.add_argument('--replace-existing',action='store_true')
    parser.add_argument('--show-skipped',action='store_true',help='Print every unresolved conversion instead of only summary counts')
    parser.add_argument('--part',type=int,action='append',help='Limit to one part ID; repeatable')
    parser.add_argument('--state',type=Path)
    parser.add_argument('--wait',type=int,default=600)
    args=parser.parse_args()
    if args.publish and not args.apply:parser.error('--publish also requires --apply')
    if args.wait<1:parser.error('--wait must be positive')
    bundle=json.loads(args.manifest.read_text())
    if bundle.get('version')!=1 or bundle.get('course_id')!=args.course or not isinstance(bundle.get('parts'),list):
        parser.error('Manifest version/course/parts is invalid.')
    if args.check:
        if args.apply or args.publish:parser.error('--check cannot write or publish')
        count=0
        for row in bundle['parts']:
            if row.get('status')=='ready' and (not args.part or row['part_id'] in args.part):
                load_bundle(args.manifest.parent,row);count+=1
        print(f'{count} ready bundles validated offline. No API calls or uploads made.')
        return 0
    api=API(args.url,os.environ.get('TRELLIS_API_TOKEN',''))
    course=api.request('GET',f'/courses/{args.course}/')
    if course['id']!=args.course:raise ValueError('The token targets a different course.')
    state_path=args.state or args.manifest.with_name('upload-state.json')
    lock=None
    if args.apply:
        lock=state_path.with_suffix('.lock').open('w')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        state=json.loads(state_path.read_text()) if state_path.exists() else {'version':1,'origin':api.url,'course_id':args.course,'parts':{}}
        if state.get('origin')!=api.url or state.get('course_id')!=args.course:raise ValueError('State belongs to a different site/course.')
        def save():private_json(state_path,state)
        counts={};results=[]
        seen=set()
        for row in bundle['parts']:
            pid=row.get('part_id')
            if pid in seen:raise ValueError('Manifest contains duplicate part IDs.')
            seen.add(pid)
            if args.part and pid not in args.part:continue
            if row.get('status')!='ready':
                status={'unmapped':'unmapped','run_only':'not_graded','retired':'retired'}.get(row.get('status'),'needs_review');message=row.get('reason','Not ready for upload.')
            else:
                print(f'[checking] {pid} {row.get("title","")}',flush=True)
                try:status=process(api,args.manifest.parent,row,state,save,args);message=''
                except (ValueError,APIError,OSError) as exc:status='error';message=str(exc)
            counts[status]=counts.get(status,0)+1
            results.append({'part_id':pid,'status':status,'message':message})
            if status not in {'needs_review','unmapped'} or args.show_skipped:
                print(f'[{status}] {pid} {row.get("title","")}' + (f': {message}' if message else ''),flush=True)
        if args.apply:private_json(state_path.with_name(state_path.stem+'-report.json'),{'summary':counts,'parts':results})
        print(json.dumps(counts,sort_keys=True),flush=True)
        return 1 if counts.get('error') else 0
    finally:
        api.session.close()
        if lock:lock.close()


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,APIError,OSError) as exc:raise SystemExit(str(exc)) from None
