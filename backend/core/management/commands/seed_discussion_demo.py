"""Populate a selected local course with original, fictional discussion activity."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.demo_data.discussions import NOTES, POLLS, QUESTIONS
from core.discussion_search import refresh_thread_index
from core.models import (Course, DiscussionAnswer, DiscussionFolder, DiscussionPollOption,
    DiscussionPollVote, DiscussionPostRevision, DiscussionReply, DiscussionReplyLike,
    DiscussionThread, DiscussionThreadState, Membership)


DEMO_KEY = "fictional_discussion_demo_v1"


class Command(BaseCommand):
    help = "Add fictional discussion posts, answers, and demo participants to one local course. Safe to rerun."

    def add_arguments(self, parser):
        parser.add_argument("--course-id", required=True, type=int)

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Discussion demo data is available only with DEBUG=1.")
        try:
            course = Course.objects.select_for_update().get(pk=options["course_id"])
        except Course.DoesNotExist:
            raise CommandError("Choose an existing local course ID.")
        if DEMO_KEY in course.metadata:
            self.stdout.write("This course already has the fictional discussion demo. Existing edits are preserved.")
            return

        def participant(number, role):
            label = f"Student {number:02d} (demo)" if role == "student" else (
                "Course staff (demo)" if role == "instructor" else "Teaching assistant (demo)")
            user, created = get_user_model().objects.get_or_create(
                username=f"demo-discussion-{course.pk}-{number:02d}", defaults={"first_name": label})
            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
            elif user.has_usable_password():
                raise CommandError("A demo username is already in use; no existing account was changed.")
            member, created = Membership.objects.get_or_create(course=course, user=user,
                defaults={"role": role, "source": "discussion_demo", "external_ids": {"demo_dataset": DEMO_KEY}})
            if not created and member.source != "discussion_demo":
                raise CommandError("An existing enrollment conflicts with a demo participant.")
            return member, label

        students = [participant(number, "student") for number in range(1, 19)]
        instructor, instructor_label = participant(90, "instructor")
        ta, ta_label = participant(91, "ta")
        members = [member for member, _ in students] + [instructor, ta]
        folders = {}
        for folder in dict.fromkeys([q[0] for q in QUESTIONS] + [n[0] for n in NOTES] + [p[0] for p in POLLS]):
            folders[folder], _ = DiscussionFolder.objects.get_or_create(course=course, name=folder,
                defaults={"position": course.discussion_folders.count()})
        now = timezone.now()
        thread_ids = []

        def post(folder, title, body, author, label, posted, kind="question", pinned=False):
            thread = DiscussionThread.objects.create(course=course, author=author, author_label=label,
                title=title, body=body, kind=kind, pinned=pinned)
            thread.folders.add(folders[folder])
            DiscussionThread.objects.filter(pk=thread.pk).update(created_at=posted, updated_at=posted)
            revision = DiscussionPostRevision.objects.create(thread=thread, version=1,
                title=title, body=body, editor_label=label)
            DiscussionPostRevision.objects.filter(pk=revision.pk).update(created_at=posted)
            thread_ids.append(thread.pk)
            return thread

        for index, (folder, title, body, answer) in enumerate(QUESTIONS):
            author, label = students[index % len(students)]
            posted = now - timedelta(days=12) + timedelta(hours=index * 6)
            thread = post(folder, title, body, author, label, posted)
            if answer:
                answerer, answer_label = (ta, ta_label) if index % 2 else (instructor, instructor_label)
                row = DiscussionAnswer.objects.create(thread=thread, kind="instructor", body=answer,
                    last_editor=answerer, last_editor_label=answer_label)
                DiscussionAnswer.objects.filter(pk=row.pk).update(updated_at=posted + timedelta(minutes=25))
            if index % 3 == 0:
                helper, helper_label = students[(index + 5) % len(students)]
                student_answer = DiscussionAnswer.objects.create(thread=thread, kind="student",
                    body=f"For “{title}”, I would start with two values and predict each step before running the trace.",
                    last_editor=helper, last_editor_label=helper_label, endorsed=bool(answer))
                DiscussionAnswer.objects.filter(pk=student_answer.pk).update(updated_at=posted + timedelta(minutes=12))
            followup_author, followup_label = author, label
            followup = DiscussionReply.objects.create(thread=thread, author=followup_author,
                author_label=followup_label, body=(f"Revisiting “{title}”: I tried a tiny input, and the explanation helped." if answer
                    else f"I have a similar question about “{title}”. Could we see another small example?"), resolved=bool(answer))
            DiscussionReply.objects.filter(pk=followup.pk).update(created_at=posted + timedelta(minutes=40))
            if index % 2 == 0:
                reply = DiscussionReply.objects.create(thread=thread, parent=followup,
                    author=ta, author_label=ta_label,
                    body=f"Try explaining “{title}” in your own words before changing the code." if answer
                        else f"For “{title}”, please include your smallest input; we are collecting examples to review.")
                DiscussionReply.objects.filter(pk=reply.pk).update(created_at=posted + timedelta(minutes=50))
            DiscussionReplyLike.objects.create(reply=followup, membership=students[(index + 7) % len(students)][0])
            DiscussionThread.objects.filter(pk=thread.pk).update(updated_at=posted + timedelta(minutes=50))

        for index, (folder, title, body) in enumerate(NOTES):
            post(folder, title, body, instructor, instructor_label,
                now - timedelta(days=2, hours=index), kind="note", pinned=index < 2)
        for index, (folder, title, body, labels) in enumerate(POLLS):
            thread = post(folder, title, body, ta, ta_label, now - timedelta(days=1, hours=index), kind="poll")
            choices = [DiscussionPollOption.objects.create(thread=thread, label=label, position=position)
                for position, label in enumerate(labels)]
            for position, (student, _) in enumerate(students):
                DiscussionPollVote.objects.create(thread=thread, membership=student,
                    option=choices[(position + index) % len(choices)])
        for position, thread_id in enumerate(thread_ids):
            thread = DiscussionThread.objects.get(pk=thread_id)
            for index, (student, _) in enumerate(students):
                if (position + index) % 4 == 0:
                    continue
                DiscussionThreadState.objects.create(thread=thread, membership=student,
                    read_at=min(now, thread.updated_at + timedelta(hours=2 + index)),
                    liked=(position + index) % 5 == 0, bookmarked=(position + index) % 11 == 0,
                    following=(position + index) % 7 == 0)
            refresh_thread_index(thread_id)
        course.metadata = {**course.metadata, DEMO_KEY: {"thread_ids": thread_ids,
            "member_ids": [member.pk for member in members], "seeded_at": now.isoformat()}}
        course.save(update_fields=["metadata"])
        self.stdout.write(self.style.SUCCESS(
            f"Added {len(thread_ids)} fictional posts, 18 demo students, and 2 demo staff. "
            "Demo accounts have no usable password. Existing posts and enrollments were preserved."))
