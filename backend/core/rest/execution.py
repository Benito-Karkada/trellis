import json
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ..models import ExecutionJob
from ..studio import starter_files
from .. import execution as engine
from .auth import endpoint,APIError
from .content import part_get,latest,precondition

@endpoint({'POST':['execution:write','content:read']})
def test_runs(request,part_id):
 part=part_get(request,part_id);revision=latest(part);precondition(request,revision)
 if not getattr(settings,"EXECUTION_ENABLED",True):raise APIError(503,'execution_unavailable','The isolated executor is not available.')
 body=request.api_body
 if body.get('operation','submit') not in {'run','submit'}:raise APIError(400,'invalid_operation','Use run or submit.')
 # Delegate to the same authenticated queue and file policy used by staff preview.
 request._body=json.dumps({'operation':body.get('operation','submit'),'entrypoint':body.get('entrypoint',revision.grading.get('entrypoint')),
  'files':body.get('files',starter_files(revision)),'preview':True}).encode()
 result=engine.enqueue(request,revision.pk)
 if result.status_code!=200:
  data=json.loads(result.content);raise APIError(result.status_code,'execution_rejected',data.get('error','Execution was rejected.'))
 data=json.loads(result.content);request.api_audit={'part_id':part.pk,'revision_id':revision.pk,'job_id':data['id'],'preview':True}
 return JsonResponse({**data,'part_id':part.pk,'revision_id':revision.pk,'preview':True},status=202)

@endpoint({'GET':['execution:write','content:read']})
def test_run_detail(request,job_id):
 job=get_object_or_404(ExecutionJob,pk=job_id,user=request.user,preview=True,revision__activity__lesson__course=request.api_course)
 return JsonResponse({'id':str(job.pk),'part_id':job.revision.activity_id,'revision_id':job.revision_id,'status':job.status,
  'created_at':job.created_at,'completed_at':job.completed_at,'result':job.result,'preview':True})
