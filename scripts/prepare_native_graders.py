#!/usr/bin/env python3
"""Prepare independent native test data from legacy specifications and staff answers.

Parses Ferb with AST only; it never imports/runs Ferb or copies its answer functions.
Staff sample answers run only in disposable Docker containers. Unknown checks,
mutating case generators and unsupported comparison rules remain review items.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runner'))
from grading.docker_executor import DockerExecutor
from grading.engine import grade
from grading.manifest import load_definition
from grading.spec import RunRequest, valid_value
from upload_native_graders import bundle_digest, private_json


class Review(ValueError):
    pass


def name(node):
    return node.id if isinstance(node,ast.Name) else node.attr if isinstance(node,ast.Attribute) else ''


class Data:
    """Small data-expression reader, not eval/exec of legacy Python."""
    def __init__(self):self.values={};self.random=random.Random(1301)
    def value(self,node):
        if isinstance(node,ast.Constant):result=node.value
        elif isinstance(node,ast.Name) and node.id in self.values:result=self.values[node.id]
        elif isinstance(node,(ast.List,ast.Tuple)):
            result=[self.value(n) for n in node.elts]
            if isinstance(node,ast.Tuple):result=tuple(result)
        elif isinstance(node,ast.Dict):result={self.value(k):self.value(v) for k,v in zip(node.keys,node.values)}
        elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
            result=self.value(node.operand);result=-result if isinstance(node.op,ast.USub) else +result
        elif isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div)):
            a,b=self.value(node.left),self.value(node.right)
            if isinstance(node.op,ast.Mult) and (not isinstance(a,(int,float)) or not isinstance(b,(int,float))):raise Review('Non-numeric data multiplication needs review.')
            result=a+b if isinstance(node.op,ast.Add) else a-b if isinstance(node.op,ast.Sub) else a*b if isinstance(node.op,ast.Mult) else a/b
        elif isinstance(node,ast.Call) and not node.keywords:
            function=name(node.func);args=[self.value(a) for a in node.args]
            if isinstance(node.func,ast.Attribute) and function=='strip' and not args:
                result=self.value(node.func.value).strip()
            elif isinstance(node.func,ast.Attribute) and not (isinstance(node.func.value,ast.Name) and node.func.value.id=='random'):
                raise Review('Unsupported data call.')
            elif function=='randint' and len(args)==2 and all(type(x)is int and abs(x)<1000000 for x in args):result=self.random.randint(*args)
            elif function=='uniform' and len(args)==2:result=self.random.uniform(*args)
            elif function=='choice' and len(args)==1 and isinstance(args[0],(list,tuple)) and args[0]:result=self.random.choice(args[0])
            elif function=='round' and 1<=len(args)<=2:result=round(*args)
            elif function in {'str','int','float','bool'} and len(args)==1:result={'str':str,'int':int,'float':float,'bool':bool}[function](*args)
            else:raise Review('Unsupported data expression.')
        else:raise Review('Data requires a custom conversion.')
        if not valid_value(result):raise Review('Data is outside the native JSON limits.')
        return result


def read_declarations(tree):
    data=Data();wanted={'STUDENT_FILE_NAME','student_function_name','parameter_names','var_names','test_cases','cases','bad_consts','correct_output'}
    assignments={}
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id in wanted:
                    assignments.setdefault(target.id,[]).append(node.value)
    for key,nodes in assignments.items():
        if len(nodes)!=1:
            if key in {'test_cases','cases','STUDENT_FILE_NAME','student_function_name'}:raise Review(f'{key} is assigned more than once.')
            continue
        try:data.values[key]=data.value(nodes[0])
        except (Review,TypeError,ValueError,ArithmeticError):pass
    return data


def derive(tree, data):
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
    checks={name(n.func) for n in calls if name(n.func).startswith('check_')}
    allowed={'check_function_test_cases','check_printed_test_cases','check_code_for_string'}
    unsupported=checks-allowed
    if unsupported:raise Review('Custom source/file/class constraints: '+', '.join(sorted(unsupported)))
    if any(isinstance(n,ast.Attribute) and n.attr=='co_consts' for n in ast.walk(tree)):
        raise Review('Hard-coded-constant checks need a native equivalent.')
    # Only ignore obsolete-starter diagnostics, never a code-content grading check.
    parents={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for call in calls:
        if name(call.func)!='check_code_for_string':continue
        parent=parents.get(call)
        if not isinstance(parent,ast.If) or not any(isinstance(n,ast.Call) and name(n.func)=='get_outdated_results' for statement in parent.body for n in ast.walk(statement)):
            raise Review('A code-content check needs a native equivalent.')
    helper=[c for c in calls if name(c.func) in {'check_function_test_cases','check_printed_test_cases'}]
    if helper:
        if len(helper)!=1:raise Review('Multiple helper grading paths need review.')
        call=helper[0];action='function' if name(call.func)=='check_function_test_cases' else 'stdout'
        if any(k.arg not in {'lines_to_skip'} for k in call.keywords):raise Review('Legacy comparison options need a native equivalent.')
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id in {'test_cases','cases'}:
                raise Review('A generated/mutated test matrix needs explicit conversion.')
            if isinstance(node,ast.AugAssign) and name(node.target) in {'test_cases','cases'}:raise Review('A generated test matrix needs explicit conversion.')
        try:
            parameters=data.value(call.args[0]);matrix=data.value(call.args[1])
            target=data.value(call.args[3]) if action=='function' else ''
            if action=='stdout' and len(call.args)>4 and data.value(call.args[4]):raise Review('Forbidden constants need a native equivalent.')
        except (IndexError,TypeError,ValueError) as exc:raise Review('Could not recover the complete input matrix: '+str(exc)) from None
        if not isinstance(parameters,(list,tuple)) or any(not isinstance(p,str) or not p.isidentifier() for p in parameters):raise Review('Invalid input names.')
        if not isinstance(matrix,(list,tuple)) or not 1<=len(matrix)<=200:raise Review('Invalid or missing test matrix.')
        if action=='function' and (not isinstance(target,str) or not target.isidentifier()):raise Review('Invalid function target.')
        cases=[]
        for i,raw in enumerate(matrix,1):
            arguments=list(raw) if isinstance(raw,tuple) else [raw]
            if len(arguments)!=len(parameters):raise Review('Case arity differs from its input declarations.')
            cases.append({'id':f'case-{i}','label':f'Test {i}','action':action,'target':target,
                          'arguments':arguments if action=='function' else [],
                          'variables':dict(zip(parameters,arguments)) if action=='stdout' else {},
                          'public':True,**({'strip_output':True} if action=='stdout' else {})})
        return cases, 'staff_sample'
    types=next((n.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='expected_variables' for t in n.targets)),None)
    if isinstance(types,(ast.List,ast.Tuple)):
        cases=[]
        for pair in types.elts:
            if not isinstance(pair,(ast.List,ast.Tuple)) or len(pair.elts)!=2:raise Review('Custom expected-variable structure.')
            key,kind=pair.elts
            if not isinstance(key,ast.Constant) or not isinstance(key.value,str) or not isinstance(kind,ast.Name) or kind.id not in {'int','float','str','bool','list','dict','tuple','set'}:raise Review('Custom variable checks need review.')
            cases.append({'id':'type-'+key.value,'label':'Type of '+key.value,'action':'variable_type','target':key.value,'expected':kind.id,'public':True})
        return cases,'staff_sample'
    output=data.values.get('correct_output')
    if isinstance(output,str) and not checks:
        forbidden_names={'program_code','program_code_no_spaces','bad_consts','const'}
        if any(isinstance(n,ast.Compare) and any(isinstance(v,ast.Name) and v.id in forbidden_names for v in ast.walk(n)) for n in ast.walk(tree)):
            raise Review('Additional source/comment constraints need review.')
        return [{'id':'output','label':'Printed output','action':'stdout','expected':output,'strip_output':True,'public':True}], 'literal_output'
    raise Review('No complete native conversion is available for this custom grader.')



def input_generator(node,data):
    if isinstance(node,ast.Call):
        function=name(node.func)
        if function=='randint':return {'kind':'integer','min':data.value(node.args[0]),'max':data.value(node.args[1])}
        if function=='uniform':return {'kind':'float','min':data.value(node.args[0]),'max':data.value(node.args[1])}
        if function=='choice':return {'kind':'choice','values':list(data.value(node.args[0]))}
        if function=='round' and len(node.args)==2:
            child=input_generator(node.args[0],data)
            if child['kind']!='float':raise Review('Rounded random input requires a float generator.')
            return {**child,'digits':data.value(node.args[1])}
    if isinstance(node,(ast.List,ast.Tuple)):
        return {'kind':'sequence','items':[input_generator(child,data) for child in node.elts]}
    return {'kind':'literal','value':data.value(node)}


def random_spec(tree,data):
    helpers=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and name(n.func) in {'check_function_test_cases','check_printed_test_cases'}]
    if not helpers:return None
    if len(helpers)!=1:raise Review('Random input conversion has more than one grading path.')
    call=helpers[0];node=call.args[1]
    if isinstance(node,ast.Name):
        nodes=[n.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==node.id for t in n.targets)]
        if len(nodes)!=1:raise Review('Random matrix needs custom authoring.')
        node=nodes[0]
    if not isinstance(node,(ast.List,ast.Tuple)):raise Review('Random matrix must have declarative rows.')
    parameters=data.value(call.args[0]);action='function' if name(call.func)=='check_function_test_cases' else 'stdout'
    target=data.value(call.args[3]) if action=='function' else ''
    templates=[]
    for row in node.elts:
        if not any(isinstance(n,ast.Call) and name(n.func) in {'randint','uniform','choice'} for n in ast.walk(row)):continue
        args=row.elts if isinstance(row,ast.Tuple) else [row]
        if len(args)!=len(parameters):raise Review('Random matrix input arity needs review.')
        inputs=[input_generator(n,data) for n in args]
        template={'action':action,'target':target}
        if action=='function':template['arguments']=inputs
        else:template.update(variables=dict(zip(parameters,inputs)),strip_output=True)
        if template not in templates:templates.append(template)
    if not templates:raise Review('This input-based exercise needs explicit random input domains.')
    return {'count':3,'oracle_path':'grader/reference.py','templates':templates}

def workspace(folder):
    result={}
    for path in sorted((folder/'startercode').rglob('*')):
        if path.is_symlink() or not path.is_file():continue
        result[str(path.relative_to(folder/'startercode'))]=path.read_text()
    return result


def prepare(row, source, archive, out, executor):
    tree=ast.parse(source.read_text());data=read_declarations(tree)
    cases,kind=derive(tree,data)
    entrypoint=data.values.get('STUDENT_FILE_NAME')
    files=workspace(archive)
    if entrypoint not in files:raise Review('The declared entrypoint is not in the student file set.')
    sample=next(iter(sorted((archive/'private').glob('sample_answer*.py'))),None)
    if sample:
        positive=sample.read_text();sampletree=ast.parse(positive)
        if any(isinstance(n,ast.Call) and name(n.func) in {'today','now','time'} for n in ast.walk(sampletree)):raise Review('Time-dependent answers need dynamic test support.')
    elif kind=='literal_output':positive='print('+repr(cases[0]['expected'])+')\n'
    else:raise Review('No staff sample answer is available for independent expected results.')
    for case in cases:
        if 'expected' in case:continue
        observation=executor.run(RunRequest(source=positive,action=case['action'],target=case.get('target',''),
            arguments=tuple(case.get('arguments',[])),variables=case.get('variables',{}),files=files))
        if observation.status!='ok':raise Review('Staff answer did not run successfully in isolation: '+observation.status)
        expected=observation.stdout if case['action']=='stdout' else observation.value
        if not valid_value(expected):raise Review('Staff observation is not representable by native JSON tests.')
        case['expected']=expected
    definition={'version':1,'scoring':'all_or_nothing','cases':cases}
    dynamic=random_spec(tree,data)
    if dynamic:definition['random_cases']=dynamic
    exercise=load_definition(definition)
    if not all(grade(positive,exercise,executor,files=files,oracle_source=positive if dynamic else None,oracle_files=files,random_seed=seed)['passed'] for seed in (1301,2025)):raise Review('Staff answer failed the converted native definition.')
    negatives=['raise RuntimeError("Deliberately incorrect test submission")\n']
    if cases[0]['action']=='function':
        negatives.append(f"def {cases[0]['target']}(*args, **kwargs):\n    return {cases[0]['expected']!r}\n")
    elif cases[0]['action']=='stdout':
        if any(case.get('variables') for case in cases):negatives.append('print('+repr(cases[0]['expected'].strip())+')\n')
        else:negatives.append('print("Deliberately incorrect output")\n')
    else:
        negatives.append('\n'.join(case['target']+' = None' for case in cases)+'\n')
    for negative in negatives:
        if grade(negative,exercise,executor,files=files,oracle_source=positive if dynamic else None,oracle_files=files,random_seed=1301)['passed']:raise Review('A constant/incorrect solution passes; stronger native cases are needed.')
    folder=out/f"part-{row['part_id']}";folder.mkdir(parents=True,exist_ok=True)
    private_json(folder/'autograder.json',definition)
    (folder/'correct.py').write_text(positive);(folder/'correct.py').chmod(0o600)
    paths=[]
    for i,negative in enumerate(negatives,1):
        path=folder/f'incorrect-{i}.py';path.write_text(negative);path.chmod(0o600);paths.append(str(path.relative_to(out)))
    row.update(status='ready',entrypoint=entrypoint,definition=str((folder/'autograder.json').relative_to(out)),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        validation={'status':'passed','positive':str((folder/'correct.py').relative_to(out)), 'negatives':paths})
    if dynamic:
        reference=folder/'reference.py';reference.write_text(positive);reference.chmod(0o600);row['reference']=str(reference.relative_to(out))
    row['randomization']='per_submission' if dynamic else 'fixed_output_or_type_constraint'
    row['validation']['bundle_sha256']=bundle_digest(row,definition,positive,negatives,positive if dynamic else None)
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,default=ROOT/'var/ferb-sources/manifest.json')
    parser.add_argument('--report',type=Path,default=ROOT/'var/api-reports/missing-native-graders.json')
    parser.add_argument('--archives',type=Path,default=ROOT/'var/vocareum-coding-archives')
    parser.add_argument('--out',type=Path,default=ROOT/'var/native-graders')
    parser.add_argument('--course',type=int,default=1)
    parser.add_argument('--part',type=int,action='append')
    args=parser.parse_args()
    from pull_ferb import cached_parts
    archives=cached_parts(args.archives,'144164')
    sources={str(r['trellis_part_id']):r for r in json.loads(args.sources.read_text())['parts'] if r['status']=='saved'}
    rows=json.loads(args.report.read_text());executor=DockerExecutor();result=[];args.out.mkdir(parents=True,exist_ok=True)
    manifest={'version':1,'course_id':args.course,'parts':result}
    for source_row in rows:
        if args.part and source_row['part_id'] not in args.part:continue
        row={k:source_row[k] for k in ('part_id','assignment_id','title','vocareum_part_id')}
        row.update(expected_revision_id=source_row['published_revision_id'],status='needs_review')
        reference=sources.get(str(row['part_id']))
        try:
            if not reference:
                row['status']='unmapped'
                raise Review('No mapped Ferb source. Placeholder matching is separate.')
            archive=archives[str(row['vocareum_part_id'])][1]
            row=prepare(row,args.sources.parent/reference['file'],archive,args.out,executor)
        except (Review,ValueError,TypeError,SyntaxError,OSError,RuntimeError) as exc:
            row['reason']=str(exc)
        result.append(row);private_json(args.out/'manifest.json',manifest)
        print(f"[{row['status']}] {row['part_id']} {row['title']}" + (': '+row['reason'] if row.get('reason') else ''),flush=True)
    print(f"Ready {sum(r['status']=='ready' for r in result)} / {len(result)}; remaining entries require explicit conversion/review.",flush=True)


if __name__=='__main__':main()
