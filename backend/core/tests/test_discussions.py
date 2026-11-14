from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from core.models import (Course, DiscussionAnswer, DiscussionReply, DiscussionSearchDocument,
    DiscussionThread, Membership)
from .test_studio import StudioTests


class DiscussionTests(TestCase):
    def setUp(self):
        StudioTests.setUp(self)
        self.course = self.activity.lesson.course

    def post(self, path, data):
        return self.client.post(path, data, content_type="application/json")

    def test_members_can_post_and_reply(self):
        created = self.post("/api/discussions/new/", {"title": " Variables ", "body": " How do they work? "})
        self.assertEqual(created.status_code, 201)
        thread = created.json()["thread"]
        self.assertEqual((thread["title"], thread["body"], thread["reply_count"]),
                         ("Variables", "How do they work?", 0))
        self.client.force_login(self.staff)
        reply = self.post(f"/api/discussions/{thread['id']}/replies/", {"body": "Use an assignment."})
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(self.client.get("/api/discussions/").json()["threads"][0]["reply_count"], 1)
        self.assertEqual(self.client.get(f"/api/discussions/{thread['id']}/").json()["replies"][0]["author"], "staff")

    def test_other_course_and_inactive_members_cannot_read_or_reply(self):
        thread = DiscussionThread.objects.create(course=self.course,
            author=Membership.objects.get(course=self.course, user=self.staff), title="Private", body="Course only")
        other_course = Course.objects.create(title="Other", term="Pilot")
        other_user = get_user_model().objects.create_user("other")
        Membership.objects.create(course=other_course, user=other_user, role="student")
        self.client.force_login(other_user)
        self.assertEqual(self.client.get("/api/discussions/").json()["threads"], [])
        self.assertEqual(self.client.get(f"/api/discussions/{thread.pk}/").status_code, 404)
        self.assertEqual(self.post(f"/api/discussions/{thread.pk}/replies/", {"body": "No"}).status_code, 404)
        self.client.force_login(self.student)
        Membership.objects.filter(course=self.course, user=self.student).update(active=False)
        self.assertEqual(self.client.get("/api/discussions/").status_code, 403)
        self.assertEqual(self.post("/api/discussions/new/", {"title": "No", "body": "No"}).status_code, 403)

    def test_explicit_course_context_keeps_boards_separate(self):
        first = self.post("/api/discussions/new/", {"title": "First course", "body": "Here"})
        self.assertEqual(first.status_code, 201)
        another = Course.objects.create(title="Another course", term="Pilot")
        Membership.objects.create(course=another, user=self.student, role="student")
        selected = {"HTTP_X_TRELLIS_COURSE": str(another.pk)}
        second = self.client.post("/api/discussions/new/", {"title": "Second course", "body": "Here"},
            content_type="application/json", **selected)
        self.assertEqual(second.status_code, 201)
        self.assertEqual([row["title"] for row in self.client.get("/api/discussions/", **selected).json()["threads"]], ["Second course"])
        self.assertEqual(self.client.get(f'/api/discussions/{first.json()["thread"]["id"]}/', **selected).status_code, 404)

    def test_invalid_posts_do_not_create_content(self):
        for data in [{"title": "", "body": "x"}, {"title": "x", "body": "  "},
                     {"title": "x" * 161, "body": "x"}, {"title": "x", "body": "x", "course": 9}]:
            with self.subTest(data=data):
                self.assertEqual(self.post("/api/discussions/new/", data).status_code, 400)
        self.assertEqual(DiscussionThread.objects.count(), 0)
        thread = DiscussionThread.objects.create(course=self.course,
            author=Membership.objects.get(course=self.course, user=self.staff), title="Hello", body="World")
        self.assertEqual(self.post(f"/api/discussions/{thread.pk}/replies/", {"body": " "}).status_code, 400)
        self.assertEqual(DiscussionReply.objects.count(), 0)

    def test_member_removal_keeps_post_and_attribution(self):
        created = self.post("/api/discussions/new/", {"title": "Question", "body": "Hello"}).json()["thread"]
        member = Membership.objects.get(course=self.course, user=self.student)
        member.delete()
        self.client.force_login(self.staff)
        thread = self.client.get(f"/api/discussions/{created['id']}/").json()["thread"]
        self.assertEqual(thread["author"], "student")
        self.assertIsNone(DiscussionThread.objects.get(pk=created["id"]).author)

    def test_recent_posts_are_paginated(self):
        member = Membership.objects.get(course=self.course, user=self.student)
        for number in range(32):
            DiscussionThread.objects.create(course=self.course, author=member,
                title=f"Post {number}", body="Message")
        first = self.client.get("/api/discussions/").json()
        self.assertEqual(len(first["threads"]), 30)
        self.assertTrue(first["has_more"])
        second = self.client.get("/api/discussions/?offset=30").json()
        self.assertEqual(len(second["threads"]), 2)
        self.assertFalse(second["has_more"])

    def test_staff_settings_and_folders_control_student_posts(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.post("/api/discussions/settings/", {"require_folder": True, "allow_student_polls": False}).status_code, 200)
        folder = self.post("/api/discussions/folders/", {"action": "create", "name": "Assignments"}).json()["folders"][0]
        self.client.force_login(self.student)
        self.assertEqual(self.post("/api/discussions/new/", {"title": "Help", "body": "Question"}).status_code, 400)
        self.assertEqual(self.post("/api/discussions/new/", {"title": "Poll", "body": "Vote", "kind": "poll", "folder_ids": [folder["id"]], "options": ["A", "B"]}).status_code, 403)
        created = self.post("/api/discussions/new/", {"title": "Help", "body": "Question", "folder_ids": [folder["id"]]})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["thread"]["folders"][0]["name"], "Assignments")
        self.assertEqual(len(self.client.get(f'/api/discussions/?folder={folder["id"]}').json()["threads"]), 1)
        self.assertEqual(self.post("/api/discussions/settings/", {"allow_student_posts": False}).status_code, 403)

    def test_private_and_anonymous_posts_are_projected_by_role(self):
        other = get_user_model().objects.create_user("classmate")
        Membership.objects.create(course=self.course, user=other, role="student")
        private = self.post("/api/discussions/new/", {"title": "Private", "body": "Question", "visibility": "private"}).json()["thread"]
        anonymous = self.post("/api/discussions/new/", {"title": "Anonymous", "body": "Question", "anonymous": "classmates"}).json()["thread"]
        self.client.force_login(other)
        rows = self.client.get("/api/discussions/").json()["threads"]
        self.assertEqual([row["title"] for row in rows], ["Anonymous"])
        self.assertEqual(rows[0]["author"], "Anonymous")
        self.assertEqual(self.client.get(f'/api/discussions/{private["id"]}/').status_code, 404)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(f'/api/discussions/{anonymous["id"]}/').json()["thread"]["author"], "student")
        self.assertEqual(self.client.get(f'/api/discussions/{private["id"]}/').status_code, 200)

    def test_answers_followups_reactions_and_moderation(self):
        thread = self.post("/api/discussions/new/", {"title": "Question", "body": "Why?"}).json()["thread"]
        pk = thread["id"]
        self.assertEqual(self.post(f"/api/discussions/{pk}/answer/", {"kind": "instructor", "body": "No"}).status_code, 403)
        self.assertEqual(self.post(f"/api/discussions/{pk}/answer/", {"kind": "student", "body": "Because"}).status_code, 200)
        followup = self.post(f"/api/discussions/{pk}/replies/", {"body": "Another question"}).json()["reply"]
        self.assertEqual(self.post(f'/api/discussions/replies/{followup["id"]}/action/', {"action": "resolve", "value": True}).status_code, 200)
        self.assertEqual(self.post(f"/api/discussions/{pk}/action/", {"action": "bookmark", "value": True}).status_code, 200)
        self.assertTrue(self.client.get(f"/api/discussions/{pk}/").json()["thread"]["bookmarked"])
        self.client.force_login(self.staff)
        self.assertEqual(self.post(f"/api/discussions/{pk}/answer/", {"kind": "instructor", "body": "Staff answer"}).status_code, 200)
        self.assertEqual(self.post(f"/api/discussions/{pk}/answer/endorse/", {"value": True}).status_code, 200)
        self.assertEqual(self.post(f"/api/discussions/{pk}/action/", {"action": "pin", "value": True}).status_code, 200)
        self.assertEqual(self.post(f"/api/discussions/{pk}/action/", {"action": "lock", "value": True}).status_code, 200)
        self.client.force_login(self.student)
        self.assertEqual(self.post(f"/api/discussions/{pk}/replies/", {"body": "Blocked"}).status_code, 403)
        data = self.client.get(f"/api/discussions/{pk}/").json()
        self.assertTrue(data["thread"]["pinned"])
        self.assertTrue(data["answers"]["student"]["endorsed"])
        self.assertTrue(data["replies"][0]["resolved"])

    def test_poll_vote_and_statistics(self):
        thread = self.post("/api/discussions/new/", {"title": "Choose", "body": "One", "kind": "poll", "options": ["A", "B"]}).json()["thread"]
        pk = thread["id"]
        options = self.client.get(f"/api/discussions/{pk}/").json()["poll_options"]
        self.assertEqual(self.post(f"/api/discussions/{pk}/vote/", {"option_id": options[0]["id"]}).status_code, 200)
        detail = self.client.get(f"/api/discussions/{pk}/").json()
        self.assertEqual(detail["poll_options"][0]["votes_count"], 1)
        self.assertEqual(detail["my_vote"], options[0]["id"])
        self.client.force_login(self.staff)
        stats = self.client.get("/api/discussions/statistics/")
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.json()["polls"], 1)
        self.assertTrue(stats.json()["contributors"])
        self.assertIn("Member,Role,Posts,Followups,Answers,Post views", self.client.get("/api/discussions/statistics/export/").content.decode())
        self.assertEqual(self.post(f"/api/discussions/{pk}/action/", {"action": "lock", "value": True}).status_code, 200)
        self.client.force_login(self.student)
        self.assertEqual(self.post(f"/api/discussions/{pk}/vote/", {"option_id": options[1]["id"]}).status_code, 403)

    def test_anonymous_followup_hides_author_from_classmates(self):
        thread = self.post("/api/discussions/new/", {"title": "Question", "body": "Help"}).json()["thread"]
        self.assertEqual(self.post(f'/api/discussions/{thread["id"]}/replies/',
            {"body": "I have this question too", "anonymous": "classmates"}).status_code, 201)
        other = get_user_model().objects.create_user("classmate")
        Membership.objects.create(course=self.course, user=other, role="student")
        self.client.force_login(other)
        self.assertEqual(self.client.get(f'/api/discussions/{thread["id"]}/').json()["replies"][0]["author"], "Anonymous")
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(f'/api/discussions/{thread["id"]}/').json()["replies"][0]["author"], "student")

    def test_post_history_and_anonymity_controls(self):
        self.assertEqual(self.post("/api/discussions/new/", {"title": "Hidden", "body": "x", "anonymous": "everyone"}).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.post("/api/discussions/settings/", {"allow_anonymous_to_staff": True}).status_code, 200)
        self.client.force_login(self.student)
        thread = self.post("/api/discussions/new/", {"title": "First", "body": "Version one", "anonymous": "everyone"}).json()["thread"]
        pk = thread["id"]
        self.assertEqual(self.post(f"/api/discussions/{pk}/edit/", {"title": "Second", "body": "**Version two**", "editor_mode": "plain", "folder_ids": []}).status_code, 200)
        versions = self.client.get(f"/api/discussions/{pk}/history/").json()["revisions"]
        self.assertEqual([row["title"] for row in versions], ["First", "Second"])
        self.assertEqual(versions[1]["editor_mode"], "plain")
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(f"/api/discussions/{pk}/").json()["thread"]["author"], "Anonymous")
        self.assertEqual(self.client.get(f"/api/discussions/{pk}/history/").json()["revisions"][0]["editor_label"], "Anonymous")
        self.assertEqual(self.client.get("/api/discussions/statistics/").json()["contributors"][0]["posts"], 0)
        self.assertEqual(self.post(f"/api/discussions/{pk}/action/", {"action": "hide_history", "value": True}).status_code, 200)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(f"/api/discussions/{pk}/history/").status_code, 403)

    def test_attachments_are_private_and_course_scoped(self):
        thread = self.post("/api/discussions/new/", {"title": "File", "body": "See attached", "visibility": "private"}).json()["thread"]
        pk = thread["id"]
        uploaded = self.client.post(f"/api/discussions/{pk}/attachments/",
            {"file": SimpleUploadedFile("example.py", b"print(1)\n", content_type="text/plain")})
        self.assertEqual(uploaded.status_code, 201)
        attachment = uploaded.json()["attachment"]
        reply = self.post(f"/api/discussions/{pk}/replies/", {"body": "My traceback is attached."}).json()["reply"]
        reply_upload = self.client.post(f'/api/discussions/replies/{reply["id"]}/attachments/',
            {"file": SimpleUploadedFile("traceback.txt", b"ValueError: example\n", content_type="text/plain")})
        self.assertEqual(reply_upload.status_code, 201)
        reply_attachment = reply_upload.json()["attachment"]
        detail = self.client.get(f"/api/discussions/{pk}/").json()
        self.assertEqual([row["name"] for row in detail["attachments"]], ["example.py"])
        self.assertEqual([row["name"] for row in detail["replies"][0]["attachments"]], ["traceback.txt"])
        self.assertEqual(self.client.get(f'/api/discussions/attachments/{attachment["id"]}/').status_code, 200)
        self.assertEqual(self.client.get(f'/api/discussions/attachments/{reply_attachment["id"]}/').status_code, 200)
        other = get_user_model().objects.create_user("classmate")
        Membership.objects.create(course=self.course, user=other, role="student")
        self.client.force_login(other)
        self.assertEqual(self.client.get(f'/api/discussions/attachments/{attachment["id"]}/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/discussions/attachments/{reply_attachment["id"]}/').status_code, 404)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(f'/api/discussions/attachments/{attachment["id"]}/').status_code, 200)
        self.assertEqual(self.client.get(f'/api/discussions/attachments/{reply_attachment["id"]}/').status_code, 200)

    def test_members_cannot_attach_files_to_someone_elses_post_or_reply(self):
        thread = self.post("/api/discussions/new/", {"title": "Public file question", "body": "Help"}).json()["thread"]
        reply = self.post(f'/api/discussions/{thread["id"]}/replies/', {"body": "Student followup"}).json()["reply"]
        classmate = get_user_model().objects.create_user("attachment-classmate")
        Membership.objects.create(course=self.course, user=classmate, role="student")
        self.client.force_login(classmate)
        file = lambda: {"file": SimpleUploadedFile("example.txt", b"hello", content_type="text/plain")}
        self.assertEqual(self.client.post(f'/api/discussions/{thread["id"]}/attachments/', file()).status_code, 403)
        self.assertEqual(self.client.post(f'/api/discussions/replies/{reply["id"]}/attachments/', file()).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(f'/api/discussions/{thread["id"]}/attachments/', file()).status_code, 201)
        uploaded = self.client.post(f'/api/discussions/replies/{reply["id"]}/attachments/', file())
        self.assertEqual(uploaded.status_code, 201)
        self.assertEqual(self.post(f'/api/discussions/replies/{reply["id"]}/action/',
            {"action": "delete", "value": True}).status_code, 200)
        self.assertEqual(self.client.get(
            f'/api/discussions/attachments/{uploaded.json()["attachment"]["id"]}/').status_code, 404)

    def test_student_view_hides_staff_controls(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.post("/api/student-view/", {"enabled": True}).status_code, 200)
        self.assertFalse(self.client.get("/api/discussions/meta/").json()["staff"])
        self.assertEqual(self.post("/api/discussions/settings/", {"allow_student_posts": False}).status_code, 403)
        self.assertEqual(self.client.get("/api/discussions/statistics/export/").status_code, 403)

    def test_saved_draft_is_private_and_cleared_when_published(self):
        draft = {"title": "Work in progress", "body": "", "editor_mode": "plain", "kind": "question", "visibility": "public",
            "anonymous": "none", "folder_ids": [], "options": []}
        self.assertEqual(self.post("/api/discussions/draft/save/", draft).status_code, 200)
        self.assertEqual(self.client.get("/api/discussions/draft/").json()["draft"]["title"], "Work in progress")
        self.assertEqual(self.client.get("/api/discussions/draft/").json()["draft"]["editor_mode"], "plain")
        other = get_user_model().objects.create_user("classmate")
        Membership.objects.create(course=self.course, user=other, role="student")
        self.client.force_login(other)
        self.assertIsNone(self.client.get("/api/discussions/draft/").json()["draft"])
        self.client.force_login(self.student)
        self.assertEqual(self.post("/api/discussions/new/", {"title": "Finished", "body": "Question"}).status_code, 201)
        self.assertIsNone(self.client.get("/api/discussions/draft/").json()["draft"])

    def test_teacher_can_require_reading_before_student_posts(self):
        self.client.force_login(self.staff)
        note = self.post("/api/discussions/new/", {"title": "Read first", "body": "Instructions", "kind": "note"}).json()["thread"]
        pk = note["id"]
        self.assertEqual(self.post(f"/api/discussions/{pk}/action/", {"action": "required_reading", "value": True}).status_code, 200)
        self.assertEqual(self.post("/api/discussions/settings/", {"require_reading_before_posting": True}).status_code, 200)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get("/api/discussions/meta/").json()["reading"], {"unread": 1, "required": 1})
        self.assertEqual(self.post("/api/discussions/new/", {"title": "Question", "body": "Help"}).status_code, 403)
        self.assertEqual(self.post(f"/api/discussions/{pk}/action/", {"action": "read", "value": True}).status_code, 400)
        self.assertEqual(self.client.get(f"/api/discussions/{pk}/").status_code, 200)
        self.assertEqual(self.client.get("/api/discussions/meta/").json()["reading"]["required"], 0)
        self.assertEqual(self.post("/api/discussions/new/", {"title": "Question", "body": "Help"}).status_code, 201)

    def test_hybrid_search_ranks_exact_and_semantic_post_matches(self):
        exact = self.post("/api/discussions/new/", {
            "title": "HW4 requirements.toml file", "body": "The configuration file is missing from Canvas."
        }).json()["thread"]
        semantic = self.post("/api/discussions/new/", {
            "title": "Account access", "body": "Authentication credentials are rejected by the course site."
        }).json()["thread"]
        self.post("/api/discussions/new/", {
            "title": "List practice", "body": "Use a for loop to total the values."
        })

        literal = self.client.get("/api/discussions/?q=requirements.toml").json()["threads"]
        self.assertEqual([row["id"] for row in literal], [exact["id"]])
        self.assertEqual(literal[0]["search_match"]["source"], "Post")
        self.assertIn("requirements.toml", literal[0]["search_match"]["excerpt"])

        related = self.client.get("/api/discussions/?q=I+cannot+log+in+with+my+password").json()["threads"]
        self.assertEqual(related[0]["id"], semantic["id"])
        self.assertGreater(related[0]["search_match"]["score"], 0)

    def test_search_finds_answers_followups_and_nested_replies(self):
        thread = self.post("/api/discussions/new/", {
            "title": "General homework question", "body": "I need help with this week's work."
        }).json()["thread"]
        pk = thread["id"]
        self.client.force_login(self.staff)
        self.post(f"/api/discussions/{pk}/answer/", {
            "kind": "instructor", "body": "Create the conda environment from requirements.toml."
        })
        self.client.force_login(self.student)
        followup = self.post(f"/api/discussions/{pk}/replies/", {
            "body": "The notebook kernel keeps restarting during training."
        }).json()["reply"]
        self.post(f"/api/discussions/{pk}/replies/", {
            "body": "Reducing the epoch count fixed the runtime.", "parent_id": followup["id"]
        })

        answer_result = self.client.get("/api/discussions/?q=conda+requirements.toml").json()["threads"]
        self.assertEqual(answer_result[0]["id"], pk)
        self.assertEqual(answer_result[0]["search_match"]["source"], "Instructor answer")
        followup_result = self.client.get("/api/discussions/?q=kernel+restarting").json()["threads"]
        self.assertEqual(followup_result[0]["search_match"]["source"], "Followup")
        nested_result = self.client.get("/api/discussions/?q=epoch+count").json()["threads"]
        self.assertEqual(nested_result[0]["search_match"]["source"], "Followup reply")
        self.assertEqual(DiscussionSearchDocument.objects.filter(thread_id=pk).count(), 4)

    def test_search_respects_private_posts_courses_and_filters(self):
        private = self.post("/api/discussions/new/", {
            "title": "Private accommodation", "body": "My unique quasar deadline request.", "visibility": "private"
        }).json()["thread"]
        public = self.post("/api/discussions/new/", {
            "title": "Public deadline", "body": "The quasar project deadline is Friday."
        }).json()["thread"]
        other_course = Course.objects.create(title="Other search course", term="Pilot")
        Membership.objects.create(course=other_course, user=self.student, role="student")
        selected = {"HTTP_X_TRELLIS_COURSE": str(other_course.pk)}
        other = self.client.post("/api/discussions/new/", {
            "title": "Other course quasar", "body": "This must stay on the other board."
        }, content_type="application/json", **selected).json()["thread"]

        primary = self.client.get("/api/discussions/?q=quasar").json()["threads"]
        self.assertEqual({row["id"] for row in primary}, {private["id"], public["id"]})
        self.assertNotIn(other["id"], {row["id"] for row in primary})
        mine = self.client.get("/api/discussions/?q=quasar&filter=mine").json()["threads"]
        self.assertEqual({row["id"] for row in mine}, {private["id"], public["id"]})

        classmate = get_user_model().objects.create_user("search-classmate")
        Membership.objects.create(course=self.course, user=classmate, role="student")
        self.client.force_login(classmate)
        classmate_rows = self.client.get("/api/discussions/?q=quasar").json()["threads"]
        self.assertEqual([row["id"] for row in classmate_rows], [public["id"]])

        self.client.force_login(self.staff)
        staff_rows = self.client.get("/api/discussions/?q=quasar").json()["threads"]
        self.assertEqual({row["id"] for row in staff_rows}, {private["id"], public["id"]})

    def test_search_reindexes_edits_and_removes_deleted_followups(self):
        thread = self.post("/api/discussions/new/", {
            "title": "Recursion question", "body": "Where does the recursive base case go?"
        }).json()["thread"]
        pk = thread["id"]
        self.assertEqual(self.client.get("/api/discussions/?q=recursive+base+case").json()["threads"][0]["id"], pk)
        edited = self.post(f"/api/discussions/{pk}/edit/", {
            "title": "Dictionary question", "body": "How do mapping keys and values work?", "folder_ids": []
        })
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(self.client.get("/api/discussions/?q=recursive+base+case").json()["threads"], [])
        self.assertEqual(self.client.get("/api/discussions/?q=mapping+keys").json()["threads"][0]["id"], pk)

        followup = self.post(f"/api/discussions/{pk}/replies/", {
            "body": "The unique zephyr sentinel appears here."
        }).json()["reply"]
        self.assertEqual(self.client.get("/api/discussions/?q=zephyr+sentinel").json()["threads"][0]["id"], pk)
        self.assertEqual(self.post(f'/api/discussions/replies/{followup["id"]}/action/', {
            "action": "delete", "value": True
        }).status_code, 200)
        self.assertEqual(self.client.get("/api/discussions/?q=zephyr+sentinel").json()["threads"], [])
        self.assertFalse(DiscussionSearchDocument.objects.filter(content_type="followup", object_id=followup["id"]).exists())

    def test_teacher_issue_organizer_groups_repeated_problems_and_omits_isolated_questions(self):
        def member(username):
            user = get_user_model().objects.create_user(username)
            return Membership.objects.create(course=self.course, user=user, role="student")

        def question(author, title, body, answered=False):
            thread = DiscussionThread.objects.create(course=self.course, author=author,
                author_label=author.user.username, title=title, body=body)
            if answered:
                staff = Membership.objects.get(course=self.course, user=self.staff)
                DiscussionAnswer.objects.create(thread=thread, kind="instructor", body="Here is an explanation.",
                    last_editor=staff, last_editor_label="staff")
            return thread

        students = [Membership.objects.get(course=self.course, user=self.student)] + [
            member(f"issue-student-{number}") for number in range(1, 8)]
        login_posts = [
            question(students[0], "Cannot sign in", "My password and authentication credentials are rejected."),
            question(students[1], "Course login is failing", "The sign-in page will not accept my account password."),
            question(students[2], "Account access problem", "Authentication fails whenever I try to log in."),
            question(students[3], "Password rejected", "I cannot access the course because login is broken."),
        ]
        deadline_posts = [
            question(students[4], "Submission deadline blocked", "I cannot submit the project before the due date."),
            question(students[5], "Project upload is failing", "The submission error is blocking my deadline."),
        ]
        list_posts = [
            question(students[6], "Understanding list slicing", "How do sequence slices and indexes work?", answered=True),
            question(students[7], "List slice explanation", "Please clarify slicing a list by index.", answered=True),
        ]
        isolated = question(students[0], "One minor tuple question", "What punctuation creates a tuple?")
        other_course = Course.objects.create(title="Other issues", term="Pilot")
        other_member = Membership.objects.create(course=other_course,
            user=get_user_model().objects.create_user("other-issue-student"), role="student")
        DiscussionThread.objects.create(course=other_course, author=other_member,
            author_label="other", title="Cannot sign in", body="My password is rejected.")

        self.assertEqual(self.client.get("/api/discussions/issues/").status_code, 403)
        self.client.force_login(self.staff)
        response = self.client.get("/api/discussions/issues/")
        self.assertEqual(response.status_code, 200)
        issues = response.json()["issues"]
        by_priority = {row["priority"]: row for row in issues}
        self.assertEqual(set(by_priority), {"high", "medium", "low"})
        self.assertEqual({post["id"] for post in by_priority["high"]["posts"]},
            {thread.pk for thread in login_posts})
        self.assertEqual({post["id"] for post in by_priority["medium"]["posts"]},
            {thread.pk for thread in deadline_posts})
        self.assertEqual({post["id"] for post in by_priority["low"]["posts"]},
            {thread.pk for thread in list_posts})
        self.assertNotIn(isolated.pk, {post["id"] for issue in issues for post in issue["posts"]})
