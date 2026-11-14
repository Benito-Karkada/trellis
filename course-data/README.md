# CS 1301 course baseline

`cs1301.tar.gz` contains the complete course baseline: 26 sections, 1,064 parts,
all six programming quizzes, published content plus current staff drafts, native
grading definitions, exercise files, staff sample answers, and referenced images.

It contains no original user accounts, enrollments, submissions, grades, saved
student work, integration credentials, or external-platform connections. Private
solutions and graders retain their staff/grader visibility when loaded.

Run `python3 scripts/setup-local.py` from the repository root. Setup loads this
snapshot into the local database once and connects the local instructor/student
accounts. Running setup again preserves edits and saved work. If you previously
used the miniature demo, its work remains stored, but navigation opens this full
course instead.

The bundle is a native Trellis content snapshot. No source-platform export or
conversion tools are needed. Course edits belong in the web UI and local database.
