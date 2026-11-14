from django.test import TestCase
from core.models import Activity,Revision,ActivityProgress,Workspace,Membership,Submission
from core.combine_analysis import combine_group
from . import test_studio


class CombinedAnalysisTests(TestCase):
    def setUp(self):
        test_studio.StudioTests.setUp(self)
        self.lesson=self.activity.lesson;self.group='Analysis exercise'
        self.activity.metadata={'kind':'coding','sandbox':True,'group':self.group};self.activity.position=2;self.activity.save()
        reading=Activity.objects.create(lesson=self.lesson,title='Context',position=1,metadata={'kind':'reading','group':self.group})
        r=Revision.objects.create(activity=reading,number=1,created_by=self.staff,content={'version':1,'blocks':[{'id':'document','type':'document','content':[{'type':'text','text':'Dataset instructions'}]}]},grading={'maximum_points':'0'})
        reading.published_revision=r;reading.save()
        self.question=Activity.objects.create(lesson=self.lesson,title='Answers',position=3,metadata={'kind':'question','group':self.group})
        content={'version':1,'blocks':[{'id':'q','type':'fill_blank','prompt':[{'type':'text','text':'Answer?'}],'input':{'kind':'text'}}]}
        self.native=Revision.objects.create(activity=self.question,number=1,created_by=self.staff,content=content,grading={'maximum_points':'1.5','questions':{'q':{'answers':['yes']}}})
        self.question.published_revision=self.native;self.question.save()
        Workspace.objects.create(user=self.student,revision=self.revision,files={'main.py':'print("saved")','grader/tests.json':'never copy'})
        ActivityProgress.objects.create(user=self.student,activity=self.question,score='1.5',maximum='1.5',completed=True,question_state={'q':{'solved':True,'correct':True,'response':'yes'}})
        Submission.objects.create(membership=Membership.objects.get(user=self.student),revision=self.native,response={'q':'yes'})
    def test_combination_preserves_question_ids_grading_work_and_history(self):
        primary,changed=combine_group(self.lesson,self.group,'data.csv',b'a,b\n1,2\n',self.staff)
        self.assertTrue(changed);self.assertEqual(primary.pk,self.question.pk);self.assertEqual(primary.published_revision.grading,self.native.grading)
        self.assertEqual([b['id'] for b in primary.published_revision.content['blocks']],['context_'+str(primary.metadata['combined_sources'][0])+'_document','analysis_workspace','q'])
        detail=self.client.get(f'/api/studio/{primary.pk}/').json();self.assertEqual(detail['workspace']['main.py'],'print("saved")');self.assertIn('data.csv',detail['workspace']);self.assertNotIn('grader/tests.json',detail['workspace'])
        self.assertEqual(detail['earned_points'],'1.5');self.assertEqual(Submission.objects.count(),1)
        self.assertEqual(Activity.objects.filter(lesson=self.lesson,deleted_at=None).count(),1)
        self.assertFalse(combine_group(self.lesson,self.group,'data.csv',b'a,b\n1,2\n',self.staff)[1])
    def test_workspace_runs_but_only_native_answers_can_be_submitted_for_credit(self):
        primary,_=combine_group(self.lesson,self.group,'data.csv',b'a,b\n1,2\n',self.staff)
        files=self.client.get(f'/api/studio/{primary.pk}/').json()['workspace'];revision=primary.published_revision_id
        body={'operation':'run','files':files,'entrypoint':'main.py'}
        self.assertEqual(self.client.post(f'/api/execute/{revision}/',body,content_type='application/json').status_code,200)
        body['operation']='submit';self.assertEqual(self.client.post(f'/api/execute/{revision}/',body,content_type='application/json').status_code,400)
        response=self.client.post(f'/api/submit-native/{revision}/',{'responses':{'q':'yes'}},content_type='application/json')
        self.assertEqual(response.status_code,200);self.assertTrue(response.json()['passed'])
