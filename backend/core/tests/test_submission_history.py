from django.test import TestCase
from django.contrib.auth import get_user_model
from core.models import Membership,ExecutionJob,Submission,Workspace,Revision
from . import test_studio

class SubmissionHistoryTests(TestCase):
 def setUp(self):
  test_studio.StudioTests.setUp(self);self.member=Membership.objects.get(user=self.student);self.client.force_login(self.staff)
  self.url=f'/api/gradebook/work/?membership={self.member.pk}&activity={self.activity.pk}'
 def job(self,**kw):
  defaults=dict(user=self.student,revision=self.revision,generation=0,operation='submit',snapshot={'main.py':'original'},entrypoint='main.py',status='completed',result={'score':'2','maximum':'3'})
  return ExecutionJob.objects.create(**{**defaults,**kw})
 def test_submit_history_includes_failed_jobs_once_not_runs_or_previews(self):
  a=self.job();b=self.job(status='failed');self.job(operation='run');self.job(preview=True)
  Submission.objects.create(membership=self.member,revision=self.revision,response={'job':str(a.pk)})
  rows=self.client.get(self.url).json()['history']
  self.assertEqual([r['id'] for r in rows],['job:'+str(a.pk),'job:'+str(b.pk)])
  self.assertEqual([r['number'] for r in rows],[1,2]);self.assertNotIn('snapshot',str(rows))
 def test_snapshot_uses_historical_revision_and_does_not_change_saved_work(self):
  j=self.job(snapshot={'main.py':'original','private/Ferb.py':'secret'})
  newer=Revision.objects.create(activity=self.activity,number=2,created_by=self.staff,content=self.revision.content)
  self.activity.published_revision=newer;self.activity.save()
  Workspace.objects.create(user=self.student,revision=newer,files={'main.py':'current'})
  data=self.client.get(self.url+'&attempt=job:'+str(j.pk)).json()
  self.assertEqual(data['files'],{'main.py':'original'});self.assertEqual(data['revision'],self.revision.pk)
  self.assertEqual(Workspace.objects.get().files,{'main.py':'current'})
 def test_native_answers_and_revision_preserved(self):
  a=Submission.objects.create(membership=self.member,revision=self.revision,response={'q':'wrong'})
  Submission.objects.create(membership=self.member,revision=self.revision,response={'q':'right'})
  self.assertEqual(len(self.client.get(self.url).json()['history']),2)
  self.assertEqual(self.client.get(self.url+'&attempt=submission:'+str(a.pk)).json()['latest_response'],{'q':'wrong'})
 def test_other_student_preview_run_and_bad_identifiers_denied(self):
  other=get_user_model().objects.create_user('other')
  ids=['job:'+str(self.job(user=other).pk),'job:'+str(self.job(preview=True).pk),'job:'+str(self.job(operation='run').pk),'job:bad','submission:bad']
  for value in ids:self.assertEqual(self.client.get(self.url+'&attempt='+value).status_code,404)
 def test_student_and_student_view_denied(self):
  self.client.force_login(self.student);self.assertEqual(self.client.get(self.url).status_code,403)
  self.client.force_login(self.staff);s=self.client.session;s['student_view_course']=self.member.course_id;s.save()
  self.assertEqual(self.client.get(self.url).status_code,403)

 def test_assignment_score_detail_is_scoped_to_requested_assignment(self):
  from core.models import Lesson,Activity
  lesson=Lesson.objects.create(course=self.member.course,title='2.2 Problem set',position=10)
  part=Activity.objects.create(lesson=lesson,title='2.2 Coding problem 8',position=8)
  revision=Revision.objects.create(activity=part,number=1,created_by=self.staff,content=self.revision.content)
  part.published_revision=revision;part.save()
  url=f'/api/gradebook/detail/?summary=1&membership={self.member.pk}'
  focused=self.client.get(url+f'&lesson={lesson.pk}').json()
  self.assertEqual(focused['lesson']['id'],lesson.pk)
  self.assertEqual([p['id'] for p in focused['activities']],[part.pk])
  entire=self.client.get(url).json()
  self.assertIsNone(entire['lesson']['id'])
  self.assertEqual({p['id'] for p in entire['activities']},{self.activity.pk,part.pk})
