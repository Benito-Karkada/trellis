#!/usr/bin/env python3
"""Import Run-only example plans through the staff API. Default is read-only.

Set TRELLIS_URL and TRELLIS_API_TOKEN. --apply creates drafts and verifies Run;
--apply --publish publishes only successful runs. Generated content stays in var/.
"""
import argparse,json,os,time
from pathlib import Path
from upload_native_graders import API,private_json
ROOT=Path(__file__).resolve().parents[1]
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plans',type=Path,default=ROOT/'var/native-example-imports');parser.add_argument('--url',default=os.environ.get('TRELLIS_URL',''));parser.add_argument('--apply',action='store_true');parser.add_argument('--publish',action='store_true');args=parser.parse_args()
 if args.publish and not args.apply:parser.error('--publish requires --apply')
 api=API(args.url,os.environ.get('TRELLIS_API_TOKEN',''));statepath=args.plans/'upload-state.json';state=json.loads(statepath.read_text()) if statepath.exists() else {}
 try:
  for item in json.loads((args.plans/'manifest.json').read_text()):
   plan=json.loads((args.plans/item['file']).read_text());pid=plan['part_id'];part=api.request('GET',f'/parts/{pid}/');record=state.get(str(pid),{})
   if record.get('published'):print('[already published]',pid);continue
   own=record.get('revision')==part['revision_id']
   if not own and (part['revision_id']!=part['published_revision_id'] or part['files']):raise RuntimeError('A draft/files already exist; review before importing '+str(pid))
   if part['title']!=plan['title']:raise RuntimeError('Source title mismatch: '+str(pid))
   if not args.apply:print('[planned]',pid,plan['title']);continue
   if not own:
    body={'metadata':{'sandbox':True,'workspace_mode':'sandbox','placeholder':False,'vocareum_part_id':plan['vocareum_part_id'],'source_course_id':plan['course_id'],'archive_import':'run_only'},'content':plan['content'],'grading':{'maximum_points':'0','entrypoint':plan['entrypoint'],'placeholder':False,'review_required':False,'definition':None},'files':[{'path':path,'visibility':'student','text':text} for path,text in plan['files'].items()]}
    part=api.request('PATCH',f'/parts/{pid}/',body,part['revision_id']);record={'revision':part['revision_id'],'published':False};state[str(pid)]=record;private_json(statepath,state)
   if not record.get('verified'):
    job=api.request('POST',f'/parts/{pid}/test-runs/',{'operation':'run','files':plan['files']},record['revision']);deadline=time.monotonic()+600
    while True:
     outcome=api.request('GET',f"/test-runs/{job['id']}/")
     if outcome['status'] in {'completed','failed'}:break
     if time.monotonic()>deadline:raise RuntimeError('Run verification timed out.')
     time.sleep(2)
    if outcome['status']!='completed' or outcome['result'].get('execution_status')!='ok':raise RuntimeError('Run failed for '+str(pid))
    record['verified']=True;private_json(statepath,state)
   if args.publish:api.request('POST',f'/parts/{pid}/publish/',{},record['revision']);record['published']=True;private_json(statepath,state)
   print('[published]' if record.get('published') else '[verified draft]',pid,plan['title'],flush=True)
 finally:api.session.close()
if __name__=='__main__':main()
