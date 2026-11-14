# Submission review and enrollment removal

Course settings → **Enrollment** lets instructors remove students, TAs, or other instructors. Removal disables that course membership, preserving accounts, submissions, workspaces, grades, and review notes. Re-enrolling the same email restores the membership. Self-removal is blocked. Removed staff tokens stop working because token authentication checks active membership. Canvas synchronization follows the LMS roster and may restore an active Canvas enrollment.

Course settings → **Submission review** provides a searchable, paginated student table and an assignment filter. Staff can inspect metric contributions, exact recorded attempts, latest work, attempt histories, and code observations; save review status/notes; and prepare an editable email draft. No email is sent automatically. Student view cannot access these records.

## Index

The index is a staff review aid on a 0–100 scale, **not an AI probability or a finding of misconduct**. It does not reject submissions, suppress successful feedback, change earned points, or send grade updates. Any grading restrictions should be handled as explicit course/exercise requirements; behavioral flags require human interpretation.

Components have fixed weights; unavailable components contribute no points and are labeled as insufficient data rather than silently rescaled:

- **Timing (35):** a configurable timing formula, averaging `1 / (1 + gap / tau)` across positive gaps between the latest submission timestamps of different parts. Default tau is 180 seconds. Repeat submissions to the same part do not create extra inter-part gaps. Native and coding submission receipts are included.
- **Code observations (35):** the fraction of analyzed coding parts with recorded flags. AST inspection records added imports, configured advanced syntax, and configured call/method names. `math` is allowed by default; imports already supplied by staff anywhere in the workspace are exempt. Supplied syntax/calls and released sample-answer files are exempt. Comments and string contents are never mistaken for executable syntax. An unsuccessful parse is not evidence of clean code.
- **First submission without Run (20):** the fraction of eligible coding parts whose first completed submission passed with no earlier recorded Run. Requires at least three eligible parts. Infrastructure failures and stale results are excluded from eligibility. This measures recorded activity, not whether debugging occurred elsewhere.
- **Focus (10):** `min(recorded away episodes / focus reference, 1)`, default reference 10. Tab-hidden and window-focus-loss events are combined by episode ID, so a blur followed by a hidden event counts once. Focus signals are weak context; they never identify another website/app or explain why focus changed.

Runs, submits, code hashes/revisions, changes following unsuccessful attempts, server timestamps, analysis coverage, and tab-hidden versus window-only counts are available separately. Historical code can be backfilled, but historical focus events cannot. Counts include practice attempts; the existing deadline/credit rules remain unchanged.

## Focus collection

Only enrolled students on course pages are recorded; staff/config/preview are excluded. Telemetry uses `visibilitychange`, window `blur`/`focus`, and `pagehide`; embedded-video iframe focus is ignored where detectable. Only bounded identifiers, state, reason, and an approximate client-reported elapsed duration are accepted. No URLs, window titles, browsing history, screenshots, clipboard contents, or keystrokes are collected. Events are deduplicated and rate-limited. Missing events do not prove uninterrupted focus, and browser telemetry can be blocked or manipulated.

## Settings, API and backfill

Instructors can configure import allowances, syntax and call names, timing baseline, and the focus reference. Settings apply to future code analysis; historical observations retain a policy digest. Saving a staff review captures the current metric snapshot and notes. No weights are inferred from student demographics or accommodations.

`GET /api/v1/courses/{course_id}/reports/submission-review/` requires both `activity:read` and `submissions:read`. Query parameters: `search`, `assignment` (one assignment ID), `membership` (one enrollment ID), and zero-based `page` (50 students per page). Existing execution-job APIs also expose `review_signals` to authorized staff; snapshots remain opt-in via `include_files=true`. Existing visits/events APIs provide server timestamps and focus records.

To analyze old coding attempts for existing records:

```sh
python manage.py backfill_submission_review --course 1 --limit 5000
```

This command never executes student code, changes a workspace, or changes a grade. It skips attempts already analyzed. Supplied-file baselines are cached with a bounded cache.


## Local exports

Use the staff review screen to download a CSV of the current filters. The REST export endpoint is `GET /api/v1/courses/{course_id}/reports/submission-review/export/`, with `?format=csv` for CSV output. Keep exports outside Git and use synthetic data for demonstrations.
