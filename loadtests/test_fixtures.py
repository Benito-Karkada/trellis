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

class LiveCleanupTests(TestCase):
    def setUp(self):
        from django.core.files.base import ContentFile
        self.media=tempfile.TemporaryDirectory();self.addCleanup(self.media.cleanup)
        self.override=override_settings(MEDIA_ROOT=self.media.name);self.override.enable();self.addCleanup(self.override.disable)
        self.owner=get_user_model().objects.create_user('real-owner')
        self.course=Course.objects.create(title='Actual course',term='fall')
        self.owner_member=Membership.objects.create(course=self.course,user=self.owner,role='instructor')
        self.lesson=Lesson.objects.create(course=self.course,title='Actual lesson')
        def part(kind,title,grading):
            activity=Activity.objects.create(lesson=self.lesson,title=title,metadata={'kind':kind})
            revision=Revision.objects.create(activity=activity,number=1,created_by=self.owner,content={'version':1,'blocks':[]},grading=grading)
            activity.published_revision=revision;activity.save();return activity,revision
        part('reading','Real reading',{})
        part('question','Real question',{'maximum_points':'0.5','questions':{'q1':{'correct_choice_ids':['a'],'selection':'one'}}})
        self.coding,self.revision=part('coding','Real coding',{'entrypoint':'main.py','maximum_points':'3','definition':{'version':1,'cases':[{'id':str(n),'action':'stdout','expected':'5\n'} for n in range(6)]}})
        for path,visibility,text in [('main.py','student','a = 2\nb = 3\n'),('solutions/sample_answer_1.py','staff','a = 2\nb = 3\nprint(a+b)\n')]:
            ActivityFile.objects.create(revision=self.revision,path=path,visibility=visibility,blob=ContentFile(text.encode(),name=path.split('/')[-1]),sha256='fixture')

    def test_live_enrollment_cleanup_preserves_real_users_content_and_progress(self):
        from loadtests.fixtures import create_live_fixture,cleanup_live_fixture
        from core.models import ActivityProgress,ExecutionJob,Submission,GradeEvent
        from decimal import Decimal
        import uuid
        before=list(Activity.objects.filter(lesson__course=self.course).values('pk','published_revision_id','metadata','title'))
        ActivityProgress.objects.create(user=self.owner,activity=self.coding,score=Decimal('2'),maximum=Decimal('3'))
        fixture=create_live_fixture('live-cleanup-test',2,self.course.pk,(self.coding.pk,))
        self.assertEqual(Activity.objects.filter(lesson__course=self.course).count(),3)
        account=fixture['accounts'][0]
        job=ExecutionJob.objects.create(user_id=account['user_id'],revision=self.revision,generation=1,operation='submit',snapshot={},entrypoint='main.py')
        with self.assertRaises(AssertionError):cleanup_live_fixture(fixture)
        self.assertEqual(get_user_model().objects.filter(pk__in=[a['user_id'] for a in fixture['accounts']]).count(),2)
        job.status='completed';job.save()
        sub=Submission.objects.create(revision=self.revision,membership_id=account['membership_id'])
        GradeEvent.objects.create(submission=sub,idempotency_key=uuid.uuid4(),score=3,maximum=3)
        result=cleanup_live_fixture(fixture)
        self.assertEqual(result['removed']['test_users'],2)
        self.assertEqual(list(Activity.objects.filter(lesson__course=self.course).values('pk','published_revision_id','metadata','title')),before)
        self.assertEqual(ActivityProgress.objects.get(user=self.owner,activity=self.coding).score,2)
        self.assertTrue(Membership.objects.filter(pk=self.owner_member.pk,active=True).exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.owner.pk).exists())
        self.assertEqual(ActivityFile.objects.filter(revision=self.revision).count(),2)
