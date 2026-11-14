from copy import deepcopy
from datetime import timedelta
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase,TestCase
from django.utils import timezone
from core.code_review import analyze,DEFAULT_POLICY
from core.submission_review import metrics
from core.models import AssignmentVisit,Membership,ExecutionJob,LearningEvent,StudentReview,ActivityProgress,APIAuditEvent
from core.course_settings import enroll
from .test_studio import StudioTests


class CodeReviewTests(SimpleTestCase):
 def test_supplied_imports_and_math_are_exempt_but_added_imports_are_observed(self):
  source='import datetime\nimport math\nimport numpy\n'
  d=analyze({'main.py':source},{'main.py':'import datetime\n'},DEFAULT_POLICY)
  self.assertEqual([f['name'] for f in d['flags']],['numpy'])
 def test_only_actual_syntax_and_calls_are_observed(self):
  d=analyze({'x.py':'# lambda\ntext="eval(x)"\nf=lambda x:x\neval("1")\n'}, {}, DEFAULT_POLICY)
  self.assertEqual({f['name'] for f in d['flags']},{'lambda','eval'})
 def test_provided_syntax_and_released_samples_are_exempt(self):
  d=analyze({'x.py':'f=lambda x:x\n','sample_answer_1.py':'import os\n'},{'x.py':'f=lambda x:x\n'},DEFAULT_POLICY)
  self.assertEqual(d['flags'],[]);self.assertEqual(d['files_total'],1)
 def test_invalid_python_is_an_unparsed_observation_not_a_server_error(self):
  d=analyze({'x.py':'x = ('},{},DEFAULT_POLICY)
  self.assertEqual(d['files_parsed'],0);self.assertEqual(d['flags'],[])
 def test_digest_tracks_edits_without_recording_full_source_in_the_report(self):
  a=analyze({'x.py':'print(1)'},{},DEFAULT_POLICY);b=analyze({'x.py':'print(2)'},{},DEFAULT_POLICY)
  self.assertNotEqual(a['digest'],b['digest']);self.assertNotIn('print(1)',str(a))


class MetricTests(SimpleTestCase):
 def test_gap_index_uses_latest_timestamp_per_exercise_not_repeated_attempts(self):
  now=timezone.now();subs=[{'revision__activity_id':p,'received_at':now+timedelta(seconds=s),'created_at':now} for p,s in [(1,0),(1,60),(2,240)]]
  d=metrics([],subs,[],DEFAULT_POLICY)
  self.assertEqual(d['gap_count'],1);self.assertEqual(d['legacy_gap_index'],0.5)
 def test_no_data_and_identical_timestamps_do_not_create_false_evidence(self):
  self.assertIsNone(metrics([],[],[],DEFAULT_POLICY)['index'])
  now=timezone.now();subs=[{'revision__activity_id':p,'received_at':now,'created_at':now} for p in (1,2)]
  self.assertIsNone(metrics([],subs,[],DEFAULT_POLICY)['legacy_gap_index'])
 def test_window_blur_and_hidden_events_count_as_one_episode(self):
  focus=[{'metadata':{'episode_id':'one','state':state,'reason':'window','elapsed_ms':ms}} for state,ms in [('away',0),('hidden',10),('back',3000)]]
  d=metrics([],[],focus,DEFAULT_POLICY)
  self.assertEqual(d['focus_changes'],1);self.assertEqual(d['tab_hidden'],1);self.assertEqual(d['window_only'],0);self.assertEqual(d['recorded_away_seconds'],3)
 def test_first_pass_and_debugging_are_observations_not_authorship_claims(self):
  now=timezone.now();jobs=[]
  for i in range(3):
   jobs.append({'id':uuid4(),'user_id':1,'revision__activity_id':i,'created_at':now+timedelta(seconds=i*60),'operation':'submit','status':'completed','review_signals':{'version':1,'digest':str(i),'files_parsed':1,'files_total':1,'flags':[]},'result__passed':True,'result__execution_status':None,'result__error':None,'result__stale':None})
  d=metrics(jobs,[],[],DEFAULT_POLICY)
  self.assertEqual(d['first_pass_without_run'],3);self.assertEqual(d['first_pass_eligible'],3);self.assertEqual(d['components']['first_pass']['contribution'],20)


class ReviewAccessTests(TestCase):
 def setUp(self):
  StudioTests.setUp(self);self.member=Membership.objects.get(user=self.student);self.lesson=self.activity.lesson
 def test_review_baselines_exclude_private_files_and_non_python_data(self):
  from core.code_review import provided_python
  self.assertEqual(provided_python(self.revision),{'main.py':'print(1)'})
 def test_code_observations_do_not_block_run_or_leak_to_student(self):
  url=f'/api/execute/{self.revision.pk}/'
  r=self.client.post(url,{'operation':'run','files':{'main.py':'import os\nf=lambda x:x\n'}},content_type='application/json')
  self.assertEqual(r.status_code,200);job=ExecutionJob.objects.get(pk=r.json()['id']);self.assertTrue(job.review_signals['flags'])
  data=self.client.get(f'/api/jobs/{job.pk}/').json();self.assertNotIn('review_signals',data);self.assertNotIn('lambda',str(data))
 def test_private_report_and_notes_require_staff_not_student_view(self):
  self.assertEqual(self.client.get('/api/settings/submission-review/').status_code,403)
  self.client.force_login(self.staff);d=self.client.get('/api/settings/submission-review/').json()
  self.assertEqual(d['results'][0]['membership_id'],self.member.pk)
  r=self.client.post(f'/api/settings/submission-review/{self.member.pk}/',{'status':'reviewed','notes':'Discussed in office hours.'},content_type='application/json');self.assertEqual(r.status_code,200)
  self.assertEqual(StudentReview.objects.get().notes,'Discussed in office hours.')
  session=self.client.session;session['student_view_course']=self.member.course_id;session.save()
  self.assertEqual(self.client.get('/api/settings/submission-review/').status_code,403)
 def test_report_uses_private_job_observations_without_exposing_source(self):
  job=ExecutionJob.objects.create(user=self.student,revision=self.revision,generation=0,operation='submit',status='completed',snapshot={'main.py':'f=lambda x:x'},entrypoint='main.py',review_signals=analyze({'main.py':'f=lambda x:x'},{},DEFAULT_POLICY),result={'passed':True})
  self.client.force_login(self.staff);r=self.client.get('/api/settings/submission-review/');self.assertEqual(r.status_code,200)
  row=r.json()['results'][0];self.assertEqual(row['flagged_parts'],1);self.assertEqual(row['code_flags'][0]['job_id'],str(job.pk));self.assertNotIn('snapshot',row);self.assertEqual(row['index'],35)
  from core.rest.auth import issue_token
  token,raw=issue_token(Membership.objects.get(user=self.staff),'review',['activity:read'])
  url=f'/api/v1/courses/{self.member.course_id}/reports/submission-review/'
  self.assertEqual(self.client.get(url,HTTP_AUTHORIZATION='Bearer '+raw).status_code,403)
  token.scopes=['activity:read','submissions:read'];token.save()
  self.assertEqual(self.client.get(url,HTTP_AUTHORIZATION='Bearer '+raw).status_code,200)
 def test_recorded_attempt_is_staff_only_and_does_not_include_other_courses(self):
  job=ExecutionJob.objects.create(user=self.student,revision=self.revision,generation=0,operation='submit',snapshot={'main.py':'print(7)'},entrypoint='main.py')
  url=f'/api/settings/submission-review/attempts/{job.pk}/'
  self.assertEqual(self.client.get(url).status_code,403)
  self.client.force_login(self.staff);self.assertEqual(self.client.get(url).json()['files'],{'main.py':'print(7)'})
  session=self.client.session;session['student_view_course']=self.member.course_id;session.save()
  self.assertEqual(self.client.get(url).status_code,403)
 def test_only_instructor_can_configure_and_values_are_bounded(self):
  self.client.force_login(self.staff);bad={**DEFAULT_POLICY,'tau_seconds':0}
  self.assertEqual(self.client.post('/api/settings/submission-review/policy/',bad,content_type='application/json').status_code,400)
  self.assertEqual(self.client.post('/api/settings/submission-review/policy/',DEFAULT_POLICY,content_type='application/json').status_code,200)
  Membership.objects.filter(user=self.staff).update(role='ta')
  self.assertEqual(self.client.post('/api/settings/submission-review/policy/',DEFAULT_POLICY,content_type='application/json').status_code,403)
 def test_focus_is_deduplicated_and_does_not_store_destinations(self):
  AssignmentVisit.objects.create(membership=self.member,assignment=self.lesson,last_opened_at=timezone.now())
  data={'event_id':str(uuid4()),'episode_id':str(uuid4()),'tab_id':str(uuid4()),'state':'away','reason':'tab','part_id':self.activity.pk,'url':'not-stored'}
  url=f'/api/assignments/{self.lesson.pk}/focus/'
  self.assertTrue(self.client.post(url,data,content_type='application/json').json()['recorded'])
  self.assertFalse(self.client.post(url,data,content_type='application/json').json()['recorded'])
  event=LearningEvent.objects.get(kind='focus_changed');self.assertNotIn('url',event.metadata)
  self.assertEqual(self.client.post(url,{**data,'event_id':str(uuid4()),'elapsed_ms':-1},content_type='application/json').status_code,400)
  self.client.force_login(self.staff);self.assertFalse(self.client.post(url,{**data,'event_id':str(uuid4())},content_type='application/json').json()['recorded'])
 def test_enrollment_removal_supports_all_target_roles_and_preserves_records(self):
  self.student.username='student@example.test';self.student.email='student@example.test';self.student.save()
  ActivityProgress.objects.create(user=self.student,activity=self.activity,score=2,maximum=3)
  self.client.force_login(self.staff)
  for role in ('student','ta','instructor'):
   target=self.member if role=='student' else enroll(self.member.course,f'{role}@example.test',role)[0]
   r=self.client.post(f'/api/settings/enrollments/{target.pk}/remove/',{},content_type='application/json');self.assertEqual(r.status_code,200)
   target.refresh_from_db();self.assertFalse(target.active)
  self.assertEqual(ActivityProgress.objects.get().score,2);self.assertEqual(APIAuditEvent.objects.count(),3)
  restored,_=enroll(self.member.course,self.student.username,'student');self.assertEqual(restored.pk,self.member.pk);self.assertTrue(restored.active)
  me=Membership.objects.get(user=self.staff);self.assertEqual(self.client.post(f'/api/settings/enrollments/{me.pk}/remove/',{},content_type='application/json').status_code,400)
