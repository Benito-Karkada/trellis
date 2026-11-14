import tempfile
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.utils import timezone
from core.models import Course, Lesson, Activity, Revision, ActivityFile, Membership, ActivityProgress


class StudioTests(TestCase):
    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.staff = get_user_model().objects.create_user('staff')
        self.student = get_user_model().objects.create_user('student')
        course = Course.objects.create(title='CS 1301', term='Pilot')
        for user, role in [(self.staff, 'instructor'), (self.student, 'student')]:
            Membership.objects.create(course=course, user=user, role=role)
        lesson = Lesson.objects.create(course=course, title='Variables')
        self.activity = Activity.objects.create(lesson=lesson, title='Dates')
        self.revision = Revision.objects.create(activity=self.activity, number=1, created_by=self.staff,
            content={'version': 1, 'blocks': [{'id': 'code', 'type': 'coding', 'prompt': [{'type': 'text', 'text': 'Try it'}]}]},
            grading={'secret': 'not for students'})
        self.activity.published_revision = self.revision
        self.activity.save()
        self.starter = ActivityFile.objects.create(revision=self.revision, path='main.py', visibility='student',
            blob=ContentFile(b'print(1)', name='main.py'))
        self.private = ActivityFile.objects.create(revision=self.revision, path='private/Ferb.py', visibility='grader',
            blob=ContentFile(b'secret tests', name='Ferb.py'))
        self.client.force_login(self.student)

    def test_student_projection_and_private_file_denial(self):
        response = self.client.get(f'/api/studio/{self.activity.pk}/').json()
        self.assertNotIn('grading', response)
        self.assertEqual([f['path'] for f in response['files']], ['main.py'])
        for mode in ['student', 'preview', 'config']:
            self.assertIn(self.client.get(f'/api/files/{self.private.pk}/?mode={mode}').status_code, [403, 404])
        self.assertEqual(self.client.get(f'/api/studio/{self.activity.pk}/?mode=config').status_code, 403)

    def test_staff_preview_cannot_fetch_hidden_files(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(f'/api/files/{self.private.pk}/?mode=config').status_code, 200)
        for mode in ['student', 'preview']:
            self.assertEqual(self.client.get(f'/api/files/{self.private.pk}/?mode={mode}').status_code, 404)

    def test_workspace_is_private_and_allows_content_edits_only(self):
        detail = f'/api/studio/{self.activity.pk}/'
        self.assertEqual(self.client.get(detail).json()['workspace'], {'main.py': 'print(1)'})
        endpoint = f'/api/workspaces/{self.revision.pk}/'
        for files in [{'main.py': 'print(2)'}]:
            self.assertEqual(self.client.post(endpoint, {'files': files}, content_type='application/json').status_code, 200)
            self.assertEqual(self.client.get(detail).json()['workspace'], files)
        for files in [{'main.py':'print(2)', 'extra.py':''}, {'renamed.py':'print(2)'}, {}]:
            self.assertEqual(self.client.post(endpoint, {'files':files}, content_type='application/json').status_code, 400)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(detail).json()['workspace'], {'main.py': 'print(1)'})

    def test_workspace_rejects_unsafe_paths(self):
        for path in ['../escape', '/absolute', '', 'private\\escape']:
            self.assertEqual(self.client.post(f'/api/workspaces/{self.revision.pk}/',
                {'files': {path: 'x'}}, content_type='application/json').status_code, 400)

    def test_publishing_carries_student_work_forward(self):
        self.client.post(f'/api/workspaces/{self.revision.pk}/', {'files': {'main.py': 'keep me'}},
                         content_type='application/json')
        next_revision = Revision.objects.create(activity=self.activity, number=2, created_by=self.staff,
                                                content=self.revision.content)
        self.activity.published_revision = next_revision
        self.activity.save()
        data = self.client.get(f'/api/studio/{self.activity.pk}/').json()
        self.assertEqual(data['workspace'], {'main.py': 'keep me'})

    def test_reset_restores_exact_starter_files_without_private_files(self):
        from core.models import Workspace
        Workspace.objects.create(user=self.student, revision=self.revision,
                                 files={'main.py':'edited', 'old.txt':'stale feedback'})
        endpoint = f'/api/workspaces/{self.revision.pk}/'
        response = self.client.post(endpoint, {'action':'reset'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['workspace'], {'main.py':'print(1)'})
        self.assertEqual(self.client.get(f'/api/studio/{self.activity.pk}/').json()['workspace'],
                         {'main.py':'print(1)'})

    def test_preview_starts_fresh_and_does_not_create_or_change_saved_workspace(self):
        from core.models import Workspace
        self.client.force_login(self.staff)
        workspace = Workspace.objects.create(user=self.staff, revision=self.revision, files={'main.py':'saved code'})
        response = self.client.get(f'/api/studio/{self.activity.pk}/?mode=preview')
        self.assertEqual(response.json()['workspace'], {'main.py':'print(1)'})
        workspace.refresh_from_db()
        self.assertEqual(workspace.files, {'main.py':'saved code'})
        self.assertEqual(Workspace.objects.count(), 1)

    def test_invalid_json_is_a_client_error(self):
        for value in ['{', '[]', 'null']:
            self.assertEqual(self.client.post(f'/api/workspaces/{self.revision.pk}/', value,
                                             content_type='application/json').status_code, 400)

    def test_anonymous_authoring_is_denied(self):
        self.client.logout()
        self.assertEqual(self.client.post(f'/api/studio/{self.activity.pk}/edit/', {},
                                         content_type='application/json').status_code, 403)

    def test_drafts_are_immutable_and_publish_is_explicit(self):
        self.client.force_login(self.staff)
        endpoint = f'/api/studio/{self.activity.pk}/edit/'
        body = {'base_revision': self.revision.pk, 'content': self.revision.content,
                'files': [{'path': 'main.py', 'visibility': 'student', 'text': 'new starter'}]}
        response = self.client.post(endpoint, body, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        draft = response.json()['revision']
        self.assertEqual(self.client.post(endpoint, body, content_type='application/json').status_code, 409)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.published_revision_id, self.revision.pk)
        self.assertEqual(self.client.post(endpoint, {'base_revision': draft, 'action': 'publish'},
                                         content_type='application/json').status_code, 200)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.published_revision_id, draft)
        self.assertEqual(Revision.objects.get(pk=self.revision.pk).files.count(), 2)

    def test_config_file_access_is_derived_from_its_folder(self):
        self.client.force_login(self.staff)
        endpoint = f'/api/studio/{self.activity.pk}/edit/'
        files = [
            {'path': 'main.py', 'visibility': 'grader', 'text': 'student'},
            {'path': 'grader/tests.json', 'visibility': 'student', 'text': '{}'},
            {'path': 'solutions/sample_answer.py', 'visibility': 'student', 'text': 'answer'},
        ]
        response = self.client.post(endpoint, {'base_revision': self.revision.pk,
            'content': self.revision.content, 'files': files}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        revision = Revision.objects.get(pk=response.json()['revision'])
        self.assertEqual({f.path: f.visibility for f in revision.files.all()}, {
            'main.py': 'student', 'grader/tests.json': 'grader',
            'solutions/sample_answer.py': 'staff'})

    def test_staff_student_view_uses_student_projection_and_can_exit(self):
        self.client.force_login(self.staff)
        enabled = self.client.post('/api/student-view/', {'enabled': True}, content_type='application/json')
        self.assertTrue(enabled.json()['student_view'])
        outline = self.client.get('/api/outline/').json()
        self.assertEqual(outline['role'], 'student')
        self.assertEqual(outline['actual_role'], 'instructor')
        self.assertTrue(outline['student_view'])
        self.assertEqual(self.client.get(f'/api/studio/{self.activity.pk}/?mode=config').status_code, 403)
        self.assertEqual(self.client.get(f'/api/files/{self.private.pk}/?mode=config').status_code, 403)
        detail = self.client.get(f'/api/studio/{self.activity.pk}/').json()
        self.assertEqual([f['path'] for f in detail['files']], ['main.py'])
        disabled = self.client.post('/api/student-view/', {'enabled': False}, content_type='application/json')
        self.assertFalse(disabled.json()['student_view'])

    def test_outline_reports_trimmed_earned_and_maximum_points(self):
        self.revision.grading = {'definition': {'version': 1}, 'maximum_points': '1.5'}
        self.revision.save()
        ActivityProgress.objects.create(user=self.student, activity=self.activity, viewed=True,
                                        score='0.5', maximum='1.5')
        item = self.client.get('/api/outline/').json()['lessons'][0]['activities'][0]
        self.assertEqual(item['earned_points'], '0.5')
        self.assertEqual(item['maximum_points'], '1.5')

    def test_unpublished_and_deleted_content_is_unavailable(self):
        Activity.objects.create(lesson=self.activity.lesson, title='Private draft')
        titles = [a['title'] for l in self.client.get('/api/outline/').json()['lessons'] for a in l['activities']]
        self.assertEqual(titles, ['Dates'])
        self.activity.deleted_at = timezone.now()
        self.activity.save()
        self.assertEqual(self.client.get(f'/api/files/{self.starter.pk}/').status_code, 404)

    @override_settings(DEBUG=False, ALLOW_LOCAL_LOGIN=True)
    def test_production_has_no_dev_login(self):
        self.assertEqual(self.client.post('/api/local-login/').status_code, 404)
        self.assertFalse(self.client.get('/api/session/').json()['local_login'])
