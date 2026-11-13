"""Idempotent digest import: native content, private answers, coding placeholders."""
import base64
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from decimal import Decimal
from defusedxml import ElementTree as ET
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Course, Lesson, Activity, Revision, ImportRecord, CourseAsset
from core.importers.scope import include_section, include_component
from core.importers.edx import parse_problem_xml
from core.importers.rich_html import parse_html
from core.importers.kaltura import load_kaltura_catalog
from core.schema import validate_content


def title(name):
    return re.sub(r"^\d+ - ", "", name)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("source", type=Path)
        parser.add_argument("--report", type=Path)
        parser.add_argument("--refresh",action="store_true",help="Refresh untouched initial imports from their original sources")

    @transaction.atomic
    def handle(self, *args, **options):
        source = options["source"]
        user = get_user_model().objects.get(username="studio-instructor")
        course = Course.objects.get(membership__user=user, membership__role="instructor")
        catalog, _ = load_kaltura_catalog((source/"kaltura_videos.csv").read_text(encoding="utf-8-sig"))
        report = {"imported":0,"existing":0,"coding_placeholders":0,"videos":0,"kaltura":0,"warnings":[]}
        assets = {}
        normalize=lambda name:re.sub(r"[^a-z0-9.]","",name.casefold())
        asset_names={}
        for path in (source/"static").rglob("*"):
            if path.is_file():asset_names.setdefault(normalize(path.name),[]).append(path)

        def asset_url(value, warnings):
            if re.match(r"^data:image/(png|jpeg|gif|webp);base64,",value):
                try: base64.b64decode(value.split(",",1)[1],validate=True); return value
                except ValueError: pass
            if not (value.startswith(("/static/", "/asset-v1:", "static/"))): return value
            name = unquote(urlparse(value).path.split("block@")[-1].removeprefix("/static/").removeprefix("static/"))
            path = (source/"static"/name).resolve()
            if not path.is_file():
                matches=asset_names.get(normalize(Path(name).name),[])
                if len(matches)==1:path=matches[0].resolve();name=str(path.relative_to((source/"static").resolve()))
            if not path.is_relative_to((source/"static").resolve()) or not path.is_file():
                warnings.append({"code":"missing_asset","path":value})
                return ""
            if name not in assets:
                asset, created = CourseAsset.objects.get_or_create(course=course,source_path=name,
                    defaults={"content_type":mimetypes.guess_type(name)[0] or "application/octet-stream"})
                if created:
                    asset.blob.save(path.name,ContentFile(path.read_bytes()))
                assets[name] = f"/api/assets/{asset.pk}/"
            return assets[name]

        def resolve(node,warnings):
            if isinstance(node,dict):
                for key,value in node.items():
                    if key in {"src","href"} and isinstance(value,str): node[key]=asset_url(value,warnings)
                    else: resolve(value,warnings)
            elif isinstance(node,list):
                for item in node: resolve(item,warnings)

        for section in sorted(source.iterdir()):
            if not section.is_dir() or not include_section(section.name): continue
            lesson, _ = Lesson.objects.get_or_create(course=course,source_path=section.name,
                defaults={"title":title(section.name),"position":int(section.name.split(" ")[0])})
            units = []
            for folder in sorted(section.iterdir()):
                if not folder.is_dir(): continue
                if not include_component(folder.relative_to(source)): continue
                category = "problem_set" if "Knowledge Checks" in folder.name else "supplemental" if "Supplemental" in folder.name else "content"
                for unit in sorted(folder.iterdir()):
                    if not unit.is_dir(): continue
                    if not include_component(unit.relative_to(source)): continue
                    advanced = "advanced" in unit.name.lower()
                    coding = any(" - LTI - " in p.name for p in unit.iterdir())
                    rank = (2 if advanced else 1 if coding else 0) if category=="problem_set" else 0
                    units.append((folder.name,rank,unit.name,category,unit))
            position = 0
            for _,rank,_,category,unit in sorted(units):
                for path in sorted(unit.iterdir()):
                    if path.suffix.lower() not in {".xml",".html"}:continue
                    relative = str(path.relative_to(source))
                    if not include_component(relative): continue
                    existing=Activity.objects.filter(lesson=lesson,metadata__source_path=relative).first()
                    if existing and (not options["refresh"] or existing.revisions.count()>1):
                        report["existing"]+=1;position+=1;continue
                    raw = path.read_text(encoding="utf-8-sig")
                    warnings=[]; grading={}; blocks=[]; maximum="0"; kind="reading"
                    activity_title = path.stem.split(" - ",2)[-1]
                    try:
                        if path.suffix==".html":
                            from .repair_course_rendering import reading_title
                            nodes,warnings=parse_html(raw)
                            blocks=[{"id":"document","type":"document","content":nodes}]
                            activity_title = reading_title(raw, title(unit.name), int(path.name.split(" ")[0]))
                        else:
                            root=ET.fromstring(raw)
                            activity_title=root.get("display_name",activity_title)
                            if root.tag in {"lti_consumer","lti"}:
                                kind="coding";maximum=root.get("weight","1")
                                blocks=[{"id":"coding","type":"coding","prompt":[{"type":"text","text":"Coding exercise files have not been imported yet."}]}]
                                grading={"placeholder":True,"source_launch_url":root.get("launch_url","")}
                                report["coding_placeholders"]+=1
                                if urlparse(root.get("launch_url","")).hostname != "labs.vocareum.com":
                                    kind="external";maximum="0"
                                    blocks=[{"id":"external","type":"placeholder","message":"This external activity needs integration review."}]
                                    grading["placeholder"]=False
                                    warnings.append({"code":"external_integration_required"})
                                    report["coding_placeholders"]-=1
                            elif root.tag=="video":
                                kind="video";report["videos"]+=1
                                match=re.search(r"(\d+\.\d+\.\d+\.\d+\s*[A-Za-z]?)",activity_title)
                                key=re.sub(r"\s","",match.group(1)) if match else None
                                key = key or {"Unit 4: Data Structures":"1.1.6.4", "Unit 5: Objects & Algorithms":"1.1.6.5"}.get(activity_title)
                                video=catalog.get(key)
                                if video:
                                    blocks=[{"id":"video","type":"kaltura","entry_id":video.entry_id,"partner_id":video.partner_id,"uiconf_id":video.uiconf_id,"widget_id":video.widget_id or ""}]
                                    report["kaltura"]+=1
                                else:
                                    encoded=root.find(".//encoded_video[@profile='desktop_mp4']")
                                    url=encoded.get("url","") if encoded is not None else ""
                                    blocks=[{"id":"video","type":"video","url":url}] if url.startswith("https://") else [{"id":"video","type":"placeholder","message":"Video mapping needs review."}]
                                    warnings.append({"code":"unmatched_kaltura","key":key})
                            else:
                                candidate=parse_problem_xml(raw)
                                blocks=candidate.content["blocks"];grading=candidate.grading;warnings=candidate.warnings
                                kind="question";maximum=root.get("weight","1")
                        if not Decimal(maximum).is_finite() or Decimal(maximum)<0:raise ValueError("Invalid points")
                        content={"version":1,"blocks":blocks}
                        resolve(content,warnings)
                        validate_content(content)
                    except Exception as error:
                        warnings.append({"code":"import_error","type":type(error).__name__})
                        content={"version":1,"blocks":[{"id":"review","type":"placeholder","message":"This component needs import review."}]}
                        maximum="0"
                    grading["maximum_points"]=maximum
                    blocked = any(w["code"] in {"import_error","invalid_xml","invalid_correct_answer_count","requires_dynamic_problem_review","missing_choice_group"} for w in warnings)
                    grading["review_required"]=blocked
                    activity=existing or Activity.objects.create(lesson=lesson,title=activity_title[:200],position=position,
                        metadata={"source_path":relative,"group":title(unit.name),"category":category,
                                  "kind":kind,"advanced":rank==2,"placeholder":grading.get("placeholder",False)})
                    revision=Revision.objects.create(activity=activity,number=2 if existing else 1,content=content,grading=grading,created_by=user)
                    ImportRecord.objects.create(source_path=relative,raw_xml=raw,revision=revision,
                        candidate=content,warnings=warnings,status="needs_review" if warnings else "approved")
                    activity.published_revision=revision;activity.save(update_fields=["published_revision"])
                    position+=1;report["imported"]+=1
                    if warnings:report["warnings"].append({"source":relative,"warnings":warnings})
        report["assets"]=CourseAsset.objects.filter(course=course).count()
        from django.core.management import call_command
        call_command("group_lesson_media", stdout=self.stdout)
        call_command("update_course_feedback", stdout=self.stdout)
        if options["report"]:options["report"].write_text(json.dumps(report,indent=2))
        self.stdout.write(json.dumps({k:len(v) if k=="warnings" else v for k,v in report.items()}))
