from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from core.models import Course, Membership, LoginThrottle
from core.security import login_allowed
from core.rest.auth import issue_token, SCOPES


class SecurityTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(title='Security test', term='Test')
        self.user = get_user_model().objects.create_user('ta@example.invalid', email='ta@example.invalid', password='test-password-1301')
        self.member = Membership.objects.create(course=self.course, user=self.user, role='ta')
        self.client.force_login(self.user)

    def test_ta_cannot_promote_self_or_add_any_role(self):
        for role in ['student', 'ta', 'instructor']:
            r = self.client.post('/api/settings/enrollments/', {'email':self.user.email, 'role':role}, content_type='application/json')
            self.assertEqual(r.status_code, 403)
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, 'ta')

    def test_ta_cannot_sync_roster_change_policies_or_push_grades(self):
        for url in ['/api/settings/roster/sync/', '/api/gradebook/sync-canvas/',
                    '/api/settings/course-controls/save/', '/api/settings/submission-review/policy/',
                    '/api/settings/ed-discussion/save/', '/api/settings/accommodations/save/']:
            self.assertEqual(self.client.post(url, {}, content_type='application/json').status_code, 403, url)

    def test_ta_can_read_roster_and_gradebook_but_preview_cannot(self):
        for url in ['/api/settings/roster/', '/api/gradebook/']:
            self.assertEqual(self.client.get(url).status_code, 200)
        session = self.client.session
        session['student_view_course'] = self.course.pk
        session.save()
        for url in ['/api/settings/roster/', '/api/gradebook/']:
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_instructor_can_enroll(self):
        self.member.role = 'instructor'; self.member.save()
        self.assertEqual(self.client.post('/api/settings/enrollments/', {'email':'student@example.invalid','role':'student'}, content_type='application/json').status_code, 200)

    def test_demoted_instructor_token_loses_admin_scope_immediately(self):
        self.member.role='instructor'; self.member.save()
        _, raw = issue_token(self.member, 'Admin token', list(SCOPES))
        self.member.role='ta'; self.member.save()
        r=self.client.post(f'/api/v1/courses/{self.course.pk}/enrollments/', {'email':'new@example.invalid'}, content_type='application/json', HTTP_AUTHORIZATION='Bearer '+raw)
        self.assertEqual(r.status_code, 403)

    @patch('core.security.time.time', return_value=3000)
    def test_login_limit_is_shared_and_expires(self, clock):
        for _ in range(20):
            self.assertTrue(login_allowed(self.user.email)[0])
        self.assertFalse(login_allowed(self.user.email)[0])
        self.assertEqual(LoginThrottle.objects.count(), 2)
        self.assertNotIn(self.user.email, str(list(LoginThrottle.objects.values())))
        clock.return_value=3300
        self.assertTrue(login_allowed(self.user.email)[0])
        self.assertEqual(LoginThrottle.objects.count(), 2)

    def test_sign_in_returns_retry_after_before_password_hash_work(self):
        self.client.logout()
        with patch('core.security.login_allowed', return_value=(False, 120)), patch('core.accounts.authenticate') as auth:
            response=self.client.post('/api/auth/login/', {'email':self.user.email,'password':'wrong'}, content_type='application/json')
        self.assertEqual(response.status_code,429)
        self.assertEqual(response['Retry-After'],'120')
        auth.assert_not_called()

    def test_private_response_headers_and_csrf(self):
        response=self.client.get('/api/session/')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertEqual(Client(enforce_csrf_checks=True).post('/api/auth/login/', {}, content_type='application/json').status_code,403)

    def test_ta_api_cannot_change_deadlines_via_metadata(self):
        from core.models import Lesson
        lesson=Lesson.objects.create(course=self.course,title='Assignment',metadata={'due_at':None})
        _,raw=issue_token(self.member,'Teaching token',['content:write'])
        for body in [{'due_at':'2030-01-01T00:00:00Z'},{'metadata':{'due_at':'2030-01-01T00:00:00Z'}}]:
            response=self.client.patch(f'/api/v1/assignments/{lesson.pk}/',body,content_type='application/json',HTTP_AUTHORIZATION='Bearer '+raw)
            self.assertEqual(response.status_code,403)
        lesson.refresh_from_db()
        self.assertIsNone(lesson.metadata['due_at'])

    def test_admin_login_is_also_throttled(self):
        self.client.logout()
        with patch('core.security.login_allowed',return_value=(False,60)):
            response=self.client.post('/admin/login/',{'username':'admin','password':'wrong'})
        self.assertEqual(response.status_code,429)
        self.assertEqual(response['Retry-After'],'60')
