from datetime import datetime,timedelta,timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch,Mock
from django.test import TestCase
from core.models import Membership,CanvasGradeUpdate,Accommodation,ActivityProgress,Activity,Revision
from core.canvas_sync import grade_comment,enqueue_grade,process_one
from . import test_studio

class CanvasCommentTests(TestCase):
 def setUp(self):
  test_studio.StudioTests.setUp(self);self.member=Membership.objects.get(user=self.student);self.lesson=self.activity.lesson
  self.member.canvas_user_id='789';self.member.save()
  self.lesson.course.canvas_context_id='123';self.lesson.course.save()
  self.lesson.metadata={'canvas_assignment_id':'456','due_at':'2026-11-12T23:59:00-05:00'};self.lesson.save()
  self.revision.grading={'maximum_points':'3','definition':{'version':1}};self.revision.save()
  self.now=datetime(2026,11,9,2,30,tzinfo=dt_timezone.utc)
  self.job=CanvasGradeUpdate.objects.create(membership=self.member,lesson=self.lesson,assignment_id='456',score=1,maximum=3,include_comment=True)
 def test_incomplete_message_uses_eastern_date_and_precise_days_remaining(self):
  msg=grade_comment(self.job,self.now)
  self.assertIn('November 08, 2026 at 09:30 PM EST',msg)
  self.assertIn('1 / 3 points',msg);self.assertIn('4 days and 2 hours',msg)
 def test_full_credit_message_has_no_countdown_or_emoji(self):
  self.job.score=Decimal(3);msg=grade_comment(self.job,self.now)
  self.assertIn('Well done!',msg);self.assertIn('full credit',msg);self.assertNotIn('left until',msg);self.assertNotIn('✅',msg)
 def test_individual_extension_replaces_base_deadline(self):
  Accommodation.objects.create(membership=self.member,lesson=self.lesson,due_at_override=self.now+timedelta(days=8))
  self.assertIn('8 days left',grade_comment(self.job,self.now))
 def test_under_one_day_and_expired_deadlines_do_not_claim_zero_or_negative_days(self):
  self.lesson.metadata['due_at']=(self.now+timedelta(minutes=30)).isoformat();self.lesson.save()
  self.assertIn('less than 1 hour',grade_comment(self.job,self.now))
  self.lesson.metadata['due_at']=(self.now-timedelta(seconds=1)).isoformat();self.lesson.save()
  msg=grade_comment(self.job,self.now);self.assertIn('due date has passed',msg);self.assertNotIn('left until',msg)
 def test_no_deadline_has_no_invented_countdown(self):
  self.lesson.metadata.pop('due_at');self.lesson.save();self.assertIn('No due date is currently set',grade_comment(self.job,self.now))
 def test_part_override_and_completed_parts_are_respected(self):
  Accommodation.objects.create(membership=self.member,activity=self.activity,due_at_override=self.now+timedelta(days=2))
  self.assertIn('2 days left',grade_comment(self.job,self.now))
  other=Activity.objects.create(lesson=self.lesson,title='Other')
  rev=Revision.objects.create(activity=other,number=1,created_by=self.staff,content=self.revision.content,grading=self.revision.grading)
  other.published_revision=rev;other.save()
  Accommodation.objects.create(membership=self.member,activity=other,due_at_override=self.now+timedelta(days=1))
  ActivityProgress.objects.create(user=self.student,activity=other,score=3,maximum=3,completed=True)
  self.assertIn('2 days left',grade_comment(self.job,self.now))
 @patch.dict('os.environ',{'CANVAS_API_TOKEN':'test-secret','CANVAS_BASE_URL':'https://canvas.example.invalid'})
 @patch('core.canvas_sync.requests.put')
 def test_manual_comment_survives_auto_coalescing_and_retry_then_clears(self,put):
  self.job.delete();self.assertTrue(enqueue_grade(self.member,self.lesson,force=True))
  enqueue_grade(self.member,self.lesson);self.assertTrue(CanvasGradeUpdate.objects.get().include_comment)
  put.return_value=Mock(status_code=429);process_one();job=CanvasGradeUpdate.objects.get()
  self.assertTrue(job.include_comment);self.assertEqual(job.status,'retrying')
  self.assertIn('comment[text_comment]',put.call_args.kwargs['data'])
  CanvasGradeUpdate.objects.update(next_attempt_at=None);put.return_value=Mock(status_code=200);process_one()
  job.refresh_from_db();self.assertFalse(job.include_comment);self.assertEqual(job.status,'sent')
  enqueue_grade(self.member,self.lesson);process_one()
  self.assertNotIn('comment[text_comment]',put.call_args.kwargs['data'])
