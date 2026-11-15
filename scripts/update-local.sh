#!/bin/sh
# Apply pulled source and database changes without deleting local data.
set -eu
cd "$(dirname "$0")/.."
docker compose build backend celery frontend
# Do not serve the new code against the old schema during migration.
docker compose stop frontend celery backend
docker compose up -d --wait postgres redis
docker compose run --rm --no-deps backend python manage.py migrate --noinput
docker compose up -d --wait backend celery frontend
printf '\nLocal Trellis updated. Refresh your browser.\n'
