import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from core.models import Activity, ActivityProgress, Course, CourseAsset, Membership
from core.schema import student_projection


@override_settings(DEBUG=True)
class LocalCourseTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        settings = override_settings(MEDIA_ROOT=Path(self.folder.name) / "media")
        settings.enable()
        self.addCleanup(settings.disable)

    def bundle(self, corrupt=False, alter=None):
        blobs = {}
        def blob(data):
            digest = hashlib.sha256(data).hexdigest()
            blobs[digest] = data
            return digest
        image = blob(b"synthetic image")
        student = blob(b"print(2 + 3)\n")
        solution = blob(b"print(5)\n")
        definition = {"version": 1, "cases": [{"id": "sum", "label": "Addition", "action": "stdout", "expected": "5\n"}]}
        grader = blob(json.dumps(definition).encode())
        revision = {"revision_id": 100, "revision_number": 1,
            "content": {"version": 1, "blocks": [
                {"id": "image", "type": "image", "asset_id": 41, "alt": "Example"},
                {"id": "intro", "type": "paragraph", "content": [{"type": "image", "src": "/api/assets/41/", "alt": "Example"}]},
                {"id": "code", "type": "coding", "prompt": [{"type": "text", "text": "Print five."}]}]},
            "grading": {"entrypoint": "main.py", "maximum_points": "3", "definition": definition},
            "files": [{"path": "main.py", "visibility": "student", "sha256": student},
                      {"path": "solutions/sample_answer.py", "visibility": "staff", "sha256": solution},
                      {"path": "grader/tests.json", "visibility": "grader", "sha256": grader}]}
        draft = copy.deepcopy(revision)
        draft.update(revision_id=101, revision_number=2)
        package = {"format": "trellis-course-v1", "key": "test-course",
            "course": {"title": "Full CS 1301", "term": "Local course"}, "metadata": {},
            "assets": [{"id": 41, "sha256": image, "content_type": "image/png"}],
            "lessons": [{"id": 7, "title": "Chapter 1.1", "position": 0, "visibility": "student", "metadata": {},
                "parts": [{"id": 90, "title": "Exercise", "position": 0, "published_revision_id": 100,
                           "metadata": {"kind": "coding"}, "revisions": [revision, draft]}]}]}
        if alter:
            alter(package)
        path = Path(self.folder.name) / "course.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            data = json.dumps(package).encode()
            info = tarfile.TarInfo("course.json"); info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
            for digest, data in blobs.items():
                if corrupt and digest == student:
                    data = b"changed file"
                info = tarfile.TarInfo("blobs/" + digest); info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def load(self, path):
        call_command("load_local_course", path, stdout=io.StringIO())

    def test_load_preserves_published_and_draft_content_and_private_files(self):
        self.load(self.bundle())
        part = Activity.objects.get()
        self.assertEqual(part.published_revision.number, 1)
        self.assertEqual(part.revisions.order_by("-number").first().number, 2)
        self.assertEqual([f["path"] for f in student_projection(part.published_revision)["files"]], ["main.py"])
        with part.published_revision.files.get(path="main.py").blob.open("rb") as stream:
            self.assertEqual(stream.read(), b"print(2 + 3)\n")
        asset = CourseAsset.objects.get()
        self.assertEqual(part.published_revision.content["blocks"][0]["asset_id"], asset.pk)
        self.assertEqual(part.published_revision.content["blocks"][1]["content"][0]["src"], f"/api/assets/{asset.pk}/")
        self.assertEqual(Membership.objects.filter(active=True).count(), 2)
        self.assertFalse(Course.objects.get().canvas_context_id)

    def test_loading_again_preserves_edits_and_passwords(self):
        bundle = self.bundle()
        self.load(bundle)
        part = Activity.objects.get()
        part.title = "My edited exercise"; part.save()
        user = get_user_model().objects.get(username="studio-instructor")
        user.set_password("my-custom-local-password"); user.save()
        self.load(bundle)
        part.refresh_from_db(); user.refresh_from_db()
        self.assertEqual(Course.objects.count(), 1)
        self.assertEqual(part.title, "My edited exercise")
        self.assertTrue(user.check_password("my-custom-local-password"))

    def test_full_course_replaces_the_mini_demo_in_navigation_without_deleting_work(self):
        call_command("seed_demo", stdout=io.StringIO())
        user = get_user_model().objects.get(username="studio-instructor")
        old = Activity.objects.get(metadata__demo_key="sum")
        ActivityProgress.objects.create(user=user, activity=old, score=3, maximum=3, completed=True)
        self.load(self.bundle())
        self.assertTrue(ActivityProgress.objects.get(user=user, activity=old).completed)
        active = Membership.objects.get(user=user, active=True)
        self.assertEqual(active.course.title, "Full CS 1301")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/api/outline/").json()["title"], "Full CS 1301")

    def test_corrupt_file_is_rejected_without_loading_a_course(self):
        with self.assertRaises(CommandError):
            self.load(self.bundle(corrupt=True))
        self.assertFalse(Course.objects.exists())

    def test_account_payloads_and_private_student_paths_are_rejected(self):
        with self.assertRaises(CommandError):
            self.load(self.bundle(alter=lambda p: p.update(accounts=[{"email": "not-course-content"}])))
        def expose(package):
            package["lessons"][0]["parts"][0]["revisions"][0]["files"][1]["visibility"] = "student"
        with self.assertRaises(CommandError):
            self.load(self.bundle(alter=expose))
        self.assertFalse(Course.objects.exists())

    @override_settings(DEBUG=False)
    def test_loader_is_local_only(self):
        with self.assertRaises(CommandError):
            self.load(self.bundle())
