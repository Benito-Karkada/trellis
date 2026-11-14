#!/usr/bin/env python3
"""Remove a final ASCII hyphen from course part titles through the staff API.

Set TRELLIS_URL and TRELLIS_API_TOKEN (course:read, content:read, content:write).
Default is a read-only plan; --apply writes guarded batches and verifies the result.
"""
import argparse,json,os
from pathlib import Path
from upload_native_graders import API,private_json
ROOT=Path(__file__).resolve().parents[1]

def pages(api,path):
    rows=[]
    while path:
        data=api.request('GET',path);rows.extend(data['results'])
        path=data.get('next');path=path.removeprefix('/api/v1') if path else None
    return rows

def parts(api,course):
    rows=[]
    for assignment in pages(api,f'/courses/{course}/assignments/?limit=200'):
        rows.extend(pages(api,f"/assignments/{assignment['id']}/parts/?limit=200"))
    return rows

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course',type=int,default=1);parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();root=ROOT/'var/title-hyphen-cleanup';root.mkdir(parents=True,exist_ok=True);root.chmod(0o700)
    api=API(os.environ['TRELLIS_URL'],os.environ['TRELLIS_API_TOKEN'])
    try:
        original=parts(api,args.course)
        updates=[{'id':p['id'],'expected_title':p['title'],'title':p['title'][:-1].rstrip()}
                 for p in original if p['title'].endswith('-') and p['title'][:-1].strip()]
        private_json(root/'plan.json',{'course_id':args.course,'updates':updates})
        print('Scanned',len(original),'parts;',len(updates),'titles end in a hyphen.',flush=True)
        if not args.apply:return
        applied=[]
        for start in range(0,len(updates),500):
            batch=updates[start:start+500]
            result=api.request('PATCH',f'/courses/{args.course}/parts/titles/',{'updates':batch})
            assert result['updated']==len(batch)
            applied.extend(batch);private_json(root/'applied.json',applied)
            print('Updated',len(applied),'of',len(updates),'titles.',flush=True)
        current={p['id']:p['title'] for p in parts(api,args.course)}
        for update in applied:assert current.get(update['id'])==update['title'],f"Title verification failed: {update['id']}"
        # Confirm all other titles in the initial inventory were left alone.
        changed={u['id'] for u in applied}
        untouched=sum(p['id'] in current and current[p['id']]==p['title'] for p in original if p['id'] not in changed)
        private_json(root/'result.json',{'status':'complete','course_id':args.course,'updated':len(applied),'verified':len(applied),'other_titles_unchanged':untouched})
        print('Complete:',len(applied),'titles cleaned and verified;',untouched,'other titles unchanged.',flush=True)
    finally:api.session.close()
if __name__=='__main__':main()
