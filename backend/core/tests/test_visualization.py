from datetime import timedelta
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.utils import timezone
from core.models import ActivityFile, ActivityProgress, ExecutionJob, Membership, QuizAttempt, VisualizationJob, Workspace, Submission
from . import test_studio


@override_settings(RUNNER_TOKEN="visualizer-test")
class VisualizationTests(TestCase):
    def setUp(self):
        test_studio.StudioTests.setUp(self)
        self.sample = ActivityFile.objects.create(revision=self.revision, path="solutions/sample_answer.py", visibility="staff",
            blob=ContentFile(b"answer = 42\nprint(answer)", name="sample.py"))

    def post(self, body):
        return self.client.post("/api/visualizations/", body, content_type="application/json")

    def solved(self, **overrides):
        fields = dict(user=self.student, revision=self.revision, generation=1, operation="submit", snapshot={"main.py":"print(42)"},
            entrypoint="main.py", status="completed", result={"passed": True, "score_fraction": "1"})
        fields.update(overrides)
        return ExecutionJob.objects.create(**fields)

    def sample_url(self):
        return f"/api/visualizations/samples/{self.activity.pk}/"

    def test_home_trace_requires_login_and_enrollment_and_validates_limits(self):
        self.client.logout()
        self.assertEqual(self.post({"source":"print(1)"}).status_code,403)
        self.client.force_login(self.student)
        for body in ({"source":""},{"source":17},{"source":"x"*12001},{"source":"pass\n"*301},
                     {"source":"print(1)","stdin":{}},{"source":"print(1)","activity":"bad"}):
            self.assertEqual(self.post(body).status_code,400)
        Membership.objects.filter(user=self.student).update(active=False)
        self.assertEqual(self.post({"source":"print(1)"}).status_code,403)
        self.assertFalse(VisualizationJob.objects.exists())

    def test_sample_is_locked_until_correct_submit_and_never_unlocks_for_run_or_preview(self):
        self.assertEqual(self.client.get(self.sample_url()).status_code,403)
        for options in ({"operation":"run"},{"preview":True},{"result":{"passed":False,"score_fraction":1}},
                        {"result":{"passed":True,"score_fraction":"0.5"}}):
            self.solved(**options)
            self.assertEqual(self.client.get(self.sample_url()).status_code,403)
        self.solved()
        data=self.client.get(self.sample_url()).json()
        self.assertEqual(data["samples"][0]["source"],"answer = 42\nprint(answer)")
        self.assertNotIn("secret tests",str(data))
        self.assertTrue(self.client.get(f"/api/studio/{self.activity.pk}/").json()["visualization_available"])

    def test_quiz_samples_never_available_even_when_solved_or_staff(self):
        lesson=self.activity.lesson;lesson.metadata={"kind":"programming_quiz"};lesson.save()
        self.solved()
        for user in (self.student,self.staff):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.sample_url()).status_code,403)
            self.assertEqual(self.post({"activity":self.activity.pk,"sample":self.sample.path}).status_code,403)

    def test_sample_source_is_server_selected_and_does_not_include_private_graders(self):
        self.solved()
        response=self.post({"activity":self.activity.pk,"sample":self.sample.path,"source":"print('tampered')"})
        self.assertEqual(response.status_code,200)
        job=VisualizationJob.objects.get()
        self.assertIn("answer = 42",job.source)
        self.assertEqual(job.files,{"main.py":"print(1)"})
        self.assertNotIn("grader/tests.json",job.files)
        self.assertFalse(Workspace.objects.exists())
        self.assertFalse(Submission.objects.exists())
        self.assertFalse(ActivityProgress.objects.exists())

    def test_membership_is_rechecked_and_other_accounts_cannot_read_trace(self):
        job_id=self.post({"source":"print(1)"}).json()["id"]
        url=f"/api/visualizations/{job_id}/"
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code,404)
        self.client.force_login(self.student)
        Membership.objects.filter(user=self.student).update(active=False)
        self.assertEqual(self.client.get(url).status_code,403)

    def test_active_exam_blocks_library_as_well_as_direct_sample_urls(self):
        member=Membership.objects.get(user=self.student)
        lesson=self.activity.lesson;lesson.metadata={"kind":"programming_quiz","exam_mode":True};lesson.save()
        QuizAttempt.objects.create(membership=member,lesson=lesson,started_at=timezone.now(),expires_at=timezone.now()+timedelta(minutes=30))
        self.assertEqual(self.post({"source":"print(1)"}).status_code,403)
        self.assertEqual(self.client.get(self.sample_url()).status_code,403)

    def test_queue_lease_owner_and_completion_never_create_a_grade(self):
        job_id=self.post({"source":"print(1)"}).json()["id"]
        self.assertEqual(self.client.post("/api/runner/claim/").status_code,403)
        auth={"HTTP_AUTHORIZATION":"Bearer visualizer-test"}
        claimed=self.client.post("/api/runner/claim/",**auth).json()["job"]
        self.assertEqual(claimed["id"],job_id)
        self.assertEqual(claimed["operation"],"visualize")
        url=f"/api/runner/complete/{job_id}/"
        body={"lease":"wrong","result":{"trace":{"steps":[]}}}
        self.assertEqual(self.client.post(url,body,content_type="application/json",**auth).status_code,403)
        body["lease"]=claimed["lease"]
        self.assertEqual(self.client.post(url,body,content_type="application/json",**auth).status_code,200)
        self.assertEqual(self.client.get(f"/api/visualizations/{job_id}/").json()["status"],"completed")
        self.assertFalse(Workspace.objects.exists())
        self.assertFalse(Submission.objects.exists())
        self.assertFalse(ActivityProgress.objects.exists())
        self.assertFalse(ExecutionJob.objects.exists())

    def test_duplicate_jobs_and_cross_queue_spam_are_blocked_and_rate_is_bounded(self):
        self.post({"source":"print(1)"})
        self.assertEqual(self.post({"source":"print(2)"}).status_code,409)
        self.assertEqual(self.client.post(f"/api/execute/{self.revision.pk}/",{"operation":"run","files":{"main.py":"print(1)"}},content_type="application/json").status_code,409)
        VisualizationJob.objects.update(status="completed")
        for _ in range(11):
            VisualizationJob.objects.create(user=self.student,source="pass",status="completed")
        self.assertEqual(self.post({"source":"print(3)"}).status_code,429)

    def test_expired_trace_returns_actionable_error(self):
        job=VisualizationJob.objects.create(user=self.student,source="pass")
        VisualizationJob.objects.filter(pk=job.pk).update(created_at=timezone.now()-timedelta(minutes=6))
        data=self.client.get(f"/api/visualizations/{job.pk}/").json()
        self.assertEqual(data["status"],"failed")
        self.assertIn("local worker",data["result"]["error"])

    def test_public_function_input_is_visible_and_expected_answers_are_omitted(self):
        self.revision.grading={"definition":{"cases":[
            {"id":"public","label":"Test with 7","action":"function","target":"double","arguments":[7],"expected":14,"public":True},
            {"id":"hidden","action":"function","target":"double","arguments":[99],"expected":198,"public":False}]}}
        self.revision.save()
        self.sample.blob.save("double.py",ContentFile(b"def double(number):\n    return number * 2"))
        self.solved()
        data=self.client.get(self.sample_url()).json()
        self.assertEqual(data["selected_case"],"public")
        self.assertEqual(len(data["cases"]),1)
        self.assertNotIn("expected",str(data))
        self.assertIn("print(double(7))",data["samples"][0]["source"])
        self.assertEqual(self.client.get(self.sample_url()+"?case=hidden").status_code,404)
        response=self.post({"activity":self.activity.pk,"sample":self.sample.path,"case":"public"})
        self.assertEqual(response.status_code,200)
        self.assertEqual(VisualizationJob.objects.get().source,data["samples"][0]["source"])
        original=self.client.get(self.sample_url()+"?case=original").json()
        self.assertNotIn("print(double(7))",original["samples"][0]["source"])

    def test_replaced_variables_are_present_in_displayed_code(self):
        from core.visualization_inputs import walkthrough
        program=walkthrough("sunny=True\nwindy=False\nif sunny:\n    print(windy)",
            {"action":"stdout","variables":{"sunny":False,"windy":True}})
        self.assertIn("sunny = False",program)
        self.assertIn("windy = True",program)
        self.assertIn("if sunny:",program)

    def test_queue_claims_the_oldest_job_across_both_types(self):
        trace=VisualizationJob.objects.create(user=self.student,source="pass")
        execute=self.solved(user=self.staff,status="pending")
        auth={"HTTP_AUTHORIZATION":"Bearer visualizer-test"}
        claimed=self.client.post("/api/runner/claim/",**auth).json()["job"]
        self.assertEqual(claimed["id"],str(trace.pk))
        claimed=self.client.post("/api/runner/claim/",**auth).json()["job"]
        self.assertEqual(claimed["id"],str(execute.pk))

    def test_stale_source_is_rejected_and_an_abandoned_trace_does_not_block_forever(self):
        self.solved()
        response=self.post({"activity":self.activity.pk,"revision":self.revision.pk+100,"sample":self.sample.path})
        self.assertEqual(response.status_code,409)
        job=VisualizationJob.objects.create(user=self.student,source="pass")
        VisualizationJob.objects.filter(pk=job.pk).update(created_at=timezone.now()-timedelta(minutes=6))
        self.assertEqual(self.post({"source":"print(1)"}).status_code,200)
        job.refresh_from_db()
        self.assertEqual(job.status,"failed")

    def test_staff_student_view_obeys_student_unlock_and_quarantine_is_excluded(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.sample_url()).status_code,200)
        session=self.client.session
        session["student_view_course"]=self.activity.lesson.course_id
        session.save()
        self.assertEqual(self.client.get(self.sample_url()).status_code,403)
        self.solved(user=self.staff)
        self.assertEqual(self.client.get(self.sample_url()).status_code,200)
        self.sample.visibility="quarantine";self.sample.save()
        self.assertEqual(self.client.get(self.sample_url()).status_code,404)
