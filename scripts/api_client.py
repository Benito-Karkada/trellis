#!/usr/bin/env python3
"""Trellis REST client. Set TRELLIS_URL and TRELLIS_API_TOKEN in the environment."""
import argparse
import csv
import json
import os
from pathlib import Path
import sys
import uuid
from urllib.parse import urlsplit, quote
import requests

class Trellis:
 def __init__(self,url,token):
  self.url=url.rstrip('/');self.session=requests.Session();self.session.trust_env=False
  parsed=urlsplit(self.url)
  if parsed.scheme!='https' and not(parsed.scheme=='http' and parsed.hostname in {'localhost','127.0.0.1'}):raise ValueError('Use HTTPS, except for local development.')
  if not token:raise ValueError('Set TRELLIS_API_TOKEN.')
  self.session.headers['Authorization']='Bearer '+token
 def request(self,method,path,body=None,revision=None):
  if not path.startswith('/api/v1/'):raise ValueError('Pagination links must stay within the Trellis API.')
  headers={}
  if method!='GET':headers['Idempotency-Key']=str(uuid.uuid4())
  if revision is not None:headers['If-Match']=f'"{revision}"'
  response=self.session.request(method,self.url+path,json=body,headers=headers,timeout=60,allow_redirects=False)
  data=response.json()
  if not response.ok:raise RuntimeError(f"HTTP {response.status_code}: {data.get('error',{}).get('message','Request failed')}")
  return data
 def rows(self,path):
  while path:
   data=self.request('GET',path)
   yield from data['results'];path=data['next']


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default=os.environ.get('TRELLIS_URL',''))
 sub=p.add_subparsers(dest='command',required=True)
 for command in ('missing-graders','grades','submissions','events','enrollments'):
  s=sub.add_parser(command);s.add_argument('--course',type=int,required=True);s.add_argument('--output',type=Path);s.add_argument('--assignment-ids');s.add_argument('--enrollment-ids')
 s=sub.add_parser('get-part');s.add_argument('part',type=int)
 s=sub.add_parser('put-file');s.add_argument('part',type=int);s.add_argument('remote_path');s.add_argument('file',type=Path);s.add_argument('--visibility',choices=['student','staff','grader'],required=True)
 s=sub.add_parser('put-grader');s.add_argument('part',type=int);s.add_argument('file',type=Path);s.add_argument('--entrypoint');s.add_argument('--mark-reviewed',action='store_true');s.add_argument('--reference',type=Path)
 s=sub.add_parser('publish');s.add_argument('part',type=int)
 s=sub.add_parser('enroll');s.add_argument('--course',type=int,required=True);s.add_argument('--email',required=True);s.add_argument('--name',default='');s.add_argument('--role',default='student',choices=['student','ta','instructor'])
 s=sub.add_parser('drop');s.add_argument('enrollment',type=int)
 args=p.parse_args();client=Trellis(args.url,os.environ.get('TRELLIS_API_TOKEN',''))
 if args.command in {'get-part','put-file','put-grader','publish'}:
  part=client.request('GET',f'/api/v1/parts/{args.part}/');revision=part['revision_id']
  if args.command=='get-part':data=part
  elif args.command=='put-file':
   import base64
   raw=args.file.read_bytes()
   try:payload={'text':raw.decode('utf-8')}
   except UnicodeDecodeError:payload={'content_base64':base64.b64encode(raw).decode()}
   payload['visibility']=args.visibility
   data=client.request('PUT',f'/api/v1/parts/{args.part}/files/{quote(args.remote_path, safe='/')}' ,payload,revision)
  elif args.command=='put-grader':
   payload={'definition':json.loads(args.file.read_text()),'mark_reviewed':args.mark_reviewed}
   if args.entrypoint:payload['entrypoint']=args.entrypoint
   if args.reference:payload['reference_source']=args.reference.read_text()
   data=client.request('PUT',f'/api/v1/parts/{args.part}/grader/',payload,revision)
  else:data=client.request('POST',f'/api/v1/parts/{args.part}/publish/',{},revision)
 elif args.command=='enroll':data=client.request('POST',f'/api/v1/courses/{args.course}/enrollments/',{'email':args.email,'name':args.name,'role':args.role})
 elif args.command=='drop':data=client.request('DELETE',f'/api/v1/enrollments/{args.enrollment}/',{})
 else:
  resource='reports/missing-graders' if args.command=='missing-graders' else args.command
  from urllib.parse import urlencode
  params={k:v for k,v in {'assignment_ids':args.assignment_ids,'enrollment_ids':args.enrollment_ids}.items() if v}
  data=list(client.rows(f'/api/v1/courses/{args.course}/{resource}/'+('?' + urlencode(params) if params else '')))
 if getattr(args,'output',None):
  args.output.parent.mkdir(parents=True,exist_ok=True)
  if args.output.suffix.lower()=='.csv' and isinstance(data,list):
   with args.output.open('w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(data[0]) if data else ['part_id']);writer.writeheader()
    for row in data:writer.writerow({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in row.items()})
  else:args.output.write_text(json.dumps(data,indent=2)+'\n')
  print(f'Saved {len(data) if isinstance(data,list) else 1} records to {args.output}')
 else:print(json.dumps(data,indent=2))

if __name__=='__main__':
 try:main()
 except (ValueError,RuntimeError,requests.RequestException) as exc:print(str(exc),file=sys.stderr);sys.exit(1)
