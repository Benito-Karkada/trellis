"""Restore existing Azure secret references and scoped registry auth (no secret reads)."""
import argparse
import json
import pathlib
import subprocess
import tempfile
import time

GROUP = 'CoC-inst-OMSCS-RG'
APP = 'cs1301-poc-web-v2'
BASE = ['az', 'resource', 'show', '-g', GROUP, '-n', APP,
        '--resource-type', 'Microsoft.App/containerApps', '--api-version', '2025-01-01', '-o', 'json']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-tag', help='Deploy this cs1301-web tag while preserving secret references')
    parser.add_argument('--enable-ingress', action='store_true', help='Enable HTTPS preview access on port 8000')
    args = parser.parse_args()
    for attempt in range(21):
        app = json.loads(subprocess.check_output(BASE))
        names = {secret['name'] for secret in app['properties']['configuration'].get('secrets', [])}
        required = {'acr-pull-password', 'django-secret-key', 'postgres-password'}
        if not required.issubset(names):
            raise SystemExit('Create the missing app secrets first: ' + ', '.join(sorted(required - names)))
        template = app['properties']['template']
        container = template['containers'][0]
        if args.image_tag:
            container['image'] = container['image'].rsplit(':', 1)[0] + ':' + args.image_tag
        env = {item['name']: item for item in container.get('env', [])}
        for name, secret in [('SECRET_KEY', 'django-secret-key'), ('POSTGRES_PASSWORD', 'postgres-password')]:
            if name == 'POSTGRES_PASSWORD' and env.get(name, {}).get('secretRef'):
                continue  # Preserve the least-privilege runtime credential.
            env[name] = {'name': name, 'secretRef': secret}
        environment_id = app['properties'].get('environmentId') or app['properties'].get('managedEnvironmentId')
        environment = json.loads(subprocess.check_output([
            'az', 'resource', 'show', '--ids', environment_id,
            '--api-version', '2025-01-01', '-o', 'json']))
        host = APP + '.' + environment['properties']['defaultDomain']
        env['ALLOWED_HOSTS'] = {'name': 'ALLOWED_HOSTS', 'value': host + ',localhost'}
        env['CSRF_TRUSTED_ORIGINS'] = {'name': 'CSRF_TRUSTED_ORIGINS', 'value': 'https://' + host}
        container['env'] = list(env.values())
        template['revisionSuffix'] = 'secretfix-' + str(int(time.time()))
        body = {'properties': {
            'configuration': {'registries': [{
                'server': container['image'].split('/')[0],
                'username': 'cs1301-poc-web-pull-token',
                'passwordSecretRef': 'acr-pull-password',
            }]},
            'template': template,
        }}
        if args.enable_ingress:
            body['properties']['configuration']['ingress'] = {
                'external': True, 'targetPort': 8000, 'transport': 'auto',
                'allowInsecure': False,
            }
        with tempfile.TemporaryDirectory(prefix='cs1301-web-config-') as folder:
            path = pathlib.Path(folder) / 'patch.json'
            path.write_text(json.dumps(body))
            result = subprocess.run([
                'az', 'rest', '--method', 'patch', '--url',
                'https://management.azure.com' + app['id'] + '?api-version=2025-01-01',
                '--body', '@' + str(path), '--query',
                '{state:properties.provisioningState,latest:properties.latestRevisionName}', '-o', 'json',
            ], capture_output=True, text=True)
        if result.returncode == 0:
            print('Configuration accepted; existing secret values were preserved.', flush=True)
            print('HTTPS ingress enabled.' if args.enable_ingress else 'Ingress unchanged.', flush=True)
            print(result.stdout, flush=True)
            return
        if 'ContainerAppOperationInProgress' not in result.stderr:
            print(result.stderr, flush=True)
            raise SystemExit(result.returncode)
        if attempt == 20:
            raise SystemExit('Azure still holds the operation lock. No replacement revision could be submitted.')
        print('Azure is finishing the previous operation; retrying in 15 seconds.', flush=True)
        time.sleep(15)


if __name__ == '__main__':
    main()
