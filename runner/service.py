"""Trusted queue worker on a dedicated Docker execution host (local or Azure).

Only the controller has the runner credential. The DockerExecutor supplies no
credentials, expected answers, host mounts or networks to student containers.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import logging
import os
import signal
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
from grading import grade, RunRequest
from grading.manifest import load_definition
from grading.docker_executor import DockerExecutor

log = logging.getLogger("trellis.worker")
stopping = threading.Event()


def configuration():
    token = os.environ.get("RUNNER_TOKEN", "")
    if not token and not os.environ.get("RUNNER_API_URL"):
        env = Path(__file__).resolve().parent.parent / ".env"
        if env.exists():
            token = next((line.split("=", 1)[1].strip() for line in env.read_text().splitlines()
                          if line.startswith("RUNNER_TOKEN=")), "")
    base = os.environ.get("RUNNER_API_URL", "http://127.0.0.1:8000/api/runner/")
    parsed = urlsplit(base)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme != "https" and not
                (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}))) :
        raise ValueError("Worker requires HTTPS, except on localhost")
    if not token or "\n" in token or "\r" in token:
        raise ValueError("Configure RUNNER_TOKEN on the execution host")
    return base.rstrip("/") + "/", token


class BudgetExecutor:
    """Finish before Django's five-minute lease expires, even for many cases."""
    def __init__(self, executor):
        self.executor = executor
        self.deadline = time.monotonic() + 240

    def run(self, request):
        remaining = self.deadline - time.monotonic() - 5
        if remaining < request.timeout_seconds:
            raise RuntimeError("Attempt exceeded the execution budget")
        return self.executor.run(request)


def execute_job(job, executor):
    try:
        bounded = BudgetExecutor(executor)
        source = job["files"][job["entrypoint"]]
        if job["operation"] == "run":
            observation = bounded.run(RunRequest(source=source, files=job["files"]))
            if observation.status == "infrastructure_error":
                return {"error": "Execution service unavailable. Retry the attempt."}
            message = {
                "timeout": "Your program exceeded the time limit and was stopped safely. Check that your loops reach their stopping condition, then try again.",
                "output_limit": "Your program produced too much output and was stopped safely. Check for a loop that keeps printing, then try again.",
            }.get(observation.status)
            return {"stdout": (observation.stdout + "\n\n" + message).strip() if message else observation.stdout,
                    "execution_status": observation.status}
        if job["operation"] != "submit":
            raise ValueError("Unknown operation")
        return grade(source, load_definition(job["definition"]), bounded,
                     operation="submit", files=job["files"], oracle_source=job.get("oracle_source"), oracle_files=job.get("oracle_files"),
                     random_seed=int.from_bytes(hashlib.sha256(str(job.get("id", "local")).encode()).digest()[:16],"big"))
    except Exception:
        # Do not print source, test definitions, credentials or raw exceptions.
        return {"error": "The grading job could not complete. Check its configuration and retry."}


def concurrency():
    """Bound admission to the host; each slot runs at most one sandbox at a time."""
    value = int(os.environ.get("RUNNER_CONCURRENCY", "2"))
    if not 1 <= value <= 4:
        raise ValueError("RUNNER_CONCURRENCY must be between 1 and 4")
    return value


def work_slot(base, token, executor):
    # requests sessions are private to a slot, never shared between threads.
    with requests.Session() as session:
        session.trust_env = False
        session.headers["Authorization"] = "Bearer " + token
        consume_jobs(session, base, executor)


def consume_jobs(session, base, executor):
    while not stopping.is_set():
        try:
            with session.post(base + "claim/", timeout=10, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise requests.RequestException("Claim rejected")
                job = response.json()["job"]
            if not job:
                stopping.wait(2)
                continue
            result = execute_job(job, executor)
            for retry in range(5):
                try:
                    with session.post(base + "complete/" + job["id"] + "/",
                            json={"lease": job["lease"], "result": result}, timeout=10,
                            allow_redirects=False) as response:
                        if response.status_code == 409:
                            log.warning("Attempt lease expired; result not applied")
                            break
                        if response.status_code != 200:
                            raise requests.RequestException("Completion rejected")
                    log.info("Attempt completed%s", " with service error" if "error" in result else "")
                    break
                except requests.RequestException:
                    if retry == 4:
                        log.warning("Completion unavailable; attempt will expire without a grade")
                    else:
                        time.sleep(1 + retry)
        except (requests.RequestException, ValueError, KeyError):
            log.warning("Queue unavailable; retrying")
            stopping.wait(5)



def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    base, token = configuration()
    slots = concurrency()
    # This adapter holds only an immutable image ID. Every run uses independent
    # request state, subprocesses, pipes, deadlines and a uniquely named container.
    executor = DockerExecutor(image=os.environ.get("RUNNER_IMAGE", "cs1301-student-python:local"))
    stopping.clear()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopping.set())
    log.info("Trellis execution worker ready; concurrency=%s", slots)
    with ThreadPoolExecutor(max_workers=slots, thread_name_prefix="trellis-executor") as pool:
        futures = [pool.submit(work_slot, base, token, executor) for _ in range(slots)]
        try:
            for future in as_completed(futures):
                future.result()
        finally:
            # Stop claiming new work, but let already claimed jobs finish and
            # report results before systemd restarts or stops this process.
            stopping.set()


if __name__ == "__main__":
    main()
