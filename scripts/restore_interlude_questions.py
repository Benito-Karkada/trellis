#!/usr/bin/env python3
"""Restore three missing native interlude exercises through the staff API."""
import argparse
import ast
import itertools
import json
import os
from pathlib import Path
import sys
from clean_trailing_part_hyphens import pages
from upload_native_graders import API, private_json
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent
sys.path.insert(0,str(ROOT/'backend'))
from core.schema import validate_content
from core.assessment import assess

SPECS=[
 {'title':'Interlude 3.3.1 Exercise 1','after':798,'before':800,'points':'0.5','correct':['D'],
  'instruction':'Copy and paste the following three lines into IDLE or another Python editor, then answer the question below.',
  'prompt':'What is the output?',
  'choices':['The character is I','The character is n','The character is d','The character is i','The character is c','The character is e','The character is s']},
 {'title':'Interlude 3.3.2 Exercise 1','after':831,'before':833,'points':'0.5','correct':['A'],
  'instruction':'Copy and paste the following code segment into IDLE or another Python editor, then answer the question below.',
  'prompt':'What is the output of the code segment above?',
  'choices':['0: A totally wrong result.','1: A totally wrong result.','24: One iteration too few.','120: The right answer!','720: One iteration too many.']},
 {'title':'Interlude 3.5.1 Exercise 2','after':1102,'before':1104,'points':'1','correct':['A','F'],
  'instruction':'Copy and paste the following code into IDLE or another Python editor. Run it with some of the test cases from the previous exercise, or some you think of yourself. Then answer the question below.',
  'prompt':'Which of the following statements about the performance of the code appears to be true? Select all that apply.',
  'choices':['It only ever checks the first letter.','It only ever checks the last letter.','It misclassifies all vowels as consonants.','It misclassifies all consonants as vowels.','It never prints "Done".',None]},
]

def text(nodes):
 return ''.join('\n' if n.get('tag')=='br' or n['type']=='line_break' else n.get('text','')+text(n.get('children',[])) for n in nodes)

def code_from(content):
 found=[]
 def walk(nodes):
  for node in nodes:
   if node.get('tag')=='pre':found.append(text(node.get('children',[])))
   else:walk(node.get('children',[]))
 for block in content['blocks']:
  if block['type']=='code':found.append(block['text'])
  else:walk(block.get('content',block.get('prompt',[])))
 assert len(found)==1,'Expected exactly one referenced code snippet'
 source=found[0].replace('\u00a0',' ')
 ast.parse(source)
 return source

def payload(spec,after,before):
 assert after['assignment_id']==before['assignment_id']
 assert before['position']>after['position']+1,'No free insertion position; refusing to reorder unrelated content'
 qid='q1';multiple=len(spec['correct'])>1
 choices=[]
 for i,label in enumerate(spec['choices']):
  content=([{'type':'text','text':label}] if label is not None else [
   {'type':'text','text':'It only prints "Done" if '},{'type':'inline_code','text':'a_str'},{'type':'text','text':' is empty.'}])
  choices.append({'id':chr(65+i),'content':content})
 content={'version':1,'blocks':[
  {'id':'instructions','type':'paragraph','content':[{'type':'text','text':spec['instruction']}]},
  {'id':'example','type':'code','language':'python','text':code_from(after['content'])},
  {'id':qid,'type':'select_all' if multiple else 'multiple_choice','prompt':[{'type':'text','text':spec['prompt']}],'choices':choices}]}
 grading={'version':1,'questions':{qid:{'selection':'all' if multiple else 'one','correct_choice_ids':spec['correct']}},'maximum_points':spec['points'],'review_required':False}
 validate_content(content)
 # Check every possible selection against the native assessment engine.
 answers=([list(combo) for n in range(len(choices)+1) for combo in itertools.combinations([c['id'] for c in choices],n)] if multiple else [c['id'] for c in choices])
 for answer in answers:
  expected=set(answer)==set(spec['correct']) if multiple else answer==spec['correct'][0]
  assert assess(grading,{qid:answer})['passed']==expected
 assert 'vocareum' not in json.dumps(content).casefold()
 sources=list(SOURCE.glob('*/01*/*/*'+spec['title']+'.xml'))
 assert len(sources)==1,f'Expected one source XML for {spec["title"]}'
 return {'title':spec['title'],'kind':'question','category':after.get('category','content'),
  'position':after['position']+1,'metadata':{'group':after['metadata']['group'],'restoration_key':spec['title']},
  'content':content,'grading':grading,'files':[{'path':'source/original.xml','visibility':'staff','text':sources[0].read_text()}]}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
 api=API(os.environ['TRELLIS_URL'],os.environ['TRELLIS_API_TOKEN']);folder=ROOT/'var/interlude-questions-restored';folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
 try:
  plans=[];original={}
  for spec in SPECS:
   after=api.request('GET',f"/parts/{spec['after']}/");before=api.request('GET',f"/parts/{spec['before']}/")
   aid=after['assignment_id']
   if aid not in original:original[aid]=pages(api,f'/assignments/{aid}/parts/?limit=200')
   body=payload(spec,after,before)
   if any(p['position']==body['position'] and p['title']!=spec['title'] for p in original[aid]):raise ValueError('Insertion slot is already occupied.')
   plans.append({'assignment_id':aid,'after':after['id'],'before':before['id'],'body':body})
   print(f"Prepared {spec['title']}: {spec['points']} points, position {body['position']}, correct {','.join(spec['correct'])}.",flush=True)
  private_json(folder/'plan.json',plans);private_json(folder/'original-outline.json',original)
  if not args.apply:return
  restored=[]
  for plan in plans:
   body=plan['body'];aid=plan['assignment_id']
   existing=[p for p in pages(api,f'/assignments/{aid}/parts/?limit=200') if p['title']==body['title']]
   assert len(existing)<=1,'Duplicate titles already exist'
   if existing:
    part=api.request('GET',f"/parts/{existing[0]['id']}/")
    assert part['metadata'].get('restoration_key')==body['title'] and part['content']==body['content'] and part['grading']==body['grading'],'Existing exercise differs; refusing to overwrite it'
   else:part=api.request('POST',f'/assignments/{aid}/parts/',body,key='restore-'+body['title'].replace(' ','-'))
   if part['published_revision_id']!=part['revision_id']:api.request('POST',f"/parts/{part['id']}/publish/",{},part['revision_id'])
   current=api.request('GET',f"/parts/{part['id']}/")
   assert current['published_revision_id']==current['revision_id']
   assert current['content']==body['content'] and current['grading']==body['grading']
   rows=pages(api,f'/assignments/{aid}/parts/?limit=200');ids=[p['id'] for p in rows];index=ids.index(current['id'])
   assert ids[index-1]==plan['after'] and ids[index+1]==plan['before'],'Unexpected exercise order'
   restored.append({'id':current['id'],'title':current['title'],'points':current['grading']['maximum_points'],'assignment_id':aid,'position':current['position']})
   private_json(folder/'applied.json',restored)
   print('Published and verified:',current['title'],flush=True)
  new_ids={r['id'] for r in restored}
  for aid,old in original.items():
   now=pages(api,f'/assignments/{aid}/parts/?limit=200')
   signature=lambda rows:[(p['id'],p['title'],p['position']) for p in rows if p['id'] not in new_ids]
   assert signature(now)==signature(old),'Unrelated outline content changed during restoration'
  private_json(folder/'result.json',{'status':'published-and-verified','exercises':restored})
  print('All three restored with correct ordering, scoring, and answer selection.',flush=True)
 finally:api.session.close()
if __name__=='__main__':main()
