from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from core.discussion_search import _postgres_cosine, embedding_provider, refresh_thread_index
from core.models import (Course, DiscussionAnswer, DiscussionDraft, DiscussionSearchDocument,
                         DiscussionThread, DiscussionThreadState, Membership)


class SuggestionTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(title="Example", term="Test")
        self.user = get_user_model().objects.create_user("viewer")
        self.staff_user = get_user_model().objects.create_user("teacher")
        self.member = Membership.objects.create(course=self.course, user=self.user, role="student")
        self.teacher = Membership.objects.create(course=self.course, user=self.staff_user, role="instructor")
        self.client.force_login(self.user)
        self.headers = {"HTTP_X_TRELLIS_COURSE": str(self.course.pk)}

    def question(self, title="Account access", body="Authentication credentials are rejected.",
                 answer="Reset your password in account settings.", **kwargs):
        thread = DiscussionThread.objects.create(course=self.course, author=self.teacher,
            title=title, body=body, **kwargs)
        if answer is not None:
            DiscussionAnswer.objects.create(thread=thread, kind="instructor", body=answer,
                last_editor=self.teacher)
        refresh_thread_index(thread.pk)
        return thread

    def suggest(self, text="I cannot log in with my password", **payload):
        return self.client.post("/api/discussions/suggestions/", {"text": text, **payload},
            content_type="application/json", **self.headers)

    def test_paraphrased_answered_question_is_suggested_without_saving_draft_or_view(self):
        thread = self.question()
        rows = self.suggest().json()["suggestions"]
        self.assertEqual(rows[0]["id"], thread.pk)
        self.assertEqual(rows[0]["answer_label"], "Instructor answer")
        self.assertGreater(rows[0]["score"], .18)
        self.assertEqual(DiscussionThreadState.objects.count(), 0)
        self.assertEqual(DiscussionDraft.objects.count(), 0)

    def test_only_answered_live_questions_and_excludes_edited_post(self):
        answered = self.question()
        self.question(answer=None)
        self.question(kind="note")
        self.question(deleted_at=timezone.now())
        rows = self.suggest().json()["suggestions"]
        self.assertEqual([row["id"] for row in rows], [answered.pk])
        self.assertEqual(self.suggest(exclude_id=answered.pk).json()["suggestions"], [])

    def test_private_and_other_course_posts_do_not_leak_even_in_student_preview(self):
        public = self.question()
        self.question(visibility="private")
        other = Course.objects.create(title="Other", term="Test")
        hidden = DiscussionThread.objects.create(course=other, author=self.teacher,
            title="Password login", body="Authentication login credentials")
        DiscussionAnswer.objects.create(thread=hidden, kind="instructor", body="Password reset")
        refresh_thread_index(hidden.pk)
        self.assertEqual([r["id"] for r in self.suggest().json()["suggestions"]], [public.pk])
        self.client.force_login(self.staff_user)
        session = self.client.session
        session["student_view_course"] = self.course.pk
        session.save()
        # Staff preview may still see their own private question, as on the board.
        private = DiscussionThread.objects.get(course=self.course, visibility="private")
        private.author = self.member
        private.save()
        self.assertEqual([r["id"] for r in self.suggest().json()["suggestions"]], [public.pk])

    def test_student_endorsement_label_and_answer_body_are_searchable(self):
        thread = self.question(title="Help with homework", body="My code has a problem.", answer=None)
        DiscussionAnswer.objects.create(thread=thread, kind="student", endorsed=True,
            body="Use a dictionary mapping keys and values.")
        refresh_thread_index(thread.pk)
        row = self.suggest("dictionary mapping keys and values").json()["suggestions"][0]
        self.assertEqual(row["id"], thread.pk)
        self.assertEqual(row["answer_label"], "Endorsed answer")
        self.assertIn("dictionary", row["excerpt"])

    def test_results_are_bounded_and_empty_queries_do_not_search(self):
        for _ in range(8):
            self.question()
        self.assertEqual(len(self.suggest().json()["suggestions"]), 5)
        with patch("core.discussions.search_discussions") as search:
            self.assertEqual(self.suggest("login").json()["suggestions"], [])
            search.assert_not_called()
        for payload in [{"text": "x" * 1501}, {"text": []}, {"text": "password", "exclude_id": True},
                        {"text": "password", "course": 100}]:
            response = self.client.post("/api/discussions/suggestions/", payload,
                content_type="application/json", **self.headers)
            self.assertEqual(response.status_code, 400)

    def test_repeated_search_does_not_rebuild_index(self):
        self.question()
        with patch("core.discussion_search.refresh_thread_index") as refresh:
            self.suggest()
            self.suggest("my account authentication password")
            refresh.assert_not_called()

    def test_inactive_members_and_anonymous_users_are_denied(self):
        self.member.active = False
        self.member.save()
        self.assertEqual(self.suggest().status_code, 403)
        self.client.logout()
        self.assertEqual(self.suggest().status_code, 403)

    def test_pgvector_cosine_scores_cover_all_authorized_documents(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL vector integration")
        thread = self.question()
        base = DiscussionSearchDocument.objects.filter(thread=thread).first()
        DiscussionSearchDocument.objects.bulk_create([
            DiscussionSearchDocument(course=self.course, thread=thread, content_type="followup",
                object_id=10000 + index, content="Password login", embedding=base.embedding,
                content_hash=base.content_hash, source_label="Followup") for index in range(505)])
        documents = list(DiscussionSearchDocument.objects.filter(thread=thread))
        scores = _postgres_cosine(documents, embedding_provider().embed("authentication password"))
        self.assertEqual(len(scores), len(documents))

    def test_vector_failure_recovers_without_poisoning_request_transaction(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL vector integration")
        thread = self.question()
        documents = list(DiscussionSearchDocument.objects.filter(thread=thread))
        with patch.object(DiscussionSearchDocument._meta, "db_table", "missing_vector_test_table"):
            scores = _postgres_cosine(documents, embedding_provider().embed("password"))
        self.assertEqual(scores, {})
        self.assertTrue(Course.objects.filter(pk=self.course.pk).exists())
