"""Run through manage.py shell with the separate local worker already running."""
import time
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.test import Client
from core.models import Activity, Membership, Workspace, ExecutionJob, ActivityProgress, Submission
from core.studio import starter_files

activity = Activity.objects.get(title="Days between dates", metadata__kind="coding")
revision = activity.published_revision
user = get_user_model().objects.create_user("execution-check-" + uuid4().hex)
try:
    Membership.objects.create(user=user, course=activity.lesson.course, role="student")
    client = Client(HTTP_HOST="localhost")
    client.force_login(user)
    files = starter_files(revision)
    files["DaysBetweenDates.py"] = files["DaysBetweenDates.py"].replace(
        "#Write your code here!", "days_between = (later_date - earlier_date).days")
    response = client.post(f"/api/execute/{revision.pk}/", {
        "operation": "submit", "files": files}, content_type="application/json")
    assert response.status_code == 200, response.content
    job = ExecutionJob.objects.get(pk=response.json()["id"])
    for attempt in range(60):
        job.refresh_from_db()
        if job.status in {"completed", "failed"}:
            break
        time.sleep(0.5)
    assert job.status == "completed", job.result
    assert job.result["passed"], job.result
    assert job.result["score"] == job.result["maximum"], job.result
    workspace = Workspace.objects.get(user=user, revision=revision)
    assert workspace.files["full_results.txt"].strip()
    assert "We expected the value" in workspace.files["full_results.txt"]
    assert "Private test" not in workspace.files["full_results.txt"]
    assert any(text.strip() for name, text in workspace.files.items() if name.startswith("sample_answer"))
    assert ActivityProgress.objects.get(user=user, activity=activity).completed
    print("Submission passed: full credit, feedback file replaced, sample answer released, progress completed.")
finally:
    Submission.objects.filter(membership__user=user).delete()
    user.delete()
