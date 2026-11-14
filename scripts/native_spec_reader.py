"""Bounded AST reader for legacy test DATA. Never imports or executes source code."""
import ast,math,operator,random,string,datetime
class VirtualFile:
 def __init__(self,files,name,mode="w"):
  self.files=files;self.name=name;self.mode=mode
  if "w" in mode:self.files[name]=""
 def write(self,value):
  text=value.decode() if isinstance(value,bytes) else value
  if len(self.files.get(self.name,''))+len(text)>1000000:raise ValueError('Virtual fixture file is too large.')
  self.files[self.name]=self.files.get(self.name,"")+text;return len(value)
 def flush(self):pass
 def close(self):pass

from prepare_native_graders import Review,name
class ObjectInput:
 def __init__(self,name,args):self.name=name;self.arguments=args;self.attributes={}
class Reader:
 def __init__(self,seed=1301):self.values={};self.files={};self.errors={};self.classes={};self.random=random.Random(seed);self.operations=0
 def tick(self):
  self.operations+=1
  if self.operations>1000000:raise Review('Test-data reader budget exceeded.')
 def bind(self,target,value):
  if isinstance(target,ast.Name):self.values[target.id]=value;self.errors.pop(target.id,None)
  elif isinstance(target,(ast.List,ast.Tuple)):
   if len(target.elts)!=len(value):raise Review('Data unpacking mismatch.')
   for t,v in zip(target.elts,value):self.bind(t,v)
  elif isinstance(target,ast.Attribute):
   obj=self.value(target.value)
   if not isinstance(obj,ObjectInput):raise Review('Only data objects may be mutated.')
   obj.attributes[target.attr]=value
  elif isinstance(target,ast.Subscript):self.value(target.value)[self.value(target.slice)]=value
  else:raise Review('Unsupported data assignment.')
 def value(self,n):
  self.tick()
  if isinstance(n,ast.Constant):return n.value
  if isinstance(n,ast.Name):
   if n.id in self.errors:raise Review('Incomplete test data '+n.id+': '+self.errors[n.id])
   if n.id in self.values:return self.values[n.id]
   raise Review('Unknown test data '+n.id)
  if isinstance(n,(ast.List,ast.Tuple,ast.Set)):
   return {ast.List:list,ast.Tuple:tuple,ast.Set:set}[type(n)](self.value(v) for v in n.elts)
  if isinstance(n,ast.Dict):return {self.value(k):self.value(v) for k,v in zip(n.keys,n.values)}
  if isinstance(n,ast.UnaryOp):return {ast.USub:operator.neg,ast.UAdd:operator.pos,ast.Not:operator.not_}[type(n.op)](self.value(n.operand))
  if isinstance(n,ast.BinOp):
   a,b=self.value(n.left),self.value(n.right)
   if isinstance(n.op,ast.Mult) and ((isinstance(a,(str,list,tuple)) and abs(b)>1000) or (isinstance(b,(str,list,tuple)) and abs(a)>1000)):raise Review('Data repetition too large.')
   if isinstance(n.op,ast.Pow) and (not isinstance(b,(int,float)) or abs(b)>100 or not isinstance(a,(int,float)) or abs(a)>1e6):raise Review('Data exponent is outside bounded limits.')
   v={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod,ast.Pow:operator.pow}[type(n.op)](a,b)
   if isinstance(v,(str,list,tuple,dict)) and len(v)>10000:raise Review('Test data too large.')
   return v
  if isinstance(n,ast.Compare):
   left=self.value(n.left)
   for op,right in zip(n.ops,n.comparators):
    right=self.value(right)
    if not {ast.Eq:operator.eq,ast.NotEq:operator.ne,ast.Lt:operator.lt,ast.LtE:operator.le,ast.Gt:operator.gt,ast.GtE:operator.ge,ast.In:lambda a,b:a in b,ast.NotIn:lambda a,b:a not in b}[type(op)](left,right):return False
    left=right
   return True
  if isinstance(n,ast.BoolOp):return (all if isinstance(n.op,ast.And) else any)(self.value(x) for x in n.values)
  if isinstance(n,ast.IfExp):return self.value(n.body if self.value(n.test) else n.orelse)
  if isinstance(n,ast.Subscript):return self.value(n.value)[self.value(n.slice)]
  if isinstance(n,ast.Slice):return slice(*(self.value(v) if v else None for v in (n.lower,n.upper,n.step)))
  if isinstance(n,ast.Attribute):
   receiver=None
   try:receiver=self.value(n.value)
   except (Review,KeyError):pass
   if isinstance(receiver,ObjectInput) and n.attr in receiver.attributes:return receiver.attributes[n.attr]
   if isinstance(receiver,(datetime.date,datetime.time,datetime.datetime,VirtualFile)) and n.attr in {'year','month','day','hour','minute','second','name'}:return getattr(receiver,n.attr)
   if isinstance(n.value,ast.Name) and n.value.id=='math' and n.attr in {'pi','e'}:return getattr(math,n.attr)
   raise Review('Unsupported data attribute.')
  if isinstance(n,(ast.ListComp,ast.GeneratorExp)):
   result=[]
   def visit(i):
    if i==len(n.generators):result.append(self.value(n.elt));return
    g=n.generators[i]
    for row in self.value(g.iter):
     self.bind(g.target,row)
     if all(self.value(c) for c in g.ifs):visit(i+1)
   visit(0);return result
  if isinstance(n,ast.Call):
   f=name(n.func);a=[self.value(v) for v in n.args];kw={v.arg:self.value(v.value) for v in n.keywords}
   if f in self.classes:
    obj=ObjectInput(f,a);definition=self.classes[f]
    init=next((x for x in definition.body if isinstance(x,ast.FunctionDef) and x.name=='__init__'),None)
    if init:
     local=dict(zip([x.arg for x in init.args.args[1:]],a));local.update(kw)
     for arg,default in zip(init.args.args[-len(init.args.defaults):],init.args.defaults):
      if arg.arg not in local:local[arg.arg]=self.value(default)
     for statement in init.body:
      if isinstance(statement,ast.Assign) and len(statement.targets)==1 and isinstance(statement.targets[0],ast.Attribute):
       target=statement.targets[0]
       if isinstance(target.value,ast.Name) and target.value.id=='self':
        if isinstance(statement.value,ast.Name) and statement.value.id in local:obj.attributes[target.attr]=local[statement.value.id]
        elif isinstance(statement.value,(ast.List,ast.Dict,ast.Constant)):obj.attributes[target.attr]=self.value(statement.value)
    return obj
   if f in {'get_random_words','get_random_names'}:
    count=a[0] if a else kw.get('count',1)
    words=['river','apple','cloud','violet','ocean','paper','copper','bright','tree','quiet','mountain','book','amber','forest','stone','winter','summer','clear','music','green','bridge','chair','silver','table','orange','water','lantern','garden','field','spring']
    first=['Alex','Jordan','Casey','Taylor','Morgan','Drew','Riley','Sam','Jamie','Avery','Robin','Lee'];last=['Hill','Chen','Rivera','Patel','Kim','Reed','Clark','Park','Smith','Young','Ng','Fox']
    if f=='get_random_words':return [self.random.choice(words) for _ in range(count)]
    result=[]
    for _ in range(count):
     a,b=self.random.choice(first),self.random.choice(last)
     result.append(b+', '+a if kw.get('last_first') else a+' '+b if kw.get('full') else a if kw.get('first',True) else b)
    return result
   if f in {'date','time'} and a:return {'date':datetime.date,'time':datetime.time}[f](*a,**kw)
   if f=='today':return datetime.date(2026,6,15)
   if f=='now':return datetime.datetime(2026,6,15,13,24,36)
   if f=='open':return VirtualFile(self.files,*a,**kw)
   if f=='NamedTemporaryFile':return VirtualFile(self.files,'test-'+str(len(self.files))+'.txt')
   if f=='get_random_string':
    size=a[0] if a else 10
    if type(size)is not int or not 0<=size<=10000:raise Review('Random text length is outside bounded limits.')
    alphabet=string.digits if kw.get('all_numbers') else string.ascii_uppercase if kw.get('all_caps') else string.ascii_lowercase if kw.get('all_lower') else string.ascii_letters
    return ''.join(self.random.choice(alphabet) for _ in range(size))
   if f in {'randint','uniform','choice','sample','shuffle','randrange'}:return getattr(self.random,f)(*a,**kw)
   if f in {'range','str','int','float','bool','len','round','chr','ord','sum','list','tuple','sorted','enumerate','zip','abs','min','max'}:
    allowed={'range':lambda *args:list(range(*args)) if len(range(*args))<=10000 else (_ for _ in ()).throw(Review('Data range is too large.')),'str':str,'int':int,'float':float,'bool':bool,'len':len,'round':round,'chr':chr,'ord':ord,'sum':sum,'list':list,'tuple':tuple,'sorted':sorted,'enumerate':lambda *args:list(enumerate(*args)),'zip':lambda *args:list(zip(*args)),'abs':abs,'min':min,'max':max};return allowed[f](*a,**kw)
   if isinstance(n.func,ast.Attribute) and f in {'format','strip','split','join','lower','upper','replace','append','extend','insert','sort','keys','values','items','write','flush','close','encode'}:
    receiver=self.value(n.func.value)
    if type(receiver) not in {str,list,dict,VirtualFile}:raise Review('Unsupported method receiver.')
    return getattr(receiver,f)(*a,**kw)
   raise Review('Unsupported data call '+f)
  raise Review('Unsupported test data '+type(n).__name__)
 def statements(self,body):
  for n in body:
   snapshot=dict(self.values)
   try:
    if isinstance(n,ast.Assign):
     v=self.value(n.value)
     for t in n.targets:self.bind(t,v)
    elif isinstance(n,ast.AugAssign):self.bind(n.target,self.value(ast.BinOp(left=n.target,op=n.op,right=n.value)))
    elif isinstance(n,ast.Expr):self.value(n.value)
    elif isinstance(n,ast.While):
     iterations=0
     while self.value(n.test):
      iterations+=1;self.tick()
      if iterations>1000:raise Review('Test data loop exceeded its budget.')
      self.statements(n.body)
    elif isinstance(n,ast.With):
     for item in n.items:
      value=self.value(item.context_expr)
      if item.optional_vars:self.bind(item.optional_vars,value)
     self.statements(n.body)
    elif isinstance(n,ast.For):
     for v in self.value(n.iter):self.tick();self.bind(n.target,v);self.statements(n.body)
    elif isinstance(n,ast.If):
     try:condition=self.value(n.test)
     except (Review,KeyError):
      # Runtime success/obsolete-source guards are not input-domain decisions.
      self.statements(n.body);continue
     self.statements(n.body if condition else n.orelse)
    elif isinstance(n,ast.Try):self.statements(n.body)
    elif isinstance(n,ast.FunctionDef) and n.name=='get_results':self.statements(n.body)
   except (Review,KeyError,TypeError,ValueError,IndexError,AttributeError,ZeroDivisionError,OverflowError) as exc:
    self.values=snapshot
    if isinstance(n,ast.Assign):
     for t in n.targets:
      if isinstance(t,ast.Name):self.errors[t.id]=str(exc)
    elif isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and isinstance(n.value.func.value,ast.Name):self.errors[n.value.func.value.id]=str(exc)
 def read(self,tree):
  self.classes={n.name:n for n in ast.walk(tree) if isinstance(n,ast.ClassDef)}
  self.statements(tree.body);return self
