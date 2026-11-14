# Azure POC image

The `cs1301-web` image contains the built React frontend and Django/Gunicorn on
port 8000. It also supports the Celery worker by overriding the container command.
Local Compose remains unchanged. The image contains no course data, local database,
`.env` files, or credentials. The Dockerfile-specific ignore file allowlists source.

## Upload from a Mac

1. Start Docker Desktop and install Azure CLI (`brew install azure-cli`).
2. Run `az login`, completing Georgia Tech sign-in in your browser.
3. Select the subscription: `az account set --subscription 'CoC - Production'`.
4. From the repository root, run `sh scripts/push-azure-image.sh`.

The script discovers the registry's hashed login server, builds Linux/AMD64 for
Azure, authenticates without the registry admin account, pushes
`cs1301-web:poc-v1`, and queries Azure for its digest. Your identity needs AcrPush
on this registry when it uses classic RBAC registry permissions. Creating Azure
resources alone does not necessarily grant push or role-assignment permission.
Do not grant subscription-wide Contributor to solve an image push failure.

Portal values: Image `cs1301-web`; Image tag `poc-v1`; target port `8000`.

## Settings required before the app can start

- `SECRET_KEY`: dedicated random secret (Container App secret; Key Vault when authorized)
- `ALLOWED_HOSTS`: exact Container App hostname, comma separated if multiple
- `CSRF_TRUSTED_ORIGINS`: full HTTPS origins, comma separated
- `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `POSTGRES_DB=cs1301`, `POSTGRES_PORT=5432`
- `AZURE_STORAGE_ACCOUNT`: private storage account name
- `AZURE_STORAGE_CONTAINER=private-media`
- `AZURE_CLIENT_ID`: client ID of the attached user-assigned managed identity, or
  `AZURE_STORAGE_SAS_TOKEN`: container-scoped expiring SAS (POC fallback)
- `CELERY_BROKER_URL`: TLS Redis URL with authentication
- `RUNNER_TOKEN`: dedicated execution-controller secret if that API is used

For identity-based storage, the identity needs Storage Blob Data Contributor on
the private-media container. The current shared-subscription POC cannot grant roles,
so `scripts/configure-azure-poc-storage.py` creates/rotates a 90-day HTTPS-only SAS
restricted to that container. The app never receives the storage account key.
Rotate before expiry; replace with managed identity for the dedicated deployment.
Public storage access remains disabled. Private files are served by authenticated
API endpoints; the storage backend refuses direct URLs to avoid disclosing SAS.
Network access and private DNS must be configured for PostgreSQL, storage, Key
Vault and Redis. An external website does not require publicly exposing any of
those data services.

PostgreSQL is required; Azure settings never fall back to SQLite. Blob storage
fails closed until configured. Migrations are not run by each web replica: execute
`python manage.py migrate --noinput` as a controlled one-off job before enabling
traffic. Import course data separately; never bake it into the image.

For the worker, use the same image with command `celery` and arguments
`-A config.celery worker -l INFO`. Disable ingress. Adjust settings/identity for its
own permissions. Canvas passback and Azure execution integration are still
separate work; uploading this image does not implement those adapters.

Do not expose the application with DEBUG or ALLOW_LOCAL_LOGIN enabled. This is a
POC deployment package, not evidence of production security review. Azure disables
self-registration and development login. Provision POC staff accounts explicitly.
CAS, Azure runner integration, load testing, and service-role
review remain required before student deployment.

## Import course content over the private network

`python scripts/build-course-transfer.py` exports only course content from local
Compose and validates every referenced file against the private-media backup.
The ignored `var/azure-poc/course-transfer.tar.gz` contains no user accounts,
memberships, Canvas connection records, sessions, student work, or progress.
An inactive identity is created on the target to own historical content revisions.

The target command is `python manage.py import_course_transfer /tmp/course.tar.gz`.
It refuses to replace an existing course, validates checksums before writing, and
retains exact file paths and revision IDs. Blobs upload first; database content is
loaded in one transaction. A failed database import may leave private blobs, and
a retry verifies them rather than silently replacing different content.

`scripts/azure-private-exec.py` transfers a bundle and executes a trusted maintenance
script through Azure's authenticated exec connection. It needs `websocket-client`
and `certifi` in the local venv. This keeps storage and app ingress closed during
import. Do not use the maintenance channel to run student programs. Course data
stays out of both Git and the application image.

## Recover a secret-reference / registry-authentication revision failure

The initial portal revision can boot without required secrets and fail with
`Required Azure setting is missing: SECRET_KEY`. After adding the three app
secrets (`django-secret-key`, `postgres-password`, `acr-pull-password`), run:

```
python3 scripts/repair-azure-web-config.py
```

This script never lists secret values. It updates environment secret references,
derives allowed hosts and CSRF origin from the actual environment domain, restores
repository-token image authentication, and submits a fresh revision. Ingress stays
unchanged. It retries an existing `ContainerAppOperationInProgress` lock for about
five minutes, then stops if Azure still holds the lock. A successful script exit
means the update was accepted, not that the new revision is healthy; inspect the
revision and console logs afterward.

The portal's registry image selector may reselect `system-environment` auth when
editing an existing ACR-backed app. That breaks image pulls for this POC because
its environment identity has no AcrPull role. Verify `configuration.registries`
uses `username` and `passwordSecretRef` after any portal edit. Do not redeploy the
initial example parameters over an already configured app: their empty bootstrap
settings will not preserve later application secrets or configuration.

## Current POC state (2026-11-09)

- Dedicated, unpeered VNet: `cs1301-poc-vnet`, South Central US, in
  `CoC-inst-OMSCS-RG`. It uses the existing POC address scheme in a separate
  isolated network; no campus routing or OMSCS peering is configured.
- Four dedicated subnets: app `10.0.1.0/24`, database `10.0.2.0/26`, private
  endpoints `10.0.3.0/26`, grader `10.0.4.0/27`.
- Environment: `cs1301-poc-env-v2`. Web: `cs1301-poc-web-v2`, image
  `cs1301-web:poc-v53`, HTTPS on port 8000.
- Preview: https://cs1301-poc-web-v2.agreeablewave-32290e77.southcentralus.azurecontainerapps.io
- Database: `cs1301-poc-db27`, private access only. The network migration verified
  all 38 public tables and 36,874 rows against the frozen source using row counts
  and checksums. The actual course has 26 sections and 1,064 activities; the
  two previously retained test courses were also preserved.
- Storage account and Key Vault are unchanged; their new private endpoints are
  `cs1301-poc-storage-pe-v2` and `cs1301-poc-kv-pe-v2`. Existing private addresses
  are mirrored in the isolated VNet, preserving DNS during migration.
- The grader remains `cs1301-poc-grader-vm`, now attached through
  `cs1301-poc-grader-nic-v2` to the dedicated VNet. Its original disk, public IP,
  VM size and security profile were preserved. Two worker slots are enabled.
- Existing accounts, passwords, course content, grades and workspaces were
  preserved. Instructor credentials remain in ignored
  `var/azure-poc/login-details.json`, mode 0600; never commit this file.
- `TRELLIS_MAINTENANCE_MODE=1` pauses new page/API changes while retaining
  authenticated worker claim/completion endpoints so existing work can drain.
  Normal operation uses `0` or leaves the setting unset.
- After explicit cleanup approval, the old app/database/private endpoints,
  obsolete DNS links and all four Trellis-added OMSCS subnets were removed.
  The owner's original default subnet and VM attachment were verified unchanged.
  Azure is still finalizing deletion of the empty legacy environment
  `cs1301-poc-vnet-env`; its old subnet no longer exists. Private rollback
  configurations, grader snapshot and integrity evidence are retained in
  ignored `var/azure-poc/network-migration-20261109/` and Azure.
- Storage SAS expires 2027-02-05 UTC; rotate with the storage helper before then.
- The unused earlier Redis app `cs1301-poc-app-env` is in a different environment;
  execution uses the PostgreSQL queue rather than Redis/Celery. Canvas and GT CAS
  integration remain unconnected.

For the next source image, pass an explicit new tag to `push-azure-image.sh`, then
use `repair-azure-web-config.py --image-tag TAG` to preserve working registry
authentication and secret references. Use `--enable-ingress` only when enabling
HTTPS access is intended. Local Compose is not needed to keep this Azure preview
online.


## Restricted runtime database account (2026-11-09)

The live web app uses `trellis_runtime` and the `runtime-db-password` secret.
Do not redeploy bootstrap example parameters or replace it with `cs1301admin`.
The configuration-repair helper preserves this credential reference.

For future schema changes, deploy the compatible image, then run:

```
python3 scripts/migrate-azure-db.py
```

This authorizes a short-lived maintenance process through Azure, using the
separate administrator credential already stored in the app configuration. It
never changes the web runtime role. Plan maintenance/expand-contract migrations
where needed; this command does not make incompatible schema changes safe while
requests are running. Database grants for future tables are set through the
administrator's default privileges. See `docs/SECURITY.md` for the role matrix,
current protections, and outstanding edge WAF/DDoS work.
