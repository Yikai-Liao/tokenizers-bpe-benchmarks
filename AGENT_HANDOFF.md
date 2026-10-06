# Agent handoff

Start with [README.md](README.md). The supported command is `python -m bench`,
run from this repository. Python supervises; the single Rust runner explicitly
selects `core` or `pipeline` through the recorded job.

1. Specify two immutable tokenizers revisions and the question being measured.
   Best Multicore `57c04ca9ed1e843f6e36fe68ed3ae5adf499936c` is the historical
   performance control. Official upstream `bbccb0513ff9afda385ca5c85c66eddb1318cfc7`
   is the API baseline. Do not confuse these roles. Use the retained control's
   recorded vendor/algorithm settings when reproducing that particular control.
2. Generate a named runner lock for each required dependency graph with
   `python -m bench lock`, then build with `python -m bench build`. Record the
   returned `build.json` paths. Builds are locked and source snapshots are retained.
3. Identify text with `python -m bench text`, or prepare pinned Wikipedia through
   `python -m bench corpus`. Only `core` requires `prepare-input`; `pipeline`
   calls the measured version's real public `feed` and `train_vocab`.
4. Copy an [experiment template](experiments/), set the build/input paths and an
   available CPU set from actual topology, then run into a **new** `.bench` output
   directory. A W-worker cell uses the first W CPUs. Paths resolve relative to
   the configuration file. Keep repetitions and warmups fixed before measuring.
5. Inspect `report/summary.json` and `REPORT.md`, all failures, full vocabulary
   IDs and ordered merges. Publish the exact revisions, identities, timing
   boundaries, paired ratios, memory measures and complete evidence. Historical
   mismatch remains a correctness failure after diagnostic retry.

`archive/` contains historical evidence and old exploratory scripts. Active
commands do not import it. Historical timings have their original boundaries;
[the published smoke](results/protocol-smoke-20261006/VALIDATION.md) validates
workflow and correctness, not large-corpus performance.

Use independent experiment directories when several agents work at once. Build
artifact copying is serialized; each experiment has one writer. Run performance
matrices on a quiet machine. Do not run overlapping compilation/testing while
claiming a timing result. Source/model mismatches require investigation rather
than a weaker comparator or altered token IDs.
