#!/usr/bin/env python3
"""Create an isolated synthetic course through the local Docker Compose backend."""
import argparse,base64,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True);p.add_argument('--users',type=int,default=10)
    p.add_argument('--source-course',type=int,default=1);p.add_argument('--url',default='http://localhost:5173');a=p.parse_args()
    from urllib.parse import urlsplit
    u=urlsplit(a.url)
    if u.path not in {'','/'} or u.query or u.fragment or u.username or u.password:raise ValueError('Use a site origin.')
    if u.scheme!='http' or u.hostname not in {'127.0.0.1','localhost'}:raise ValueError('Use an HTTP localhost origin.')
    source=(ROOT/'loadtests/fixtures.py').read_text()
    code="import django,json\ndjango.setup()\nexec("+repr(source)+")\nfixture=create_fixture("+repr(a.run_id)+","+str(a.users)+","+str(a.source_course)+")\n"
    code+="print('TRELLIS_LOAD_FIXTURE:'+json.dumps(fixture),flush=True)\n"
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'setup.py';path.write_text(code)
        cmd=['docker','compose','exec','-T','backend','python','manage.py','shell','-c',code]
        r=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True)
        # Captured output includes synthetic passwords. Never echo it on failure.
        if r.returncode or 'TRELLIS_LOAD_FIXTURE:' not in r.stdout:raise RuntimeError('Fixture creation failed. No credentials were printed; inspect the synthetic course before retrying.')
        fixture=json.loads(r.stdout.split('TRELLIS_LOAD_FIXTURE:',1)[1].splitlines()[0]);fixture['url']=a.url.rstrip('/')
    target=ROOT/'var/loadtests'/a.run_id;target.mkdir(parents=True,mode=0o700,exist_ok=True);target.chmod(0o700)
    destination=target/'fixture.json'
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump(fixture,f,indent=2)
    print('Synthetic course:',fixture['course_id'],'| students:',len(fixture['accounts']),'| outline parts:',fixture['copied_parts'])
    print('Private fixture saved:',destination)
if __name__=='__main__':main()
