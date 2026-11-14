import os
import unittest
import threading
import time
import service
from unittest.mock import patch
from grading import Observation
from service import configuration, execute_job


class Executor:
    def __init__(self, status="ok", value=5, stdout="hello\n"):
        self.status, self.value, self.stdout = status, value, stdout
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return Observation(self.status, self.value, self.stdout)


class WorkerTests(unittest.TestCase):
    def job(self, operation="submit"):
        return {"operation": operation, "entrypoint": "main.py", "files": {"main.py": "answer=5"},
                "definition": {"version": 1, "cases": [
                    {"id": "answer", "label": "Value", "target": "answer", "expected": 5}]}}

    def test_remote_url_requires_tls_and_explicit_token(self):
        with patch.dict(os.environ, {"RUNNER_API_URL": "https://trellis.example/api/runner/",
                                     "RUNNER_TOKEN": "secret"}, clear=True):
            self.assertEqual(configuration(), ("https://trellis.example/api/runner/", "secret"))
        for url in ("http://remote.example/api/runner/", "https://user:password@remote.example/",
                    "file:///tmp/token", "https://remote.example/?secret=oops"):
            with patch.dict(os.environ, {"RUNNER_API_URL": url, "RUNNER_TOKEN": "secret"}, clear=True):
                with self.assertRaises(ValueError):
                    configuration()
        with patch.dict(os.environ, {"RUNNER_API_URL": "https://remote.example/"}, clear=True):
            with self.assertRaises(ValueError):
                configuration()

    def test_run_does_not_grade_or_release_samples(self):
        result = execute_job(self.job("run"), Executor())
        self.assertEqual(result, {"stdout": "hello\n", "execution_status": "ok"})

    def test_local_worker_uses_the_configured_backend_port(self):
        with patch.dict(os.environ, {"RUNNER_TOKEN": "local-test", "TRELLIS_BACKEND_PORT": "8001"}, clear=True):
            self.assertEqual(configuration(), ("http://127.0.0.1:8001/api/runner/", "local-test"))

    def test_submit_compares_outside_sandbox(self):
        executor = Executor()
        result = execute_job(self.job(), executor)
        self.assertTrue(result["passed"])
        self.assertTrue(result["release_samples"])
        self.assertIn("full_results.txt", result["workspace_files"])
        self.assertFalse(hasattr(executor.requests[0], "expected"))
        self.assertEqual(execute_job(self.job(), Executor(value=4))["score_fraction"], "0")

    def test_service_failure_is_not_a_zero_grade(self):
        result = execute_job(self.job(), Executor(status="infrastructure_error"))
        self.assertIn("error", result)
        self.assertNotIn("score_fraction", result)

    def test_budget_expiry_is_not_a_zero_grade(self):
        with patch("service.time.monotonic", side_effect=[0, 241]):
            result = execute_job(self.job(), Executor())
        self.assertIn("error", result)
        self.assertNotIn("score_fraction", result)


class ParallelWorkerTests(unittest.TestCase):
    def tearDown(self):
        service.stopping.clear()

    def test_concurrency_has_a_small_validated_limit(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(service.concurrency(), 2)
        for value in ('0', '-1', '5', 'unlimited'):
            with patch.dict(os.environ, {'RUNNER_CONCURRENCY': value}):
                with self.assertRaises(ValueError): service.concurrency()

    def test_slots_overlap_without_sharing_sessions_or_claiming_twice(self):
        lock=threading.Lock(); barrier=threading.Barrier(2)
        pending=[{'id':str(i),'lease':'test'} for i in range(4)]
        completed=[]; sessions=[]; active=0; peak=0
        class Response:
            status_code=200
            def __init__(self, data):self.data=data
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def json(self):return self.data
        class Session:
            def __init__(self):self.headers={};self.closed=False;sessions.append(self)
            def __enter__(self):return self
            def __exit__(self,*args):self.closed=True
            def post(self,url,**kwargs):
                with lock:
                    if url.endswith('claim/'):
                        return Response({'job':pending.pop(0) if pending else None})
                    completed.append(url.split('/')[-2])
                    if len(completed)==4:service.stopping.set()
                    return Response({'ok':True})
        def execute(job,executor):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            barrier.wait(timeout=5)
            time.sleep(.01)
            with lock:active-=1
            return {'stdout':'ok'}
        with patch.dict(os.environ,{'RUNNER_API_URL':'https://test.example/api/runner/','RUNNER_TOKEN':'test','RUNNER_CONCURRENCY':'2'}), \
             patch('service.requests.Session',Session), patch('service.DockerExecutor'), patch('service.execute_job',execute), patch('service.signal.signal'):
            service.main()
        self.assertEqual(peak,2)
        self.assertCountEqual(completed,['0','1','2','3'])
        self.assertEqual(len(sessions),2)
        self.assertTrue(all(s.closed for s in sessions))
