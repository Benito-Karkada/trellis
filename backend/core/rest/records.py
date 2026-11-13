from decimal import Decimal
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from ..models import Membership,Lesson,Activity,ActivityProgress,AssignmentVisit,LearningEvent,Submission,ExecutionJob,Workspace,Accommodation,APIAuditEvent
from ..course_settings import enroll,clean_email
from ..studio import activity_maximum
from .auth import endpoint,APIError,course_guard,envelope,paginate,ids_filter
from .content import fields,due_date


def person(member):
 return {'id':member.pk,'user_id':member.user_id,'course_id':member.course_id,'email':member.user.email or member.user.username,
  'first_name':member.user.first_name,'last_name':member.user.last_name,'name':member.user.get_full_name(),
  'role':member.role,'active':member.active,'source':member.source,'canvas_user_id':member.canvas_user_id,'external_ids':member.external_ids}


def student_filters(request,query,member_path='membership',assignment_path='revision__activity__lesson',part_path='revision__activity'):
 members=ids_filter(request,'enrollment_ids');assignments=ids_filter(request,'assignment_ids');parts=ids_filter(request,'part_ids')
 if members:query=query.filter(**{member_path+'__in':members})
 if assignments:query=query.filter(**{assignment_path+'__in':assignments})
 if parts:query=query.filter(**{part_path+'__in':parts})
 return query


def date_filters(request,query,field='created_at'):
 for key,lookup in [('since','gte'),('until','lte')]:
  if request.GET.get(key):
   value=parse_datetime(request.GET[key])
   if value is None or timezone.is_naive(value):raise APIError(400,'invalid_timestamp',f'{key} must be ISO 8601 with a UTC offset.')
   query=query.filter(**{field+'__'+lookup:value})
 return query


@endpoint({'GET':['roster:read'],'POST':['roster:write']})
def enrollments(request,course_id):
 course_guard(request,course_id)
 if request.method=='GET':
  query=Membership.objects.filter(course=request.api_course).select_related('user').order_by('pk')
  if request.GET.get('include_inactive')!='true':query=query.filter(active=True)
  if request.GET.get('role'):query=query.filter(role=request.GET['role'])
  if request.GET.get('search'):
   needle=request.GET['search'];query=query.filter(Q(user__email__icontains=needle)|Q(user__first_name__icontains=needle)|Q(user__last_name__icontains=needle))
  return envelope(request,query,person)
 body=request.api_body;fields(body,{'email','role','name','external_ids','canvas_user_id'})
 email=clean_email(body.get('email'));role=body.get('role','student')
 if Membership.objects.filter(course=request.api_course,user__email__iexact=email).exists():raise APIError(409,'enrollment_exists','This person already has an enrollment. PATCH that enrollment to restore or update it.')
 member,_=enroll(request.api_course,email,role,name=body.get('name',''))
 update_identifiers(member,body);member.save();request.api_audit={'enrollment_id':member.pk,'role':member.role}
 return JsonResponse(person(member),status=201)


def update_identifiers(member,body):
 if 'external_ids' in body:
  value=body['external_ids']
  if not isinstance(value,dict) or set(value)-{'gtid','gt_username','sis_user_id'} or any(not isinstance(v,str) or len(v)>100 for v in value.values()):raise APIError(400,'invalid_external_ids','Use string gtid, gt_username, and/or sis_user_id values up to 100 characters.')
  member.external_ids={**member.external_ids,**value}
 if 'canvas_user_id' in body:
  value=body['canvas_user_id']
  if not isinstance(value,str) or len(value)>32 or (value and not value.isdigit()):raise APIError(400,'invalid_canvas_user_id','Canvas user ID must be a numeric string or empty.')
  if value and Membership.objects.filter(course=member.course,canvas_user_id=value).exclude(pk=member.pk).exists():raise APIError(409,'identifier_conflict','Another enrollment already has this Canvas user ID.')
  member.canvas_user_id=value

@endpoint({'GET':['roster:read'],'PATCH':['roster:write'],'DELETE':['roster:write']})
def enrollment_detail(request,enrollment_id):
 member=get_object_or_404(Membership.objects.select_for_update(of=('self',)).select_related('user'),pk=enrollment_id,course=request.api_course)
 if request.method=='GET':return JsonResponse(person(member))
 if member.pk==request.api_member.pk:raise APIError(400,'self_enrollment','You cannot modify your own enrollment through this token.')
 if request.method=='DELETE':member.active=False
 else:
  body=request.api_body;fields(body,{'active','role','first_name','last_name','external_ids','canvas_user_id'})
  if 'active' in body:
   if type(body['active'])!=bool:raise APIError(400,'invalid_active','Active must be a boolean.')
   member.active=body['active']
  if 'role' in body:
   if body['role'] not in {'student','ta','instructor'}:raise APIError(400,'invalid_role','Use student, ta, or instructor.')
   member.role=body['role']
  for field in ('first_name','last_name'):
   if field in body:
    value=body[field]
    if not isinstance(value,str) or len(value)>150:raise APIError(400,'invalid_name','Names must be strings up to 150 characters.')
    setattr(member.user,field,value)
  member.user.save(update_fields=['first_name','last_name']);update_identifiers(member,body)
 member.save();request.api_audit={'enrollment_id':member.pk,'active':member.active,'role':member.role}
 return JsonResponse(person(member))

@endpoint({'GET':['grades:read']})
def grades(request,course_id):
 course_guard(request,course_id)
 members=Membership.objects.filter(course=request.api_course,role='student').select_related('user').order_by('pk')
 if request.GET.get('include_inactive')!='true':members=members.filter(active=True)
 mids=ids_filter(request,'enrollment_ids')
 if mids:members=members.filter(pk__in=mids)
 lessons=Lesson.objects.filter(course=request.api_course,deleted_at=None).order_by('pk')
 lids=ids_filter(request,'assignment_ids')
 if lids:lessons=lessons.filter(pk__in=lids)
 lessons=list(lessons);members=list(members)
 pairs=[(m,l) for m in members for l in lessons]
 page,meta=paginate(request,pairs)
 member_ids={m.user_id for m,l in page};lesson_ids={l.pk for m,l in page}
 activities=list(Activity.objects.filter(lesson_id__in=lesson_ids,deleted_at=None,published_revision__isnull=False).select_related('published_revision'))
 totals={l.pk:Decimal(0) for m,l in page}
 for a in activities:totals[a.lesson_id]+=Decimal(activity_maximum(a))
 scores={}
 for p in ActivityProgress.objects.filter(user_id__in=member_ids,activity__in=activities).select_related('activity'):
  key=(p.user_id,p.activity.lesson_id);scores[key]=scores.get(key,Decimal(0))+p.score
 visits={(v.membership_id,v.assignment_id):v for v in AssignmentVisit.objects.filter(membership_id__in=[m.pk for m,l in page],assignment_id__in=lesson_ids)}
 rows=[]
 for member,lesson in page:
  visit=visits.get((member.pk,lesson.pk))
  rows.append({'enrollment_id':member.pk,'user_id':member.user_id,'email':member.user.email or member.user.username,'name':member.user.get_full_name(),
   'assignment_id':lesson.pk,'assignment_title':lesson.title,'earned':format(scores.get((member.user_id,lesson.pk),Decimal(0)).normalize(),'f'),'maximum':format(totals[lesson.pk].normalize(),'f'),
   'due_at':lesson.metadata.get('due_at'),'first_opened_at':visit.first_opened_at if visit else None,'last_opened_at':visit.last_opened_at if visit else None})
 return JsonResponse({**meta,'results':rows})

@endpoint({'GET':['submissions:read']})
def submissions(request,course_id):
 course_guard(request,course_id)
 query=Submission.objects.filter(membership__course=request.api_course).select_related('membership__user','revision__activity__lesson').order_by('pk')
 from django.db.models.functions import Coalesce
 query=query.annotate(api_received_at=Coalesce('received_at','created_at'))
 query=date_filters(request,student_filters(request,query),'api_received_at')
 page,meta=paginate(request,query)
 page=list(page);job_ids=[s.response.get('job') for s in page if isinstance(s.response,dict) and s.response.get('job')]
 # Only trust valid job IDs saved by the server; arbitrary native answers may
 # happen to use a question named "job".
 import uuid
 valid=[]
 for value in job_ids:
  try:valid.append(uuid.UUID(str(value)))
  except ValueError:pass
 jobs={str(j.pk):j for j in ExecutionJob.objects.filter(pk__in=valid,user_id__in=[s.membership.user_id for s in page])}
 rows=[]
 for s in page:
  job=jobs.get(str(s.response.get('job'))) if isinstance(s.response,dict) else None
  if job and (job.user_id!=s.membership.user_id or job.revision_id!=s.revision_id):job=None
  rows.append({'id':s.pk,'enrollment_id':s.membership_id,'user_id':s.membership.user_id,'email':s.membership.user.email,
   'assignment_id':s.revision.activity.lesson_id,'part_id':s.revision.activity_id,'revision_id':s.revision_id,
   'kind':'coding' if job else 'native','submitted_at':s.received_at or (job.created_at if job else s.created_at),
   'record_created_at':s.created_at,'graded_at':job.completed_at if job else s.created_at,
   'response':s.response,'execution_job_id':str(job.pk) if job else None,'result':job.result if job else None})
 return JsonResponse({**meta,'results':rows})

@endpoint({'GET':['submissions:read']})
def execution_jobs(request,course_id):
 course_guard(request,course_id)
 query=ExecutionJob.objects.filter(revision__activity__lesson__course=request.api_course,preview=False).select_related('revision__activity').order_by('created_at','pk')
 assignments=ids_filter(request,'assignment_ids');parts=ids_filter(request,'part_ids');mids=ids_filter(request,'enrollment_ids')
 if assignments:query=query.filter(revision__activity__lesson_id__in=assignments)
 if parts:query=query.filter(revision__activity_id__in=parts)
 if mids:query=query.filter(user_id__in=Membership.objects.filter(course=request.api_course,pk__in=mids).values('user_id'))
 if request.GET.get('status'):query=query.filter(status=request.GET['status'])
 if request.GET.get('operation'):query=query.filter(operation=request.GET['operation'])
 query=date_filters(request,query)
 def serialize(j):
  data={'id':str(j.pk),'user_id':j.user_id,'assignment_id':j.revision.activity.lesson_id,'part_id':j.revision.activity_id,'revision_id':j.revision_id,
   'review_signals':j.review_signals,'operation':j.operation,'status':j.status,'submitted_at':j.created_at,'claimed_at':j.claimed_at,'completed_at':j.completed_at,'result':j.result}
  if request.GET.get('include_files')=='true':data['files']=j.snapshot
  return data
 return envelope(request,query,serialize)

@endpoint({'GET':['submissions:read']})
def workspace(request,enrollment_id,part_id):
 member=get_object_or_404(Membership,pk=enrollment_id,course=request.api_course)
 part=get_object_or_404(Activity.objects.select_related('published_revision'),pk=part_id,lesson__course=request.api_course,deleted_at=None,lesson__deleted_at=None)
 saved=Workspace.objects.filter(user=member.user,revision__activity=part).order_by('-updated_at').first()
 allowed=set(part.published_revision.files.filter(visibility='student').values_list('path',flat=True)) if part.published_revision else set()
 return JsonResponse({'enrollment_id':member.pk,'part_id':part.pk,'assignment_id':part.lesson_id,'revision_id':saved.revision_id if saved else None,
  'saved_at':saved.updated_at if saved else None,'files':{p:t for p,t in (saved.files if saved else {}).items() if p in allowed}})

@endpoint({'GET':['activity:read']})
def visits(request,course_id):
 course_guard(request,course_id)
 query=AssignmentVisit.objects.filter(membership__course=request.api_course).select_related('membership__user').order_by('pk')
 mids=ids_filter(request,'enrollment_ids');lids=ids_filter(request,'assignment_ids')
 if mids:query=query.filter(membership_id__in=mids)
 if lids:query=query.filter(assignment_id__in=lids)
 query=date_filters(request,query,'first_opened_at')
 return envelope(request,query,lambda v:{'id':v.pk,'enrollment_id':v.membership_id,'user_id':v.membership.user_id,'email':v.membership.user.email,
  'assignment_id':v.assignment_id,'first_opened_at':v.first_opened_at,'last_opened_at':v.last_opened_at,'open_count':v.open_count})

@endpoint({'GET':['activity:read']})
def events(request,course_id):
 course_guard(request,course_id)
 query=LearningEvent.objects.filter(membership__course=request.api_course).select_related('membership').order_by('pk')
 query=date_filters(request,student_filters(request,query,assignment_path='assignment',part_path='part'))
 if request.GET.get('kind'):query=query.filter(kind=request.GET['kind'])
 return envelope(request,query,lambda e:{'id':e.pk,'enrollment_id':e.membership_id,'user_id':e.membership.user_id,'assignment_id':e.assignment_id,'part_id':e.part_id,'kind':e.kind,'created_at':e.created_at,'metadata':e.metadata})

@endpoint({'GET':['audit:read']})
def audit(request,course_id):
 course_guard(request,course_id)
 query=date_filters(request,APIAuditEvent.objects.filter(course=request.api_course).order_by('pk'))
 return envelope(request,query,lambda e:{'id':e.pk,'actor_user_id':e.actor_id,'token_id':str(e.token_id) if e.token_id else None,'request_id':str(e.request_id),'method':e.method,'path':e.path,'status':e.status,'summary':e.summary,'created_at':e.created_at})

@endpoint({'GET':['roster:read'],'PUT':['roster:write']})
def accommodations(request,enrollment_id):
 member=get_object_or_404(Membership,pk=enrollment_id,course=request.api_course)
 if request.method=='GET':return envelope(request,Accommodation.objects.filter(membership=member).order_by('pk'),lambda a:{'id':a.pk,'assignment_id':a.lesson_id,'part_id':a.activity_id,'time_multiplier':str(a.time_multiplier),'extra_minutes':a.extra_minutes,'extra_attempts':a.extra_attempts,'due_at_override':a.due_at_override})
 body=request.api_body;fields(body,{'assignment_id','part_id','time_multiplier','extra_minutes','extra_attempts','due_at_override'})
 lesson=None;part=None
 if body.get('assignment_id') and body.get('part_id'):raise APIError(400,'invalid_scope','Choose an assignment or part, not both.')
 if body.get('assignment_id'):lesson=get_object_or_404(Lesson,pk=body['assignment_id'],course=request.api_course,deleted_at=None)
 if body.get('part_id'):part=get_object_or_404(Activity,pk=body['part_id'],lesson__course=request.api_course,deleted_at=None)
 try:
  multiplier=Decimal(str(body.get('time_multiplier',1)))
  if not multiplier.is_finite() or not 1<=multiplier<=100:raise ValueError()
 except (ValueError,ArithmeticError):raise APIError(400,'invalid_accommodation','Time multiplier must be between 1 and 100.')
 for key in ('extra_minutes','extra_attempts'):
  if type(body.get(key,0))!=int or not 0<=body.get(key,0)<=10000:raise APIError(400,'invalid_accommodation',f'{key} must be a nonnegative integer up to 10000.')
 raw=due_date(body.get('due_at_override'));due=parse_datetime(raw) if raw else None
 value,_=Accommodation.objects.update_or_create(membership=member,lesson=lesson,activity=part,defaults={'time_multiplier':multiplier,'extra_minutes':body.get('extra_minutes',0),'extra_attempts':body.get('extra_attempts',0),'due_at_override':due})
 request.api_audit={'enrollment_id':member.pk,'accommodation_id':value.pk};return JsonResponse({'id':value.pk,'updated':True})


@endpoint({'GET':['activity:read','submissions:read']})
def submission_review_report(request,course_id):
 course_guard(request,course_id)
 from ..submission_review import report_data
 return JsonResponse(report_data(request,request.api_course))


@endpoint({'GET':['activity:read','submissions:read','roster:read']})
def submission_review_export(request,course_id):
 course_guard(request,course_id)
 from ..review_export import response
 return response(request,request.api_course)
