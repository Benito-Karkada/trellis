#!/usr/bin/env python3
"""Prepare and verify the source-matched ungraded CS1301 example archives.

Reads var/vocareum-extra-archives and writes local, ignored API import plans.
Large public MARTA data is losslessly packed to fit the POC workspace budget.
No legacy private code is imported or executed.
"""
import base64,json,lzma,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'runner'))
from grading.docker_executor import DockerExecutor
from grading.spec import RunRequest
out=ROOT/'var/native-example-imports';out.mkdir(exist_ok=True);plans=[]
helper='''"""Prepare the complete public MARTA dataset for this disposable workspace."""
import base64,io,lzma,shutil
from pathlib import Path
def prepare_marta_data():
    target=Path("marta_01-18-2016.csv")
    if not target.exists():
        encoded="".join(path.read_text(encoding="ascii") for path in sorted(Path("data").glob("marta-*.b85")))
        with lzma.open(io.BytesIO(base64.b85decode(encoded)),"rb") as source,target.open("wb") as destination:
            shutil.copyfileobj(source,destination,65536)
    return str(target)
'''
for manifest in sorted((ROOT/'var/vocareum-extra-archives').glob('exercises/*/*/manifest.json')):
 m=json.loads(manifest.read_text());id=m['trellis_part_id'];files={str(p.relative_to(manifest.parent/'startercode')):p.read_text() for p in (manifest.parent/'startercode').rglob('*') if p.is_file()};entry=sorted(p for p in files if p.endswith('.py'))[0]
 if id==1626:
  payload=base64.b85encode(lzma.compress((ROOT/'var/vocareum-coding-archives/shared/course/public/marta_01-18-2016.csv').read_bytes())).decode()
  for i,start in enumerate(range(0,len(payload),900000),1):files[f'data/marta-{i:02d}.b85']=payload[start:start+900000]
  files['course_data.py']=helper;entry='Marta.py';files[entry]=files[entry].replace("marta_file = open('/voc/course/public/marta_01-18-2016.csv', 'r')", "from course_data import prepare_marta_data\nmarta_file = open(prepare_marta_data(), 'r')")
 leading=[]
 for line in files[entry].splitlines():
  if line.startswith('#'):leading.append(line[1:])
  elif not line.strip() and not leading:continue
  else:break
 instructions='\n'.join(leading).strip().replace('the dropdown in the top left','Files')
 plan={'part_id':id,'vocareum_part_id':m['part_id'],'course_id':m['course_id'],'title':m['part_name'],'entrypoint':entry,'files':files,'content':{'version':1,'blocks':[{'id':'coding','type':'coding','prompt':[{'type':'text','text':instructions}]}]}}
 path=out/f'part-{id}.json';path.write_text(json.dumps(plan,indent=2));path.chmod(0o600);plans.append({'part_id':id,'file':path.name})
 if id==1626:
  assert sum(len(t.encode()) for t in files.values())<2_000_000
  source=files[entry]+'\nprint(sum(1 for _ in marta_file))\n'
  observation=DockerExecutor().run(RunRequest(source,files=files,timeout_seconds=10))
  expected=sum(1 for _ in (ROOT/'var/vocareum-coding-archives/shared/course/public/marta_01-18-2016.csv').open())
  assert observation.status=='ok' and observation.stdout.strip()==str(expected),(observation.status,observation.stdout)
  print('Complete MARTA dataset verified:',expected,'rows;',sum(len(t.encode()) for t in files.values()),'workspace bytes.',flush=True)
 else:
  observation=DockerExecutor().run(RunRequest(files[entry],files=files,timeout_seconds=5));print(id,entry,observation.status,flush=True)
  assert observation.status=='ok',(id,observation.stdout)
(out/'manifest.json').write_text(json.dumps(plans,indent=2))
