from django.test import TestCase

from core.models import Activity, ActivityProgress, Lesson, Revision, Submission, Workspace
from .test_studio import StudioTests


class StructureAndGradebookTests(TestCase):
    def setUp(self):
        StudioTests.setUp(self)
        self.course = self.activity.lesson.course
        self.client.force_login(self.staff)

    def test_staff_can_create_copy_and_soft_delete_outline_content(self):
        created = self.client.post('/api/structure/lessons/',
            {'action': 'create', 'title': 'New module'}, content_type='application/json').json()
        lesson = Lesson.objects.get(pk=created['id'])
        part = self.client.post('/api/structure/activities/',
            {'action': 'create', 'lesson_id': lesson.pk, 'title': 'New reading'},
            content_type='application/json').json()
        activity = Activity.objects.get(pk=part['id'])
        self.assertEqual(activity.published_revision.content['blocks'][0]['type'], 'document')
        copied = self.client.post('/api/structure/activities/',
            {'action': 'copy', 'lesson_id': lesson.pk, 'activity_id': activity.pk},
            content_type='application/json').json()
        self.assertTrue(Revision.objects.filter(activity_id=copied['id']).exists())
        section_copy = self.client.post('/api/structure/lessons/',
            {'action': 'copy', 'lesson_id': lesson.pk}, content_type='application/json').json()
        self.assertEqual(Lesson.objects.get(pk=section_copy['id']).activity_set.count(), 2)
        self.client.post('/api/structure/activities/',
            {'action': 'delete', 'lesson_id': lesson.pk, 'activity_id': activity.pk},
            content_type='application/json')
        activity.refresh_from_db(); self.assertIsNotNone(activity.deleted_at)

    def test_gradebook_matrix_and_latest_workspace_drilldown(self):
        self.revision.grading = {'definition': {'version': 1}, 'maximum_points': '3'}
        self.revision.save()
        ActivityProgress.objects.create(user=self.student, activity=self.activity,
                                        viewed=True, score='2', maximum='3')
        Workspace.objects.create(user=self.student, revision=self.revision,
                                 files={'main.py': 'print(2)', 'private.py': 'omit'})
        membership = self.course.membership_set.get(user=self.student)
        Submission.objects.create(revision=self.revision, membership=membership,
                                  response={'question-1': 'choice-b'})
        matrix = self.client.get('/api/gradebook/').json()
        row = matrix['students'][0]
        value = row['assignments'][str(self.activity.lesson_id)]
        self.assertEqual((value['earned'], value['maximum']), ('2', '3'))
        detail = self.client.get(
            f'/api/gradebook/detail/?membership={membership.pk}&lesson={self.activity.lesson_id}').json()
        self.assertEqual(detail['activities'][0]['files'], {'main.py': 'print(2)'})
        self.assertEqual(detail['activities'][0]['latest_response'], {'question-1': 'choice-b'})

    def test_students_cannot_mutate_outline_or_open_gradebook(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get('/api/gradebook/').status_code, 403)
        self.assertEqual(self.client.post('/api/structure/lessons/',
            {'action': 'create', 'title': 'No'}, content_type='application/json').status_code, 403)

    def test_new_part_kind_determines_its_starter_content_and_grading(self):
        lesson = self.activity.lesson
        for kind, expected_block_type in [('reading', 'document'), ('video', 'video'),
                                           ('coding', 'coding'), ('quiz', 'multiple_choice')]:
            created = self.client.post('/api/structure/activities/',
                {'action': 'create', 'lesson_id': lesson.pk, 'title': kind, 'kind': kind},
                content_type='application/json').json()
            activity = Activity.objects.get(pk=created['id'])
            self.assertEqual(activity.published_revision.content['blocks'][0]['type'], expected_block_type)
        # An unrecognized (or missing) kind falls back to a plain reading part rather than erroring.
        fallback = self.client.post('/api/structure/activities/',
            {'action': 'create', 'lesson_id': lesson.pk, 'title': 'mystery', 'kind': 'not-a-real-kind'},
            content_type='application/json').json()
        self.assertEqual(Activity.objects.get(pk=fallback['id']).published_revision.content['blocks'][0]['type'], 'document')

    def test_reordering_parts_only_touches_positions_within_that_lesson(self):
        lesson = self.activity.lesson
        second = Activity.objects.create(lesson=lesson, title='Second part', position=self.activity.position + 1)
        other_lesson = Lesson.objects.create(course=self.course, title='Other section', position=99)
        untouched = Activity.objects.create(lesson=other_lesson, title='Untouched', position=self.activity.position)

        response = self.client.post('/api/structure/activities/',
            {'action': 'reorder', 'lesson_id': lesson.pk, 'activity_ids': [second.pk, self.activity.pk]},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        original_activity_position = self.activity.position
        self.activity.refresh_from_db(); second.refresh_from_db(); untouched.refresh_from_db()
        self.assertLess(second.position, self.activity.position, "the requested order should now hold")
        self.assertEqual(untouched.position, original_activity_position, "a different lesson's activities must be untouched")

        # A reorder that omits an id (or repeats one) is rejected rather than silently dropping a part.
        bad = self.client.post('/api/structure/activities/',
            {'action': 'reorder', 'lesson_id': lesson.pk, 'activity_ids': [second.pk]},
            content_type='application/json')
        self.assertEqual(bad.status_code, 400)

    def test_reordering_sections_does_not_collide_with_a_programming_quiz_lessons_position(self):
        # The homepage reorders "Course" sections and "Programming quizzes" as two separate lists,
        # so a reorder request for one group should never need (or be allowed to omit) the other's ids.
        lesson = self.activity.lesson
        quiz_lesson = Lesson.objects.create(course=self.course, title='Quiz 1', position=lesson.position + 1,
            metadata={'kind': 'programming_quiz'})
        second = Lesson.objects.create(course=self.course, title='Second section', position=lesson.position + 2)
        original_quiz_position = quiz_lesson.position

        response = self.client.post('/api/structure/lessons/',
            {'action': 'reorder', 'lesson_ids': [second.pk, lesson.pk]}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        lesson.refresh_from_db(); second.refresh_from_db(); quiz_lesson.refresh_from_db()
        self.assertLess(second.position, lesson.position)
        self.assertEqual(quiz_lesson.position, original_quiz_position, "the quiz group must be untouched")

        # Omitting one of the course-section ids (not just quiz ids) is still rejected.
        bad = self.client.post('/api/structure/lessons/',
            {'action': 'reorder', 'lesson_ids': [second.pk]}, content_type='application/json')
        self.assertEqual(bad.status_code, 400)

        # Reordering the quiz group on its own works the same way.
        quiz_lesson_2 = Lesson.objects.create(course=self.course, title='Quiz 2',
            position=quiz_lesson.position + 1, metadata={'kind': 'programming_quiz'})
        response = self.client.post('/api/structure/lessons/',
            {'action': 'reorder', 'lesson_ids': [quiz_lesson_2.pk, quiz_lesson.pk]}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        quiz_lesson.refresh_from_db(); quiz_lesson_2.refresh_from_db()
        self.assertLess(quiz_lesson_2.position, quiz_lesson.position)
