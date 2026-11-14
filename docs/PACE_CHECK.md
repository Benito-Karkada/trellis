# Lesson pace reminder

`POST /api/assignments/<id>/pace/` uses the current authenticated student and active course enrollment. Its only response field is `too_fast`; it never returns timings to the student. Staff and staff-only lessons return false. The frontend also excludes staff preview/config modes.

Only completed, published, graded exercises count. Readings, videos, sandboxes, zero-point parts, deleted parts, unpublished parts and items awaiting grading review are excluded. A native exercise contributes its question count; a coding exercise contributes one question. Partial completion of a multi-question part does not count until its existing progress record is completed.

The default is 60 seconds per question, with at least two questions required. A part can override this with metadata `min_seconds`, a finite number from 0 to 86400; invalid values fall back to the default. Zero disables the time requirement for that part. Working time sums gaps between the first assignment open and coursework actions (excluding focus telemetry), capped at ten minutes per gap. It does not add wall-clock time after the latest action.

The first flag records one `pace_flagged` event containing active seconds, required seconds and question count. A membership row lock prevents concurrent checks from recording duplicate first flags in PostgreSQL. Staff can inspect the event using the existing authorized events API. This is a pace reminder, not evidence of AI use, and it never changes grades or permissions.

The dismissible banner is scoped to the current lesson; a response from a previous lesson cannot display on a new lesson. Dismissals are retained per lesson while the lesson interface remains mounted. Both light and dark themes are supported.

Verification: full Django suite (158 tests, including submission-review integration), frontend production build, and browser checks using synthetic local accounts for appearance, dismissal, lesson changes and staff exclusion. No production student data was used for the browser fixture.
