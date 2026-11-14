# Working on Trellis locally

Clone the repository and follow the [README](../README.md). Each developer runs their own Docker services and local database. Sharing source changes does not share local accounts, course edits, submissions, or private files.

## Source changes

Create a branch before editing:

```sh
git pull --ff-only
git switch -c feature/short-description
```

React code is in `frontend/src`, Django code is in `backend`, and Python execution code is in `runner`. Development containers reload mounted source changes. Rebuild containers after dependency changes; restart the separate worker after runner changes.

Run the relevant checks from the README, then commit the intended files and push:

```sh
git status
git diff
git add path/to/changed-file
git commit -m "Describe the change"
git push -u origin feature/short-description
```

Open a pull request for review. Keep `.env`, local database files, private media, tokens, and `var/` out of Git. Existing course content is edited and published through the instructor UI.

## Schema changes

```sh
docker compose exec -T backend python manage.py makemigrations
docker compose exec -T backend python manage.py migrate
```

Commit generated migration files with the code that requires them. Normal container startup applies committed migrations automatically.

## Local services

`docker compose down` stops services and retains the local volumes. `docker compose up -d` starts them again. The host execution worker runs separately; stop it with Ctrl+C in its terminal.

To create a Django administrator for inspecting your own local database:

```sh
docker compose exec backend python manage.py createsuperuser
```

Open http://localhost:8000/admin/ (or your configured backend port). Course instructor/TA roles and Django administration are separate permissions.
