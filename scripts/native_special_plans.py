"""First-party plans for exercises whose legacy graders use custom control flow."""
import ast,random,string

def literal(value):return {'kind':'literal','value':value}
def number(low,high):return {'kind':'integer','min':low,'max':high}
def choice(values):return {'kind':'choice','values':values}
def construct(target,name,args):return {'op':'construct','target':target,'name':name,'arguments':args,'record':False}
def call(target,args=(),record=True):return {'op':'call','target':target,'arguments':list(args),'record':record}
def ref(name):return {'$ref':name}
def trace(steps,label='Object behavior',**extra):return {'action':'trace','target':'__module__','steps':steps,'label':label,'public':True,**extra}
def definition(cases,templates=None,rules=()):
 for i,c in enumerate(cases,1):c.setdefault('id',f'test-{i}');c.setdefault('label',f'Test {i}');c.setdefault('public',True)
 return {'version':1,'scoring':'all_or_nothing','cases':cases,'requirements':list(rules),**({'random_cases':{'count':3,'oracle_path':'grader/reference.py','templates':templates}} if templates else {})}
def special(tree,data):
 entry=data.values.get('STUDENT_FILE_NAME')
 if entry in {'HideAndSeek2.py','CountDown.py','SumOfPrimes.py'}:
  target,action,values=('hide_and_seek','function_stdout',[0,1,4,10,36]) if entry=='HideAndSeek2.py' else ('count_down2','function_stdout',[0,1,5,12,20]) if entry=='CountDown.py' else ('sum_of_primes','function',[0,1,2,6,7,8,11,37])
  base={'action':action,'target':target,**({'strip_output':True} if action=='function_stdout' else {})}
  return definition([{**base,'arguments':[v]} for v in values],[{**base,'arguments':[number(0,80 if action=='function_stdout' else 200)]}])
 if entry=='Burrito.py' and data.values.get('student_function_name')=='total_cost':
  def burrito(cost):return {'$fixture':{'attributes':{'cost':cost},'getters':{'get_cost':'cost'}}}
  cases=[{'action':'function','target':'total_cost','arguments':[[burrito(c) for c in costs]]} for costs in ([],[5.0],[6.0,7.5,6.75,7.75],[8.25,5.0,6.5])]
  item={'kind':'record','fields':{'$fixture':{'kind':'record','fields':{'attributes':{'kind':'record','fields':{'cost':choice([5.0,6.0,6.5,6.75,7.0,7.25,7.5,7.75,8.25])}},'getters':literal({'get_cost':'cost'})}}}}
  return definition(cases,[{'action':'function','target':'total_cost','arguments':[{'kind':'list','min_length':0,'max_length':15,'items':item}]}])
 if entry=='TryExcept2.py':
  cases=[{'action':'module_outcome','target':'__module__','variables':{'mystery_value':v}} for v in (9,0,'0','123',100)]
  rules=[{'id':'no-if','kind':'forbid_node','target':'If','message':'Use exception handling instead of conditionals.'},{'id':'no-type','kind':'forbid_source','target':'type(','message':'Use exception handling instead of type checks.'}]
  return definition(cases,[{'action':'module_outcome','target':'__module__','variables':{'mystery_value':choice([0,1,2,5,8,15,27,'0','123','90'])}}],rules)
 if entry=='SimpleDictionary.py':
  mapping={'A':1,'B':2,'C':3}
  cases=[{'action':'function','target':'safe_lookup','arguments':[mapping,key],'expected':mapping.get(key)} for key in ('A','B','C','D')]
  values={'kind':'record','fields':{key:number(-1000,1000) for key in mapping}}
  return definition(cases,[{'action':'function','target':'safe_lookup','arguments':[values,choice(['A','B','C','D'])]}])
 if entry=='NestedLoops.py':
  cases=[{'action':'stdout','variables':{'mystery_int':v},'strip_output':True,'comparison':'whitespace'} for v in (1,3,4,5,8)]
  return definition(cases,[{'action':'stdout','variables':{'mystery_int':number(1,12)},'strip_output':True,'comparison':'whitespace'}])
 if entry=='FormatChecker.py':
  cases=[]
  for i,(lines,expected,*_) in enumerate(data.values['test_cases']):
   cases.append({'action':'function','target':'format_checker','arguments':['format-test.txt'],'files':{'format-test.txt':'\n'.join(lines)},'expected':expected})
  pool=[{'arguments':c['arguments'],'files':c['files']} for c in cases]
  return definition(cases,[{'action':'function','target':'format_checker','inputs':choice(pool)}],[{'id':'close','kind':'require_source','target':'close(','message':'Close each file after using it.'}])
 if entry=='SortFilms.py':
  steps=[construct('sort_films','result',['films-input.txt','films-output.txt']),{'op':'file','target':'films-output.txt','record':True}]
  original=data.values['top500'].strip('\n');cases=[trace(steps,files={'films-input.txt':original})]
  for text in ('Alpha\t100\nBeta\t300\nGamma\t20','First\t9\nSecond\t80\nThird\t700','Only\t25'):
   cases.append(trace(steps,files={'films-input.txt':text}))
  rows={'kind':'list','min_length':2,'max_length':25,'items':{'kind':'join','separator':'\t','items':{'kind':'sequence','items':[{'kind':'string','min_length':3,'max_length':14,'alphabet':string.ascii_letters},{'kind':'transform','operation':'str','items':[number(1,1000000000)]}]}}}
  return definition(cases,[{'action':'trace','target':'__module__','steps':literal(steps),'files':{'films-input.txt':{'kind':'join','separator':'\n','items':rows}}}])
 if entry=='TAInfo.py':
  values={'ta_dict':{'Joshua':'Georgia','Jackie':'Vermont','Marguerite':'Tennessee'},'josh_val':'Georgia','jack_val':'Vermont','marg_val':'Tennessee'}
  rules=[{'id':'lookup-'+key,'kind':'require_source','target':f'ta_dict["{key}"]','message':'Read '+key+' from ta_dict.'} for key in values['ta_dict']]
  return definition([{'action':'variable','target':key,'expected':value} for key,value in values.items()],rules=rules)
 if entry=='PetOwner3.py':
  pool=[]
  for count in range(1,9):
   steps=[construct('Name','owner_name',['Alex','Reed']),construct('Owner','owner',[ref('owner_name')])]
   for i in range(count):
    steps += [construct('Name',f'name_{i}',['Pet'+str(i),'Reed']),construct('Pet',f'pet_{i}',[ref(f'name_{i}'),ref('owner')])]
   steps.append(call('owner.pets.__len__'))
   for i in range(count):steps.append(call('owner.pets.__contains__',[ref(f'pet_{i}')]))
   pool.append({'steps':steps})
  return definition([trace(p['steps']) for p in pool[:3]],[{'action':'trace','target':'__module__','inputs':choice(pool)}])
 if entry=='FibSeq.py':
  def steps(count):return [construct('FibSeq','sequence',[])]+[call('sequence.next_number') for _ in range(count)]
  return definition([trace(steps(count)) for count in (10,30,50)],[{'action':'trace','target':'__module__','inputs':choice([{'steps':steps(count)} for count in range(11,53)])}])
 if entry in {'Stack.py','Queue.py'}:
  cls,push,pop=('Stack','stack_push','stack_pop') if entry=='Stack.py' else ('Queue','enqueue','dequeue');rng=random.Random(1301);pool=[]
  def steps(values):return [construct(cls,'container',[])]+[call('container.'+push,[v],False) for v in values]+[call('container.'+pop) for _ in values]
  for i in range(64):pool.append({'steps':steps(rng.sample(range(-1000,1000),rng.randint(3,12)))})
  return definition([trace(steps([1,2,3])),trace(steps([7,-1,0,7]))],[{'action':'trace','target':'__module__','inputs':choice(pool)}],[{'id':'no-pop','kind':'forbid_source','target':'.pop','message':'Implement removal without using list.pop.'}] if cls=='Stack' else [])
 if entry=='FreeBodyObjects2.py':
  from prepare_native_graders_wave2 import inputs_for
  cases=[];pool=[]
  for seed in range(1301,1333):
   from native_spec_reader import Reader
   reader=Reader(seed).read(tree)
   for fields in inputs_for(reader,reader.values['test_cases'],'function',['forces']):
    steps=[construct('find_net_force','result',fields['arguments']),{'op':'read','target':'result.magnitude','record':True},call('result.get_angle')]
    candidate={'steps':steps}
    if candidate not in pool:pool.append(candidate)
    if seed==1301:cases.append(trace(steps,tolerance=0.011))
  return definition(cases,[{'action':'trace','target':'__module__','inputs':choice(pool),'tolerance':0.011}])
 return None


def burrito_cost():
    def steps(args):
        return [construct('Burrito','meal',args),call('meal.get_cost'),call('meal.set_meat',['steak'],False),call('meal.get_cost'),call('meal.set_guacamole',[True],False),call('meal.get_cost'),call('meal.set_extra_meat',[True],False),call('meal.get_cost')]
    examples=[['tofu',True,'white','black',False,False,False,False,False],['steak',False,'brown','pinto',True,True,True,True,True],['spaghetti',-1,'pink','garbonzo',False,False,False,False,False]]
    choices=[choice(['tofu','chicken','steak','pork',False,'invalid']),choice([True,False,-1,'invalid']),choice(['white','brown',False,'invalid']),choice(['black','pinto',False,'invalid'])]+[choice([True,False,'invalid']) for _ in range(5)]
    generated=steps(examples[0]);descriptors=[]
    for i,step in enumerate(generated):
        fields={k:literal(v) for k,v in step.items()}
        if i==0:fields['arguments']={'kind':'sequence','items':choices}
        descriptors.append({'kind':'record','fields':fields})
    return [trace(steps(args),tolerance=0.001) for args in examples],{'action':'trace','target':'__module__','steps':{'kind':'sequence','items':descriptors},'tolerance':0.001}
