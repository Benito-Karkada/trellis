"""Timed programming quiz lifecycle and staff configuration."""
from .course_context import require_matching_context
from datetime import timedelta
from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from .models import Accommodation, ActivityProgress, Lesson, Membership, QuizAttempt, Workspace, ExecutionJob, QuestionCooldown
from .services import require_staff
from .course_settings import staff_course, decimal_text
from .studio import json_body, require_authoring_access
from .honorlock import enabled, is_exam, access_required, unlock, config as access_config


def effective_minutes(membership, lesson):
    base = Decimal(str(lesson.metadata.get("time_limit_minutes") or 0))
    if not base:
        return None
    value = (Accommodation.objects.filter(membership=membership, lesson=lesson).first()
             or Accommodation.objects.filter(membership=membership, activity=None, lesson=None).first())
    return base * (value.time_multiplier if value else 1) + (value.extra_minutes if value else 0)


def quiz_points(user, lesson):
    earned = sum((p.score for p in ActivityProgress.objects.filter(user=user, activity__lesson=lesson)), Decimal(0))
    maximum = sum((Decimal(str(a.published_revision.grading.get("maximum_points", 1)))
        for a in lesson.activity_set.filter(deleted_at=None, published_revision__isnull=False)
        .select_related("published_revision")), Decimal(0))
    return earned, maximum


@never_cache
def quiz_data(request):
    course = staff_course(request)
    require_authoring_access(request,course)
    lessons = Lesson.objects.filter(course=course, deleted_at=None, metadata__kind="programming_quiz").select_related("access_config").order_by("position")
    return JsonResponse({"quizzes": [{"id": q.pk, "title": q.title, "visibility": q.visibility,
        "honorlock_enabled": enabled(q), "honorlock_password_set": bool(access_config(q) and access_config(q).password_hash),
        "exam_mode": bool(q.metadata.get("exam_mode")), "time_limit_minutes": q.metadata.get("time_limit_minutes"),
        "question_count": q.activity_set.filter(deleted_at=None).count()} for q in lessons]})


@require_POST
@json_body
@transaction.atomic
def save_quiz(request, pk):
    course = staff_course(request)
    require_authoring_access(request,course)
    quiz = get_object_or_404(Lesson.objects.select_for_update(), pk=pk, course=course, metadata__kind="programming_quiz", deleted_at=None)
    try:
        raw = request.payload.get("time_limit_minutes")
        minutes = int(raw) if raw not in (None, "") else None
        if minutes is not None and not 1 <= minutes <= 1440: raise ValueError
    except (TypeError, ValueError):
        return JsonResponse({"error": "Enter 1–1440 minutes, or leave the limit blank."}, status=400)
    if "visibility" in request.payload and request.payload["visibility"] not in dict(Lesson.Visibility.choices):
        return JsonResponse({"error": "Unknown visibility."}, status=400)
    if enabled(quiz) and request.payload.get('exam_mode') is not True:
        return JsonResponse({'error':'Disable Honorlock before turning off exam mode.'},status=400)
    metadata = {**quiz.metadata, "exam_mode": request.payload.get("exam_mode") is True}
    if minutes is None: metadata.pop("time_limit_minutes", None)
    else: metadata["time_limit_minutes"] = minutes
    quiz.metadata = metadata
    update_fields = ["metadata"]
    if "visibility" in request.payload:
        quiz.visibility = request.payload["visibility"]
        update_fields.append("visibility")
    quiz.save(update_fields=update_fields)
    return JsonResponse({"ok": True})


@sensitive_post_parameters("password")
@never_cache
@require_POST
@transaction.atomic
def start(request, pk):
    if not request.user.is_authenticated:raise PermissionDenied
    if request.body and request.content_type=="application/json":
        import json
        try:request.payload=json.loads(request.body)
        except (ValueError,UnicodeDecodeError):return JsonResponse({'error':'Expected a JSON object.'},status=400)
        if not isinstance(request.payload,dict):return JsonResponse({'error':'Expected a JSON object.'},status=400)
    quiz = get_object_or_404(Lesson.objects.select_for_update(), pk=pk, deleted_at=None, metadata__kind="programming_quiz")
    require_matching_context(request, quiz.course_id)
    membership = Membership.objects.filter(user=request.user, course=quiz.course, active=True).first()
    if membership is None: raise PermissionDenied
    effective_student = membership.role == "student" or request.session.get("student_view_course") == quiz.course_id
    if quiz.visibility == "staff" and effective_student: raise PermissionDenied
    if effective_student:
        Membership.objects.select_for_update().get(pk=membership.pk)
        from django.db.models import Q
        if QuizAttempt.objects.filter(membership=membership,submitted_at=None,
            lesson__metadata__kind='programming_quiz').exclude(lesson=quiz).filter(
                Q(expires_at__gt=timezone.now())|Q(expires_at=None)).exists():
            return JsonResponse({'error':'Finish your current quiz before starting another.'},status=409)
    failure=unlock(request,quiz,membership,getattr(request,'payload',{}).get('password',''))
    if failure is not None:return failure
    if not is_exam(quiz):
        return JsonResponse({"attempt_id":None,"started_at":None,"expires_at":None,"effective_minutes":None,"expired":False})
    minutes = effective_minutes(membership, quiz)
    attempt, created = QuizAttempt.objects.get_or_create(membership=membership, lesson=quiz,
        defaults={"expires_at": timezone.now() + timedelta(minutes=float(minutes)) if minutes else None})
    if created:
        from .tracking import event
        event(membership,quiz,'quiz_started',metadata={'attempt_id':attempt.pk})
    if not created and attempt.expires_at is None and minutes:
        attempt.expires_at=attempt.started_at+timedelta(minutes=float(minutes));attempt.save(update_fields=["expires_at"])
    return JsonResponse({"attempt_id": attempt.pk, "started_at": attempt.started_at.isoformat(),
        "expires_at": attempt.expires_at.isoformat() if attempt.expires_at else None,
        "effective_minutes": decimal_text(minutes) if minutes else None, "expired": bool(attempt.expires_at and attempt.expires_at <= timezone.now()),
        "submitted": bool(attempt.submitted_at), "access_required":False, "honorlock_enabled":enabled(quiz)})


@never_cache
def status(request, pk):
    if not request.user.is_authenticated:raise PermissionDenied
    quiz=get_object_or_404(Lesson,pk=pk,deleted_at=None,metadata__kind="programming_quiz")
    require_matching_context(request, quiz.course_id)
    membership=Membership.objects.filter(user=request.user,course=quiz.course,active=True).first()
    if membership is None: raise PermissionDenied
    effective_student = membership.role == "student" or request.session.get("student_view_course") == quiz.course_id
    if quiz.visibility == "staff" and effective_student: raise PermissionDenied
    attempt=QuizAttempt.objects.filter(membership=membership,lesson=quiz).first()
    earned, maximum = quiz_points(membership.user, quiz)
    return JsonResponse({"attempt_id":attempt.pk if attempt else None,
        "started_at":attempt.started_at.isoformat() if attempt else None,
        "expires_at":attempt.expires_at.isoformat() if attempt and attempt.expires_at else None,
        "expired":bool(attempt and attempt.expires_at and attempt.expires_at<=timezone.now()),
        "submitted":bool(attempt and attempt.submitted_at),
        "earned_points":decimal_text(earned), "maximum_points":decimal_text(maximum),
        "honorlock_enabled":enabled(quiz), "access_required":access_required(request,quiz,membership)})


def require_active_attempt(request, activity):
    quiz = activity.lesson
    if not is_exam(quiz):
        return
    membership = Membership.objects.get(user=request.user, course=quiz.course, active=True)
    simulated_student = request.session.get("student_view_course") == quiz.course_id
    if membership.role in {"instructor", "head_ta", "ta"} and not simulated_student: return
    from .honorlock import require_access
    require_access(request,quiz,membership)
    attempt = QuizAttempt.objects.select_for_update().filter(membership=membership, lesson=quiz).first()
    if attempt is None or attempt.submitted_at is not None or (attempt.expires_at and attempt.expires_at <= timezone.now()):
        raise PermissionDenied


@require_POST
@transaction.atomic
def finish(request, pk):
    if not request.user.is_authenticated:raise PermissionDenied
    quiz = get_object_or_404(Lesson, pk=pk, deleted_at=None, metadata__kind="programming_quiz")
    require_matching_context(request, quiz.course_id)
    membership = Membership.objects.filter(user=request.user, course=quiz.course, active=True).first()
    if membership is None: raise PermissionDenied
    attempt = get_object_or_404(QuizAttempt.objects.select_for_update(), membership=membership, lesson=quiz)
    if attempt.submitted_at is None:
        attempt.submitted_at = timezone.now(); attempt.save(update_fields=["submitted_at"])
        from .tracking import event
        event(membership,quiz,"quiz_submitted",metadata={"attempt_id":attempt.pk})
    earned, maximum = quiz_points(membership.user, quiz)
    return JsonResponse({"submitted": True, "earned_points": decimal_text(earned), "maximum_points": decimal_text(maximum)})


@require_POST
@json_body
@transaction.atomic
def reset_test_attempt(request, pk):
    """Staff may restart only their own student-view quiz, never a learner's."""
    quiz=get_object_or_404(Lesson,pk=pk,deleted_at=None,metadata__kind='programming_quiz')
    require_staff(request.user,quiz.course)
    if request.payload:
        return JsonResponse({'error':'This action resets only your own test attempt.'},status=400)
    membership=Membership.objects.select_for_update().get(user=request.user,course=quiz.course,active=True)
    jobs=ExecutionJob.objects.select_for_update().filter(user=request.user,revision__activity__lesson=quiz,
        status__in=['pending','running'])
    for job in jobs:
        job.status='failed';job.result={'error':'Your test attempt was reset. Start the quiz again.'}
        job.save(update_fields=['status','result'])
    from .studio import starter_files
    for activity in quiz.activity_set.filter(deleted_at=None,published_revision__isnull=False).select_related('published_revision'):
        workspace,_=Workspace.objects.select_for_update().get_or_create(user=request.user,revision=activity.published_revision,
            defaults={'files':{}})
        workspace.files=starter_files(activity.published_revision)
        workspace.generation+=1
        workspace.save(update_fields=['files','generation','updated_at'])
    ActivityProgress.objects.filter(user=request.user,activity__lesson=quiz).delete()
    QuestionCooldown.objects.filter(membership=membership,revision__activity__lesson=quiz).delete()
    QuizAttempt.objects.filter(membership=membership,lesson=quiz).delete()
    request.session.pop(f"quiz_unlock_{quiz.pk}",None)
    return JsonResponse({'ok':True,'message':'Your student-view quiz attempt was reset.'})


def review(request, pk):
    course = staff_course(request)
    quiz = get_object_or_404(Lesson, pk=pk, course=course, deleted_at=None,
                             metadata__kind="programming_quiz")
    students = Membership.objects.filter(course=course, role="student", active=True).select_related("user")
    questions = quiz.activity_set.filter(deleted_at=None, published_revision__isnull=False).order_by("position")
    membership_id = request.GET.get("membership")
    activity_id = request.GET.get("activity")
    data = {
        "students": [{"id": row.pk, "name": row.user.get_full_name(),
                      "email": row.user.email or row.user.username,
                      "submitted": QuizAttempt.objects.filter(membership=row, lesson=quiz,
                                                               submitted_at__isnull=False).exists(),
                      "earned_points": decimal_text(quiz_points(row.user, quiz)[0]),
                      "maximum_points": decimal_text(quiz_points(row.user, quiz)[1])}
                     for row in students],
        "questions": [{"id": activity.pk, "title": activity.title,
                       "revision": activity.published_revision_id}
                      for activity in questions],
    }
    if membership_id and activity_id:
        membership = get_object_or_404(students, pk=membership_id)
        activity = get_object_or_404(questions, pk=activity_id)
        workspace = Workspace.objects.filter(user=membership.user, revision__activity=activity).order_by("-updated_at").first()
        allowed = {file.path for file in activity.published_revision.files.filter(visibility="student")}
        files = workspace.files if workspace else {}
        data["work"] = {"files": {path: text for path, text in files.items() if path in allowed},
                        "saved_at": workspace.updated_at.isoformat() if workspace else None,
                        "score": decimal_text(ActivityProgress.objects.filter(user=membership.user,
                            activity=activity).values_list("score", flat=True).first() or Decimal(0)),
                        "maximum": decimal_text(Decimal(str(activity.published_revision.grading.get("maximum_points", 1))))}
    return JsonResponse(data)
