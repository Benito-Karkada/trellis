# Coding migration: part 5591043

Implementation decision: the replacement grader is first-party CourseSpace code,
not a port of the helpers described below. See [First-party grading](FIRST_PARTY_GRADING.md).
This document retains the source behavior as a migration reference.

Reference inputs: the user's `downloaded_part_5591043` and attached Phineas_v2.py,
Program.py, Utility.py. Preserved attachment originals are in ignored
`var/legacy-course/`. These are course content, not platform source code.
The read-only API exporter attempted course 144164 / assignment 5591000 /
part 5591043. Retrying with the same token file through the requests HTTP client
succeeded: startercode (3 files), scripts (4 files), and private (11 files) were
downloaded as ZIPs, safely extracted, and checksummed. The docs export timed out;
the course folder export returned no usable transaction. Shared course files are
therefore sourced from the user's attachments. Fresh archives and manifests live
in ignored var/vocareum-part-5591043-requests. The exporter records statuses without
tokens or signed URLs.

## File ownership and sharing

| Source | Destination and behavior |
|---|---|
| course/Utility.py, Program.py, Phineas_v2.py | Private shared course library, edited in the staff UI. Publishing a library revision affects all subsequent jobs for activities using that course library. |
| private/Ferb.py | Private per-activity tests and get_results() implementation. |
| private/sample_answer_1.py | Private solution released only after a successful submission. |
| private/AutoGrade.py and supporting files | Retain privately; inspect references before treating them as active grading code. |
| scripts/*.sh | Private lifecycle configuration, retained as source; never execute arbitrary imported hooks on the app server. |
| startercode/DaysBetweenDates.py | Seed for each student's independently saved workspace. |
| startercode/full_results.txt | Student-visible feedback placeholder overwritten after a grading run. |
| startercode/sample_answer_1.py | Student-visible placeholder; distinct from the identically named private solution. |

The downloaded placeholder files contain explanatory text; they are not empty.
build.sh is empty, making it a no-op. run.sh runs the selected Python file without
grading. grade.sh invokes Phineas_v2.py with two arguments and sets LIB/ASNLIB.
submit.sh invokes the older Phineas.py with three arguments and relies on LIB
being set elsewhere. Preserve these differences in the migration review.

## Restore workspace feedback

1. Snapshot student files plus the published activity and current published course
   library revision. Record all hashes on the attempt so old results are reproducible.
2. Run the grading job in the isolated execution service. The shared library and
   private tests are never part of a student API response.
3. Validate the trusted grader result: preview, full_output, points, show_samples,
   and optional helpful feedback. Persist the attempt result first.
4. Atomically replace the student's full_results.txt with full output and feedback
   after run/check/submit when grading actually occurs. Plain execution alone must
   not erase prior grading feedback. Include attempt sequence guards so delayed
   results cannot overwrite feedback from a newer request.
5. On successful submit only, release configured private sample_answer files into
   that student's workspace, replacing placeholders. Do not overwrite their solution
   file. A failed later attempt leaves previously earned sample access intact.
6. Notify the browser to refresh the file tree/open feedback tab. A summary may also
   appear in the grading panel, but it is not the only destination.

`core/grading_artifacts.py` retains a tested legacy result-conversion reference.
The active first-party contract is `runner/grading/engine.py`. Persistence,
concurrency guards, sample copying and browser notifications remain to implement.
The adapter intentionally does not execute legacy course code.

## Observed compatibility issues

- Phineas_v2 already writes full_results.txt and tries VOC::WORKAREA using argv[3],
  but grade.sh supplies only two arguments. Its caught exception makes copy-back
  failure non-fatal. The new platform will own artifact persistence directly.
- Both supplied Phineas variants use points // 5. Utility's normal result helper
  returns either 0 or 5. Preserve all-or-nothing scoring by default; partial credit
  must be an explicit authoring choice, not an accidental arithmetic change.
- Program uses imp.new_module, obsolete bytecode instructions CALL_FUNCTION and
  SETUP_LOOP, and an old CodeType constructor. It is not Python 3.12 compatible.
  Port module creation, AST target lookup and recursion counting with regression
  fixtures; do not silently disable pedagogical code checks.
- Utility requires pycodestyle. Its legacy stdout manipulation and signal timeouts
  are not security isolation; runner limits must be enforced outside student code.
- Ferb's downloaded get_results calls check_required_code without importing it or
  qualifying it with Util. Verify this against the active course before changing it.
- Keeping student code and hidden tests in the same Python interpreter exposes
  grading internals to introspection. A production runner requires a separate
  trusted grading supervisor and constrained student process, beyond simply moving
  this legacy exec() into a Docker container.
