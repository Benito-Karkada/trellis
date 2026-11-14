from pathlib import PurePosixPath
from django.test import SimpleTestCase
from core.grading_artifacts import feedback_update
from core.importers.coding_archive import classify_path


class GradingArtifactTests(SimpleTestCase):
    def test_placeholder_and_private_solution_are_distinct(self):
        self.assertEqual(classify_path(PurePosixPath("startercode/sample_answer_1.py")), "student")
        self.assertEqual(classify_path(PurePosixPath("private/sample_answer_1.py")), "staff")
        self.assertEqual(classify_path(PurePosixPath("course/Utility.py")), "grader")
        self.assertEqual(classify_path(PurePosixPath("scripts/run.sh")), "grader")

    def test_successful_checks_do_not_release_samples(self):
        result = {"points": 5, "show_samples": True, "full_output": "Passed"}
        for operation in ("run", "check"):
            self.assertFalse(feedback_update(result, operation=operation)["release_samples"])
        self.assertTrue(feedback_update(result, operation="submit")["release_samples"])

    def test_failed_submission_still_updates_results(self):
        result = {"points": 0, "show_samples": True, "full_output": "Failed case"}
        update = feedback_update(result, operation="submit", feedback="Check your dates")
        self.assertFalse(update["release_samples"])
        self.assertIn("Check your dates", update["files"]["full_results.txt"])
        self.assertEqual(update["score_fraction"], "0")
