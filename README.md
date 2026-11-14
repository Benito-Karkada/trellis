<p align="center">
  <img src="frontend/src/assets/trellis-classic.png" alt="Trellis rubber duck" width="190" />
</p>

# Trellis

A local course-building and learning platform. Instructors create lessons and exercises; students read, practice, write Python, and receive feedback in one workspace. The included CS 1301 course has 26 sections and 1,064 parts, including readings, videos, native questions, coding exercises, sandboxes, and all six programming quizzes.

## Start locally

Install and start **Docker Desktop**. Install **Python 3.12 or newer** on your computer, then:

```sh
git clone https://github.com/Benito-Karkada/trellis.git
cd trellis
python3 scripts/setup-local.py
```

The first run builds the containers and can take a few minutes. Later runs reuse the images. Setup creates a private `.env`, starts the local services, applies database migrations, and loads the complete course from `course-data/cs1301.tar.gz`. Running it again preserves your content edits, saved work, and existing local passwords.

Open **http://localhost:5173** and choose **Open local instructor workspace**. You can also sign in using:

| Role | Email | Local demo password |
| --- | --- | --- |
| Instructor | `instructor@trellis.local` | `trellis-demo-2026` |
| Student | `student@trellis.local` | `trellis-demo-2026` |

These accounts are for your local development setup only. The instructor can manage enrollment and create additional users from Course settings. No external service account is required.

## Enable Python Run / Submit

The web app queues execution requests. A separate worker on your computer runs each program in a disposable Docker sandbox. Keep Docker Desktop running and start this worker in a **second terminal**, from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sh scripts/start-worker.sh
```

Leave that terminal running while using Run/Submit. It builds the sandbox image on first use. Only the worker controls Docker; the web container has no Docker socket. Student containers have no network or host-directory mounts and have CPU, memory, output, and execution-time limits.

To verify submission, points, feedback replacement, and sample-answer release:

```sh
docker compose exec -T backend python manage.py shell < scripts/smoke_execution.py
```

## Code visualizer

Open **Code visualizer** from the home screen to explore editable examples of loops, conditions, lists, dictionaries, tuples, functions, objects, search, sorting, and recursion. Build a trace, then use Play, previous/next, the step slider, and speed control to follow execution. The view shows the next line, variables, shared object references, collection contents, call frames, return values, and output.

After a correct submission to a regular coding exercise, **Visualize sample** opens a read-only sample-answer walkthrough. Programming quizzes never expose this tool or their samples. Instructors can inspect regular published samples without earning credit first; student view follows student unlock rules.

The visualizer uses the same local worker as Run/Submit. If you pulled this feature into an existing setup, apply `docker compose exec -T backend python manage.py migrate` and restart `sh scripts/start-worker.sh` to rebuild the sandbox and load the new worker code. It does not change scores, submissions, or saved work. See [visualizer behavior and limits](docs/CODE_VISUALIZER.md).

## Everyday development

```sh
# Start existing services without rebuilding.
docker compose up -d

# See status and logs.
docker compose ps
docker compose logs -f backend frontend

# Stop services while keeping your local course and saved work.
docker compose down
```

Frontend and backend source are mounted into their development containers. Changes reload automatically. Rebuild after changing dependencies, Dockerfiles, or the shared grading package with `docker compose up -d --build`. Restart the host worker after changing runner code.

If ports 5173 or 8000 are in use, change `TRELLIS_FRONTEND_PORT` and `TRELLIS_BACKEND_PORT` in `.env`, recreate the containers, and restart the worker. The worker reads the local backend port automatically. The database, cache, and private files use this project's own Docker volumes; only the web and API ports bind to localhost.

The bundled snapshot initializes a fresh local database once. Normal edits stay in your database and are not written back into the bundle. Edit normal course content in the instructor UI. Use Config to edit instructions, question JSON, files, and grading definitions; save and publish to update student content. The staff preview uses the student renderer. Course data and student work stay in the local database and private media volume, outside Git.

## Checks

```sh
# Backend tests against an isolated test database.
docker compose exec -T backend python manage.py test core --noinput

# TypeScript and frontend build.
docker compose exec -T frontend npm run build

# Runner unit tests, after creating the local venv above.
cd runner
../.venv/bin/python -m unittest discover -s tests
```

For the optional Docker-backed runner checks, set `RUN_DOCKER_TESTS=1` when running the last command after the sandbox image has been built.

## Project layout

- `frontend/` — React, TypeScript, Monaco editor, course and staff interfaces.
- `backend/` — Django models, authentication, course authoring, grading records, REST APIs, and tests.
- `runner/` — Python grading engine and isolated execution worker.
- `scripts/` — local setup, worker startup, API client, and execution smoke check.
- `course-data/` — the full course baseline, with exercise files, native graders, solutions, and referenced images; no original accounts or student work.
- `loadtests/` — optional bounded local load tests.
- `extensions/trellis-ed/` — optional discussion browser extension.
- `docs/` — feature and local-development documentation.

See [local collaboration](docs/UPDATING.md), [grading](docs/FIRST_PARTY_GRADING.md), [staff API](docs/REST_API.md), and [local load testing](docs/LOAD_TESTING.md).
