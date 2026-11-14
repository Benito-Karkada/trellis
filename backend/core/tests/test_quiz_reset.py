from django.test import TestCase, override_settings
from django.utils import timezone
from core.models import ActivityProgress, ExecutionJob, Membership, QuizAttempt, Workspace
from .test_studio import StudioTests


class QuizTestResetTests(TestCase):
    def setUp(self):
        StudioTests.setUp(self)
        self.quiz=self.activity.lesson
        self.quiz.metadata={'kind':'programming_quiz','exam_mode':True,'time_limit_minutes':20}
        self.quiz.save()
        self.staff_member=Membership.objects.get(user=self.staff)
        self.student_member=Membership.objects.get(user=self.student)
        for member in (self.staff_member,self.student_member):
            QuizAttempt.objects.create(membership=member,lesson=self.quiz,submitted_at=timezone.now())
            ActivityProgress.objects.create(user=member.user,activity=self.activity,score=1,completed=True)
            Workspace.objects.create(user=member.user,revision=self.revision,files={'main.py':'saved work'},generation=4)
        self.url=f'/api/quizzes/{self.quiz.pk}/reset-test/'

    def test_student_cannot_reopen_a_submitted_quiz(self):
        self.assertEqual(self.client.post(self.url,{},content_type='application/json').status_code,403)
        self.assertTrue(QuizAttempt.objects.filter(membership=self.student_member,submitted_at__isnull=False).exists())

    @override_settings(RUNNER_TOKEN='worker')
    def test_staff_reset_in_student_view_is_scoped_to_self_and_rejects_late_results(self):
        self.client.force_login(self.staff)
        self.client.post('/api/student-view/',{'enabled':True},content_type='application/json')
        job=ExecutionJob.objects.create(user=self.staff,revision=self.revision,generation=4,operation='submit',
            snapshot={'main.py':'saved work'},entrypoint='main.py',status='running',lease='old-lease')
        self.assertEqual(self.client.post(self.url,{},content_type='application/json').status_code,200)
        self.assertFalse(QuizAttempt.objects.filter(membership=self.staff_member,lesson=self.quiz).exists())
        self.assertFalse(ActivityProgress.objects.filter(user=self.staff,activity=self.activity).exists())
        own=Workspace.objects.get(user=self.staff,revision=self.revision)
        self.assertEqual(own.files,{'main.py':'print(1)'})
        self.assertEqual(own.generation,5)
        self.assertEqual(Workspace.objects.get(user=self.student,revision=self.revision).files,{'main.py':'saved work'})
        self.assertTrue(QuizAttempt.objects.filter(membership=self.student_member,submitted_at__isnull=False).exists())
        self.assertTrue(ActivityProgress.objects.filter(user=self.student,completed=True).exists())
        response=self.client.post(f'/api/runner/complete/{job.pk}/',{'lease':'old-lease','result':{'score_fraction':'1','passed':True}},
            content_type='application/json',HTTP_AUTHORIZATION='Bearer worker')
        self.assertEqual(response.status_code,409)
        started=self.client.post(f'/api/quizzes/{self.quiz.pk}/start/').json()
        self.assertFalse(started['submitted'])
        self.assertIsNotNone(started['expires_at'])

    def test_staff_cannot_target_another_membership(self):
        self.client.force_login(self.staff)
        response=self.client.post(self.url,{'membership':self.student_member.pk},content_type='application/json')
        self.assertEqual(response.status_code,400)
        self.assertEqual(QuizAttempt.objects.filter(lesson=self.quiz).count(),2)
