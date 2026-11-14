import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.models import Accommodation, Activity, Course, Lesson, Membership, Revision


class AccountTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(title="CS 1301", term="Fall")

    @override_settings(ALLOW_SELF_REGISTRATION=False)
    def test_closed_registration_cannot_create_or_claim_accounts(self):
        user = get_user_model().objects.create(username="invited@gatech.edu", email="invited@gatech.edu")
        user.set_unusable_password(); user.save()
        for email in ("outsider@gatech.edu", "invited@gatech.edu"):
            response = self.client.post("/api/auth/register/", {
                "email": email, "password": "another useful password",
            }, content_type="application/json")
            self.assertEqual(response.status_code, 403)
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Membership.objects.count(), 0)
        self.assertFalse(self.client.get("/api/session/").json()["registration_open"])

    def test_register_creates_unenrolled_account_and_login_uses_email(self):
        response = self.client.post("/api/auth/register/", {
            "email": " Student@Gatech.edu ", "password": "a useful password 1301",
            "first_name": "Ada", "last_name": "Lovelace",
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        user = get_user_model().objects.get(username="student@gatech.edu")
        self.assertFalse(Membership.objects.filter(user=user).exists())
        self.client.post("/api/auth/logout/")
        self.assertEqual(self.client.post("/api/auth/login/", {
            "email": "student@gatech.edu", "password": "a useful password 1301",
        }, content_type="application/json").status_code, 200)

    def test_provisioned_user_can_finish_registration(self):
        user = get_user_model().objects.create(username="future@gatech.edu", email="future@gatech.edu")
        user.set_unusable_password(); user.save()
        Membership.objects.create(user=user, course=self.course, role="student")
        response = self.client.post("/api/auth/register/", {
            "email": "future@gatech.edu", "password": "another useful password",
            "first_name": "Grace", "last_name": "Hopper",
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password("another useful password"))


class CourseSettingsTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(title="CS 1301", term="Fall")
        self.staff = get_user_model().objects.create_user("staff", email="staff@gatech.edu")
        self.student = get_user_model().objects.create_user("student", email="student@gatech.edu")
        Membership.objects.create(user=self.staff, course=self.course, role="instructor")
        self.student_membership = Membership.objects.create(user=self.student, course=self.course, role="student")
        self.lesson = Lesson.objects.create(course=self.course, title="Programming Quiz 1",
            visibility="staff", metadata={"kind":"programming_quiz", "time_limit_minutes":30})
        self.activity = Activity.objects.create(lesson=self.lesson, title="Quiz 1", metadata={})
        revision = Revision.objects.create(activity=self.activity, number=1, created_by=self.staff,
            content={"version": 1, "blocks": []}, grading={"maximum_points": "10"})
        self.activity.published_revision = revision; self.activity.save()
        self.client.force_login(self.staff)

    def test_add_people_and_csv_import(self):
        response = self.client.post("/api/settings/enrollments/", {
            "email": "teacher@gatech.edu", "name": "Course Teacher", "role": "instructor",
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        upload = SimpleUploadedFile("students.csv", b"email,name\none@gatech.edu,One Student\ntwo@gatech.edu,Two Student\n", content_type="text/csv")
        response = self.client.post("/api/settings/enrollments/import/", {"file": upload, "role": "student"})
        self.assertEqual(response.json()["added"], 2)
        self.assertEqual(Membership.objects.filter(course=self.course).count(), 5)

    def test_students_cannot_read_roster(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get("/api/settings/roster/").status_code, 403)

    def test_quiz_timing_and_individual_accommodation(self):
        response = self.client.post(f"/api/settings/quizzes/{self.lesson.pk}/", {
            "time_limit_minutes": 60, "exam_mode": True,
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        response = self.client.post("/api/settings/accommodations/save/", {
            "membership_ids": [self.student_membership.pk], "activity_id": f"quiz:{self.lesson.pk}",
            "time_percent": 150, "extra_minutes": 5, "extra_attempts": 1,
        }, content_type="application/json")
        self.assertEqual(response.json()["updated"], 1)
        value = Accommodation.objects.get(membership=self.student_membership, lesson=self.lesson)
        self.assertEqual(value.time_multiplier, 1.5)
        data = self.client.get(f"/api/settings/accommodations/?activity=quiz:{self.lesson.pk}").json()
        self.assertEqual(data["students"][0]["time_percent"], "150")
        self.assertEqual(data["students"][0]["effective_minutes"], "95")

    def test_manual_enrollment_uses_three_public_roles(self):
        response = self.client.post("/api/settings/enrollments/", {
            "email":"head@gatech.edu", "role":"head_ta",
        }, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_canvas_sync_reports_missing_lti_configuration(self):
        response = self.client.post("/api/settings/roster/sync/")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Canvas", response.json()["error"])
