"""Prepare/review a type-check exercise and publish its repair to the Azure POC.

Original archives and XML stay unchanged. A new immutable revision preserves
instructions, maximum points, files, and previous student workspace snapshots.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runner"))
from grading.manifest import load_definition
from prepare_programming_quizzes import variable_type_definition


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--part-id', required=True)
    parser.add_argument('--source',type=Path,default=ROOT/'var/vocareum-coding-archives')
    parser.add_argument('--fix-sample-boolean-typo',action='store_true')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--credentials',type=Path,default=ROOT/'var/azure-poc/login-details.json')
    args=parser.parse_args()
    matches=list(args.source.glob('exercises/*/*--'+args.part_id+'/manifest.json'))
    if len(matches)!=1:raise ValueError('Expected one downloaded part')
    folder=matches[0].parent
    definition=variable_type_definition(ast.parse((folder/'private/Ferb.py').read_text()))
    if definition is None:raise ValueError('This archive does not match the supported type-check pattern')
    load_definition(definition)
    payload={'part':args.part_id,'definition':definition}
    if args.fix_sample_boolean_typo:
        sample=folder/'private/sample_answer_1.py'
        text=sample.read_text()
        if text.count('print(type(my_bool))')!=1 or 'my_boolean = ' not in text:
            raise ValueError('Sample does not match the reviewed typo; refusing to alter it')
        corrected=text.replace('print(type(my_bool))','print(type(my_boolean))')
        ast.parse(corrected)
        payload['sample_fix']={'path':'solutions/sample_answer_1.py','text':corrected,
                              'sha256':hashlib.sha256(sample.read_bytes()).hexdigest()}
    print(f'Prepared {len(definition["cases"])} native checks. Original archive preserved.',flush=True)
    if not args.apply:
        print('Dry run. Use --apply to publish a new revision to the Azure POC.')
        return
    # Use the same authenticated authoring APIs as the browser. No database
    # bypass, legacy execution or Azure exec permission is needed to publish.
    credentials=json.loads(args.credentials.read_text())
    base=credentials['url'].rstrip('/')
    session=requests.Session()
    def get(path):
        response=session.get(base+path,timeout=30)
        response.raise_for_status()
        return response.json()
    def post(path,data):
        response=session.post(base+path,json=data,headers={
            'X-CSRFToken':session.cookies.get('csrftoken',''),'Referer':base+'/'},timeout=60)
        response.raise_for_status()
        return response.json()
    try:
        get('/api/session/')
        post('/api/auth/login/',{'email':credentials['email'],'password':credentials['password']})
        activities=[a for lesson in get('/api/outline/')['lessons'] for a in lesson['activities']
                    if str(a['metadata'].get('vocareum_part_id'))==args.part_id]
        assert len(activities)==1,'Expected exactly one matching live exercise'
        activity=activities[0]
        config=get(f"/api/studio/{activity['id']}/?mode=config")
        if config['grading'].get('definition')==definition and not config['grading'].get('review_required'):
            print('Native grading repair already published.')
            return
        assert config['revision']==config['published_revision'],'A newer staff draft exists; review it first'
        grading={**config['grading'],'definition':definition,'review_required':False}
        grading['migration_review']={'method':'native_variable_type_checks','resolved_warning':grading.pop('import_warning',None)}
        files=[]
        fixed=False
        for file in config['files']:
            if file['path'] in {'grader/import-review.json','grader/tests.json'}:continue
            text=get(f"/api/files/{file['id']}/?mode=config")['text']
            fix=payload.get('sample_fix')
            if fix and file['path']==fix['path']:
                assert hashlib.sha256(text.encode()).hexdigest()==fix['sha256'],'Staff sample was edited; review it first'
                text=fix['text'];fixed=True
            files.append({'path':file['path'],'text':text})
        assert not payload.get('sample_fix') or fixed,'Reviewed sample was not found'
        files.append({'path':'grader/tests.json','text':json.dumps(definition,indent=2)+'\n'})
        saved=post(f"/api/studio/{activity['id']}/edit/",{'base_revision':config['revision'],
            'content':config['content'],'grading':grading,'files':files})
        post(f"/api/studio/{activity['id']}/edit/",{'base_revision':saved['revision'],'action':'publish'})
        print('Published native grading revision '+str(saved['revision'])+'; maximum points preserved: '+str(grading['maximum_points']),flush=True)
    finally:
        try:post('/api/auth/logout/',{})
        finally:session.close()
    return


if __name__=='__main__':main()
