"""Verify local Run/Submit with a separate worker running; remove the temporary student's records."""
import time
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client

from core.models import Activity, ActivityProgress, ExecutionJob, GradeEvent, Membership, Submission, Workspace
from core.studio import starter_files

activity = Activity.objects.get(metadata__demo_key="sum")
revision = activity.published_revision
user = get_user_model().objects.create_user("execution-check-" + uuid4().hex)
try:
    Membership.objects.create(user=user, course=activity.lesson.course, role="student")
    client = Client(HTTP_HOST="localhost")
    client.force_login(user)

    def execute(operation, source):
        saved = Workspace.objects.filter(user=user, revision=revision).first()
        files = dict(saved.files) if saved else starter_files(revision)
        files["main.py"] = source
        response = client.post(f"/api/execute/{revision.pk}/", {
            "operation": operation, "entrypoint": "main.py", "files": files}, content_type="application/json")
        assert response.status_code == 200, response.content
        job = ExecutionJob.objects.get(pk=response.json()["id"])
        for _ in range(120):
            job.refresh_from_db()
            if job.status in {"completed", "failed"}:
                break
            time.sleep(0.5)
        assert job.status == "completed" and not job.result.get("error"), job.result
        return job.result

    correct = "a = 7\nb = 3\nprint(a + b)\n"
    result = execute("run", correct)
    assert result["stdout"] == "10\n" and "score" not in result, result
    result = execute("submit", "a = 7\nb = 3\nprint(a - b)\n")
    assert not result["passed"], result
    workspace = Workspace.objects.get(user=user, revision=revision)
    assert not workspace.files.get("sample_answer.py", "").strip()
    result = execute("submit", correct)
    assert result["passed"] and result["score"] == result["maximum"], result
    workspace.refresh_from_db()
    assert "We expected" in workspace.files["full_results.txt"]
    assert workspace.files["sample_answer.py"].strip()
    assert ActivityProgress.objects.get(user=user, activity=activity).completed
    print("Local execution passed: Run output, incorrect/correct submission, points, feedback, and sample release.")
finally:
    GradeEvent.objects.filter(submission__membership__user=user).delete()
    Submission.objects.filter(membership__user=user).delete()
    user.delete()
