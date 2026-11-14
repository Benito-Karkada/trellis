from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from core.models import Accommodation, QuizAttempt, Workspace
from .test_studio import StudioTests


class ProgrammingQuizTests(TestCase):
    def setUp(self):
        StudioTests.setUp(self)
        self.lesson=self.activity.lesson
        self.lesson.visibility="staff"
        self.lesson.metadata={"kind":"programming_quiz","exam_mode":True,"time_limit_minutes":20}
        self.lesson.save()
        self.revision.grading={"definition":{"version":1,"cases":[{"id":"one","label":"Test 1","expected":1,"target":"x"}]}}
        self.revision.save()

    def test_student_cannot_discover_or_open_teacher_only_quiz(self):
        self.assertEqual(self.client.get("/api/outline/").json()["lessons"],[])
        self.assertEqual(self.client.get(f"/api/studio/{self.activity.pk}/").status_code,403)
        self.assertEqual(self.client.get(f"/api/activities/{self.activity.pk}/").status_code,403)

    def test_staff_sees_quiz_and_can_start_timer(self):
        self.client.force_login(self.staff)
        lesson=self.client.get("/api/outline/").json()["lessons"][0]
        self.assertEqual(lesson["metadata"]["kind"],"programming_quiz")
        data=self.client.post(f"/api/quizzes/{self.lesson.pk}/start/").json()
        self.assertEqual(data["effective_minutes"],"20")
        self.assertIsNotNone(data["expires_at"])

    def test_student_accommodation_changes_effective_exam_time(self):
        membership=self.activity.lesson.course.membership_set.get(user=self.student)
        self.lesson.visibility="student";self.lesson.save()
        Accommodation.objects.create(membership=membership,lesson=self.lesson,time_multiplier=Decimal("1.5"),extra_minutes=5)
        data=self.client.post(f"/api/quizzes/{self.lesson.pk}/start/").json()
        self.assertEqual(data["effective_minutes"],"35")

    def test_exam_execution_requires_unexpired_attempt(self):
        self.lesson.visibility="student";self.lesson.save()
        self.assertEqual(self.client.get("/api/outline/").json()["lessons"][0]["activities"], [])
        self.assertEqual(self.client.get(f"/api/studio/{self.activity.pk}/").status_code, 403)
        body={"operation":"run","entrypoint":"main.py","files":{"main.py":"print(1)"}}
        self.assertEqual(self.client.post(f"/api/execute/{self.revision.pk}/",body,content_type="application/json").status_code,403)
        self.client.post(f"/api/quizzes/{self.lesson.pk}/start/")
        self.assertEqual(self.client.post(f"/api/execute/{self.revision.pk}/",body,content_type="application/json").status_code,200)
        QuizAttempt.objects.update(expires_at=timezone.now())
        self.assertEqual(self.client.post(f"/api/execute/{self.revision.pk}/",body,content_type="application/json").status_code,403)

    def test_finishing_quiz_locks_future_execution_and_returns_points(self):
        self.lesson.visibility="student";self.lesson.save()
        self.client.post(f"/api/quizzes/{self.lesson.pk}/start/")
        response=self.client.post(f"/api/quizzes/{self.lesson.pk}/finish/")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["earned_points"],"0")
        self.assertEqual(response.json()["maximum_points"],"1")
        status=self.client.get(f"/api/quizzes/{self.lesson.pk}/status/").json()
        self.assertTrue(status["submitted"])
        outline=self.client.get("/api/outline/").json()["lessons"][0]
        self.assertTrue(outline["metadata"]["attempt_submitted"])
        self.assertEqual(outline["activities"],[])
        self.assertEqual(self.client.get(f"/api/studio/{self.activity.pk}/").status_code,403)
        body={"operation":"run","entrypoint":"main.py","files":{"main.py":"print(1)"}}
        self.assertEqual(self.client.post(f"/api/execute/{self.revision.pk}/",body,content_type="application/json").status_code,403)

    def test_staff_student_view_obeys_exam_attempt_requirement(self):
        self.lesson.visibility="student";self.lesson.save()
        self.client.force_login(self.staff)
        self.client.post('/api/student-view/', {'enabled': True}, content_type='application/json')
        body={"operation":"run","entrypoint":"main.py","files":{"main.py":"print(1)"}}
        self.assertEqual(self.client.post(f"/api/execute/{self.revision.pk}/",body,content_type="application/json").status_code,403)
        self.client.post(f"/api/quizzes/{self.lesson.pk}/start/")
        self.assertEqual(self.client.post(f"/api/execute/{self.revision.pk}/",body,content_type="application/json").status_code,200)

    def test_staff_can_publish_and_unpublish_a_quiz_via_settings(self):
        # setUp leaves the client logged in as the student; the quiz starts hidden (visibility="staff").
        self.assertEqual(self.lesson.visibility, "staff")
        self.assertEqual(self.client.get("/api/outline/").json()["lessons"], [])

        self.client.force_login(self.staff)
        response = self.client.post(f"/api/settings/quizzes/{self.lesson.pk}/",
            {"exam_mode": True, "time_limit_minutes": 20, "visibility": "student"},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.visibility, "student")
        self.client.force_login(self.student)
        self.assertEqual(len(self.client.get("/api/outline/").json()["lessons"]), 1)

        self.client.force_login(self.staff)
        self.client.post(f"/api/settings/quizzes/{self.lesson.pk}/",
            {"exam_mode": True, "time_limit_minutes": 20, "visibility": "staff"},
            content_type="application/json")
        self.client.force_login(self.student)
        self.assertEqual(self.client.get("/api/outline/").json()["lessons"], [])

    def test_invalid_visibility_value_is_rejected(self):
        self.client.force_login(self.staff)
        response = self.client.post(f"/api/settings/quizzes/{self.lesson.pk}/",
            {"exam_mode": True, "visibility": "everyone"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.visibility, "staff")

    def test_staff_can_review_latest_student_work_without_hidden_files(self):
        self.lesson.visibility="student";self.lesson.save()
        Workspace.objects.create(user=self.student, revision=self.revision,
                                 files={"main.py":"print('student')","unexpected.py":"hidden"})
        self.client.force_login(self.staff)
        membership=self.lesson.course.membership_set.get(user=self.student)
        response=self.client.get(f"/api/settings/quizzes/{self.lesson.pk}/review/?membership={membership.pk}&activity={self.activity.pk}")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["work"]["files"],{"main.py":"print('student')"})
