"""Authenticated queue between Django and the separate execution host."""
import secrets
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import Revision, Workspace, ExecutionJob, ActivityProgress, Membership, Submission, VisualizationJob
from .workspace_files import with_results_placeholder, results_unchanged, is_results_file
from .studio import member, json_body, starter_files, valid_path, require_authoring_access
from .services import require_staff
from .quizzes import require_active_attempt
from .assessment import display_points
from .deadlines import credit_open
from django.contrib.auth import get_user_model


@require_POST
@json_body
@transaction.atomic
def enqueue(request,pk):
    revision=get_object_or_404(Revision,pk=pk,activity__deleted_at=None,activity__lesson__deleted_at=None)
    member(request,revision.activity)
    if not getattr(settings, "EXECUTION_ENABLED", True):
        return JsonResponse({"error": "Python execution is not available in this preview yet."}, status=503)
    preview=request.payload.get("preview") is True
    if preview:require_authoring_access(request,revision.activity.lesson.course)
    elif revision.pk!=revision.activity.published_revision_id:raise Http404
    if not preview: require_active_attempt(request, revision.activity)
    operation=request.payload.get("operation")
    if operation not in {"run","submit"}:return JsonResponse({"error":"Unknown operation"},status=400)
    if operation == "submit" and (revision.activity.metadata.get("sandbox") or revision.activity.metadata.get("workspace_mode")=="sandbox"):
        return JsonResponse({"error":"Sandboxes are ungraded. Use Run."}, status=400)
    if revision.grading.get("placeholder"):return JsonResponse({"error":"Coding files have not been imported."},status=409)
    if operation=="submit" and not revision.grading.get("definition"):return JsonResponse({"error":"Configure test cases before submitting."},status=409)
    files=request.payload.get("files")
    if not isinstance(files,dict) or any(not valid_path(k) or not isinstance(v,str) for k,v in files.items()):
        return JsonResponse({"error":"Invalid workspace"},status=400)
    if sum(len(v.encode()) for v in files.values())>2_000_000:return JsonResponse({"error":"Workspace too large"},status=400)
    # Serialize all execution requests for an account, including first-use and
    # preview requests from different tabs. Reset takes this same lock first.
    get_user_model().objects.select_for_update().get(pk=request.user.pk)
    active = ExecutionJob.objects.filter(user=request.user, status__in=["pending", "running"]).first()
    if not active:
        active = VisualizationJob.objects.filter(user=request.user, status__in=["pending", "running"]).first()
    if active:
        return JsonResponse({"error": "Your code is already queued or running. Wait for it to finish before running or submitting again.",
                             "job_id": str(active.pk), "status": active.status}, status=409)
    if preview:
        # Preview must not create an empty saved workspace that masks work
        # carried forward from a previous published revision.
        allowed=starter_files(revision)
        generation=0
    else:
        workspace,_=Workspace.objects.select_for_update().get_or_create(user=request.user,revision=revision,
            defaults={"files":lambda:starter_files(revision)})
        allowed=workspace.files
        generation=workspace.generation
    allowed=with_results_placeholder(allowed)
    if preview:
        files={path:allowed.get(path,text) if is_results_file(path) else text for path,text in files.items()}
    if not preview and not results_unchanged(files,allowed):return JsonResponse({"error":"full_results.txt is read-only and is updated when you submit."},status=403)
    if set(files)!=set(allowed):return JsonResponse({"error":"The file list cannot be changed."},status=400)
    entrypoint=revision.grading.get("entrypoint") if operation=="submit" else request.payload.get("entrypoint")
    if not entrypoint:entrypoint=next((f for f in files if f.endswith(".py") and not f.startswith("sample_answer")),"")
    if entrypoint not in files or not entrypoint.endswith(".py"):return JsonResponse({"error":"Select a Python file."},status=400)
    if not preview:
        workspace.files=files;workspace.generation+=1;workspace.save()
        generation=workspace.generation
    signals = {}
    if not preview:
        from .code_review import analyze, policy, provided_python
        signals = analyze(files, provided_python(revision), policy(revision.activity.lesson.course))
    job=ExecutionJob.objects.create(user=request.user,revision=revision,generation=generation,
        operation=operation,snapshot=files,entrypoint=entrypoint,preview=preview,review_signals=signals)
    if not preview:
        from .tracking import event
        membership=Membership.objects.get(user=request.user,course=revision.activity.lesson.course,active=True)
        event(membership,revision.activity.lesson,'code_'+operation+'_requested',revision.activity,{'job_id':str(job.pk),'revision_id':revision.pk})
    return JsonResponse({"id":str(job.pk),"status":job.status})


def status(request,pk):
    if not request.user.is_authenticated:raise PermissionDenied
    job=get_object_or_404(ExecutionJob,pk=pk,user=request.user)
    member(request,job.revision.activity)
    return JsonResponse({"id":str(job.pk),"status":job.status,"result":job.result})


def worker_auth(request):
    expected=settings.RUNNER_TOKEN
    actual=request.headers.get("Authorization","").removeprefix("Bearer ")
    if not expected or not secrets.compare_digest(actual,expected):raise PermissionDenied


@csrf_exempt
@require_POST
@transaction.atomic
def claim(request):
    worker_auth(request)
    ExecutionJob.objects.filter(status="running",claimed_at__lt=timezone.now()-timedelta(minutes=5)).update(
        status="failed",result={"error":"Execution worker timed out. Please retry."})
    VisualizationJob.objects.filter(status="running", claimed_at__lt=timezone.now()-timedelta(minutes=5)).update(
        status="failed", result={"error": "The visualization timed out. Please try again."})
    trace=VisualizationJob.objects.select_for_update(skip_locked=True).filter(status="pending").order_by("created_at").first()
    job=ExecutionJob.objects.select_for_update(skip_locked=True).filter(status="pending").order_by("created_at").first()
    if trace and (not job or trace.created_at < job.created_at):
        trace.status="running";trace.lease=secrets.token_hex(24);trace.claimed_at=timezone.now();trace.save()
        return JsonResponse({"job":{"id":str(trace.pk),"lease":trace.lease,"operation":"visualize",
            "files":trace.files,"source":trace.source,"stdin":trace.stdin}})
    if not job:return JsonResponse({"job":None})
    job.status="running";job.lease=secrets.token_hex(24);job.claimed_at=timezone.now();job.save()
    payload={"id":str(job.pk),"lease":job.lease,"operation":job.operation,"files":job.snapshot,
        "entrypoint":job.entrypoint,"definition":job.revision.grading.get("definition")}
    spec=(payload["definition"] or {}).get("random_cases")
    if spec and job.operation=="submit":
        reference=job.revision.files.exclude(visibility="student").filter(path=spec.get("oracle_path")).first()
        if reference:
            with reference.blob.open("rb") as stream:payload["oracle_source"]=stream.read(256001).decode()
            payload["oracle_files"]=starter_files(job.revision)
    return JsonResponse({"job":payload})


@csrf_exempt
@require_POST
@json_body
@transaction.atomic
def complete(request,pk):
    worker_auth(request)
    trace=VisualizationJob.objects.select_for_update().filter(pk=pk).first()
    if trace:
        if not secrets.compare_digest(request.payload.get("lease", ""), trace.lease):raise PermissionDenied
        if trace.status=="completed":return JsonResponse({"ok":True})
        if trace.status!="running":return JsonResponse({"error":"Expired visualization"},status=409)
        result=request.payload.get("result",{})
        if not isinstance(result,dict):return JsonResponse({"error":"Invalid result"},status=400)
        trace.result=result;trace.status="failed" if "error" in result else "completed";trace.completed_at=timezone.now();trace.save()
        return JsonResponse({"ok":True})
    job=get_object_or_404(ExecutionJob.objects.select_for_update(),pk=pk)
    if not secrets.compare_digest(request.payload.get("lease",""),job.lease):raise PermissionDenied
    if job.status=="completed":return JsonResponse({"ok":True})
    if job.status!="running":return JsonResponse({"error":"Expired attempt"},status=409)
    result=request.payload.get("result",{})
    if not isinstance(result,dict):return JsonResponse({"error":"Invalid result"},status=400)
    job.result=result;job.status="failed" if "error" in result else "completed";job.completed_at=timezone.now();job.save()
    if job.status=="failed" or job.operation=="run":return JsonResponse({"ok":True})
    fraction=Decimal(str(result.get("score_fraction",0)))
    if not fraction.is_finite() or not 0<=fraction<=1:raise ValueError("Invalid score")
    maximum=Decimal(str(job.revision.grading.get("maximum_points",1)))
    result["score"]=display_points(fraction*maximum);result["maximum"]=display_points(maximum)
    if job.preview:
        job.result=result;job.save(update_fields=["result"])
        return JsonResponse({"ok":True})
    workspace=Workspace.objects.select_for_update().get(user=job.user,revision=job.revision)
    if workspace.generation!=job.generation:
        job.result["stale"]=True;job.save(update_fields=["result"])
        return JsonResponse({"ok":True})
    feedback=result.get("workspace_files",{}).get("full_results.txt")
    if isinstance(feedback,str):workspace.files["full_results.txt"]=feedback[:200000]
    is_quiz=job.revision.activity.lesson.metadata.get("kind")=="programming_quiz"
    if not is_quiz and result.get("release_samples") is True and result.get("passed") is True and fraction==1:
        for file in job.revision.files.exclude(visibility="student"):
            name=file.path.split("/")[-1]
            if name.startswith("sample_answer") and name.endswith(".py"):
                with file.blob.open("rb") as stream:workspace.files[name]=stream.read().decode()
    workspace.generation+=1;workspace.save()
    membership=Membership.objects.get(user=job.user,course=job.revision.activity.lesson.course)
    submission=Submission.objects.create(revision=job.revision,membership=membership,response={"job":str(job.pk)},received_at=job.created_at)
    get_user_model().objects.select_for_update().get(pk=job.user_id)
    practice=not credit_open(membership,job.revision.activity,job.created_at)
    result['practice']=practice
    progress,_=ActivityProgress.objects.get_or_create(user=job.user,activity=job.revision.activity)
    progress.viewed=True
    if not practice:
        progress.score=max(progress.score,fraction*maximum);progress.maximum=maximum
        progress.completed=progress.completed or (fraction==1 and result.get("passed") is True)
    progress.save()
    if not practice:
        from .canvas_sync import enqueue_grade
        enqueue_grade(membership,job.revision.activity.lesson)
    from .tracking import event
    event(membership,job.revision.activity.lesson,'code_submit_completed',job.revision.activity,
        {'job_id':str(job.pk),'submission_id':submission.pk,'practice':practice,'score':result['score'],'recorded_score':display_points(progress.score)})
    job.result=result;job.save(update_fields=["result"])
    return JsonResponse({"ok":True})
