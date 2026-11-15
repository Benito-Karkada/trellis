"""Dated course assignments and a private, non-grading checklist."""
from collections import defaultdict
from decimal import Decimal
from datetime import timezone as datetime_timezone
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from .course_context import current_membership
from .deadlines import effective_due_at
from .models import Accommodation, Activity, ActivityProgress, AssignmentChecklist, Lesson, QuizAttempt
from .studio import activity_maximum, json_body, point_text


def context(request):
    member = current_membership(request)
    preview = request.session.get('student_view_course') == member.course_id
    student = member.role == 'student' or preview
    lessons = Lesson.objects.filter(course=member.course, deleted_at=None)
    if student:
        lessons = lessons.exclude(visibility='staff')
    return member, preview, lessons


@require_GET
def assignments(request):
    member, preview, lessons = context(request)
    by_lesson = defaultdict(list)
    parts = list(Activity.objects.filter(lesson__in=lessons, deleted_at=None, published_revision__isnull=False)
        .select_related('lesson', 'published_revision').only('id', 'lesson_id', 'position', 'metadata',
            'published_revision_id', 'published_revision__id', 'published_revision__grading',
            'lesson__id', 'lesson__metadata', 'lesson__course_id').order_by('position', 'pk'))
    for part in parts:
        by_lesson[part.lesson_id].append(part)
    scores = dict(ActivityProgress.objects.filter(user=request.user, activity__in=parts).values_list('activity_id', 'score'))
    accommodations = list(Accommodation.objects.filter(membership=member, due_at_override__isnull=False).order_by('pk'))
    checks = dict(AssignmentChecklist.objects.filter(membership=member, student_view=preview)
        .values_list('assignment_id', 'checked'))
    now, rows = timezone.now(), []
    closed = set(QuizAttempt.objects.filter(membership=member).filter(
        Q(submitted_at__isnull=False) | Q(expires_at__lte=now)).values_list('lesson_id', flat=True))
    for lesson in lessons:
        published = by_lesson[lesson.pk]
        graded = [(part, Decimal(activity_maximum(part))) for part in published if Decimal(activity_maximum(part)) > 0]
        if not graded:
            continue
        maximum = sum((points for _, points in graded), Decimal(0))
        earned = sum((scores.get(part.pk, Decimal(0)) for part, _ in graded), Decimal(0))
        full_credit = all(scores.get(part.pk, Decimal(0)) >= points for part, points in graded)
        outstanding = [(part, points) for part, points in graded if scores.get(part.pk, Decimal(0)) < points]
        dates = []
        for part, _ in outstanding or graded:
            try:
                due = effective_due_at(member, part, accommodations=accommodations)
            except (ValueError, TypeError):
                continue
            if due:
                dates.append(due)
        if not dates:
            continue
        due = min(dates)
        closed_quiz = lesson.metadata.get('kind') == 'programming_quiz' and lesson.pk in closed
        # Completed past assignments belong in the gradebook, not the upcoming list.
        # Manually checking an overdue reminder keeps it available to uncheck.
        if due < now and (full_credit or closed_quiz):
            continue
        first = published[0]
        rows.append({'id': lesson.pk, 'title': lesson.title, 'due_at': due.astimezone(datetime_timezone.utc).isoformat(),
            'earned_points': point_text(earned), 'maximum_points': point_text(maximum),
            'done': checks.get(lesson.pk, full_credit or closed_quiz), 'full_credit': full_credit,
            'activity_id': None if lesson.metadata.get('kind') == 'programming_quiz' else first.pk,
            'category': first.metadata.get('category', 'content'),
            'multiple_deadlines': len(set(dates)) > 1})
    rows.sort(key=lambda row: (row['due_at'], row['id']))
    return JsonResponse({'course_id': member.course_id, 'items': rows, 'server_time': now.isoformat()})


@require_POST
@json_body
@transaction.atomic
def check(request, pk):
    member, preview, lessons = context(request)
    assignment = get_object_or_404(lessons, pk=pk)
    checked = request.payload.get('checked')
    if type(checked) is not bool:
        return JsonResponse({'error': 'Choose whether this assignment is checked.'}, status=400)
    entry, _ = AssignmentChecklist.objects.update_or_create(membership=member, assignment=assignment,
        student_view=preview, defaults={'checked': checked})
    return JsonResponse({'id': assignment.pk, 'done': entry.checked})
