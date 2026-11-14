import unittest
from grading import Case, Exercise, Observation, Requirement, grade
from grading.manifest import load_definition


class FakeExecutor:
    """Simulates sandbox observations; never runs submitted source in tests."""
    def __init__(self, *observations):
        self.observations = iter(observations)
        self.requests = []
    def run(self, request):
        self.requests.append(request)
        return next(self.observations)


class GradingTests(unittest.TestCase):
    def test_private_definition_loads_without_python_imports(self):
        exercise = load_definition({"version":1, "cases":[
            {"id":"value", "label":"Value", "expected":5, "target":"answer"}]})
        self.assertEqual(exercise.cases[0].expected, 5)
        self.assertEqual(exercise.scoring, "all_or_nothing")

    def test_definition_rejects_unknown_fields_and_ambiguous_visibility(self):
        for extra in [{"python_helper":"some_module"}, {"public":"false"}]:
            with self.assertRaises(ValueError):
                load_definition({"version":1, "cases":[
                    {"id":"value", "label":"Value", "expected":5, "target":"answer", **extra}]})

    def exercise(self, **kwargs):
        return Exercise((Case("answer", "Value", 5, target="days_between"),), **kwargs)

    def test_successful_check_updates_feedback_without_releasing_solutions(self):
        result = grade("days_between = 5", self.exercise(), FakeExecutor(Observation("ok", 5)))
        self.assertEqual(result["score_fraction"], "1")
        self.assertFalse(result["release_samples"])
        self.assertIn("We expected the value", result["workspace_files"]["full_results.txt"])

    def test_successful_submit_releases_samples(self):
        self.assertTrue(grade("days_between = 5", self.exercise(),
                             FakeExecutor(Observation("ok", 5)), operation="submit")["release_samples"])

    def test_expectations_are_public_feedback_but_not_sent_to_executor(self):
        executor = FakeExecutor(Observation("ok", "wrong"))
        exercise = Exercise((Case("case1", "secret label", "secret answer", target="answer"),))
        result = grade("answer = ''", exercise, executor)
        self.assertIn("secret answer", result["full_output"])
        self.assertIn("wrong", result["full_output"])
        self.assertNotIn("Private test", result["full_output"])
        self.assertNotIn("secret", str(executor.requests))
        self.assertEqual(result["score_fraction"], "0")

    def test_syntax_error_prevents_execution(self):
        executor = FakeExecutor()
        result = grade("if :", self.exercise(), executor, operation="submit")
        self.assertFalse(result["release_samples"])
        self.assertEqual(executor.requests, [])

    def test_source_requirements_inspect_syntax_not_comments(self):
        exercise = self.exercise(requirements=(Requirement("loop", "require_node", "For", "Use a for loop."),))
        result = grade("# for x in values:\ndays_between=5", exercise, FakeExecutor(Observation("ok", 5)))
        self.assertEqual(result["score_fraction"], "0")
        self.assertFalse(result["release_samples"])

    def test_timeout_produces_feedback_not_an_exception(self):
        result = grade("while True: pass", self.exercise(), FakeExecutor(Observation("timeout")))
        self.assertIn("time limit", result["full_output"])

    def test_resource_limit_stops_remaining_tests_without_awarding_credit(self):
        for status in ('timeout', 'output_limit'):
            executor = FakeExecutor(Observation(status))
            exercise = Exercise(tuple(Case(str(i), f'Test {i}', 1, target='x') for i in range(20)))
            outcome = grade('while True: pass', exercise, executor, operation='submit')
            self.assertEqual(len(executor.requests), 1)
            self.assertEqual(len(outcome['checks']), 20)
            self.assertEqual(outcome['score_fraction'], '0')
            self.assertFalse(outcome['release_samples'])
            self.assertIn('Not run because', outcome['full_output'])

    def test_infrastructure_error_does_not_produce_student_grade(self):
        with self.assertRaises(RuntimeError):
            grade("x=1", self.exercise(), FakeExecutor(Observation("infrastructure_error")))

    def test_weighted_scoring_is_explicit_and_partial_does_not_release_samples(self):
        exercise = Exercise((Case("a", "First", 1, target="x"), Case("b", "Second", 2, target="x")),
                            scoring="weighted")
        result = grade("x=1", exercise, FakeExecutor(Observation("ok", 1), Observation("ok", 0)), operation="submit")
        self.assertEqual(result["score_fraction"], "0.5")
        self.assertFalse(result["release_samples"])

    def test_boolean_is_not_accepted_as_numeric_answer(self):
        result = grade("x=True", Exercise((Case("a", "Value", 1, target="x"),)), FakeExecutor(Observation("ok", True)))
        self.assertFalse(result["passed"])

    def test_hostile_observation_does_not_crash_comparison(self):
        result = grade("x=1", self.exercise(), FakeExecutor(Observation("ok", 10**2000)))
        self.assertFalse(result["passed"])

    def test_stdout_comparison_and_function_request(self):
        exercise = Exercise((Case("out", "Output", "hello\n", action="stdout"),
                             Case("fn", "Function", 9, action="function", target="square", arguments=(3,))))
        executor = FakeExecutor(Observation("ok", stdout="hello\n"), Observation("ok", 9))
        self.assertTrue(grade("def square(x): return x*x", exercise, executor)["passed"])
        self.assertEqual(executor.requests[1].arguments, (3,))

    def test_class_scenario_is_declarative_and_forwarded_to_executor(self):
        steps=({"op":"attribute","name":"title"},{"op":"call","name":"description","arguments":[]})
        exercise=Exercise((Case("book","Book behavior",["Dune","Dune has 412 pages."],action="scenario",
            target="Book",arguments=("Dune",412),steps=steps),))
        executor=FakeExecutor(Observation("ok",["Dune","Dune has 412 pages."]))
        self.assertTrue(grade("class Book: pass",exercise,executor)["passed"])
        self.assertEqual(executor.requests[0].steps,steps)


if __name__ == "__main__":
    unittest.main()
