#!/usr/bin/env python3
"""Download the seven final coding archives, matching supplied Ferbs by filename.

Uses the same export API client as check.py's download path. Raw ZIPs and supplied
Ferbs are retained as migration references; this script never executes them.
"""
import argparse
import ast
import json
from pathlib import Path
import re
import shutil
from download_vocareum_coding_exercises import VocareumClient,exercise_path,export_folder,atomic_json

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token-file',type=Path,default=ROOT.parent/'token.txt')
    parser.add_argument('--discovery',type=Path,default=ROOT/'var/api-reports/vocareum-final-discovery.json')
    parser.add_argument('--ferbs',type=Path,default=ROOT/'var/ferb-sources')
    parser.add_argument('--output',type=Path,default=ROOT/'var/vocareum-final-problems')
    args=parser.parse_args();provided={}
    for path in args.ferbs.glob('voc*/private/Ferb.py'):
        tree=ast.parse(path.read_text())
        filename=next((ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='STUDENT_FILE_NAME' for t in n.targets)),None)
        if filename:
            if filename in provided:raise ValueError('Duplicate supplied Ferb entrypoint: '+filename)
            provided[filename]=path
    client=VocareumClient(args.token_file.read_text().strip());args.output.mkdir(parents=True,exist_ok=True)
    for group in json.loads(args.discovery.read_text()):
        assignment=group['assignment']
        for part in group['parts']:
            title=str(part.get('name',''))
            if not re.fullmatch(r'CS1301 Final Problem (?:[1-6]|10)',title):continue
            item={'course_id':'144164','assignment_id':str(assignment['id']),'assignment_name':assignment['name'],'part_id':str(part['id']),'part_name':title}
            directory=exercise_path(args.output,item);directory.mkdir(parents=True,exist_ok=True);manifest={**item,'folders':{}}
            for folder in ('startercode','private'):manifest['folders'][folder]=export_folder(client,'144164',item,folder,directory)
            filenames=[p.name for p in (directory/'startercode').glob('*.py')]
            matches=[(filename,path) for filename,path in provided.items() if filename in filenames]
            if len(matches)!=1:raise ValueError('Expected exactly one supplied Ferb match for '+title)
            filename,ferb=matches[0];(directory/'references').mkdir(exist_ok=True);shutil.copyfile(ferb,directory/'references/provided-Ferb.py')
            manifest.update(entrypoint=filename,provided_ferb=str(ferb.resolve()))
            if filename=='AllTimeRecord.py':
                source=directory/'startercode'/filename;source.write_text(source.read_text().replace('/voc/course/public/georgia_tech_football.csv','georgia_tech_football.csv'))
                dataset=ROOT/'var/vocareum-coding-archives/shared/course/public/georgia_tech_football.csv'
                shutil.copyfile(dataset,directory/'startercode'/dataset.name)
                manifest['source_transformations']=['Use local course dataset path; raw original remains in startercode ZIP.']
            atomic_json(directory/'manifest.json',manifest)
            print(title+': matched '+filename,flush=True)
    print('Final coding archives downloaded. Build native graders separately; no legacy grading program was run.',flush=True)


if __name__=='__main__':main()
