from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from core.models import Course, Lesson, Activity, Revision, Membership, QuestionCooldown, ActivityProgress


class RetryCooldownTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user('staff')
        self.student = get_user_model().objects.create_user('student')
        course = Course.objects.create(title='CS 1301', term='Pilot')
        for user, role in [(self.staff, 'instructor'), (self.student, 'student')]:
            Membership.objects.create(course=course, user=user, role=role)
        lesson = Lesson.objects.create(course=course, title='Variables')
        self.activity = Activity.objects.create(lesson=lesson, title='Quiz')
        self.revision = Revision.objects.create(
            activity=self.activity, number=1, created_by=self.staff,
            content={'version': 1, 'blocks': [
                {'id': 'q1', 'type': 'multiple_choice', 'prompt': [{'type': 'text', 'text': 'Pick one'}],
                 'choices': [{'id': 'a', 'content': [{'type': 'text', 'text': 'A'}]},
                             {'id': 'b', 'content': [{'type': 'text', 'text': 'B'}]}]}]},
            grading={'maximum_points': '1', 'questions': {'q1': {'selection': 'one', 'correct_choice_ids': ['a']}}})
        self.activity.published_revision = self.revision
        self.activity.save()
        self.membership = Membership.objects.get(user=self.student, course=course)
        self.client.force_login(self.student)

    def submit(self, choice):
        return self.client.post(f'/api/submit-native/{self.revision.pk}/', {'responses': {'q1': choice}}, content_type='application/json')

    def test_wrong_answer_locks_question_and_blocks_immediate_retry(self):
        first = self.submit('b').json()
        self.assertFalse(first['checks']['q1'])
        self.assertIn('q1', first['locks'])
        self.assertTrue(QuestionCooldown.objects.filter(membership=self.membership, revision=self.revision, question_id='q1').exists())

        second = self.submit('a').json()
        self.assertFalse(second['checks']['q1'], "the correct retry should be ignored while the cooldown is active")
        self.assertIn('q1', second['locks'])

        projection = self.client.get(f'/api/studio/{self.activity.pk}/').json()
        self.assertIn('q1', projection['locks'])

    def test_correct_answer_clears_any_cooldown(self):
        self.submit('b')
        self.assertTrue(QuestionCooldown.objects.filter(membership=self.membership, question_id='q1').exists())
        QuestionCooldown.objects.filter(membership=self.membership, question_id='q1').update(locked_until=timezone.now())
        result = self.submit('a').json()
        self.assertTrue(result['checks']['q1'])
        self.assertNotIn('q1', result['locks'])
        self.assertFalse(QuestionCooldown.objects.filter(membership=self.membership, question_id='q1').exists())

    def test_preview_mode_is_never_locked(self):
        self.client.force_login(self.staff)
        response = self.client.post(f'/api/submit-native/{self.revision.pk}/', {'responses': {'q1': 'b'}, 'preview': True}, content_type='application/json').json()
        self.assertEqual(response['locks'], {})
        self.assertFalse(QuestionCooldown.objects.exists())

    def test_revisiting_for_feedback_after_full_credit_does_not_lower_the_recorded_grade(self):
        # A student who already earned full credit may resubmit (once their cooldown clears) just
        # to read another choice's feedback. That attempt can show 0/1 for itself, but the grade
        # actually recorded for the course must never drop back down.
        correct = self.submit('a').json()
        self.assertTrue(correct['passed'])
        progress = ActivityProgress.objects.get(user=self.student, activity=self.activity)
        self.assertEqual(progress.score, 1)
        self.assertTrue(progress.completed)

        QuestionCooldown.objects.filter(membership=self.membership, question_id='q1').update(locked_until=timezone.now())
        wrong = self.submit('b').json()
        self.assertFalse(wrong['passed'])
        self.assertEqual(wrong['score'], '0')

        progress.refresh_from_db()
        self.assertEqual(progress.score, 1, "the recorded grade must not regress after a deliberately-wrong revisit")
        self.assertTrue(progress.completed)
