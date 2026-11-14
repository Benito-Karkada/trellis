"""Synthetic test course setup and read-only queue snapshots (trusted Django context)."""
import copy
import hashlib
import json
import secrets
from datetime import timedelta


def create_fixture(run_id, users=10, source_course_id=1):
    import re
    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile
    from django.db import transaction
    from core.models import Course, Membership, Lesson, Activity, Revision, ActivityFile
    if not re.fullmatch(r'[a-z0-9-]{6,50}', run_id) or not 1 <= users <= 20:
        raise ValueError('Use a unique run ID and 1–20 test users.')
    if Course.objects.filter(term='loadtest-'+run_id).exists():
        raise ValueError('This run already exists; use its saved manifest or choose a new ID.')
    with transaction.atomic():
        course = Course.objects.create(title='Trellis load test '+run_id, term='loadtest-'+run_id,
            metadata={'load_test':True,'run_id':run_id})
        accounts = []
        for index in range(users+1):
            email=f'loadtest-{run_id}-{index:02d}@example.invalid'
            password=secrets.token_urlsafe(24)
            user=get_user_model().objects.create_user(username=email,email=email,password=password)
            Membership.objects.create(course=course,user=user,role='student' if index else 'instructor',source='loadtest')
            accounts.append({'email':email,'password':password})
        author=get_user_model().objects.get(email=accounts[0]['email'])
        # Reproduce current course outline/content payload sizes without copying
        # any enrollments, submissions, files, Canvas mappings, or quiz content.
        copied_sections, copied_parts = copy_outline(course, source_course_id, author)
        lesson=Lesson.objects.create(course=course,title='Synthetic student workflow',position=0)
        def add(kind,title,content,grading):
            part=Activity.objects.create(lesson=lesson,title=title,metadata={'kind':kind,'category':'problem_set' if kind!='reading' else 'content'})
            rev=Revision.objects.create(activity=part,number=1,created_by=author,content={'version':1,'blocks':content},grading=grading)
            part.published_revision=rev;part.save(update_fields=['published_revision'])
            return {'activity':part.pk,'revision':rev.pk},rev
        reading,_=add('reading','Reading: addition in Python',[{'id':'read','type':'paragraph','content':[{'type':'text','text':'Use + to add two integers. Run your code, inspect the output, and submit your answer.'}]}],{})
        native,_=add('question','Question: what does 2 + 3 produce?',[{'id':'q1','type':'multiple_choice','prompt':[{'type':'text','text':'What does print(2 + 3) display?'}],
            'choices':[{'id':'a','content':[{'type':'text','text':'5'}]},{'id':'b','content':[{'type':'text','text':'23'}]}]}],
            {'maximum_points':'1','questions':{'q1':{'selection':'one','correct_choice_ids':['a']}}})
        coding,revision=add('coding','Coding: add two integers',[{'id':'code','type':'coding','prompt':[{'type':'text','text':'Print the sum of a and b. Keep the two variable assignments at the start of main.py.'}]}],
            {'entrypoint':'main.py','maximum_points':'3','definition':{'version':1,'scoring':'all_or_nothing','cases':[
                {'id':'initial','label':'Initial values','action':'stdout','expected':'5\n','variables':{'a':2,'b':3},'public':True},
                {'id':'negative','label':'Negative value','action':'stdout','expected':'3\n','variables':{'a':-4,'b':7},'public':True},
                {'id':'zero','label':'Zero','action':'stdout','expected':'0\n','variables':{'a':0,'b':0},'public':True}]}})
        for path,text in [('main.py','a = 2\nb = 3\n\n'),('full_results.txt','')]:
            ActivityFile.objects.create(revision=revision,path=path,visibility='student',sha256=hashlib.sha256(text.encode()).hexdigest(),blob=ContentFile(text.encode(),name=path))
        return {'version':1,'run_id':run_id,'course_id':course.pk,'lesson_id':lesson.pk,
            'source_course_id':source_course_id,'copied_sections':copied_sections,'copied_parts':copied_parts,
            'accounts':accounts[1:],'staff':accounts[0],'reading':reading,'native':native,'coding':coding,
            'wrong_source':'a = 2\nb = 3\nprint(a - b)\n','correct_source':'a = 2\nb = 3\nprint(a + b)\n'}


def queue_snapshot(course_id):
    from django.utils import timezone
    from django.db.models import Count
    from core.models import Course, ExecutionJob, ActivityProgress, LearningEvent, Membership, CanvasGradeUpdate
    course=Course.objects.get(pk=course_id)
    if not course.metadata.get('load_test'):raise ValueError('Only synthetic test courses are supported.')
    jobs=ExecutionJob.objects.filter(revision__activity__lesson__course=course)
    active=ExecutionJob.objects.filter(status__in=['pending','running'])
    pending=active.filter(status='pending').order_by('created_at').first()
    now=timezone.now()
    completed=list(jobs.filter(completed_at__isnull=False).values('created_at','claimed_at','completed_at'))
    def timing(field):
        values=sorted((r[field[1]]-r[field[0]]).total_seconds() for r in completed if r[field[0]] and r[field[1]])
        return {'count':len(values),'p50_seconds':round(values[(len(values)-1)//2],3) if values else None,
            'p95_seconds':round(values[min(len(values)-1,int(len(values)*.95))],3) if values else None,'max_seconds':round(max(values),3) if values else None}
    counts=lambda q:dict(q.values('status').annotate(n=Count('pk')).values_list('status','n'))
    return {'at':now.isoformat(),'course_id':course.pk,'jobs':counts(jobs),'global_active_jobs':counts(active),
        'global_oldest_pending_seconds':round((now-pending.created_at).total_seconds(),1) if pending else 0,
        'queue_wait':timing(('created_at','claimed_at')),'grading':timing(('claimed_at','completed_at')),
        'end_to_end':timing(('created_at','completed_at')),'students':Membership.objects.filter(course=course,role='student',active=True).count(),
        'progress_records':ActivityProgress.objects.filter(activity__lesson__course=course).count(),
        'events':LearningEvent.objects.filter(membership__course=course).count(),
        'review_observations':jobs.exclude(review_signals={}).count(),
        'canvas_updates':CanvasGradeUpdate.objects.filter(membership__course=course).count()}


def copy_outline(course, source_course_id, author):
    from django.db import transaction
    from core.models import Course, Lesson, Activity, Revision
    if not course.metadata.get('load_test'):raise ValueError('Synthetic course required.')
    with transaction.atomic():
        source=Course.objects.get(pk=source_course_id)
        lesson_map={}; part_pairs=[]
        for old in source.lesson_set.filter(deleted_at=None).order_by('position'):
            if old.metadata.get('kind') == 'programming_quiz':continue
            lesson=Lesson.objects.create(course=course,title=old.title,position=old.position,
                visibility=old.visibility,metadata={k:copy.deepcopy(v) for k,v in old.metadata.items() if k in {'kind','group'}})
            lesson_map[old.pk]=lesson
        originals=Activity.objects.filter(lesson_id__in=lesson_map,deleted_at=None,published_revision__isnull=False).select_related('published_revision')
        new_parts=Activity.objects.bulk_create([Activity(lesson=lesson_map[a.lesson_id],title=a.title,position=a.position,
            metadata={k:copy.deepcopy(v) for k,v in a.metadata.items() if k in {'kind','category','group','sandbox'}}) for a in originals])
        revisions=Revision.objects.bulk_create([Revision(activity=part,number=1,created_by=author,
            content=copy.deepcopy(old.published_revision.content),grading=copy.deepcopy(old.published_revision.grading))
            for old,part in zip(originals,new_parts)])
        for part,rev in zip(new_parts,revisions):part.published_revision=rev
        Activity.objects.bulk_update(new_parts,['published_revision'])
    return len(lesson_map), len(new_parts)


def add_representative_workloads(fixture, source_part_ids=(444,712)):
    """Copy approved stdout graders into the synthetic assignment, never originals.

    Blob references are shared read-only; do not delete underlying blobs when
    retiring these copies. Answers remain in the private test manifest.
    """
    from core.models import Course,Membership,Lesson,Activity,Revision,ActivityFile
    from django.db import transaction
    course=Course.objects.get(pk=fixture['course_id'])
    if course.metadata.get('run_id')!=fixture['run_id'] or not course.metadata.get('load_test'):
        raise ValueError('Synthetic fixture mismatch.')
    author=Membership.objects.get(course=course,role='instructor').user
    lesson=Lesson.objects.get(pk=fixture['lesson_id'],course=course)
    workloads=[{**fixture['coding'],'name':'Synthetic addition','entrypoint':'main.py','case_count':3,
        'correct_source':fixture['correct_source'],'wrong_source':fixture['wrong_source'],
        'correct_stdout':'5\n','wrong_stdout':'-1\n'}]
    with transaction.atomic():
        for source_id in source_part_ids:
            original=Activity.objects.select_related('published_revision','lesson').get(pk=source_id,lesson__course_id=fixture['source_course_id'],deleted_at=None)
            old=original.published_revision;grading=old.grading;definition=grading.get('definition') or {}
            cases=definition.get('cases',[])
            if original.lesson.metadata.get('kind')=='programming_quiz' or not 6<=len(cases)<=12 or any(c.get('action')!='stdout' for c in cases):
                raise ValueError('Only reviewed non-quiz stdout exercises with 6–12 cases are supported.')
            if definition.get('random_cases') or definition.get('requirements') or grading.get('review_required'):
                raise ValueError('Unexpected grader complexity; review before copying.')
            entrypoint=grading['entrypoint']
            solution=old.files.filter(visibility='staff',path='solutions/sample_answer_1.py').get()
            with solution.blob.open('rb') as stream:correct=stream.read().decode('utf-8')
            defaults=old.files.get(path=entrypoint,visibility='student')
            with defaults.blob.open('rb') as stream:starter=stream.read().decode('utf-8')
            wrong=starter+'\nprint("Synthetic incorrect answer")\n'
            part=Activity.objects.create(lesson=lesson,title='Load test · '+original.title,position=len(workloads)+2,
                metadata={'kind':'coding','category':'problem_set','load_test_source_part':source_id})
            revision=Revision.objects.create(activity=part,number=1,created_by=author,content=copy.deepcopy(old.content),grading=copy.deepcopy(grading))
            ActivityFile.objects.bulk_create([ActivityFile(revision=revision,path=f.path,visibility=f.visibility,blob=f.blob.name,sha256=f.sha256) for f in old.files.all()])
            part.published_revision=revision;part.save(update_fields=['published_revision'])
            workloads.append({'activity':part.pk,'revision':revision.pk,'name':original.title,'entrypoint':entrypoint,
                'case_count':len(cases),'correct_source':correct,'wrong_source':wrong,'wrong_stdout':'Synthetic incorrect answer\n'})
    return workloads


def create_live_fixture(run_id, users=20, course_id=1, source_part_ids=(444,712)):
    """Enroll tagged test students in the real course. No content writes."""
    import re
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from core.models import Course,Membership,Activity
    if not re.fullmatch(r'[a-z0-9-]{6,50}',run_id) or not 1<=users<=20:raise ValueError('Invalid run or user count.')
    course=Course.objects.get(pk=course_id)
    if course.metadata.get('load_test'):raise ValueError('Use an actual course.')
    if Membership.objects.filter(source='loadtest',external_ids__trellis_load_test_run=run_id).exists():raise ValueError('Run already exists.')
    workloads=[]
    for source_id in source_part_ids:
        part=Activity.objects.select_related('published_revision','lesson').get(pk=source_id,lesson__course=course,deleted_at=None)
        old=part.published_revision;grading=old.grading;definition=grading.get('definition') or {};cases=definition.get('cases',[])
        if part.lesson.metadata.get('kind')=='programming_quiz' or part.lesson.visibility!='student' or not 6<=len(cases)<=12 or any(c.get('action')!='stdout' for c in cases):raise ValueError('Unexpected exercise type.')
        if definition.get('random_cases') or definition.get('requirements') or grading.get('review_required'):raise ValueError('Unexpected grader complexity.')
        entrypoint=grading['entrypoint']
        with old.files.get(path='solutions/sample_answer_1.py',visibility='staff').blob.open('rb') as stream:correct=stream.read().decode('utf-8')
        with old.files.get(path=entrypoint,visibility='student').blob.open('rb') as stream:starter=stream.read().decode('utf-8')
        workloads.append({'activity':part.pk,'revision':old.pk,'lesson_id':part.lesson_id,'name':part.title,'entrypoint':entrypoint,
            'case_count':len(cases),'correct_source':correct,'wrong_source':starter+'\nprint("Synthetic incorrect answer")\n'})
    reading=Activity.objects.filter(lesson__course=course,lesson__deleted_at=None,lesson__visibility='student',deleted_at=None,metadata__kind='reading',published_revision__isnull=False).select_related('lesson').order_by('pk').first()
    if not reading:raise ValueError('No reading found.')
    native=None
    for part in Activity.objects.filter(lesson__course=course,lesson__deleted_at=None,lesson__visibility='student',deleted_at=None,metadata__kind='question',published_revision__isnull=False).select_related('published_revision','lesson').order_by('pk'):
        if part.lesson.metadata.get('kind')=='programming_quiz':continue
        grading=part.published_revision.grading;rules=grading.get('questions',{});responses={}
        for qid,rule in rules.items():
            if 'correct_choice_ids' in rule:responses[qid]=rule['correct_choice_ids'][0] if rule.get('selection')=='one' else rule['correct_choice_ids']
            elif rule.get('answers'):responses[qid]=str(rule['answers'][0])
        if rules and len(responses)==len(rules) and not grading.get('review_required'):
            native={'activity':part.pk,'revision':part.published_revision_id,'lesson_id':part.lesson_id,'responses':responses,'maximum':str(grading.get('maximum_points',1))};break
    if not native:raise ValueError('No native question found.')
    accounts=[];enrollments=[]
    with transaction.atomic():
        for index in range(users):
            email=f'loadtest-{run_id}-{index:02d}@example.invalid';password=secrets.token_urlsafe(24)
            user=get_user_model().objects.create_user(username=email,email=email,password=password,first_name='Load Test',last_name=f'{run_id}-{index:02d}')
            member=Membership.objects.create(course=course,user=user,role='student',source='loadtest',external_ids={'trellis_load_test_run':run_id})
            accounts.append({'email':email,'password':password,'user_id':user.pk,'membership_id':member.pk});enrollments.append(member.pk)
    return {'version':1,'run_id':run_id,'live_course':True,'course_id':course.pk,'source_course_id':course.pk,
        'expected_title':course.title,'expected_term':course.term,'lesson_id':workloads[0]['lesson_id'],
        'source_course_id':course.pk,'copied_sections':0,'copied_parts':Activity.objects.filter(lesson__course=course,deleted_at=None,lesson__deleted_at=None,published_revision__isnull=False).count(),
        'accounts':accounts,'enrollment_ids':enrollments,'reading':{'activity':reading.pk,'revision':reading.published_revision_id,'lesson_id':reading.lesson_id},
        'native':native,'coding':workloads[0],'workloads':workloads,'staff_credentials_file':'var/azure-poc/login-details.json'}


def cleanup_live_fixture(fixture):
    """Delete only exact, tagged test identities after all their jobs drain."""
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from django.contrib.sessions.models import Session
    from core.models import Membership,ExecutionJob,Submission,GradeEvent,CanvasGradeUpdate,ActivityProgress,Workspace,LearningEvent,Activity
    from django.db.models import Count,Sum
    if not fixture.get('live_course'):raise ValueError('Expected a live-course fixture.')
    uids=[a['user_id'] for a in fixture['accounts']];mids=fixture['enrollment_ids']
    with transaction.atomic():
        members=list(Membership.objects.select_for_update().select_related('user').filter(pk__in=mids))
        assert len(members)==len(uids)==len(set(uids))
        for member in members:
            account=next(a for a in fixture['accounts'] if a['user_id']==member.user_id)
            assert member.course_id==fixture['course_id'] and member.role=='student' and member.source=='loadtest'
            assert member.external_ids.get('trellis_load_test_run')==fixture['run_id'] and member.user.email==account['email'] and member.user.username==account['email']
            assert account['email'].startswith('loadtest-'+fixture['run_id']+'-') and account['email'].endswith('@example.invalid')
            assert not member.user.is_staff and not member.user.is_superuser and not member.canvas_user_id
            assert Membership.objects.filter(user_id=member.user_id).count()==1
        assert not ExecutionJob.objects.filter(user_id__in=uids,status__in=['pending','running']).exists(),'Wait for jobs to drain.'
        assert not CanvasGradeUpdate.objects.filter(membership_id__in=mids).exists(),'Unexpected Canvas queue record.'
        protected_users=set(get_user_model().objects.exclude(pk__in=uids).values_list('pk',flat=True))
        outline_before=list(Activity.objects.filter(lesson__course_id=fixture['course_id']).order_by('pk').values_list('pk','published_revision_id','title','deleted_at'))
        other_progress=ActivityProgress.objects.filter(activity__lesson__course_id=fixture['course_id']).exclude(user_id__in=uids)
        grades_before=other_progress.aggregate(records=Count('pk'),points=Sum('score'),maximum=Sum('maximum'))
        counts={'test_users':len(uids),'jobs':ExecutionJob.objects.filter(user_id__in=uids).count(),'submissions':Submission.objects.filter(membership_id__in=mids).count(),
            'progress':ActivityProgress.objects.filter(user_id__in=uids).count(),'events':LearningEvent.objects.filter(membership_id__in=mids).count()}
        GradeEvent.objects.filter(submission__membership_id__in=mids).delete()
        Submission.objects.filter(membership_id__in=mids).delete()
        get_user_model().objects.filter(pk__in=uids).delete()
        for session in Session.objects.all().iterator():
            if str(session.get_decoded().get('_auth_user_id','')) in {str(u) for u in uids}:session.delete()
        assert set(get_user_model().objects.values_list('pk',flat=True))==protected_users
        assert not Membership.objects.filter(pk__in=mids).exists()
        assert not ExecutionJob.objects.filter(user_id__in=uids).exists()
        assert other_progress.aggregate(records=Count('pk'),points=Sum('score'),maximum=Sum('maximum'))==grades_before
        assert list(Activity.objects.filter(lesson__course_id=fixture['course_id']).order_by('pk').values_list('pk','published_revision_id','title','deleted_at'))==outline_before
    return {'status':'cleaned','run_id':fixture['run_id'],'removed':counts,'other_user_accounts_preserved':len(protected_users),'existing_course_progress_unchanged':True,'course_outline_unchanged':True}
