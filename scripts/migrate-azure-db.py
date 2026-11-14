"""Run trusted Django migrations with a separate administrator connection.

The web application's runtime credentials and revision are never changed.
Uses Azure authorization to read the existing deployment secret only for this
short-lived maintenance process; no credentials are printed or retained.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',default='cs1301-poc-web-v2')
    parser.add_argument('--group',default='CoC-inst-OMSCS-RG')
    parser.add_argument('--admin-user',default='cs1301admin')
    args=parser.parse_args()
    def az(*parts):
        result=subprocess.run(['az',*parts,'--only-show-errors','-o','json'],capture_output=True,text=True)
        if result.returncode:raise RuntimeError('Azure administration request failed; no secret or response body was printed.')
        return json.loads(result.stdout)
    app=az('containerapp','show','-g',args.group,'-n',args.app)
    secrets=az('rest','--method','post','--url','https://management.azure.com'+app['id']+'/listSecrets?api-version=2025-01-01')
    password=next(s['value'] for s in secrets['value'] if s['name']=='postgres-password')
    source=('import os\nos.environ["POSTGRES_USER"]='+repr(args.admin_user)+'\nos.environ["POSTGRES_PASSWORD"]='+repr(password)+
            '\nimport django\ndjango.setup()\nfrom django.core.management import call_command\ncall_command("migrate",interactive=False)\n')
    with tempfile.TemporaryDirectory(prefix='trellis-db-migrate-') as folder:
        script=Path(folder)/'migration.py';script.touch(mode=0o600);script.write_text(source)
        result=subprocess.run([sys.executable,str(ROOT/'scripts/azure-private-exec.py'),'--app',args.app,'--python-file',str(script)],capture_output=True,text=True)
        if result.returncode or 'CS1301_MAINTENANCE_DONE' not in result.stdout:
            raise RuntimeError('Migration failed; web runtime credentials were unchanged. No secret or error body was printed.')
        print('Migrations completed; the web app still uses its restricted runtime database role.')

if __name__=='__main__':main()
