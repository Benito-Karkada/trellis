#!/usr/bin/env python3
"""Plan fixes from current API snapshots and preserved original starter sources.

Use clean_coding_instructions.py --root <repair-root> --apply to publish the
reviewable plan with revision/hash guards. Never touches learner workspaces.
"""
import argparse,ast,copy,hashlib,io,json,re,sys,tokenize
from pathlib import Path
from clean_coding_instructions import clean_source,ROOT
from upload_native_graders import private_json
from core.coding_content import clean_prompt,local_test_lines
from core.schema import validate_content


def code_signature(source):
    try:return ast.dump(ast.parse(source),include_attributes=False)
    except (SyntaxError,ValueError):
        tokens=[]
        try:
            for t in tokenize.generate_tokens(io.StringIO(source).readline):
                if t.type not in {tokenize.COMMENT,tokenize.NL,tokenize.ENDMARKER}:tokens.append((t.type,t.string))
        except (tokenize.TokenError,IndentationError):pass
        return repr(tokens)


def repair(current,original):
    part=current['part'];content=copy.deepcopy(part['content']);seen=set()
    for block in content['blocks']:
        if block['type']=='coding':block['prompt']=clean_prompt(block['prompt'],seen)
    files=[];restored=0;test_calls=0
    required=[r['target'] for r in (part['grading'].get('definition') or {}).get('requirements',[]) if r['kind']=='require_comment']
    for path,existing in current['files'].items():
        source=original['files'].get(path)
        if source is None:continue
        if code_signature(existing)!=code_signature(source):raise ValueError(f'{path}: executable defaults changed since the original snapshot; staff edits preserved.')
        cleaned,_,_=clean_source(source,required)
        cleaned=re.sub(r'#If your (?:function|code) works correctly, this will originally', '#These local tests should', cleaned)
        cleaned=re.sub(r'#These local tests should\n#print\s*:?','#These local tests should print:',cleaned)
        cleaned=re.sub(r'#These local tests should\n#(?=\")','#These local tests should print:\n#',cleaned)
        if code_signature(cleaned)!=code_signature(existing):raise ValueError('Executable Python changed.')
        tests=local_test_lines(source)
        if tests:
            restored+=1
            test_calls+=sum(bool(re.match(r'^\s*#?\s*print\(',line)) for i,line in enumerate(source.splitlines()) if i in tests)
        if cleaned!=existing:files.append({'path':path,'text':cleaned,'visibility':'student'})
    validate_content(content)
    return {'part_id':part['id'],'assignment_id':part['assignment_id'],'title':part['title'],'base_revision':part['revision_id'],
        'content':content,'files':files,'source_hashes':{p:hashlib.sha256(t.encode()).hexdigest() for p,t in current['files'].items()},
        'content_changed':content!=part['content'],'local_test_files':restored,'local_print_calls':test_calls,
        'status':'ready' if files or content!=part['content'] else 'unchanged'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT/'var/coding-content-repair')
    p.add_argument('--original',type=Path,default=ROOT/'var/workspace-instruction-cleanup');a=p.parse_args();rows=[]
    for path in sorted((a.root/'current').glob('part-*.json')):
        current=json.loads(path.read_text());part=current['part'];prior=a.original/path.name
        try:
            if part['revision_id']!=part['published_revision_id']:raise ValueError('An unpublished draft exists; preserved.')
            if not prior.exists():raise ValueError('Missing preserved original source.')
            rows.append(repair(current,json.loads(prior.read_text())))
        except ValueError as exc:rows.append({'part_id':part['id'],'title':part['title'],'status':'review','reason':str(exc)})
    private_json(a.root/'plan.json',{'version':1,'parts':rows})
    print({status:sum(r['status']==status for r in rows) for status in ('ready','unchanged','review')})
    print('Files with original local tests:',sum(r.get('local_test_files',0) for r in rows),'local print calls:',sum(r.get('local_print_calls',0) for r in rows))
    for row in rows:
        if row['status']=='review':print('Review:',row['part_id'],row['reason'])

if __name__=='__main__':main()
