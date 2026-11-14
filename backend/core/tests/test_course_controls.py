from datetime import timedelta
from unittest.mock import patch,Mock
from django.test import TestCase,override_settings
from django.utils import timezone
from core.models import ActivityProgress,Membership,Accommodation,ExecutionJob,Workspace,ActivityFile,CanvasGradeUpdate,Revision,Lesson,Activity
from core.deadlines import credit_open
from core.canvas_sync import process_one
from .test_studio import StudioTests


class CourseControlTests(TestCase):
    def setUp(self):
        StudioTests.setUp(self)
        self.course=self.activity.lesson.course
        self.member=Membership.objects.get(user=self.student)
        self.revision.grading={'maximum_points':'3','entrypoint':'main.py','definition':{'version':1,'cases':[{'id':'x','action':'stdout','expected':'1'}]},'questions':{'q':{'selection':'one','correct_choice_ids':['yes']}}}
        self.revision.save()
        self.activity.lesson.metadata={'due_at':(timezone.now()-timedelta(hours=1)).isoformat()};self.activity.lesson.save()
    def post(self,path,body):return self.client.post(path,body,content_type='application/json')
    def test_late_native_correct_and_wrong_preserve_recorded_grade_and_completion(self):
        ActivityProgress.objects.create(user=self.student,activity=self.activity,score=1,maximum=3,completed=False)
        for answer in ('yes','no'):
            response=self.post(f'/api/submit-native/{self.revision.pk}/',{'responses':{'q':[answer]}})
            self.assertEqual(response.status_code,200);self.assertTrue(response.json()['practice'])
            p=ActivityProgress.objects.get(user=self.student);self.assertEqual(p.score,1);self.assertFalse(p.completed)
    @override_settings(RUNNER_TOKEN='worker')
    def test_coding_receipt_time_not_worker_completion_decides_credit(self):
        Workspace.objects.create(user=self.student,revision=self.revision,files={'main.py':'print(1)'},generation=1)
        due=timezone.now()-timedelta(minutes=1)
        self.activity.lesson.metadata={'due_at':due.isoformat()};self.activity.lesson.save()
        for received,practice in ((due+timedelta(seconds=1),True),(due-timedelta(seconds=1),False)):
            p=ActivityProgress.objects.filter(user=self.student).first()
            if p:p.delete()
            ws=Workspace.objects.get(user=self.student);ws.generation=1;ws.save()
            job=ExecutionJob.objects.create(user=self.student,revision=self.revision,generation=1,operation='submit',snapshot=ws.files,entrypoint='main.py',status='running',lease='lease')
            ExecutionJob.objects.filter(pk=job.pk).update(created_at=received)
            r=self.client.post(f'/api/runner/complete/{job.pk}/',{'lease':'lease','result':{'score_fraction':'1','passed':True,'workspace_files':{'full_results.txt':'Details'}}},content_type='application/json',HTTP_AUTHORIZATION='Bearer worker')
            self.assertEqual(r.status_code,200)
            p=ActivityProgress.objects.get(user=self.student);self.assertEqual(p.score,0 if practice else 3)
            job.refresh_from_db();self.assertEqual(job.result['practice'],practice)
            self.assertEqual(Workspace.objects.get(user=self.student).files['full_results.txt'],'Details')
    def test_individual_deadline_override_and_exact_cutoff(self):
        now=timezone.now();Accommodation.objects.create(membership=self.member,lesson=self.activity.lesson,due_at_override=now+timedelta(hours=1))
        self.assertTrue(credit_open(self.member,self.activity,now))
        self.assertTrue(credit_open(self.member,self.activity,now+timedelta(hours=1)))
        self.assertFalse(credit_open(self.member,self.activity,now+timedelta(hours=1,seconds=1)))
    def test_ui_deadline_saves_timezone_and_students_cannot_change_it(self):
        body={'assignment_id':self.activity.lesson_id,'due_at':'2026-12-01T12:00:00-05:00','canvas_assignment_id':''}
        self.assertEqual(self.post('/api/settings/course-controls/save/',body).status_code,403)
        self.client.force_login(self.staff)
        self.assertEqual(self.post('/api/settings/course-controls/save/',body).status_code,200)
        body['due_at']='2026-12-01T12:00:00'
        self.assertEqual(self.post('/api/settings/course-controls/save/',body).status_code,400)
    def test_editing_due_date_preserves_synced_canvas_mapping(self):
        self.client.force_login(self.staff)
        lesson=self.activity.lesson
        lesson.metadata={**lesson.metadata,'canvas_assignment_id':'456'};lesson.save()
        response=self.post('/api/settings/course-controls/save/',{'assignment_id':lesson.pk,'due_at':None})
        self.assertEqual(response.status_code,200)
        lesson.refresh_from_db();self.assertEqual(lesson.metadata['canvas_assignment_id'],'456')

    def test_course_wide_review_is_batched_and_files_load_on_demand(self):
        self.client.force_login(self.staff)
        other=Lesson.objects.create(course=self.course,title='Second lesson')
        for n in range(20):
            a=Activity.objects.create(lesson=other,title=f'Part {n}');r=Revision.objects.create(activity=a,number=1,created_by=self.staff,content={'version':1,'blocks':[]});a.published_revision=r;a.save()
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            r=self.client.get(f'/api/gradebook/detail/?membership={self.member.pk}')
        self.assertEqual(r.status_code,200);self.assertEqual(len(r.json()['activities']),21);self.assertLessEqual(len(queries),6)
        Workspace.objects.create(user=self.student,revision=self.revision,files={'main.py':'student code','private.py':'never'})
        response=self.client.get(f'/api/gradebook/work/?membership={self.member.pk}&activity={self.activity.pk}')
        self.assertEqual(response.json()['files'],{'main.py':'student code'})
    @patch.dict('os.environ',{'CANVAS_API_TOKEN':'test-secret','CANVAS_BASE_URL':'https://canvas.example.invalid'})
    @patch('core.canvas_sync.requests.put')
    def test_canvas_updates_coalesce_retry_and_only_send_frozen_score(self,put):
        self.client.force_login(self.staff)
        self.course.canvas_context_id='123';self.course.save()
        lesson=self.activity.lesson;lesson.metadata={**lesson.metadata,'canvas_assignment_id':'456'};lesson.save()
        self.member.canvas_user_id='789';self.member.save()
        ActivityProgress.objects.create(user=self.student,activity=self.activity,score=1,maximum=3)
        for _ in range(2):self.assertEqual(self.client.post('/api/gradebook/sync-canvas/').status_code,200)
        self.assertEqual(CanvasGradeUpdate.objects.count(),1)
        put.return_value=Mock(status_code=429)
        self.assertTrue(process_one());job=CanvasGradeUpdate.objects.get();self.assertEqual(job.status,'retrying')
        CanvasGradeUpdate.objects.update(next_attempt_at=None);put.return_value=Mock(status_code=200)
        process_one();job.refresh_from_db();self.assertEqual(job.status,'sent')
        self.assertTrue(put.call_args.kwargs['data']['submission[posted_grade]'].startswith('33.3333'))
        self.assertNotIn('test-secret',job.last_error)
    def test_canvas_placeholder_does_not_queue_or_send(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post('/api/gradebook/sync-canvas/').status_code,409)
        self.assertFalse(CanvasGradeUpdate.objects.exists())
