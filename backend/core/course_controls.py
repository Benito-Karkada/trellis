"""Staff-only assignment deadlines and shared grading feedback."""
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST
from .models import Membership
from .course_settings import instructor_course, staff_course
from .studio import json_body,require_authoring_access

DEFAULT_FEEDBACK={'success_title':'Well done!','success_body':'Your submission earned full credit. Your score has been updated.',
    'failure_title':'Not quite yet','failure_body':'Open full_results.txt to compare your answer with the expected results.'}


def data(request):
    course=staff_course(request);require_authoring_access(request,course)
    return JsonResponse({'assignments':[{'id':l.pk,'title':l.title,'due_at':l.metadata.get('due_at'),
        'canvas_assignment_id':l.metadata.get('canvas_assignment_id','')} for l in course.lesson_set.filter(deleted_at=None).order_by('position')],
        'feedback':{**DEFAULT_FEEDBACK,**course.metadata.get('grading_feedback',{})},})


@require_POST
@json_body
@transaction.atomic
def save(request):
    course=instructor_course(request);require_authoring_access(request,course)
    if sum(k in request.payload for k in ('assignment_id','feedback','canvas_course_id','student_id'))!=1:
        return JsonResponse({'error':'Save one settings section at a time.'},status=400)
    if 'assignment_id' in request.payload:
        lesson=get_object_or_404(course.lesson_set.select_for_update(),pk=request.payload['assignment_id'],deleted_at=None)
        raw=request.payload.get('due_at')
        due=parse_datetime(raw) if isinstance(raw,str) and raw else None
        if raw and (due is None or timezone.is_naive(due)):
            return JsonResponse({'error':'Enter a valid date and time with a time zone.'},status=400)
        canvas_id=str(request.payload.get('canvas_assignment_id',lesson.metadata.get('canvas_assignment_id',''))).strip()
        if canvas_id and not canvas_id.isdigit():return JsonResponse({'error':'Canvas assignment ID must be numeric.'},status=400)
        lesson.metadata={**lesson.metadata,'due_at':due.isoformat() if due else None,'canvas_assignment_id':canvas_id};lesson.save(update_fields=['metadata'])
    if 'feedback' in request.payload:
        feedback=request.payload['feedback']
        if not isinstance(feedback,dict) or set(feedback)!=set(DEFAULT_FEEDBACK) or any(not isinstance(v,str) or not v.strip() or len(v)>2000 for v in feedback.values()):
            return JsonResponse({'error':'Enter all four feedback messages, up to 2000 characters each.'},status=400)
        course.metadata={**course.metadata,'grading_feedback':feedback}
    if 'canvas_course_id' in request.payload:
        value=str(request.payload['canvas_course_id']).strip()
        if value and not value.isdigit():return JsonResponse({'error':'Canvas course ID must be numeric.'},status=400)
        course.canvas_context_id=value
    if 'student_id' in request.payload:
        member=get_object_or_404(Membership,pk=request.payload['student_id'],course=course,role='student',active=True)
        value=str(request.payload.get('canvas_user_id','')).strip()
        if value and not value.isdigit():return JsonResponse({'error':'Canvas user ID must be numeric.'},status=400)
        if value and Membership.objects.filter(course=course,canvas_user_id=value).exclude(pk=member.pk).exists():
            return JsonResponse({'error':'That Canvas user is already mapped to another student.'},status=400)
        member.canvas_user_id=value;member.save(update_fields=['canvas_user_id'])
    course.save(update_fields=['metadata','canvas_context_id'])
    return JsonResponse({'ok':True})
