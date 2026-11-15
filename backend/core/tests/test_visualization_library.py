from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from core.models import Course, Lesson, Membership, QuizAttempt, VisualizationSandbox, VisualizationJob


class VisualizationLibraryTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(title="Example", term="Test")
        self.teacher = get_user_model().objects.create_user("teacher")
        self.student = get_user_model().objects.create_user("student")
        self.ta = get_user_model().objects.create_user("ta")
        for user, role in [(self.teacher, "instructor"), (self.student, "student"), (self.ta, "ta")]:
            Membership.objects.create(user=user, course=self.course, role=role)
        self.client.force_login(self.teacher)
        self.headers = {"HTTP_X_TRELLIS_COURSE": str(self.course.pk)}
        self.fields = {"title": " Nested loops ", "sandbox_name": " Multiplication table ",
            "description": " Watch the inner loop reset. ", "source": "for n in range(3):\n    print(n)\n"}

    def create(self, **overrides):
        return self.client.post("/api/visualizations/library/new/", {**self.fields, **overrides},
            content_type="application/json", **self.headers)

    def library(self):
        return self.client.get("/api/visualizations/library/", **self.headers)

    def update(self, sandbox, **overrides):
        return self.client.post(f"/api/visualizations/library/{sandbox['id']}/",
            {**self.fields, "version": sandbox["version"], **overrides}, content_type="application/json", **self.headers)

    def test_instructor_creates_persistent_named_sandbox_available_to_students(self):
        created = self.create()
        self.assertEqual(created.status_code, 201)
        saved = created.json()["sandbox"]
        self.assertEqual(saved["title"], "Nested loops")
        self.assertEqual(saved["sandbox_name"], "Multiplication table")
        self.assertEqual(saved["description"], "Watch the inner loop reset.")
        self.assertEqual(VisualizationSandbox.objects.get(pk=saved["id"]).created_by, self.teacher)
        self.assertTrue(self.library().json()["can_edit"])
        self.client.force_login(self.student)
        response = self.library().json()
        self.assertFalse(response["can_edit"])
        self.assertEqual(response["sandboxes"], [saved])
        self.assertEqual(VisualizationJob.objects.count(), 0)

    def test_only_instructors_in_selected_course_can_create_or_update(self):
        saved = self.create().json()["sandbox"]
        for user in [self.student, self.ta]:
            self.client.force_login(user)
            self.assertFalse(self.library().json()["can_edit"])
            self.assertEqual(self.create().status_code, 403)
            self.assertEqual(self.update(saved).status_code, 403)
        self.client.force_login(self.teacher)
        session = self.client.session
        session["student_view_course"] = self.course.pk
        session.save()
        self.assertFalse(self.library().json()["can_edit"])
        self.assertEqual(self.create().status_code, 403)
        self.assertEqual(self.update(saved).status_code, 403)

    def test_library_and_mutations_are_course_scoped(self):
        saved = self.create().json()["sandbox"]
        other = Course.objects.create(title="Other", term="Test")
        Membership.objects.create(user=self.teacher, course=other, role="instructor")
        self.headers = {"HTTP_X_TRELLIS_COURSE": str(other.pk)}
        self.assertEqual(self.library().json()["sandboxes"], [])
        self.assertEqual(self.update(saved).status_code, 404)
        Membership.objects.filter(user=self.teacher, course=other).update(role="student")
        self.assertFalse(self.library().json()["can_edit"])
        self.assertEqual(self.create().status_code, 403)

    def test_edit_updates_title_name_and_source_and_rejects_stale_version(self):
        saved = self.create().json()["sandbox"]
        updated = self.update(saved, title="Lists", sandbox_name="Shared references", source="values = [1, 2]\n")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["sandbox"]["version"], 2)
        self.assertEqual(self.update(saved, title="Old tab").status_code, 409)
        sandbox = VisualizationSandbox.objects.get(pk=saved["id"])
        self.assertEqual((sandbox.title, sandbox.sandbox_name, sandbox.source),
            ("Lists", "Shared references", "values = [1, 2]\n"))

    def test_invalid_fields_and_execution_limits_are_rejected(self):
        for values in [{"title": " "}, {"title": "x" * 161}, {"sandbox_name": ""},
            {"sandbox_name": "x" * 101}, {"description": []}, {"description": "x" * 1001},
            {"source": ""}, {"source": "x" * 12001}, {"source": "é" * 6001},
            {"source": "pass\n" * 301}, {"course": 20}]:
            with self.subTest(values=values):
                self.assertEqual(self.create(**values).status_code, 400)
        self.assertFalse(VisualizationSandbox.objects.exists())
        saved = self.create().json()["sandbox"]
        self.assertEqual(self.update(saved, version=True).status_code, 400)

    def test_inactive_and_unauthenticated_members_cannot_access_library(self):
        Membership.objects.filter(user=self.teacher).update(active=False)
        self.assertEqual(self.library().status_code, 403)
        self.assertEqual(self.create().status_code, 403)
        self.client.logout()
        self.assertEqual(self.library().status_code, 403)

    def test_active_exam_cannot_access_or_create_library_items(self):
        self.client.force_login(self.student)
        lesson = Lesson.objects.create(course=self.course, title="Exam",
            metadata={"kind": "programming_quiz", "exam_mode": True})
        membership = Membership.objects.get(user=self.student, course=self.course)
        QuizAttempt.objects.create(membership=membership, lesson=lesson,
            expires_at=timezone.now() + timedelta(minutes=30))
        self.assertEqual(self.library().status_code, 403)
        self.assertEqual(self.create().status_code, 403)
