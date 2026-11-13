"""Batched course gradebook and lazy staff-only learner workspace review."""
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .course_settings import decimal_text,staff_course
from .models import Activity,ActivityProgress,Membership,QuizAttempt,Submission,Workspace,ExecutionJob,LearningEvent
from django.core.exceptions import PermissionDenied
from .studio import activity_maximum
from .canvas_sync import summary


def review_course(request):
    course=staff_course(request)
    if request.session.get('student_view_course')==course.pk:raise PermissionDenied
    return course


def gradebook(request):
    course=review_course(request)
    lessons=list(course.lesson_set.filter(deleted_at=None,visibility='student').order_by('position'))
    students=list(Membership.objects.filter(course=course,role='student',active=True).select_related('user').order_by('user__last_name','user__first_name','user__email'))
    activities=list(Activity.objects.filter(lesson__in=lessons,deleted_at=None,published_revision__isnull=False).select_related('published_revision'))
    maximum={l.pk:Decimal(0) for l in lessons};parts={l.pk:0 for l in lessons}
    for a in activities:maximum[a.lesson_id]+=Decimal(activity_maximum(a));parts[a.lesson_id]+=1
    by_user={}
    for p in ActivityProgress.objects.filter(user_id__in=[m.user_id for m in students],activity__in=activities).select_related('activity'):
        value=by_user.setdefault((p.user_id,p.activity.lesson_id),{'earned':Decimal(0),'completed':0})
        value['earned']+=p.score;value['completed']+=int(p.completed)
    submitted=set(QuizAttempt.objects.filter(membership__in=students,lesson__in=lessons,submitted_at__isnull=False).values_list('membership_id','lesson_id'))
    return JsonResponse({'course':course.title,'canvas':summary(course),'lessons':[{'id':l.pk,'title':l.title,'kind':l.metadata.get('kind','lesson'),
        'maximum':decimal_text(maximum[l.pk]),'parts':parts[l.pk],'due_at':l.metadata.get('due_at')} for l in lessons],
        'students':[{'id':m.pk,'name':m.user.get_full_name(),'email':m.user.email or m.user.username,
            'assignments':{str(l.pk):{'earned':decimal_text(by_user.get((m.user_id,l.pk),{}).get('earned',Decimal(0))),
                'maximum':decimal_text(maximum[l.pk]),'completed_parts':by_user.get((m.user_id,l.pk),{}).get('completed',0),
                'submitted':(m.pk,l.pk) in submitted} for l in lessons}} for m in students]})


def activity_work(membership,activity):
    workspace=Workspace.objects.filter(user=membership.user,revision__activity=activity).order_by('-updated_at').first()
    allowed=set(activity.published_revision.files.filter(visibility='student').values_list('path',flat=True))
    submission=Submission.objects.filter(membership=membership,revision__activity=activity,is_preview=False).order_by('-created_at','-pk').first()
    return {'files':{p:t for p,t in (workspace.files if workspace else {}).items() if p in allowed},
        'saved_at':workspace.updated_at.isoformat() if workspace else None,
        'latest_response':submission.response if submission else None,
        'submitted_at':submission.created_at.isoformat() if submission else None}


def detail(request):
    course=review_course(request)
    membership=get_object_or_404(Membership.objects.select_related('user'),pk=request.GET.get('membership'),course=course,role='student',active=True)
    lesson_id=request.GET.get('lesson')
    lesson=get_object_or_404(course.lesson_set,pk=lesson_id,deleted_at=None) if lesson_id else None
    activities=Activity.objects.filter(lesson__course=course,lesson__deleted_at=None,deleted_at=None,published_revision__isnull=False).select_related('published_revision','lesson').order_by('lesson__position','position')
    if lesson:activities=activities.filter(lesson=lesson)
    activities=list(activities)
    progress={p.activity_id:p for p in ActivityProgress.objects.filter(user=membership.user,activity__in=activities)}
    rows=[]
    for a in activities:
        p=progress.get(a.pk)
        row={'id':a.pk,'title':a.title,'kind':a.metadata.get('kind'),'revision':a.published_revision_id,
            'lesson_id':a.lesson_id,'lesson_title':a.lesson.title,'earned':decimal_text(p.score if p else Decimal(0)),
            'maximum':activity_maximum(a),'completed':bool(p and p.completed),'files':{},'saved_at':None,'latest_response':None,'submitted_at':None}
        # Preserve the original lesson API; course review loads files only on demand.
        if lesson and request.GET.get("summary")!="1":row.update(activity_work(membership,a))
        rows.append(row)
    attempt=QuizAttempt.objects.filter(membership=membership,lesson=lesson).first() if lesson else None
    return JsonResponse({'student':{'id':membership.pk,'name':membership.user.get_full_name(),'email':membership.user.email or membership.user.username},
        'lesson':{'id':lesson.pk if lesson else None,'title':lesson.title if lesson else 'Entire course','kind':lesson.metadata.get('kind') if lesson else 'course'},
        'attempt':{'started_at':attempt.started_at.isoformat() if attempt else None,'submitted_at':attempt.submitted_at.isoformat() if attempt and attempt.submitted_at else None},'activities':rows})


def work(request):
    course=review_course(request)
    member=get_object_or_404(Membership,pk=request.GET.get('membership'),course=course,role='student',active=True)
    activity=get_object_or_404(Activity.objects.select_related('published_revision'),pk=request.GET.get('activity'),lesson__course=course,lesson__deleted_at=None,deleted_at=None,published_revision__isnull=False)
    data=activity_work(member,activity)
    data['history']=submission_history(member,activity)
    selected=request.GET.get('attempt')
    if selected:
        data.update(historical_work(member,activity,selected))
    return JsonResponse(data)


def submission_history(member, activity):
    """Lightweight metadata only; fetch one immutable snapshot on selection.

    Include failed/pending Submit jobs too, which have no Submission row.
    Preview jobs and Run jobs are deliberately excluded.
    """
    jobs=ExecutionJob.objects.filter(user=member.user,revision__activity=activity,preview=False,operation='submit')
    rows=[{'id':'job:'+str(j['id']),'revision':j['revision_id'],'submitted_at':j['created_at'],
        'status':j['status'],'score':j['result__score'],'maximum':j['result__maximum'],
        'passed':j['result__passed'],'practice':bool(j['result__practice'])}
        for j in jobs.values('id','revision_id','created_at','status','result__score','result__maximum','result__passed','result__practice')]
    native=Submission.objects.filter(membership=member,revision__activity=activity,is_preview=False).exclude(response__has_key='job')
    rows.extend({'id':'submission:'+str(s.pk),'revision':s.revision_id,
        'submitted_at':s.received_at or s.created_at,'status':'completed'} for s in native.only('pk','revision_id','received_at','created_at'))
    rows.sort(key=lambda r:(r['submitted_at'],r['id']))
    for number,row in enumerate(rows,1):row['number']=number
    return rows


def historical_work(member, activity, selected):
    from django.http import Http404
    from django.core.exceptions import ValidationError
    kind,_,identifier=selected.partition(':')
    if kind=='job':
        try:
            job=get_object_or_404(ExecutionJob.objects.select_related('revision'),pk=identifier,user=member.user,
                revision__activity=activity,preview=False,operation='submit')
        except (ValidationError,ValueError):raise Http404
        allowed=set(job.revision.files.filter(visibility='student').values_list('path',flat=True))
        return {'selected_attempt':selected,'revision':job.revision_id,
            'files':{p:t for p,t in job.snapshot.items() if p in allowed},
            'saved_at':None,'latest_response':None,'submitted_at':job.created_at,
            'attempt_result':job.result,'attempt_status':job.status,'entrypoint':job.entrypoint,
            'snapshot_available':True}
    if kind=='submission' and identifier.isdigit():
        sub=get_object_or_404(Submission,pk=identifier,membership=member,revision__activity=activity,is_preview=False)
        # Coding snapshots are served only through the validated job route.
        if 'job' in sub.response:raise Http404
        event=LearningEvent.objects.filter(membership=member,part=activity,kind='native_submitted',
            metadata__submission_id=sub.pk).order_by('-created_at').first()
        return {'selected_attempt':selected,'revision':sub.revision_id,'files':{},'saved_at':None,
            'latest_response':sub.response,'submitted_at':sub.received_at or sub.created_at,
            'attempt_result':event.metadata if event else {},'attempt_status':'completed','snapshot_available':True}
    raise Http404
