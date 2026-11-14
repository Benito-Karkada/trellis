"""Generate fresh bounded inputs and observe an isolated staff reference solution."""
from copy import deepcopy
from dataclasses import replace
import random
import secrets
from .spec import Case,RunRequest,valid_value
from .spec import validate_random_cases


def sample(rule,rng):
    kind=rule['kind']
    if kind=='transform':
        args=[sample(child,rng) for child in rule['items']]
        op=rule['operation']
        if op=='multiply' and any(isinstance(v,(str,list)) for v in args) and any(type(v)is int and abs(v)>100 for v in args):raise ValueError('Generated repetition is too large.')
        value={'str':lambda a:str(a),'chr':lambda a:chr(a),'add':lambda a,b:a+b,'multiply':lambda a,b:a*b,'round':lambda a,b:round(a,b)}[op](*args)
        if not valid_value(value):raise ValueError('Generated transform is outside protocol limits.')
        return value
    if kind=='literal':return deepcopy(rule['value'])
    if kind=='integer':return rng.randint(rule['min'],rule['max'])
    if kind=='float':
        value=rng.uniform(rule['min'],rule['max'])
        return round(value,rule['digits']) if 'digits' in rule else value
    if kind=='choice':return deepcopy(rng.choice(rule['values']))
    if kind=='string':return ''.join(rng.choice(rule['alphabet']) for _ in range(rng.randint(rule['min_length'],rule['max_length'])))
    if kind=='list':return [sample(rule['items'],rng) for _ in range(rng.randint(rule['min_length'],rule['max_length']))]
    if kind=='join':
        values=sample(rule['items'],rng)
        if not isinstance(values,list) or any(not isinstance(v,str) for v in values):raise ValueError('Text joins need lists of strings.')
        return rule['separator'].join(values)
    if kind=='sequence':return [sample(child,rng) for child in rule['items']]
    if kind=='record':return {key:sample(child,rng) for key,child in rule['fields'].items()}
    raise ValueError('Unknown generator.')


def expand(exercise,executor,oracle_source,oracle_files=None,seed=None):
    spec=validate_random_cases(exercise.random_cases,len(exercise.cases))
    if not isinstance(oracle_source,str) or not oracle_source or len(oracle_source.encode())>256000:raise RuntimeError('Configure an isolated reference solution for random tests.')
    rng=random.Random(secrets.randbits(128) if seed is None else seed)
    generated=[]
    for index in range(spec['count']):
        for attempt in range(10):
            template=rng.choice(spec['templates']);arguments=[sample(v,rng) for v in template.get('arguments',[])];variables={k:sample(v,rng) for k,v in template.get('variables',{}).items()};case_seed=rng.randrange(2**31)
            inputs=sample(template['inputs'],rng) if 'inputs' in template else {}
            if not isinstance(inputs,dict) or set(inputs)-{'arguments','variables','files','steps'}:raise ValueError('Invalid combined public inputs.')
            arguments=inputs.get('arguments',arguments);variables=inputs.get('variables',variables)
            fixtures=inputs.get('files',{path:sample(rule,rng) for path,rule in template.get('files',{}).items()})
            if any(not isinstance(v,str) for v in fixtures.values()):raise ValueError('Fixture generators must produce text.')
            steps=inputs.get('steps',sample(template['steps'],rng) if 'steps' in template else [])
            constructors=template.get('argument_constructors',{})
            request=RunRequest(source=oracle_source,action=template['action'],target=template.get('target',''),arguments=tuple(arguments),variables=variables,
                               seed=case_seed,timeout_seconds=exercise.timeout_seconds,files={**(oracle_files or {}),**fixtures},argument_constructors=constructors,steps=steps,clock=template.get("clock"))
            observation=executor.run(request)
            if observation.status=='infrastructure_error':raise RuntimeError('Reference execution service is unavailable.')
            if observation.status!='ok':continue
            expected=observation.stdout if template['action'] in {'stdout','function_stdout'} else observation.value
            if not valid_value(expected):raise RuntimeError('Reference output cannot be represented by the grading protocol.')
            generated.append(Case(id=f'random-{index+1}',label=f'Random test {index+1}',action=template['action'],target=template.get('target',''),
                expected=expected,arguments=tuple(arguments),variables=variables,seed=case_seed,public=True,files=fixtures,argument_constructors=constructors,steps=steps,clock=template.get("clock"),
                strip_output=template.get('strip_output',False),tolerance=template.get('tolerance'),comparison=template.get('comparison','exact')))
            break
        else:raise RuntimeError('The reference could not produce a valid random case; no grade was recorded.')
    expanded=replace(exercise,cases=exercise.cases+tuple(generated),random_cases=None)
    expanded.validate();return expanded
