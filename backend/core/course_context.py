"""Explicit browser course context; URLs keep independent tabs independent."""
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Subquery
from django.utils import timezone
from .models import Membership, QuizAttempt


def current_membership(request):
    if not request.user.is_authenticated:
        raise PermissionDenied
    if getattr(request, 'api_member', None):
        return request.api_member
    query = Membership.objects.filter(user=request.user, active=True).select_related('course')
    selected = request.headers.get('X-Trellis-Course')
    if selected is not None:
        if not selected.isascii() or not selected.isdigit() or len(selected) > 18 or int(selected) < 1:
            raise PermissionDenied('Choose a valid course.')
        query = query.filter(course_id=int(selected))
    locked_course = QuizAttempt.objects.filter(
        Q(membership__role='student') | Q(membership__course_id=request.session.get('student_view_course')),
        membership__user=request.user, membership__active=True,
        submitted_at=None, expires_at__gt=timezone.now(), lesson__metadata__exam_mode=True,
        lesson__metadata__kind='programming_quiz').order_by('pk').values('membership__course_id')[:1]
    membership = query.annotate(active_exam_course=Subquery(locked_course)).order_by('pk').first()
    if membership is None:
        raise PermissionDenied('You are not enrolled in this course.')
    if membership.active_exam_course and membership.active_exam_course != membership.course_id:
        raise PermissionDenied('Finish your active quiz before switching courses.')
    return membership


def require_matching_context(request, course_id):
    # Legacy ID URLs remain supported; explicit browser context must match the target.
    if getattr(request, 'api_course', None):
        if request.api_course.pk != course_id:
            raise PermissionDenied
    elif request.headers.get('X-Trellis-Course') is not None:
        if current_membership(request).course_id != course_id:
            raise PermissionDenied('This item belongs to a different course.')
