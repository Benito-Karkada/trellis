import json
from django.test import TestCase
from core.models import Activity, Lesson, Revision
from . import test_studio

class StructureDraftTests(TestCase):
 def setUp(self):
  test_studio.StudioTests.setUp(self)
  self.client.force_login(self.staff)
  self.course=self.activity.lesson.course
 def state(self):return self.client.get('/api/structure/draft/').json()
 def save(self,operations,version=None):
  return self.client.post('/api/structure/save/',{'base_version':version or self.state()['version'],'operations':operations},content_type='application/json')
 def test_save_creates_renames_copies_and_resolves_temporary_ids(self):
  before=self.state();old_title=self.activity.title;revisions=Revision.objects.count()
  ops=[{'entity':'lesson','action':'create','title':'New section','client_id':-1},
   {'entity':'part','action':'copy','lesson_id':-1,'activity_id':self.activity.pk,'client_id':-2},
   {'entity':'part','action':'rename','lesson_id':-1,'activity_id':-2,'title':'Renamed copy'},
   {'entity':'part','action':'rename','lesson_id':self.activity.lesson_id,'activity_id':self.activity.pk,'title':'Renamed original'}]
  response=self.save(ops,before['version']);self.assertEqual(response.status_code,200,response.content)
  self.activity.refresh_from_db();self.assertEqual(self.activity.title,'Renamed original')
  copy=Activity.objects.get(title='Renamed copy');self.assertNotEqual(copy.lesson_id,self.activity.lesson_id)
  self.assertEqual(copy.published_revision.files.count(),self.revision.files.count())
  self.assertEqual(Revision.objects.count(),revisions+1)
  self.assertNotEqual(self.state()['version'],before['version'])
 def test_failure_rolls_back_all_changes(self):
  response=self.save([{'entity':'lesson','action':'create','title':'Must roll back','client_id':-1},
   {'entity':'part','action':'rename','lesson_id':self.activity.lesson_id,'activity_id':self.activity.pk,'title':' '}])
  self.assertEqual(response.status_code,400);self.assertFalse(Lesson.objects.filter(title='Must roll back').exists())
 def test_conflict_preserves_newer_staff_changes(self):
  before=self.state();Activity.objects.filter(pk=self.activity.pk).update(title='Another staff edit')
  response=self.save([{'entity':'part','action':'delete','lesson_id':self.activity.lesson_id,'activity_id':self.activity.pk}],before['version'])
  self.assertEqual(response.status_code,409);self.activity.refresh_from_db();self.assertIsNone(self.activity.deleted_at)
 def test_copy_section_then_edit_its_copied_part_and_soft_delete_original(self):
  response=self.save([{'entity':'lesson','action':'copy','lesson_id':self.activity.lesson_id,'client_id':-1,'client_part_ids':{str(self.activity.pk):-2}},
   {'entity':'part','action':'rename','lesson_id':-1,'activity_id':-2,'title':'Copied child'},
   {'entity':'part','action':'delete','lesson_id':self.activity.lesson_id,'activity_id':self.activity.pk}])
  self.assertEqual(response.status_code,200,response.content)
  self.activity.refresh_from_db();self.assertIsNotNone(self.activity.deleted_at)
  self.assertTrue(Revision.objects.filter(activity=self.activity).exists())
  self.assertEqual(Activity.objects.get(title='Copied child').lesson.title,'Copy of '+self.activity.lesson.title)
 def test_students_cannot_read_or_save_structure_drafts(self):
  self.client.force_login(self.student)
  self.assertEqual(self.client.get('/api/structure/draft/').status_code,403)
  self.assertEqual(self.save([{'entity':'lesson','action':'create','title':'Forbidden','client_id':-1}],version='x').status_code,403)
 def test_unknown_temporary_reference_and_cross_course_part_cannot_mutate(self):
  response=self.save([{'entity':'part','action':'delete','lesson_id':self.activity.lesson_id,'activity_id':-9}])
  self.assertEqual(response.status_code,400)
  from core.models import Course
  other=Course.objects.create(title='Other',term='Other');lesson=Lesson.objects.create(course=other,title='Other')
  part=Activity.objects.create(lesson=lesson,title='Other')
  response=self.save([{'entity':'part','action':'delete','lesson_id':self.activity.lesson_id,'activity_id':part.pk}])
  self.assertEqual(response.status_code,404);part.refresh_from_db();self.assertIsNone(part.deleted_at)
