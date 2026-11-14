import json
from datetime import timedelta
from django.test import TestCase,Client
from django.utils import timezone
from django.core.files.base import ContentFile
from core.models import Course,Membership,Lesson,Activity,Revision,ActivityFile,ActivityProgress,Workspace,Submission,APIToken,APIAuditEvent,APIReplay,AssignmentVisit,LearningEvent,ExecutionJob
from core.rest.auth import issue_token,SCOPES
from . import test_studio

class RestAPITests(TestCase):
 def setUp(self):
  test_studio.StudioTests.setUp(self)
  self.course=self.activity.lesson.course;self.member=Membership.objects.get(user=self.staff)
  self.token,self.secret=issue_token(self.member,'Tests',list(SCOPES))
  self.headers={'HTTP_AUTHORIZATION':'Bearer '+self.secret}
 def api(self,method,path,body=None,base=None,key=None,**headers):
  if base is not None:headers['HTTP_IF_MATCH']=f'"{base}"'
  if key is not None:headers['HTTP_IDEMPOTENCY_KEY']=key
  return getattr(self.client,method)('/api/v1'+path,data=json.dumps(body or {}),content_type='application/json',**self.headers,**headers) if method!='get' else self.client.get('/api/v1'+path,**self.headers,**headers)
 def test_bearer_required_scoped_course_and_revocation(self):
  self.assertEqual(self.client.get('/api/v1/courses/').status_code,401)
  response=self.api('get','/courses/');self.assertEqual(response.status_code,200);self.assertEqual(response.json()['results'][0]['id'],self.course.pk)
  self.assertNotIn(self.secret,self.token.secret_hash)
  other=Course.objects.create(title='Other',term='Other');lesson=Lesson.objects.create(course=other,title='Secret')
  self.assertEqual(self.api('get',f'/assignments/{lesson.pk}/').status_code,404)
  self.token.revoked_at=timezone.now();self.token.save()
  self.assertEqual(self.api('get','/courses/').status_code,401)
 def test_scopes_follow_current_role_and_active_enrollment(self):
  token,secret=issue_token(self.member,'Read grades',['grades:read']);self.headers={'HTTP_AUTHORIZATION':'Bearer '+secret}
  self.assertEqual(self.api('get',f'/parts/{self.activity.pk}/').status_code,403)
  self.headers={'HTTP_AUTHORIZATION':'Bearer '+self.secret}
  Membership.objects.filter(pk=self.member.pk).update(role='ta')
  self.assertEqual(self.api('post',f'/courses/{self.course.pk}/enrollments/',{'email':'new@example.invalid'}).status_code,403)
  Membership.objects.filter(pk=self.member.pk).update(active=False)
  self.assertEqual(self.api('get','/courses/').status_code,403)
 def test_writes_are_drafts_have_preconditions_and_preserve_versions(self):
  url=f'/parts/{self.activity.pk}/'
  self.assertEqual(self.api('patch',url,{'title':'Changed'}).status_code,428)
  self.assertEqual(self.api('patch',url,{'title':'Changed'},base=999999).status_code,412)
  r=self.api('patch',url,{'content':{'version':1,'blocks':[{'id':'text','type':'paragraph','content':[{'type':'text','text':'Updated instructions'}]}]}},base=self.revision.pk)
  self.assertEqual(r.status_code,200);new=r.json()['revision_id'];self.assertNotEqual(new,self.revision.pk)
  self.activity.refresh_from_db();self.assertEqual(self.activity.published_revision_id,self.revision.pk)
  self.assertEqual(self.api('post',f'/parts/{self.activity.pk}/publish/',{},base=new).status_code,200)
  self.activity.refresh_from_db();self.assertEqual(self.activity.published_revision_id,new)
  self.assertNotIn('Updated instructions',str(self.revision.content))
 def test_file_upsert_private_paths_binary_and_partial_patch_preserve_files(self):
  url=f'/parts/{self.activity.pk}/files/grader/test.txt'
  r=self.api('put',url,{'text':'secret tests','visibility':'grader'},base=self.revision.pk)
  self.assertEqual(r.status_code,200);new=r.json()['revision_id']
  self.assertEqual(self.api('get',url).json()['text'],'secret tests')
  self.assertEqual(Revision.objects.get(pk=new).files.count(),3)
  self.assertEqual(self.api('put',url,{'text':'leak','visibility':'student'},base=new).status_code,400)
  self.assertEqual(self.api('get',f'/parts/{self.activity.pk}/').json()['revision_id'],new)
  r=self.api('put',f'/parts/{self.activity.pk}/files/diagram.bin',{'content_base64':'AP8=','visibility':'student'},base=new)
  self.assertEqual(r.status_code,200);self.assertEqual(self.api('get',f'/parts/{self.activity.pk}/files/diagram.bin').json()['content_base64'],'AP8=')
 def test_idempotent_create_replays_and_conflicting_body_is_rejected(self):
  path=f'/courses/{self.course.pk}/assignments/'
  r=self.api('post',path,{'title':'New'},key='create-once');self.assertEqual(r.status_code,201)
  replay=self.api('post',path,{'title':'New'},key='create-once');self.assertEqual(replay.status_code,201);self.assertEqual(replay.json()['id'],r.json()['id']);self.assertEqual(replay['Idempotency-Replayed'],'true')
  self.assertEqual(self.course.lesson_set.filter(title='New').count(),1)
  self.assertEqual(self.api('post',path,{'title':'Different'},key='create-once').status_code,409)
 def test_grader_report_upload_private_manifest_publish_and_test_queue(self):
  self.activity.metadata={'kind':'coding','vocareum_part_id':'5591032'};self.activity.save()
  self.revision.grading={'maximum_points':'3','entrypoint':'main.py','review_required':True};self.revision.save()
  report=f'/courses/{self.course.pk}/reports/missing-graders/'
  self.assertEqual(self.api('get',report).json()['count'],1)
  definition={'version':1,'cases':[{'id':'output','label':'Output','action':'stdout','expected':'1\n'}]}
  r=self.api('put',f'/parts/{self.activity.pk}/grader/',{'definition':definition,'mark_reviewed':True},base=self.revision.pk)
  self.assertEqual(r.status_code,200);new=r.json()['revision_id']
  manifest=Revision.objects.get(pk=new).files.get(path='grader/tests.json');self.assertEqual(manifest.visibility,'grader')
  r=self.api('post',f'/parts/{self.activity.pk}/test-runs/',{},base=new)
  self.assertEqual(r.status_code,202);job=ExecutionJob.objects.get(pk=r.json()['id']);self.assertTrue(job.preview)
  self.assertFalse(Workspace.objects.filter(user=self.staff).exists())
  self.assertEqual(self.api('post',f'/parts/{self.activity.pk}/publish/',{},base=new).status_code,200)
  self.assertEqual(self.api('get',report).json()['count'],0)
 def test_add_drop_restore_enrollment_preserves_history(self):
  path=f'/courses/{self.course.pk}/enrollments/'
  r=self.api('post',path,{'email':'new@example.invalid','name':'New Person','external_ids':{'gtid':'provided-id'}})
  self.assertEqual(r.status_code,201);mid=r.json()['id'];member=Membership.objects.get(pk=mid)
  self.assertFalse(member.user.has_usable_password())
  Submission.objects.create(revision=self.revision,membership=member,response={})
  self.assertEqual(self.api('delete',f'/enrollments/{mid}/').status_code,200)
  member.refresh_from_db();self.assertFalse(member.active);self.assertTrue(Submission.objects.filter(membership=member).exists())
  self.assertEqual(self.api('patch',f'/enrollments/{mid}/',{'active':True}).status_code,200)
 def test_grade_filters_submission_times_and_workspace_privacy(self):
  student=Membership.objects.get(user=self.student)
  ActivityProgress.objects.create(user=self.student,activity=self.activity,score='0.5')
  self.revision.grading={'maximum_points':'1.5','questions':{'q':{}}};self.revision.save()
  r=self.api('get',f'/courses/{self.course.pk}/grades/?assignment_ids={self.activity.lesson_id}&enrollment_ids={student.pk}')
  self.assertEqual(r.status_code,200);row=r.json()['results'][0];self.assertEqual(row['earned'],'0.5');self.assertEqual(row['maximum'],'1.5');self.assertIsNone(row['first_opened_at'])
  received=timezone.now()-timedelta(minutes=3)
  Submission.objects.create(membership=student,revision=self.revision,response={'q':'answer'},received_at=received)
  r=self.api('get',f'/courses/{self.course.pk}/submissions/?enrollment_ids={student.pk}')
  self.assertEqual(r.status_code,200);self.assertIn('submitted_at',r.json()['results'][0])
  Workspace.objects.create(user=self.student,revision=self.revision,files={'main.py':'student work','private/Ferb.py':'never expose'})
  r=self.api('get',f'/enrollments/{student.pk}/workspaces/{self.activity.pk}/');self.assertEqual(r.json()['files'],{'main.py':'student work'})
 def test_first_open_and_part_events_are_exact_and_do_not_record_staff_preview(self):
  self.assertFalse(AssignmentVisit.objects.exists())
  r=self.client.post(f'/api/assignments/{self.activity.lesson_id}/open/');self.assertEqual(r.status_code,200)
  first=AssignmentVisit.objects.get().first_opened_at
  self.client.post(f'/api/assignments/{self.activity.lesson_id}/open/')
  self.client.post(f'/api/viewed/{self.activity.pk}/')
  visit=AssignmentVisit.objects.get();self.assertEqual(visit.first_opened_at,first);self.assertEqual(visit.open_count,2)
  self.assertTrue(LearningEvent.objects.filter(kind='part_opened').exists())
  self.client.force_login(self.staff);self.client.post(f'/api/assignments/{self.activity.lesson_id}/open/')
  self.assertEqual(AssignmentVisit.objects.count(),1)
  r=self.api('get',f'/courses/{self.course.pk}/visits/');self.assertEqual(r.json()['results'][0]['open_count'],2)
 def test_publish_new_files_preserves_edits_and_updates_untouched_starter_code(self):
  Workspace.objects.create(user=self.student,revision=self.revision,files={'main.py':'student edits'})
  r=self.api('patch',f'/parts/{self.activity.pk}/',{'files':[{'path':'main.py','text':'updated baseline','visibility':'student'},{'path':'extra.py','text':'new public file','visibility':'student'}]},base=self.revision.pk)
  self.assertEqual(r.status_code,200);new=r.json()['revision_id']
  self.api('post',f'/parts/{self.activity.pk}/publish/',{},base=new)
  data=self.client.get(f'/api/studio/{self.activity.pk}/').json()
  self.assertEqual(data['workspace'],{'main.py':'student edits','extra.py':'new public file'})
 def test_session_token_management_docs_and_csrf_bearer_boundary(self):
  self.client.force_login(self.staff)
  r=self.client.post('/api/settings/api-tokens/',{'name':'Read-only','scopes':['content:read'],'expires_in_days':1},content_type='application/json')
  self.assertEqual(r.status_code,201);raw=r.json()['token'];tid=r.json()['id']
  self.assertEqual(r['Cache-Control'],'no-store');self.assertNotIn(raw,str(self.client.get('/api/settings/api-tokens/').json()))
  self.assertEqual(self.client.get('/api/v1/docs/').status_code,200)
  spec=json.loads(b''.join(self.client.get('/api/v1/openapi.json').streaming_content));self.assertEqual(spec['openapi'],'3.1.0');self.assertIn('/parts/{part_id}/grader/',spec['paths'])
  self.client.post(f'/api/settings/api-tokens/{tid}/revoke/',{})
  self.assertEqual(self.client.get('/api/v1/courses/',HTTP_AUTHORIZATION='Bearer '+raw).status_code,401)
  csrf=Client(enforce_csrf_checks=True)
  response=csrf.post(f'/api/v1/courses/{self.course.pk}/assignments/',json.dumps({'title':'Bearer POST'}),content_type='application/json',**self.headers)
  self.assertEqual(response.status_code,201)
 def test_invalid_types_and_private_data_are_not_written_to_audit(self):
  self.assertEqual(self.api('post',f'/courses/{self.course.pk}/assignments/',{'title':{'bad':True}}).status_code,400)
  response=self.api('get','/courses/?limit=201');self.assertEqual(response.status_code,400);self.assertEqual(response.json()['error']['code'],'invalid_pagination')
  self.api('get',f'/courses/{self.course.pk}/grades/')
  self.assertNotIn(self.secret,str(list(APIAuditEvent.objects.values('summary'))))

 def test_batch_titles_are_atomic_scoped_and_do_not_touch_content_or_files(self):
  other=Activity.objects.create(lesson=self.activity.lesson,title='Second')
  path=f'/courses/{self.course.pk}/parts/titles/'
  before=self.activity.title;count=Revision.objects.count()
  updates=[{'id':self.activity.pk,'title':'Updated one','expected_title':before},{'id':other.pk,'title':'Updated two','expected_title':'stale'}]
  self.assertEqual(self.api('patch',path,{'updates':updates}).status_code,409)
  self.activity.refresh_from_db();self.assertEqual(self.activity.title,before)
  updates[1]['expected_title']='Second'
  result=self.api('patch',path,{'updates':updates},key='rename-titles-once')
  self.assertEqual(result.status_code,200);self.assertEqual(result.json()['updated'],2)
  self.assertEqual(self.api('patch',path,{'updates':updates},key='rename-titles-once')['Idempotency-Replayed'],'true')
  self.assertEqual(Revision.objects.count(),count);self.activity.refresh_from_db();self.assertEqual(self.activity.published_revision_id,self.revision.pk)
  self.assertEqual(self.api('patch',path,{'updates':[{'id':other.pk,'title':'No expected'}]}).status_code,400)
  other_course=Course.objects.create(title='Other',term='Other');foreign=Activity.objects.create(lesson=Lesson.objects.create(course=other_course,title='Other'),title='Hidden')
  self.assertEqual(self.api('patch',path,{'updates':[{'id':foreign.pk,'title':'No','expected_title':'Hidden'}]}).status_code,404)

from django.test import SimpleTestCase

class NativeDefinitionContractTests(SimpleTestCase):
 def test_extended_definitions_have_matching_api_and_worker_validation(self):
  from core.rest.content import validate_definition
  import sys
  from pathlib import Path
  sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'runner'))
  from grading.manifest import load_definition
  for action in ('trace','function_file','function_stdout','recursion','module_outcome'):
   case={'id':'test','label':'Test','action':action,'target':'check','expected':True}
   if action=='module_outcome':case['expected']={'exception':None,'message':None,'stdout':'hello'}
   if action=='trace':case.update(steps=[{'op':'exists_class','target':'Thing'}],expected=[True])
   if action=='function_stdout':case.update(expected='hello',strip_output=True,comparison='whitespace',clock='2030-01-02T03:04:05')
   definition={'version':1,'cases':[case],'requirements':[{'id':'count','kind':'max_node_count','target':'For:1','message':'Use the supplied loop.'}]}
   self.assertEqual(validate_definition(definition),definition);load_definition(definition)
 def test_malformed_public_observations_are_rejected(self):
  from core.rest.content import validate_definition
  from core.rest.auth import APIError
  for fields in ({'steps':[{'op':'exec','target':'x'}]}, {'clock':'not-a-date'}, {'comparison':'eval'}):
   case={'id':'test','label':'Test','action':'trace','target':'check','steps':[{'op':'read','target':'x'}],'expected':[1],**fields}
   with self.assertRaises(APIError):validate_definition({'version':1,'cases':[case]})

 def test_nested_conditional_requirement_is_supported_in_grader_api(self):
  from core.rest.content import validate_definition
  definition={'version':1,'cases':[{'id':'output','label':'Output','action':'stdout','expected':''}],
   'requirements':[{'id':'nested','kind':'require_nested_if','target':'If','message':'Use nested conditionals.'}]}
  self.assertEqual(validate_definition(definition),definition)
