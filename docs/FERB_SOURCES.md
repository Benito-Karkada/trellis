# Ferb source collection

The Trellis missing-grader report uses internal `part_id` and `assignment_id` values. Its `vocareum_part_id` refers to the source coding part; the Vocareum assignment ID must come from the source archive manifest or the complete course inventory. Course `144164` is **D. Joyner Sandbox**.

Run from the platform repository:

```sh
python scripts/pull_ferb.py var/api-reports/missing-native-graders.csv --course 144164
```

The script prefers the existing verified archives under `var/vocareum-coding-archives`. It defaults to `var/ferb-sources`, with a folder per Trellis part containing `Ferb.py` and `source.json`. The top-level `manifest.json` lists every saved, unmapped or failed row. CSV and JSON report inputs are supported. Files remain outside Git.

To request fresh copies, use:

```sh
python scripts/pull_ferb.py var/api-reports/missing-native-graders.csv --course 144164 --refresh
```

Fresh downloads use `VOCAREUM_TOKEN` when set, otherwise `../token.txt`. No token is needed when every mapped source is already cached. The script requests `/voc/private` as an export, polls the transaction, downloads its ZIP without sending API credentials to the signed download URL, and selects `Ferb.py` case-insensitively. It does not import or execute grading code. If assignment discovery is necessary, it reuses the full-pagination downloader rather than relying on the first page's embedded parts.

The initial inventory produced **131 saved files, 16 unmapped placeholders, and zero errors**. Unmapped entries have no confirmed Vocareum part ID and require separate matching; they are not evidence that a particular Vocareum part lacks Ferb.

Existing collected sources are reusable. If an existing `Ferb.py` has different bytes, the script reports an error rather than replacing it; move the old source aside intentionally before refreshing it. API errors and missing files are reported separately from unmapped IDs.

These are migration inputs. Collecting Ferb does not create a Trellis autograder or publish a change. Convert and review the exercise's tests, then use the native grader upload/test/publish workflow in [REST API documentation](REST_API.md).
