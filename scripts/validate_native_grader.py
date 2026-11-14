#!/usr/bin/env python3
"""Validate a manually converted grader in Docker and mark its upload bundle ready."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runner'))
from grading.docker_executor import DockerExecutor
from grading.engine import grade
from grading.manifest import load_definition
from prepare_native_graders import workspace
from pull_ferb import cached_parts
from upload_native_graders import bundle_digest,private_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=ROOT/'var/native-graders/manifest.json')
    parser.add_argument('--part',type=int,required=True)
    parser.add_argument('--definition',type=Path,required=True)
    parser.add_argument('--positive',type=Path,required=True)
    parser.add_argument('--negative',type=Path,required=True,action='append')
    parser.add_argument('--entrypoint',required=True)
    parser.add_argument('--reference',type=Path,help='Private reference source for random cases; defaults to the correct solution')
    parser.add_argument('--archives',type=Path,default=ROOT/'var/vocareum-coding-archives')
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text());rows=[r for r in manifest['parts'] if r['part_id']==args.part]
    if len(rows)!=1:parser.error('Part must appear exactly once in the conversion manifest.')
    row=rows[0];archive=cached_parts(args.archives,'144164').get(str(row.get('vocareum_part_id')))
    if not archive:parser.error('Resolve this part’s source mapping before validating it.')
    files=workspace(archive[1])
    if args.entrypoint not in files:parser.error('Entrypoint must be a file in the original student workspace.')
    definition=json.loads(args.definition.read_text());exercise=load_definition(definition)
    positive=args.positive.read_text();negatives=[p.read_text() for p in args.negative];executor=DockerExecutor()
    reference=(args.reference.read_text() if args.reference else positive) if definition.get('random_cases') else None
    if not grade(positive,exercise,executor,files=files,oracle_source=reference,oracle_files=files,random_seed=1301)['passed']:raise SystemExit('The correct solution did not pass. Bundle was not changed.')
    for i,negative in enumerate(negatives,1):
        if grade(negative,exercise,executor,files=files,oracle_source=reference,oracle_files=files,random_seed=1301)['passed']:raise SystemExit(f'Incorrect solution {i} passed. Bundle was not changed.')
    root=args.manifest.parent;folder=root/f'part-{args.part}';folder.mkdir(parents=True,exist_ok=True)
    private_json(folder/'autograder.json',definition)
    target=folder/'correct.py';target.write_text(positive);target.chmod(0o600)
    paths=[]
    for i,negative in enumerate(negatives,1):
        path=folder/f'incorrect-{i}.py';path.write_text(negative);path.chmod(0o600);paths.append(str(path.relative_to(root)))
    row.update(status='ready',entrypoint=args.entrypoint,definition=str((folder/'autograder.json').relative_to(root)),
        validation={'status':'passed','positive':str(target.relative_to(root)),'negatives':paths})
    row.pop('reason',None)
    if reference is not None:
        path=folder/'reference.py';path.write_text(reference);path.chmod(0o600);row['reference']=str(path.relative_to(root))
    row['validation']['bundle_sha256']=bundle_digest(row,definition,positive,negatives,reference)
    private_json(args.manifest,manifest)
    print(f'Part {args.part}: correct solution passed, {len(negatives)} incorrect solutions rejected. Bundle is ready; nothing was uploaded.')


if __name__=='__main__':main()
