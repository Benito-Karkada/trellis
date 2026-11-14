"""Local control-plane adapter. Never mount Docker's socket into the web app.

Run this adapter on the dedicated execution host. No host paths, private tests,
answers, course libraries, app credentials, or networks are supplied to containers.
"""
from dataclasses import asdict
import json
import selectors
import subprocess
import tempfile
import time
from uuid import uuid4
from .spec import Observation, RunRequest


class DockerExecutor:
    def __init__(self, image="cs1301-student-python:local"):
        resolved = subprocess.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                                  capture_output=True, text=True, timeout=10, check=True)
        self.image = resolved.stdout.strip()
        if not self.image.startswith("sha256:"):
            raise ValueError("Expected an immutable local image ID")

    def run(self, request: RunRequest) -> Observation:
        name = "cs1301-attempt-" + uuid4().hex
        command = ["docker", "run", "--pull=never", "--name", name, "--log-driver=none",
            "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit=32",
            "--memory=128m", "--memory-swap=128m", "--cpus=0.5",
            "--ulimit=nofile=64:64", "--user=65534:65534",
            "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777",
            "-i", self.image]
        # A regular input descriptor prevents a large request blocking a pipe write.
        with tempfile.TemporaryFile() as input_file:
            input_file.write(json.dumps(asdict(request), allow_nan=False).encode())
            input_file.seek(0)
            process = subprocess.Popen(command, stdin=input_file, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                stdout, stderr = bytearray(), bytearray()
                deadline = time.monotonic() + request.timeout_seconds + 5  # Container startup allowance.
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ, stdout)
                    selector.register(process.stderr, selectors.EVENT_READ, stderr)
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return Observation("timeout")
                        for key, _ in selector.select(min(remaining, 0.1)):
                            chunk = key.fileobj.read1(8192)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            key.data.extend(chunk)
                            if len(stdout) + len(stderr) > 65536:
                                return Observation("output_limit")
                exit_code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
                if exit_code == 125:
                    return Observation("infrastructure_error")
                if exit_code:
                    return Observation("runtime_error")
                try:
                    data = json.loads(stdout)
                    if (not isinstance(data, dict) or set(data) != {"status", "value", "stdout"}
                        or data["status"] not in {"ok", "timeout", "runtime_error", "output_limit", "missing_target"}
                        or not isinstance(data["stdout"], str)):
                        return Observation("runtime_error")
                    return Observation(data["status"], data["value"], data["stdout"])
                except (ValueError, RecursionError):
                    return Observation("runtime_error")
            except subprocess.TimeoutExpired:
                return Observation("timeout")
            finally:
                # Detach the bounded output reader before removal. A flooding
                # attach connection can otherwise block Docker's forced removal.
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()
                # Killing the CLI alone does not terminate its container.
                subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=15, check=True)
