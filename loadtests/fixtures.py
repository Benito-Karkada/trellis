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
