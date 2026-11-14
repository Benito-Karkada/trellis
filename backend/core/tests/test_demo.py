import io
import tempfile

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from core.assessment import assess
from core.models import Activity, ActivityFile, Course, Membership
from core.schema import student_projection


@override_settings(DEBUG=True)
class DemoTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        setting = override_settings(MEDIA_ROOT=self.media.name)
        setting.enable()
        self.addCleanup(setting.disable)

    def seed(self):
        call_command("seed_demo", stdout=io.StringIO())

    def test_fresh_demo_has_usable_accounts_and_private_grading(self):
        self.seed()
        user = get_user_model().objects.get(username="studio-instructor")
        self.assertTrue(user.check_password("trellis-demo-2026"))
        self.assertEqual(Membership.objects.get(user=user).role, "instructor")
        part = Activity.objects.get(metadata__demo_key="sum")
        self.assertTrue(part.published_revision.grading["definition"]["cases"])
        paths = [row["path"] for row in student_projection(part.published_revision)["files"]]
        self.assertIn("main.py", paths)
        self.assertIn("full_results.txt", paths)
        self.assertNotIn("grader/tests.json", paths)
        self.assertNotIn("solutions/sample_answer.py", paths)
        question = Activity.objects.get(metadata__demo_key="variable-question").published_revision
        self.assertTrue(assess(question.grading, {"q1": "b"})["passed"])
        self.assertFalse(assess(question.grading, {"q1": "a"})["passed"])

    def test_repeat_setup_preserves_content_and_passwords(self):
        self.seed()
        part = Activity.objects.get(metadata__demo_key="sum")
        part.title = "An instructor's edited title"
        part.save()
        user = get_user_model().objects.get(username="studio-instructor")
        user.set_password("a-personal-local-password")
        user.save()
        counts = (Course.objects.count(), Activity.objects.count(), ActivityFile.objects.count())
        self.seed()
        part.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(part.title, "An instructor's edited title")
        self.assertTrue(user.check_password("a-personal-local-password"))
        self.assertEqual(counts, (Course.objects.count(), Activity.objects.count(), ActivityFile.objects.count()))

    def test_quiz_has_five_questions_and_staff_only_solutions(self):
        self.seed()
        parts = Activity.objects.filter(lesson__metadata__kind="programming_quiz")
        self.assertEqual(parts.count(), 5)
        for part in parts:
            paths = [row["path"] for row in student_projection(part.published_revision)["files"]]
            self.assertNotIn("sample_answer.py", paths)
            self.assertTrue(part.published_revision.files.filter(path="solutions/sample_answer.py", visibility="staff").exists())

    @override_settings(DEBUG=False)
    def test_demo_seed_is_disabled_outside_debug(self):
        with self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(Course.objects.exists())
