"""Backfill static observations only; never executes code or changes scores."""
from collections import OrderedDict
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import ExecutionJob
from core.code_review import analyze,policy,provided_python

class Command(BaseCommand):
 help=__doc__
 def add_arguments(self,parser):
  parser.add_argument('--course',type=int,required=True);parser.add_argument('--limit',type=int,default=5000)
 def handle(self,*args,**options):
  if not 1<=options['limit']<=100000:raise ValueError('Limit must be 1–100000.')
  query=ExecutionJob.objects.filter(preview=False,review_signals={},revision__activity__lesson__course_id=options['course']).select_related('revision__activity__lesson__course').order_by('pk')[:options['limit']]
  cache=OrderedDict();count=0
  for job in query.iterator(chunk_size=100):
   if job.revision_id not in cache:
    cache[job.revision_id]=provided_python(job.revision)
    if len(cache)>128:cache.popitem(last=False)
   data=analyze(job.snapshot,cache[job.revision_id],policy(job.revision.activity.lesson.course))
   data.update(historical=True,analyzed_at=timezone.now().isoformat())
   ExecutionJob.objects.filter(pk=job.pk,review_signals={}).update(review_signals=data);count+=1
  self.stdout.write(f'Analyzed {count} historical attempts; no workspaces or grades changed.')
