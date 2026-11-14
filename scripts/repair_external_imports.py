"""Correct imported non-Vocareum LTI labels while preserving revision history."""
from urllib.parse import urlparse
from django.db import transaction
from core.models import Activity, Revision, ImportRecord

with transaction.atomic():
    count = 0
    for activity in Activity.objects.filter(metadata__placeholder=True).select_related("published_revision"):
        old = activity.published_revision
        host = urlparse(old.grading.get("source_launch_url", "")).hostname
        if host != "aairs.tegrity.com" or old.files.exists():
            continue
        content = {"version": 1, "blocks": [{"id": "external", "type": "placeholder",
                   "message": "This external activity needs integration review."}]}
        revision = Revision.objects.create(activity=activity,
            number=activity.revisions.order_by("-number").first().number + 1,
            content=content, grading={**old.grading, "placeholder": False, "maximum_points": "0"},
            created_by=old.created_by)
        for record in ImportRecord.objects.filter(revision=old):
            ImportRecord.objects.create(revision=revision, source_path=record.source_path,
                raw_xml=record.raw_xml, candidate=content, status="needs_review",
                warnings=[*record.warnings, {"code": "external_integration_required"}])
        activity.metadata.update(kind="external", placeholder=False)
        activity.published_revision=revision
        activity.save()
        count += 1
    print(f"Corrected {count} external activity labels.")
