"""Combine a native assessment with its instructions and ungraded coding workspace."""
from copy import deepcopy
import hashlib
from pathlib import Path
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from .models import Activity,ActivityFile,Revision,Workspace
from .schema import validate_content


@transaction.atomic
def combine_group(lesson, group, dataset_name, dataset_bytes, user):
    if not dataset_name or '/' in dataset_name or '\\' in dataset_name:raise ValueError('Use a dataset filename.')
    parts=list(Activity.objects.select_for_update(of=('self',)).filter(lesson=lesson,deleted_at=None,metadata__group=group).select_related('published_revision').order_by('position','pk'))
    assessments=[a for a in parts if a.published_revision and a.published_revision.grading.get('questions')]
    if len(assessments)!=1:raise ValueError('Expected exactly one existing native assessment in this group.')
    primary=assessments[0]
    if primary.metadata.get('combined_analysis'):return primary,False
    for part in parts:
        if part.published_revision_id and part.revisions.order_by('-number').first().pk!=part.published_revision_id:raise ValueError('Publish or discard the existing draft before combining this group.')
    sources=[a for a in parts if a!=primary]
    if not any(a.metadata.get('kind')=='coding' for a in sources):raise ValueError('Expected a coding workspace in this group.')
    old=primary.published_revision
    # Question IDs stay unchanged, retaining saved responses and per-question review state.
    blocks=[]
    for part in parts:
        if part==primary or part.metadata.get('kind')=='coding':continue
        if not part.published_revision:continue
        for block in deepcopy(part.published_revision.content['blocks']):
            block['id']=f'context_{part.pk}_{block["id"]}';blocks.append(block)
    if dataset_name=='babynames.csv':
        blocks.append({'id':'dataset_columns','type':'document','content':[{'type':'text','text':'babynames.csv has no header row. Each row contains a name, its frequency, and gender (Girl or Boy), in that order.'}]})
    elif dataset_name=='georgia_tech_football.csv':
        blocks.append({'id':'dataset_columns','type':'document','content':[{'type':'text','text':'georgia_tech_football.csv begins with a header row: Date, Opponent, Location, Points For, Points Against. Dates use YYYY-MM-DD; compare Points For and Points Against to determine wins, losses and ties.'}]})
    blocks.append({'id':'analysis_workspace','type':'coding','prompt':[{'type':'text','text':f'Use the sandbox to explore {dataset_name}, then submit your answers below. Only your answers are graded.'}]})
    blocks.extend(deepcopy(old.content['blocks']))
    content={'version':1,'blocks':blocks};validate_content(content)
    revision=Revision.objects.create(activity=primary,number=primary.revisions.order_by('-number').first().number+1,created_by=user,content=content,grading=deepcopy(old.grading))
    files={}
    for part in [primary,*sources]:
        if part.published_revision:
            for file in part.published_revision.files.all():
                if file.path not in files:files[file.path]=file
    for file in files.values():
        ActivityFile.objects.create(revision=revision,path=file.path,visibility=file.visibility,blob=file.blob.name,sha256=file.sha256)
    if 'main.py' not in files:
        raw=(f'import csv\n\nwith open({dataset_name!r}, newline="") as dataset:\n    rows = list(csv.reader(dataset))\n\nprint(rows[0])\n# Explore the dataset here.\n').encode()
        ActivityFile.objects.create(revision=revision,path='main.py',visibility='student',blob=ContentFile(raw,name='main.py'),sha256=hashlib.sha256(raw).hexdigest())
    ActivityFile.objects.filter(revision=revision,path=dataset_name).delete()
    ActivityFile.objects.create(revision=revision,path=dataset_name,visibility='student',blob=ContentFile(dataset_bytes,name=dataset_name),sha256=hashlib.sha256(dataset_bytes).hexdigest())
    baseline={}
    for file in revision.files.filter(visibility='student'):
        with file.blob.open('rb') as stream:baseline[file.path]=stream.read().decode()
    # Preserve the latest saved sandbox code; original workspace records remain intact.
    prior=Workspace.objects.filter(revision__activity__in=sources).select_related('revision').order_by('user_id','-updated_at')
    carried=set()
    for saved in prior:
        if saved.user_id in carried:continue
        carried.add(saved.user_id)
        public=set(saved.revision.files.filter(visibility='student').values_list('path',flat=True))
        carried_files={**baseline,**{p:t for p,t in saved.files.items() if p in public and p in baseline}}
        Workspace.objects.get_or_create(user_id=saved.user_id,revision=revision,defaults={'files':carried_files})
    primary.title=group;primary.position=min(a.position for a in parts)
    primary.metadata={**primary.metadata,'kind':'question','workspace_mode':'sandbox','placeholder':False,'combined_analysis':True,'combined_sources':[a.pk for a in parts],'dataset':dataset_name}
    primary.metadata.pop('sandbox',None);primary.published_revision=revision;primary.save()
    for part in sources:
        part.deleted_at=timezone.now();part.metadata={**part.metadata,'combined_into':primary.pk};part.save(update_fields=['deleted_at','metadata'])
    return primary,True
