import unittest
from grading import Observation,RunRequest
from grading.engine import grade
from grading.manifest import load_definition


def definition():
    return {'version':1,'cases':[{'id':'fixed','label':'Fixed','action':'function','target':'double','arguments':[3],'expected':6}],
            'random_cases':{'count':3,'oracle_path':'grader/reference.py','templates':[{'action':'function','target':'double','arguments':[{'kind':'integer','min':1,'max':1000000}]}]}}


class Executor:
    def __init__(self,fail_reference=False):self.requests=[];self.fail_reference=fail_reference
    def run(self,request):
        self.requests.append(request)
        if request.source=='REFERENCE' and self.fail_reference:return Observation('runtime_error')
        return Observation('ok',request.arguments[0]*2 if request.source!='WRONG' else 0)


class RandomCaseTests(unittest.TestCase):
    def test_random_inputs_change_between_attempts_and_reproduce_within_an_attempt(self):
        exercise=load_definition(definition());executor=Executor()
        first=grade('def double(x): return x*2',exercise,executor,oracle_source='REFERENCE',random_seed=1)
        again=grade('def double(x): return x*2',exercise,Executor(),oracle_source='REFERENCE',random_seed=1)
        second=grade('def double(x): return x*2',exercise,Executor(),oracle_source='REFERENCE',random_seed=2)
        self.assertTrue(first['passed']);self.assertEqual(first['random_inputs'],again['random_inputs']);self.assertNotEqual(first['random_inputs'],second['random_inputs'])
        self.assertEqual(len(first['checks']),4)
    def test_private_reference_and_student_execute_as_separate_requests(self):
        executor=Executor();source='def double(x): return x*2'
        grade(source,load_definition(definition()),executor,oracle_source='REFERENCE',oracle_files={'data.txt':'immutable'},files={'main.py':'student-file'},random_seed=1)
        oracle=[r for r in executor.requests if r.source=='REFERENCE'];student=[r for r in executor.requests if r.source==source]
        self.assertEqual(len(oracle),3);self.assertEqual(len(student),4)
        self.assertTrue(all(r.files=={'data.txt':'immutable'} for r in oracle));self.assertTrue(all('REFERENCE' not in str(r.files) for r in student))
        self.assertTrue(all(not hasattr(r,'expected') for r in student))
    def test_reference_failure_or_missing_source_cannot_be_a_zero_grade(self):
        for executor,source in [(Executor(True),'REFERENCE'),(Executor(),None)]:
            with self.assertRaises(RuntimeError):grade('answer=1',load_definition(definition()),executor,oracle_source=source,random_seed=1)
    def test_bounded_generators_and_paths_are_validated(self):
        import copy
        for change in [{'count':200},{'oracle_path':'../secrets.py'},{'oracle_path':'main.py'}, {'templates':[{'action':'eval','target':'x'}]}]:
            d=definition();d['random_cases'].update(change)
            with self.assertRaises(ValueError):load_definition(d)
        huge={'kind':'list','min_length':100,'max_length':100,'items':{'kind':'list','min_length':100,'max_length':100,'items':{'kind':'list','min_length':100,'max_length':100,'items':{'kind':'literal','value':1}}}}
        d=definition();d['random_cases']['templates'][0]['arguments']=[huge]
        with self.assertRaises(ValueError):load_definition(d)
        d=definition();d['random_cases']['templates'][0]['arguments'][0]['max']=float('inf')
        with self.assertRaises(ValueError):load_definition(d)
    def test_random_input_failures_do_not_skip_fixed_cases(self):
        result=grade('WRONG',load_definition(definition()),Executor(),oracle_source='REFERENCE',random_seed=1)
        self.assertFalse(result['passed']);self.assertEqual(result['score_fraction'],'0');self.assertEqual(len(result['checks']),4)


@unittest.skipUnless(__import__('os').environ.get('RUN_DOCKER_TESTS')=='1','Opt-in Docker integration')
class RandomDockerTests(unittest.TestCase):
    def test_fresh_inputs_and_isolated_reference_are_real(self):
        from grading.docker_executor import DockerExecutor
        executor=DockerExecutor();exercise=load_definition(definition())
        reference='def double(x): return x+x'
        correct='import os\nassert not os.path.exists("grader/reference.py")\ndef double(x): return 2*x'
        first=grade(correct,exercise,executor,oracle_source=reference,random_seed=11)
        second=grade(correct,exercise,executor,oracle_source=reference,random_seed=12)
        wrong=grade('def double(x): return 6',exercise,executor,oracle_source=reference,random_seed=11)
        self.assertTrue(first['passed']);self.assertTrue(second['passed']);self.assertFalse(wrong['passed'])
        self.assertNotEqual(first['random_inputs'],second['random_inputs'])
        self.assertTrue(wrong['checks'][0]['passed']);self.assertFalse(wrong['checks'][1]['passed'])
