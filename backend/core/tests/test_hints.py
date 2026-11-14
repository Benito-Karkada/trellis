from django.test import TestCase
from django.utils import timezone
from core.models import ActivityProgress,Submission,QuestionCooldown,QuizAttempt,Membership,Revision
from .test_studio import StudioTests

class HintTests(TestCase):
    def setUp(self):
        StudioTests.setUp(self)
        self.revision.content={'version':1,'blocks':[{'id':'q','type':'multiple_choice','prompt':[{'type':'text','text':'Question'}],'choices':[{'id':'yes','content':[{'type':'text','text':'Yes'}]},{'id':'no','content':[{'type':'text','text':'No'}]}]}]}
        self.revision.grading={'questions':{'q':{'selection':'one','correct_choice_ids':['yes'],'choice_feedback_rules':{
            'yes':[{'selected':True,'content':[{'type':'text','text':'Why yes works'}]}],
            'no':[{'selected':True,'content':[{'type':'text','text':'Try a different approach'}]}]}}},'hints':[[{'type':'text','text':'General hint'}]]}
        self.revision.save()
        self.url=f'/api/hints/{self.revision.pk}/'
    def post(self,body):return self.client.post(self.url,body,content_type='application/json')
    def test_only_general_hints_are_available_before_correct_submission(self):
        response=self.post({'question_id':'q','response':'no'})
        self.assertEqual(response.status_code,200)
        text=str(response.json());self.assertIn('General hint',text)
        for private in ('correct_choice_ids','checks','score','Why yes works','Try a different approach'):
            self.assertNotIn(private,text)
        self.assertEqual(self.post({'question_id':'q','kind':'choice','choice_id':'no'}).status_code,403)
        self.assertFalse(ActivityProgress.objects.exists());self.assertFalse(Submission.objects.exists());self.assertFalse(QuestionCooldown.objects.exists())
    def test_wrong_feedback_survives_cooldown_and_refresh_but_does_not_unlock_other_answers(self):
        response=self.client.post(f'/api/submit-native/{self.revision.pk}/',{'responses':{'q':'no'}},content_type='application/json')
        self.assertIn('Try a different approach',str(response.json()['feedback']))
        self.assertIn('q',response.json()['locks'])
        detail=self.client.get(f'/api/studio/{self.activity.pk}/').json()
        self.assertEqual(detail['native_review']['responses']['q'],'no')
        self.assertIn('Try a different approach',str(detail['native_review']['feedback']))
        self.assertEqual(detail['solved_questions'],[])
        self.assertEqual(self.post({'question_id':'q','kind':'choice','choice_id':'yes'}).status_code,403)
        # Supplying a correct answer during cooldown must not unlock explanations.
        self.client.post(f'/api/submit-native/{self.revision.pk}/',{'responses':{'q':'yes'}},content_type='application/json')
        self.assertEqual(self.post({'question_id':'q','kind':'choice','choice_id':'no'}).status_code,403)
        detail=self.client.get(f'/api/studio/{self.activity.pk}/').json()
        self.assertEqual(detail['native_review']['responses']['q'],'no')

    def test_correct_submission_unlocks_review_without_changing_score_or_attempts(self):
        self.revision.grading['maximum_points']='1.5';self.revision.save()
        response=self.client.post(f'/api/submit-native/{self.revision.pk}/',{'responses':{'q':'yes'}},content_type='application/json')
        self.assertEqual(response.json()['solved_questions'],['q'])
        progress=ActivityProgress.objects.get(user=self.student);score=progress.score;count=Submission.objects.count()
        response=self.post({'question_id':'q','kind':'choice','choice_id':'no'})
        self.assertEqual(response.status_code,200);self.assertIn('Try a different approach',str(response.json()))
        progress.refresh_from_db();self.assertEqual(progress.score,score);self.assertEqual(Submission.objects.count(),count)
        detail=self.client.get(f'/api/studio/{self.activity.pk}/').json()
        self.assertEqual(detail['native_review']['responses']['q'],'yes')
        self.assertEqual(detail['solved_questions'],['q'])

    def test_unlock_is_per_question_even_when_the_exercise_is_not_complete(self):
        import copy
        block=copy.deepcopy(self.revision.content['blocks'][0]);block['id']='other'
        self.revision.content['blocks'].append(block)
        self.revision.grading['questions']['other']=copy.deepcopy(self.revision.grading['questions']['q']);self.revision.save()
        self.client.post(f'/api/submit-native/{self.revision.pk}/',{'responses':{'q':'yes','other':'no'}},content_type='application/json')
        self.assertFalse(ActivityProgress.objects.get(user=self.student).completed)
        self.assertEqual(self.post({'question_id':'q','kind':'choice','choice_id':'no'}).status_code,200)
        self.assertEqual(self.post({'question_id':'other','kind':'choice','choice_id':'yes'}).status_code,403)
    def test_other_revisions_and_staff_preview_remain_protected(self):
        self.assertEqual(self.post({'question_id':'q','preview':True}).status_code,403)
        unpublished=Revision.objects.create(activity=self.activity,number=2,content=self.revision.content,grading=self.revision.grading,created_by=self.staff)
        self.assertEqual(self.client.post(f'/api/hints/{unpublished.pk}/',{'question_id':'q'},content_type='application/json').status_code,404)
        self.client.force_login(self.staff)
        self.assertEqual(self.post({'question_id':'q','kind':'choice','choice_id':'unknown-choice','preview':True}).status_code,400)
    def test_closed_quiz_cannot_reveal_hints(self):
        lesson=self.activity.lesson;lesson.metadata={'kind':'programming_quiz','exam_mode':True};lesson.save()
        QuizAttempt.objects.create(membership=Membership.objects.get(user=self.student),lesson=lesson,submitted_at=timezone.now())
        self.assertEqual(self.post({'question_id':'q'}).status_code,403)
