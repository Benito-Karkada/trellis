from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from core.models import (Accommodation, Activity, ActivityProgress, AssignmentChecklist,
    Course, Lesson, Membership, QuizAttempt, Revision)
from .test_studio import StudioTests


class UpcomingTests(TestCase):
    def setUp(self):
        StudioTests.setUp(self)
        self.course = self.activity.lesson.course
        self.member = Membership.objects.get(user=self.student, course=self.course)
        self.now = timezone.now()
        self.lesson = self.activity.lesson
        self.lesson.metadata = {'due_at': (self.now + timedelta(days=3)).isoformat()}
        self.lesson.save()
        self.revision.grading = {'maximum_points': '2.5', 'questions': {'q': {'answers': ['ok']}}}
        self.revision.save()
        self.headers = {'HTTP_X_TRELLIS_COURSE': str(self.course.pk)}

    def items(self):
        response = self.client.get('/api/upcoming/', **self.headers)
        self.assertEqual(response.status_code, 200)
        return response.json()['items']

    def add(self, title, days, *, visibility='student', kind='lesson', maximum='5'):
        lesson = Lesson.objects.create(course=self.course, title=title, visibility=visibility,
            metadata={'kind': kind, **({'due_at': (self.now + timedelta(days=days)).isoformat()} if days is not None else {})})
        part = Activity.objects.create(lesson=lesson, title='Question')
        revision = Revision.objects.create(activity=part, created_by=self.staff, number=1,
            content={'version': 1, 'blocks': []}, grading={'maximum_points': maximum, 'questions': {'q': {'answers': ['ok']}}})
        part.published_revision = revision; part.save()
        return lesson, part

    def test_order_real_scores_and_only_published_non_deleted_graded_content(self):
        overdue, _ = self.add('Overdue', -1)
        soon, _ = self.add('Tomorrow', 1)
        undated, _ = self.add('No deadline', None)
        ungraded, _ = self.add('Reading', 2, maximum='0')
        removed, _ = self.add('Removed', 2); removed.deleted_at=self.now;removed.save()
        Revision.objects.create(activity=self.activity,number=2,created_by=self.staff,
            content={'version': 1, 'blocks': []},grading={'maximum_points':'99','questions':{'q':{}}})
        ActivityProgress.objects.create(user=self.student,activity=self.activity,score='0.5',maximum='2.5')
        rows=self.items()
        self.assertEqual([row['id'] for row in rows],[overdue.pk,soon.pk,self.lesson.pk])
        self.assertEqual(rows[-1]['earned_points'],'0.5')
        self.assertEqual(rows[-1]['maximum_points'],'2.5')
        self.assertEqual(rows[-1]['activity_id'],self.activity.pk)
        self.assertFalse(rows[-1]['done'])

    def test_sort_compares_instants_across_different_utc_offsets(self):
        other,_=self.add('Earlier UTC',1)
        self.lesson.metadata={'due_at':'2030-01-01T08:00:00-05:00'};self.lesson.save()
        other.metadata={'due_at':'2030-01-01T12:00:00+00:00'};other.save()
        self.assertEqual([row['id'] for row in self.items()],[other.pk,self.lesson.pk])

    def test_deadline_accommodations_take_precedence_and_part_deadlines_are_honored(self):
        override=self.now+timedelta(days=1)
        Accommodation.objects.create(membership=self.member,lesson=self.lesson,due_at_override=override)
        self.assertEqual(self.items()[0]['due_at'],override.isoformat())
        part_override=self.now+timedelta(hours=3)
        Accommodation.objects.create(membership=self.member,activity=self.activity,due_at_override=part_override)
        self.assertEqual(self.items()[0]['due_at'],part_override.isoformat())

    def test_multiple_part_deadlines_show_next_outstanding_deadline(self):
        other=Activity.objects.create(lesson=self.lesson,title='Later part',metadata={'due_at':(self.now+timedelta(days=5)).isoformat()})
        revision=Revision.objects.create(activity=other,created_by=self.staff,number=1,content={'version':1,'blocks':[]},grading=self.revision.grading)
        other.published_revision=revision;other.save()
        self.assertTrue(self.items()[0]['multiple_deadlines'])
        ActivityProgress.objects.create(user=self.student,activity=self.activity,score='2.5',maximum='2.5',completed=True)
        row=self.items()[0]
        self.assertEqual(row['maximum_points'],'5')
        self.assertEqual(row['due_at'],other.metadata['due_at'])
        self.assertFalse(row['multiple_deadlines'])

    def test_checklist_persists_per_account_without_changing_scores_or_completion(self):
        url=f'/api/upcoming/{self.lesson.pk}/check/'
        for checked in (True,False):
            response=self.client.post(url,{'checked':checked},content_type='application/json',**self.headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(self.items()[0]['done'],checked)
            self.assertFalse(ActivityProgress.objects.filter(user=self.student).exists())
        self.client.force_login(self.staff)
        self.assertFalse(self.items()[0]['done'])
        self.assertEqual(AssignmentChecklist.objects.count(),1)
        self.assertEqual(self.client.post(url,{'checked':'yes'},content_type='application/json',**self.headers).status_code,400)

    def test_full_credit_checks_future_assignment_but_manual_uncheck_is_preserved(self):
        ActivityProgress.objects.create(user=self.student,activity=self.activity,score='2.5',maximum='2.5',completed=True)
        self.assertTrue(self.items()[0]['done'])
        self.client.post(f'/api/upcoming/{self.lesson.pk}/check/',{'checked':False},content_type='application/json',**self.headers)
        self.assertFalse(self.items()[0]['done'])
        self.assertEqual(ActivityProgress.objects.get(user=self.student,activity=self.activity).score,2.5)

    def test_student_view_checklist_is_separate_from_instructor_checklist(self):
        self.client.force_login(self.staff)
        url=f'/api/upcoming/{self.lesson.pk}/check/'
        self.client.post(url,{'checked':True},content_type='application/json',**self.headers)
        self.client.post('/api/student-view/',{'enabled':True},content_type='application/json',**self.headers)
        self.assertFalse(self.items()[0]['done'])
        self.client.post(url,{'checked':False},content_type='application/json',**self.headers)
        self.client.post('/api/student-view/',{'enabled':False},content_type='application/json',**self.headers)
        self.assertTrue(self.items()[0]['done'])

    def test_cross_course_hidden_and_deleted_assignments_are_not_exposed_or_writable(self):
        hidden,_=self.add('Hidden quiz',1,visibility='staff',kind='programming_quiz')
        other_course=Course.objects.create(title='Other',term='Test')
        other=Lesson.objects.create(course=other_course,title='Other assignment')
        self.assertEqual(len(self.items()),1)
        for lesson in (hidden,other):
            self.assertEqual(self.client.post(f'/api/upcoming/{lesson.pk}/check/',{'checked':True},content_type='application/json',**self.headers).status_code,404)
        self.assertEqual(self.client.get('/api/upcoming/',HTTP_X_TRELLIS_COURSE=str(other_course.pk)).status_code,403)
        self.client.logout()
        self.assertEqual(self.client.get('/api/upcoming/',**self.headers).status_code,403)

    def test_completed_past_work_is_removed_and_upcoming_quizzes_open_at_assignment_gate(self):
        old,part=self.add('Completed past work',-2)
        ActivityProgress.objects.create(user=self.student,activity=part,score=5,maximum=5,completed=True)
        quiz,_=self.add('Quiz',2,kind='programming_quiz')
        QuizAttempt.objects.create(membership=self.member,lesson=quiz,submitted_at=self.now)
        expired,_=self.add('Expired past quiz',-1,kind='programming_quiz')
        QuizAttempt.objects.create(membership=self.member,lesson=expired,expires_at=self.now-timedelta(hours=1))
        rows=self.items()
        self.assertNotIn(expired.pk,[row['id'] for row in rows])
        self.assertNotIn(old.pk,[row['id'] for row in rows])
        row=next(row for row in rows if row['id']==quiz.pk)
        self.assertIsNone(row['activity_id'])
        self.assertTrue(row['done'])

    def test_query_count_does_not_grow_with_number_of_assignments(self):
        for index in range(15): self.add(f'Assignment {index}',index+1)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            rows=self.items()
        self.assertEqual(len(rows),16)
        self.assertLessEqual(len(queries),10)
