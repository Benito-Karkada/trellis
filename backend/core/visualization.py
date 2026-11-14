"""Read-only Python traces. Source executes only on the isolated runner."""
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import Activity, ExecutionJob, Membership, QuizAttempt, VisualizationJob
from .studio import json_body, member, starter_files
from .visualization_inputs import public_cases, select_case, walkthrough


def access(request):
    if not request.user.is_authenticated:
        raise PermissionDenied
    memberships = Membership.objects.filter(user=request.user, active=True)
    if not memberships.exists():
        raise PermissionDenied
    # A direct URL must not bypass an active exam's navigation lock.
    if QuizAttempt.objects.filter(membership__in=memberships, submitted_at=None,
            lesson__metadata__kind="programming_quiz", lesson__metadata__exam_mode=True,
            expires_at__gt=timezone.now()).exists():
        raise PermissionDenied


def samples(revision):
    return [file for file in revision.files.filter(visibility__in=["staff", "grader"]).order_by("path")
            if file.path.split("/")[-1].startswith("sample_answer") and file.path.endswith(".py")]


def unlocked(request, revision):
    if revision.activity.lesson.metadata.get("kind") == "programming_quiz":
        return False
    membership = Membership.objects.filter(user=request.user, course=revision.activity.lesson.course, active=True).first()
    if not membership:
        return False
    if membership.role in {"instructor", "head_ta", "ta"} and request.session.get("student_view_course") != membership.course_id:
        return True
    return ExecutionJob.objects.filter(user=request.user, revision=revision, operation="submit",
        preview=False, status="completed", result__passed=True, result__score_fraction__in=[1, "1", "1.0"]).exists()


def sample_data(request, pk):
    access(request)
    activity = get_object_or_404(Activity, pk=pk, deleted_at=None, lesson__deleted_at=None)
    member(request, activity)
    revision = activity.published_revision
    if not revision or not unlocked(request, revision):
        raise PermissionDenied
    files = samples(revision)
    if not files:
        raise Http404
    try:
        selected = select_case(revision, request.GET.get("case"))
    except ValueError:
        raise Http404
    result = []
    for file in files:
        with file.blob.open("rb") as stream:
            source = stream.read(12001).decode("utf-8", errors="replace")
            try:
                source = walkthrough(source, selected)
            except (SyntaxError, ValueError, TypeError, RecursionError):
                return JsonResponse({"error": "This sample cannot be prepared for the selected test input."}, status=400)
            result.append({"path": file.path, "source": source})
    return JsonResponse({"title": activity.title, "revision": revision.pk, "samples": result,
        "selected_case": selected["id"] if selected else "original",
        "cases": [{"id": case["id"], "label": case.get("label", case["id"]), "stdin": case.get("stdin", "")} for case in public_cases(revision)]})


@require_POST
@json_body
@transaction.atomic
def start(request):
    access(request)
    if not getattr(settings, "EXECUTION_ENABLED", True):
        return JsonResponse({"error": "The execution worker is unavailable."}, status=503)
    source, files, revision = request.payload.get("source"), {}, None
    if "activity" in request.payload:
        if type(request.payload["activity"]) is not int:
            return JsonResponse({"error": "Choose an exercise ID."}, status=400)
        activity = get_object_or_404(Activity, pk=request.payload["activity"], deleted_at=None, lesson__deleted_at=None)
        member(request, activity)
        revision = activity.published_revision
        if not revision or not unlocked(request, revision):
            raise PermissionDenied
        if request.payload.get("revision", revision.pk) != revision.pk:
            return JsonResponse({"error": "This exercise changed. Reopen the walkthrough before tracing it."}, status=409)
        sample = next((file for file in samples(revision) if file.path == request.payload.get("sample")), None)
        if sample is None:
            raise Http404
        with sample.blob.open("rb") as stream:
            source = stream.read(12001).decode("utf-8", errors="replace")
        try:
            source = walkthrough(source, select_case(revision, request.payload.get("case")))
        except (SyntaxError, ValueError, TypeError, RecursionError):
            return JsonResponse({"error": "This sample cannot be prepared for the selected test input."}, status=400)
        files = {path: text for path, text in starter_files(revision).items() if path.endswith(".py")}
    stdin = request.payload.get("stdin", "")
    if not isinstance(source, str) or not source.strip() or len(source.encode()) > 12000 or len(source.splitlines()) > 300:
        return JsonResponse({"error": "Use a program up to 300 lines and 12 KB."}, status=400)
    if not isinstance(stdin, str) or len(stdin.encode()) > 2000:
        return JsonResponse({"error": "Program input must be under 2 KB."}, status=400)
    if sum(len(text.encode()) for text in files.values()) > 200000:
        return JsonResponse({"error": "This exercise has too many supporting files to visualize."}, status=400)
    get_user_model().objects.select_for_update().get(pk=request.user.pk)
    VisualizationJob.objects.filter(user=request.user, status__in=["pending", "running"],
        created_at__lt=timezone.now()-timedelta(minutes=5)).update(
            status="failed", result={"error": "The previous visualization expired. Please try again."})
    if (ExecutionJob.objects.filter(user=request.user, status__in=["pending", "running"]).exists()
            or VisualizationJob.objects.filter(user=request.user, status__in=["pending", "running"]).exists()):
        return JsonResponse({"error": "Wait for your current code execution to finish."}, status=409)
    if VisualizationJob.objects.filter(user=request.user, created_at__gte=timezone.now()-timedelta(minutes=1)).count() >= 12:
        return JsonResponse({"error": "Please wait a minute before starting another visualization."}, status=429)
    job = VisualizationJob.objects.create(user=request.user, revision=revision, source=source, files=files, stdin=stdin)
    # Traces are temporary learning aids, not submissions or permanent code history.
    VisualizationJob.objects.filter(user=request.user, created_at__lt=timezone.now()-timedelta(days=1)).exclude(
        status__in=["pending", "running"]).delete()
    return JsonResponse({"id": str(job.pk), "status": job.status})


def status(request, pk):
    access(request)
    job = get_object_or_404(VisualizationJob, pk=pk, user=request.user)
    if job.revision_id:
        member(request, job.revision.activity)
        if not unlocked(request, job.revision):
            raise PermissionDenied
    if job.status in {"pending", "running"} and job.created_at < timezone.now()-timedelta(minutes=5):
        VisualizationJob.objects.filter(pk=job.pk, status__in=["pending", "running"]).update(
            status="failed", result={"error": "The execution worker did not respond. Check that the local worker is running and try again."})
        job.refresh_from_db()
    return JsonResponse({"id": str(job.pk), "status": job.status, "result": job.result})
