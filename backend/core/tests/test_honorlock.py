from datetime import timedelta
from decimal import Decimal
from django.test import TestCase, Client, override_settings
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from core.models import QuizAccessConfig, QuizUnlockFailure, QuizAttempt, Accommodation, ExecutionJob, Membership
from .test_studio import StudioTests


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class HonorlockTests(TestCase):
    def setUp(self):
        StudioTests.setUp(self)
        self.lesson=self.activity.lesson
        self.lesson.visibility='student'
        self.lesson.metadata={'kind':'programming_quiz','exam_mode':True,'time_limit_minutes':20}
        self.lesson.save()
        self.revision.grading={'entrypoint':'main.py','maximum_points':3,'definition':{'version':1,'cases':[]}}
        self.revision.save()
        self.password='Test-quiz-password-123456'
        self.settings=f'/api/settings/quizzes/{self.lesson.pk}/honorlock/'
        self.start=f'/api/quizzes/{self.lesson.pk}/start/'
        self.status=f'/api/quizzes/{self.lesson.pk}/status/'
        self.member=Membership.objects.get(user=self.student)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(self.settings,{'enabled':True,'password':self.password},content_type='application/json').status_code,200)
        self.client.force_login(self.student)

    def begin(self,password=None):
        return self.client.post(self.start,{'password':self.password if password is None else password},content_type='application/json')

    def test_hash_only_and_no_secret_in_student_or_staff_projection(self):
        value=QuizAccessConfig.objects.get(lesson=self.lesson)
        self.assertNotEqual(value.password_hash,self.password);self.assertTrue(check_password(self.password,value.password_hash))
        for path in ['/api/outline/',self.status]:
            response=self.client.get(path)
            self.assertNotContains(response,self.password);self.assertNotContains(response,value.password_hash)
        self.client.force_login(self.staff)
        response=self.client.get('/api/settings/quizzes/')
        self.assertTrue(response.json()['quizzes'][0]['honorlock_password_set'])
        self.assertNotContains(response,self.password);self.assertNotContains(response,value.password_hash)
        self.lesson.refresh_from_db();self.assertNotIn('password',str(self.lesson.metadata))

    def test_locked_quiz_blocks_every_student_content_and_execution_path(self):
        self.assertTrue(self.client.get(self.status).json()['access_required'])
        self.assertEqual(self.client.get('/api/outline/').json()['lessons'][0]['activities'],[])
        for path in [f'/api/studio/{self.activity.pk}/',f'/api/activities/{self.activity.pk}/',f'/api/files/{self.starter.pk}/',f'/api/files/{self.private.pk}/?mode=config']:
            self.assertIn(self.client.get(path).status_code,[403,404])
        for path,body in [(f'/api/workspaces/{self.revision.pk}/',{'files':{'main.py':'print(2)'}}),
            (f'/api/execute/{self.revision.pk}/',{'operation':'run','files':{'main.py':'print(2)'},'entrypoint':'main.py'}),
            (f'/api/execute/{self.revision.pk}/',{'operation':'submit','files':{'main.py':'print(2)'},'entrypoint':'main.py'})]:
            self.assertEqual(self.client.post(path,body,content_type='application/json').status_code,403)
        self.assertEqual(self.begin('').status_code,403)
        self.assertEqual(self.begin('incorrect').status_code,403)
        self.assertFalse(QuizAttempt.objects.exists())

    def test_success_starts_adjusted_timer_once_and_allows_repeated_run_submit(self):
        Accommodation.objects.create(membership=self.member,lesson=self.lesson,time_multiplier=Decimal('1.5'),extra_minutes=5)
        result=self.begin().json();self.assertEqual(result['effective_minutes'],'35')
        self.assertEqual(self.client.get(f'/api/studio/{self.activity.pk}/').status_code,200)
        for operation in ['run','submit','run','submit']:
            response=self.client.post(f'/api/execute/{self.revision.pk}/',{'operation':operation,'entrypoint':'main.py','files':{'main.py':'print(1)'}},content_type='application/json')
            self.assertEqual(response.status_code,200)
            ExecutionJob.objects.filter(pk=response.json()['id']).update(status='completed',result={})
        self.assertEqual(self.begin('').json()['expires_at'],result['expires_at'])
        self.assertEqual(QuizAttempt.objects.count(),1)

    def test_new_session_and_password_rotation_require_unlock_without_new_time(self):
        first=self.begin().json()
        self.client.logout();self.client.force_login(self.student)
        self.assertTrue(self.client.get(self.status).json()['access_required'])
        self.assertEqual(self.begin().json()['expires_at'],first['expires_at'])
        staff=Client();staff.force_login(self.staff)
        new='New-unique-password-987654'
        self.assertEqual(staff.post(self.settings,{'enabled':True,'password':new},content_type='application/json').status_code,200)
        self.assertEqual(self.client.get('/api/outline/').json()['lessons'][0]['activities'],[])
        self.assertEqual(self.begin().status_code,403)
        self.assertEqual(self.begin(new).json()['expires_at'],first['expires_at'])

    def test_finish_and_expiry_hide_work_and_prevent_reopening(self):
        self.begin()
        self.assertEqual(self.client.post(f'/api/quizzes/{self.lesson.pk}/finish/').status_code,200)
        self.assertTrue(self.begin().json()['submitted'])
        self.assertEqual(self.client.get(f'/api/studio/{self.activity.pk}/').status_code,403)
        QuizAttempt.objects.update(submitted_at=None,expires_at=timezone.now()-timedelta(seconds=1))
        self.assertTrue(self.client.get(self.status).json()['expired'])
        self.assertTrue(self.client.get('/api/outline/').json()['lessons'][0]['metadata']['attempt_submitted'])
        self.assertEqual(self.client.get(f'/api/studio/{self.activity.pk}/').status_code,403)
        self.assertTrue(self.begin().json()['expired'])

    def test_staff_authoring_bypasses_gate_but_student_view_requires_it(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(f'/api/studio/{self.activity.pk}/?mode=config').status_code,200)
        self.client.post('/api/student-view/',{'enabled':True},content_type='application/json')
        self.assertEqual(self.client.post(self.settings,{'enabled':False},content_type='application/json').status_code,403)
        self.assertEqual(self.client.get('/api/settings/quizzes/').status_code,403)
        self.assertEqual(self.client.get(f'/api/activities/{self.activity.pk}/preview/').status_code,403)
        self.assertEqual(self.begin('').status_code,403)
        self.assertEqual(self.begin().status_code,200)
        self.assertEqual(self.client.post(f'/api/quizzes/{self.lesson.pk}/reset-test/',{},content_type='application/json').status_code,200)
        self.assertTrue(self.client.get(self.status).json()['access_required'])
        self.assertFalse(QuizAttempt.objects.filter(membership__user=self.staff).exists())

    def test_persistent_throttling_before_attempt_creation(self):
        for _ in range(10):self.assertEqual(self.begin('wrong').status_code,403)
        response=self.begin();self.assertEqual(response.status_code,429);self.assertIn('Retry-After',response)
        self.assertFalse(QuizAttempt.objects.exists())
        state=QuizUnlockFailure.objects.get();state.locked_until=timezone.now()-timedelta(seconds=1);state.save()
        self.assertEqual(self.begin().status_code,200)

    def test_configuration_permissions_validation_and_exam_mode_dependency(self):
        self.assertEqual(self.client.post(self.settings,{'enabled':False},content_type='application/json').status_code,403)
        self.client.force_login(self.staff)
        for password in ['short','spaces are not allowed','quote-abcdefghijklmnop"']:
            self.assertEqual(self.client.post(self.settings,{'enabled':True,'password':password},content_type='application/json').status_code,400)
        self.assertEqual(self.client.post(f'/api/settings/quizzes/{self.lesson.pk}/',{'exam_mode':False},content_type='application/json').status_code,400)
        before=QuizAccessConfig.objects.get().password_hash
        self.assertEqual(self.client.post(self.settings,{'enabled':False},content_type='application/json').status_code,200)
        self.assertEqual(QuizAccessConfig.objects.get().password_hash,before)
        self.assertEqual(self.client.post(f'/api/settings/quizzes/{self.lesson.pk}/',{'exam_mode':False},content_type='application/json').status_code,200)
        self.assertEqual(self.client.post(self.settings,{'enabled':True},content_type='application/json').status_code,400)

    def test_csrf_required_for_password_post_and_anonymous_denied(self):
        browser=Client(enforce_csrf_checks=True);browser.force_login(self.student)
        self.assertEqual(browser.post(self.start,{'password':self.password},content_type='application/json').status_code,403)
        self.client.logout()
        self.assertEqual(self.client.get(self.status).status_code,403)
        self.assertEqual(self.begin().status_code,403)
