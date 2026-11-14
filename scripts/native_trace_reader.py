"""Translate legacy class test declarations into public native observations.
No legacy code is imported or executed; constructors/methods become data steps.
"""
import ast,math
from native_spec_reader import Reader
from prepare_native_graders import Review,name
class Ref:
 def __init__(self,path):self.path=path
class TraceReader(Reader):
 def __init__(self,seed=1301):
  super().__init__(seed);self.steps=[];self.step_generators=[];self.expected=[];self.failures=[];self.generators={};self.values.update(program=None,success=True)
 def emit(self,op,target,expected=None,record=False,**kw):
  descriptors=kw.pop('_generators',{})
  step={'op':op,'target':target,'record':record,**kw}
  self.steps.append(step)
  self.step_generators.append({'kind':'record','fields':{key:descriptors.get(key,{'kind':'literal','value':value}) for key,value in step.items()}})
  if record:self.expected.append(expected)
 def input_rule(self,node):
  from prepare_native_graders_wave2 import generator
  if isinstance(node,ast.Name) and isinstance(self.values.get(node.id),Ref):return {'kind':'literal','value':self.wire(self.values[node.id])}
  try:
   rule=generator(node,self)
   from grading.spec import valid_value
   if not valid_value(rule):raise Review('Internal symbolic value.')
   return rule
  except (Review,TypeError,ValueError,KeyError):return {'kind':'literal','value':self.wire(self.value(node))}
 def wire(self,v):
  if isinstance(v,Ref):return {'$ref':v.path}
  if isinstance(v,(list,tuple)):return [self.wire(x) for x in v]
  if isinstance(v,dict):return {k:self.wire(x) for k,x in v.items()}
  return v
 def bind(self,t,v):
  if isinstance(t,ast.Attribute):
   parent=self.value(t.value)
   if not isinstance(parent,Ref):raise Review('Attribute write needs an object observation.')
   self.emit('set',parent.path+'.'+t.attr,value=self.wire(v));return
  super().bind(t,v)
 def value(self,n):
  if isinstance(n,ast.Attribute):
   text=ast.unparse(n)
   if text.startswith('program.globals.'):
    return Ref(text[len('program.globals.'):])
   if isinstance(n.value,ast.Name) and n.value.id=='program':return Ref(n.attr)
   try:v=super().value(n.value)
   except (Review,KeyError):v=None
   if isinstance(v,Ref):return Ref(v.path+'.'+n.attr)
  if isinstance(n,ast.Subscript) and isinstance(n.value,ast.Attribute) and isinstance(n.value.value,ast.Name) and n.value.value.id=='program' and n.value.attr in {'global_variables','global_classes','global_functions'}:
   return Ref(self.value(n.slice))
  if isinstance(n,ast.Call):
   f=name(n.func)
   if f=='setup_program':return (None,True)
   if f=='check_code_for_string':return False
   if f.startswith(('distribute_','get_results_','get_outdated_')):return None
   if f in {'check_required_code','check_forbidden_code','check_bad_consts'}:return []
   if f=='get_random_words' and n.args:return self.random.sample(['river','apple','cloud','python','violet','ocean','paper','copper','bright','tree','quiet','mountain','book','amber','forest','stone','winter','summer','clear','music','green','bridge','chair','silver','table','orange','water','lantern','garden','field'],self.value(n.args[0]))
   if f in {'radians','cos','sin','sqrt','floor','ceil'}:return getattr(math,f)(*[self.value(x) for x in n.args])
   if f=='eval':
    text=self.value(n.args[0])
    if not text.startswith('program.globals.') or not text[16:].isidentifier():raise Review('Only a declared class reference may be resolved.')
    return Ref(text[16:])
   if f in {'check_class_exists','check_variable_exists'}:
    target=self.value(n.args[0]);self.emit('exists_class' if f=='check_class_exists' else 'exists',target,expected=True,record=True);return (True,'')
   if f=='test_instance_creation':
    cls=self.value(n.args[0]);args=self.value(n.args[1]);key=f'_trellis_object_{len(self.steps)}';self.emit('construct',cls.path,name=key,arguments=self.wire(args),_generators={'arguments':self.input_rule(n.args[1])});return True,'',Ref(key)
   if f=='check_object_has_method':
    method=self.value(n.args[1]);obj=self.value(n.args[2]);self.emit('callable',obj.path+'.'+method,expected=True,record=True);return True,''
   if f=='check_attribute':
    field=self.value(n.args[1]);expected=self.value(n.args[2]);obj=self.value(n.args[3]);self.emit('read',obj.path+'.'+field,expected=expected,record=True);return True,''
   if f=='check_attributes':
    expected=self.value(n.args[1]);obj=self.value(n.args[2])
    for key,value in expected.items():self.emit('read',obj.path+'.'+key,expected=value,record=True)
    return []
   if f=='check_object_has_methods':
    methods=self.value(n.args[1]);obj=self.value(n.args[2])
    for method in methods:self.emit('callable',obj.path+'.'+method,expected=True,record=True)
    return []
   if f=='check_method_output':
    method=self.value(n.args[1]);obj=self.value(n.args[2]);expected=self.value(n.args[3]);kw={k.arg:k.value for k in n.keywords};args=self.value(kw['arguments']) if 'arguments' in kw else []
    self.emit('call',obj.path+'.'+method,expected=expected,record=True,arguments=self.wire(args),_generators={'arguments':self.input_rule(kw['arguments'])} if 'arguments' in kw else {});return True,''
   try:receiver=self.value(n.func)
   except (Review,KeyError):receiver=None
   if isinstance(receiver,Ref):
    args=[self.value(x) for x in n.args]
    if n.keywords:raise Review('Object constructor keyword arguments need explicit conversion.')
    if receiver.path.startswith('global_'):raise Review('Unsupported direct program inspection.')
    if '.' in receiver.path:self.emit('call',receiver.path,arguments=self.wire(args),_generators={'arguments':{'kind':'sequence','items':[self.input_rule(x) for x in n.args]}});return None
    key=f'_trellis_object_{len(self.steps)}';self.emit('construct',receiver.path,name=key,arguments=self.wire(args),_generators={'arguments':{'kind':'sequence','items':[self.input_rule(x) for x in n.args]}});return Ref(key)
  return super().value(n)
 def statements(self,body):
  for n in body:
   before=len(self.steps)
   if isinstance(n,ast.Try) and any(isinstance(h.type,ast.Name) and h.type.id=='TypeError' for h in n.handlers):
    attempted=next((x.value for x in n.body if isinstance(x,ast.Assign) and isinstance(x.value,ast.Call)),None)
    if attempted is not None:
     receiver=self.value(attempted.func)
     if isinstance(receiver,Ref):
      self.emit('exception',receiver.path,expected='TypeError',record=True,arguments=[self.wire(self.value(a)) for a in attempted.args]);continue
   if isinstance(n,(ast.Assign,ast.Expr)):
    try:
     if isinstance(n,ast.Assign):
      value=self.value(n.value)
      for t in n.targets:
       if isinstance(t,ast.Name) and not isinstance(value,Ref) and not any(isinstance(c,ast.Call) and (name(c.func).startswith(('check_','distribute_','get_results_')) or name(c.func) in {'test_instance_creation','setup_program'}) for c in ast.walk(n.value)):
        try:self.generators[t.id]=self.input_rule(n.value)
        except (Review,TypeError,KeyError,ValueError):pass
       self.bind(t,value)
     else:self.value(n.value)
    except (Review,KeyError,TypeError,ValueError,IndexError,AttributeError,ZeroDivisionError) as e:
     # Unknown grading operations cannot silently disappear.
     if any(isinstance(c,ast.Call) and (name(c.func).startswith('check_') or name(c.func)=='test_instance_creation') for c in ast.walk(n)) and not any(isinstance(c,ast.Call) and name(c.func)=='check_code_for_string' for c in ast.walk(n)):self.failures.append(str(e))
    continue
   super().statements([n])
