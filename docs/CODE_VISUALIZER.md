# Code visualizer

## Student experience

The home screen has separate Course and Code visualizer tabs. The library includes eleven editable Python examples: for loops, while loops, branching, list aliases/copies, dictionary counting, tuple unpacking, functions, classes, binary search, insertion sort, and recursion. Students can replace an example with their own small program and change its values directly in the code editor.

Building a trace runs real CPython in a disposable Docker container. Playback happens entirely in the browser after execution finishes. The highlighted line is the **next** statement to execute; the displayed variables reflect statements already executed. Return snapshots show the return value before the frame leaves the stack. The replay supports step forward/backward, first step, scrubbing, play/pause, and speed selection. Shared references have stable IDs; clicking one highlights the corresponding object. Changed variables and collection entries are highlighted.

For a regular published coding exercise, a successful full-credit submission unlocks Visualize sample. The API verifies the successful submission for that user and revision. It reads the selected sample from staff files on the server, ignoring any source supplied by the client. Multiple sample answers are selectable. Where supported, a public-test-input selector replaces module input variables or adds a visible function call to the sample. The displayed program is exactly the one traced; expected answers are omitted. Choose Sample as written to trace the original code. Inputs requiring specialized fixtures are omitted from the selector. Replaying does not modify the student's editor, workspace, grade, or submission history. Instructors and TAs can inspect regular published samples; staff in student view follow the student unlock rule. Quiz samples are unavailable to every role through these endpoints, and the standalone library is blocked during an active exam.

## Local setup

Start the normal Docker services, apply migrations, and run the host worker:

```sh
docker compose up -d
docker compose exec -T backend python manage.py migrate
sh scripts/start-worker.sh
```

Restart the worker after pulling runner or sandbox changes. The script rebuilds `cs1301-student-python:local`. No new dependency or cloud resource is needed.

## API

All routes require a logged-in, enrolled user. POST routes require the normal CSRF cookie/header.

| Request | Body / response |
| --- | --- |
| `GET /api/visualizations/samples/<activity_id>/` | Authorized regular samples: `{title, revision, samples: [{path, source}], cases, selected_case}`. Use `?case=<id>` or `?case=original` to select public inputs. Locked or quiz samples return 403. |
| `POST /api/visualizations/` | Free lab: `{source, stdin?}`. Exercise: `{activity, sample, revision?, case?, stdin?}` with a server-owned sample path. Returns `{id, status}`; include the fetched revision to reject stale walkthroughs with 409. |
| `GET /api/visualizations/<job_uuid>/` | Owner only: `{id, status, result}`. Completed results contain `{trace, execution_status}`. |

`trace.steps` contains `{line, event, frames, heap, stdout}` snapshots; return/exception events may add `returned` or `exception`. Each frame contains its name, line, and locals. Containers/objects appear in `heap` with type and entries, with `{ref: id}` references from variables. Primitive values carry their Python type. The trace also includes final output, execution status, and a truncation flag.

Visualization jobs share the existing authenticated worker claim/completion protocol with Run/Submit. The oldest available job across both queues is selected first. An account can have one active execution or visualization at a time; new visualizations are limited to 12 per minute. Completion updates only the visualization record. Completed traces older than a day are removed when that user starts another trace. These routes use session auth; they do not expand the staff content-editing API token scopes.

## Limits

- Source: 300 lines / 12 KB. Input: 2 KB. Supporting student Python files: 200 KB.
- Standard sandbox: no network, no host mounts or application credentials, non-root, read-only root filesystem, bounded CPU/memory/process/output limits and an independent container deadline.
- Execution: 2-second student-code timer; 220 snapshots or a 48 KB serialized snapshot budget, whichever comes first. A limit stops execution and keeps the captured prefix.
- Display: 8 latest stack frames, 16 variables per frame, 20 items per collection, bounded nested objects and strings. Large/unsupported values are summarized. Imported module internals are skipped; only the main Python source is traced. Async execution, native libraries, and custom object layouts are not full debugger targets.
- Values are inspected without calling student `repr()` or property hooks. Trace output is still untrusted sandbox output and is never used as a grading verdict.
- A missing worker produces a retryable error after five minutes. Runtime/syntax errors preserve available steps and show error output. Snapshot truncation is not a successful grade or proof that a program terminates.

## Validation

Backend regression tests cover authentication/enrollment, active-exam locks, successful-submission gating, quiz exclusion, source selection, queue ownership/leases, duplicate admission, throttling, and unchanged grades/workspaces. Runner tests cover real CPython line semantics, aliases/cycles, tuples/dictionaries/objects, recursion, inspection hooks, input, exceptions, snapshot bounds, and timeout handling. Real Docker checks exercise every bundled example and confirm sandbox isolation.
