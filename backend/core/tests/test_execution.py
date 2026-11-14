from django.test import TestCase, override_settings
from core.models import Workspace, ExecutionJob, ActivityProgress
from . import test_studio


@override_settings(RUNNER_TOKEN="test-worker-token")
class ExecutionTests(TestCase):
    @override_settings(EXECUTION_ENABLED=False)
    def test_disabled_execution_does_not_leave_a_pending_job(self):
        response=self.client.post(f"/api/execute/{self.revision.pk}/", {
            "operation":"run","files":{"main.py":"print(1)"},
        },content_type="application/json")
        self.assertEqual(response.status_code,503)
        self.assertEqual(ExecutionJob.objects.count(),0)

    def test_native_submission_returns_trimmed_score_and_selected_hint(self):
        rule={"selection":"one","correct_choice_ids":["yes"],"choice_feedback":{
            "yes":[{"type":"text","text":"That is why this is correct."}],
            "no":[{"type":"text","text":"Try the other approach."}]}}
        self.revision.grading={"maximum_points":"1.5","questions":{"a":rule,"b":rule,"c":rule}}
        self.revision.save()
        data=self.client.post(f"/api/submit-native/{self.revision.pk}/",{"responses":{"a":"yes","b":"no"}},content_type="application/json").json()
        self.assertEqual(data["score"],"0.5")
        self.assertEqual(data["maximum"],"1.5")
        self.assertIn("why this is correct",str(data["feedback"]["a"]))
        self.assertIn("other approach",str(data["feedback"]["b"]))
        self.assertNotIn("c",data["feedback"])

    def test_sandbox_accepts_run_but_rejects_both_submit_endpoints(self):
        self.activity.metadata={"sandbox":True}
        self.activity.save()
        body={"operation":"submit","files":{"main.py":"print(1)"}}
        self.assertEqual(self.client.post(f"/api/execute/{self.revision.pk}/",body,content_type="application/json").status_code,400)
        self.assertEqual(self.client.post(f"/api/submit-native/{self.revision.pk}/",{},content_type="application/json").status_code,400)
        body["operation"]="run"
        self.assertEqual(self.client.post(f"/api/execute/{self.revision.pk}/",body,content_type="application/json").status_code,200)

    def setUp(self):
        test_studio.StudioTests.setUp(self)
        self.revision.grading = {"definition": {}, "maximum_points": "7.5"}
        self.revision.save()
        self.workspace = Workspace.objects.create(user=self.student, revision=self.revision,
                                                  files={"main.py": "print(1)"}, generation=1)

    def test_active_job_blocks_run_submit_and_reset_without_workspace_changes(self):
        self.revision.grading['definition'] = {'cases': []}
        self.revision.save()
        for status in ('pending', 'running'):
            job = self.job()
            job.status = status
            job.save()
            before = self.workspace.files.copy()
            for operation in ('run', 'submit'):
                response = self.client.post(f'/api/execute/{self.revision.pk}/',
                    {'operation': operation, 'files': {'main.py': 'while True: pass'}}, content_type='application/json')
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()['job_id'], str(job.pk))
            response = self.client.post(f'/api/workspaces/{self.revision.pk}/',
                {'action': 'reset'}, content_type='application/json')
            self.assertEqual(response.status_code, 409)
            self.workspace.refresh_from_db()
            self.assertEqual(self.workspace.files, before)
            self.assertEqual(ExecutionJob.objects.count(), 1)
            job.delete()
        response = self.client.post(f'/api/workspaces/{self.revision.pk}/',
            {'action': 'reset'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)

    def job(self, **kwargs):
        return ExecutionJob.objects.create(user=self.student, revision=self.revision,
            generation=1, operation="submit", snapshot=self.workspace.files,
            entrypoint="main.py", status="running", lease="lease", **kwargs)

    def complete(self, job, result, token="test-worker-token"):
        return self.client.post(f"/api/runner/complete/{job.pk}/",
            {"lease": "lease", "result": result}, content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + token)

    def test_worker_authentication_and_owner_status(self):
        job = self.job()
        self.assertEqual(self.complete(job, {}, token="wrong").status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(f"/api/jobs/{job.pk}/").status_code, 404)

    def test_private_review_flags_do_not_make_an_automatic_grade_decision(self):
        job=self.job(review_signals={'version':1,'flags':[{'kind':'syntax','name':'lambda'}]})
        self.assertEqual(self.complete(job,{'score_fraction':1,'passed':True,'workspace_files':{'full_results.txt':'Passed'}}).status_code,200)
        self.assertEqual(ActivityProgress.objects.get(user=self.student).score,7.5)

    def test_submission_replaces_feedback_and_scales_points(self):
        job = self.job()
        self.assertEqual(self.complete(job, {"score_fraction": 0.5, "passed": False,
            "workspace_files": {"full_results.txt": "One test failed"}}).status_code, 200)
        self.workspace.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(self.workspace.files["full_results.txt"], "One test failed")
        self.assertEqual(job.result["score"], "3.75")
        self.assertFalse(ActivityProgress.objects.get(user=self.student).completed)

    def test_quiz_submission_never_releases_staff_sample_answer(self):
        from django.core.files.base import ContentFile
        from core.models import ActivityFile
        self.activity.lesson.metadata = {'kind': 'programming_quiz'}
        self.activity.lesson.save()
        ActivityFile.objects.create(revision=self.revision, path='solutions/sample_answer.py',
            visibility='staff', blob=ContentFile(b'print("answer")', name='sample_answer.py'))
        job = self.job()
        self.complete(job, {'score_fraction': 1, 'passed': True, 'release_samples': True,
            'workspace_files': {'full_results.txt': 'All tests passed'}})
        self.workspace.refresh_from_db()
        self.assertNotIn('sample_answer.py', self.workspace.files)

    def test_regular_coding_submission_releases_sample_into_workspace(self):
        from django.core.files.base import ContentFile
        from core.models import ActivityFile
        ActivityFile.objects.create(revision=self.revision, path='solutions/sample_answer.py',
            visibility='staff', blob=ContentFile(b'print("answer")', name='sample_answer.py'))
        job = self.job()
        self.complete(job, {'score_fraction': 1, 'passed': True, 'release_samples': True,
            'workspace_files': {'full_results.txt': 'All tests passed'}})
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.files['sample_answer.py'], 'print("answer")')

    def test_reset_prevents_late_result_overwrite(self):
        job = self.job()
        self.workspace.generation = 2
        self.workspace.save()
        self.complete(job, {"score_fraction": 1, "passed": True,
                           "workspace_files": {"full_results.txt": "Late result"}})
        self.workspace.refresh_from_db()
        job.refresh_from_db()
        self.assertTrue(job.result["stale"])
        self.assertEqual(self.workspace.files, {"main.py": "print(1)"})
        self.assertFalse(ActivityProgress.objects.exists())

    def test_preview_reports_points_without_changing_workspace_or_progress(self):
        job = self.job(preview=True)
        self.complete(job, {"score_fraction": 1, "passed": True,
                           "workspace_files": {"full_results.txt": "Preview"}})
        job.refresh_from_db()
        self.workspace.refresh_from_db()
        self.assertEqual(job.result["score"], "7.5")
        self.assertEqual(self.workspace.files, {"main.py": "print(1)"})
        self.assertFalse(ActivityProgress.objects.exists())

    def test_run_never_records_grades(self):
        job = self.job()
        job.operation = "run"
        job.save()
        self.complete(job, {"stdout": "hello"})
        self.assertFalse(ActivityProgress.objects.exists())

    def test_execution_rejects_student_file_creation(self):
        response = self.client.post(f"/api/execute/{self.revision.pk}/",
            {"operation": "run", "entrypoint": "main.py",
             "files": {"main.py": "print(1)", "new.py": ""}}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_feedback_file_is_read_only_before_and_after_grading(self):
        self.revision.grading['definition']={'cases': []}
        self.revision.save()
        from django.core.files.base import ContentFile
        from core.models import ActivityFile
        from core.workspace_files import RESULTS_PLACEHOLDER
        ActivityFile.objects.create(revision=self.revision, path='full_results.txt', visibility='student',
            blob=ContentFile(b'', name='full_results.txt'))
        self.workspace.files['full_results.txt']=''
        self.workspace.save()
        data=self.client.get(f'/api/studio/{self.activity.pk}/').json()
        self.assertEqual(data['workspace']['full_results.txt'],RESULTS_PLACEHOLDER)
        for operation in ('save','run','submit'):
            files={**data['workspace'],'full_results.txt':'Student wrote fake results'}
            url=f'/api/workspaces/{self.revision.pk}/' if operation=='save' else f'/api/execute/{self.revision.pk}/'
            response=self.client.post(url,{'operation':operation,'files':files},content_type='application/json')
            self.assertEqual(response.status_code,403)
        self.assertEqual(ExecutionJob.objects.count(),0)
        job=self.job()
        self.assertEqual(self.complete(job,{'score_fraction':1,'passed':True,
            'workspace_files':{'full_results.txt':'All tests passed'}}).status_code,200)
        data=self.client.get(f'/api/studio/{self.activity.pk}/').json()
        self.assertEqual(data['workspace']['full_results.txt'],'All tests passed')
        for operation in ('save','run','submit'):
            url=f'/api/workspaces/{self.revision.pk}/' if operation=='save' else f'/api/execute/{self.revision.pk}/'
            response=self.client.post(url,{'operation':operation,'files':{**data['workspace'],'full_results.txt':'Altered'}},content_type='application/json')
            self.assertEqual(response.status_code,403)
        files={**data['workspace'],'main.py':'print(2)'}
        self.assertEqual(self.client.post(f'/api/workspaces/{self.revision.pk}/',{'files':files},content_type='application/json').status_code,200)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.files['full_results.txt'],'All tests passed')
        self.assertEqual(self.workspace.files['main.py'],'print(2)')
        response=self.client.post(f'/api/execute/{self.revision.pk}/',{'operation':'submit','files':files},content_type='application/json')
        self.assertEqual(response.status_code,200)
        reset=self.client.post(f'/api/workspaces/{self.revision.pk}/',{'action':'reset'},content_type='application/json')
        self.assertEqual(reset.status_code,409)
        ExecutionJob.objects.filter(status='pending').update(status='completed')
        reset=self.client.post(f'/api/workspaces/{self.revision.pk}/',{'action':'reset'},content_type='application/json')
        self.assertEqual(reset.json()['workspace']['full_results.txt'],RESULTS_PLACEHOLDER)

    def test_preview_can_submit_repeatedly_without_saving_feedback_edits(self):
        self.revision.grading['definition']={'cases': []}
        self.revision.save()
        from django.core.files.base import ContentFile
        from core.models import ActivityFile
        from core.workspace_files import RESULTS_PLACEHOLDER
        ActivityFile.objects.create(revision=self.revision,path='full_results.txt',visibility='student',
            blob=ContentFile(b'',name='full_results.txt'))
        self.client.force_login(self.staff)
        response=self.client.post(f'/api/execute/{self.revision.pk}/',{'preview':True,'operation':'submit',
            'files':{'main.py':'print(1)','full_results.txt':'Results from the previous preview'}},content_type='application/json')
        self.assertEqual(response.status_code,200)
        job=ExecutionJob.objects.get(pk=response.json()['id'])
        self.assertEqual(job.snapshot['full_results.txt'],RESULTS_PLACEHOLDER)
        self.assertFalse(Workspace.objects.filter(user=self.staff).exists())
