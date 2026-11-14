"""Course discovery, instructor-owned creation and course identity settings."""
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_http_methods
from .models import Course, Membership
from .studio import json_body
from .course_context import current_membership


def can_create(request):
    return not request.session.get('student_view_course') and (request.user.is_staff or
        Membership.objects.filter(user=request.user, active=True, role='instructor').exists())


def identity(course):
    return {'id': course.pk, 'title': course.title, 'term': course.term,
        'code': course.metadata.get('code') or ('CS 1301' if course.metadata.get('local_course_key') == 'cs1301' else ''),
        'description': course.metadata.get('description', ''),
        'example': course.metadata.get('local_course_key') == 'cs1301'}


def clean(body):
    limits = {'title': 200, 'code': 40, 'term': 40, 'description': 1000}
    result = {}
    for key, maximum in limits.items():
        value = body.get(key, '')
        if not isinstance(value, str) or len(value.strip()) > maximum:
            raise ValueError(f'{key.capitalize()} must be text, up to {maximum} characters.')
        result[key] = value.strip()
    if not result['title']:
        raise ValueError('Enter a course title.')
    return result


@require_http_methods(['GET', 'POST'])
def collection(request):
    if not request.user.is_authenticated:
        raise PermissionDenied
    if request.method == 'POST':
        return create(request)
    memberships = Membership.objects.filter(user=request.user, active=True).select_related('course').annotate(
        sections=Count('course__lesson', filter=Q(course__lesson__deleted_at=None), distinct=True),
        visible_sections=Count('course__lesson', filter=Q(course__lesson__deleted_at=None) & ~Q(course__lesson__visibility='staff'), distinct=True))
    # Students must never learn hidden section counts through course cards.
    rows = []
    for member in memberships.order_by('course__title', 'pk'):
        student_view = request.session.get('student_view_course') == member.course_id
        rows.append({**identity(member.course), 'role': 'student' if student_view else member.role,
            'section_count': member.visible_sections if member.role == 'student' or student_view else member.sections})
    return JsonResponse({'courses': rows, 'can_create': bool(can_create(request))})


@json_body
@transaction.atomic
def create(request):
    if not can_create(request):
        raise PermissionDenied('Only instructors can create courses.')
    try:
        values = clean(request.payload)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    course = Course.objects.create(title=values.pop('title'), term=values.pop('term'), metadata=values)
    Membership.objects.create(course=course, user=request.user, role='instructor')
    return JsonResponse(identity(course), status=201)


@require_http_methods(['GET', 'POST'])
def settings_data(request):
    from .course_settings import instructor_course
    if request.method == 'GET':
        member = current_membership(request)
        if member.role not in {'instructor', 'head_ta', 'ta'} or request.session.get('student_view_course') == member.course_id:
            raise PermissionDenied
        return JsonResponse({**identity(member.course), 'can_edit': member.role == 'instructor'})
    return save_settings(request, instructor_course(request))


@json_body
@transaction.atomic
def save_settings(request, course):
    try:
        values = clean(request.payload)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    course = Course.objects.select_for_update().get(pk=course.pk)
    course.title, course.term = values.pop('title'), values.pop('term')
    course.metadata = {**course.metadata, **values}
    course.save(update_fields=['title', 'term', 'metadata'])
    return JsonResponse(identity(course))
