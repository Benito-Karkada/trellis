from decimal import Decimal
from django.db import transaction
from django.http import JsonResponse, FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from .models import CourseAsset, Membership, Activity, ActivityProgress, Revision, Submission, QuestionCooldown
from .studio import member, json_body
from .services import require_staff
from .assessment import assess, display_points
from .deadlines import credit_open
from .cooldowns import active_locks, RETRY_COOLDOWN_SECONDS


def asset(request,pk):
    asset=get_object_or_404(CourseAsset,pk=pk)
    if not request.user.is_authenticated or not Membership.objects.filter(user=request.user,course=asset.course,active=True).exists():raise PermissionDenied
    response=FileResponse(asset.blob.open("rb"),content_type=asset.content_type)
    response["Content-Security-Policy"]="default-src 'none'; sandbox"
    response["X-Content-Type-Options"]="nosniff"
    return response


@require_POST
def viewed(request,pk):
    activity=get_object_or_404(Activity,pk=pk,deleted_at=None,lesson__deleted_at=None)
    membership=member(request,activity)
    if not activity.published_revision:raise Http404
    progress,_=ActivityProgress.objects.get_or_create(user=request.user,activity=activity)
    progress.viewed=True
    if activity.metadata.get("kind") in {"reading","video"} or activity.metadata.get("sandbox"):
        progress.completed=True
        progress.save(update_fields=["viewed", "completed", "updated_at"])
    else:
        progress.save(update_fields=["viewed", "updated_at"])
    from .tracking import event
    event(membership,activity.lesson,"part_opened",activity)
    return JsonResponse({"ok":True})



def native_practice(progress):
    return bool(progress and any(value.get('practice') for value in progress.question_state.values()))


def native_reset_available(revision, progress):
    rules = revision.grading.get('questions', {})
    if not rules or not progress:
        return False
    if not progress.question_state:
        # Older full-credit records have no per-question attempt state.
        return progress.completed and progress.maximum > 0 and progress.score >= progress.maximum
    return all(progress.question_state.get(qid, {}).get('correct') is True for qid in rules)


@require_POST
@transaction.atomic
def reset_native(request, pk):
    revision = get_object_or_404(Revision, pk=pk, activity__deleted_at=None, activity__lesson__deleted_at=None)
    membership = member(request, revision.activity)
    from .quizzes import require_active_attempt
    require_active_attempt(request, revision.activity)
    if revision.pk != revision.activity.published_revision_id:
        raise Http404
    if revision.activity.metadata.get('kind') == 'coding' or not revision.grading.get('questions'):
        return JsonResponse({'error': 'Only non-coding exercises can be reset here.'}, status=400)
    get_user_model().objects.select_for_update().get(pk=request.user.pk)
    progress = ActivityProgress.objects.filter(user=request.user, activity=revision.activity).first()
    if not native_reset_available(revision, progress):
        return JsonResponse({'error': 'Answer every question correctly before resetting this exercise.'}, status=409)
    # Explicit empty attempt entries disable the legacy full-credit review fallback.
    # Earned points, completion, prior submissions and Canvas grades stay intact.
    progress.question_state = {qid: {'solved': False, 'practice': True} for qid in revision.grading['questions']}
    progress.save(update_fields=['question_state', 'updated_at'])
    QuestionCooldown.objects.filter(membership=membership, revision__activity=revision.activity).delete()
    from .tracking import event
    event(membership, revision.activity.lesson, 'native_reset', revision.activity, {'revision_id': revision.pk})
    response = JsonResponse({'ok': True, 'practice': True, 'recorded_score': display_points(progress.score)})
    response['Cache-Control'] = 'no-store'
    return response


@require_POST
@json_body
@transaction.atomic
def submit_native(request,pk):
    revision=get_object_or_404(Revision,pk=pk,activity__deleted_at=None,activity__lesson__deleted_at=None)
    member(request,revision.activity)
    if revision.activity.metadata.get("sandbox"):
        return JsonResponse({"error":"Sandboxes are ungraded. Use Run."},status=400)
    preview=request.payload.get("preview") is True
    if preview:require_staff(request.user,revision.activity.lesson.course)
    elif revision.pk!=revision.activity.published_revision_id:raise Http404
    if revision.grading.get("review_required"):return JsonResponse({"error":"This problem needs import review before grading."},status=409)
    responses=request.payload.get("responses",{})
    if not isinstance(responses,dict):return JsonResponse({"error":"Invalid answers"},status=400)
    membership=None if preview else Membership.objects.get(user=request.user,course=revision.activity.lesson.course)
    now=timezone.now()
    if membership:get_user_model().objects.select_for_update().get(pk=request.user.pk)
    progress=ActivityProgress.objects.filter(user=request.user,activity=revision.activity).first() if membership else None
    retry_unlocked=bool(progress and (native_practice(progress) or (progress.completed and progress.maximum>0 and progress.score>=progress.maximum)))
    if membership and retry_unlocked:
        QuestionCooldown.objects.filter(membership=membership,revision=revision).delete()
    locks=active_locks(membership,revision) if membership and not retry_unlocked else {}
    locked_questions=set(locks)
    result=assess(revision.grading,responses,locked=set(locks))
    maximum=Decimal(str(revision.grading.get("maximum_points",1)))
    score=maximum*result["fraction"]
    progress=ActivityProgress.objects.filter(user=request.user,activity=revision.activity).first() if membership else None
    practice=bool(membership and (native_practice(progress) or not credit_open(membership,revision.activity,now)))
    if membership:
        for qid, correct in result["checks"].items():
            if qid in locks: continue
            if correct:
                QuestionCooldown.objects.filter(membership=membership,revision=revision,question_id=qid).delete()
            elif not retry_unlocked:
                until=now+timezone.timedelta(seconds=RETRY_COOLDOWN_SECONDS)
                QuestionCooldown.objects.update_or_create(membership=membership,revision=revision,question_id=qid,defaults={"locked_until":until})
                locks[qid]=until
        submission=Submission.objects.create(revision=revision,membership=membership,response=responses,received_at=now)
        progress,_=ActivityProgress.objects.get_or_create(user=request.user,activity=revision.activity)
        progress.viewed=True
        state=dict(progress.question_state)
        for qid in locked_questions:
            if state.get(qid,{}).get('feedback'):result['feedback'][qid]=state[qid]['feedback']
        for qid,correct in result['checks'].items():
            if qid in locked_questions:continue
            state[qid]={'solved':bool(state.get(qid,{}).get('solved') or correct),
                'correct':correct,'response':responses.get(qid),'feedback':result['feedback'].get(qid,[]),
                'practice':bool(state.get(qid,{}).get('practice'))}
        progress.question_state=state
        if not practice:
            progress.score=max(progress.score,score);progress.maximum=maximum
            progress.completed=progress.completed or result["passed"]
        progress.save()
        if not practice:
            from .canvas_sync import enqueue_grade
            enqueue_grade(membership,revision.activity.lesson)
    if membership:
        from .tracking import event
        event(membership,revision.activity.lesson,'native_submitted',revision.activity,
            {'submission_id':submission.pk,'revision_id':revision.pk,'practice':practice,'score':display_points(score),'recorded_score':display_points(progress.score)})
    solved=[qid for qid,correct in result['checks'].items() if correct]
    if membership:
        from .hints import solved_questions
        solved=solved_questions(revision,progress)
    return JsonResponse({"reset_available":native_reset_available(revision,progress) if membership else result["passed"],
        "recorded_score":display_points(progress.score) if membership else display_points(score),
        "solved_questions":solved,"practice":practice,"checks":result["checks"],"feedback":result["feedback"],"passed":result["passed"],
        "score":display_points(score),"maximum":display_points(maximum),
        "locks":{qid: until.isoformat() for qid, until in locks.items()}})
