# Architecture

## System boundaries

```text
Canvas
  │ LTI 1.3 launch / NRPS / AGS
  ▼
React web app ──► Django API ──► PostgreSQL
                       │              │
                       │              └─ course, drafts, revisions, attempts, grades
                       ├──────────► private object storage
                       │              └─ student, staff, grader, and source blobs
                       └──────────► Redis / Celery
                                      ├─ Canvas grade passback
                                      ├─ roster synchronization
                                      └─ sandbox job dispatch

Sandbox control plane ──► disposable Python sandbox
                              ├─ student snapshot
                              ├─ hidden grader mounted at runtime
                              ├─ network disabled
                              └─ bounded result returned
```

The Django application never runs submitted Python. The runner controller never receives Canvas credentials or the application database password. Each sandbox receives only the files and short-lived job data required for one attempt.

## Content and publication

An activity owns immutable revisions. A revision has a public content document, private grading rules, and versioned files with one of four visibility levels: student, staff, grader, or quarantine. Draft changes create a new revision. Publishing atomically points the activity at one validated revision. Soft-deleted lessons and activities remain recoverable and cannot be published.

Staff preview and live student delivery call the same `student_projection` function. Preview chooses the newest draft; live delivery chooses the published revision. That function is the security boundary: it returns the public content document and only files marked `student`.

## Migration pipeline

Non-coding edX XML and old Vocareum coding material are separate inputs. XML becomes structured blocks and private grading rules. The original XML, source path, candidate result, and warnings remain attached to an import record. Coding ZIPs are retained with a checksum, inspected for unsafe paths and excessive size, and classified conservatively. Ambiguous files remain quarantined and block publication.

The Kaltura CSV is authoritative for video playback. The importer extracts stable Kaltura identifiers from each iframe and stores those identifiers. It does not copy arbitrary iframe HTML into student content.

## Grade flow

Question grading and assignment aggregation happen in the platform transaction. A committed score creates a unique grade event. `transaction.on_commit` immediately sends the event to Celery. The Canvas AGS worker locks the event, sends the newest score with an increasing timestamp, and records sent/retrying/failed state. Retries use exponential backoff and the UUID idempotency key prevents duplicate logical events.

The AGS adapter is intentionally disabled in this starter until LTI launch validation, OAuth scopes, line-item ownership, and signed deployment configuration are implemented.
