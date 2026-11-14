"""Real sandbox checks, opt-in on the dedicated Docker host."""
import os
import subprocess
import unittest
from grading import Case, Exercise, RunRequest, grade
from grading.docker_executor import DockerExecutor


@unittest.skipUnless(os.environ.get("RUN_DOCKER_TESTS") == "1", "Opt-in Docker integration")
class IsolationTests(unittest.TestCase):
    def test_network_secrets_and_filesystem_boundaries(self):
        source = '''
import os, socket
isolated = os.getuid() == 65534
isolated = isolated and 'RUNNER_TOKEN' not in os.environ
isolated = isolated and not os.path.exists('/var/run/docker.sock')
isolated = isolated and not os.path.exists('/opt/trellis/worker.env')
try:
    open('/forbidden', 'w').write('bad')
    isolated = False
except OSError:
    pass
for address in ('10.0.2.4', '169.254.169.254', '1.1.1.1'):
    try:
        socket.create_connection((address, 443), timeout=0.1).close()
        isolated = False
    except OSError:
        pass
open('/tmp/allowed', 'w').write('temporary')
'''
        result = grade(source, Exercise((Case("isolation", "Isolation", True, target="isolated"),)),
                       DockerExecutor())
        self.assertTrue(result["passed"])

    def test_workspace_is_disposable(self):
        executor = DockerExecutor()
        self.assertEqual(executor.run(RunRequest("open('/tmp/previous_attempt', 'w').write('private')")).status, "ok")
        result = grade("import os\nclean = not os.path.exists('/tmp/previous_attempt')",
                       Exercise((Case("clean", "Fresh workspace", True, target="clean"),)), executor)
        self.assertTrue(result["passed"])

    def test_processes_are_removed_after_timeout(self):
        response = DockerExecutor().run(RunRequest("while True: pass", timeout_seconds=0.1))
        self.assertEqual(response.status, "timeout")
        names = subprocess.check_output(["docker", "ps", "-a", "--filter", "name=cs1301-attempt-",
                                         "--format", "{{.Names}}"], text=True)
        self.assertEqual(names.strip(), "")
