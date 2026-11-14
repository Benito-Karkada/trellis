"""Upgrade only recognized zero-point surveys; retain the original import records."""
from django.db import transaction
from django.db.models import F
from core.importers.edx import parse_problem_xml
from core.models import ImportRecord, Revision
from core.schema import validate_content

with transaction.atomic():
    count = 0
    records = ImportRecord.objects.filter(revision__activity__published_revision_id=F("revision_id"),
                                          raw_xml__contains="customresponse")
    for record in list(records):
        old = record.revision
        if not old.grading.get("review_required"):
            continue
        candidate = parse_problem_xml(record.raw_xml)
        if candidate.warnings:
            continue
        validate_content(candidate.content)
        activity = old.activity
        revision = Revision.objects.create(activity=activity,
            number=activity.revisions.order_by("-number").first().number+1,
            content=candidate.content, created_by=old.created_by,
            grading={**candidate.grading, "maximum_points": "0", "review_required": False})
        ImportRecord.objects.create(revision=revision, source_path=record.source_path,
            raw_xml=record.raw_xml, candidate=candidate.content, warnings=[], status="approved")
        activity.published_revision=revision
        activity.save(update_fields=["published_revision"])
        count += 1
    print(f"Upgraded {count} ungraded surveys.")
