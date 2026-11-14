import json,os,random,unittest
from grading.manifest import load_definition
from grading.random_cases import sample
from grading.spec import RunRequest
try:
 from trellis_contract import validate_generator,validate_trace
except ModuleNotFoundError:
 from core.grading_contract import validate_generator,validate_trace
class NativeObservationTests(unittest.TestCase):
 def test_bounded_transforms_and_correlated_inputs(self):
  rule={'kind':'transform','operation':'str','items':[{'kind':'integer','min':100,'max':100000}]}
  validate_generator(rule);self.assertNotEqual(sample(rule,random.Random(1)),sample(rule,random.Random(2)))
  bad={'kind':'transform','operation':'eval','items':[{'kind':'literal','value':'1'}]}
  with self.assertRaises(ValueError):validate_generator(bad)
 def test_trace_rejects_unknown_operations_and_paths(self):
  for steps in ([{'op':'exec','target':'x'}],[{'op':'read','target':'x[0]'}],[]):
   with self.assertRaises(ValueError):validate_trace(steps)
 def test_private_observer_has_no_expected_field(self):
  from dataclasses import asdict
  request=RunRequest('x=1',action='trace',target='__module__',steps=({'op':'read','target':'x'},))
  self.assertNotIn('expected',asdict(request));self.assertNotIn('reference',asdict(request))
@unittest.skipUnless(os.environ.get('RUN_DOCKER_TESTS')=='1','Opt-in Docker integration')
class NativeObservationDockerTests(unittest.TestCase):
 def setUp(self):
  from grading.docker_executor import DockerExecutor
  self.executor=DockerExecutor()
 def test_class_state_and_method_observations(self):
  source='class Counter:\n def __init__(self,n): self.value=n\n def add(self,n): self.value+=n\n'
  steps=[{'op':'exists_class','target':'Counter','record':True},{'op':'construct','target':'Counter','name':'c','arguments':[3]},{'op':'call','target':'c.add','arguments':[4],'record':False},{'op':'read','target':'c.value'}]
  o=self.executor.run(RunRequest(source,action='trace',target='__module__',steps=steps));self.assertEqual((o.status,o.value),('ok',[True,7]))
 def test_function_file_uses_fresh_public_fixture(self):
  source='def append(name,text):\n with open(name,"a") as f:f.write(text)\n'
  o=self.executor.run(RunRequest(source,action='function_file',target='append',arguments=('a.txt','new'),files={'a.txt':'existing '}));self.assertEqual(o.value,'existing new')
 def test_frozen_clock_and_real_input_types(self):
  source='from datetime import date,datetime\ndef info(value): return [isinstance(value,date),str(date.today()),str(datetime.now()),str(type(date.today()))]'
  o=self.executor.run(RunRequest(source,action='function',target='info',arguments=({'$date':[2001,2,3]},),clock='2030-04-05T06:07:08'))
  self.assertEqual(o.value,[True,'2030-04-05','2030-04-05 06:07:08',"<class 'datetime.date'>"])
 def test_cyclic_object_inputs_and_shared_identity(self):
  source='class Owner:\n def __init__(self,name): self.name=name;self.pets=[]\nclass Pet:\n def __init__(self,owner):self.owner=owner\ndef valid(owner):return owner.pets[0].owner is owner'
  owner={'$class':'Owner','$id':'owner','arguments':['Alex'],'attributes':{'pets':[{'$class':'Pet','$id':'pet','arguments':[{'$object_ref':'owner'}]}]}}
  o=self.executor.run(RunRequest(source,action='function',target='valid',arguments=(owner,)));self.assertEqual((o.status,o.value),('ok',True))

@unittest.skipUnless(os.environ.get('RUN_DOCKER_TESTS')=='1','Opt-in Docker integration')
class ConstructorExceptionTests(unittest.TestCase):
 def test_exception_type_is_an_observation_not_an_expected_answer(self):
  from grading.docker_executor import DockerExecutor
  source='class Number:\n def __init__(self,value,even):self.value=value;self.even=even'
  steps=[{'op':'exception','target':'Number','arguments':[],'record':True}]
  observation=DockerExecutor().run(RunRequest(source,action='trace',target='__module__',steps=steps))
  self.assertEqual((observation.status,observation.value),('ok',['TypeError']))

@unittest.skipUnless(os.environ.get('RUN_DOCKER_TESTS')=='1','Opt-in Docker integration')
class PublicOutcomeTests(unittest.TestCase):
 def test_intentional_uncaught_exception_is_observed_without_traceback_line_numbers(self):
  from grading.docker_executor import DockerExecutor
  source='mystery_value=9\ntry: print(10/mystery_value)\nexcept ZeroDivisionError: print("Not possible")'
  executor=DockerExecutor()
  failure=executor.run(RunRequest(source,action='module_outcome',target='__module__',variables={'mystery_value':'0'}))
  self.assertEqual(failure.status,'ok');self.assertEqual(failure.value['exception'],'TypeError')
  normal=executor.run(RunRequest(source,action='module_outcome',target='__module__',variables={'mystery_value':0}))
  self.assertEqual(normal.value,{'exception':None,'message':None,'stdout':'Not possible'})
 def test_public_getter_fixture_does_not_require_a_student_class_definition(self):
  from grading.docker_executor import DockerExecutor
  fixture={'$fixture':{'attributes':{'cost':7.75},'getters':{'get_cost':'cost'}}}
  source='def total_cost(items):return sum((item.get_cost() for item in items),0.0)'
  result=DockerExecutor().run(RunRequest(source,action='function',target='total_cost',arguments=([fixture,fixture],)))
  self.assertEqual((result.status,result.value),('ok',15.5))
