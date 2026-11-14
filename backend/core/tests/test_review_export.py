import csv,io
from django.test import TestCase
from django.contrib.auth import get_user_model
from core.models import Membership,Course
from core.rest.auth import issue_token
from core.review_export import COLUMNS,cell_text
from . import test_studio

class ReviewExportTests(TestCase):
 def setUp(self):
  test_studio.StudioTests.setUp(self);self.member=Membership.objects.get(user=self.student)
  self.member.external_ids={'gtid':'001234567'};self.member.save()
  self.student.first_name='=DANGEROUS()';self.student.save()
  self.url='/api/settings/submission-review/export/'
  self.rest=f'/api/v1/courses/{self.member.course_id}/reports/submission-review/export/'
 def test_anonymous_student_and_student_view_denied(self):
  self.client.logout();self.assertEqual(self.client.get(self.url).status_code,403)
  self.client.force_login(self.student);self.assertEqual(self.client.get(self.url).status_code,403)
  self.client.force_login(self.staff);s=self.client.session;s['student_view_course']=self.member.course_id;s.save()
  self.assertEqual(self.client.get(self.url).status_code,403)
 def test_gtid_as_text_unknown_blanks_and_no_source_or_staff_notes(self):
  self.client.force_login(self.staff);r=self.client.get(self.url);self.assertEqual(r.status_code,200)
  data=r.json();row=dict(zip(data['columns'],data['rows'][0]))
  self.assertEqual(row['GTID'],'001234567');self.assertTrue(row['Name'].startswith("'="))
  self.assertIsNone(row['Sus index / 100']);self.assertIn('0/4',row['Data coverage'])
  self.assertEqual(len(data['rows'][0]),len(COLUMNS));self.assertIn('ROUND',data['formulas'][0]['D'])
  self.assertNotIn('Formula',data['columns']);self.assertEqual(data['schema_version'],2)
  self.assertIn('SUMPRODUCT(E2:H2,$AJ$2:$AM$2)',data['formulas'][0]['D'])
  self.assertNotIn('Staff notes',data['columns']);self.assertIn('no-store',r['Cache-Control'])
  for text in [' =HYPERLINK()','+1','-1','@cmd','\tbad']:self.assertTrue(cell_text(text).startswith("'"))
  rows=list(csv.reader(io.StringIO(self.client.get(self.url+'?format=csv').content.decode('utf-8-sig'))))
  self.assertEqual(rows[1][1],'001234567');self.assertTrue(rows[1][2].startswith("'="))
 def test_all_pages_exported_even_if_page_parameter_is_set(self):
  for n in range(51):
   u=get_user_model().objects.create_user(f'm{n}');Membership.objects.create(course=self.member.course,user=u,role='student')
  self.client.force_login(self.staff);data=self.client.get(self.url+'?page=1').json()
  self.assertEqual(data['total'],52);self.assertEqual(len({r[0] for r in data['rows']}),52)
 def test_rest_needs_three_scopes_and_is_course_bound(self):
  m=Membership.objects.get(user=self.staff)
  for scopes,expected in [(['activity:read','submissions:read'],403),(['activity:read','submissions:read','roster:read'],200)]:
   _,raw=issue_token(m,'export',scopes);self.assertEqual(self.client.get(self.rest,HTTP_AUTHORIZATION='Bearer '+raw).status_code,expected)
  other=Course.objects.create(title='Other',term='Other')
  self.assertIn(self.client.get(f'/api/v1/courses/{other.pk}/reports/submission-review/export/',HTTP_AUTHORIZATION='Bearer '+raw).status_code,[403,404])

 def test_score_rounding_matches_excel_half_up(self):
  from core.submission_review import metrics
  from core.code_review import DEFAULT_POLICY
  from django.utils import timezone
  from datetime import timedelta
  now=timezone.now()
  subs=[{'revision__activity_id':i,'received_at':now+timedelta(seconds=i*60),'created_at':now} for i in range(2)]
  self.assertEqual(metrics([],subs,[],DEFAULT_POLICY)['index'],26.3)
