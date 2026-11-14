# Trellis Staff REST API v1

Base URL: `https://YOUR-TRELLIS-HOST/api/v1/`.

The deployed reference is **Course settings → API access → Open API documentation** (`/api/v1/docs/`). Download the OpenAPI 3.1 contract at `/api/v1/openapi.json`. Both accept an existing staff session or a bearer token for reading documentation; data endpoints require a bearer token.

## Access

Create a named token in **Course settings → API access**, select scopes and expiry, and copy the token once. Only its SHA-256 hash is stored. It belongs to the selected course and its owner's active staff enrollment. Revocation, course drops, account deactivation and role changes take effect on subsequent requests. Instructors can revoke any token in their course; TAs manage their own. Roster writes and audit access are instructor-only.

Store `TRELLIS_URL` and `TRELLIS_API_TOKEN` in your terminal environment or secret store. Do not put a token in Git, a browser URL, a shared document, or a course file. No CSRF token is needed for bearer API requests. Browser token creation/revocation retains normal session/CSRF protection.

- `course:read`: course ID/name.
- `content:read`: assignments, parts, version history and **private staff/grader files and answer keys**.
- `content:write`: create/edit draft content, files and native graders; soft-delete content.
- `content:publish`: publish a draft or restore a historical part revision.
- `roster:read` / `roster:write`: list / add, drop, restore or edit enrollments and accommodations.
- `grades:read`: recorded course/assignment grades.
- `submissions:read`: submitted answers, coding jobs and student workspaces.
- `activity:read`: assignment visits and learning events.
- `execution:write` with `content:read`: queue/poll staff-copy grader tests in the isolated executor.
- `audit:read`: API change/access logs without secrets or full request bodies.

## IDs and content structure

`course_id` is a Course ID. `assignment_id` is the existing lesson/section container ID, including programming quizzes. `part_id` is an existing activity ID. `enrollment_id` is a course-membership ID; it is different from the platform `user_id`, GTID, SIS ID and Canvas user ID. Assignment and part IDs remain stable through edits, file changes and publishing; revision IDs change.

For the current course, a chapter/lesson section contains its content and problem-set parts. An assignment due date applies to its graded parts, with existing individual deadline accommodations taking precedence. The API does not silently invent new Canvas assignment mappings or infer a GTID from a Canvas numeric ID.

Content is the same native structured `{ "version": 1, "blocks": [...] }` representation used by the web editor. Do not flatten non-coding prompts, code blocks and answer choices into a README. `PATCH /parts/{id}/` replaces `content` when supplied, shallow-merges `grading`, and upserts any supplied `files`; unmentioned files remain intact.

## Editing safely

1. `GET /parts/{id}/` returns the latest draft and `ETag: "REVISION_ID"`.
2. Send `If-Match: "REVISION_ID"` or JSON `base_revision_id` with each part/file/grader change.
3. The response contains the new revision ID. Missing preconditions return 428; stale versions return 412 without overwriting anything.
4. Content, grading and file changes remain drafts until `POST /parts/{id}/publish/`. Publishing requires `content:publish`, even if your token has write access.
5. To restore an earlier revision, fetch the latest draft ID for `If-Match` and send the earlier `revision_id` to the publish endpoint.

Assignment updates and part titles, ordering and metadata apply immediately; part content, grading and files are versioned. A newly created assignment defaults to staff visibility; set `visibility: "student"` explicitly when ready. Deleting assignments/parts is a soft delete and preserves historical submissions. Dropping a student sets the course enrollment inactive and preserves accounts, code and grades.

New files require explicit `visibility` (`student`, `staff`, `grader`) and exactly one of `text` or `content_base64`, up to 1 MB. Existing-file PUT may omit visibility to preserve it. Grader/solution paths and known legacy grader filenames cannot be student-visible. Private blob URLs and app secrets are never exposed by file endpoints. Current enrolled students receive newly published public files on next load; edited files are preserved, and untouched files pick up the new baseline. Reset workspace restores the published baseline exactly.

Every write accepts an optional `Idempotency-Key` up to 100 characters. Reusing the same token/key/method/path/body replays its response. A different request with the same key returns 409. Use a fresh key for each distinct edit.

## CLI examples

Use the supplied client; it follows pagination and reads credentials from environment variables:

```sh
python scripts/api_client.py missing-graders --course 1 --output var/api-reports/missing-graders.csv
python scripts/api_client.py get-part 355
python scripts/api_client.py put-file 355 main.py ./main.py --visibility student
python scripts/api_client.py put-file 355 grader/helper.py ./helper.py --visibility grader
python scripts/api_client.py put-grader 355 ./tests.json --entrypoint main.py --mark-reviewed
python scripts/api_client.py publish 355
python scripts/api_client.py grades --course 1 --assignment-ids 10,11 --output var/api-reports/grades.json
python scripts/api_client.py submissions --course 1 --enrollment-ids 9 --output var/api-reports/submissions.json
python scripts/api_client.py events --course 1 --output var/api-reports/events.json
python scripts/api_client.py enroll --course 1 --email person@gatech.edu --name "Student Name"
python scripts/api_client.py drop 123
```

IDs above are examples: look up actual IDs instead of assuming them. Enrollment creation is roster-only; it never returns/changes a password. Use the existing instructor Enrollment login controls when a local login is needed.

## Missing-grader / Ferb migration workflow

`GET /courses/{course_id}/reports/missing-graders/` reports published coding parts missing/invalid native definitions, entrypoint problems, pending coding imports, or grader review requirements. Sandboxes are excluded. `include_ready=true` also lists working graders. Rows include stable part/assignment IDs, a Vocareum part reference when known, reasons, archived grader/staff filenames, and whether a native grader file exists. A working definition in the database counts as a grader even if an old import has no physical `grader/tests.json`; archived Ferb alone never counts.

1. Export this report and match the relevant old archive/part. Use [Ferb source collection](FERB_SOURCES.md) to collect matching sources from existing archives or fresh private ZIP exports.
2. Read Ferb/test/sample sources as migration material. Do not execute legacy graders on the app server.
3. Produce a first-party native JSON definition for that exercise. Upload using `PUT /parts/{id}/grader/`; it creates both private `grader/tests.json` and the corresponding `Revision.grading.definition` in one draft.
4. The entrypoint must already be a student-visible Python file. Optionally set `maximum_points`; use `mark_reviewed: true` only after reviewing the conversion.
5. Test with `POST /parts/{id}/test-runs/`, passing the latest draft precondition, `operation: "submit"`, and optionally a full public-file snapshot with your sample implementation. Poll `/test-runs/{job_id}/`. Tests use the isolated executor and do not modify a learner's workspace, submission history, or grade.
6. Publish only after verification. Rerun the report to confirm the published part is ready.

Minimal definition:

```json
{
  "version": 1,
  "scoring": "all_or_nothing",
  "timeout_seconds": 2,
  "cases": [
    {"id": "sum", "label": "Sum", "action": "variable", "target": "answer", "expected": 10}
  ]
}
```

Supported case actions are `variable`, `variable_type`, `function`, `stdout`, `file`, and `scenario`. Inputs, variable overrides, arguments, tolerances, source requirements and weighted scoring are described in the OpenAPI schema. Putting arbitrary Python into a private course file stores it; it does **not** make Django run it or replace the native execution protocol.

## Grades, submissions and activity

List responses use `{count, limit, offset, next, previous, results}`. Default page size 100, maximum 200. Follow relative `next` links. CSV-style ID filters accept up to 200 IDs: `assignment_ids=10,11`, `enrollment_ids=9`, and, on relevant endpoints, `part_ids=355`. Scope and course boundaries are checked on every page.

- `/courses/{id}/grades/`: recorded scores, not a later practice attempt's score. Filter the course or selected assignments/students. Inactive students are excluded unless `include_inactive=true`.
- `/courses/{id}/submissions/`: native responses and completed coding submissions. `submitted_at` is receipt time; `record_created_at` is when the submission row was persisted. `graded_at` is separate.
- `/courses/{id}/execution-jobs/`: also includes Run requests and pending/failed coding Submit jobs. `include_files=true` includes the student snapshot, never runner credentials or leases.
- `/enrollments/{id}/workspaces/{part_id}/`: latest saved student files only, without resetting or changing their work.
- `/courses/{id}/visits/`: exact first/last assignment-open timestamps and visit counts, recorded from deployment onward.
- `/courses/{id}/events/`: assignment/part opens, native submissions and practice resets (`native_reset`), coding Run/Submit requests, completed coding submissions, quiz starts and quiz submission.

Timestamp filters `since` and `until` require timezone-aware ISO 8601 values. All response timestamps are UTC. Historical coding receipt timestamps are recovered from their known execution-job creation time. Unknown historical assignment first-open times remain null; `ActivityProgress.updated_at` is not substituted for them. Staff previews and API staff-copy test runs do not pollute learner event/visit histories.

## Error contract

Errors are JSON objects with `error.code`, `error.message`, optional `error.details`, and `request_id`. The response also includes `X-Request-ID`. Typical statuses: 400 invalid input, 401 missing/expired token, 403 missing scope/current role, 404 inaccessible resource, 409 conflict, 412 stale revision, 413 oversized content, 415 wrong media type, 428 missing revision precondition.

The legacy browser `/api/...` endpoints remain in place for the UI. Automation should use `/api/v1/...` as its supported contract.

## Randomized coding tests

`PUT /parts/{id}/grader/` accepts an optional `reference_source` alongside a definition with `random_cases`. The endpoint stores it at the definition's `oracle_path` with grader visibility. The execution controller receives it through the authenticated worker channel; the student projection and student execution container never receive it. Reference failures are service errors and do not record a zero grade.

```json
{
  "definition": {
    "version": 1,
    "cases": [{"id":"example","label":"Example","action":"function","target":"double","arguments":[3],"expected":6}],
    "random_cases": {
      "count": 3,
      "oracle_path": "grader/reference.py",
      "templates": [{"action":"function","target":"double","arguments":[{"kind":"integer","min":-1000,"max":1000}]}]
    }
  },
  "reference_source": "def double(value):\n    return value + value\n"
}
```

Each new submission gets a new input seed. Retrying delivery of that same job reproduces its inputs. Fixed cases remain present; randomized cases supplement them. The reference uses the published baseline, not the student's modified files, and runs separately for each generated case. Both runs use the same public inputs. Public feedback reports inputs, expected values and actual values, including fixture-file contents.

Supported generator kinds are `literal`, `integer`, `float`, `choice`, `string`, `list`, `sequence`, `record`, and `join`. A `join` descriptor has `separator` and an `items` generator that produces a list of strings. Numeric ranges, collection lengths, nesting, total expansion, case counts and execution time are bounded. Random templates may include `files`, a map of relative public fixture paths to text-producing generators. Fixed cases use literal text in `files`. Do not use grader, solution, absolute or parent paths.

For object exercises, `argument_constructors: {"0":"Nation"}` converts argument zero from a list of attribute records to instances of the sandbox's `Nation` class. Constructors execute inside that same isolated container. They never execute on Django or the worker host.

The CLI supports `put-grader ... --reference ./reference.py`. The batch uploader includes the reference in its validated bundle digest and uploads it with the grader in one versioned write.


Additional native grading actions: `function_stdout` captures only the requested function's printed output; `function_file` invokes a function and reads its first filename argument; `trace` collects public declarative object/file observations; `recursion` verifies recursive calls at runtime. Optional `comparison` supports exact, contains, numeric_text, string, or whitespace normalization. Optional `clock` freezes only the disposable test container's date/time. These fields do not execute course Python on the web server.

## Submission review

`GET /api/v1/courses/{course_id}/reports/submission-review/` requires `activity:read` and `submissions:read`. It accepts `search`, `assignment`, `membership`, and zero-based `page` (50 rows per page). The response includes the staff review index, component contributions, gaps, attempts/revisions, focus counts, analysis coverage, and saved review status/notes. These metrics do not alter grades. See [Submission review](SUBMISSION_REVIEW.md).

Private Excel worksheet export: `GET /api/v1/courses/{course_id}/reports/submission-review/export/` requires `roster:read`, `activity:read` and `submissions:read`. JSON returns all matching active students, text GTIDs, formula maps, contributions and coverage; `?format=csv` downloads Excel-compatible CSV. This endpoint sends nothing externally. See `SUBMISSION_REVIEW.md` for the separately authorized Microsoft sync script.

## Renaming parts

A part's ID stays the same when its title changes. For a single part, the existing
`PATCH /parts/{part_id}/` endpoint accepts `title` alongside the usual revision
precondition. For title-only changes across one or more parts, use:

```http
PATCH /api/v1/courses/1/parts/titles/
Authorization: Bearer <staff-token>
Content-Type: application/json
Idempotency-Key: rename-parts-2026-11-08
```

```json
{
  "updates": [
    {"id": 123, "expected_title": "Old title", "title": "Updated title"},
    {"id": 456, "expected_title": "Another title", "title": "Updated second title"}
  ]
}
```

Requires `content:write`. Read the current titles with the assignment/part list or
`GET /parts/{part_id}/` first. Up to 500 unique part IDs are accepted. Every
`expected_title` must match the currently stored title; a mismatch returns 409 and
**none** of the changes are applied. Missing/cross-course/deleted parts are rejected.
Titles must contain 1–200 characters after trimming. The response returns `updated`
and `results` with each part's `id`, `assignment_id`, and `title`.

Title-only updates take effect immediately and do not create/publish content
revisions, alter files, or modify student work, submissions, or grades. Use an
idempotency key for retryable requests. This endpoint is listed in the built-in
API documentation and OpenAPI schema.

## Course structure drafts in the UI

**Edit course structure** now stages title edits, additions, copies, deletions, and
reordering. **Undo** restores the previous draft action, including deleted items;
continuous typing in one title counts as one undoable action. **Discard changes**
reloads the saved structure. **Save changes** applies the whole draft atomically
and resets the Undo history. Save is the commit point; Undo applies to unsaved
changes. Deletions remain soft deletes and never remove student records.

The staff session endpoints are `GET /api/structure/draft/` and
`POST /api/structure/save/`. The latter requires the snapshot's `base_version` plus
an ordered `operations` list. A concurrent outline/content change returns 409 with
the unsaved draft retained in the browser. Discard/reload and reapply the desired
changes after checking the other author's edits. These are cookie/CSRF-protected
UI endpoints; scripts should use the bearer-token REST endpoints above.
