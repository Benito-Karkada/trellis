"""Verify local Run/Submit with a separate worker running; remove the temporary student's records."""
import time
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client

from core.models import Activity, ActivityProgress, ExecutionJob, GradeEvent, Membership, Submission, Workspace
from core.studio import starter_files

activity = None
correct = None
for candidate in Activity.objects.filter(lesson__course__metadata__local_course_key="cs1301",
        lesson__visibility="student", deleted_at=None, published_revision__isnull=False,
        metadata__kind="coding").select_related("published_revision", "lesson").order_by("lesson__position", "position", "pk"):
    definition = candidate.published_revision.grading.get("definition") or {}
    if (candidate.metadata.get("sandbox") or candidate.lesson.metadata.get("kind") == "programming_quiz"
            or not 1 <= len(definition.get("cases", [])) <= 10 or definition.get("random_cases")
            or candidate.metadata.get("due_at") or candidate.lesson.metadata.get("due_at")):
        continue
    sample = candidate.published_revision.files.filter(visibility="staff", path__startswith="solutions/sample_answer").first()
    if sample:
        activity = candidate
        with sample.blob.open("rb") as stream:
            correct = stream.read().decode("utf-8")
        break
assert activity is not None, "Load the full course before running this check."
revision = activity.published_revision
entrypoint = revision.grading["entrypoint"]
user = get_user_model().objects.create_user("execution-check-" + uuid4().hex)
try:
    Membership.objects.create(user=user, course=activity.lesson.course, role="student")
    client = Client(HTTP_HOST="localhost")
    client.force_login(user)

    def execute(operation, source):
        saved = Workspace.objects.filter(user=user, revision=revision).first()
        files = dict(saved.files) if saved else starter_files(revision)
        files[entrypoint] = source
        response = client.post(f"/api/execute/{revision.pk}/", {
            "operation": operation, "entrypoint": entrypoint, "files": files}, content_type="application/json")
        assert response.status_code == 200, response.content
        job = ExecutionJob.objects.get(pk=response.json()["id"])
        for _ in range(120):
            job.refresh_from_db()
            if job.status in {"completed", "failed"}:
                break
            time.sleep(0.5)
        assert job.status == "completed" and not job.result.get("error"), job.result
        return job.result

    result = execute("run", correct)
    assert result["execution_status"] == "ok" and "score" not in result, result
    result = execute("submit", "def unfinished(\n")
    assert not result["passed"], result
    workspace = Workspace.objects.get(user=user, revision=revision)
    baseline = starter_files(revision)
    assert all(workspace.files.get(name) == value for name, value in baseline.items() if name.startswith("sample_answer"))
    result = execute("submit", correct)
    assert result["passed"] and result["score"] == result["maximum"], result
    workspace.refresh_from_db()
    assert "We expected" in workspace.files["full_results.txt"]
    assert any(name.startswith("sample_answer") and value.strip() == correct.strip()
               for name, value in workspace.files.items())
    assert ActivityProgress.objects.get(user=user, activity=activity).completed
    print("Local execution passed: Run output, incorrect/correct submission, points, feedback, and sample release.")
finally:
    GradeEvent.objects.filter(submission__membership__user=user).delete()
    Submission.objects.filter(membership__user=user).delete()
    user.delete()
