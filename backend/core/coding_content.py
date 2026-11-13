"""Conservative presentation cleanup for coding prompts and public local tests."""
import ast
import re

DIRECTIVE=re.compile(r"\b(?:(?:add|write|insert|put|place)\s+(?:your|the)\s+(?:code|function|solution|answer)|call\s+your\s+function)\s+(?:here|below)\s*(?:[!.:](?=\s|$)|(?=$))",re.I)
TEST_MARKER=re.compile(r"\b(?:below|following)\b.*\btest\b|\b(?:lines?|code|statements?)\b.*\btest\b.*\b(?:function|code|class|edits|submission)\b",re.I)


def local_test_lines(source):
    lines=source.splitlines();last_placeholder=-1
    for i,line in enumerate(lines):
        if line.lstrip().startswith('#') and DIRECTIVE.search(line.lstrip()[1:]):last_placeholder=i
    start=None
    for i,line in enumerate(lines):
        if i<=last_placeholder or not line.startswith('#'):continue
        if TEST_MARKER.search(line[1:]):start=i;break
    keep=set(range(start,len(lines))) if start is not None else set()
    for i,line in enumerate(lines):
        if i<=last_placeholder or not line.startswith('#'):continue
        try:tree=ast.parse(line[1:].strip())
        except SyntaxError:continue
        if len(tree.body)==1 and isinstance(tree.body[0],ast.Expr) and isinstance(tree.body[0].value,ast.Call) and isinstance(tree.body[0].value.func,ast.Name) and tree.body[0].value.func.id=='print':
            keep.add(i);j=i-1
            while j>=0 and (not lines[j].strip() or lines[j].startswith('#')):
                if DIRECTIVE.search(lines[j]):break
                keep.add(j);j-=1
    return {i for i in keep if not DIRECTIVE.search(lines[i])}


def normalize(text):return re.sub(r'\s+',' ',text.replace('’',"'")).strip()


def _clean_prompt_once(nodes, seen=None):
    """Deduplicate prose sentences; preserve code, math, media and rich markup."""
    import copy
    seen=set() if seen is None else seen
    output=[]
    for original in nodes:
        node=copy.deepcopy(original)
        if node.get('type')=='element' and node.get('tag') in {'pre','code','table','ul','ol'}:
            output.append(node);continue
        if node.get('type')=='element' and node.get('tag')=='h3' and normalize(' '.join(n.get('text','') for n in node.get('children',[]))).casefold()=='workspace instructions':continue
        text=None
        if node.get('type')=='text':text=node.get('text','')
        elif node.get('type')=='element' and node.get('tag') in {'p','div'} and all(n.get('type')=='text' for n in node.get('children',[])):
            text=''.join(n.get('text','') for n in node['children'])
        if text is not None:
            text=DIRECTIVE.sub('',text)
            sentences=re.split(r'(?<=[.!?])\s+(?=[A-Z"\'])',normalize(text));unique=[]
            for sentence in sentences:
                key=normalize(sentence)
                if key and key not in seen:unique.append(sentence);seen.add(key)
            if not unique:continue
            value=' '.join(unique)
            # Old imports joined bullet lists and long comment groups into one
            # paragraph. Restore block structure without rewriting any wording.
            bullets=re.split(r'\s+- (?=[A-Za-z_])',value)
            starts_list=value.startswith('- ')
            if (starts_list or ':' in bullets[0]) and len(bullets)>=3:
                prefix=bullets.pop(0)
                if starts_list:bullets.insert(0,prefix[2:])
                elif prefix:
                    output.append({'type':'element','tag':'p','children':[{'type':'text','text':prefix}]})
                    seen.update(normalize(sentence) for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])",prefix))
                output.append({'type':'element','tag':'ul','children':[{'type':'element','tag':'li','children':[{'type':'text','text':item}]} for item in bullets]})
                continue
            if len(value)>600 and len(unique)>2:
                output.extend({'type':'element','tag':'p','children':[{'type':'text','text':' '.join(unique[i:i+2])}]} for i in range(0,len(unique),2))
                continue
            if node['type']=='text':node['text']=value
            else:node['children']=[{'type':'text','text':value}]
        # Inline markup is not a bag of independent prose sentences. Keep it
        # intact so repeated conjunctions/code fragments are never removed.
        elif 'children' in node:
            def strip_cues(children):
                for child in children:
                    if child.get('type')=='text':child['text']=DIRECTIVE.sub('',child.get('text',''))
                    elif child.get('tag') not in {'pre','code'}:strip_cues(child.get('children',[]))
            strip_cues(node['children'])
        output.append(node)
    return output



def clean_prompt(nodes, seen=None):
    """Normalize until stable because splitting a list exposes its prose prefix."""
    baseline=set() if seen is None else set(seen)
    current=nodes
    for _ in range(4):
        current_seen=set(baseline)
        result=_clean_prompt_once(current,current_seen)
        if result==current:
            if seen is not None:seen.update(current_seen)
            return result
        current=result
    raise ValueError('Coding prompt normalization did not stabilize.')
