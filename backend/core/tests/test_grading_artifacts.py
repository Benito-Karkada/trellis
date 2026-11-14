from django.test import SimpleTestCase
from core.grading_artifacts import feedback_update


class GradingArtifactTests(SimpleTestCase):
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
