from django.test import TestCase
from core.models import Lesson, Activity, Revision
from core.ed_discussion import clean_url
from .test_studio import StudioTests

ED='https://edstem.org/us/courses/100193/discussion'
class EdDiscussionTests(TestCase):
 def setUp(self):
  StudioTests.setUp(self);self.course=self.activity.lesson.course
 def configure(self,url=ED):
  self.client.force_login(self.staff)
  return self.client.post('/api/settings/ed-discussion/save/',{'url':url},content_type='application/json')
 def test_staff_configuration_and_student_link_leave_content_and_grades_unchanged(self):
  revisions=Revision.objects.count();before=self.revision.content
  self.assertEqual(self.configure().status_code,200)
  self.assertEqual(self.client.get('/api/settings/ed-discussion/').json()['url'],ED)
  self.client.force_login(self.student)
  data=self.client.get(f'/api/studio/{self.activity.pk}/').json()
  self.assertEqual(data['ed_discussion_url'],ED);self.assertNotIn('grading',data)
  self.assertEqual(Revision.objects.count(),revisions);self.revision.refresh_from_db();self.assertEqual(self.revision.content,before)
 def test_student_cannot_change_or_read_staff_settings(self):
  self.assertEqual(self.client.get('/api/settings/ed-discussion/').status_code,403)
  self.assertEqual(self.client.post('/api/settings/ed-discussion/save/',{'url':ED},content_type='application/json').status_code,403)
 def test_invalid_targets_are_rejected_without_changing_existing_config(self):
  self.configure()
  for value in ['javascript:alert(1)','http://edstem.org/us/courses/100193/discussion','https://edstem.org.evil.test/us/courses/1/discussion','https://user:pass@edstem.org/us/courses/1/discussion','https://edstem.org/us/courses/1/discussion?redirect=elsewhere','https://example.test/us/courses/1/discussion',ED+'#fragment','https://edstem.org:444/us/courses/1/discussion',{},None]:
   with self.subTest(value=value):self.assertEqual(self.configure(value).status_code,400)
  self.course.refresh_from_db();self.assertEqual(self.course.metadata['ed_discussion_url'],ED)
 def test_quizzes_never_expose_link_including_staff_preview(self):
  self.configure();lesson=self.activity.lesson;lesson.metadata={'kind':'programming_quiz'};lesson.save()
  self.assertIsNone(self.client.get(f'/api/studio/{self.activity.pk}/?mode=preview').json()['ed_discussion_url'])
 def test_disconnect_and_unconfigured_courses_hide_link(self):
  self.assertIsNone(self.client.get(f'/api/studio/{self.activity.pk}/').json()['ed_discussion_url'])
  self.configure();self.assertEqual(self.configure('').status_code,200)
  self.client.force_login(self.student);self.assertIsNone(self.client.get(f'/api/studio/{self.activity.pk}/').json()['ed_discussion_url'])
 def test_canonical_course_urls_and_legacy_invalid_values(self):
  self.assertEqual(clean_url(' '+ED+'/ '),ED)
  self.course.metadata={'ed_discussion_url':'https://example.test/'};self.course.save()
  self.assertIsNone(self.client.get(f'/api/studio/{self.activity.pk}/').json()['ed_discussion_url'])
