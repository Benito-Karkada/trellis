from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from core.models import ActivityProgress, Submission, QuestionCooldown, Membership, Revision, QuizAttempt, LearningEvent
from . import test_hints


class NativeResetTests(TestCase):
    def setUp(self):
        test_hints.HintTests.setUp(self)
        self.activity.metadata={'kind':'question'};self.activity.save()
        self.revision.grading['maximum_points']='1.5';self.revision.save()
        self.reset_url=f'/api/reset-native/{self.revision.pk}/'
        self.submit_url=f'/api/submit-native/{self.revision.pk}/'
        self.member=Membership.objects.get(user=self.student)

    def post(self,path,body=None):
        return self.client.post(path,body or {},content_type='application/json')

    def answer(self,value):
        return self.post(self.submit_url,{'responses':{'q':value}})

    def detail(self):
        return self.client.get(f'/api/studio/{self.activity.pk}/').json()

    def test_unanswered_and_wrong_answers_cannot_reset_or_skip_cooldown(self):
        self.assertEqual(self.client.get(self.reset_url).status_code,405)
        self.assertEqual(self.post(self.reset_url).status_code,409)
        self.assertFalse(ActivityProgress.objects.exists())
        self.answer('no')
        self.assertEqual(self.post(self.reset_url).status_code,409)
        self.assertTrue(QuestionCooldown.objects.filter(membership=self.member).exists())
        self.assertFalse(self.detail()['reset_available'])

    def test_reset_clears_attempt_and_explanations_preserving_grade_history_and_completion(self):
        self.answer('yes');before=ActivityProgress.objects.get(user=self.student);count=Submission.objects.count()
        self.assertTrue(self.detail()['reset_available'])
        response=self.post(self.reset_url)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['recorded_score'],'1.5')
        after=ActivityProgress.objects.get(user=self.student)
        self.assertEqual((after.score,after.maximum,after.completed),(before.score,before.maximum,before.completed))
        self.assertEqual(Submission.objects.count(),count)
        self.assertEqual(LearningEvent.objects.filter(kind='native_reset',membership=self.member).count(),1)
        detail=self.detail();self.assertEqual(detail['solved_questions'],[]);self.assertTrue(detail['native_practice'])
        self.assertFalse(detail['reset_available']);self.assertEqual(detail['native_review']['responses'],{})
        self.assertEqual(detail['native_review']['checks'],{})
        self.assertEqual(self.post(f'/api/hints/{self.revision.pk}/',{'question_id':'q','kind':'choice','choice_id':'no'}).status_code,403)
        with patch('core.canvas_sync.enqueue_grade') as sync:
            response=self.answer('no').json();sync.assert_not_called()
        self.assertTrue(response['practice']);self.assertFalse(response['passed'])
        self.assertEqual(response['score'],'0');self.assertEqual(response['recorded_score'],'1.5')
        self.assertIn('Try a different approach',str(response['feedback']));self.assertEqual(response['locks'],{})
        self.assertFalse(QuestionCooldown.objects.filter(membership=self.member).exists())
        self.assertEqual(self.answer('no').json()['locks'],{})
        detail=self.detail();self.assertEqual(detail['native_review']['responses'],{'q':'no'});self.assertEqual(detail['earned_points'],'1.5')
        self.assertEqual(self.post(self.reset_url).status_code,409)
        QuestionCooldown.objects.filter(membership=self.member).delete()
        self.assertTrue(self.answer('yes').json()['reset_available'])
        self.assertEqual(self.post(self.reset_url).status_code,200)

    def test_every_question_must_be_correct_before_reset(self):
        import copy
        block=copy.deepcopy(self.revision.content['blocks'][0]);block['id']='other'
        self.revision.content['blocks'].append(block)
        self.revision.grading['questions']['other']=copy.deepcopy(self.revision.grading['questions']['q']);self.revision.save()
        self.post(self.submit_url,{'responses':{'q':'yes','other':'no'}})
        self.assertEqual(self.post(self.reset_url).status_code,409)
        QuestionCooldown.objects.filter(membership=self.member).delete()
        self.post(self.submit_url,{'responses':{'q':'yes','other':'yes'}})
        self.assertEqual(self.post(self.reset_url).status_code,200)
        self.assertEqual(self.detail()['solved_questions'],[])

    def test_legacy_full_credit_records_can_reset_once_then_require_another_correct_attempt(self):
        ActivityProgress.objects.create(user=self.student,activity=self.activity,completed=True,score='1.5',maximum='1.5')
        self.assertEqual(self.detail()['solved_questions'],['q'])
        self.assertEqual(self.post(self.reset_url).status_code,200)
        self.assertEqual(self.detail()['solved_questions'],[])
        self.assertEqual(self.post(self.reset_url).status_code,409)

    def test_staff_own_reset_does_not_touch_student_work(self):
        self.answer('yes');student_state=ActivityProgress.objects.get(user=self.student).question_state
        self.client.force_login(self.staff);self.answer('yes')
        self.assertEqual(self.post(self.reset_url,{'membership':self.member.pk}).status_code,200)
        self.assertEqual(ActivityProgress.objects.get(user=self.student).question_state,student_state)
        self.assertEqual(ActivityProgress.objects.get(user=self.staff).score,ActivityProgress.objects.get(user=self.student).score)

    def test_correct_practice_after_deadline_can_reset_without_granting_credit(self):
        lesson=self.activity.lesson;lesson.metadata={'due_at':(timezone.now()-timedelta(hours=1)).isoformat()};lesson.save()
        response=self.answer('yes').json();self.assertTrue(response['practice']);self.assertTrue(response['reset_available'])
        self.assertEqual(self.post(self.reset_url).status_code,200)
        self.answer('no');p=ActivityProgress.objects.get(user=self.student)
        self.assertEqual(p.score,0);self.assertFalse(p.completed)

    def test_unpublished_closed_quiz_and_dropped_access_cannot_reset(self):
        self.answer('yes')
        draft=Revision.objects.create(activity=self.activity,number=2,content=self.revision.content,grading=self.revision.grading,created_by=self.staff)
        self.assertEqual(self.post(f'/api/reset-native/{draft.pk}/').status_code,404)
        lesson=self.activity.lesson;lesson.metadata={'kind':'programming_quiz','exam_mode':True};lesson.save()
        QuizAttempt.objects.create(membership=self.member,lesson=lesson,submitted_at=timezone.now())
        self.assertEqual(self.post(self.reset_url).status_code,403)
        QuizAttempt.objects.filter(membership=self.member).update(submitted_at=None,expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.post(self.reset_url).status_code,403)
        Membership.objects.filter(pk=self.member.pk).update(active=False)
        self.assertEqual(self.post(self.reset_url).status_code,403)
