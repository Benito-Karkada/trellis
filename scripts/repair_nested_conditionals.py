#!/usr/bin/env python3
"""Repair 3.2.6 Coding Exercise 1, verify in isolation, then publish. Dry run by default."""
import argparse
import copy
import os
import re
from pathlib import Path
import sys
import uuid
from clean_trailing_part_hyphens import pages
from upload_native_graders import API, private_json, public_workspace, test_job, poll_job
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runner'))
from grading.manifest import load_definition

RULES=[
 {'id':'no-and-operator','kind':'forbid_node','target':'And',
  'message':"Use nested conditionals instead of the 'and' operator. Remove every use of the 'and' operator from your code."},
 {'id':'nested-conditionals','kind':'require_nested_if','target':'If',
  'message':'Use a nested conditional: place an if statement inside another conditional. Keep the original behavior.'}
]

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
 api=API(os.environ['TRELLIS_URL'],os.environ['TRELLIS_API_TOKEN'])
 root=ROOT/'var/nested-conditionals-repair';root.mkdir(parents=True,exist_ok=True);root.chmod(0o700)
 try:
  candidates=[]
  for lesson in pages(api,'/courses/1/assignments/?limit=200'):
   candidates.extend(p for p in pages(api,f"/assignments/{lesson['id']}/parts/?limit=200")
    if re.search(r'3\.2\.6.*coding.*exercise\s*1(?:\D|$)', p['title'], re.I))
  assert len(candidates)==1,f'Expected one exercise, found {len(candidates)}'
  part=api.request('GET',f"/parts/{candidates[0]['id']}/")
  assert part['grading']['entrypoint']=='Outfit.py'
  assert part['revision_id']==part['published_revision_id'],'A newer staff draft exists; do not publish unrelated edits.'
  definition=copy.deepcopy(part['grading']['definition'])
  old_cases=copy.deepcopy(definition['cases'])
  definition['requirements']=[r for r in definition.get('requirements',[]) if r['id'] not in {x['id'] for x in RULES}]+RULES
  load_definition(definition)
  private_json(root/'before.json',part);private_json(root/'definition.json',definition)
  print(f"Prepared {part['title']} (part {part['id']}); preserves {len(old_cases)} output cases and {part['grading']['maximum_points']} points.",flush=True)
  if not args.apply:return
  pid=part['id'];run=str(uuid.uuid4())
  updated=api.request('PUT',f'/parts/{pid}/grader/',{'definition':definition,'mark_reviewed':True},part['revision_id'])
  revision=updated['revision_id'];files=public_workspace(api,updated)
  original=files['Outfit.py']
  assert 'and' in original,'Original starter code differs from the reviewed exercise.'
  results={}
  cases=[('starter',original,'0'),('nested',"sunny = True\nwindy = False\n\nif sunny:\n    if windy:\n        print(\"Enjoy the breeze!\")\n    else:\n        print(\"Wear a hat!\")\n",'1')]
  for name,source,expected in cases:
   job=test_job(api,pid,revision,{**files,'Outfit.py':source},run+'-'+name)
   result=poll_job(api,job,180)
   private_json(root/(name+'-result.json'),result)
   assert result['score_fraction']==expected,(name,result)
   results[name]={'job_id':job,'score_fraction':result['score_fraction'],'passed':result['passed']}
   print(f"Verified {name}: score fraction {result['score_fraction']}, passed {result['passed']}.",flush=True)
  assert all(c['passed'] for c in result['checks'])
  published=api.request('POST',f'/parts/{pid}/publish/',{},revision)
  current=api.request('GET',f'/parts/{pid}/')
  assert current['published_revision_id']==revision
  assert current['grading']['definition']['cases']==old_cases
  assert current['grading']['maximum_points']==part['grading']['maximum_points']
  assert current['grading']['definition']['requirements']==definition['requirements']
  private_json(root/'result.json',{'status':'published-and-verified','part_id':pid,'revision_id':revision,'tests':results})
  print('Published and verified repaired grader. Student scores were not modified by preview tests.',flush=True)
 finally:api.session.close()
if __name__=='__main__':main()
