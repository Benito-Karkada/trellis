# Trellis grading

The grading engine in `runner/grading` uses versioned JSON test definitions and disposable local Docker containers.

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

Authenticated queued Run/Submit jobs, result validation, workspace feedback/sample updates, staff-copy test runs, and API grader editing are implemented. See [the staff REST API](REST_API.md) for editing and testing JSON grading definitions.


### Coding instructions and local examples

Edit exercise instructions and Python files through Config. Preserve useful example calls and expected-output comments. Changes create a new revision; saved student workspaces remain separate. Publish reviewed changes explicitly.
