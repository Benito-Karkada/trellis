"""Load a portable native course snapshot locally, preserving existing course edits."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Activity, ActivityFile, Course, CourseAsset, Lesson, Membership, Revision
from core.schema import validate_content
from core.studio import valid_path

DIGEST = re.compile(r"[a-f0-9]{64}\Z")
ASSET_URL = re.compile(r"(?:https?://[^/\s\"<>]+)?/api/assets/(\d+)/")


def read_bundle(path):
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 20000 or sum(m.size for m in members) > 512 * 1024 * 1024:
            raise CommandError("Course bundle exceeds local loading limits.")
        names = set()
        for member in members:
            name = PurePosixPath(member.name)
            if (not member.isfile() or name.is_absolute() or ".." in name.parts
                    or member.name in names or member.size > 128 * 1024 * 1024):
                raise CommandError("Unsafe or duplicate bundle member.")
            if member.name != "course.json" and not re.fullmatch(r"blobs/[a-f0-9]{64}", member.name):
                raise CommandError("Unexpected bundle member.")
            names.add(member.name)
        if "course.json" not in names or archive.getmember("course.json").size > 64 * 1024 * 1024:
            raise CommandError("Missing or oversized course manifest.")
        package = json.load(archive.extractfile("course.json"))
        if (not isinstance(package, dict) or set(package) != {"format", "key", "course", "metadata", "lessons", "assets"}
                or package["format"] != "trellis-course-v1"
                or not isinstance(package["key"], str) or not re.fullmatch(r"[a-z0-9-]{1,50}", package["key"])):
            raise CommandError("Expected a native Trellis course bundle.")
        if set(package["course"]) != {"title", "term"} or not isinstance(package["metadata"], dict):
            raise CommandError("Course bundles contain course content only.")
        if (not isinstance(package["lessons"], list) or len(package["lessons"]) > 500
                or not isinstance(package["assets"], list)):
            raise CommandError("Invalid course sections or assets.")
        used = set()
        asset_ids = set()
        part_ids = set()
        for asset in package["assets"]:
            if set(asset) != {"id", "sha256", "content_type"} or asset["id"] in asset_ids:
                raise CommandError("Invalid or duplicate course asset.")
            asset_ids.add(asset["id"])
            used.add(asset["sha256"])
        for lesson in package["lessons"]:
            if set(lesson) != {"id", "title", "position", "visibility", "metadata", "parts"} or lesson["visibility"] not in {"student", "staff"}:
                raise CommandError("Invalid course section.")
            for part in lesson["parts"]:
                if set(part) != {"id", "title", "position", "published_revision_id", "metadata", "revisions"} or part["id"] in part_ids:
                    raise CommandError("Invalid or duplicate course part.")
                part_ids.add(part["id"])
                revision_ids = set()
                numbers = set()
                for revision in part["revisions"]:
                    if set(revision) != {"revision_id", "revision_number", "content", "grading", "files"}:
                        raise CommandError("Invalid course revision.")
                    if revision["revision_id"] in revision_ids or revision["revision_number"] in numbers:
                        raise CommandError("Duplicate course revision.")
                    revision_ids.add(revision["revision_id"])
                    numbers.add(revision["revision_number"])
                    try:
                        validate_content(revision["content"])
                    except ValidationError as exc:
                        raise CommandError("Invalid native lesson content.") from exc
                    paths = set()
                    for file in revision["files"]:
                        if (set(file) != {"path", "visibility", "sha256"} or not valid_path(file["path"])
                                or file["path"] in paths or file["visibility"] not in {"student", "staff", "grader", "quarantine"}
                                or file["visibility"] == "student" and file["path"].startswith(("grader/", "solutions/"))):
                            raise CommandError("Invalid exercise file or visibility.")
                        paths.add(file["path"])
                        used.add(file["sha256"])
                if part["published_revision_id"] is not None and part["published_revision_id"] not in revision_ids:
                    raise CommandError("The published course revision is missing.")
        if any(not isinstance(value, str) or not DIGEST.fullmatch(value) for value in used):
            raise CommandError("Invalid file checksum.")
        if names != {"course.json", *("blobs/" + digest for digest in used)}:
            raise CommandError("Missing or unlisted course files.")
        blobs = {}
        for digest in used:
            data = archive.extractfile("blobs/" + digest).read()
            if hashlib.sha256(data).hexdigest() != digest:
                raise CommandError("Course file checksum mismatch.")
            blobs[digest] = data
    return package, blobs


def rewrite_assets(value, assets):
    if isinstance(value, list):
        return [rewrite_assets(item, assets) for item in value]
    if isinstance(value, dict):
        result = {key: rewrite_assets(item, assets) for key, item in value.items()}
        if value.get("type") == "image" and "asset_id" in value:
            try:
                result["asset_id"] = assets[int(value["asset_id"])]
            except (KeyError, ValueError, TypeError) as exc:
                raise CommandError("Lesson references a missing image.") from exc
        return result
    if isinstance(value, str):
        try:
            return ASSET_URL.sub(lambda match: f"/api/assets/{assets[int(match.group(1))]}/", value)
        except KeyError as exc:
            raise CommandError("Lesson references a missing image.") from exc
    return value


def local_accounts(course):
    users = get_user_model()
    for username, email, role, name in [
        ("studio-instructor", "instructor@trellis.local", "instructor", "Instructor"),
        ("student@trellis.local", "student@trellis.local", "student", "Student"),
    ]:
        user, created = users.objects.get_or_create(username=username, defaults={
            "email": email, "first_name": "Local", "last_name": name})
        if created:
            user.set_password("trellis-demo-2026")
            user.save()
        Membership.objects.get_or_create(user=user, course=course, defaults={"role": role})
        # Retain the old miniature demo and any work, but open the full course.
        Membership.objects.filter(user=user, course__metadata__local_demo=True).exclude(course=course).update(active=False)
    return users.objects.get(username="studio-instructor")


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("bundle", type=Path)

    @transaction.atomic
    def handle(self, bundle, **options):
        if not settings.DEBUG:
            raise CommandError("This course loader is for local development only.")
        try:
            package, blobs = read_bundle(bundle)
        except (OSError, tarfile.TarError, ValueError, TypeError, KeyError) as exc:
            raise CommandError("Could not validate the local course bundle.") from exc
        existing = Course.objects.filter(metadata__local_course_key=package["key"]).first()
        if existing:
            local_accounts(existing)
            self.stdout.write("Full course already loaded; local edits and saved work preserved.")
            return
        course = Course.objects.create(title=package["course"]["title"], term=package["course"]["term"],
            metadata={**package["metadata"], "local_course_key": package["key"],
                      "local_bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest()})
        author = local_accounts(course)
        stored = {}
        for digest, data in blobs.items():
            name = f"course-bundles/{package['key']}/{digest}"
            if default_storage.exists(name):
                with default_storage.open(name, "rb") as stream:
                    if hashlib.sha256(stream.read()).hexdigest() != digest:
                        raise CommandError("A local course file conflicts with the bundle.")
                stored[digest] = name
            else:
                stored[digest] = default_storage.save(name, ContentFile(data))
        assets = {}
        for item in package["assets"]:
            asset = CourseAsset.objects.create(course=course, source_path=f"bundle/{item['id']}",
                content_type=item["content_type"], blob=stored[item["sha256"]])
            assets[item["id"]] = asset.pk
        part_count = 0
        file_count = 0
        for item in package["lessons"]:
            lesson = Lesson.objects.create(course=course, title=item["title"], position=item["position"],
                visibility=item["visibility"], metadata=item["metadata"])
            for entry in item["parts"]:
                part = Activity.objects.create(lesson=lesson, title=entry["title"], position=entry["position"],
                    metadata={**entry["metadata"], "local_bundle_part_id": entry["id"]})
                for version in entry["revisions"]:
                    revision = Revision.objects.create(activity=part, number=version["revision_number"],
                        content=rewrite_assets(version["content"], assets), grading=version["grading"], created_by=author)
                    ActivityFile.objects.bulk_create([ActivityFile(revision=revision, path=file["path"],
                        visibility=file["visibility"], sha256=file["sha256"], blob=stored[file["sha256"]])
                        for file in version["files"]])
                    file_count += len(version["files"])
                    if version["revision_id"] == entry["published_revision_id"]:
                        part.published_revision = revision
                        part.save(update_fields=["published_revision"])
                part_count += 1
        self.stdout.write(self.style.SUCCESS(
            f"Full course loaded: {len(package['lessons'])} sections, {part_count} parts, "
            f"{file_count} exercise files and {len(assets)} images/assets."))
