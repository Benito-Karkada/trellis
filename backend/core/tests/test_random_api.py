from django.test import TestCase,override_settings
from core.models import ExecutionJob,Revision,Workspace
from . import test_rest_api


class RandomGraderAPITests(TestCase):
    def setUp(self):
        test_rest_api.RestAPITests.setUp(self)
        self.activity.metadata={'kind':'coding'};self.activity.save()
        self.revision.grading={'entrypoint':'main.py'};self.revision.save()
        self.definition={'version':1,'cases':[{'id':'one','label':'One','action':'stdout','expected':'1\n'}],
                         'random_cases':{'count':3,'oracle_path':'grader/reference.py','templates':[{'action':'stdout','variables':{'value':{'kind':'integer','min':1,'max':100}}}]}}
    def api(self,*args,**kwargs):return test_rest_api.RestAPITests.api(self,*args,**kwargs)
    def test_random_definition_requires_a_private_reference_and_never_exposes_it_to_students(self):
        self.assertEqual(self.api('put',f'/parts/{self.activity.pk}/grader/',{'definition':self.definition},base=self.revision.pk).status_code,400)
        result=self.api('put',f'/parts/{self.activity.pk}/grader/',{'definition':self.definition,'reference_source':'print(value)\n'},base=self.revision.pk)
        self.assertEqual(result.status_code,200);rev=result.json()['revision_id']
        self.assertEqual(Revision.objects.get(pk=rev).files.get(path='grader/reference.py').visibility,'grader')
        self.api('post',f'/parts/{self.activity.pk}/publish/',{},base=rev)
        public=self.client.get(f'/api/studio/{self.activity.pk}/').json()
        self.assertNotIn('reference.py',str(public));self.assertNotIn('oracle_source',str(public))
    @override_settings(RUNNER_TOKEN='worker')
    def test_only_the_authenticated_execution_controller_receives_reference_and_immutable_baseline(self):
        result=self.api('put',f'/parts/{self.activity.pk}/grader/',{'definition':self.definition,'reference_source':'print(value)\n'},base=self.revision.pk)
        rev=Revision.objects.get(pk=result.json()['revision_id']);self.activity.published_revision=rev;self.activity.save()
        ExecutionJob.objects.create(user=self.student,revision=rev,operation='submit',generation=0,entrypoint='main.py',snapshot={'main.py':'student edits'})
        self.assertEqual(self.client.post('/api/runner/claim/').status_code,403)
        response=self.client.post('/api/runner/claim/',HTTP_AUTHORIZATION='Bearer worker').json()['job']
        self.assertEqual(response['oracle_source'],'print(value)\n');self.assertEqual(response['oracle_files']['main.py'],'print(1)')
        self.assertEqual(response['files']['main.py'],'student edits')
    def test_oversized_generators_or_nonprivate_reference_paths_are_rejected(self):
        self.definition['random_cases']['oracle_path']='main.py'
        self.assertEqual(self.api('put',f'/parts/{self.activity.pk}/grader/',{'definition':self.definition,'reference_source':'print(value)'},base=self.revision.pk).status_code,400)
    def test_file_fixtures_and_object_inputs_use_the_same_validated_contract(self):
        self.definition['cases'][0].update(files={'test.txt':'public fixture'})
        self.definition['random_cases']['templates']=[{'action':'function','target':'convert','arguments':[{'kind':'list','min_length':0,'max_length':3,'items':{'kind':'record','fields':{'name':{'kind':'string','min_length':1,'max_length':4,'alphabet':'abc'}}}}], 'argument_constructors':{'0':'Item'},'files':{'words.txt':{'kind':'join','separator':' ','items':{'kind':'list','min_length':2,'max_length':4,'items':{'kind':'string','min_length':1,'max_length':4,'alphabet':'xyz'}}}}}]
        response=self.api('put',f'/parts/{self.activity.pk}/grader/',{'definition':self.definition,'reference_source':'# trusted staff reference'},base=self.revision.pk)
        self.assertEqual(response.status_code,200)
        self.definition['cases'][0]['files']={'../escape':'no'}
        response=self.api('put',f'/parts/{self.activity.pk}/grader/',{'definition':self.definition,'reference_source':'# reference'},base=response.json()['revision_id'])
        self.assertEqual(response.status_code,400)
