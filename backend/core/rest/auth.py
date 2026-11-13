import hashlib
import hmac
import json
import secrets
import uuid
from functools import wraps
from datetime import timedelta
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.http import JsonResponse,Http404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from ..models import APIToken,APIAuditEvent,APIReplay,Membership

SCOPES={
 'course:read':'Read course information',
 'content:read':'Read staff content, grader definitions, and private files',
 'content:write':'Create and edit assignments, parts, drafts, and files',
 'content:publish':'Publish part revisions',
 'roster:read':'Read enrolled people and external identifiers',
 'roster:write':'Add, drop, or change enrollments (instructors only)',
 'grades:read':'Read course, assignment, and part scores',
 'submissions:read':'Read submissions, execution snapshots, and student workspaces',
 'activity:read':'Read assignment visits and learning events',
 'execution:write':'Run staff test copies in the isolated executor',
 'audit:read':'Read API audit events (instructors only)',
}
INSTRUCTOR_ONLY={'roster:write','audit:read'}
READ_SCOPES=[key for key in SCOPES if key.endswith(':read') and key!='audit:read']

class APIError(Exception):
 def __init__(self,status,code,message,details=None):
  self.status=status;self.code=code;self.message=message;self.details=details


def allowed_scopes(member):
 return set(SCOPES) if member.role=='instructor' else set(SCOPES)-INSTRUCTOR_ONLY


def issue_token(member,name,scopes,days=30):
 if not isinstance(name,str) or not name.strip() or len(name)>120:raise APIError(400,'invalid_name','Enter a token name, up to 120 characters.')
 if not isinstance(scopes,list) or not scopes or any(not isinstance(s,str) for s in scopes) or not set(scopes)<=allowed_scopes(member):
  raise APIError(400,'invalid_scopes','Select permitted access scopes.')
 if type(days)!=int or not 1<=days<=365:raise APIError(400,'invalid_expiry','Choose an expiry of 1–365 days.')
 token=APIToken(membership=member,name=name.strip(),scopes=sorted(set(scopes)),expires_at=timezone.now()+timedelta(days=days))
 raw=f'trl_{token.pk.hex}_{secrets.token_urlsafe(32)}'
 token.secret_hash=hashlib.sha256(raw.encode()).hexdigest();token.save()
 return token,raw


def authenticate(request):
 header=request.headers.get('Authorization','')
 if not header.startswith('Bearer '):raise APIError(401,'authentication_required','Use an Authorization: Bearer header with a Trellis API token.')
 raw=header[7:]
 if len(raw)>200:raise APIError(401,'invalid_token','The API token is invalid or expired.')
 try:identifier=uuid.UUID(hex=raw.split('_')[1])
 except (ValueError,IndexError):raise APIError(401,'invalid_token','The API token is invalid or expired.')
 token=APIToken.objects.select_related('membership__user','membership__course').filter(pk=identifier).first()
 if not token or not hmac.compare_digest(token.secret_hash,hashlib.sha256(raw.encode()).hexdigest()) or token.revoked_at or token.expires_at<=timezone.now():
  raise APIError(401,'invalid_token','The API token is invalid or expired.')
 member=token.membership
 if not member.active or not member.user.is_active or member.role not in {'instructor','head_ta','ta'}:
  raise APIError(403,'access_revoked','The token owner no longer has active staff access.')
 request.api_token=token;request.api_member=member;request.api_course=member.course;request.user=member.user
 if token.last_used_at is None or token.last_used_at<timezone.now()-timedelta(minutes=5):APIToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
 return token


def error_response(request,exc):
 body={'error':{'code':exc.code,'message':exc.message},'request_id':str(request.api_request_id)}
 if exc.details is not None:body['error']['details']=exc.details
 response=JsonResponse(body,status=exc.status)
 if exc.status==401:response['WWW-Authenticate']='Bearer realm="Trellis API"'
 response['Cache-Control']='no-store';response['X-Request-ID']=str(request.api_request_id)
 return response


def endpoint(methods):
 """Method -> required scopes. No cookie authentication for data endpoints."""
 def decorate(view):
  @csrf_exempt
  @wraps(view)
  def wrapped(request,*args,**kwargs):
   request.api_request_id=uuid.uuid4()
   try:
    authenticate(request)
    if request.method not in methods:raise APIError(405,'method_not_allowed','This endpoint does not support that HTTP method.')
    required=set(methods[request.method])
    if not required<=set(request.api_token.scopes) or not required<=allowed_scopes(request.api_member):raise APIError(403,'insufficient_scope','This token does not have the required access.',{'required_scopes':sorted(required)})
    request.api_body={}
    if request.method not in {'GET','HEAD'}:
     if len(request.body)>2_500_000:raise APIError(413,'request_too_large','Request bodies must be smaller than 2.5 MB.')
     if request.body:
      if request.content_type!='application/json':raise APIError(415,'unsupported_media_type','Send application/json.')
      try:request.api_body=json.loads(request.body,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
      except (ValueError,UnicodeDecodeError):raise APIError(400,'invalid_json','Send a valid JSON object.')
      if not isinstance(request.api_body,dict):raise APIError(400,'invalid_json','Send a JSON object.')
    mutating=request.method not in {'GET','HEAD'}
    with transaction.atomic():
     replay=None
     key=request.headers.get('Idempotency-Key') if mutating else None
     if key:
      if len(key)>100:raise APIError(400,'invalid_idempotency_key','Idempotency-Key must be at most 100 characters.')
      digest=hashlib.sha256(request.method.encode()+request.path.encode()+request.body).hexdigest()
      replay,_=APIReplay.objects.get_or_create(token=request.api_token,key=key,defaults={'request_hash':digest})
      replay=APIReplay.objects.select_for_update().get(pk=replay.pk)
      if replay.request_hash!=digest:raise APIError(409,'idempotency_conflict','This key was already used for a different request.')
      if replay.response_status:
       response=JsonResponse(replay.response,status=replay.response_status)
       if replay.response_etag:response['ETag']=replay.response_etag
       response['Idempotency-Replayed']='true'
      else:response=view(request,*args,**kwargs)
     else:response=view(request,*args,**kwargs)
     if replay and not replay.response_status and response.status_code<300:
      replay.response=json.loads(response.content);replay.response_status=response.status_code;replay.response_etag=response.get('ETag','');replay.save()
     if mutating or required&{'grades:read','submissions:read','roster:read','activity:read'}:
      APIAuditEvent.objects.create(course=request.api_course,actor=request.user,token=request.api_token,request_id=request.api_request_id,
       method=request.method,path=request.path[:1000],status=response.status_code,summary=getattr(request,'api_audit',{}))
    response['Cache-Control']='no-store';response['X-Request-ID']=str(request.api_request_id)
    return response
   except APIError as exc:return error_response(request,exc)
   except Http404:return error_response(request,APIError(404,'not_found','The requested resource does not exist in this token’s course.'))
   except PermissionDenied:return error_response(request,APIError(403,'permission_denied','This action is not permitted.'))
   except ValidationError as exc:return error_response(request,APIError(400,'validation_error',' '.join(exc.messages)))
   except (ValueError,TypeError,OverflowError):return error_response(request,APIError(400,'invalid_request','Check request field types and identifiers.'))
  return wrapped
 return decorate


def course_guard(request,course_id):
 if request.api_course.pk!=course_id:raise Http404


def paginate(request,items):
 try:
  limit=int(request.GET.get('limit','100'));offset=int(request.GET.get('offset','0'))
  if not 1<=limit<=200 or offset<0:raise ValueError()
 except ValueError:raise APIError(400,'invalid_pagination','Use limit 1–200 and a nonnegative offset.')
 count=items.count() if hasattr(items,'model') else len(items)
 page=items[offset:offset+limit]
 def link(at):
  params=request.GET.copy();params['offset']=str(at);params['limit']=str(limit)
  return request.path+'?'+params.urlencode()
 return page,{'count':count,'limit':limit,'offset':offset,'next':link(offset+limit) if offset+limit<count else None,'previous':link(max(0,offset-limit)) if offset else None}


def envelope(request,items,serialize=lambda x:x):
 page,meta=paginate(request,items)
 return JsonResponse({**meta,'results':[serialize(item) for item in page]})


def ids_filter(request,key):
 raw=request.GET.get(key,'')
 if not raw:return None
 try:
  values=[int(v) for v in raw.split(',')]
  if len(values)>200 or any(v<1 for v in values):raise ValueError()
 except ValueError:raise APIError(400,'invalid_filter',f'{key} must be a comma-separated list of up to 200 positive IDs.')
 return values
