"""Keep contiguous presentation components together in their original unit order."""
import copy
from pathlib import PurePosixPath
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from core.models import Activity, Revision, ImportRecord, ActivityProgress
from core.schema import validate_content


def presentation_runs(activities):
    run = []
    unit = None
    for activity in activities:
        path = activity.metadata.get("source_path")
        current_unit = str(PurePosixPath(path).parent) if path else None
        eligible = (path and activity.metadata.get("kind") in {"reading", "video"}
                    and activity.metadata.get("category") == "content")
        if not eligible or current_unit != unit:
            if run: yield run
            run = []
        if eligible: run.append(activity)
        unit = current_unit
    if run: yield run


class Command(BaseCommand):
    @transaction.atomic
    def handle(self, *args, **options):
        grouped = removed = 0
        lesson_ids = Activity.objects.filter(deleted_at=None).values_list("lesson_id", flat=True).distinct()
        for lesson_id in list(lesson_ids):
            activities = Activity.objects.filter(lesson_id=lesson_id, deleted_at=None).select_related(
                "published_revision").order_by("position", "pk")
            for run in presentation_runs(activities):
                videos = [a for a in run if a.metadata.get("kind") == "video"]
                if len(run) < 2 or not videos: continue
                if any(a.published_revision is None or a.published_revision.files.exists() for a in run): continue
                primary = videos[0]
                blocks = []
                for activity in run:
                    for block in copy.deepcopy(activity.published_revision.content["blocks"]):
                        block["id"] = f"part_{activity.pk}_{block['id']}"
                        blocks.append(block)
                content = {"version":1, "blocks":blocks}
                validate_content(content)
                revision = Revision.objects.create(activity=primary,
                    number=primary.revisions.order_by("-number").first().number+1,
                    content=content, grading={"maximum_points":"0"},
                    created_by=primary.published_revision.created_by)
                for activity in run:
                    for record in ImportRecord.objects.filter(revision=activity.published_revision):
                        ImportRecord.objects.create(revision=revision, source_path=record.source_path,
                            raw_xml=record.raw_xml, candidate=record.candidate,
                            warnings=record.warnings, status=record.status)
                if len(videos) > 1:
                    primary.title = primary.metadata.get("group", primary.title)
                primary.position = run[0].position
                primary.metadata["combined_sources"] = [source for a in run for source in
                    a.metadata.get("combined_sources", [a.metadata["source_path"]])]
                primary.published_revision = revision
                primary.save()
                # A previously viewed video alone does not complete its newly joined text.
                progress = list(ActivityProgress.objects.filter(activity__in=run))
                for user_id in {p.user_id for p in progress}:
                    states = [p for p in progress if p.user_id == user_id]
                    ActivityProgress.objects.update_or_create(user_id=user_id, activity=primary,
                        defaults={"viewed":any(p.viewed for p in states),
                                  "completed":len(states)==len(run) and all(p.completed for p in states)})
                for activity in run:
                    if activity.pk != primary.pk:
                        activity.deleted_at = timezone.now()
                        activity.metadata["combined_into"] = primary.pk
                        activity.save(update_fields=["deleted_at", "metadata"])
                        removed += 1
                grouped += 1
        self.stdout.write(f"Grouped {grouped} presentation parts; removed {removed} separate navigation entries.")
