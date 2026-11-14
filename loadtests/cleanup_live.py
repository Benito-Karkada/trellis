#!/usr/bin/env python3
"""Delete exact tagged live-test identities after reports are saved and jobs drain."""
import argparse,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixture',type=Path,required=True);a=p.parse_args();f=json.loads(a.fixture.read_text())
 if not f.get('live_course') or not (a.fixture.parent/'summary.json').exists():raise ValueError('Save the live-course report before cleanup.')
 source=(ROOT/'loadtests/fixtures.py').read_text();safe={k:f[k] for k in ('run_id','live_course','course_id','accounts','enrollment_ids')}
 for row in safe['accounts']:row.pop('password',None)
 script="import django,json\ndjango.setup()\nexec("+repr(source)+")\nprint('TRELLIS_CLEANUP:'+json.dumps(cleanup_live_fixture("+repr(safe)+")),flush=True)\n"
 with tempfile.TemporaryDirectory() as t:
  file=Path(t)/'cleanup.py';file.write_text(script);r=subprocess.run([sys.executable,str(ROOT/'scripts/azure-private-exec.py'),'--python-file',str(file)],capture_output=True,text=True)
  if r.returncode or 'TRELLIS_CLEANUP:' not in r.stdout:raise RuntimeError('Cleanup stopped safely; test identities remain. Inspect queued jobs and exact IDs before retrying.')
  result=json.loads(r.stdout.split('TRELLIS_CLEANUP:',1)[1].splitlines()[0])
 (a.fixture.parent/'cleanup.json').write_text(json.dumps(result,indent=2));print('Cleanup verified:',result['removed'],'other accounts preserved:',result['other_user_accounts_preserved'])
if __name__=='__main__':main()
