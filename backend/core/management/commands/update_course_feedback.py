"""Restore choice hint rules, remove retired platform instructions, configure sandboxes."""
import copy
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from core.models import Activity, Revision, ActivityFile, ImportRecord
from core.importers.edx import parse_problem_xml


def mentions_old_platform(node):
    if isinstance(node, list): return any(mentions_old_platform(x) for x in node)
    if isinstance(node, dict):
        return any("vocareum" in str(node.get(k, "")).casefold() for k in ("text", "href", "alt")) or any(
            mentions_old_platform(node.get(k, [])) for k in ("content", "prompt", "children"))
    return False


class Command(BaseCommand):
    @transaction.atomic
    def handle(self,*args,**options):
        counts={"hints":0,"sandboxes":0,"removed_blocks":0,"removed_pages":0}
        retired_prefixes = tuple(f"part_{pk}_" for pk in Activity.objects.filter(title__icontains="vocareum").values_list("pk",flat=True))
        for activity in Activity.objects.filter(deleted_at=None).select_related("published_revision"):
            old=activity.published_revision
            if old is None or activity.metadata.get("feedback_update") == 2: continue
            content=copy.deepcopy(old.content); grading=copy.deepcopy(old.grading); changed=False
            records=list(ImportRecord.objects.filter(revision=old))
            if activity.metadata.get("kind")=="question" and len(records)==1:
                parsed=parse_problem_xml(records[0].raw_xml)
                existing=list(grading.get("questions",{}).values())
                incoming=list(parsed.grading.get("questions",{}).values())
                if len(existing)==len(incoming):
                    for rule, fresh in zip(existing,incoming):
                        # Keep published block/choice IDs and existing answers stable.
                        old_ids=list(rule.get("choice_feedback",{}))
                        new_ids=list(fresh.get("choice_feedback",{}))
                        if len(old_ids)==len(new_ids) and "choice_feedback_rules" in fresh:
                            rule["choice_feedback_rules"]={oid:fresh["choice_feedback_rules"].get(nid,[]) for oid,nid in zip(old_ids,new_ids)}
                    changed=True; counts["hints"]+=1
            if "sandbox" in activity.title.casefold():
                activity.metadata.update(sandbox=True,placeholder=False)
                grading={"maximum_points":"0","placeholder":False,"entrypoint":"main.py"}
                content={"version":1,"blocks":[{"id":"sandbox","type":"coding","prompt":[{"type":"text","text":"Use this workspace to try Python code. This sandbox is not graded."}]}]}
                changed=True; counts["sandboxes"]+=1
            elif "vocareum" in (activity.title+" "+activity.metadata.get("group","")).casefold():
                activity.deleted_at=timezone.now(); activity.save(update_fields=["deleted_at"])
                counts["removed_pages"]+=1; continue
            else:
                before=len(content["blocks"])
                content["blocks"]=[b for b in content["blocks"] if not mentions_old_platform(b) and not b["id"].startswith(retired_prefixes)]
                removed=before-len(content["blocks"])
                if removed: counts["removed_blocks"]+=removed; changed=True
                if not content["blocks"]:
                    activity.deleted_at=timezone.now(); activity.save(update_fields=["deleted_at"])
                    counts["removed_pages"]+=1; continue
            if changed:
                revision=Revision.objects.create(activity=activity,number=activity.revisions.order_by("-number").first().number+1,
                    content=content,grading=grading,created_by=old.created_by)
                for file in old.files.all():
                    ActivityFile.objects.create(revision=revision,path=file.path,visibility=file.visibility,blob=file.blob.name,sha256=file.sha256)
                if activity.metadata.get("sandbox") and not revision.files.filter(visibility="student").exists():
                    ActivityFile.objects.create(revision=revision,path="main.py",visibility="student",blob=ContentFile(b"",name="main.py"))
                for record in records:
                    ImportRecord.objects.create(revision=revision,source_path=record.source_path,raw_xml=record.raw_xml,
                        candidate=record.candidate,warnings=record.warnings,status=record.status)
                activity.published_revision=revision
            activity.metadata["feedback_update"]=2
            activity.save()
        self.stdout.write(str(counts))
