"""Load a validated course-only bundle into an empty deployment database."""
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile

from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.exceptions import FieldDoesNotExist
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import BaseCommand, CommandError, call_command
from django.db import transaction

from core.models import Course

ALLOWED = {"core." + name for name in (
    "course", "lesson", "activity", "revision", "activityfile", "courseasset", "importrecord",
)}


def read_bundle(path):
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 50000 or sum(m.size for m in members) > 512 * 1024 * 1024:
            raise CommandError("Bundle exceeds import limits")
        names = set()
        for member in members:
            name = PurePosixPath(member.name)
            if (not member.isfile() or name.is_absolute() or ".." in name.parts
                    or member.name in names or member.size > 128 * 1024 * 1024):
                raise CommandError("Unsafe or duplicate bundle entry")
            names.add(member.name)
        if not {"course.json", "manifest.json"}.issubset(names):
            raise CommandError("Bundle is missing its fixture or manifest")
        fixture = json.load(archive.extractfile("course.json"))
        manifest = json.load(archive.extractfile("manifest.json"))
        for record in fixture:
            if record["model"] not in ALLOWED:
                raise CommandError("Bundle includes non-content records")
            fields = record["fields"]
            if record["model"] == "core.course" and (fields.get("lti_registration") or fields.get("canvas_context_id")):
                raise CommandError("Course integration credentials/connections must be provisioned separately")
            if record["model"] == "core.importrecord" and fields.get("reviewer") is not None:
                raise CommandError("Imported reviewer identities are not allowed")
            if record["model"] == "core.revision" and fields.get("created_by") is not None:
                raise CommandError("Imported author identities are not allowed")
            blob = fields.get("blob") or fields.get("source_archive")
            if blob and blob not in manifest:
                raise CommandError("Referenced file is absent from manifest")
            if fields.get("sha256") and blob and fields["sha256"] != manifest[blob]["sha256"]:
                raise CommandError("Activity file digest does not match manifest")
        try:
            # Validate fixture field names/types before uploading any private files.
            for _ in serializers.deserialize("python", fixture):
                pass
        except (serializers.base.DeserializationError, FieldDoesNotExist, TypeError, ValueError) as exc:
            raise CommandError("Fixture does not match the current course schema") from exc
        if names != {"course.json", "manifest.json", *("blobs/" + name for name in manifest)}:
            raise CommandError("Bundle contains unlisted files")
        blobs = {}
        for name, metadata in manifest.items():
            path_name = PurePosixPath(name)
            if path_name.is_absolute() or ".." in path_name.parts:
                raise CommandError("Unsafe blob path")
            data = archive.extractfile("blobs/" + name).read()
            if len(data) != metadata["size"] or hashlib.sha256(data).hexdigest() != metadata["sha256"]:
                raise CommandError("File checksum mismatch: " + name)
            blobs[name] = data
    return fixture, blobs


def save_blob(item):
    name, data = item
    if default_storage.exists(name):
        with default_storage.open(name, "rb") as stream:
            if hashlib.sha256(stream.read()).digest() != hashlib.sha256(data).digest():
                raise CommandError("Refusing to overwrite a different existing file: " + name)
        return
    saved = default_storage.save(name, ContentFile(data))
    if saved != name:
        default_storage.delete(saved)
        raise CommandError("File collision during upload: " + name)


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("bundle", type=Path)

    def handle(self, bundle, **options):
        # Never restore a dump over an existing course or student database.
        if Course.objects.exists():
            raise CommandError("Target already contains a course; refusing to replace existing data")
        fixture, blobs = read_bundle(bundle)
        self.stdout.write(f"Validated {len(fixture)} content records and {len(blobs)} files")
        with ThreadPoolExecutor(max_workers=8) as pool:
            pending = deque()
            for index, item in enumerate(blobs.items(), 1):
                pending.append(pool.submit(save_blob, item))
                if len(pending) >= 16:
                    pending.popleft().result()
                if index % 100 == 0:
                    self.stdout.write(f"Uploading private files: {index}/{len(blobs)}", ending="\n")
            for future in pending:
                future.result()
        with transaction.atomic():
            if Course.objects.select_for_update().exists():
                raise CommandError("Course created during upload; import stopped")
            user, created = get_user_model().objects.get_or_create(username="course-content-import",
                defaults={"is_active": False, "is_staff": False, "is_superuser": False})
            if not created:
                raise CommandError("Content import identity already exists; review before retrying")
            user.set_unusable_password(); user.save()
            for record in fixture:
                if record["model"] == "core.revision":
                    record["fields"]["created_by"] = user.pk
            with tempfile.TemporaryDirectory(prefix="course-fixture-") as folder:
                path = Path(folder) / "course.json"
                path.touch(mode=0o600)
                path.write_text(json.dumps(fixture))
                call_command("loaddata", str(path), verbosity=0)
        self.stdout.write(self.style.SUCCESS("Course imported: " + json.dumps(dict(Counter(r["model"] for r in fixture)))))
