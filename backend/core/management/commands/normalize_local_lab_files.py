"""Replace the local lab's copied Vocareum hooks with platform-native configuration."""
import hashlib
import json
from pathlib import PurePosixPath
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import ActivityFile, Lesson, Revision

LEGACY={"Ferb.py","Utility.py","Program.py","AutoGrade.py","RequiredCode.py","BadLines.txt","correct.out","publicdata","voc_file"}


class Command(BaseCommand):
    help=__doc__
    @transaction.atomic
    def handle(self,*args,**options):
        lesson=Lesson.objects.filter(title="Local coding lab",deleted_at=None).first()
        if lesson is None:
            self.stdout.write("Local coding lab not found.");return
        changed=0
        for activity in lesson.activity_set.filter(deleted_at=None):
            previous=activity.revisions.order_by("-number").first()
            if previous is None: continue
            kept={}
            for file in previous.files.all():
                name=PurePosixPath(file.path).name
                if file.path.startswith("scripts/") or name in LEGACY: continue
                with file.blob.open("rb") as stream: raw=stream.read()
                path=file.path;visibility=file.visibility
                if name.startswith("sample_answer"):
                    path="solutions/"+name;visibility="staff"
                kept[path]=(visibility,raw)
            if (len(kept)==previous.files.count() and "grader/tests.json" in kept
                and all(not p.startswith("private/") for p in kept)): continue
            revision=Revision.objects.create(activity=activity,number=previous.number+1,content=previous.content,
                grading={**previous.grading,"source":"coursespace"},created_by=previous.created_by)
            definition=revision.grading.get("definition")
            if definition:
                kept["grader/tests.json"]=("grader",(json.dumps(definition,indent=2)+"\n").encode())
            for path,(visibility,raw) in kept.items():
                ActivityFile.objects.create(revision=revision,path=path,visibility=visibility,
                    blob=ContentFile(raw,name=PurePosixPath(path).name),sha256=hashlib.sha256(raw).hexdigest())
            activity.published_revision=revision;activity.save(update_fields=["published_revision"]);changed+=1
        self.stdout.write(self.style.SUCCESS(f"Normalized {changed} local coding activities."))
