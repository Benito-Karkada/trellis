# Native grader conversion and API uploads

Trellis uses its own grading engine and a private **`grader/tests.json`** per coding part. The local converted artifact is named **`autograder.json`**. This is declarative test data, not a renamed Ferb module. The upload endpoint writes the private file and grading definition together in a new revision.

The original Ferb files remain reference material under `var/ferb-sources`. The converter parses their AST to recover supported input declarations and behavior. It never imports or runs Ferb, Phineas, Utility or Program, and never uploads them. Expected observations come from staff sample answers in isolated Docker containers, or literal output requirements. Converted files and sample validation submissions stay in ignored `var/native-graders` and do not enter Git.

## Current conversion inventory

The remaining 123 imported entries are resolved locally as follows:

- **115 native graders:** 736 fixed checks, with fresh randomized supplements on 101 exercises. Prescribed-output exercises keep fixed checks. Every bundle passed a correct solution and deliberately incorrect controls in isolated Docker containers.
- **7 ungraded activities:** six worked examples and the MARTA analysis workspace, restored as Run-only activities. The full MARTA dataset is preserved.
- **1 retired placeholder:** the empty Tic-Tac-Toe entry was confirmed obsolete and soft-deleted; its history remains available.

The final batch lives in `var/native-graders-complete/manifest.json`. Each `ready` row has a private `part-ID/autograder.json`, validated `correct.py`, negative controls, target IDs, and a content digest. The historical first batch remains in `var/native-graders` and is not overwritten. Native course content stays in ignored `var/`, outside Git.

Live publication progress is saved in `var/native-graders-complete/upload-state.json`. A part is published only after Azure independently accepts its correct control and rejects every incorrect control. Check the fresh API reports in `var/api-reports` for the live inventory; a local `ready` status alone does not mean a bundle is published. Failed checks leave the previous published exercise intact.

Corrected or missing archived sample answers are replaced with validated solutions after the corresponding grader is published. Their revisions and hashes are recorded in `var/api-reports/corrected-sample-answers.json`.

The final live audit confirms **308 active graded coding parts, zero missing graders**, all 115 new bundles published, all seven Run-only activities verified, and 20 corrected sample answers published. See `var/api-reports/native-conversion-completion.json`.

## Create a token

In Trellis, go to **Course settings → API access**. Select:

- `course:read`
- `content:read`
- `content:write`
- `execution:write`
- `content:publish` if publishing

Use **Trellis course ID `1`**. Vocareum source course `144164` is a different ID system. The script checks course, assignment, part and Vocareum source identity before writing. It preserves each exercise's current maximum points and all existing files, and does not write student workspaces or learner grades.

From the platform repository, set the URL and read the token without echoing it (macOS zsh):

```sh
export TRELLIS_URL='https://cs1301-poc-web-v2.agreeablewave-32290e77.southcentralus.azurecontainerapps.io'
read -rs "TRELLIS_API_TOKEN?Paste API token: "
export TRELLIS_API_TOKEN
```

Do not paste the token into chat or commit it. Only the existing `requests` Python dependency is required by the uploader; Docker is required by conversion/local validation.

## Run the uploader

Offline artifact validation, without a token or network access:

```sh
python scripts/upload_native_graders.py var/native-graders-complete/manifest.json --course 1 --check
```

Default read-only plan, using the API token:

```sh
python scripts/upload_native_graders.py var/native-graders-complete/manifest.json --course 1
```

Upload ready definitions as drafts and verify them through Azure's isolated runner:

```sh
caffeinate -i python scripts/upload_native_graders.py var/native-graders-complete/manifest.json --course 1 --apply
```

Upload, test and publish in one pass, or publish the already verified drafts:

```sh
caffeinate -i python scripts/upload_native_graders.py var/native-graders-complete/manifest.json --course 1 --apply --publish
```

`caffeinate -i` keeps the Mac awake while the command runs. On other systems, omit that prefix. No assistant session is required to keep the script running.

Add `--part 89` to limit a run to one Trellis part; repeat the flag for several IDs. Add `--show-skipped` to print every pending conversion reason. Every API write uses a version precondition and idempotency key. The script refuses to overwrite another draft or a published version that changed since preparation. A working existing grader is skipped unless explicitly selected with `--replace-existing`; baseline checks still apply.

Each uploaded draft must pass a correct control and reject every negative control through staff-copy API test runs before it can be published. Failed validation leaves the previous published exercise intact. Private sample source is sent only as a staff test submission, never installed as a student file.

Progress is written atomically to `var/native-graders-complete/upload-state.json`; a per-run summary is written beside it. Rerun the same command with the same state file to resume. Pending jobs are polled again rather than blindly resubmitted. Publishing is a separate permission and requires both `--apply` and `--publish`.

## Prepare another conversion batch

To rerun automatic preparation with Docker Desktop running:

```sh
docker build -t cs1301-student-python:local runner/sandbox
python scripts/prepare_native_graders.py
```

Preparation does not upload anything. The converter deliberately reports unsupported behavior instead of dropping a legacy requirement or turning every answer into a pass. It does not claim arbitrary legacy Python is representable by the current JSON format.

For a manually authored native definition, validate it against a correct solution and meaningful incorrect solutions before making it eligible for upload:

```sh
python scripts/validate_native_grader.py \
  --manifest var/native-graders-complete/manifest.json \
  --part PART_ID \
  --definition /path/to/autograder.json \
  --positive /path/to/correct.py \
  --negative /path/to/wrong.py \
  --entrypoint Exercise.py
```

Use the actual entrypoint from that part's student files. The validator runs only in Docker and updates the selected manifest row/digest after the controls pass. Run it after automatic preparation has finished. If a previously uploaded draft failed, fix/revalidate the bundle and use `--retry-failed` to replace only that batch's own failed draft. Another staff member's newer changes remain protected.

Test controls are necessary but do not prove complete equivalence. Review the exercise's instructions, original checks, edge cases and constraints when authoring a custom conversion. Class instances, unrecognized fixture generation, special comparisons and source requirements may need explicit native conversion before a faithful conversion can be uploaded.

## Fresh cases and final problem set

Input-based ready bundles now contain `random_cases` and a private `reference.py`. Each Submit supplements the fixed cases with freshly generated inputs. Fixed-output and variable-type exercises keep their deterministic requirements. The converter refuses input-based problems whose random domains it cannot describe safely; no constraint is silently discarded.

Final problems 1–6 and 10 have a separate independently authored conversion under `var/native-final-graders/manifest.json`. Use `python scripts/download_final_problems.py` to re-download the matched archives from the saved course discovery, then run `python scripts/prepare_final_graders.py --references var/native-final-references` to rebuild and validate those bundles from the downloaded final archives. Their references and samples are private course content in ignored `var/`, not legacy grading modules. Each definition has six fresh cases as well as fixed boundary cases. File fixtures and Nation object inputs use the native data contract. The replacement follows the written exercise requirements, including all 26 first/last-name initials and multiple-ace Blackjack totals.

Final problems 7–9 retain their existing native answer grading. `combine_analysis_exercises` combines the original rich instructions, dataset, ungraded sandbox, and answer blocks under the existing assessment IDs. Source presentation entries are soft-deleted, and prior workspace/history records remain available. Only the answer submission earns points; the coding workspace has Run only. Resetting a solved native exercise clears practice responses without changing its earned score and allows immediate retries without a cooldown.


Native conversion extensions
---------------------------

`prepare_native_graders_wave2.py` reads legacy test *data* through a bounded AST interpreter. It never imports Ferb, Utility, Program, or Phineas. Custom plans live in `native_special_plans.py`; corrected staff references and generated exercise content stay under ignored `var/` directories.

Native cases now support public `trace` steps (construct/read/call/set/presence/file), `function_file`, `function_stdout`, and runtime `recursion` checks. Source requirements use Python tokens/AST rather than raw substring matches. A required comment cannot be satisfied by a string literal. Protected input declarations are excluded from forbidden-literal checks.

Randomized tests use bounded generators or a correlated bank of generated public inputs. Expected values always stay with the trusted controller and come from a separate reference container. Linked-list/tree fixtures use flat object graphs, preserving shared references and cycles without deeply nested JSON. A case may specify an ISO `clock` for reproducible date/time exercises.

Use a new output directory for a new conversion wave. The upload tool checks source identity, current published revision, artifact hashes, a correct solution, and incorrect controls before publishing. Failed controls remain drafts. Never replace a working native grader without explicitly reviewing the change.

Trace `exception` steps observe the exception type from an attempted call. The expected type remains in the private case definition. This supports constructor-arity exercises without failing the entire grading job.

`module_outcome` observes intentionally uncaught exceptions without comparing traceback line numbers. Public getter fixtures let function-only exercises receive supplied objects without requiring an optional student class definition. `python` comparison preserves the old string trimming and four-decimal float behavior.
