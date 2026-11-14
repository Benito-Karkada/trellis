from decimal import Decimal
from django.test import SimpleTestCase
from core.assessment import assess, check_question


class AssessmentTests(SimpleTestCase):
    def test_fractional_points_display_without_padding(self):
        from core.assessment import display_points
        self.assertEqual(display_points(Decimal("1.5")/3), "0.5")
        self.assertEqual(display_points(Decimal("0.500000000")), "0.5")
        self.assertEqual(display_points(Decimal("1.500000")), "1.5")

    def test_feedback_matches_selected_and_missed_choices(self):
        rule={"selection":"all","correct_choice_ids":["a"],"choice_feedback_rules":{
            "a":[{"selected":False,"content":[{"type":"text","text":"Remember A"}]}],
            "b":[{"selected":True,"content":[{"type":"text","text":"B is incorrect"}]}]}}
        result=assess({"questions":{"q":rule}},{"q":["b"]})
        self.assertEqual(len(result["feedback"]["q"]),2)
        self.assertNotIn("q", assess({"questions":{"q":rule}},{"q":["a"]})["feedback"])

    def test_ungraded_poll_accepts_nonempty_response(self):
        grading = {"questions": {"reflection": {"accept_nonempty": True}}, "maximum_points": "0"}
        self.assertTrue(assess(grading, {"reflection": "To learn Python"})["passed"])
        self.assertFalse(assess(grading, {"reflection": "  "})["passed"])

    def test_single_choice_accepts_alternatives_but_not_multiple_selections(self):
        rule = {"selection": "one", "correct_choice_ids": ["a", "b"]}
        self.assertTrue(check_question(rule, "b"))
        self.assertFalse(check_question(rule, ["a", "b"]))

    def test_select_all_requires_exact_set_without_duplicates(self):
        rule = {"selection": "all", "correct_choice_ids": ["a", "b"]}
        self.assertTrue(check_question(rule, ["b", "a"]))
        for answer in [["a"], ["a", "b", "c"], ["a", "a", "b"]]:
            self.assertFalse(check_question(rule, answer))

    def test_numeric_tolerance_and_nonfinite_inputs(self):
        rule = {"answers": ["100"], "tolerance": "5%"}
        self.assertTrue(check_question(rule, "105"))
        for answer in ["105.01", "NaN", "Infinity", "hello"]:
            self.assertFalse(check_question(rule, answer))

    def test_case_policy_and_partial_credit(self):
        rule = {"answers": ["Python"], "case_sensitive": False}
        self.assertTrue(check_question(rule, " python "))
        result = assess({"questions": {"one": rule, "two": rule}}, {"one": "PYTHON"})
        self.assertEqual(result["fraction"], Decimal("0.5"))
        self.assertFalse(result["passed"])

    def test_locked_question_ignores_submitted_answer_and_drops_feedback(self):
        rule={"selection":"all","correct_choice_ids":["a"],"choice_feedback_rules":{
            "a":[{"selected":False,"content":[{"type":"text","text":"Remember A"}]}]}}
        result=assess({"questions":{"q":rule}},{"q":["a"]},locked={"q"})
        self.assertFalse(result["checks"]["q"])
        self.assertNotIn("q", result["feedback"])
        self.assertFalse(result["passed"])
