"""Opt-in real container tests: RUN_DOCKER_TESTS=1 python -m unittest discover -s tests."""
import os
import unittest
import time
import subprocess
from grading import Case, Exercise, Observation, RunRequest, grade
from grading.docker_executor import DockerExecutor


@unittest.skipUnless(os.environ.get("RUN_DOCKER_TESTS") == "1", "Opt-in Docker integration")
class DockerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.executor = DockerExecutor()

    def test_real_variable_function_and_stdout(self):
        cases = (Case("v", "Variable", 5, target="answer"),
                 Case("f", "Function", 9, action="function", target="square", arguments=(3,)),
                 Case("o", "Output", "hello\n", action="stdout"))
        result = grade("answer=5\ndef square(x): return x*x\nprint('hello')",
                       Exercise(cases), self.executor, operation="submit")
        self.assertTrue(result["passed"])
        self.assertTrue(result["release_samples"])

    def test_runtime_error(self):
        self.assertEqual(self.executor.run(RunRequest("raise ValueError('oops')")).status, "runtime_error")

    def test_file_comparison_and_missing_variable_feedback(self):
        result = grade("open('result.txt','w').write('hello')", Exercise((
            Case("file", "Output file", "hello", action="file", target="result.txt"),)), self.executor)
        self.assertTrue(result["passed"])
        self.assertIn("the file result.txt to contain this, and it did", result["full_output"])
        missing = grade("pass", Exercise((Case("v", "Variable", 2, target="answer"),)), self.executor)
        self.assertIn("called answer, but we did not", missing["full_output"])

    def test_raw_output_flood_is_bounded(self):
        response = self.executor.run(RunRequest("import os\nwhile True: os.write(1,b'x'*8192)"))
        self.assertEqual(response.status, "output_limit")

    def test_timeout_and_container_cleanup(self):
        start = time.monotonic()
        response = self.executor.run(RunRequest("while True: pass", timeout_seconds=0.1))
        self.assertEqual(response.status, "timeout")
        self.assertLess(time.monotonic() - start, 4)
        self.assertEqual(self.executor.run(RunRequest("print('Ready again')")).stdout, 'Ready again\n')
        containers = subprocess.check_output(['docker', 'ps', '-aq', '--filter', 'name=cs1301-attempt-'], text=True)
        self.assertEqual(containers.strip(), '')

    def test_no_root_or_host_mounts(self):
        source = "import os\nanswer = os.getuid() == 65534 and not os.path.exists('/var/run/docker.sock')"
        result = grade(source, Exercise((Case("isolation", "Isolation", True, target="answer"),)), self.executor)
        self.assertTrue(result["passed"])


    def test_visualization_keeps_aliases_and_never_returns_a_grade(self):
        observation = self.executor.run(RunRequest(
            "first = [1, 2]\nsecond = first\nsecond.append(3)\nprint(first)", action="visualize"))
        self.assertEqual(observation.status, "ok")
        trace = observation.value
        self.assertEqual(trace["stdout"], "[1, 2, 3]\n")
        self.assertFalse(trace["truncated"])
        variables = trace["steps"][-1]["frames"][0]["locals"]
        self.assertEqual(variables["first"], variables["second"])
        self.assertNotIn("score_fraction", trace)

    def test_visualization_stops_infinite_loops_and_removes_the_container(self):
        observation = self.executor.run(RunRequest("while True:\n    pass", action="visualize"))
        self.assertTrue(observation.value["truncated"])
        self.assertLessEqual(len(observation.value["steps"]), 220)
        containers = subprocess.check_output(['docker', 'ps', '-aq', '--filter', 'name=cs1301-attempt-'], text=True)
        self.assertEqual(containers.strip(), '')
