"""Real CPython tracing tests; the app never executes this source itself."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from grading import RunRequest
from dataclasses import asdict
from service import execute_job

SANDBOX = Path(__file__).resolve().parents[1] / "sandbox" / "execute.py"


def trace(source, **kwargs):
    request = asdict(RunRequest(source=source, action="visualize", **kwargs))
    # Only test-owned source is run here. Real requests always use DockerExecutor.
    result = subprocess.run([sys.executable,"-I",str(SANDBOX)],input=json.dumps(request),
                            capture_output=True,text=True,timeout=5,check=True)
    return json.loads(result.stdout)


class VisualizationTests(unittest.TestCase):
    def test_loop_snapshots_are_before_line_and_final_state_has_completed_output(self):
        result=trace("total = 0\nfor n in [1, 2, 3]:\n    total += n\nprint(total)")
        self.assertEqual(result["status"],"ok")
        rows=result["value"]["steps"]
        self.assertEqual(rows[0]["line"],1)
        self.assertEqual(rows[0]["frames"][0]["locals"],{})
        self.assertEqual(rows[-1]["frames"][0]["locals"]["total"]["value"],6)
        self.assertEqual(rows[-1]["stdout"],"6\n")
        self.assertEqual(rows[-1]["event"],"return")

    def test_aliases_collections_cycles_and_object_attributes(self):
        source="""class Counter:
    def __init__(self):
        self.count = 1
obj = Counter()
a = [1, 2]
b = a
a.append(a)
coordinates = (3, 4)
counts = {'duck': 2}
"""
        row=trace(source)["value"]["steps"][-1]
        variables=row["frames"][0]["locals"]
        self.assertEqual(variables["a"],variables["b"])
        ref=variables["a"]["ref"]
        self.assertEqual(row["heap"][ref]["items"][-1][1],{"ref":ref})
        self.assertEqual(row["heap"][variables["coordinates"]["ref"]]["type"],"tuple")
        self.assertEqual(row["heap"][variables["counts"]["ref"]]["type"],"dict")
        self.assertEqual(row["heap"][variables["obj"]["ref"]]["items"][0][0],"count")

    def test_recursive_call_stack_and_return_values(self):
        rows=trace("def fact(n):\n    if n <= 1: return 1\n    return n * fact(n-1)\nanswer = fact(4)")["value"]["steps"]
        self.assertEqual(max(len(row["frames"]) for row in rows),5)
        self.assertTrue(any(row.get("returned",{}).get("value")==24 for row in rows))
        self.assertEqual(rows[-1]["frames"][0]["locals"]["answer"]["value"],24)

    def test_inspection_does_not_call_user_repr_or_dict_properties(self):
        result=trace("""class Dangerous:
    def __repr__(self):
        print('BAD REPR')
        return 'unsafe'
    @property
    def __dict__(self):
        print('BAD PROPERTY')
        return {}
x = Dangerous()
print('safe')
""")
        self.assertEqual(result["stdout"],"safe\n")

    def test_error_and_syntax_error_are_explorable(self):
        result=trace("value=1\nprint(missing)")
        self.assertEqual(result["status"],"runtime_error")
        self.assertIn("NameError",result["value"]["stdout"])
        self.assertTrue(result["value"]["steps"])
        result=trace("for")
        self.assertEqual(result["value"]["steps"],[])
        self.assertIn("SyntaxError",result["value"]["stdout"])

    def test_infinite_loop_and_large_snapshots_are_bounded(self):
        result=trace("while True:\n    pass")
        self.assertTrue(result["value"]["truncated"])
        self.assertLessEqual(len(result["value"]["steps"]),220)
        result=trace("items=list(range(500))\nwhile True:\n    items.append(1)")
        self.assertLess(len(json.dumps(result)),65536)
        self.assertTrue(result["value"]["truncated"])
        self.assertTrue(any(item.get("truncated") for row in result["value"]["steps"] for item in row["heap"].values()))

    def test_stdin_and_library_internals(self):
        result=trace("import math\nnumber=int(input())\nprint(math.sqrt(number))",stdin="16\n")
        self.assertEqual(result["stdout"],"4.0\n")
        self.assertTrue(all(1<=row["line"]<=3 for row in result["value"]["steps"]))

    def test_wall_time_stops_blocking_library_calls(self):
        result=trace("import time\ntime.sleep(5)",timeout_seconds=.05)
        self.assertEqual(result["status"],"timeout")
        self.assertTrue(result["value"]["steps"])

    def test_worker_returns_trace_without_grades_or_release_flags(self):
        class Executor:
            def run(self, request):
                from grading import Observation
                assert request.action=="visualize"
                return Observation("ok",{"steps":[],"stdout":"","status":"ok","truncated":False})
        result=execute_job({"operation":"visualize","source":"pass"},Executor())
        self.assertIn("trace",result)
        self.assertNotIn("score_fraction",result)
        self.assertNotIn("release_samples",result)
