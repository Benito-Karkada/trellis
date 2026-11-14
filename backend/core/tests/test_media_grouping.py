from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model
from core.models import Course, Lesson, Activity, Revision


class MediaGroupingTests(TestCase):
    def test_original_order_preserved_exercises_separate_and_rerun_safe(self):
        user = get_user_model().objects.create_user("author")
        course = Course.objects.create(title="CS 1301")
        lesson = Lesson.objects.create(course=course, title="Assignment")
        originals = []
        for i, kind in enumerate(["reading","video","reading","question","reading","video"]):
            activity = Activity.objects.create(lesson=lesson, title=f"Part {i}", position=i,
                metadata={"source_path":f"unit/{i}.xml","kind":kind,"category":"content","group":"Unit"})
            revision = Revision.objects.create(activity=activity, number=1, created_by=user,
                content={"version":1,"blocks":[{"id":"body","type":"paragraph",
                    "content":[{"type":"text","text":str(i)}]}]})
            activity.published_revision=revision; activity.save()
            originals.append(activity)
        call_command("group_lesson_media")
        active = list(Activity.objects.filter(deleted_at=None).order_by("position"))
        self.assertEqual([a.pk for a in active], [originals[1].pk, originals[3].pk, originals[5].pk])
        blocks = active[0].published_revision.content["blocks"]
        self.assertEqual([b["content"][0]["text"] for b in blocks], ["0","1","2"])
        self.assertEqual(len({b["id"] for b in blocks}), 3)
        count = Revision.objects.count()
        call_command("group_lesson_media")
        self.assertEqual(Revision.objects.count(), count)
