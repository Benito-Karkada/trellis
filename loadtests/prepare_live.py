#!/usr/bin/env python3
"""Explicit, tagged synthetic enrollment in the real course; no course edits."""
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True);p.add_argument('--users',type=int,default=20);p.add_argument('--course',type=int,default=1);a=p.parse_args()
 credentials=json.loads((ROOT/'var/azure-poc/login-details.json').read_text());source=(ROOT/'loadtests/fixtures.py').read_text()
 script="import django,json\ndjango.setup()\nexec("+repr(source)+")\nprint('TRELLIS_LOAD_FIXTURE:'+json.dumps(create_live_fixture("+repr(a.run_id)+","+str(a.users)+","+str(a.course)+")),flush=True)\n"
 with tempfile.TemporaryDirectory() as t:
  file=Path(t)/'setup.py';file.write_text(script);r=subprocess.run([sys.executable,str(ROOT/'scripts/azure-private-exec.py'),'--python-file',str(file)],capture_output=True,text=True)
  if r.returncode or 'TRELLIS_LOAD_FIXTURE:' not in r.stdout:raise RuntimeError('Live fixture setup failed; inspect tagged enrollments before retrying. No credentials printed.')
  fixture=json.loads(r.stdout.split('TRELLIS_LOAD_FIXTURE:',1)[1].splitlines()[0]);fixture['url']=credentials['url'].rstrip('/')
 folder=ROOT/'var/loadtests'/a.run_id;folder.mkdir(parents=True,mode=0o700,exist_ok=True);folder.chmod(0o700)
 fd=os.open(folder/'fixture.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:json.dump(fixture,f,indent=2)
 print('Enrolled',len(fixture['accounts']),'tagged test students in actual course',fixture['course_id'])
if __name__=='__main__':main()
