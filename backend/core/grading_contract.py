"""Pure-data contract shared by Django and the isolated execution controller."""
import math


def bounded(value, depth=0):
    if depth>16:raise ValueError('Generator data is nested too deeply.')
    if type(value) in {int,float}:
        if not math.isfinite(value) or abs(value)>1e12:raise ValueError('Generator value is outside the supported range.')
    elif value is None or type(value)is bool:pass
    elif isinstance(value,str):
        if len(value)>65536:raise ValueError('Generator string is too long.')
    elif isinstance(value,list):
        if len(value)>1000:raise ValueError('Generator collection is too long.')
        for child in value:bounded(child,depth+1)
    elif isinstance(value,dict):
        if len(value)>1000 or any(not isinstance(k,str) for k in value):raise ValueError('Generator dictionaries need string keys.')
        for child in value.values():bounded(child,depth+1)
    else:raise ValueError('Unsupported generator value.')


def validate_generator(value, depth=0):
    if depth>12 or not isinstance(value,dict):raise ValueError('Invalid input generator.')
    kind=value.get('kind')
    if kind=='literal':
        if set(value)!={'kind','value'}:raise ValueError('Literal generators need value.')
        bounded(value['value']);return
    if kind in {'integer','float'}:
        allowed={'kind','min','max'} | ({'digits'} if kind=='float' else set())
        if set(value)-allowed or not {'min','max'}<=set(value):raise ValueError('Numeric generators need min and max.')
        lo,hi=value['min'],value['max']
        if any(type(x) not in {int,float} or not math.isfinite(x) or abs(x)>1e9 for x in (lo,hi)) or lo>hi:raise ValueError('Invalid numeric generator bounds.')
        if kind=='integer' and (type(lo)is not int or type(hi)is not int):raise ValueError('Integer bounds must be integers.')
        if 'digits' in value and (type(value['digits'])is not int or not 0<=value['digits']<=8):raise ValueError('Float digits must be 0–8.')
    elif kind=='transform':
        if set(value)!={'kind','operation','items'} or value['operation'] not in {'str','chr','add','multiply','round'} or not isinstance(value['items'],list) or not 1<=len(value['items'])<=2:raise ValueError('Invalid bounded transform.')
        if (value['operation'] in {'str','chr'} and len(value['items'])!=1) or (value['operation'] in {'add','multiply','round'} and len(value['items'])!=2):raise ValueError('Transform arity is invalid.')
        for child in value['items']:validate_generator(child,depth+1)
    elif kind=='choice':
        if set(value)!={'kind','values'} or not isinstance(value['values'],list) or not 1<=len(value['values'])<=1000:raise ValueError('Choice generators need a nonempty bounded values list.')
        bounded(value['values'])
    elif kind in {'list','string'}:
        allowed={'kind','min_length','max_length','items' if kind=='list' else 'alphabet'}
        if set(value)!=allowed:raise ValueError('Collection generator fields are invalid.')
        lo,hi=value['min_length'],value['max_length']
        if type(lo)is not int or type(hi)is not int or not 0<=lo<=hi<=100:raise ValueError('Collection lengths must be 0–100.')
        if kind=='list':validate_generator(value['items'],depth+1)
        elif not isinstance(value['alphabet'],str) or not 1<=len(value['alphabet'])<=128:raise ValueError('String generators need an alphabet of 1–128 characters.')
    elif kind=='join':
        if set(value)!={'kind','separator','items'} or not isinstance(value['separator'],str) or len(value['separator'])>16:raise ValueError('Invalid text join generator.')
        validate_generator(value['items'],depth+1)
    elif kind=='record':
        if set(value)!={'kind','fields'} or not isinstance(value['fields'],dict) or len(value['fields'])>100:raise ValueError('Invalid record generator.')
        for key,child in value['fields'].items():
            if not isinstance(key,str):raise ValueError('Record keys must be strings.')
            validate_generator(child,depth+1)
    elif kind=='sequence':
        if set(value)!={'kind','items'} or not isinstance(value['items'],list) or len(value['items'])>500:raise ValueError('Invalid fixed sequence generator.')
        for child in value['items']:validate_generator(child,depth+1)
    else:raise ValueError('Unknown generator kind.')


def generator_cost(rule):
    """Bound expansion before allocating nested generated collections."""
    kind=rule['kind']
    if kind=='list':return 1+rule['max_length']*generator_cost(rule['items'])
    if kind=='transform':return 64 if rule['operation']=='str' else sum(generator_cost(child) for child in rule['items'])+1
    if kind=='sequence':return 1+sum(generator_cost(child) for child in rule['items'])
    if kind=='record':return 1+sum(generator_cost(child) for child in rule['fields'].values())
    if kind=='join':return (1+len(rule['separator']))*generator_cost(rule['items'])
    if kind=='string':return 1+rule['max_length']
    if kind=='literal':return data_cost(rule['value'])
    if kind=='choice':return max(data_cost(child) for child in rule['values'])
    return 1


def data_cost(value):
    if isinstance(value,str):return 1+len(value)
    if isinstance(value,list):return 1+sum(data_cost(child) for child in value)
    if isinstance(value,dict):return 1+sum(len(key)+data_cost(child) for key,child in value.items())
    return 1


def validate_random_cases(value, fixed_count=0):
    if not isinstance(value,dict) or set(value)!={'count','oracle_path','templates'}:raise ValueError('Random cases need count, oracle_path and templates.')
    count=value['count']
    if type(count)is not int or not 1<=count<=8 or fixed_count+count>200:raise ValueError('Use 1–8 random cases and at most 200 total cases.')
    path=value['oracle_path']
    if not isinstance(path,str) or not path.startswith('grader/') or not path.endswith('.py') or '\\' in path or any(p in {'','.','..'} for p in path.split('/')):raise ValueError('Reference source must be a private grader Python file.')
    templates=value['templates']
    if not isinstance(templates,list) or not 1<=len(templates)<=10:raise ValueError('Use 1–10 random input templates.')
    for template in templates:
        if not isinstance(template,dict) or set(template)-{'action','target','arguments','variables','strip_output','tolerance','files','argument_constructors','steps','clock','inputs','comparison'}:raise ValueError('Invalid random template fields.')
        if template.get('action') not in {'stdout','function','variable','variable_type','trace','function_file','function_stdout','recursion','module_outcome'}:raise ValueError('Unsupported random case action.')
        if template['action'] not in {'stdout','function_stdout'} and (not isinstance(template.get('target'),str) or not template['target'].isidentifier()):raise ValueError('Random checks need a target identifier.')
        if type(template.get('strip_output',False))is not bool or (template.get('strip_output') and template['action'] not in {'stdout','function_stdout'}):raise ValueError('Only stdout supports output stripping.')
        if template.get('comparison','exact') not in {'exact','contains','numeric_text','string','whitespace','python'}:raise ValueError('Unknown comparison mode.')
        if 'tolerance' in template and (type(template['tolerance'])not in {int,float} or not math.isfinite(template['tolerance']) or template['tolerance']<0):raise ValueError('Invalid random comparison tolerance.')
        args=template.get('arguments',[]);variables=template.get('variables',{})
        if not isinstance(args,list) or len(args)>100 or not isinstance(variables,dict) or len(variables)>100:raise ValueError('Invalid random arguments or variable inputs.')
        for descriptor in args:validate_generator(descriptor)
        for key,descriptor in variables.items():
            if not isinstance(key,str) or not key.isidentifier():raise ValueError('Random variable keys need identifiers.')
            validate_generator(descriptor)
        if 'inputs' in template:
            if set(template)&{'arguments','variables','files','steps'}:raise ValueError('Combined inputs cannot be mixed with separate input generators.')
            validate_generator(template['inputs'])
        if 'clock' in template:
            import datetime
            if not isinstance(template['clock'],str):raise ValueError('Clock needs an ISO datetime.')
            datetime.datetime.fromisoformat(template['clock'])
        if 'steps' in template:validate_generator(template['steps'])
        fixtures=template.get('files',{})
        if not isinstance(fixtures,dict) or len(fixtures)>20:raise ValueError('Use at most 20 test fixture files.')
        for path,descriptor in fixtures.items():
            validate_fixture_path(path);validate_generator(descriptor)
        validate_constructors(template.get('argument_constructors',{}),len(args))
        if sum(generator_cost(child) for child in [*args,*variables.values(),*fixtures.values(),*([template['steps']] if 'steps' in template else []),*([template['inputs']] if 'inputs' in template else [])])>50000:raise ValueError('Generated inputs are too large.')
    return value


def validate_fixture_path(path):
    if not isinstance(path,str) or not path or path.startswith('/') or '\\' in path or any(p in {'','.','..'} for p in path.split('/')) or path.startswith(('grader/','solutions/','private/')):raise ValueError('Use relative public test fixture paths.')


def validate_constructors(value,argument_count):
    if not isinstance(value,dict) or len(value)>argument_count:raise ValueError('Invalid argument constructors.')
    for index,name in value.items():
        if not isinstance(index,str) or not index.isdigit() or not 0<=int(index)<argument_count or not isinstance(name,str) or not name.isidentifier():raise ValueError('Argument constructors need an argument index and class identifier.')


def validate_trace(steps):
    if not isinstance(steps,(list,tuple)) or not 1<=len(steps)<=500:raise ValueError('Trace needs 1–500 public observation steps.')
    for step in steps:
        if not isinstance(step,dict) or step.get('op') not in {'construct','read','call','set','exists','exists_class','callable','file','exception'}:raise ValueError('Unknown trace observation.')
        if set(step)-{'op','name','target','arguments','value','record'}:raise ValueError('Unknown trace fields.')
        if step.get('op')=='construct' and (not isinstance(step.get('name'),str) or not step['name'].isidentifier()):raise ValueError('Constructed objects need an identifier.')
        if step['op']=='file':validate_fixture_path(step.get('target'))
        elif not isinstance(step.get('target'),str) or any(not part.isidentifier() for part in step['target'].split('.')):raise ValueError('Trace targets need dotted identifiers.')
        if 'record' in step and type(step['record'])is not bool:raise ValueError('Record must be boolean.')
        if 'arguments' in step and not isinstance(step['arguments'],list):raise ValueError('Trace arguments must be a list.')


def validate_observation_expected(action,steps,expected):
    if action=='trace':
        count=sum(step.get('record',step['op'] in {'read','call','exists','exists_class','callable','file','exception'}) for step in steps)
        if not isinstance(expected,list) or len(expected)!=count:raise ValueError('Trace expectations must match the recorded public observations.')
    if action=='module_outcome':
        if not isinstance(expected,dict) or set(expected)!={'exception','message','stdout'} or not isinstance(expected['stdout'],str):raise ValueError('Module outcomes need exception, message and stdout.')
        if any(expected[k] is not None and not isinstance(expected[k],str) for k in ('exception','message')):raise ValueError('Exception outcomes must be text or null.')
