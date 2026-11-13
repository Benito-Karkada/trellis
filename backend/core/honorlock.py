"""Honorlock Universal password handoff; not a proctoring attestation API."""
import secrets
from datetime import timedelta
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_POST
from .models import Lesson, Membership, QuizAccessConfig, QuizUnlockFailure
from .studio import json_body, require_authoring_access
from .course_settings import instructor_course, staff_course


def config(lesson):
    try: return lesson.access_config
    except QuizAccessConfig.DoesNotExist: return None


def enabled(lesson):
    value=config(lesson)
    return bool(value and value.enabled)


def is_exam(lesson):
    return lesson.metadata.get('kind')=='programming_quiz' and (lesson.metadata.get('exam_mode') or enabled(lesson))


def effective_student(request, membership):
    return membership.role=='student' or request.session.get('student_view_course')==membership.course_id


def access_required(request, lesson, membership):
    value=config(lesson)
    return bool(value and value.enabled and effective_student(request,membership)
        and request.session.get(f'quiz_unlock_{lesson.pk}') != value.version)


def require_access(request, lesson, membership):
    if access_required(request,lesson,membership): raise PermissionDenied('Unlock this quiz through Honorlock first.')


@sensitive_variables('password', 'body')
@sensitive_post_parameters('password')
@require_POST
@json_body
@transaction.atomic
def save_settings(request, pk):
    course=instructor_course(request);require_authoring_access(request,course)
    lesson=get_object_or_404(Lesson.objects.select_for_update(),pk=pk,course=course,
        deleted_at=None,metadata__kind='programming_quiz')
    body=request.payload
    if set(body)-{'enabled','password'} or type(body.get('enabled')) is not bool:
        return JsonResponse({'error':'Send enabled and an optional new quiz password.'},status=400)
    password=body.get('password','')
    if not isinstance(password,str) or (password and (not 16<=len(password)<=128 or any(not 33<=ord(c)<=126 or c in "\"'" for c in password))):
        return JsonResponse({'error':'Use 16–128 printable characters without spaces or quotation marks.'},status=400)
    value=config(lesson)
    if body['enabled'] and not (password or value and value.password_hash):
        return JsonResponse({'error':'Set a unique quiz password before enabling Honorlock.'},status=400)
    if body['enabled'] and not lesson.metadata.get('exam_mode'):
        return JsonResponse({'error':'Enable exam mode before enabling Honorlock.'},status=400)
    if value is None:value=QuizAccessConfig(lesson=lesson,version=secrets.token_hex(24))
    changed=value.enabled!=body['enabled'] or bool(password)
    if password:value.password_hash=make_password(password)
    value.enabled=body['enabled']
    if changed:value.version=secrets.token_hex(24)
    value.save()
    result=JsonResponse({'ok':True,'enabled':value.enabled,'password_set':bool(value.password_hash)})
    result['Cache-Control']='no-store';return result


@sensitive_variables('password')
def unlock(request, lesson, membership, password):
    """Called under start()'s transaction. A successful unlock never resets the timer."""
    if not access_required(request,lesson,membership):return None
    # Serialize counters per account across tabs, processes and replicas.
    Membership.objects.select_for_update().get(pk=membership.pk)
    state,_=QuizUnlockFailure.objects.select_for_update().get_or_create(membership=membership,lesson=lesson)
    now=timezone.now()
    if state.locked_until and state.locked_until>now:
        result=JsonResponse({'error':'Too many unlock attempts. Please wait 15 minutes before trying again.'},status=429)
        result['Retry-After']=str(max(1,int((state.locked_until-now).total_seconds())));return result
    if now-state.window_started_at>timedelta(minutes=15):state.failures=0;state.window_started_at=now
    value=config(lesson)
    if not isinstance(password,str) or len(password)>128 or not check_password(password,value.password_hash):
        state.failures+=1
        if state.failures>=10:state.locked_until=now+timedelta(minutes=15)
        state.save()
        return JsonResponse({'error':'Quiz not unlocked. Launch this assessment through Honorlock and use Unlock assessment.'},status=403)
    state.failures=0;state.locked_until=None;state.window_started_at=now;state.save()
    request.session[f'quiz_unlock_{lesson.pk}']=value.version
    from .tracking import event
    event(membership,lesson,'quiz_unlocked',metadata={'provider':'honorlock_universal'})
    return None
