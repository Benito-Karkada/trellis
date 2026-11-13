"""Private staff review metrics. No metric is an AI probability or an automatic grade decision."""
from collections import defaultdict
import math
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from .models import Membership, Lesson, ExecutionJob, Submission, LearningEvent, StudentReview, Course
from .course_settings import instructor_course, staff_course
from .studio import require_authoring_access, json_body
from .code_review import policy, DEFAULT_POLICY, FEATURES

WEIGHTS = {'timing': 35, 'code': 35, 'first_pass': 20, 'focus': 10}


def metrics(jobs, submissions, focus, rules):
    by_part = defaultdict(list); latest = {}; flags = []; analyzed = set(); flagged = set()
    for row in submissions:
        t = row['received_at'] or row['created_at']; key = row['revision__activity_id']
        if key not in latest or t > latest[key]: latest[key] = t
    times = sorted(latest.values()); gaps = [(b-a).total_seconds() for a,b in zip(times,times[1:]) if b>a]
    gap_index = sum(1/(1+g/rules['tau_seconds']) for g in gaps)/len(gaps) if gaps else None
    for job in jobs:
        part = job['revision__activity_id']; by_part[part].append(job)
        signals = job['review_signals'] or {}
        if signals.get('version') and signals.get('files_parsed',0)>0:
            analyzed.add(part)
            if signals.get('flags'):
                flagged.add(part)
                flags.append({'job_id':str(job['id']),'part_id':part,'submitted_at':job['created_at'],
                    'operation':job['operation'],'flags':signals['flags'],'policy_digest':signals.get('policy_digest')})
    first_pass = 0; no_run_first_pass = 0; eligible = 0; revisions = 0; failed_then_changed = 0; parts = []
    for part, attempts in by_part.items():
        attempts.sort(key=lambda r:r['created_at'])
        completed = [j for j in attempts if j['operation']=='submit' and j['status']=='completed' and not j['result__stale'] and not j['result__error']]
        first = completed[0] if completed else None
        if first:
            eligible += 1
            if first['result__passed'] is True:
                first_pass += 1
                if not any(j['operation']=='run' and j['created_at']<first['created_at'] for j in attempts):no_run_first_pass += 1
        previous = None; part_changes = 0; part_debug = 0
        for j in attempts:
            digest = (j['review_signals'] or {}).get('digest')
            if previous and digest and previous[0] and digest!=previous[0]:
                part_changes += 1
                if previous[1]:part_debug += 1
            failed = (j['status']=='completed' and not j['result__error'] and (j['result__passed'] is False or j['result__execution_status'] in {'runtime_error','missing_target','timeout'}))
            previous = (digest,failed)
        revisions += part_changes; failed_then_changed += part_debug
        parts.append({'part_id':part,'runs':sum(j['operation']=='run' for j in attempts),'submits':sum(j['operation']=='submit' for j in attempts),
            'first_submit_passed':first['result__passed'] if first else None,'code_revisions':part_changes,'revisions_after_unsuccessful_attempts':part_debug,
            'first_attempt_at':attempts[0]['created_at'],'last_attempt_at':attempts[-1]['created_at']})
    episodes = {}
    for event in focus:
        data = event['metadata']; key = data.get('episode_id')
        if not key:continue
        item = episodes.setdefault(key,{'away':False,'hidden':False,'duration_ms':None})
        item['away'] |= data.get('state')=='away'
        item['hidden'] |= data.get('reason')=='tab' or data.get('state')=='hidden'
        if data.get('state') in {'back','end'}:item['duration_ms']=min(int(data.get('elapsed_ms',0)),86400000)
    episodes = [e for e in episodes.values() if e['away']]
    components={'timing':gap_index,'code':len(flagged)/len(analyzed) if analyzed else None,
        'first_pass':no_run_first_pass/eligible if eligible>=3 else None,
        'focus':min(len(episodes)/rules['focus_reference'],1) if focus else None}
    score = float(Decimal(str(sum(WEIGHTS[k]*v for k,v in components.items() if v is not None))).quantize(Decimal('0.1'),rounding=ROUND_HALF_UP)) if any(v is not None for v in components.values()) else None
    reasons=[]
    if gap_index is not None and gap_index>=0.75:reasons.append('Short gaps between latest submissions across different exercises')
    if flagged:reasons.append(f'Code observations on {len(flagged)} analyzed exercise(s)')
    if eligible>=3 and no_run_first_pass/eligible>=0.8:reasons.append('Most first submissions passed without an earlier recorded Run')
    if len(episodes)>=5:reasons.append('Repeated recorded focus changes')
    return {'index':score,'legacy_gap_index':round(gap_index,4) if gap_index is not None else None,'gap_count':len(gaps),
        'latest_submission_at':max(times) if times else None,'submitted_parts':len(latest),'runs':sum(j['operation']=='run' for j in jobs),
        'submits':sum(j['operation']=='submit' for j in jobs),'analyzed_parts':len(analyzed),'flagged_parts':len(flagged),
        'unassessed_attempts':sum(not bool(j['review_signals']) or (j['review_signals'].get('files_parsed',0)<j['review_signals'].get('files_total',1)) for j in jobs),'first_pass_parts':first_pass,'first_pass_eligible':eligible,
        'first_pass_without_run':no_run_first_pass,'code_revisions':revisions,'revisions_after_unsuccessful_attempts':failed_then_changed,
        'focus_changes':len(episodes),'tab_hidden':sum(e['hidden'] for e in episodes),'window_only':sum(not e['hidden'] for e in episodes),
        'recorded_away_seconds':round(sum(e['duration_ms'] or 0 for e in episodes)/1000),
        'components':{k:{'value':round(v,4) if v is not None else None,'raw_value':v,'weight':WEIGHTS[k],'contribution':round(v*WEIGHTS[k],2) if v is not None else None} for k,v in components.items()},
        'reasons':reasons,'code_flags':flags[-100:],'parts':parts}


def report_data(request, course):
    require_authoring_access(request,course)
    students=Membership.objects.filter(course=course,active=True,role='student').select_related('user').order_by('user__last_name','user__first_name','pk')
    query=request.GET.get('search','').strip()[:150]
    if query:students=students.filter(Q(user__email__icontains=query)|Q(user__first_name__icontains=query)|Q(user__last_name__icontains=query))
    for key in ('membership','assignment'):
        if request.GET.get(key) and not request.GET[key].isdigit():
            from django.http import Http404
            raise Http404
    if request.GET.get('membership'):students=students.filter(pk=request.GET['membership'])
    try:page=max(0,min(int(request.GET.get('page',0)),10000))
    except ValueError:page=0
    total=students.count();members=list(students[page*50:(page+1)*50]);mids=[m.pk for m in members];uids=[m.user_id for m in members]
    lessons=Lesson.objects.filter(course=course,deleted_at=None)
    if request.GET.get('assignment'):
        lesson=get_object_or_404(lessons,pk=request.GET['assignment']);selected=[lesson.pk]
    else:selected=list(lessons.values_list('pk',flat=True))
    jobs=ExecutionJob.objects.filter(user_id__in=uids,revision__activity__lesson_id__in=selected,preview=False,revision__activity__deleted_at=None).order_by('created_at','pk')
    job_values=jobs.values('id','user_id','revision__activity_id','created_at','operation','status','review_signals','result__passed','result__execution_status','result__stale','result__error')
    submits=Submission.objects.filter(membership_id__in=mids,revision__activity__lesson_id__in=selected,revision__activity__deleted_at=None).values('membership_id','revision__activity_id','received_at','created_at')
    events=LearningEvent.objects.filter(membership_id__in=mids,assignment_id__in=selected,kind='focus_changed').values('membership_id','metadata','created_at')
    by_user=defaultdict(list);by_member=defaultdict(list);by_focus=defaultdict(list)
    for job in job_values:by_user[job['user_id']].append(job)
    for sub in submits:by_member[sub['membership_id']].append(sub)
    for event in events:by_focus[event['membership_id']].append(event)
    records={r.membership_id:r for r in StudentReview.objects.filter(membership_id__in=mids).select_related('reviewed_by')}
    rows=[];rules=policy(course)
    for m in members:
        record=records.get(m.pk)
        rows.append({'membership_id':m.pk,'name':m.user.get_full_name(),'email':m.user.email or m.user.username,
            **metrics(by_user[m.user_id],by_member[m.pk],by_focus[m.pk],rules),
            'review':{'status':record.status if record else 'unreviewed','notes':record.notes if record else '',
                'updated_at':record.updated_at if record else None,'reviewer':record.reviewed_by.get_full_name() or record.reviewed_by.username if record and record.reviewed_by else None}})
    return {'results':rows,'total':total,'page':page,'page_size':50,'policy':rules,'weights':WEIGHTS,
        'can_configure':Membership.objects.filter(course=course,user=request.user,role='instructor',active=True).exists(),
        'assignments':list(lessons.order_by('position','pk').values('id','title'))}


def report(request):
    return JsonResponse(report_data(request,staff_course(request)))


@require_POST
@json_body
@transaction.atomic
def save_review(request, pk):
    course=staff_course(request);require_authoring_access(request,course)
    target=get_object_or_404(Membership,pk=pk,course=course,role='student',active=True)
    status=request.payload.get('status');notes=request.payload.get('notes','')
    if status not in {'unreviewed','reviewed','follow_up','dismissed'} or not isinstance(notes,str) or len(notes)>4000:
        return JsonResponse({'error':'Choose a review status and notes up to 4000 characters.'},status=400)
    original=request.GET;params=original.copy();params['membership']=str(pk);params['page']='0';request.GET=params
    current=report_data(request,course)['results'][0];request.GET=original
    snapshot={k:current[k] for k in ('index','components','reasons','runs','submits','focus_changes','flagged_parts')}
    record,_=StudentReview.objects.update_or_create(membership=target,defaults={'status':status,'notes':notes,'reviewed_by':request.user,'snapshot':snapshot})
    return JsonResponse({'ok':True,'updated_at':record.updated_at})


@require_POST
@json_body
@transaction.atomic
def save_policy(request):
    course=instructor_course(request);require_authoring_access(request,course)
    if not Membership.objects.filter(user=request.user,course=course,active=True,role='instructor').exists():
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    body=request.payload
    if set(body)!=set(DEFAULT_POLICY):return JsonResponse({'error':'Send all review settings.'},status=400)
    try:
        for key,low,high in [('tau_seconds',1,3600),('focus_reference',1,1000)]:
            if type(body[key]) not in {int,float} or not math.isfinite(body[key]) or not low<=body[key]<=high:raise ValueError()
        for key in ('allowed_imports','features','calls'):
            if not isinstance(body[key],list) or len(body[key])>100 or any(not isinstance(v,str) or not v.isidentifier() or len(v)>80 for v in body[key]):raise ValueError()
        if set(body['features'])-set(FEATURES)-{'decorator'}:raise ValueError()
    except (ValueError,TypeError):return JsonResponse({'error':'Invalid review settings.'},status=400)
    course=Course.objects.select_for_update().get(pk=course.pk);course.metadata={**course.metadata,'submission_review':body};course.save(update_fields=['metadata'])
    return JsonResponse({'ok':True})


def attempt(request, job_id):
    course=staff_course(request);require_authoring_access(request,course)
    job=get_object_or_404(ExecutionJob,pk=job_id,preview=False,revision__activity__lesson__course=course)
    return JsonResponse({'id':str(job.pk),'files':job.snapshot,'entrypoint':job.entrypoint,'submitted_at':job.created_at,'operation':job.operation})
