"""Durable, coalesced Canvas REST grade updates. Credentials stay on the app host."""
import os
from datetime import timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
import requests
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import CanvasGradeUpdate, Membership, ActivityProgress, Accommodation
from .course_settings import instructor_course, staff_course
from .studio import activity_maximum


def configured():
    return bool(os.environ.get('CANVAS_API_TOKEN') and os.environ.get('CANVAS_BASE_URL','').startswith('https://'))


def totals(membership,lesson):
    activities=list(lesson.activity_set.filter(deleted_at=None,published_revision__isnull=False).select_related('published_revision'))
    earned=sum(ActivityProgress.objects.filter(user=membership.user,activity__in=activities).values_list('score',flat=True),Decimal(0))
    maximum=sum((Decimal(activity_maximum(a)) for a in activities),Decimal(0))
    return earned,maximum


def enqueue_grade(membership,lesson,force=False):
    assignment=lesson.metadata.get('canvas_assignment_id')
    if membership.role!='student' or not assignment or not membership.canvas_user_id:return False
    if not force and not configured():return False
    score,maximum=totals(membership,lesson)
    if maximum<=0:return False
    CanvasGradeUpdate.objects.update_or_create(membership=membership,lesson=lesson,defaults={
        'assignment_id':str(assignment),'score':score,'maximum':maximum,'status':'pending',
        'attempts':0,'next_attempt_at':None,'last_error':'',
        **({'include_comment':True} if force else {})})
    return True


def summary(course):
    from django.db.models import Count
    return {'configured':configured(),'course_id':course.canvas_context_id,
        'counts':dict(CanvasGradeUpdate.objects.filter(lesson__course=course).values_list('status').annotate(n=Count('id')))}


@require_POST
@transaction.atomic
def sync_all(request):
    course=instructor_course(request)
    if not configured() or not course.canvas_context_id:
        return JsonResponse({'error':'Canvas is not connected. Configure the server credential and Canvas course ID first.'},status=409)
    lessons=list(course.lesson_set.filter(deleted_at=None,visibility='student').prefetch_related('activity_set__published_revision'))
    lessons=[l for l in lessons if any(Decimal(activity_maximum(a))>0 for a in l.activity_set.all() if not a.deleted_at)]
    students=list(Membership.objects.filter(course=course,role='student',active=True))
    missing_lessons=[l.title for l in lessons if not l.metadata.get('canvas_assignment_id')]
    missing_students=[m.pk for m in students if not m.canvas_user_id]
    if missing_lessons or missing_students:
        return JsonResponse({'error':f'Finish Canvas mappings first: {len(missing_lessons)} assignments and {len(missing_students)} students are unmapped.'},status=409)
    count=sum(enqueue_grade(m,l,force=True) for m in students for l in lessons)
    return JsonResponse({'queued':count,**summary(course)})


def process_one():
    if not configured():return False
    # Holding this row lock through delivery prevents an older score overtaking a
    # newer queued update. Other learners' submissions remain independent.
    with transaction.atomic():
        job=(CanvasGradeUpdate.objects.select_for_update(skip_locked=True)
            .filter(status__in=['pending','retrying'])
            .filter(Q(next_attempt_at=None)|Q(next_attempt_at__lte=timezone.now()))
            .select_related('membership__course','lesson').order_by('updated_at').first())
        if not job:return False
        member=job.membership;course=member.course
        if not member.active or member.role!='student' or job.lesson.deleted_at or not member.canvas_user_id:
            job.status='failed';job.last_error='Enrollment or assignment is no longer active.';job.save();return True
        job.attempts+=1
        try:
            host=os.environ['CANVAS_BASE_URL'].rstrip('/')
            if not course.canvas_context_id.isdigit() or not job.assignment_id.isdigit() or not member.canvas_user_id.isdigit():raise ValueError('Invalid Canvas mapping')
            payload={'submission[posted_grade]':str(job.score/job.maximum*100)+'%'}
            if job.include_comment:payload['comment[text_comment]']=grade_comment(job)
            response=requests.put(f'{host}/api/v1/courses/{course.canvas_context_id}/assignments/{job.assignment_id}/submissions/{member.canvas_user_id}',
                headers={'Authorization':'Bearer '+os.environ['CANVAS_API_TOKEN']},
                data=payload,timeout=20,allow_redirects=False)
            if response.status_code not in {200,201}:
                # Never save response bodies or credentials in errors.
                raise RuntimeError(f'Canvas returned HTTP {response.status_code}')
            job.status='sent';job.last_error='';job.next_attempt_at=None;job.include_comment=False
        except (requests.RequestException,RuntimeError,ValueError) as exc:
            job.status='failed' if job.attempts>=10 else 'retrying'
            job.last_error='Canvas network request failed.' if isinstance(exc,requests.RequestException) else str(exc)[:200]
            job.next_attempt_at=timezone.now()+timedelta(seconds=min(15*2**min(job.attempts,8),3600))
        job.save()
        return True



def grade_comment(job, now=None):
    """Student-visible summary for an explicit staff gradebook sync only."""
    from .course_settings import decimal_text
    from .deadlines import effective_due_at
    now=now or timezone.now()
    local=now.astimezone(ZoneInfo('America/New_York'))
    stamp=local.strftime('%B %d, %Y at %I:%M %p %Z')
    message=f'Grades updated from Trellis on {stamp}.\nRecorded score: {decimal_text(job.score)} / {decimal_text(job.maximum)} points.'
    if job.score>=job.maximum:
        return message+'\nWell done! You have earned full credit for this assignment.'
    parts=list(job.lesson.activity_set.filter(deleted_at=None,published_revision__isnull=False).select_related('published_revision','lesson'))
    scores=dict(ActivityProgress.objects.filter(user=job.membership.user,activity__in=parts).values_list('activity_id','score'))
    remaining=[p for p in parts if Decimal(activity_maximum(p))>0 and scores.get(p.pk,Decimal(0))<Decimal(activity_maximum(p))]
    overrides=list(Accommodation.objects.filter(membership=job.membership,due_at_override__isnull=False).order_by('pk'))
    dates={effective_due_at(job.membership,p,accommodations=overrides) for p in remaining}
    # If the queue's frozen score differs from current progress, use all graded
    # deadlines rather than inventing a completion state for that earlier score.
    if not remaining:
        dates={effective_due_at(job.membership,p,accommodations=overrides) for p in parts if Decimal(activity_maximum(p))>0}
    known=sorted(d for d in dates if d is not None)
    if not known:return message+'\nNo due date is currently set for this assignment.'
    future=[d for d in known if d>now]
    if not future:
        suffix='The due date has passed. Work after the deadline does not change your recorded score.'
        if None in dates:suffix='Some exercise deadlines have passed. Check Trellis for the deadlines on your remaining exercises.'
        return message+'\n'+suffix
    due=future[0];seconds=(due-now).total_seconds();days=int(seconds//86400)
    if days:
        hours=int(seconds%86400//3600)
        left=f'{days} day'+('s' if days!=1 else '')+(f' and {hours} hour'+('s' if hours!=1 else '') if hours else '')
    elif seconds>=3600:
        hours=int(seconds//3600);left=f'{hours} hour'+('s' if hours!=1 else '')
    else:left='less than 1 hour'
    label='your due date' if len(dates)==1 else 'your next remaining exercise deadline'
    when=due.astimezone(ZoneInfo('America/New_York')).strftime('%B %d, %Y at %I:%M %p %Z')
    message+=f'\nYou have {left} left until {label}: {when}.'
    if len(dates)>1:message+=' Check Trellis for the deadlines on each remaining exercise.'
    return message
