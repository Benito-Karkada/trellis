"""Instructor-triggered Canvas REST publishing, independent of LTI launches.

A durable reservation precedes every network request. An ambiguous create is
never automatically repeated: staff link the created assignment before retrying.
"""
import html
import os
import uuid
from decimal import Decimal
from urllib.parse import urlencode, urlsplit
import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_POST
from .models import Activity, Course, Lesson, Membership
from .course_settings import instructor_course, staff_course
from .studio import activity_maximum, json_body, point_text


def public_origin(value):
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError('Enter the Trellis site URL.')
    url = urlsplit(value.strip())
    if (url.scheme not in {'https', 'http'} or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in {'', '/'}
            or (url.scheme == 'http' and url.hostname not in {'localhost', '127.0.0.1'})):
        raise ValueError('Use the HTTPS Trellis site URL, or localhost for a local preview.')
    # Accessing port also rejects malformed authorities.
    url.port
    return value.strip().rstrip('/')


def configured():
    try:
        base = public_origin(os.environ.get('CANVAS_BASE_URL', ''))
    except ValueError:
        return False
    return bool(base.startswith('https://') and os.environ.get('CANVAS_API_TOKEN'))


def origin(course):
    value = (course.metadata.get('trellis_public_url') or os.environ.get('TRELLIS_PUBLIC_URL', '')
        or (f'http://localhost:{settings.FRONTEND_PORT}' if settings.DEBUG else ''))
    return public_origin(value) if value else ''


def assignment_row(lesson, base):
    parts = getattr(lesson, 'canvas_parts', None)
    if parts is None:
        parts = list(lesson.activity_set.filter(deleted_at=None, published_revision__isnull=False)
            .select_related('published_revision').order_by('position', 'pk'))
    maximum = sum((Decimal(activity_maximum(part)) for part in parts), Decimal(0))
    params = {'course': lesson.course_id, 'lesson': lesson.pk}
    if parts:
        params.update(activity=parts[0].pk, category=parts[0].metadata.get('category', 'content'))
    link = f'{base}/#/course?{urlencode(params)}' if base else ''
    state = lesson.metadata.get('canvas_publish', {})
    return {'id': lesson.pk, 'title': lesson.title, 'points': point_text(maximum),
        'due_at': lesson.metadata.get('due_at'), 'url': link, 'part_count': len(parts),
        'visibility': lesson.visibility, 'canvas_assignment_id': str(lesson.metadata.get('canvas_assignment_id', '')),
        'status': state.get('status', 'not_published'), 'last_error': state.get('error', ''),
        'synced_at': state.get('synced_at'), 'published': state.get('published', False)}


@require_GET
def overview(request):
    course = staff_course(request)
    base = origin(course)
    lessons = course.lesson_set.filter(deleted_at=None).order_by('position', 'pk').prefetch_related(
        Prefetch('activity_set', queryset=Activity.objects.filter(deleted_at=None, published_revision__isnull=False)
            .select_related('published_revision').order_by('position', 'pk'), to_attr='canvas_parts'))
    return JsonResponse({'course_id': course.pk, 'canvas_course_id': course.canvas_context_id,
        'trellis_url': base, 'configured': configured(),
        'can_publish': Membership.objects.filter(course=course, user=request.user, role='instructor', active=True).exists(),
        'assignments': [assignment_row(lesson, base) for lesson in lessons]})


@require_POST
@json_body
@transaction.atomic
def configure(request):
    course = Course.objects.select_for_update().get(pk=instructor_course(request).pk)
    target = request.payload.get('canvas_course_id', '')
    if not isinstance(target, str) or (target and (not target.isascii() or not target.isdigit() or len(target) > 32)):
        return JsonResponse({'error': 'Enter a numeric Canvas course ID.'}, status=400)
    try:
        base = public_origin(request.payload.get('trellis_url', ''))
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    if target != course.canvas_context_id and any(
            lesson.metadata.get('canvas_assignment_id') or lesson.metadata.get('canvas_publish')
            for lesson in course.lesson_set.all()):
        return JsonResponse({'error': 'This course already has Canvas mappings. Keep its Canvas course ID to avoid sending grades to another course.'}, status=409)
    course.canvas_context_id = target
    course.metadata = {**course.metadata, 'trellis_public_url': base}
    course.save(update_fields=['canvas_context_id', 'metadata'])
    return JsonResponse({'ok': True})


def save_result(pk, reservation, **values):
    with transaction.atomic():
        lesson = Lesson.objects.select_for_update().get(pk=pk)
        state = lesson.metadata.get('canvas_publish', {})
        if state.get('reservation') != reservation:
            return
        state = {**state, **values.pop('state', {})}
        lesson.metadata = {**lesson.metadata, **values, 'canvas_publish': state}
        lesson.save(update_fields=['metadata'])


@require_POST
@json_body
def publish_assignment(request, pk):
    course = instructor_course(request)
    if type(request.payload.get('published', False)) is not bool:
        return JsonResponse({'error': 'Choose whether to publish in Canvas.'}, status=400)
    published = request.payload.get('published', False)
    # Serialize reservations against both another publish and course remapping.
    with transaction.atomic():
        course = Course.objects.select_for_update().get(pk=course.pk)
        lesson = get_object_or_404(Lesson.objects.select_for_update(), pk=pk, course=course, deleted_at=None)
        if not configured() or not course.canvas_context_id.isdigit() or not origin(course):
            return JsonResponse({'error': 'Configure the server Canvas credentials, Canvas course ID and Trellis URL first.'}, status=409)
        state = lesson.metadata.get('canvas_publish', {})
        if state.get('status') == 'publishing':
            return JsonResponse({'error': 'A publish request is already in progress. If it was interrupted, check Canvas and link its assignment ID before retrying.'}, status=409)
        assignment_id = str(lesson.metadata.get('canvas_assignment_id', ''))
        if assignment_id and not assignment_id.isdigit():
            return JsonResponse({'error': 'The mapped Canvas assignment ID is invalid.'}, status=400)
        if state.get('status') == 'uncertain' and not assignment_id:
            return JsonResponse({'error': 'The previous create may have succeeded. Check Canvas and link its assignment ID before trying again.'}, status=409)
        row = assignment_row(lesson, origin(course))
        if not row['part_count']:
            return JsonResponse({'error': 'Publish at least one part in Trellis first.'}, status=409)
        due = row['due_at']
        try:
            parsed = parse_datetime(due) if isinstance(due, str) else None
        except ValueError:
            parsed = None
        if due and (parsed is None or timezone.is_naive(parsed)):
            return JsonResponse({'error': 'Save a valid assignment due date first.'}, status=400)
        reservation = uuid.uuid4().hex
        lesson.metadata = {**lesson.metadata, 'canvas_publish': {**state, 'status': 'publishing',
            'reservation': reservation, 'error': '', 'started_at': timezone.now().isoformat()}}
        lesson.save(update_fields=['metadata'])
    description = f'<p>Complete this assignment in Trellis.</p><p><a href="{html.escape(row["url"], quote=True)}">Open {html.escape(row["title"])}</a></p>'
    payload = {'assignment': {'name': row['title'], 'points_possible': float(row['points']),
        'grading_type': 'points', 'submission_types': ['none'], 'description': description,
        'due_at': due or None, 'published': published}}
    if not assignment_id:
        payload['assignment']['integration_id'] = f'trellis-course-{course.pk}-assignment-{pk}'
    endpoint = f'{os.environ["CANVAS_BASE_URL"].rstrip("/")}/api/v1/courses/{course.canvas_context_id}/assignments'
    if assignment_id:
        endpoint += '/' + assignment_id
    try:
        response = requests.request('PUT' if assignment_id else 'POST', endpoint, json=payload,
            headers={'Authorization': 'Bearer ' + os.environ['CANVAS_API_TOKEN']},
            timeout=(5, 15), allow_redirects=False)
        if response.status_code not in {200, 201}:
            # A server error can follow a committed creation. Do not repeat it.
            uncertain = not assignment_id and response.status_code not in {400, 401, 403, 404, 405, 409, 413, 422, 429}
            error = f'Canvas returned HTTP {response.status_code}.'
            save_result(pk, reservation, state={'status': 'uncertain' if uncertain else 'failed', 'error': error})
            return JsonResponse({'error': error + (' Check Canvas before retrying.' if uncertain else '')}, status=502)
        data = response.json()
        remote_id = str(data.get('id', ''))
        if not remote_id.isdigit() or (assignment_id and remote_id != assignment_id):
            raise ValueError('Unexpected Canvas response')
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        error = 'Canvas did not confirm the request. Check Canvas and link its assignment ID before retrying.'
        save_result(pk, reservation, state={'status': 'failed' if assignment_id else 'uncertain', 'error': error})
        return JsonResponse({'error': error}, status=502)
    save_result(pk, reservation, canvas_assignment_id=remote_id, state={'status': 'synced', 'error': '',
        'synced_at': timezone.now().isoformat(), 'published': published})
    return JsonResponse({'ok': True, 'canvas_assignment_id': remote_id,
        'action': 'updated' if assignment_id else 'created', 'published': published})
