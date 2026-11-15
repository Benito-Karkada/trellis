from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.issue_organizer import organize_course_issues
from core.management.commands.seed_discussion_demo import DEMO_KEY
from core.models import (Course, DiscussionAnswer, DiscussionPollVote, DiscussionReply,
    DiscussionThread, DiscussionThreadState, Membership)


@override_settings(DEBUG=True)
class DiscussionDemoTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(title="Local course", term="Test", metadata={"keep": "unchanged"})
        self.existing = DiscussionThread.objects.create(course=self.course, title="An existing post", body="Keep my edits")

    def seed(self):
        call_command("seed_discussion_demo", course_id=self.course.pk, stdout=StringIO())
        self.course.refresh_from_db()

    def test_populates_only_selected_course_without_real_identities_or_login_credentials(self):
        other = Course.objects.create(title="Other", term="Test")
        self.seed()
        registry = self.course.metadata[DEMO_KEY]
        self.assertGreaterEqual(len(registry["thread_ids"]), 40)
        self.assertEqual(self.course.metadata["keep"], "unchanged")
        self.assertFalse(other.discussion_threads.exists())
        self.existing.refresh_from_db()
        self.assertEqual(self.existing.body, "Keep my edits")
        members = Membership.objects.filter(pk__in=registry["member_ids"])
        self.assertEqual(members.filter(role="student").count(), 18)
        for member in members.select_related("user"):
            self.assertFalse(member.user.email)
            self.assertFalse(member.user.has_usable_password())
            self.assertFalse(member.canvas_user_id)
            self.assertEqual(member.source, "discussion_demo")
        self.assertGreater(DiscussionAnswer.objects.filter(thread__course=self.course).count(), 20)
        self.assertTrue(DiscussionAnswer.objects.filter(thread__course=self.course, kind="student", endorsed=True).exists())
        self.assertGreater(DiscussionReply.objects.filter(thread__course=self.course).count(), 50)
        self.assertGreater(DiscussionThreadState.objects.filter(thread__course=self.course).count(), 300)
        self.assertEqual(DiscussionPollVote.objects.filter(thread__course=self.course).count(), 36)
        notes = self.course.discussion_threads.filter(kind="note", pinned=True)
        self.assertTrue(any("fictional" in note.body for note in notes))

    def test_rerun_preserves_edited_posts_and_does_not_duplicate_activity(self):
        self.seed()
        pk = self.course.metadata[DEMO_KEY]["thread_ids"][0]
        DiscussionThread.objects.filter(pk=pk).update(title="An instructor changed this title")
        counts = (DiscussionThread.objects.count(), Membership.objects.count(), DiscussionReply.objects.count())
        self.seed()
        self.assertEqual(counts, (DiscussionThread.objects.count(), Membership.objects.count(), DiscussionReply.objects.count()))
        self.assertEqual(DiscussionThread.objects.get(pk=pk).title, "An instructor changed this title")

    def test_demo_creates_multiple_actionable_pain_points(self):
        self.seed()
        issues = organize_course_issues(self.course)
        self.assertGreaterEqual(len(issues), 3)
        self.assertIn("high", {issue["priority"] for issue in issues})
        self.assertIn("low", {issue["priority"] for issue in issues},
            [(i["title"], i["priority"], i["student_count"], i["post_count"]) for i in issues])
        self.assertTrue(any(issue["open_count"] for issue in issues))
        self.assertTrue(any(issue["student_count"] >= 4 for issue in issues))
        for issue in issues:
            titles = {post["title"] for post in issue["posts"]}
            if "IndexError on the final item in my list" in titles:
                self.assertNotIn("Two objects seem to share the same list", titles)

    @override_settings(DEBUG=False)
    def test_seeding_is_disabled_outside_local_debug_mode(self):
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(DiscussionThread.objects.count(), 1)
        self.assertFalse(Membership.objects.exists())
