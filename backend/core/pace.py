"""Server-side pace check. Raw timings never leave the server; students only learn `too_fast`."""
from datetime import timedelta
import math
from django.db import transaction
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from .models import Membership, Lesson, Activity, ActivityProgress, AssignmentVisit, LearningEvent

DEFAULT_SECONDS_PER_QUESTION = 60   # a part may override with metadata["min_seconds"] (per question)
IDLE_CAP = timedelta(minutes=10)    # gaps longer than this count as a break, not working time
MIN_QUESTIONS = 2                   # too little signal below this


def question_count(activity):
    if activity.metadata.get('sandbox') or activity.metadata.get('kind') in {'reading', 'video'}:
        return 0
    revision = activity.published_revision
    if not revision:
        return 0
    grading = revision.grading or {}
    try:
        maximum = float(grading.get('maximum_points', 1))
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(maximum) or maximum <= 0 or grading.get('review_required'):
        return 0
    questions = grading.get('questions')
    if isinstance(questions, dict) and questions:
        return len(questions)
    return 1 if grading.get('definition') else 0


def assess(membership, lesson):
    """Return (too_fast, details). details is for staff-side storage only."""
    visit = AssignmentVisit.objects.filter(membership=membership, assignment=lesson).first()
    if not visit:
        return False, {}
    done = ActivityProgress.objects.filter(user=membership.user, completed=True, activity__lesson=lesson,
        activity__deleted_at=None).select_related('activity__published_revision')
    questions = 0
    required = 0.0
    for progress in done:
        activity = progress.activity
        n = question_count(activity)
        if not n:
            continue
        try:
            raw = activity.metadata.get('min_seconds', DEFAULT_SECONDS_PER_QUESTION)
            per_question = float(raw)
            if isinstance(raw, bool) or not math.isfinite(per_question) or not 0 <= per_question <= 86400:
                raise ValueError('Invalid minimum working time')
        except (TypeError, ValueError, OverflowError):
            per_question = DEFAULT_SECONDS_PER_QUESTION
        questions += n
        required += n * per_question
    if questions < MIN_QUESTIONS:
        return False, {}
    # Working time = first open plus every logged action, with long gaps capped.
    times = [visit.first_opened_at] + list(LearningEvent.objects.filter(membership=membership,
        assignment=lesson, created_at__gte=visit.first_opened_at).exclude(kind__in=['pace_flagged','focus_changed']).order_by('created_at').values_list('created_at', flat=True))
    times.sort()
    active = sum((min(b - a, IDLE_CAP) for a, b in zip(times, times[1:])), timedelta()).total_seconds()
    return active < required, {'active_seconds': round(active), 'required_seconds': round(required), 'questions': questions}


@require_POST
@transaction.atomic
def check(request, assignment_id):
    if not request.user.is_authenticated:
        raise Http404
    lesson = get_object_or_404(Lesson, pk=assignment_id, deleted_at=None)
    membership = get_object_or_404(Membership.objects.select_for_update(), user=request.user, course=lesson.course, active=True)
    if membership.role != 'student' or lesson.visibility == 'staff' or lesson.metadata.get('kind') == 'programming_quiz':
        return JsonResponse({'too_fast': False})
    too_fast, details = assess(membership, lesson)
    if too_fast and not LearningEvent.objects.filter(membership=membership, assignment=lesson, kind='pace_flagged').exists():
        LearningEvent.objects.create(membership=membership, assignment=lesson, kind='pace_flagged', metadata=details)
    return JsonResponse({'too_fast': too_fast})
