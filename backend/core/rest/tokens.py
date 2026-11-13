from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ..course_settings import staff_course
from ..studio import json_body,require_authoring_access
from ..models import Membership,APIToken,APIAuditEvent
import uuid
from .auth import APIError,issue_token,allowed_scopes,SCOPES,READ_SCOPES


def serialize(token):
 return {'id':str(token.pk),'name':token.name,'course_id':token.membership.course_id,'owner':token.membership.user.email or token.membership.user.username,
  'scopes':token.scopes,'created_at':token.created_at,'expires_at':token.expires_at,'last_used_at':token.last_used_at,'revoked_at':token.revoked_at}


def settings_tokens(request,token_id=None):
 course=staff_course(request);require_authoring_access(request,course)
 member=Membership.objects.get(course=course,user=request.user,active=True)
 if request.method=='GET' and token_id is None:
  query=APIToken.objects.filter(membership__course=course).select_related('membership__user')
  if member.role!='instructor':query=query.filter(membership=member)
  return JsonResponse({'course_id':course.pk,'tokens':[serialize(t) for t in query.order_by('-created_at')],
   'scopes':{s:SCOPES[s] for s in SCOPES if s in allowed_scopes(member)},'default_scopes':READ_SCOPES})
 if request.method=='POST' and token_id is None:
  try:
   import json
   body=json.loads(request.body)
   if not isinstance(body,dict):raise ValueError()
   token,raw=issue_token(member,body.get('name'),body.get('scopes'),body.get('expires_in_days',30))
  except (ValueError,UnicodeDecodeError):return JsonResponse({'error':'Send a valid token request.'},status=400)
  except APIError as exc:return JsonResponse({'error':exc.message},status=exc.status)
  APIAuditEvent.objects.create(course=course,actor=request.user,request_id=uuid.uuid4(),method='POST',path=request.path,status=201,summary={'action':'token_created','token_id':str(token.pk),'scopes':token.scopes})
  response=JsonResponse({**serialize(token),'token':raw},status=201);response['Cache-Control']='no-store';return response
 if request.method=='POST' and token_id is not None:
  query=APIToken.objects.filter(membership__course=course)
  if member.role!='instructor':query=query.filter(membership=member)
  token=get_object_or_404(query,pk=token_id);token.revoked_at=timezone.now();token.save(update_fields=['revoked_at'])
  APIAuditEvent.objects.create(course=course,actor=request.user,request_id=uuid.uuid4(),method='POST',path=request.path,status=200,summary={'action':'token_revoked','token_id':str(token.pk)})
  return JsonResponse({'id':str(token.pk),'revoked':True})
 return JsonResponse({'error':'Method not allowed.'},status=405)
