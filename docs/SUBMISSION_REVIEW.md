# Submission review and enrollment removal

Course settings → **Enrollment** lets instructors remove students, TAs, or other instructors. Removal disables that course membership, preserving accounts, submissions, workspaces, grades, and review notes. Re-enrolling the same email restores the membership. Self-removal is blocked. Removed staff tokens stop working because token authentication checks active membership. Canvas synchronization follows the LMS roster and may restore an active Canvas enrollment.

Course settings → **Submission review** provides a searchable, paginated student table and an assignment filter. Staff can inspect metric contributions, exact recorded attempts, latest work, attempt histories, and code observations; save review status/notes; and prepare an editable email draft. No email is sent automatically. Student view cannot access these records.

## Index

The index is a staff review aid on a 0–100 scale, **not an AI probability or a finding of misconduct**. It does not reject submissions, suppress successful feedback, change earned points, or send grade updates. Any grading restrictions should be handled as explicit course/exercise requirements; behavioral flags require human interpretation.

Components have fixed weights; unavailable components contribute no points and are labeled as insufficient data rather than silently rescaled:

- **Timing (35):** the original `sus.py` formula, averaging `1 / (1 + gap / tau)` across positive gaps between the latest submission timestamps of different parts. Default tau is 180 seconds. Repeat submissions to the same part do not create extra inter-part gaps. Native and coding submission receipts are included.
- **Code observations (35):** the fraction of analyzed coding parts with recorded flags. AST inspection records added imports, configured advanced syntax, and configured call/method names. `math` is allowed by default; imports already supplied by staff anywhere in the workspace are exempt. Supplied syntax/calls and released sample-answer files are exempt. Comments and string contents are never mistaken for executable syntax. An unsuccessful parse is not evidence of clean code.
- **First submission without Run (20):** the fraction of eligible coding parts whose first completed submission passed with no earlier recorded Run. Requires at least three eligible parts. Infrastructure failures and stale results are excluded from eligibility. This measures recorded activity, not whether debugging occurred elsewhere.
- **Focus (10):** `min(recorded away episodes / focus reference, 1)`, default reference 10. Tab-hidden and window-focus-loss events are combined by episode ID, so a blur followed by a hidden event counts once. Focus signals are weak context; they never identify another website/app or explain why focus changed.

Runs, submits, code hashes/revisions, changes following unsuccessful attempts, server timestamps, analysis coverage, and tab-hidden versus window-only counts are available separately. Historical code can be backfilled, but historical focus events cannot. Counts include practice attempts; the existing deadline/credit rules remain unchanged.

## Focus collection

Only enrolled students on course pages are recorded; staff/config/preview are excluded. Telemetry uses `visibilitychange`, window `blur`/`focus`, and `pagehide`; embedded-video iframe focus is ignored where detectable. Only bounded identifiers, state, reason, and an approximate client-reported elapsed duration are accepted. No URLs, window titles, browsing history, screenshots, clipboard contents, or keystrokes are collected. Events are deduplicated and rate-limited. Missing events do not prove uninterrupted focus, and browser telemetry can be blocked or manipulated.

## Settings, API and backfill

Instructors can configure import allowances, syntax and call names, timing baseline, and the focus reference. Settings apply to future code analysis; historical observations retain a policy digest. Saving a staff review captures the current metric snapshot and notes. No weights are inferred from student demographics or accommodations.

`GET /api/v1/courses/{course_id}/reports/submission-review/` requires both `activity:read` and `submissions:read`. Query parameters: `search`, `assignment` (one assignment ID), `membership` (one enrollment ID), and zero-based `page` (50 students per page). Existing execution-job APIs also expose `review_signals` to authorized staff; snapshots remain opt-in via `include_files=true`. Existing visits/events APIs provide server timestamps and focus records.

To analyze old coding attempts after migration:

```sh
python manage.py backfill_submission_review --course 1 --limit 5000
```

This command never executes student code, changes a workspace, or changes a grade. It skips attempts already analyzed. Supplied-file baselines are cached with a bounded cache.

## Instruction cleanup

`scripts/clean_coding_instructions.py` operates on a private API snapshot under `var/workspace-instruction-cleanup`. A plan is read-only by default; `--apply` publishes guarded revisions through the API. It checks executable AST/token equivalence (including intentionally broken-code exercises), retains grader-required comments, preserves every original prompt, and uses native paragraphs/preformatted blocks. Student workspaces and private graders are never rewritten.

The completed batch updated 314 workspaces; 72 already needed no changes. This includes the three combined final-problem sandboxes. All 386 original prompts were verified intact, with no publishing errors. Files and state remain under ignored `var/`.


## Submission history and Excel review worksheet

In **Gradebook**, click a student, choose an exercise and use **Submission history**.
Numbered Submit attempts are chronological, including failed/pending coding jobs;
Run attempts and staff previews are excluded. Native responses and coding source
snapshots retain their original revision. Staff can run/submit a review copy;
this never changes the student's workspace or recorded grade. Historical native
scores are shown only when recorded in the event log, rather than recalculated.

**Settings → Submission review → Export review metrics (CSV)** exports all
active students, optionally limited to the selected assignment. CSV imports should
set Enrollment ID and GTID columns to **Text** to preserve leading zeroes.
Unknown metrics and scores remain blank. GTID is taken only from the roster's
`external_ids.gtid`; Canvas user IDs and email usernames are not substituted.
The export includes four metric values/contributions, ranked reasons,
data coverage and as-of UTC. It omits source code, email addresses and staff notes.

For a repeatable refresh of the linked Microsoft workbook:

```sh
export TRELLIS_URL=https://your-trellis-host
# Set TRELLIS_API_TOKEN and MS_GRAPH_ACCESS_TOKEN securely in your shell.
python scripts/sync_review_workbook.py --course 1          # inspect/dry-run
python scripts/sync_review_workbook.py --course 1 --apply  # update owned sheet
```

The Trellis token needs **roster:read**, **submissions:read**, **activity:read**.
The Microsoft token needs delegated work/school **Files.ReadWrite** and access to
that workbook. Microsoft Graph Excel does not support application-only permission
for these operations. Do not put either token in Git or chat. No recurring task or
email is created by this script.

The script manages `Trellis Review 1` only. Header/ownership-marker mismatches abort;
other worksheets remain intact. Keep manual notes in a separate worksheet keyed by
Enrollment ID or GTID. Data is a staff review aid, not evidence of AI use by itself.
The score and contributions are actual Excel formulas; all unknown inputs produce
a blank score. After writing, scores and identifiers are read back and verified.
There is no separate Formula column. Each score cell directly calculates
`ROUND(SUMPRODUCT(E2:H2,$AJ$2:$AM$2),1)` (blank if all four metrics are unknown).
The labeled weights in AJ1:AM2 are timing 35, code 35, first-pass 20, focus 10.
Contribution cells also reference those weights. Sync restores the platform weights;
manual workbook edits do not change Trellis policy. The owned schema-1 worksheet is
migrated in place on the next sync. CSV contains static calculated values; use the
sync script for live Excel formulas, not a CSV import. No Microsoft connection is
configured by downloading the CSV.

API: `GET /api/v1/courses/1/reports/submission-review/export/` (JSON by default,
`?format=csv` for CSV), with the three scopes above. Filters: `assignment`,
`membership`, `search`. Page is ignored because export includes every matching row.

Microsoft API references:
- https://learn.microsoft.com/en-us/graph/api/workbook-createsession?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/range-update?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/shares-get?view=graph-rest-1.0
