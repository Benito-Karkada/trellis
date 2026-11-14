#!/usr/bin/env python3
"""Plan/publish instruction-only cleanup using cached API snapshots. Never rewrites learner work."""
import argparse,ast,copy,difflib,hashlib,io,json,os,re,sys,tokenize,uuid
from pathlib import Path
from upload_native_graders import API,private_json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from core.schema import validate_content
from core.coding_content import local_test_lines, clean_prompt, DIRECTIVE


def clean_source(source, required=()):
    lines=source.splitlines(keepends=True);remove=set();comment_lines=[]
    tests=local_test_lines(source)
    tokens=[]
    stream=tokenize.generate_tokens(io.StringIO(source).readline)
    try:
        for token in stream:tokens.append(token)
    except tokenize.TokenError:
        pass  # Preserve the unfinished token/statement verbatim; edit only recognized comments.
    except IndentationError:
        raise ValueError('Invalid indentation needs manual review.')
    try:before=ast.dump(ast.parse(source),include_attributes=False)
    except (SyntaxError,ValueError):before=None  # Some exercises intentionally contain syntax errors.
    for token in tokens:
        if token.type!=tokenize.COMMENT or lines[token.start[0]-1][:token.start[1]].strip():continue
        if token.start[0]-1 in tests:continue
        text=token.string[1:]
        if token.start[0]<=2 and re.search(r'coding[:=]',text):continue
        comment_lines.append(text[1:] if text.startswith(' ') else text)
        if any(''.join(target.split()) in ''.join(token.string.split()) for target in required):continue
        remove.add(token.start[0]-1)
    cleaned=''.join(line for i,line in enumerate(lines) if i not in remove)
    if before is not None:
        cleaned=cleaned.strip('\r\n')
        if cleaned:cleaned+='\n'
        if ast.dump(ast.parse(cleaned),include_attributes=False)!=before:raise ValueError('Executable Python changed.')
    # Token equivalence also covers intentionally broken exercises without fixing them.
    ignored={tokenize.COMMENT,tokenize.NL,tokenize.ENDMARKER}
    original_tokens=[(t.type,'\n' if t.type==tokenize.NEWLINE else t.string) for t in tokens if t.type not in ignored]
    after=[]
    try:
        for token in tokenize.generate_tokens(io.StringIO(cleaned).readline):after.append(token)
    except tokenize.TokenError:pass
    after_tokens=[(t.type,'\n' if t.type==tokenize.NEWLINE else t.string) for t in after if t.type not in ignored]
    if original_tokens!=after_tokens:raise ValueError('Executable Python tokens changed.')
    return cleaned,comment_lines,len(remove)


def paragraphs(lines):
    groups=[];current=[]
    for line in lines+['']:
        if not line.strip():
            if current:groups.append(current);current=[]
        elif re.match(r'^\s*\d+[.)]\s',line) and current:
            groups.append(current);current=[line]
        else:current.append(line)
    nodes=[]
    for group in groups:
        text=' '.join(line.strip() for line in group)
        is_output=len(group)>1 and all(re.match(r'^\s*(?:-?\d+(?:\.\d+)?|True|False|None)\s*$',line) for line in group)
        if is_output:nodes.append({'type':'element','tag':'pre','children':[{'type':'text','text':'\n'.join(group)}]})
        else:nodes.append({'type':'element','tag':'p','children':[{'type':'text','text':text}]})
    return nodes


def plain(nodes):
    return ' '.join(n.get('text','')+' '+plain(n.get('children',[])) for n in nodes)


def prepare(snapshot):
    part=snapshot['part'];files=snapshot['files'];content=copy.deepcopy(part['content']);changes=[];comments=[];removed=0
    required=[r['target'] for r in (part['grading'].get('definition') or {}).get('requirements',[]) if r['kind']=='require_comment']
    for path,source in files.items():
        cleaned,lines,count=clean_source(source,required);comments+=lines+[''];removed+=count
        if cleaned!=source and count:changes.append({'path':path,'text':cleaned,'visibility':'student'})
    nodes=paragraphs(comments)
    coding=[b for b in content['blocks'] if b['type']=='coding']
    if nodes and coding:
        block=coding[0];old=block['prompt'];old_text=' '.join(plain(old).split());new_text=' '.join(plain(nodes).split())
        only_text=all(n['type']=='text' for n in old)
        normalize=lambda text:re.sub(r'\W+',' ',text.lower()).strip()
        if only_text:
            # Locate original paragraph boundaries without dropping XML-only text.
            segments=[];cursor=0;matched=True
            for node in nodes:
                value=' '.join(plain([node]).split());index=old_text.find(value,cursor)
                if index<0:matched=False;break
                if old_text[cursor:index].strip():segments.append({'type':'element','tag':'p','children':[{'type':'text','text':old_text[cursor:index].strip()}]})
                segments.append(node);cursor=index+len(value)
            if matched:
                if old_text[cursor:].strip():segments.append({'type':'element','tag':'p','children':[{'type':'text','text':old_text[cursor:].strip()}]})
                block['prompt']=segments
            else:
                sentences=re.split(r'(?<=[.!?])\s+(?=[A-Z])',old_text)
                block['prompt']=[{'type':'element','tag':'p','children':[{'type':'text','text':' '.join(sentences[i:i+2])}]} for i in range(0,len(sentences),2)]
                missing=[n for n in nodes if normalize(plain([n])) not in normalize(old_text)]
                if missing:block['prompt']+=[{'type':'element','tag':'h3','children':[{'type':'text','text':'Workspace instructions'}]},*missing]
        else:
            missing=[n for n in nodes if normalize(plain([n])) not in normalize(old_text)]
            if missing:block['prompt']=[*old,{'type':'element','tag':'h3','children':[{'type':'text','text':'Workspace instructions'}]},*missing]
    seen=set()
    for block in content['blocks']:
        if block['type']=='coding':block['prompt']=clean_prompt(block['prompt'],seen)
    validate_content(content)
    return {'part_id':part['id'],'assignment_id':part['assignment_id'],'title':part['title'],'base_revision':part['revision_id'],
        'content':content,'files':changes,'source_hashes':{p:hashlib.sha256(t.encode()).hexdigest() for p,t in files.items()},
        'removed_comment_lines':removed,'preserved_required_comments':len(required),'content_changed':content!=part['content']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT/'var/workspace-instruction-cleanup');p.add_argument('--apply',action='store_true');args=p.parse_args()
    if not args.apply:
        rows=[]
        for path in sorted(args.root.glob('part-*.json')):
            snapshot=json.loads(path.read_text());part=snapshot['part']
            if part['revision_id']!=part['published_revision_id']:rows.append({'part_id':part['id'],'title':part['title'],'status':'review','reason':'An unpublished draft already exists.'});continue
            try:
                plan=prepare(snapshot);plan['status']='ready' if plan['files'] or plan['content_changed'] else 'unchanged';rows.append(plan)
            except ValueError as exc:rows.append({'part_id':part['id'],'title':part['title'],'status':'review','reason':str(exc)})
        private_json(args.root/'plan.json',{'version':1,'parts':rows});print({k:sum(r['status']==k for r in rows) for k in ('ready','unchanged','review')});return
    plans=json.loads((args.root/'plan.json').read_text())['parts'];statepath=args.root/'upload-state.json';state=json.loads(statepath.read_text()) if statepath.exists() else {}
    api=API(os.environ['TRELLIS_URL'],os.environ['TRELLIS_API_TOKEN']);failures=[]
    try:
        for row in plans:
            if row['status']!='ready':continue
            pid=row['part_id'];record=state.setdefault(str(pid),{})
            if record.get('phase')=='published':continue
            current=api.request('GET',f'/parts/{pid}/')
            if record.get('revision') and current['published_revision_id']==record['revision']:
                record['phase']='published';private_json(statepath,state);continue
            try:
                if not record.get('revision'):
                    if current['course_id']!=1 or current['assignment_id']!=row['assignment_id'] or current['revision_id']!=row['base_revision'] or current['published_revision_id']!=row['base_revision']:raise ValueError('Part changed since the snapshot; preserved for review.')
                    hashes={f['path']:f['sha256'] for f in current['files'] if f['visibility']=='student'}
                    if any(hashes.get(path)!=digest for path,digest in row['source_hashes'].items()):raise ValueError('Student defaults changed since the snapshot.')
                    record.setdefault('patch_key',str(uuid.uuid4()));record['phase']='patching';private_json(statepath,state)
                    changed=api.request('PATCH',f'/parts/{pid}/',{'content':row['content'],'files':row['files']},row['base_revision'],record['patch_key'])
                    if changed['grading']!=current['grading']:raise ValueError('Unexpected grading change; draft kept unpublished.')
                    record['revision']=changed['revision_id'];record['phase']='draft';record['publish_key']=str(uuid.uuid4());private_json(statepath,state)
                api.request('POST',f'/parts/{pid}/publish/',{},record['revision'],record['publish_key']);record['phase']='published';private_json(statepath,state)
                print('[published]',pid,row['title'],flush=True)
            except (ValueError,RuntimeError) as exc:
                failures.append({'part_id':pid,'error':str(exc)});print('[review]',pid,str(exc),flush=True)
        private_json(args.root/'completion.json',{'published':sum(r.get('phase')=='published' for r in state.values()),'unchanged':sum(r['status']=='unchanged' for r in plans),'manual_review':[r for r in plans if r['status']=='review'],'errors':failures})
        print('Published:',sum(r.get('phase')=='published' for r in state.values()),'errors:',len(failures),flush=True)
    finally:api.session.close()

if __name__=='__main__':main()
