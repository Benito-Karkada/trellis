"""Course-scoped Ed Discussion links. No Ed credentials or posting proxy."""
import re
from urllib.parse import urlsplit
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from .models import Course
from .course_settings import instructor_course, staff_course
from .studio import json_body, require_authoring_access


def clean_url(value):
    if not isinstance(value, str) or len(value) > 300:
        raise ValueError('Enter an Ed Discussion course URL.')
    value = value.strip()
    if not value: return ''
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.netloc != 'edstem.org' or parsed.query or parsed.fragment
        or not re.fullmatch(r'/[a-z]{2}/courses/[1-9][0-9]*/discussion/?', parsed.path)):
        raise ValueError('Use an Ed course URL such as https://edstem.org/us/courses/123/discussion.')
    return value.rstrip('/')


def student_link(activity):
    if activity.lesson.metadata.get('kind') == 'programming_quiz': return None
    try: return clean_url(activity.lesson.course.metadata.get('ed_discussion_url', '')) or None
    except ValueError: return None


@require_GET
def settings_data(request):
    course = staff_course(request); require_authoring_access(request, course)
    return JsonResponse({'url': course.metadata.get('ed_discussion_url', '')})


@require_POST
@json_body
@transaction.atomic
def settings_save(request):
    course = instructor_course(request); require_authoring_access(request, course)
    if set(request.payload) != {'url'}:
        return JsonResponse({'error': 'Send the Ed Discussion course URL.'}, status=400)
    try: url = clean_url(request.payload['url'])
    except ValueError as exc: return JsonResponse({'error': str(exc)}, status=400)
    course = Course.objects.select_for_update().get(pk=course.pk)
    course.metadata = {**course.metadata, 'ed_discussion_url': url}
    course.save(update_fields=['metadata'])
    return JsonResponse({'ok': True, 'url': url})
