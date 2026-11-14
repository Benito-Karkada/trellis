# Contained Locust tests

Locust runs on your Mac; the existing Azure app and grader receive real HTTPS
requests. Nothing new is provisioned and the VM is not resized. The grader now runs two bounded execution slots on the same VM. A rising
queue can still be the bottleneck even when CPU is low.

## Install once

From the repository folder:

```bash
python3 -m venv .venv-loadtest
.venv-loadtest/bin/pip install -r requirements-loadtest.txt
```

Keep the existing app `.venv` for the maintenance/monitor scripts. Locust's
optional dependencies are separate from production requirements.

## Prepare a new run

Sign in to Azure CLI with the existing project account. Choose a unique run ID:

```bash
.venv/bin/python loadtests/prepare.py --azure \
  --run-id poc-example-10 --users 10 --source-course 1 \
  --url https://cs1301-poc-web.wittypebble-dbdb2241.southcentralus.azurecontainerapps.io
```

This creates a separate synthetic course with 10 student logins, one test
instructor, a reading, a native question and a three-case coding exercise. It
copies the source course's published, non-quiz outline and content to reproduce
outline payload size. It does not copy enrollments, student work, file blobs,
Canvas mappings, or programming quizzes. Only the synthetic coding exercise is
executed. The fixture's login details are private in ignored `var/loadtests/`;
do not commit or share that file. An existing run ID is never overwritten.

For a local database, omit `--azure` and set the normal Django settings and
PYTHONPATH environment variables before running preparation/monitoring.

## Start monitoring, then run

In one terminal:

```bash
.venv/bin/python loadtests/monitor.py --azure \
  --fixture var/loadtests/poc-example-10/fixture.json --duration 420 --interval 30
```

In another:

```bash
.venv/bin/python loadtests/run.py \
  --fixture var/loadtests/poc-example-10/fixture.json --users 10 --minutes 5 --dashboard
```

Open http://127.0.0.1:8089 while it runs. **Statistics** shows per-operation
latency/failures; **Charts** shows throughput, response times and user count.
**Stop** ends the run. The dashboard listens only on your Mac, closes after the
timed test, and its standalone HTML report remains in the run folder. Omit
`--dashboard` for a headless run. The launcher supports at most 20 students and
10 minutes; there is no distributed-test support.

Each student receives a unique account and waits 15–25 seconds between tasks.
Journeys cover login, full outline loads, assignment/part opens, question points,
Run/Submit, wrong-to-correct code changes, pace checks and **synthetic** focus
signals. Some students submit correctly first; others debug. A wrong answer
with the expected zero score is a successful test, not an HTTP failure.

The circuit breaker stops the test for >10% failed requests after 50 samples,
a grading job exceeding 60 seconds, a host/fixture mismatch, or the 160-job
execution budget. Normal tasks get up to 65 seconds to drain at shutdown.
A graceful stop does not cancel a job already accepted by the server; verify
the queue drains before another run. Treat Ctrl-C as stopping new load, not
as deleting submissions or changing grades.

## What to watch

- **Queue:** monitor output and `monitor.jsonl` show pending/running test jobs,
  oldest pending age, and queue/grading/end-to-end p50/p95 durations. The API
  monitor uses a temporary, course-scoped `submissions:read` token and revokes
  it when it exits. It never reads real students' submissions. Azure remote
  shell polling was throttled during the first test, so ongoing Azure queue
  monitoring uses the API instead. The API queue view is scoped to the test
  course; unrelated work is not included. Local trusted snapshots can show
  aggregate global queue counts without identities.
- **Autograder VM:** Azure → `cs1301-poc-grader-vm` → Monitoring → Metrics.
  Watch Percentage CPU, CPU Credits Remaining (burstable VM), network and disk.
  Available Memory Bytes is also requested, but may have no points if the VM
  is not emitting guest memory metrics. The sampler does not install an agent.
- **App:** `cs1301-poc-web` → Metrics: CPU, Working Set Bytes, Requests and
  Restart Count. Use Log stream for application exceptions. Monitor CPU
  together with latency; queued requests can be slow without HTTP failures.
- **Database:** `cs1301-poc-db26` → Metrics: CPU percent, memory percent and
  active connections. Growing connections or CPU with slow outline requests
  point toward the app/database path rather than the Python runner.
- **Guest details when needed:** VM → Run command → RunShellScript can run
  `free -h`, `uptime`, `docker stats --no-stream`, and
  `journalctl -u trellis-worker.service -n 20 --no-pager`. These commands don't
  require enabling SSH. Never display `/opt/trellis/worker.env` or credentials.

Azure metrics use one-minute buckets and can arrive late. The sampler saves
rolling ten-minute windows, which include baseline/preflight/other traffic and
must not be interpreted as exclusive per-test usage. Monitoring also adds a
small amount of traffic. A five-minute test is too short to prove sustained
burstable-CPU behavior.

## Save the results

After the run and a short cooldown:

```bash
.venv/bin/python loadtests/report.py \
  --fixture var/loadtests/poc-example-10/fixture.json
```

Open `var/loadtests/poc-example-10/report.html` for the summary or `locust.html`
for Locust's full report. CSVs contain request statistics/history and failures;
`summary.json`, `grades.json`, and `submission-review.json` retain grades,
review-index contributions, reasons, run/submit counts, and focus metrics for
the synthetic students. These are scripted signals, not AI detections.
The synthetic course and accounts remain for inspection; no cleanup removes
real course data. Stop/disable those test accounts when inspection is finished.

This is an HTTP/API capacity probe, not a browser UX/rendering test. It does
not load Monaco, render React, download static assets, stream videos, interact
with Ed, contact Canvas, take quizzes, or measure complex real grader suites.
Start small and review errors/queue drain before increasing load. Passing this
test does not establish readiness for 600–700 students.

## First recorded run (2026-11-09)

`poc-20261109-10`: 10 students, five minutes, 548 HTTP requests, zero failures;
8 Run and 12 Submit workflows all returned expected results. Course outline
p95 was about 1.5 seconds; Run/Submit p95 was about 9.9/8.6 seconds, including
client polling. The queue drained; no app restarts were observed. Peak sampled
VM CPU was 5.54%, but these Azure windows include preflight and other traffic.

Two Azure exec samples were unavailable (a diagnostic returned HTTP 429);
course-scoped REST sampling replaced remote-shell queue polling. The original
synthetic focus sender omitted the initial `away` event, so those HTTP calls
did not count as complete episodes. The sender now uses `away → hidden → back`.
A separate post-run check verified one complete episode and its review-score
contribution; it is labeled separately in the report. These are test/monitoring
issues, not Trellis request failures.

## Coordinated bursts and actual-course testing

`--profile burst` assigns half the users to coding. Those students release a
mixed Run/Submit wave together every 90 seconds, beginning 35 seconds after
startup. Other students browse/answer questions with 5–10-second think time.
Each coding student awaits its own job before scheduling another. The controller
now processes up to two accepted jobs concurrently; additional jobs wait in the
PostgreSQL queue. The same 60-second load-test job timeout and failure stops
remain enabled.

For a separate-course burst run, prepare with `--representative` to include
copies of two actual 8- and 10-case stdout graders. The source files/grading
rules are read-only references; do not delete their shared blobs on cleanup.

The user explicitly approved a subsequent test inside the actual CS 1301
course and removal of the test identities afterward:

```bash
.venv/bin/python loadtests/prepare_live.py \
  --run-id live-example-burst20 --users 20 --course 1
.venv/bin/python loadtests/smoke_representative.py \
  var/loadtests/live-example-burst20/fixture.json
.venv/bin/python loadtests/monitor.py --azure \
  --fixture var/loadtests/live-example-burst20/fixture.json --duration 660 --interval 15
# In a second terminal:
.venv/bin/python loadtests/run.py \
  --fixture var/loadtests/live-example-burst20/fixture.json \
  --profile burst --users 20 --minutes 10 --dashboard
```

Live preparation enrolls unique `loadtest-...@example.invalid` accounts named
“Load Test,” marked with a run ID and exact membership/user IDs. It reads actual
published exercises 444 and 712, their starter files, reference solutions and
graders; it does not change any course content or deadlines. It uses an actual
native exercise and a reading for the other journeys. Applicable due dates are
honored; a practice attempt is not required to earn credit. Test enrollments
have no Canvas user IDs, so they cannot generate Canvas grade passback. No
quizzes are opened. Staff monitoring requests filter by the exact test
enrollment IDs, and saved reports exclude existing students.

After stopping load, letting accepted jobs finish, and letting the monitor
revoke its temporary token:

```bash
.venv/bin/python loadtests/report.py \
  --fixture var/loadtests/live-example-burst20/fixture.json
.venv/bin/python loadtests/cleanup_live.py \
  --fixture var/loadtests/live-example-burst20/fixture.json
```

Cleanup requires a saved report, the exact tagged test identities, student
roles, blank Canvas IDs, no other enrollments, and no pending/running jobs. It
removes those accounts and their test submissions, progress, events, workspaces,
and sessions. It asserts that every other user account survives. It never
deletes course activities, revisions or file blobs. The deleted test records
remain available only in the private saved reports. Treat the private fixture
as a credential file; do not publish it.

## Actual-course run (2026-11-09)

`live-20261109-burst20`: 20 tagged students in the actual CS 1301 course,
10 minutes, seven waves of 10 concurrent requests (five Run and five Submit).
All 3,952 HTTP requests and all 70 timed execution workflows passed. Each
wave's arrivals spanned about 0.8–2.2 seconds; queue wait reached 40.9 seconds.
The queue drained between waves and after the run. Eight additional jobs were
preflight controls, excluded from the timed Locust workflow counts.

After saving grades, review contributions, job timestamps and metrics, cleanup
deleted all 20 test users, 78 jobs, 150 submissions, 42 progress records and
1,916 learning events, plus associated sessions/workspaces. It verified the
other 42 user accounts, pre-existing course progress totals and the published
outline were unchanged. No Canvas grade updates were created by these test
enrollments, which had blank Canvas IDs. The private run directory contains
`cleanup.json` and the archived results. The earlier separate-course burst run
was interrupted when the user requested the actual-course run.

## Execution safety checks

`loadtests/smoke_execution_safety.py` accepts a newly prepared, tagged live
fixture with 2–5 students. It tests busy loops, twelve simultaneous Run/Submit
requests from one student, reset attempts while queued and running, clear
student feedback, and successful Run/Submit recovery. Duplicate requests and
active-job resets must return HTTP 409; only one request may create a job.
The script saves `summary.json`, including timeout timings, before cleanup.

```sh
.venv/bin/python loadtests/smoke_execution_safety.py \
  var/loadtests/YOUR-NEW-RUN/fixture.json
.venv/bin/python loadtests/cleanup_live.py \
  --fixture var/loadtests/YOUR-NEW-RUN/fixture.json
```

Execution normally gets a two-second student-code budget, independent of
container startup. Exercise-specific configured time limits still apply.
The controller retains a separate hard deadline and forcibly removes the
container, including if student code interferes with its inner timer. Grading
stops at the first timeout or output-limit violation; remaining checks are
reported as not run and cannot earn credit. This is a bounded execution
policy, not a claim that arbitrary infinite loops can be proved statically.

The initial Azure safety run (`live-20261109-safety5`) accepted one of twelve
concurrent requests and blocked eleven duplicates, blocked the queued reset,
and recovered successfully after all five looping jobs. Empty-queue Run and
Submit timeout responses took 5.11 and 4.90 seconds end to end, including
queue pickup, container startup, polling, and network overhead. All five
accounts and associated records were removed afterward.


## Bounded parallel execution

The dedicated worker defaults to `RUNNER_CONCURRENCY=2`; accepted values are
1–4. Each slot has its own HTTP session and claims one job at a time through
PostgreSQL's existing locked queue. Containers retain their individual CPU,
memory, output and time limits. Slots process different students' jobs; tests
inside one submission remain sequential, preserving timeout early stopping.
The per-account single-active-job rule still prevents duplicate admission.
Stopping the service prevents new claims while existing jobs finish.

`loadtests/smoke_parallel_execution.py` uses a fresh tagged live fixture with
2–10 students for one simultaneous Run/Submit burst. It verifies correct results
and exactly two overlapping server execution intervals, and saves queue timings
and Azure metrics to `summary.json`. Run `cleanup_live.py` afterward to remove
only those test identities. The earlier ten-minute burst results in this file
were collected before parallel execution was enabled.

Azure verification (`live-20261109-parallel10`, 2026-11-09): one simultaneous
burst of ten jobs (five Run and five Submit) completed with correct results.
Server claim/completion intervals confirmed a peak of exactly two active jobs.
The longest queue wait was 27.990 seconds and the longest client workflow was
37.015 seconds. This burst includes both 8- and 10-case Submit graders; it is
not a matched before/after benchmark against the older burst, whose Submit
jobs all used the 8-case grader. No VM resize or web redeployment was needed.
