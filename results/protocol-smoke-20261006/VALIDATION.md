# Protocol validation, 2026-10-06

This is correctness and workflow evidence, **not performance evidence**.

- Python supervision/protocol tests: 15 passed, including late mismatch,
  diagnostic retry, changed input/binary/revision/CPU, invalid output, signal,
  timeout, memory guard and interrupted recovery.
- Native locked runners: official upstream `bbccb0513ff9afda385ca5c85c66eddb1318cfc7`
  and simplified source `d857cfeecc659449550c6f5ff37438c6d0ebffd5`.
- 112 independent process attempts passed, including warmups; exact vocabulary
  IDs and ordered merges matched for 1/2 workers, four preprocessors, core and
  public pipeline, single-character affixes and empty/zero-target input.
- Every successful main-matrix experiment was resumed without adding attempts.
- Model JSON serialization and comparison took place after training timing.

[manifest.json](manifest.json) binds source revisions, experiment IDs, attempt
counts and archive checksums. `smoke-records.tar.gz` contains plans, environments,
build manifests, input manifests and fixtures, all attempts/logs/full models, and
reports. Its recorded `.bench` paths are original locators, not portable resume
paths. Extract and inspect or regenerate reports with `python -m bench report
--out <extracted-smoke>/<experiment-name>`. To rerun, build the two recorded
revisions using the supplied lock profiles and use a new output directory.

The preliminary multi-character affix fixture failed even when both arms used
identical upstream binaries. `upstream-affix-diagnostic.tar.gz` preserves that
original mismatch, both models, logs, failed summary, build provenance and runner
source/lock. The passing smoke uses a single-character affix fixture to verify
that API path. This diagnostic was not erased, relabeled as a passing experiment,
or used for performance conclusions; the exact comparator remains unchanged.

Validation used Linux, Python 3.14.7 and rustc 1.99.0 locally. CI is configured to
run Python 3.11 and a pinned-upstream runner smoke. No large corpus performance
matrix was rerun as part of this repository restructuring.
