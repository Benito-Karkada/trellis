"""Student focus telemetry: visibility/focus only, never destinations or browser history."""
from datetime import timedelta
from uuid import UUID
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import AssignmentVisit, LearningEvent, Lesson, Membership, Activity
from .studio import json_body, member


@require_POST
@json_body
@transaction.atomic
def changed(request, assignment_id):
    if not request.user.is_authenticated:
        raise Http404
    lesson = get_object_or_404(Lesson, pk=assignment_id, deleted_at=None, visibility='student')
    enrollment = get_object_or_404(Membership.objects.select_for_update(), course=lesson.course, user=request.user, active=True)
    if enrollment.role != 'student':
        return JsonResponse({'recorded': False})
    data = request.payload
    try:
        identifiers = {key: str(UUID(data[key])) for key in ('event_id', 'episode_id', 'tab_id')}
    except (KeyError, ValueError, TypeError, AttributeError):
        return JsonResponse({'error': 'Invalid focus event.'}, status=400)
    if data.get('state') not in {'away', 'hidden', 'back', 'end'} or data.get('reason') not in {'tab', 'window'}:
        return JsonResponse({'error': 'Invalid focus state.'}, status=400)
    elapsed = data.get('elapsed_ms', 0)
    if type(elapsed) is not int or not 0 <= elapsed <= 86400000:
        return JsonResponse({'error': 'Invalid focus duration.'}, status=400)
    # No caller-provided URLs, window titles, text or arbitrary metadata is stored.
    activity = None
    if data.get('part_id') is not None and (type(data['part_id']) is not int or data['part_id']<1):
        return JsonResponse({'error':'Invalid part.'},status=400)
    if data.get('part_id'):
        activity = get_object_or_404(Activity, pk=data['part_id'], lesson=lesson, deleted_at=None)
        member(request, activity)
    if not AssignmentVisit.objects.filter(membership=enrollment, assignment=lesson).exists():
        return JsonResponse({'recorded': False})
    query = LearningEvent.objects.filter(membership=enrollment, kind='focus_changed')
    if query.filter(metadata__event_id=identifiers['event_id']).exists():
        return JsonResponse({'recorded': False})
    if query.filter(created_at__gte=timezone.now()-timedelta(minutes=1)).count() >= 120:
        return JsonResponse({'recorded': False}, status=429)
    LearningEvent.objects.create(membership=enrollment, assignment=lesson, part=activity, kind='focus_changed',
        metadata={**identifiers, 'state': data['state'], 'reason': data['reason'], 'elapsed_ms': elapsed})
    return JsonResponse({'recorded': True})
