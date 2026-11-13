import base64
import binascii
import hashlib
import json
import math
import ast
from copy import deepcopy
from decimal import Decimal,InvalidOperation
from pathlib import PurePosixPath
from django.core.files.base import ContentFile
from django.http import JsonResponse,Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from ..models import Activity,ActivityFile,Lesson,Revision
from ..schema import validate_content
from ..services import publish
from django.core.exceptions import PermissionDenied
from ..structure import PART_KINDS,next_position
from ..studio import valid_path
from .auth import endpoint,APIError,course_guard,envelope


def fields(body,allowed):
 extra=set(body)-set(allowed)
 if extra:raise APIError(400,'unknown_fields','Unknown request fields.',{'fields':sorted(extra)})


def title(value):
 if not isinstance(value,str) or not value.strip() or len(value)>200:raise APIError(400,'invalid_title','Use a nonempty title up to 200 characters.')
 return value.strip()


def metadata(value):
 if not isinstance(value,dict) or len(json.dumps(value))>64000:raise APIError(400,'invalid_metadata','Metadata must be a JSON object smaller than 64 KB.')
 return value


def position(value):
 if type(value)!=int or not 0<=value<=1000000:raise APIError(400,'invalid_position','Position must be a nonnegative integer up to 1000000.')
 return value


def due_date(value):
 if value is None or value=='':return None
 due=parse_datetime(value) if isinstance(value,str) else None
 if due is None or timezone.is_naive(due):raise APIError(400,'invalid_due_at','Use an ISO 8601 timestamp with a UTC offset, or null.')
 return due.isoformat()


def validate_definition(value):
 if not isinstance(value,dict) or value.get('version')!=1 or set(value)-{'version','cases','requirements','scoring','timeout_seconds','random_cases'}:raise APIError(400,'invalid_grader','Expected a native version 1 grading definition.')
 if value.get('scoring','all_or_nothing') not in {'weighted','all_or_nothing'}:raise APIError(400,'invalid_grader','Unknown scoring policy.')
 timeout=value.get('timeout_seconds',2)
 if type(timeout) not in {int,float} or not math.isfinite(timeout) or not 0<timeout<=30:raise APIError(400,'invalid_grader','Timeout must be greater than zero and at most 30 seconds.')
 cases=value.get('cases');requirements=value.get('requirements',[])
 if not isinstance(cases,list) or not 1<=len(cases)<=200 or not isinstance(requirements,list):raise APIError(400,'invalid_grader','Use 1–200 cases and a requirements list.')
 def bounded(item,depth=0):
  if depth>20:raise APIError(400,'invalid_grader','Test data is nested too deeply.')
  if type(item) is float and not math.isfinite(item):raise APIError(400,'invalid_grader','Test values must be finite.')
  if type(item) is int and item.bit_length()>4096:raise APIError(400,'invalid_grader','Test integers are too large.')
  if isinstance(item,str) and len(item)>65536:raise APIError(400,'invalid_grader','Test strings are too long.')
  if isinstance(item,dict):
   for child in item.values():bounded(child,depth+1)
  if isinstance(item,list):
   if len(item)>10000:raise APIError(400,'invalid_grader','Test collections are too large.')
   for child in item:bounded(child,depth+1)
 bounded(value)
 ids=set()
 for case in cases:
  allowed={'id','label','expected','action','target','arguments','stdin','seed','tolerance','weight','public','hint','variables','steps','strip_output','files','argument_constructors','clock','comparison'}
  if not isinstance(case,dict) or set(case)-allowed or not {'id','label','expected'}<=set(case):raise APIError(400,'invalid_grader','Every case needs id, label, and expected fields.')
  identifier=case['id'];action=case.get('action','variable');target=case.get('target','')
  if not isinstance(identifier,str) or not identifier or identifier in ids or not isinstance(case['label'],str):raise APIError(400,'invalid_grader','Case IDs must be unique nonempty strings and labels must be text.')
  ids.add(identifier)
  if action not in {'variable','variable_type','function','stdout','file','scenario','trace','function_file','function_stdout','recursion','module_outcome'}:raise APIError(400,'invalid_grader','Unknown case action.')
  if action not in {'stdout','file'} and (not isinstance(target,str) or not target.isidentifier()):raise APIError(400,'invalid_grader','This case action needs an identifier target.')
  if action=='file' and not valid_path(target):raise APIError(400,'invalid_grader','Use a relative file target.')
  if action=='variable_type' and case['expected'] not in ('int','float','str','bool','list','dict','tuple','set','NoneType'):raise APIError(400,'invalid_grader','Unknown variable type.')
  if type(case.get('weight',1))!=int or case.get('weight',1)<=0:raise APIError(400,'invalid_grader','Case weights must be positive integers.')
  if type(case.get('public',True))!=bool or not isinstance(case.get('stdin',''),str) or not isinstance(case.get('hint',''),str) or type(case.get('seed',0))!=int:raise APIError(400,'invalid_grader','Invalid public, stdin, hint, or seed field.')
  if type(case.get('strip_output',False))!=bool or (case.get('strip_output') and (action not in {'stdout','function_stdout'} or not isinstance(case['expected'],str))):raise APIError(400,'invalid_grader','Output stripping requires a stdout case with a string expectation.')
  if case.get('comparison','exact') not in {'exact','contains','numeric_text','string','whitespace','python'}:raise APIError(400,'invalid_grader','Unknown comparison mode.')
  tolerance=case.get('tolerance')
  if tolerance is not None and (type(tolerance) not in {float,int} or not math.isfinite(tolerance) or tolerance<0):raise APIError(400,'invalid_grader','Tolerance must be a nonnegative finite number.')
  variables=case.get('variables',{})
  if not isinstance(variables,dict) or any(not key.isidentifier() for key in variables):raise APIError(400,'invalid_grader','Variable overrides need identifier keys.')
  if not isinstance(case.get('arguments',[]),list) or not isinstance(case.get('steps',[]),list):raise APIError(400,'invalid_grader','Arguments and steps must be lists.')
  from ..grading_contract import validate_fixture_path,validate_constructors,validate_trace,validate_observation_expected
  try:
   fixtures=case.get('files',{})
   if not isinstance(fixtures,dict) or len(fixtures)>20 or any(not isinstance(t,str) for t in fixtures.values()):raise ValueError('Invalid fixture files.')
   for path in fixtures:validate_fixture_path(path)
   validate_constructors(case.get('argument_constructors',{}),len(case.get('arguments',[])))
   if action=='trace':validate_trace(case.get('steps',[]))
   validate_observation_expected(action,case.get('steps',[]),case['expected'])
   if case.get('clock') is not None:
    import datetime
    if not isinstance(case['clock'],str):raise ValueError('Clock needs an ISO datetime.')
    datetime.datetime.fromisoformat(case['clock'])
  except ValueError as exc:raise APIError(400,'invalid_case_inputs',str(exc))
  if action=='scenario' and any(not isinstance(step,dict) or step.get('op') not in {'attribute','call'} or not isinstance(step.get('name'),str) or not step['name'].isidentifier() for step in case.get('steps',[])):raise APIError(400,'invalid_grader','Invalid scenario steps.')
 for rule in requirements:
  if not isinstance(rule,dict) or set(rule)!={'id','kind','target','message'} or any(not isinstance(v,str) for v in rule.values()) or not rule['id'] or rule['id'] in ids:raise APIError(400,'invalid_grader','Invalid source requirement.')
  ids.add(rule['id'])
  if rule['kind'] not in {'require_node','forbid_node','require_function','require_source','forbid_source','forbid_constant','require_comment','max_node_count','require_nested_if'}:raise APIError(400,'invalid_grader','Unknown source requirement.')
  if rule['kind']=='require_function':
   if not rule['target'].isidentifier():raise APIError(400,'invalid_grader','Function requirements need an identifier target.')
  elif rule['kind'] in {'require_node','forbid_node'}:
   node=getattr(ast,rule['target'],None)
   if not isinstance(node,type) or not issubclass(node,ast.AST):raise APIError(400,'invalid_grader','Unknown syntax-node requirement.')
  elif rule['kind']=='max_node_count':
   try:
    node,maximum=rule['target'].split(':')
    if not 0<=int(maximum)<=100 or not isinstance(getattr(ast,node,None),type):raise ValueError()
   except (ValueError,TypeError):raise APIError(400,'invalid_grader','Invalid syntax count limit.')
  elif rule['kind']=='forbid_constant':
   try:json.loads(rule['target'])
   except (ValueError,TypeError):raise APIError(400,'invalid_grader','Constant restrictions need a JSON literal.')
 if value.get("random_cases") is not None:
  from ..grading_contract import validate_random_cases
  try:
   validate_random_cases(value["random_cases"],len(cases))
   if any(c["id"].startswith("random-") for c in cases):raise ValueError("The random- case ID prefix is reserved")
  except ValueError as exc:raise APIError(400,"invalid_random_cases",str(exc))
 return value


def validate_grading(grading):
 if not isinstance(grading,dict):raise APIError(400,'invalid_grading','Grading must be a JSON object.')
 try:
  points=Decimal(str(grading.get('maximum_points',1)))
  if not points.is_finite() or not 0<=points<=10000:raise ValueError()
 except (InvalidOperation,ValueError):raise APIError(400,'invalid_points','Maximum points must be between 0 and 10000.')
 if grading.get('definition') is not None:validate_definition(grading['definition'])
 if 'questions' in grading and not isinstance(grading['questions'],dict):raise APIError(400,'invalid_grading','Questions must be a JSON object.')
 return grading


def assignment_data(lesson):
 return {'id':lesson.pk,'course_id':lesson.course_id,'title':lesson.title,'position':lesson.position,'visibility':lesson.visibility,
  'kind':lesson.metadata.get('kind','lesson'),'due_at':lesson.metadata.get('due_at'),'metadata':lesson.metadata,'deleted_at':lesson.deleted_at}


def part_data(part,revision=None,full=False):
 revision=revision or part.revisions.order_by('-number').first()
 data={'id':part.pk,'assignment_id':part.lesson_id,'course_id':part.lesson.course_id,'title':part.title,'position':part.position,
  'kind':part.metadata.get('kind'),'category':part.metadata.get('category','content'),'metadata':part.metadata,'deleted_at':part.deleted_at,
  'published_revision_id':part.published_revision_id,'revision_id':revision.pk if revision else None,'revision_number':revision.number if revision else None,
  'is_published':bool(revision and revision.pk==part.published_revision_id)}
 if full and revision:
  data.update(content=revision.content,grading=revision.grading,files=list(revision.files.values('path','visibility','sha256')))
 return data


def part_query(request):
 return Activity.objects.filter(lesson__course=request.api_course,lesson__deleted_at=None,deleted_at=None).select_related('lesson','published_revision')


def part_get(request,part_id,lock=False):
 query=part_query(request)
 if lock:query=query.select_for_update(of=('self',))
 return get_object_or_404(query,pk=part_id)


def latest(part):
 revision=part.revisions.order_by('-number').first()
 if revision is None:raise Http404
 return revision


def precondition(request,revision):
 expected=request.headers.get('If-Match')
 if expected is not None:
  expected=expected.strip().strip('"')
 else:expected=request.api_body.get('base_revision_id')
 if expected is None:raise APIError(428,'precondition_required','Send the latest revision ID in If-Match or base_revision_id.')
 if str(expected)!=str(revision.pk):raise APIError(412,'revision_conflict','This part changed. Fetch its latest revision before editing.')


def response_part(request,part,revision,status=200):
 request.api_audit={'part_id':part.pk,'revision_id':revision.pk,'assignment_id':part.lesson_id}
 response=JsonResponse(part_data(part,revision,True),status=status);response['ETag']=f'"{revision.pk}"';return response


def clone(part,old,user,content=None,grading=None):
 revision=Revision.objects.create(activity=part,number=old.number+1,created_by=user,content=old.content if content is None else content,grading=old.grading if grading is None else grading)
 ActivityFile.objects.bulk_create([ActivityFile(revision=revision,path=f.path,visibility=f.visibility,blob=f.blob.name,sha256=f.sha256) for f in old.files.all()])
 return revision


def write_file(revision,path,body,create_only=False):
 if not valid_path(path):raise APIError(400,'invalid_path','Use a safe relative file path.')
 current=revision.files.filter(path=path).first()
 if create_only and current:raise APIError(409,'file_exists','This file already exists. Use PUT to replace it.')
 visibility=body.get('visibility',current.visibility if current else None)
 if visibility not in {'student','staff','grader'}:raise APIError(400,'invalid_visibility','Set visibility explicitly to student, staff, or grader for new files.')
 reserved=PurePosixPath(path).name.casefold() in {'ferb.py','phineas.py','phineas_v2.py','utility.py','program.py','autograder.py'}
 if visibility=='student' and (path.startswith(('grader/','solutions/')) or reserved):raise APIError(400,'private_file','Grader and solution files cannot have student visibility.')
 if ('text' in body)==('content_base64' in body):raise APIError(400,'invalid_file','Send exactly one of text or content_base64.')
 if 'text' in body:
  if not isinstance(body['text'],str):raise APIError(400,'invalid_file','File text must be a string.')
  raw=body['text'].encode()
 else:
  try:raw=base64.b64decode(body['content_base64'],validate=True)
  except (ValueError,TypeError,binascii.Error):raise APIError(400,'invalid_file','Invalid base64 file content.')
 if len(raw)>1024*1024:raise APIError(413,'file_too_large','Files must be at most 1 MB.')
 revision.files.filter(path=path).delete()
 ActivityFile.objects.create(revision=revision,path=path,visibility=visibility,blob=ContentFile(raw,name=PurePosixPath(path).name),sha256=hashlib.sha256(raw).hexdigest())


@endpoint({'GET':['course:read']})
def courses(request):return envelope(request,[request.api_course],lambda c:{'id':c.pk,'title':c.title,'term':c.term})

@endpoint({'GET':['course:read']})
def course_detail(request,course_id):
 course_guard(request,course_id);c=request.api_course
 return JsonResponse({'id':c.pk,'title':c.title,'term':c.term,'api_version':'v1','timestamps':'UTC ISO 8601; unavailable historical timestamps are null.'})

@endpoint({'GET':['content:read'],'POST':['content:write']})
def assignments(request,course_id):
 course_guard(request,course_id)
 if request.method=='GET':
  query=Lesson.objects.filter(course=request.api_course,deleted_at=None).order_by('position','pk')
  if request.GET.get('search'):query=query.filter(title__icontains=request.GET['search'])
  return envelope(request,query,assignment_data)
 body=request.api_body;fields(body,{'title','kind','position','visibility','metadata','due_at'})
 kind=body.get('kind','lesson')
 if kind not in {'lesson','programming_quiz'}:raise APIError(400,'invalid_kind','Assignment kind must be lesson or programming_quiz.')
 visibility=body.get('visibility','staff')
 if visibility not in {'student','staff'}:raise APIError(400,'invalid_visibility','Unknown visibility.')
 meta={**metadata(body.get('metadata',{})),'kind':kind,'due_at':due_date(body.get('due_at'))}
 if request.api_member.role!='instructor' and any(meta.get(k) for k in ('due_at','canvas_assignment_id')):raise PermissionDenied
 lesson=Lesson.objects.create(course=request.api_course,title=title(body.get('title')),metadata=meta,visibility=visibility,position=position(body.get('position',next_position(request.api_course.lesson_set.all()))))
 request.api_audit={'assignment_id':lesson.pk};return JsonResponse(assignment_data(lesson),status=201)

@endpoint({'GET':['content:read'],'PATCH':['content:write'],'DELETE':['content:write']})
def assignment_detail(request,assignment_id):
 lesson=get_object_or_404(Lesson.objects.select_for_update(),pk=assignment_id,course=request.api_course,deleted_at=None)
 if request.method=='DELETE':
  lesson.deleted_at=timezone.now();lesson.save(update_fields=['deleted_at']);request.api_audit={'assignment_id':lesson.pk,'soft_deleted':True};return JsonResponse({'id':lesson.pk,'deleted':True})
 if request.method=='PATCH':
  body=request.api_body;fields(body,{'title','position','visibility','metadata','due_at'})
  if 'title' in body:lesson.title=title(body['title'])
  if 'position' in body:lesson.position=position(body['position'])
  if 'visibility' in body:
   if body['visibility'] not in {'student','staff'}:raise APIError(400,'invalid_visibility','Unknown visibility.')
   lesson.visibility=body['visibility']
  if 'metadata' in body:lesson.metadata={**lesson.metadata,**metadata(body['metadata'])}
  if 'due_at' in body:lesson.metadata={**lesson.metadata,'due_at':due_date(body['due_at'])}
  if request.api_member.role!='instructor':
   old=Lesson.objects.get(pk=lesson.pk).metadata
   if any(lesson.metadata.get(k)!=old.get(k) for k in ('due_at','canvas_assignment_id')):raise PermissionDenied
  lesson.save();request.api_audit={'assignment_id':lesson.pk,'fields':sorted(body)}
 return JsonResponse(assignment_data(lesson))

@endpoint({'GET':['content:read'],'POST':['content:write']})
def parts(request,assignment_id):
 lesson=get_object_or_404(Lesson,pk=assignment_id,course=request.api_course,deleted_at=None)
 if request.method=='GET':
  query=part_query(request).filter(lesson=lesson).order_by('position','pk')
  if request.GET.get('kind'):query=query.filter(metadata__kind=request.GET['kind'])
  if request.GET.get('search'):query=query.filter(title__icontains=request.GET['search'])
  from .auth import paginate
  page,meta=paginate(request,query);page=list(page);current={}
  for revision in Revision.objects.filter(activity__in=page).order_by('activity_id','-number'):
   current.setdefault(revision.activity_id,revision)
  return JsonResponse({**meta,'results':[part_data(p,current.get(p.pk)) for p in page]})
 body=request.api_body;fields(body,{'title','kind','category','position','metadata','content','grading','files'})
 kind=body.get('kind','reading');template=PART_KINDS.get('quiz' if kind=='question' else kind)
 if not template:raise APIError(400,'invalid_kind','Use reading, video, coding, or question.')
 content=body.get('content',deepcopy(template['content']));validate_content(content)
 grading=validate_grading(body.get('grading',deepcopy(template['grading'])))
 part=Activity.objects.create(lesson=lesson,title=title(body.get('title')),position=position(body.get('position',next_position(lesson.activity_set.all()))),
  metadata={**template['metadata'],**metadata(body.get('metadata',{})),'kind':kind,'category':body.get('category',template['category'])})
 revision=Revision.objects.create(activity=part,number=1,created_by=request.user,content=content,grading=grading)
 files=body.get('files',[])
 if not isinstance(files,list) or len(files)>100:raise APIError(400,'invalid_files','Use a list of up to 100 files.')
 for f in files:
  if not isinstance(f,dict):raise APIError(400,'invalid_files','Each file must be an object.')
  write_file(revision,f.get('path'),f,True)
 return response_part(request,part,revision,201)

@endpoint({'GET':['content:read'],'PATCH':['content:write'],'DELETE':['content:write']})
def part_detail(request,part_id):
 part=part_get(request,part_id,request.method!='GET');old=latest(part)
 if old is None:raise Http404
 if request.method=='GET':return response_part(request,part,old)
 precondition(request,old)
 if request.method=='DELETE':
  part.deleted_at=timezone.now();part.save(update_fields=['deleted_at']);request.api_audit={'part_id':part.pk,'soft_deleted':True};return JsonResponse({'id':part.pk,'deleted':True})
 body=request.api_body;fields(body,{'base_revision_id','title','position','metadata','content','grading','files'})
 content=body.get('content',old.content);validate_content(content)
 grading=old.grading
 if 'grading' in body:
  grading=validate_grading({**old.grading,**body['grading']}) if isinstance(body['grading'],dict) else validate_grading(body['grading'])
 revision=clone(part,old,request.user,content,grading)
 if 'title' in body:part.title=title(body['title'])
 if 'position' in body:part.position=position(body['position'])
 if 'metadata' in body:part.metadata={**part.metadata,**metadata(body['metadata'])}
 part.save(update_fields=['title','position','metadata'])
 files=body.get('files',[])
 if not isinstance(files,list) or len(files)>100:raise APIError(400,'invalid_files','Use a list of up to 100 file upserts.')
 for f in files:
  if not isinstance(f,dict):raise APIError(400,'invalid_files','Each file must be an object.')
  write_file(revision,f.get('path'),f)
 return response_part(request,part,revision)

@endpoint({'GET':['content:read']})
def revisions(request,part_id):
 part=part_get(request,part_id)
 return envelope(request,part.revisions.order_by('-number'),lambda r:{'id':r.pk,'part_id':part.pk,'number':r.number,'created_at':r.created_at,'created_by':r.created_by_id,'published':r.pk==part.published_revision_id})

@endpoint({'GET':['content:read']})
def revision_detail(request,part_id,revision_id):
 part=part_get(request,part_id);revision=get_object_or_404(part.revisions,pk=revision_id)
 return response_part(request,part,revision)

@endpoint({'POST':['content:publish']})
def publish_part(request,part_id):
 part=part_get(request,part_id,True);old=latest(part);precondition(request,old)
 revision=get_object_or_404(part.revisions,pk=request.api_body.get('revision_id',old.pk))
 publish(part,revision,request.user);return response_part(request,part,revision)

@endpoint({'GET':['content:read'],'POST':['content:write']})
def files(request,part_id):
 part=part_get(request,part_id,request.method!='GET');old=latest(part)
 if request.method=='GET':return envelope(request,old.files.order_by('path'),lambda f:{'path':f.path,'visibility':f.visibility,'sha256':f.sha256,'revision_id':old.pk})
 fields(request.api_body,{'base_revision_id','path','visibility','text','content_base64'});precondition(request,old)
 revision=clone(part,old,request.user);write_file(revision,request.api_body.get('path'),request.api_body,True)
 return response_part(request,part,revision,201)

@endpoint({'GET':['content:read'],'PUT':['content:write'],'DELETE':['content:write']})
def file_detail(request,part_id,file_path):
 part=part_get(request,part_id,request.method!='GET');old=latest(part)
 if not valid_path(file_path):raise APIError(400,'invalid_path','Use a safe relative path.')
 if request.method=='GET':
  revision=old
  if request.GET.get('revision_id'):revision=get_object_or_404(part.revisions,pk=request.GET['revision_id'])
  file=get_object_or_404(revision.files,path=file_path)
  with file.blob.open('rb') as stream:raw=stream.read()
  data={'path':file.path,'revision_id':revision.pk,'visibility':file.visibility,'sha256':file.sha256}
  try:data.update(encoding='utf-8',text=raw.decode('utf-8'))
  except UnicodeDecodeError:data.update(encoding='base64',content_base64=base64.b64encode(raw).decode())
  response=JsonResponse(data);response['ETag']=f'"{revision.pk}"';return response
 precondition(request,old);fields(request.api_body,{'base_revision_id','visibility','text','content_base64'})
 revision=clone(part,old,request.user)
 if request.method=='DELETE':get_object_or_404(revision.files,path=file_path).delete()
 else:write_file(revision,file_path,request.api_body)
 return response_part(request,part,revision)

@endpoint({'GET':['content:read'],'PUT':['content:write']})
def grader(request,part_id):
 part=part_get(request,part_id,request.method!='GET');old=latest(part)
 if part.metadata.get('kind')!='coding':raise APIError(400,'not_coding','This endpoint applies to coding parts.')
 if request.method=='GET':return JsonResponse({'part_id':part.pk,'revision_id':old.pk,'definition':old.grading.get('definition'),'entrypoint':old.grading.get('entrypoint'),'review_required':bool(old.grading.get('review_required'))})
 body=request.api_body;fields(body,{'base_revision_id','definition','entrypoint','maximum_points','mark_reviewed','reference_source'})
 precondition(request,old);definition=validate_definition(body.get('definition'))
 entrypoint=body.get('entrypoint',old.grading.get('entrypoint'))
 if not valid_path(entrypoint) or not entrypoint.endswith('.py') or not old.files.filter(path=entrypoint,visibility='student').exists():raise APIError(400,'invalid_entrypoint','Choose a Python file with student visibility.')
 grading={**old.grading,'definition':definition,'entrypoint':entrypoint,'placeholder':False}
 if 'maximum_points' in body:grading['maximum_points']=body['maximum_points']
 if body.get('mark_reviewed') is True:grading['review_required']=False
 validate_grading(grading)
 reference=body.get('reference_source')
 random_spec=definition.get('random_cases')
 if reference is not None and (not isinstance(reference,str) or not reference or len(reference.encode())>256000):raise APIError(400,'invalid_reference','Reference source must be nonempty Python text up to 256 KB.')
 if random_spec and reference is None and not old.files.filter(path=random_spec['oracle_path']).exclude(visibility='student').exists():raise APIError(400,'missing_reference','Upload a private reference source for random tests.')
 if reference is not None and not random_spec:raise APIError(400,'invalid_reference','A reference source requires random case configuration.')
 revision=clone(part,old,request.user,grading=grading)
 if random_spec and reference is not None:write_file(revision,random_spec['oracle_path'],{'text':reference,'visibility':'grader'})
 write_file(revision,'grader/tests.json',{'text':json.dumps(definition,indent=2),'visibility':'grader'})
 return response_part(request,part,revision)

@endpoint({'GET':['content:read']})
def missing_graders(request,course_id):
 course_guard(request,course_id)
 query=part_query(request).filter(metadata__kind='coding',published_revision__isnull=False).prefetch_related('published_revision__files').order_by('lesson__position','position','pk')
 rows=[]
 for part in query:
  r=part.published_revision
  if part.metadata.get('sandbox'):continue
  definition=r.grading.get('definition');reason=[]
  try:validate_definition(definition)
  except APIError:reason.append('missing_or_invalid_native_definition')
  if r.grading.get('placeholder'):reason.append('coding_files_not_imported')
  if r.grading.get('review_required'):reason.append('grader_review_required')
  files=list(r.files.all());entrypoint=r.grading.get('entrypoint')
  random_spec=(definition or {}).get('random_cases') if isinstance(definition,dict) else None
  if random_spec and not any(f.path==random_spec.get('oracle_path') and f.visibility!='student' for f in files):reason.append('missing_private_reference')
  if not any(f.path==entrypoint and f.visibility=='student' for f in files):reason.append('missing_student_entrypoint')
  if not reason and request.GET.get('include_ready')!='true':continue
  rows.append({'part_id':part.pk,'assignment_id':part.lesson_id,'assignment_title':part.lesson.title,'title':part.title,
    'published_revision_id':r.pk,'vocareum_part_id':part.metadata.get('vocareum_part_id') or r.grading.get('vocareum_part_id'),
    'needs_attention':bool(reason),'reasons':reason,'has_native_definition':bool(definition and isinstance(definition,dict) and definition.get('cases')),'has_native_grader_file':any(f.path=='grader/tests.json' for f in files),
    'grader_files':[f.path for f in files if f.visibility=='grader'],'staff_files':[f.path for f in files if f.visibility=='staff']})
 return envelope(request,rows)


@endpoint({'PATCH':['content:write']})
def part_titles(request, course_id):
 """Rename multiple live part titles atomically without cloning content revisions."""
 course_guard(request,course_id)
 fields(request.api_body,{'updates'})
 updates=request.api_body.get('updates')
 if not isinstance(updates,list) or not 1<=len(updates)<=500:
  raise APIError(400,'invalid_updates','Send between 1 and 500 title updates.')
 checked=[];ids=set()
 for update in updates:
  if not isinstance(update,dict):raise APIError(400,'invalid_updates','Each update must be an object.')
  fields(update,{'id','title','expected_title'})
  identifier=update.get('id')
  if type(identifier)!=int or identifier<=0 or identifier in ids:raise APIError(400,'invalid_updates','Use unique positive part IDs.')
  if not isinstance(update.get('expected_title'),str):raise APIError(400,'expected_title_required','Include the current expected_title for each part to prevent overwriting another edit.')
  checked.append((identifier,title(update.get('title')),update['expected_title']));ids.add(identifier)
 rows={row.pk:row for row in Activity.objects.select_for_update().filter(pk__in=ids,
  lesson__course=request.api_course,lesson__deleted_at=None,deleted_at=None).order_by('pk')}
 if set(rows)!=ids:raise APIError(404,'part_not_found','One or more parts are unavailable in this course.')
 for identifier,value,expected in checked:
  if rows[identifier].title!=expected:raise APIError(409,'title_conflict','A part title changed. Fetch current titles before retrying.',{'part_id':identifier,'current_title':rows[identifier].title})
 for identifier,value,expected in checked:rows[identifier].title=value
 Activity.objects.bulk_update(rows.values(),['title'])
 request.api_audit={'part_ids':sorted(ids),'titles_updated':len(rows)}
 return JsonResponse({'updated':len(rows),'results':[{'id':identifier,'assignment_id':rows[identifier].lesson_id,'title':value} for identifier,value,_ in checked]})
