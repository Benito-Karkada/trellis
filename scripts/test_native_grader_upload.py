import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import requests

from upload_native_graders import API,APIError,bundle_digest,load_bundle,process,private_json
from prepare_native_graders import Data,Review,derive,read_declarations
import ast


class FakeAPI:
    def __init__(self):
        self.part={'id':8,'course_id':1,'assignment_id':2,'kind':'coding','revision_id':10,'published_revision_id':10,
                   'metadata':{'vocareum_part_id':'123'},'grading':{'review_required':True,'maximum_points':'7.5'},
                   'files':[{'path':'main.py','visibility':'student'}]}
        self.calls=[];self.jobs={};self.fail_positive=False;self.pass_negative=False
    def request(self,method,path,body=None,revision=None,key=None):
        self.calls.append((method,path,deepcopy(body),revision,key))
        if method=='GET' and path=='/parts/8/':return deepcopy(self.part)
        if method=='GET' and path=='/parts/8/files/main.py':return {'text':'# Baseline\n'}
        if method=='PUT':
            self.part.update(revision_id=11,grading={'definition':body['definition'],'review_required':False,'maximum_points':'7.5'})
            return deepcopy(self.part)
        if method=='POST' and path=='/parts/8/test-runs/':
            source=body['files']['main.py'];positive='answer = 5' in source
            job=str(len(self.jobs)+1);self.jobs[job]=not self.fail_positive if positive else self.pass_negative
            return {'id':job}
        if method=='GET' and path.startswith('/test-runs/'):
            return {'status':'completed','result':{'passed':self.jobs[path.split('/')[2]]}}
        if method=='POST' and path=='/parts/8/publish/':
            self.part['published_revision_id']=11;return deepcopy(self.part)
        raise AssertionError((method,path))


class BatchUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.definition={'version':1,'cases':[{'id':'x','label':'Value','action':'variable','target':'answer','expected':5}]}
        self.row={'part_id':8,'assignment_id':2,'vocareum_part_id':'123','title':'Example','status':'ready',
                  'entrypoint':'main.py','expected_revision_id':10,'definition':'autograder.json',
                  'validation':{'status':'passed','positive':'correct.py','negatives':['wrong.py']}}
        (self.root/'autograder.json').write_text(json.dumps(self.definition));(self.root/'correct.py').write_text('answer = 5\n');(self.root/'wrong.py').write_text('answer = 4\n')
        self.row['validation']['bundle_sha256']=bundle_digest(self.row,self.definition,'answer = 5\n',['answer = 4\n'])
        self.args=argparse.Namespace(course=1,apply=True,publish=False,retry_failed=False,replace_existing=False,wait=3)
        self.state={'parts':{}};self.api=FakeAPI();self.saves=0
    def save(self):self.saves+=1
    def run_part(self):return process(self.api,self.root,self.row,self.state,self.save,self.args)
    def test_state_is_written_atomically_with_private_permissions(self):
        path=self.root/'state.json';private_json(path,{'parts':{}})
        self.assertEqual(json.loads(path.read_text()),{'parts':{}})
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.assertFalse(path.with_name('state.json.tmp').exists())
    def test_dry_run_makes_no_writes(self):
        self.args.apply=False;self.assertEqual(self.run_part(),'planned');self.assertTrue(all(c[0]=='GET' for c in self.api.calls));self.assertEqual(self.state,{'parts':{}})
    def test_upload_tests_two_verdicts_preserves_points_and_defaults_to_draft(self):
        self.assertEqual(self.run_part(),'verified_draft');self.assertEqual(len(self.api.jobs),2)
        write=next(c for c in self.api.calls if c[0]=='PUT');self.assertEqual(write[1],'/parts/8/grader/');self.assertNotIn('maximum_points',write[2]);self.assertNotIn('Ferb',str(write[2]))
        self.assertEqual(self.api.part['grading']['maximum_points'],'7.5');self.assertEqual(self.api.part['published_revision_id'],10)
        self.assertEqual(self.state['parts']['8']['phase'],'verified');self.assertGreater(self.saves,3)
    def test_resume_verified_draft_publishes_without_reupload_or_retesting(self):
        self.run_part();self.api.calls=[];self.args.publish=True
        self.assertEqual(self.run_part(),'published');self.assertEqual(self.api.part['published_revision_id'],11)
        self.assertFalse(any(c[0]=='PUT' or c[1].endswith('test-runs/') for c in self.api.calls))
    def test_interrupted_publish_is_reconciled_on_resume(self):
        self.run_part();self.state['parts']['8']['publish_key']='saved-before-request';self.api.part['published_revision_id']=11
        self.assertEqual(self.run_part(),'already_published');self.assertEqual(self.state['parts']['8']['phase'],'published')
    def test_interrupted_upload_reuses_key_and_original_precondition(self):
        digest=self.row['validation']['bundle_sha256'];self.state['parts']['8']={'digest':digest,'phase':'uploading','base_revision':10,'upload_key':'same-key'}
        self.api.part['revision_id']=11
        self.assertEqual(self.run_part(),'verified_draft');write=next(c for c in self.api.calls if c[0]=='PUT');self.assertEqual(write[3:],(10,'same-key'))
    def test_failed_correct_or_wrong_control_never_publishes(self):
        for positive in (True,False):
            with self.subTest(positive=positive):
                self.state={'parts':{}};self.api=FakeAPI();self.args.publish=True
                self.api.fail_positive=positive;self.api.pass_negative=not positive
                with self.assertRaisesRegex(ValueError,'wrong verdict'):self.run_part()
                self.assertEqual(self.api.part['published_revision_id'],10);self.assertEqual(self.state['parts']['8']['phase'],'failed')
    def test_target_course_reference_baseline_and_other_drafts_are_protected(self):
        for field,value in [('course_id',999),('assignment_id',999),('published_revision_id',9),('revision_id',12)]:
            with self.subTest(field=field):
                self.api=FakeAPI();self.api.part[field]=value
                with self.assertRaises(ValueError):self.run_part()
                self.assertFalse(any(c[0]!='GET' for c in self.api.calls))
        self.api=FakeAPI();self.api.part['metadata']['vocareum_part_id']='other'
        with self.assertRaises(ValueError):self.run_part()
    def test_changed_bundle_and_escaping_artifact_path_are_rejected(self):
        (self.root/'wrong.py').write_text('answer = 5\n')
        with self.assertRaisesRegex(ValueError,'changed since validation'):load_bundle(self.root,self.row)
        self.row['definition']='../outside.json'
        with self.assertRaisesRegex(ValueError,'outside'):load_bundle(self.root,self.row)
    def test_random_reference_is_hashed_and_uploaded_only_as_private_configuration(self):
        self.definition['random_cases']={'count':3,'oracle_path':'grader/reference.py','templates':[{'action':'variable','target':'answer','variables':{'x':{'kind':'integer','min':1,'max':10}}}]}
        reference='answer = x\n';self.row['reference']='reference.py'
        (self.root/'reference.py').write_text(reference);(self.root/'autograder.json').write_text(json.dumps(self.definition))
        self.row['validation']['bundle_sha256']=bundle_digest(self.row,self.definition,'answer = 5\n',['answer = 4\n'],reference)
        self.assertEqual(self.run_part(),'verified_draft')
        write=next(c for c in self.api.calls if c[0]=='PUT');self.assertEqual(write[2]['reference_source'],reference)
        self.assertTrue(all('reference_source' not in c[2] for c in self.api.calls if c[1].endswith('test-runs/')))
        (self.root/'reference.py').write_text('answer = 99\n')
        with self.assertRaisesRegex(ValueError,'changed since validation'):load_bundle(self.root,self.row)

    def test_retry_uses_same_idempotency_key_after_lost_connection(self):
        api=API('https://trellis.example.invalid','test-token')
        response=Mock(ok=True,status_code=200);response.json.return_value={'id':8}
        api.session.request=Mock(side_effect=[requests.ConnectionError(),response])
        with patch('upload_native_graders.time.sleep'):api.request('PUT','/parts/8/grader/',{},10,'stable-key')
        self.assertEqual(api.session.request.call_args_list[0].kwargs['headers'],api.session.request.call_args_list[1].kwargs['headers'])
        self.assertEqual(api.session.request.call_args.kwargs['headers']['Idempotency-Key'],'stable-key');api.session.close()


class ConversionBoundaryTests(unittest.TestCase):
    def test_data_reader_is_deterministic_and_does_not_eval_arbitrary_calls(self):
        expression=ast.parse('[(1, 2), (random.randint(1, 9), round(random.uniform(1, 9), 2))]',mode='eval').body
        self.assertEqual(Data().value(expression),Data().value(expression))
        with self.assertRaises(Review):Data().value(ast.parse('__import__("os").system("false")',mode='eval').body)
    def test_generated_test_mutations_and_unported_constraints_are_not_dropped(self):
        sources=["test_cases=[(1,)]\nvar_names=['x']\ntest_cases.append((2,))\ncheck_printed_test_cases(var_names,test_cases,'x.py',correct)",
                 "check_required_code(['close('], program)",
                 "var_names=['x']\ntest_cases=[(1,)]\ncheck_printed_test_cases(var_names,test_cases,'x.py',correct,within=True)"]
        for source in sources:
            tree=ast.parse(source)
            with self.assertRaises(Review):derive(tree,read_declarations(tree))
    def test_type_questions_keep_value_unconstrained(self):
        tree=ast.parse("expected_variables=[('quantity',int),('label',str)]")
        cases,kind=derive(tree,read_declarations(tree));self.assertEqual([c['action'] for c in cases],['variable_type','variable_type']);self.assertEqual(cases[0]['expected'],'int')


if __name__=='__main__':unittest.main()
