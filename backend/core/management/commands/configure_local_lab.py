"""Configure the already-downloaded demonstration without fetching coding archives."""
import random
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from core.models import Activity, Revision, ActivityFile

class Command(BaseCommand):
    @transaction.atomic
    def handle(self,*args,**options):
        activity=Activity.objects.filter(title="Days between dates",metadata={}).first()
        if activity is None:
            self.stdout.write("Local coding lab is already configured; existing edits retained.")
            return
        lesson=activity.lesson
        lesson.title="Local coding lab";lesson.position=9999;lesson.save()
        activity.metadata={"kind":"coding","group":"Dates","category":"content","placeholder":False};activity.save()
        previous=activity.published_revision
        revision=Revision.objects.create(activity=activity,number=activity.revisions.order_by("-number").first().number+1,
            grading=previous.grading,content=previous.content,created_by=previous.created_by)
        ActivityFile.objects.bulk_create([ActivityFile(revision=revision,path=f.path,visibility=f.visibility,
            blob=f.blob.name,sha256=f.sha256) for f in previous.files.all()])
        cases=[]
        for seed in [0,17,31]:
            generator=random.Random(seed);earlier=generator.randint(1,25);later=generator.randint(earlier+1,28)
            cases.append({"id":f"dates-{seed}","label":"Dates","action":"variable","target":"days_between","seed":seed,"expected":later-earlier})
        revision.grading.update({"maximum_points":"5","entrypoint":"DaysBetweenDates.py",
                                "definition":{"version":1,"scoring":"all_or_nothing","cases":cases}})
        for block in revision.content["blocks"]:
            for field in ("content","prompt"):
                for node in block.get(field,[]):
                    if "text" in node:node["text"]=node["text"].replace("starter file","provided code").replace("starter comments","comments")
        revision.save()
        activity.published_revision=revision;activity.save(update_fields=["published_revision"])
        lesson.activity_set.filter(title="A name for a value").update(deleted_at=timezone.now())
        self.stdout.write("Local coding lab configured with first-party test data.")
