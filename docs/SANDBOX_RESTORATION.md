# Sandbox source restoration

`scripts/restore_sandbox_starters.py` imports the public `startercode` exports for
68 lesson sandboxes in Vocareum course 144164. Exact normalized titles match the
cached `var/api-reports/vocareum-all-parts.json` inventory; old edX LTI IDs are not
used. The initial blank-part inventory is in `var/coding-content-repair/current`.

The script preserves the original file bytes, including teaching comments,
multiple examples, supporting text files, and deliberately broken examples.
It never downloads private graders, executes imported code during preparation,
or cleans comments using the graded-exercise instruction converter.

1. Put the Vocareum token in the existing parent `token.txt`.
2. Set `TRELLIS_URL` and a temporary `TRELLIS_API_TOKEN` with `course:read`,
   `content:read`, `content:write`, `content:publish`, `roster:read`, and
   `submissions:read` scopes.
3. Run `python scripts/restore_sandbox_starters.py --audit-workspaces` to privately
   record existing work and download/validate the archives without changing content.
4. Review the generated `var/sandbox-restoration/manifest.json` and source archives.
5. Run `python scripts/restore_sandbox_starters.py --apply --publish` to upload and
   publish through the API. Omit `--publish` to create drafts for review.
6. Revoke the temporary API token.

The importer requires revision preconditions, rejects nonempty existing course
files and unrelated drafts, saves a before snapshot, and verifies every uploaded
file hash. It leaves instructions intact and sets the sandbox entrypoint and zero
points. It does not modify student workspaces, submissions, or grades. If a learner
has already used the old blank `main.py`, that public scratch-file path is retained
so existing code remains accessible when the new revision is opened. A blank
default is retained for that path; learner code is never copied into course files.

Source archives, student-work checks, snapshots, and resumable upload state stay
under ignored `var/sandbox-restoration/`, with restrictive file permissions. Do not
commit these artifacts. Publishing retains old course revisions. If an API
request is interrupted before state is recorded, inspect the current revision
before resuming; unknown drafts are intentionally rejected.

Sandboxes remain Run-only. Syntax/runtime errors in some original examples are
intentional teaching material. Targeted checks:

```
python -m unittest discover -s scripts -p test_restore_sandbox_starters.py
cd backend
../.venv/bin/python manage.py test core.tests.test_execution.ExecutionTests.test_sandbox_accepts_run_but_rejects_both_submit_endpoints
```
