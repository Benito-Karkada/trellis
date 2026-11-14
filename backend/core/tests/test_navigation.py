from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from core.models import Activity,ActivityProgress,Course,Lesson,Membership,QuizAttempt,Revision,Workspace
from .test_studio import StudioTests


class NavigationTests(TestCase):
    def setUp(self):
        StudioTests.setUp(self)

    def test_outline_query_count_does_not_grow_with_activities(self):
        for i in range(40):
            activity=Activity.objects.create(lesson=self.activity.lesson,title=f'Activity {i}')
            revision=Revision.objects.create(activity=activity,number=1,created_by=self.staff,
                content={'version':1,'blocks':[]},grading={'questions':{'a':{}},'maximum_points':'1.5'})
            activity.published_revision=revision;activity.save()
            ActivityProgress.objects.create(user=self.student,activity=activity,viewed=True,score='0.5')
        with CaptureQueriesContext(connection) as queries:
            response=self.client.get('/api/outline/')
        self.assertEqual(response.status_code,200)
        self.assertLessEqual(len(queries),8)
        lesson=response.json()['lessons'][0]
        self.assertEqual(lesson['metadata']['maximum_points'],'60')
        self.assertEqual(lesson['metadata']['earned_points'],'20')

    def test_first_login_has_no_resume_or_progress_until_content_is_opened(self):
        # Other users' history must never create a resume suggestion.
        ActivityProgress.objects.create(user=self.staff,activity=self.activity,viewed=True)
        self.student.set_password('fresh login password 1301');self.student.save()
        self.client.logout()
        self.assertTrue(self.client.login(username=self.student.username,password='fresh login password 1301'))
        for _ in range(2):
            self.assertIsNone(self.client.get('/api/outline/').json()['resume'])
        self.assertFalse(ActivityProgress.objects.filter(user=self.student).exists())
        self.assertEqual(self.client.post(f'/api/viewed/{self.activity.pk}/').status_code,200)
        self.assertEqual(self.client.get('/api/outline/').json()['resume']['activity_id'],self.activity.pk)

    def test_resume_is_latest_visible_activity_not_a_closed_quiz(self):
        ActivityProgress.objects.create(user=self.student,activity=self.activity,viewed=True)
        data=self.client.get('/api/outline/').json()
        self.assertEqual(data['resume']['activity_id'],self.activity.pk)
        quiz=Lesson.objects.create(course=self.activity.lesson.course,title='Quiz',metadata={'kind':'programming_quiz','exam_mode':True})
        question=Activity.objects.create(lesson=quiz,title='Question')
        revision=Revision.objects.create(activity=question,number=1,created_by=self.staff,content={'version':1,'blocks':[]})
        question.published_revision=revision;question.save()
        membership=Membership.objects.get(user=self.student)
        QuizAttempt.objects.create(membership=membership,lesson=quiz,submitted_at=timezone.now())
        ActivityProgress.objects.create(user=self.student,activity=question,viewed=True)
        self.assertEqual(self.client.get('/api/outline/').json()['resume']['activity_id'],self.activity.pk)
        self.activity.lesson.visibility='staff';self.activity.lesson.save()
        self.assertIsNone(self.client.get('/api/outline/').json()['resume'])

    def test_resume_excludes_every_programming_quiz_for_students_and_staff(self):
        ActivityProgress.objects.create(user=self.student,activity=self.activity,viewed=True)
        ActivityProgress.objects.create(user=self.staff,activity=self.activity,viewed=True)
        quiz=Lesson.objects.create(course=self.activity.lesson.course,title='Programming Quiz',
            metadata={'kind':'programming_quiz'})
        question=Activity.objects.create(lesson=quiz,title='Quiz Question')
        revision=Revision.objects.create(activity=question,number=1,created_by=self.staff,
            content={'version':1,'blocks':[]})
        question.published_revision=revision;question.save()
        for user in (self.student,self.staff):
            ActivityProgress.objects.create(user=user,activity=question,viewed=True)
        for user,student_view in ((self.student,False),(self.staff,False),(self.staff,True)):
            self.client.force_login(user)
            self.client.post('/api/student-view/',{'enabled':student_view},content_type='application/json')
            member=Membership.objects.get(user=user)
            for state in ('untimed','active','submitted'):
                with self.subTest(user=user.username,student_view=student_view,state=state):
                    quiz.metadata={'kind':'programming_quiz','exam_mode':state!='untimed'};quiz.save()
                    QuizAttempt.objects.filter(membership=member,lesson=quiz).delete()
                    if state!='untimed':
                        QuizAttempt.objects.create(membership=member,lesson=quiz,
                            submitted_at=timezone.now() if state=='submitted' else None)
                    data=self.client.get('/api/outline/').json()
                    self.assertEqual(data['resume']['activity_id'],self.activity.pk)
                    self.assertIn(quiz.pk,[lesson['id'] for lesson in data['lessons']])
        ActivityProgress.objects.filter(activity=self.activity).delete()
        self.assertIsNone(self.client.get('/api/outline/').json()['resume'])

    def test_running_preview_does_not_create_saved_workspace(self):
        self.client.force_login(self.staff)
        response=self.client.post(f'/api/execute/{self.revision.pk}/',{'operation':'run',
            'preview':True,'entrypoint':'main.py','files':{'main.py':'print(2)'}},content_type='application/json')
        self.assertEqual(response.status_code,200)
        self.assertFalse(Workspace.objects.filter(user=self.staff).exists())

    def test_instructor_can_choose_password_and_invalid_password_does_not_replace_it(self):
        self.student.set_password('old example password 1301');self.student.save()
        self.client.force_login(self.staff)
        member=Membership.objects.get(user=self.student)
        endpoint=f'/api/settings/enrollments/{member.pk}/login/'
        chosen='Chosen-login-1301!'
        response=self.client.post(endpoint,{'reset':True,'password':chosen},content_type='application/json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['password'],chosen)
        self.student.refresh_from_db()
        self.assertNotEqual(self.student.password,chosen)
        self.assertTrue(self.student.check_password(chosen))
        self.assertFalse(self.student.check_password('old example password 1301'))
        response=self.client.post(endpoint,{'reset':True,'password':'short'},content_type='application/json')
        self.assertEqual(response.status_code,400)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(chosen))

    def test_instructor_can_provision_student_login_but_ta_and_student_cannot(self):
        self.student.set_password('existing student password 1301');self.student.save()
        self.client.force_login(self.staff)
        member=Membership.objects.get(user=self.student)
        endpoint=f'/api/settings/enrollments/{member.pk}/login/'
        response=self.client.post(endpoint,{},content_type='application/json')
        self.assertEqual(response.status_code,409)  # Existing user has a password hash.
        response=self.client.post(endpoint,{'reset':True},content_type='application/json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Cache-Control'],'no-store')
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(response.json()['password']))
        self.assertFalse(self.student.is_staff or self.student.is_superuser)
        self.assertEqual(Membership.objects.get(pk=member.pk).role,'student')
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(endpoint,{'reset':True},content_type='application/json').status_code,403)
        Membership.objects.filter(user=self.staff).update(role='ta')
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(endpoint,{'reset':True},content_type='application/json').status_code,403)
