# Updating Trellis

The repository is `/Users/benny/Downloads/1301_proj/course.60_uqjig/cs1301-platform`.
GitHub stores platform source. Azure runs the deployed preview. They are separate:
pushing a commit does not currently deploy it to Azure.

## Course content

Edit lessons, exercises, files, rubrics, and the course structure through Trellis's
staff interface. Save a draft and publish when ready. Use the Azure site to change
the shared preview's content; edits on localhost affect only the local database.
Course content and student work do not belong in Git. An application-image update
does not replace the course database or private files.

## Platform source

Open the repository in VS Code. React screens are in `frontend/src`, Django is in
`backend`, the isolated execution implementation is in `runner`, and Azure
configuration is in `deploy/azure`.

Start local development with Docker Desktop running:

```sh
docker compose up -d postgres redis backend celery frontend
```

Open http://localhost:5173. Frontend source changes appear automatically. Rebuild
containers when dependencies or Dockerfiles change. Local Python Run/Submit also
needs the separate execution worker described in the main README.

Before publishing source changes, inspect the changed files and run the relevant
checks. For frontend changes, `cd frontend && npm run build` checks TypeScript and
builds the app. For backend changes, run `.venv/bin/python backend/manage.py test`.

To push your work on the current branch:

```sh
git status
git diff
git add path/to/changed-file path/to/new-file
git commit -m "Describe what changed"
git push
```

Replace the paths in `git add` with the files you intend to include. New files need
to be added explicitly too. Keep `.env`, credentials, `var/`, and private course
files out of commits. Check `git status` before committing.

When collaborating, start from a clean checkout and pull the latest work before
editing. For changes that need review, create a branch with
`git switch -c feature/short-description`, push it with
`git push -u origin feature/short-description`, and open a GitHub pull request.
Avoid force-pushing a shared branch.

## Deploy to the Azure preview

Start Docker Desktop. Sign into Azure if needed with `az login`, then select the
project subscription with `az account set --subscription 'CoC - Production'`.
From the repository root, choose a fresh image tag for each deployment:

```sh
trellis_tag="trellis-$(date -u +%Y%m%d-%H%M%S)"
sh scripts/push-azure-image.sh cs1301pocacr26 "$trellis_tag"
python3 scripts/repair-azure-web-config.py --image-tag "$trellis_tag"
```

The first command builds and pushes the application image. The second requests a
new Azure revision while preserving secrets, private-storage settings, and the
existing ingress configuration. Wait for the new revision to become healthy in
Azure's **Revisions and replicas** page before considering the deployment complete.
Refresh the website afterward; a hard refresh can help if the old branding remains.

Do not change registry authentication through the portal image picker: it can
replace the working repository-token configuration with an identity that lacks
image-pull permission. Use the deployment helper instead.

Database schema changes additionally require committed Django migrations and a
controlled `python manage.py migrate --noinput` operation against Azure. The
existing private maintenance script can run trusted migration code. Do not
restore a local database or rerun the initial course import to deploy source code.

The deployed preview continues running when your Mac and local Docker are off.
