from datetime import timedelta
from django.utils import timezone
from django.test import TestCase
from core.models import Membership, Activity, Revision, ActivityProgress, AssignmentVisit, LearningEvent
from . import test_studio


class PaceTests(TestCase):
    def setUp(self):
        test_studio.StudioTests.setUp(self)
        self.member = Membership.objects.get(user=self.student)
        self.lesson = self.activity.lesson
        self.revision.grading = {'questions': {'a': {}, 'b': {}, 'c': {}}}
        self.revision.save()
        ActivityProgress.objects.create(user=self.student, activity=self.activity, completed=True)

    def visit(self, minutes_ago):
        v = AssignmentVisit.objects.create(membership=self.member, assignment=self.lesson, last_opened_at=timezone.now())
        AssignmentVisit.objects.filter(pk=v.pk).update(first_opened_at=timezone.now() - timedelta(minutes=minutes_ago))

    def post(self):
        return self.client.post(f'/api/assignments/{self.lesson.pk}/pace/')

    def test_fast_completion_is_flagged_once_and_server_side_only(self):
        self.visit(1)  # 3 questions in ~1 minute
        LearningEvent.objects.create(membership=self.member, assignment=self.lesson, kind='native_submitted')
        self.assertEqual(self.post().json(), {'too_fast': True})
        self.post()
        self.assertEqual(LearningEvent.objects.filter(kind='pace_flagged').count(), 1)

    def test_reasonable_pace_not_flagged(self):
        self.visit(4)
        LearningEvent.objects.create(membership=self.member, assignment=self.lesson, kind='native_submitted')
        self.assertFalse(self.post().json()['too_fast'])

    def test_long_gap_is_capped_so_a_next_day_return_is_not_flagged(self):
        self.visit(24 * 60)
        LearningEvent.objects.create(membership=self.member, assignment=self.lesson, kind='native_submitted')
        self.assertFalse(self.post().json()['too_fast'])  # gap capped at 10 min > 3 min required

    def test_per_part_override_and_too_little_signal(self):
        self.visit(1)
        LearningEvent.objects.create(membership=self.member, assignment=self.lesson, kind='native_submitted')
        self.activity.metadata = {'min_seconds': 10}
        self.activity.save()
        self.assertFalse(self.post().json()['too_fast'])  # 3 * 10s = 30s required
        ActivityProgress.objects.all().update(completed=False)
        self.assertFalse(self.post().json()['too_fast'])

    def test_staff_never_flagged(self):
        self.visit(1)
        self.client.force_login(self.staff)
        self.assertFalse(self.post().json()['too_fast'])

    def test_readings_videos_and_ungraded_parts_do_not_count(self):
        self.visit(1)
        for kind in ('reading', 'video'):
            self.activity.metadata = {'kind': kind}
            self.activity.save()
            self.assertFalse(self.post().json()['too_fast'])
        self.activity.metadata = {}
        self.activity.save()
        self.revision.grading = {}
        self.revision.save()
        self.assertFalse(self.post().json()['too_fast'])

    def test_sandbox_zero_points_and_unpublished_parts_do_not_count(self):
        self.visit(1)
        self.activity.metadata = {'sandbox': True}
        self.activity.save()
        self.assertFalse(self.post().json()['too_fast'])
        self.activity.metadata = {}
        self.activity.save()
        self.revision.grading['maximum_points'] = '0'
        self.revision.save()
        self.assertFalse(self.post().json()['too_fast'])
        self.activity.published_revision = None
        self.activity.save()
        self.assertFalse(self.post().json()['too_fast'])

    def test_invalid_minimums_fall_back_without_server_errors(self):
        self.visit(1)
        LearningEvent.objects.create(membership=self.member, assignment=self.lesson, kind='native_submitted')
        for value in ('NaN', 'Infinity', '-1', '1e308', None, True):
            with self.subTest(value=value):
                self.activity.metadata = {'min_seconds': value}
                self.activity.save()
                self.assertEqual(self.post().json(), {'too_fast': True})

    def test_staff_only_and_inactive_enrollments(self):
        self.visit(1)
        self.lesson.visibility = 'staff'
        self.lesson.save()
        self.assertEqual(self.post().json(), {'too_fast': False})
        self.member.active = False
        self.member.save()
        self.assertEqual(self.post().status_code, 404)

    def test_deleted_parts_and_anonymous_requests(self):
        self.visit(1)
        self.activity.deleted_at = timezone.now()
        self.activity.save()
        self.assertEqual(self.post().json(), {'too_fast': False})
        self.client.logout()
        self.assertEqual(self.post().status_code, 404)

    def test_focus_events_do_not_count_as_working_time(self):
        self.visit(1)
        LearningEvent.objects.create(membership=self.member, assignment=self.lesson, kind='native_submitted')
        event = LearningEvent.objects.create(membership=self.member, assignment=self.lesson, kind='focus_changed')
        LearningEvent.objects.filter(pk=event.pk).update(created_at=timezone.now()+timedelta(minutes=5))
        self.assertEqual(self.post().json(), {'too_fast': True})

    def test_programming_quizzes_never_show_pace_banner_or_create_flags(self):
        self.visit(1)
        self.lesson.metadata = {'kind': 'programming_quiz', 'exam_mode': True}
        self.lesson.visibility = 'student'
        self.lesson.save()
        LearningEvent.objects.create(membership=self.member, assignment=self.lesson, kind='native_submitted')
        self.assertEqual(self.post().json(), {'too_fast': False})
        self.assertFalse(LearningEvent.objects.filter(kind='pace_flagged').exists())
