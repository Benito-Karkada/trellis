import tempfile
from pathlib import Path
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from core.models import Course,Lesson,Activity,Revision,Membership,ActivityFile,CanvasGradeUpdate
from loadtests.fixtures import create_fixture,queue_snapshot

class LoadFixtureTests(TestCase):
    def setUp(self):
        self.media=tempfile.TemporaryDirectory();self.addCleanup(self.media.cleanup)
        self.settings=override_settings(MEDIA_ROOT=self.media.name);self.settings.enable();self.addCleanup(self.settings.disable)
        self.author=get_user_model().objects.create_user('source-owner')
        self.source=Course.objects.create(title='Source',term='source',canvas_context_id='123')
        lesson=Lesson.objects.create(course=self.source,title='Lesson without kind',metadata={'canvas_assignment_id':'987'})
        part=Activity.objects.create(lesson=lesson,title='Source part',metadata={'kind':'reading'})
        rev=Revision.objects.create(activity=part,number=1,created_by=self.author,content={'version':1,'blocks':[]},grading={})
        part.published_revision=rev;part.save()
        Lesson.objects.create(course=self.source,title='Do not copy exam',metadata={'kind':'programming_quiz'})

    def test_isolated_course_keeps_outline_but_excludes_quizzes_and_canvas(self):
        f=create_fixture('fixture-test',2,self.source.pk);course=Course.objects.get(pk=f['course_id'])
        self.assertEqual((f['copied_sections'],f['copied_parts']),(1,1))
        self.assertEqual(course.canvas_context_id,'')
        self.assertFalse(course.lesson_set.filter(metadata__has_key='canvas_assignment_id').exists())
        self.assertFalse(course.lesson_set.filter(metadata__kind='programming_quiz').exists())
        self.assertEqual(Membership.objects.filter(course=course,role='student').count(),2)
        self.assertFalse(Membership.objects.filter(course=self.source).exists())
        self.assertEqual(ActivityFile.objects.filter(revision__activity__lesson__course=course).count(),2)
        snapshot=queue_snapshot(course.pk)
        self.assertEqual(snapshot['canvas_updates'],0)
        self.assertEqual(snapshot['students'],2)
        self.assertEqual(snapshot['jobs'],{})
        with self.assertRaises(ValueError):create_fixture('fixture-test',2,self.source.pk)

    def test_real_course_cannot_be_monitored_as_a_synthetic_fixture(self):
        with self.assertRaises(ValueError):queue_snapshot(self.source.pk)
        for count in (0,21):
            with self.assertRaises(ValueError):create_fixture('invalid-count',count,self.source.pk)
