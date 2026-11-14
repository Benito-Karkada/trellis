import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from core.management.commands.import_course_transfer import read_bundle
from core.models import Course, ActivityFile, Revision


class CourseTransferTests(TestCase):
    def bundle(self, folder, fixture=None, corrupt=False, extra=None):
        data = b"print('hello')\n"
        name = "activity-files/example.py"
        fixture = fixture if fixture is not None else [
            {"model": "core.course", "pk": 1, "fields": {"title": "CS 1301", "term": "POC"}},
            {"model": "core.lesson", "pk": 1, "fields": {"course": 1, "title": "Lesson"}},
            {"model": "core.activity", "pk": 1, "fields": {"lesson": 1, "title": "Exercise", "published_revision": 1}},
            {"model": "core.revision", "pk": 1, "fields": {"activity": 1, "number": 1, "created_by": None,
                "created_at": "2026-09-01T00:00:00Z", "content": {"blocks": []}, "grading": {"maximum_points": 5}}},
            {"model": "core.activityfile", "pk": 1, "fields": {"revision": 1, "path": "main.py", "visibility": "student",
                "blob": name, "sha256": hashlib.sha256(data).hexdigest()}},
        ]
        manifest = {name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}}
        entries = {"course.json": json.dumps(fixture).encode(), "manifest.json": json.dumps(manifest).encode(),
                   "blobs/" + name: b"changed" if corrupt else data}
        if extra:
            entries[extra] = b"unexpected"
        path = Path(folder) / "course.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for entry, payload in entries.items():
                info = tarfile.TarInfo(entry); info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
        return path

    def test_import_preserves_file_paths_and_published_revision_without_accounts(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=Path(folder) / "media"):
            call_command("import_course_transfer", self.bundle(folder), stdout=io.StringIO())
            revision = Revision.objects.get()
            self.assertEqual(revision.activity.published_revision_id, revision.pk)
            self.assertFalse(revision.created_by.is_active)
            self.assertFalse(revision.created_by.has_usable_password())
            self.assertEqual(revision.created_by.membership_set.count(), 0)
            with ActivityFile.objects.get().blob.open("rb") as stream:
                self.assertEqual(stream.read(), b"print('hello')\n")
            with self.assertRaisesMessage(CommandError, "Target already contains a course"):
                call_command("import_course_transfer", self.bundle(folder), stdout=io.StringIO())

    def test_rejects_account_records_and_corrupt_or_unsafe_files(self):
        with tempfile.TemporaryDirectory() as folder:
            for kwargs in (
                {"fixture": [{"model": "auth.user", "pk": 1, "fields": {}}]},
                {"fixture": [{"model": "core.course", "pk": 1, "fields": {"title": "Course", "canvas_context": "invalid field"}}]},
                {"corrupt": True}, {"extra": "../outside"}, {"extra": "unlisted.txt"},
            ):
                with self.assertRaises(CommandError):
                    read_bundle(self.bundle(folder, **kwargs))
        self.assertFalse(Course.objects.exists())
