# Trellis grading

The platform uses a new implementation under runner/grading. It does not import,
copy, or execute Phineas, Program, Utility, Ferb, or Vocareum grading packages.
Legacy files remain migration references. Their authorship and licensing have not
been established; this project makes no ownership claim about them.

## Responsibilities

| Need | New implementation |
| --- | --- |
| Run/check/submit orchestration | Execution host and application job lifecycle; the local CLI currently supports check and submit. |
| Per-question tests | Private versioned JSON definitions, loaded without executing Python configuration. |
| Test variables, functions, and printed output | Fresh Docker container for each case; trusted supervisor compares observations against expected values. |
| Required/forbidden constructs | Python AST checks, including required function names; comments cannot satisfy syntax requirements. |
| Feedback | Public test comparisons show inputs, expected values and types, observed results, and errors. Tests are not anonymized as private. |
| Scoring | Explicit all-or-nothing default; optional weighted cases. Syntax or required-code failures prevent full success. |
| Workspace feedback | Result includes a full_results.txt replacement payload. |
| Sample answers | Release decision is true only on a fully successful submit; private solution contents never enter the execution container. |
| Coursewide helpers | Reusable platform code in this package. Course-specific shared rules will remain versioned authoring data. |

Plain Run is distinct from grading and must not erase grading feedback or release
solutions. Infrastructure failures are retriable errors, not zero grades.

`variable_type` cases check an exact built-in type without constraining the
variable's value. For example, `action: "variable_type"`, `target: "count"`,
`expected: "int"` accepts any integer, but rejects booleans and custom classes
named `int`. Missing variables receive explicit feedback. Stdout comparisons
remain exact unless a case explicitly sets `strip_output: true`, which strips
only leading/trailing whitespace and preserves spacing within the output.

The archive preparer recognizes literal `expected_variables` type declarations
and a literal expected output without importing or running the legacy grader.
Unrecognized patterns remain flagged for review rather than receiving fake tests.
`scripts/repair_type_exercise.py` can publish a reviewed conversion through the
same staff authoring APIs as the browser, preserving the old revision and rubric.

## Local verification

From the platform repository:

```sh
docker build -t cs1301-student-python:local runner/sandbox
cd runner
RUN_DOCKER_TESTS=1 python3 -m unittest discover -s tests -v
python3 -m grading --source /path/to/student.py --definition /path/to/private-definition.json --operation check
```

A minimal private definition has this structure (illustrative data only):

```json
{
  "version": 1,
  "scoring": "all_or_nothing",
  "cases": [
    {
      "id": "double-positive",
      "label": "Positive input",
      "action": "function",
      "target": "double",
      "arguments": [4],
      "expected": 8,
      "public": true
    }
  ],
  "requirements": [
    {
      "id": "function",
      "kind": "require_function",
      "target": "double",
      "message": "Define a function named double."
    }
  ]
}
```

Actual course definitions belong in private database/object storage, edited in
Config, rather than committed as platform source. The JSON loader/CLI provides a
testable contract before that authoring form is connected.

The downloaded DaysBetweenDates starter was verified with new correct and
incorrect solution snippets across seeds 0, 17, and 31. The correct solution
received full credit and a sample-release decision; the incorrect solution
received zero and no release. Source files were read without modification, and
no legacy grader/helper modules were loaded.

## Isolation and remaining work

The local Docker adapter resolves an immutable image ID and creates a new
non-root container per case. It supplies no host mounts, Docker socket, private
graders, sample answers, or app credentials. Networking is disabled; memory, CPU,
process count, filesystem and output are bounded. The supervisor enforces a wall
deadline of the configured time plus five seconds for container startup, then
removes the container. Result values are bounded before comparison.

The executor process is untrusted and can observe only its source and public
inputs. Its output cannot directly award points or release samples. Docker is a
local development execution boundary, not a claim of production multi-tenant
security. Deploy the controller separately from the app server; never mount a
Docker socket into the web or Celery containers.

Authenticated queued Run/Submit jobs, result validation, workspace feedback/sample updates, staff-copy test runs, and API grader editing are implemented. See [native grader uploads](NATIVE_GRADER_UPLOADS.md) for conversion status, local validation and the resumable API upload/test/publish workflow. Legacy class/file/source-check patterns outside the native format remain explicit review items; they are not silently removed.


### Coding instructions and public local tests

Coding prompts are normalized by `core.coding_content.clean_prompt`: repeated
prose and generic “add your code here” placeholders are removed, while code,
inline markup, media and mathematical operators are preserved. Long prose and
flattened lists use native paragraph/list blocks. Normalization is idempotent.

`clean_coding_instructions.clean_source` preserves the original local-test section,
including input setup, print calls, expected-output comments and deliberately
commented-out print tests. Never strip all full-line comments indiscriminately.
Required grader comments remain intact, and executable AST/token equivalence is
checked before any file can be published.

The repair script is `scripts/repair_coding_content.py`; its default audit folder
is ignored `var/coding-content-repair/`, with original sources in ignored
`var/workspace-instruction-cleanup/`. Plans publish through
`scripts/clean_coding_instructions.py --root var/coding-content-repair --apply`
using normal API revision/hash guards. Unpublished drafts and changed executable
defaults are preserved for review. Graders, grades, submissions and saved student
workspaces are not modified. Fresh/reset workspaces use repaired defaults;
existing saved work stays intact.
