"""Repair imported presentation from preserved sources without deleting history."""
import re
from pathlib import Path
from urllib.parse import unquote
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from core.models import Activity, Revision, ImportRecord, CourseAsset
from core.importers.edx import parse_problem_xml
from core.importers.kaltura import load_kaltura_catalog
from core.importers.rich_html import parse_html
from core.importers.scope import include_component
from core.schema import validate_content


def text_of(nodes):
    return " ".join(n.get("text", "") + " " + text_of(n.get("children", [])) for n in nodes)


def reading_title(raw, group, ordinal):
    nodes, _ = parse_html(raw)
    def headings(items):
        for node in items:
            if node.get("tag") in {"h1", "h2", "h3"}:
                value = " ".join(text_of(node.get("children", [])).split())
                if value and len(value) <= 100: return value
            nested = headings(node.get("children", []))
            if nested: return nested
    heading = headings(nodes)
    if heading: return heading
    text = " ".join(text_of(nodes).split())
    if text.startswith("Welcome to CS1301"): return "Welcome to CS 1301"
    sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    if 5 < len(sentence) <= 100: return sentence
    return f"{group} — Reading {ordinal}"


class Command(BaseCommand):
    @transaction.atomic
    def handle(self, *args, **kwargs):
        catalog, _ = load_kaltura_catalog(Path('/app/private-media/import-source/kaltura_videos.csv').read_text())
        normalize = lambda s: re.sub(r"[^a-z0-9.]", "", s.casefold())
        assets = {normalize(Path(a.source_path).name): f"/api/assets/{a.pk}/" for a in CourseAsset.objects.all()}
        def resolve(node):
            if isinstance(node, list):
                for child in node: resolve(child)
            elif isinstance(node, dict):
                for key, value in node.items():
                    if key in {"src", "href"} and isinstance(value, str) and value.startswith(("/static/", "static/", "/asset-v1:")):
                        name = unquote(value.split("block@")[-1]).split("/")[-1]
                        node[key] = assets.get(normalize(name), value)
                    else: resolve(value)
        counts = {"excluded":0, "questions":0, "titles":0, "videos":0}
        ordinals = {}
        for activity in Activity.objects.filter(deleted_at=None).select_related("published_revision"):
            path = activity.metadata.get("source_path")
            if not path: continue
            if not include_component(path):
                activity.deleted_at=timezone.now(); activity.save(update_fields=["deleted_at"])
                counts["excluded"]+=1; continue
            if activity.metadata.get("rendering_version") == 2: continue
            old = activity.published_revision
            if old is None: continue
            record = ImportRecord.objects.filter(revision=old).first()
            if not record: continue  # Preserve web-authored content.
            content, grading, warnings = old.content, old.grading, record.warnings
            changed=False
            if activity.metadata.get("kind") == "question":
                candidate=parse_problem_xml(record.raw_xml)
                content=candidate.content; resolve(content)
                grading={**old.grading, **candidate.grading}
                warnings=candidate.warnings; changed=True; counts["questions"]+=1
            elif activity.metadata.get("kind") == "reading" and path.endswith(".html"):
                group=activity.metadata.get("group", "Lesson")
                key=(activity.lesson_id, group); ordinals[key]=ordinals.get(key,0)+1
                activity.title=reading_title(record.raw_xml, group, ordinals[key])[:200]
                activity.save(update_fields=["title"]); counts["titles"]+=1
            elif activity.title in {"Unit 4: Data Structures", "Unit 5: Objects & Algorithms"}:
                key="1.1.6.4" if activity.title.startswith("Unit 4") else "1.1.6.5"
                video=catalog[key]
                content={"version":1,"blocks":[{"id":"video","type":"kaltura","entry_id":video.entry_id,
                    "partner_id":video.partner_id,"uiconf_id":video.uiconf_id,"widget_id":video.widget_id}]}
                warnings=[]; changed=True; counts["videos"]+=1
            if changed:
                validate_content(content)
                revision=Revision.objects.create(activity=activity, number=activity.revisions.order_by("-number").first().number+1,
                    content=content, grading=grading, created_by=old.created_by)
                ImportRecord.objects.create(revision=revision,source_path=path,raw_xml=record.raw_xml,candidate=content,
                    warnings=warnings,status="needs_review" if warnings else "approved")
                activity.published_revision=revision; activity.save(update_fields=["published_revision"])
            activity.metadata["rendering_version"]=2
            activity.save(update_fields=["metadata"])
        self.stdout.write(str(counts))
