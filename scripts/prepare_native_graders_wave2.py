#!/usr/bin/env python3
"""Convert legacy test specifications to first-party declarative graders.
Only bounded test-data AST nodes are interpreted. Legacy grader implementations
and answer algorithms are never imported or executed.
"""
import ast,json,string,sys,hashlib,datetime,copy
from pathlib import Path
from prepare_native_graders import ROOT,Review,name,workspace
from native_spec_reader import Reader,ObjectInput
from upload_native_graders import private_json,bundle_digest
sys.path.insert(0,str(ROOT/'runner'))
from grading.spec import RunRequest
from grading.manifest import load_definition
from grading.engine import grade
from grading.docker_executor import DockerExecutor

def generator(n,data):
 if isinstance(n,ast.Name) and hasattr(data,'generators') and n.id in data.generators:return data.generators[n.id]
 if isinstance(n,ast.Call):
  f=name(n.func)
  if f in {'randint','uniform'}:return {'kind':'integer' if f=='randint' else 'float','min':data.value(n.args[0]),'max':data.value(n.args[1])}
  if f=='choice':return {'kind':'choice','values':list(data.value(n.args[0]))}
  if f=='get_random_string':
   length=n.args[0] if n.args else ast.Constant(value=10)
   if isinstance(length,ast.Call) and name(length.func)=='randint':lo,hi=[data.value(x) for x in length.args]
   else:lo=hi=data.value(length)
   kw={k.arg:data.value(k.value) for k in n.keywords}
   alphabet=string.digits if kw.get('all_numbers') else string.ascii_uppercase if kw.get('all_caps') else string.ascii_letters
   return {'kind':'string','min_length':lo,'max_length':hi,'alphabet':alphabet}
  if f=='round' and len(n.args)==1:return {'kind':'transform','operation':'round','items':[generator(n.args[0],data),{'kind':'literal','value':0}]}
  if f in {'str','chr','round'}:return {'kind':'transform','operation':f,'items':[generator(x,data) for x in n.args]}
 if isinstance(n,ast.BinOp) and isinstance(n.op,(ast.Add,ast.Mult)):
  return {'kind':'transform','operation':'add' if isinstance(n.op,ast.Add) else 'multiply','items':[generator(n.left,data),generator(n.right,data)]}
 if isinstance(n,(ast.List,ast.Tuple)):return {'kind':'sequence','items':[generator(x,data) for x in n.elts]}
 return {'kind':'literal','value':wire(data.value(n))}

def requirements(tree,data):
 rules=[];unknown=[]
 def add(kind,target,message):
  rule={'id':f'rule-{len(rules)+1}','kind':kind,'target':target,'message':message}
  if not any(r['kind']==kind and r['target']==target for r in rules):rules.append(rule)
 for c in [n for n in ast.walk(tree) if isinstance(n,ast.Call)]:
  f=name(c.func)
  if f in {'check_required_code','check_forbidden_code'}:
   for text in data.value(c.args[0]):add('require_source' if f=='check_required_code' else 'forbid_source',text,('Keep the required code: ' if f=='check_required_code' else 'Do not use: ')+text)
  elif f=='check_bad_consts':
   for value in data.value(c.args[0]):add('forbid_constant',json.dumps(value),'Compute the result instead of hard-coding '+repr(value)+'.')
  elif f=='check_function_present':add('require_function',data.value(c.args[1]),'Define the required function '+data.value(c.args[1])+'.')
  elif f.startswith('check_') and f not in {'check_code_for_string','check_file_exists','check_function_test_cases','check_printed_test_cases','check_file_output_test_cases','check_vars_and_vals'}:unknown.append(f)
 for node in ast.walk(tree):
  if isinstance(node,ast.Call) and name(node.func) in {'count_for_loops','count_while_loops'}:
   syntax='For' if name(node.func)=='count_for_loops' else 'While'
   if data.values.get('STUDENT_FILE_NAME')=='TryExcept4.py':add('max_node_count','For:1','Use only the supplied for loop.')
   else:add('require_node',syntax,'Use a '+syntax.lower()+' loop for this exercise.')
 if unknown:raise Review('Needs explicit native observations: '+', '.join(sorted(set(unknown))))
 # Some early graders implement literal restrictions inline instead of a helper.
 if any(isinstance(n,ast.Attribute) and n.attr=='co_consts' for n in ast.walk(tree)) and not any(isinstance(n,ast.Call) and name(n.func)=='check_bad_consts' for n in ast.walk(tree)):
  if 'bad_consts' not in data.values:raise Review('Inline constant restrictions need explicit conversion.')
  for value in data.values['bad_consts']:add('forbid_constant',json.dumps(value),'Compute the result instead of hard-coding '+repr(value)+'.')
 return rules

def wire(value):
 memo={};objects=[]
 def encode(v):
  if isinstance(v,ObjectInput):
   key=id(v)
   if key in memo:return {'$object_ref':memo[key]}
   identifier='object-'+str(len(memo));memo[key]=identifier
   row={'id':identifier,'class':v.name};objects.append(row)
   row.update(arguments=[encode(a) for a in v.arguments],attributes={k:encode(child) for k,child in v.attributes.items()})
   return {'$object_ref':identifier}
  if isinstance(v,datetime.datetime):raise Review('Datetime input needs an explicit fixture.')
  if isinstance(v,datetime.date):return {'$date':[v.year,v.month,v.day]}
  if isinstance(v,datetime.time):return {'$time':[v.hour,v.minute,v.second]}
  if isinstance(v,tuple):return {'$tuple':[encode(child) for child in v]}
  if isinstance(v,list):return [encode(child) for child in v]
  if isinstance(v,dict):
   if any(not isinstance(k,str) for k in v):return {'$dict':[[encode(k),encode(child)] for k,child in v.items()]}
   return {k:encode(child) for k,child in v.items()}
  return v
 result=encode(value)
 return {'$graph':objects,'$value':result} if objects else result

def inputs_for(data,matrix,action,parameters):
 result=[]
 for raw in matrix:
  args=list(raw) if isinstance(raw,tuple) else [raw]
  fields={'arguments':[wire(v) for v in args]} if action in {'function','function_file'} else {'variables':{k:wire(v) for k,v in zip(parameters,args)}}
  # Only attach fixture files this case actually reads. Output paths may be absent.
  fixtures={path:text for path,text in data.files.items() if path in args or any(isinstance(a,list) and path in a for a in args)}
  if action=='function_file' and data.values.get('student_function_name')=='append_to_file':fixtures[args[0]]='Existing text\n'
  if fixtures:fields['files']=fixtures
  result.append(fields)
 return result

def derive(tree,data):
 from native_special_plans import special
 plan=special(tree,data)
 if plan:return plan
 entry=data.values.get('STUDENT_FILE_NAME')
 if entry in {'PrintingIntegers.py','DaysBetweenDates.py'}:
  target='days_between' if entry=='DaysBetweenDates.py' else ''
  reduced=ast.Module(body=[ast.Expr(value=n) for n in ast.walk(tree) if isinstance(n,ast.Call) and name(n.func)=='check_required_code'],type_ignores=[])
  rules=requirements(reduced,data)
  cases=[{'id':'value','label':'Calculated value','action':'variable' if target else 'stdout','target':target,'public':True}]
  return {'version':1,'cases':cases,'requirements':rules,'random_cases':{'count':6,'oracle_path':'grader/reference.py','templates':[{'action':'variable' if target else 'stdout','target':target}]}}
 class_checks={'check_class_exists','check_attributes','check_object_has_methods','check_method_output','test_instance_creation'}
 if any(isinstance(n,ast.Call) and name(n.func) in class_checks for n in ast.walk(tree)):
  from native_trace_reader import TraceReader
  cases=[];templates=[]
  for seed in (1301,2025,2607):
   trace=TraceReader(seed).read(tree)
   if trace.failures:raise Review('Class specification incomplete: '+str(trace.failures))
   if not trace.expected:raise Review('No class observations recovered.')
   cases.append({'id':f'class-{seed}','label':f'Object behavior ({seed})','action':'trace','target':'__module__','steps':trace.steps,'expected':trace.expected,'public':True,'tolerance':0.011})
   if seed==1301:templates=[{'action':'trace','target':'__module__','steps':{'kind':'sequence','items':trace.step_generators},'tolerance':0.011}]
  # Source-only checks are still required in class exercises.
  reduced=ast.Module(body=[ast.Expr(value=n) for n in ast.walk(tree) if isinstance(n,ast.Call) and name(n.func) in {'check_required_code','check_forbidden_code','check_bad_consts'}],type_ignores=[])
  rules=requirements(reduced,data)
  if entry=='Burrito.py' and any(isinstance(n,ast.Call) and name(n.func)=='get_cost' for n in ast.walk(tree)):
   from native_special_plans import burrito_cost
   extra,random_template=burrito_cost()
   for i,c in enumerate(extra,1):c['id']=f'cost-{i}'
   cases.extend(extra);templates.append(random_template)
   rules=[r for r in rules if not (r['kind']=='forbid_source' and r['target'].strip()=='is')]
  return {'version':1,'scoring':'all_or_nothing','cases':cases,'requirements':rules,'random_cases':{'count':3,'oracle_path':'grader/reference.py','templates':templates}}
 rules=requirements(tree,data);cases=[];templates=[]
 if data.values.get('STUDENT_FILE_NAME')=='InterferingComments.py':
  rules.extend({'id':f'comment-{i}','kind':'require_comment','target':f'#Prints the number {i}','message':f'Keep the comment #Prints the number {i}.'} for i in range(1,6))
 helpers=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and name(n.func) in {'check_function_test_cases','check_printed_test_cases','check_file_output_test_cases'}]
 for helper in helpers:
  action={'check_function_test_cases':'function','check_printed_test_cases':'stdout','check_file_output_test_cases':'function_file'}[name(helper.func)];parameters=data.value(helper.args[0]);matrix=data.value(helper.args[1]);target=data.value(helper.args[3]) if action in {'function','function_file'} else ''
  if isinstance(helper.args[1],ast.Name) and helper.args[1].id in data.errors:raise Review('Incomplete input matrix: '+data.errors[helper.args[1].id])
  if not matrix:raise Review('No complete input matrix recovered.')
  options={k.arg:data.value(k.value) for k in helper.keywords}
  if set(options)-{'lines_to_skip','delete','within','approximate_floats','allow_string_equality'}:raise Review('Unknown legacy comparison option.')
  comparison='contains' if options.get('within') else 'numeric_text' if options.get('approximate_floats') else 'string' if options.get('allow_string_equality') else 'python' if action in {'function','function_file'} else 'exact'
  for fields in inputs_for(data,matrix,action,parameters):
   cases.append({'id':f'case-{len(cases)+1}','label':f'Test {len(cases)+1}','action':action,'target':target,'public':True,'comparison':comparison,**fields,**({'strip_output':True} if action=='stdout' else {})})
  # Recover the actual declared randomized expressions, preserving each row's correlations.
  node=helper.args[1]
  if isinstance(node,ast.Name):
   declarations=[n.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==node.id for t in n.targets)]
   if len(declarations)==1:node=declarations[0]
  if isinstance(node,(ast.List,ast.Tuple)):
   for row in node.elts:
    if not any(isinstance(n,ast.Call) and name(n.func) in {'randint','uniform','choice','get_random_string'} for n in ast.walk(row)):continue
    args=row.elts if isinstance(row,ast.Tuple) else [row]
    try:inputs=[generator(a,data) for a in args]
    except (Review,KeyError,TypeError,ValueError):continue
    t={'action':action,'target':target,**({'arguments':inputs} if action in {'function','function_file'} else {'variables':dict(zip(parameters,inputs)),'strip_output':True})}
    t['comparison']=comparison
    if t not in templates:templates.append(t)
 if not helpers:
  declarations=[n.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='test_vars' for t in n.targets)]
  if len(declarations)==1 and isinstance(declarations[0],ast.Dict) and 'test_cases' in data.values:
   mapping=declarations[0];parameters=[]
   for k,v in zip(mapping.keys,mapping.values):
    if not isinstance(v,ast.Subscript) or not isinstance(v.slice,ast.Constant) or v.slice.value!=len(parameters):raise Review('Custom variable mapping needs explicit conversion.')
    parameters.append(data.value(k))
   for fields in inputs_for(data,data.values['test_cases'],'stdout',parameters):cases.append({'id':f'case-{len(cases)+1}','label':f'Test {len(cases)+1}','action':'stdout','public':True,'strip_output':True,**fields})
   pool=[]
   for seed in range(1301,1365):
    reader=Reader(seed).read(tree)
    for fields in inputs_for(reader,reader.values['test_cases'],'stdout',parameters):
     if fields not in pool:pool.append(fields)
   templates=[{'action':'stdout','inputs':{'kind':'choice','values':pool},'strip_output':True}]
  for c in [n for n in ast.walk(tree) if isinstance(n,ast.Call) and name(n.func)=='check_vars_and_vals']:
   for key,value in data.value(c.args[0]):
    if value is None:raise Review('Presence-only checks need explicit conversion.')
    cases.append({'id':f'value-{key}','label':'Value of '+key,'action':'variable','target':key,'expected':wire(value),'public':True})
  if not cases and isinstance(data.values.get('correct_output'),str):cases=[{'id':'output','label':'Printed output','action':'stdout','expected':data.values['correct_output'],'strip_output':True,'public':True}]
  if not cases:
   node=next((n.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='expected_variables' for t in n.targets)),None)
   if node:
    for pair in node.elts:
     key=data.value(pair.elts[0]);kind=name(pair.elts[1])
     if kind not in {'int','float','str','bool','list','dict','tuple','set'}:
      cases.append({'id':'value-'+key,'label':'Value of '+key,'action':'variable','target':key,'expected':wire(data.value(pair.elts[1])),'public':True});continue
     cases.append({'id':'type-'+key,'label':'Type of '+key,'action':'variable_type','target':key,'expected':kind,'public':True})
 if not cases:raise Review('Needs explicit first-party test plan.')
 if helpers and (not templates or data.files):
  # Preserve correlated generated inputs and file fixtures as a public randomized
  # test bank. These are input data, never expected values or legacy code.
  for helper in helpers:
   action={'check_function_test_cases':'function','check_printed_test_cases':'stdout','check_file_output_test_cases':'function_file'}[name(helper.func)]
   parameters=data.value(helper.args[0]);target=data.value(helper.args[3]) if action!='stdout' else '';pool=[]
   for seed in range(1301,1333):
    reader=Reader(seed).read(tree)
    if isinstance(helper.args[1],ast.Name) and helper.args[1].id in reader.errors:raise Review('Incomplete generated input matrix: '+reader.errors[helper.args[1].id])
    for fields in inputs_for(reader,reader.value(helper.args[1]),action,parameters):
     if fields not in pool:pool.append(fields)
   if len(pool)<2:raise Review('No varied input domain recovered.')
   templates.append({'action':action,'target':target,'comparison':'contains' if any(k.arg=='within' and data.value(k.value) for k in helper.keywords) else 'numeric_text' if any(k.arg=='approximate_floats' and data.value(k.value) for k in helper.keywords) else 'string' if any(k.arg=='allow_string_equality' and data.value(k.value) for k in helper.keywords) else 'python' if action in {'function','function_file'} else 'exact','inputs':{'kind':'choice','values':pool[:1000]},**({'strip_output':True} if action=='stdout' else {})})
 if len(templates)>10:templates=templates[:10]
 return {'version':1,'scoring':'all_or_nothing','requirements':rules,'cases':cases,**({'random_cases':{'count':3,'oracle_path':'grader/reference.py','templates':templates}} if templates else {})}

def prepare(row,source,archive,out,executor):
 tree=ast.parse(source.read_text());data=Reader().read(tree);definition=derive(tree,data);entry=data.values['STUDENT_FILE_NAME'];files=workspace(archive)
 if entry not in files:raise Review('Declared file missing from archive.')
 samples=sorted((archive/'private').glob('sample_answer*.py'))
 override=ROOT/'var/native-reference-overrides'/f"part-{row['part_id']}.py"
 if not samples and not override.exists():raise Review('No staff sample answer.')
 positive=samples[0].read_text() if samples else override.read_text()
 override=ROOT/'var/native-reference-overrides'/f"part-{row['part_id']}.py"
 if override.exists():positive=override.read_text()
 clock='2026-06-15T13:24:36' if any(isinstance(n,ast.Call) and name(n.func) in {'today','now'} for n in ast.walk(ast.parse(positive))) else None
 if clock:
  for case in definition['cases']:case['clock']=clock
  for template in definition.get('random_cases',{}).get('templates',[]):template['clock']=clock
 for case in definition['cases']:
  if 'expected' in case:continue
  o=executor.run(RunRequest(source=positive,action=case['action'],target=case.get('target',''),arguments=tuple(case.get('arguments',[])),variables=case.get('variables',{}),steps=case.get('steps',()),clock=case.get('clock'),files={**files,**case.get('files',{})}))
  if o.status!='ok':raise Review('Staff sample execution: '+o.status+' '+o.stdout[-160:])
  case['expected']=o.stdout if case['action'] in {'stdout','function_stdout'} else o.value
 if any(isinstance(n,ast.Call) and name(n.func)=='count_recursive_calls' for n in ast.walk(tree)):
  call=next(c for c in definition['cases'] if c['action']=='function')
  definition['cases'].append({'id':'recursive-call','label':'Recursive implementation','action':'recursion','target':call['target'],'arguments':call['arguments'],'expected':True,'public':True})
 exercise=load_definition(definition)
 kwargs={'files':files,'oracle_source':positive if definition.get('random_cases') else None,'oracle_files':files}
 for seed in (1301,2025):
  result=grade(positive,exercise,executor,random_seed=seed,**kwargs)
  if not result['passed']:raise Review('Staff sample fails: '+'; '.join(c['message'] for c in result['checks'] if not c['passed'])[:350])
 negatives=['raise RuntimeError("Incorrect control")\n']
 functions=sorted({c['target'] for c in definition['cases'] if c['action']=='function'})
 if functions:negatives.append('\n'.join(f'def {f}(*args, **kwargs): return None' for f in functions)+'\n')
 else:negatives.append('print("Incorrect output")\n')
 for n in negatives:
  if grade(n,exercise,executor,random_seed=1301,**kwargs)['passed']:raise Review('Incorrect control passed.')
 folder=out/f"part-{row['part_id']}";folder.mkdir(exist_ok=True,parents=True)
 private_json(folder/'autograder.json',definition)
 for file,text in [('correct.py',positive),('reference.py',positive),*[(f'incorrect-{i}.py',n) for i,n in enumerate(negatives,1)]]:(folder/file).write_text(text);(folder/file).chmod(0o600)
 row.update(status='ready',entrypoint=entry,definition=f"part-{row['part_id']}/autograder.json",source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),randomization='per_submission' if definition.get('random_cases') else 'fixed_output_or_type_constraint',validation={'status':'passed','positive':f"part-{row['part_id']}/correct.py",'negatives':[f"part-{row['part_id']}/incorrect-{i}.py" for i in (1,2)]})
 if definition.get('random_cases'):row['reference']=f"part-{row['part_id']}/reference.py"
 row['validation']['bundle_sha256']=bundle_digest(row,definition,positive,negatives,positive if row.get('reference') else None)
 return row
if __name__=='__main__':
 import prepare_native_graders as original
 from dataclasses import asdict
 from collections import OrderedDict
 class CachedExecutor(DockerExecutor):
  def __init__(self):super().__init__();self.cache=OrderedDict()
  def run(self,request):
   key=hashlib.sha256(json.dumps(asdict(request),sort_keys=True).encode()).hexdigest()
   if key in self.cache:return self.cache[key]
   result=super().run(request)
   if result.status not in {'infrastructure_error','timeout'}:
    self.cache[key]=result
    if len(self.cache)>512:self.cache.popitem(last=False)
   return result
 original.DockerExecutor=CachedExecutor
 original.prepare=prepare
 original.main()
