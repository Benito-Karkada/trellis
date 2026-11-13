"""Import downloaded coding activities into Trellis without legacy grader code."""
import hashlib
import json
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.schema import validate_content
from core.coding_content import clean_prompt, local_test_lines, DIRECTIVE
from core.models import Activity, ActivityFile, Course, Membership, Revision
from .import_programming_quizzes import prompt_from_source


def normalized(value):
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def text_files(directory):
    if not directory.exists():
        return []
    return [path for path in sorted(directory.rglob("*")) if path.is_file() and "__pycache__" not in path.parts]


def instruction_nodes(source):
    paragraphs=[];lines=[]
    def flush():
        if lines:
            paragraphs.append({'type':'element','tag':'p','children':[{'type':'text','text':' '.join(lines)}]});lines.clear()
    tests=local_test_lines(source)
    for index,line in enumerate(source.splitlines()):
        if index in tests:continue
        stripped=line.strip()
        if stripped.startswith('#Below are some lines'):break
        if not stripped.startswith('#'):continue
        text=stripped[1:].strip()
        if text in {'Add your code here!','Write your code here!'}:continue
        if not text:flush()
        else:lines.append(text)
    flush()
    return clean_prompt(paragraphs or [{'type':'text','text':prompt_from_source(source)}])


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--source", type=Path, default=Path("/course-var/vocareum-coding-archives"))
        parser.add_argument("--refresh", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        source = options["source"]
        report_path = source / "translation-report.json"
        if not report_path.exists():
            raise CommandError("Prepare the downloaded archives before importing them.")
        report = json.loads(report_path.read_text())
        course = Course.objects.order_by("pk").first()
        if course is None:
            raise CommandError("Import the course before its coding archives.")
        membership = Membership.objects.filter(course=course, role__in=["instructor", "head_ta"]).select_related("user").first()
        author = membership.user if membership else get_user_model().objects.filter(is_superuser=True).first()
        if author is None:
            raise CommandError("An instructor account is required.")

        activities = list(Activity.objects.filter(lesson__course=course, metadata__kind="coding", deleted_at=None)
                          .select_related("published_revision"))
        by_title = {}
        for activity in activities:
            by_title.setdefault(normalized(activity.title), []).append(activity)

        imported = ready = review = skipped = 0
        for manifest_path in sorted(source.glob("exercises/*/*/manifest.json")):
            directory = manifest_path.parent
            manifest = json.loads(manifest_path.read_text())
            matches = by_title.get(normalized(manifest["part_name"]), [])
            if len(matches) != 1:
                raise CommandError(f"Expected one course activity for {manifest['part_name']}; found {len(matches)}.")
            activity = matches[0]
            previous = activity.revisions.order_by("-number").first()
            if (not options["refresh"] and previous and
                    previous.grading.get("vocareum_part_id") == str(manifest["part_id"])):
                skipped += 1
                continue

            if previous and activity.published_revision_id!=previous.pk:raise CommandError('Publish or discard the existing draft before importing '+activity.title)
            relative = str(directory.relative_to(source))
            translation = report.get(relative, {"status": "needs_review", "reason": "No translation result."})
            student_paths = [p for p in text_files(directory / "startercode")
                             if not p.name.startswith("sample_answer") and p.name != "full_results.txt"]
            if not student_paths:
                raise CommandError(f"No student files found for {manifest['part_name']}.")
            entrypoint = translation.get("entrypoint")
            if not entrypoint or not any(p.name == entrypoint for p in student_paths):
                entrypoint = next((p.name for p in student_paths if p.suffix == ".py"), student_paths[0].name)
            source_code = next((p.read_text(errors="replace") for p in student_paths if p.name == entrypoint), "")

            grading = {
                "maximum_points": str((previous.grading if previous else {}).get("maximum_points", "1")),
                "entrypoint": entrypoint,
                "placeholder": False,
                "source": "coursespace_vocareum_archive",
                "vocareum_part_id": str(manifest["part_id"]),
                "review_required": translation.get("status") != "ready",
            }
            definition_path = directory / "definition.json"
            if translation.get("status") == "ready" and definition_path.exists():
                grading["definition"] = json.loads(definition_path.read_text())
                ready += 1
            else:
                grading["import_warning"] = translation.get("reason", "Tests require staff review.")
                review += 1

            revision = Revision.objects.create(
                activity=activity,
                number=(previous.number + 1 if previous else 1),
                created_by=author,
                content={"version": 1, "blocks": [{"id": "instructions", "type": "coding",
                    "prompt": instruction_nodes(source_code)}]},
                grading=grading,
            )
            validate_content(revision.content)
            files = []
            for path in student_paths:
                files.append((path.name, "student", path.read_bytes()))
            files.append(("full_results.txt", "student", b""))
            if "definition" in grading:
                files.append(("grader/tests.json", "grader",
                              (json.dumps(grading["definition"], indent=2) + "\n").encode()))
                dynamic=grading['definition'].get('random_cases')
                if dynamic:
                    reference_path=directory/'native-reference.py'
                    if not reference_path.is_file():raise CommandError('Missing independently authored random-test reference.')
                    files.append((dynamic['oracle_path'],'grader',reference_path.read_bytes()))
            else:
                files.append(("grader/import-review.json", "grader",
                              (json.dumps({"status": "needs_review", "reason": grading["import_warning"],
                                           "source_manifest": relative + "/manifest.json"}, indent=2) + "\n").encode()))
            for sample in text_files(directory / "private"):
                if sample.name.startswith("sample_answer") and sample.suffix == ".py":
                    files.append((f"solutions/{sample.name}", "staff", sample.read_bytes()))
            for path, visibility, raw in files:
                ActivityFile.objects.create(revision=revision, path=path, visibility=visibility,
                    blob=ContentFile(raw, name=Path(path).name), sha256=hashlib.sha256(raw).hexdigest())
            activity.metadata = {**activity.metadata, "placeholder": False,
                                 "vocareum_part_id": str(manifest["part_id"]),
                                 "grading_review_required": grading["review_required"]}
            activity.published_revision = revision
            activity.save(update_fields=["metadata", "published_revision"])
            imported += 1

        self.stdout.write(self.style.SUCCESS(
            f"Imported {imported} coding activities ({ready} ready, {review} needing grading review); kept {skipped}."))
