#!/usr/bin/env python3
"""Restore original public sandbox files. Prepare by default; --apply --publish to release.

Uses title-exact mappings in the cached course-144164 inventory. Downloads only
startercode, preserves comments/bytes, and never writes student workspaces.
Resumable state and source archives are kept privately under var/sandbox-restoration.
"""
import argparse, base64, hashlib, json, os, re, stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from zipfile import ZipFile
from download_vocareum_coding_exercises import VocareumClient
from upload_native_graders import API, private_json
ROOT=Path(__file__).resolve().parents[1]

def normalized(title):
    return re.sub('[^a-z0-9]', '', title.lower())

def archive_files(path):
    """Read a public export without extracting paths or executing teaching code."""
    files={}
    with ZipFile(path) as archive:
        for item in archive.infolist():
            if item.is_dir(): continue
            p=PurePosixPath(item.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in item.filename or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('Unsafe archive member')
            parts=list(p.parts)
            if parts[:2]==['voc','startercode']: parts=parts[2:]
            elif parts[:1]==['startercode']: parts=parts[1:]
            name='/'.join(parts)
            if not name or name in files: raise ValueError('Empty or duplicate member')
            if item.file_size>1_000_000: raise ValueError('File exceeds API limit')
            files[name]=archive.read(item)
    if not files or len(files)>100 or sum(map(len,files.values()))>2_000_000:
        raise ValueError('Empty or oversized sandbox export')
    # These never belong in a public teaching sandbox export.
    if any(PurePosixPath(p).name.lower() in {'ferb.py','phineas.py','phineas_v2.py','autograder.py'} or 'private' in PurePosixPath(p).parts for p in files):
        raise ValueError('Unexpected grading/private files; review archive manually')
    return files

def digest(raw): return hashlib.sha256(raw).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-workspaces',action='store_true',help='Read and privately snapshot existing sandbox work before preparing plans')
    parser.add_argument('--apply',action='store_true');parser.add_argument('--publish',action='store_true')
    args=parser.parse_args()
    if args.publish and not args.apply: parser.error('--publish requires --apply')
    root=ROOT/'var/sandbox-restoration';root.mkdir(parents=True,exist_ok=True);root.chmod(0o700)
    workpath=root/'existing-edited-workspaces.json'
    if args.apply and not workpath.exists() and not args.audit_workspaces:raise ValueError('Run --audit-workspaces before applying')
    existing_work=json.loads(workpath.read_text()) if workpath.exists() else []
    catalog=json.loads((ROOT/'var/api-reports/vocareum-all-parts.json').read_text())
    candidates=[]
    for path in (ROOT/'var/coding-content-repair/current').glob('part-*.json'):
        snap=json.loads(path.read_text());part=snap['part']
        if part['metadata'].get('sandbox') and not any(snap['files'].values()):
            matches=[v for v in catalog.values() if str(v['course_id'])=='144164' and normalized(v['part_name'])==normalized(part['title'])]
            if len(matches)!=1: raise ValueError('Ambiguous source mapping '+str(part['id']))
            candidates.append((part,matches[0]))
    if args.audit_workspaces:
        api=API(os.environ['TRELLIS_URL'],os.environ['TRELLIS_API_TOKEN'])
        try:
            members=[];path='/courses/1/enrollments/?page_size=100'
            while path:
                page=api.request('GET',path);members.extend(page['results'])
                path=page.get('next');path=path.removeprefix('/api/v1') if path else None
            existing_work=[]
            for member in members:
                for part,_ in candidates:
                    saved=api.request('GET',f"/enrollments/{member['id']}/workspaces/{part['id']}/")
                    if any(saved['files'].values()):
                        existing_work.append({'part_id':part['id'],'enrollment_id':member['id'],'revision_id':saved['revision_id'],'files':saved['files']})
            private_json(workpath,existing_work)
            print('Existing nonempty workspaces safely recorded:',len(existing_work),flush=True)
        finally:api.session.close()
    def download(pair):
        part,source=pair;folder=root/str(part['id']);folder.mkdir(exist_ok=True);folder.chmod(0o700)
        archive=folder/'startercode.zip'
        if not archive.exists():
            client=VocareumClient((ROOT.parent/'token.txt').read_text().strip())
            try:
                transaction=client.start_export('144164',source['assignment_id'],source['part_id'],'startercode')
                client.download(client.await_export(transaction),archive);archive.chmod(0o600)
            finally:client.session.close()
        files=archive_files(archive);py=sorted(p for p in files if p.endswith('.py'))
        if not py:raise ValueError('No Python entrypoint '+str(part['id']))
        # Exact previous entrypoint if present; otherwise unique main Python file.
        entry=part['grading'].get('entrypoint')
        if entry not in py:
            preferred={666:'IfThen-1.py',963:'AFunctionwithaReturn-1.py',1297:'UsefulStringMethods-1.py',1686:'DeclaringaClass-1.py'}
            entry=preferred.get(part['id'],py[0])
            if entry not in py:raise ValueError('Missing preferred example')
        retained=sorted({p for w in existing_work if w['part_id']==part['id'] for p,t in w['files'].items() if t and p not in files})
        for p in retained:
            if p not in {f['path'] for f in part['files'] if f['visibility']=='student'}:raise ValueError('Unexpected workspace path')
            files[p]=b''  # Keep access to pre-existing learner scratch work; never copy it into defaults.
        plan={'retained_workspace_paths':retained,'part_id':part['id'],'title':part['title'],'source':source,'entrypoint':entry,'sha256':{p:digest(b) for p,b in files.items()}}
        private_json(folder/'source.json',plan)
        print('[downloaded]',part['id'],part['title'],len(files),'files',flush=True)
        return plan
    with ThreadPoolExecutor(max_workers=3) as pool: plans=list(pool.map(download,candidates))
    private_json(root/'manifest.json',plans)
    if not args.apply:print('Prepared',len(plans),'sandboxes. No platform changes.');return
    api=API(os.environ['TRELLIS_URL'],os.environ['TRELLIS_API_TOKEN']);statepath=root/'upload-state.json'
    state=json.loads(statepath.read_text()) if statepath.exists() else {}
    try:
        for plan in plans:
            pid=plan['part_id'];folder=root/str(pid);files=archive_files(folder/'startercode.zip')
            for p in plan['retained_workspace_paths']:files[p]=b''
            assert {p:digest(b) for p,b in files.items()}==plan['sha256']
            part=api.request('GET',f'/parts/{pid}/');record=state.get(str(pid),{})
            if record.get('published'):
                verify(api,part,plan);continue
            if record.get('revision')!=part['revision_id']:
                if part['revision_id']!=part['published_revision_id'] or part['title']!=plan['title'] or not part['metadata'].get('sandbox'):
                    raise ValueError('Existing draft or changed sandbox '+str(pid))
                if float(part['grading'].get('maximum_points',0))!=0 or part['grading'].get('definition'):
                    raise ValueError('Graded content; refusing sandbox overwrite '+str(pid))
                for f in part['files']:
                    data=api.request('GET',f"/parts/{pid}/files/{quote(f['path'],safe='/')}")
                    if f['visibility']!='student' or data.get('text')!='': raise ValueError('Existing content; refusing overwrite '+str(pid))
                private_json(folder/'before.json',part)
                body={'metadata':{'sandbox':True,'workspace_mode':'sandbox','vocareum_part_id':plan['source']['part_id'],'source_course_id':'144164','sandbox_starters_restored':True},'grading':{'entrypoint':plan['entrypoint'],'maximum_points':'0'},'files':[{'path':p,'visibility':'student','content_base64':base64.b64encode(b).decode()} for p,b in files.items()]}
                part=api.request('PATCH',f'/parts/{pid}/',body,part['revision_id'])
                record={'revision':part['revision_id'],'published':False};state[str(pid)]=record;private_json(statepath,state)
            for f in list(part['files']):
                if f['path'] not in files:
                    part=api.request('DELETE',f"/parts/{pid}/files/{quote(f['path'],safe='/')}",{},part['revision_id'])
                    record['revision']=part['revision_id'];private_json(statepath,state)
            before=json.loads((folder/'before.json').read_text())
            assert part['content']==before['content']
            verify(api,part,plan)
            if args.publish:
                part=api.request('POST',f'/parts/{pid}/publish/',{},part['revision_id'])
                verify(api,part,plan);record['published']=True;private_json(statepath,state)
            print('[published]' if args.publish else '[draft]',pid,plan['title'],flush=True)
        private_json(root/'verified.json',{'sandboxes':len(plans),'files':sum(len(p['sha256']) for p in plans),'published':args.publish})
    finally:api.session.close()

def verify(api,part,plan):
    assert part['title']==plan['title'] and part['metadata']['sandbox'] and part['grading']['entrypoint']==plan['entrypoint']
    assert float(part['grading']['maximum_points'])==0
    assert {f['path'] for f in part['files']}==set(plan['sha256'])
    for f in part['files']:
        data=api.request('GET',f"/parts/{part['id']}/files/{quote(f['path'],safe='/')}")
        raw=data['text'].encode() if 'text' in data else base64.b64decode(data['content_base64'])
        assert f['visibility']=='student' and digest(raw)==plan['sha256'][f['path']]
if __name__=='__main__':main()
