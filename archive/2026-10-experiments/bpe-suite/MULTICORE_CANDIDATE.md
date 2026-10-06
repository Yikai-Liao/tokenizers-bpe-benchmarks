> Historical experiment instructions: use the preserved source snapshot for the relative Cargo paths below. For independent builds, use `../build_runner.py` as described in the root README.

# Retained multicore BPE candidate

This branch preserves the validated Full configuration selected before the final
commit experiment. It combines complete-producer birth encoding, whole-pair
preparation layout, owner-local birth grouping, reciprocal shard routing, and the
measured Rayon idle policy. Initial position encoding can use every owner.
G128 positions, checked counts, identity-reuse behavior, and canonical model
ordering remain intact.

The implementation is an experimental candidate selected by explicit settings.
Use the wrapper below: library defaults do not enable every selected option.
The source snapshot is `commit-removal-selective`, based on
`1a38481cfa0bdf14b83ba0038c69ce4761e7f929`. The included
[source manifest](results/multicore-20261006/source-manifest.json) records its Rust
files and vendored dependency. The dependency locks and standalone runner preserve
the measured dependency graph; paths have been relocated into this repository.

The relocated delivery passed native fatLTO build, 60 library tests (one existing
stress test ignored), and a six-worker ByteLevel canonical model check. The archived
patch also passed `git apply --check`; see the [delivery validation](results/multicore-20261006/delivery-validation/summary.json).

## Build and run

From the repository root:

```sh
RUSTFLAGS="-C target-cpu=native" cargo build --locked --release \
  --manifest-path bpe-suite/multicore-runner/Cargo.toml

bpe-suite/with_multicore_candidate.sh \
  bpe-suite/multicore-runner/target/release/bpe-suite-runner \
  /absolute/path/job.json
```

The runner accepts the existing suite job format, for example:

```json
{
  "input": "/absolute/path/corpus.txt",
  "split": "whitespace",
  "vocab_size": 50000,
  "min_frequency": 2,
  "workers": 6,
  "output": "/absolute/path/model.json"
}
```

The wrapper selects producer fast/direct encoding, `whole` layout, fused commit
grouping, fast shard routing, batch limit 256, and Rayon spin 4096/pause 1. Extra
logical owners, removal-reduction experiments, and diagnostics are disabled.
The vendored `rayon-core` 1.13.0 changes its idle polling policy through those
environment settings; its wakeup, latch, and sleeping protocol is retained.
The upstream licenses are included. This policy can increase idle CPU usage;
its exploratory comparisons have limited repetition.

The standalone runner reports public `do_train` time after word counting and
separately reports the input/feed boundary. The archived `core_seconds` comparisons
use a measurement overlay that starts after weighted token-ID words are ready and
ends after pair indexing, merges, cleanup, and in-memory model construction.
That boundary excludes feed, initial ID resolution, and model serialization.
The core-timed control binary and the retained source snapshot have separate
provenance; their times must not be mixed as if they were one executable.

## Final commit experiment

The final candidate froze Fresh hash-map structure, scattered checked atomic count
decrements over bounded tasks, and constructed complete cold birth buckets in
independent tasks. Owners erased retired entries and published completed states
and priorities only after all shared readers joined. Single-worker execution and
Reusable ledgers retained their original algorithms.

This reduces the scope of exclusive owner work. It introduces atomic contention,
additional tasks and joins, and temporary coexistence of retired and new position
lists. One large key and each owner's final map/heap publication remain indivisible.

All 12 six-worker samples and four single-worker guard samples matched canonical
model bytes. Four focused tests, 64 library tests, native build, and one-/six-worker
ByteLevel canaries passed; one pre-existing stress test remained ignored. The first
synthetic fixture omitted the coordinator's pre-commit prefix restoration. Its
[failed run](results/multicore-20261006/commit-scatter/first-test-failure.log) is
retained; fixing that fixture left production code unchanged.

| Workload | Baseline T6 median | Candidate T6 median | Change in medians | Three paired changes |
|---|---:|---:|---:|---|
| ZH256 | 12.191 s | 11.674 s | -4.24% | -10.29%, +6.59%, -5.69% |
| EN512 | 2.320 s | 2.489 s | +7.27% | +36.35%, +2.02%, -2.98% |

The medians of paired ratios are separately -5.69% and +2.02%. They are different
statistics from the changes in arm medians above. All samples are retained.
Median six-worker HWM was effectively flat: ZH 1,994,084 to 1,991,448 KiB;
EN 522,104 to 521,452 KiB.

The one-pair T1 guard measured ZH 40.107 to 39.554 seconds and EN 6.740 to 6.376
seconds. It found no single-worker regression in that pair, but is not a repeated
scaling study. Combining those guard times with T6 medians is insufficient to claim
a stable new speedup ratio.

**Decision: retain the prior Full configuration.** The structural change did not
establish a general improvement across the two large workloads. Its implementation
is archived as [an unapplied patch](results/multicore-20261006/commit-scatter.patch)
against this branch's retained Rust sources; the live implementation remains the
previous candidate. After applying the patch, enable the experimental switch after
the wrapper's retained settings: `with_multicore_candidate.sh env TK_COMMIT_SCATTER=1 COMMAND`.
No further parameter sweep was performed.

See the [final gate record](results/multicore-20261006/commit-scatter/final-gate-summary.json),
[six-worker results](results/multicore-20261006/commit-scatter/w6-summary.json),
[single-worker guard](results/multicore-20261006/commit-scatter/t1-summary.json), and
[artifact manifest](results/multicore-20261006/artifact-manifest.json).

## Remaining scaling constraint

The earlier [full-core diagnostic](results/multicore-20261006/core-budget/summary.json)
attributed about 70% of the excess over ideal six-worker scaling to preparation
and commit together, using stage wall time and coarse worker task measurements.
Process CPU deltas between short phases are affected by cross-thread accounting
lag and were not used as precise per-phase CPU attribution. Preparation tails mostly
scan positions. Commit ties count updates, birth construction, and queue maintenance
to mutable pair shards. Splitting preparation also loses complete-producer work
and adds cross-producer aggregation. Exact next-rule selection and packed-corpus
read/write safety require completion barriers.

[YouTokenToMe](https://github.com/VKCOM/YouTokenToMe/blob/f4162d846057a3118222ca04a01b84297eb8a8db/youtokentome/cpp/bpe.cpp)
makes a different ownership choice: each worker persistently owns its
word partition, local positions, and local counts. Its coordinator synchronizes
count queries and global rule selection; position lists remain local. Full's
position-based work distribution followed by pair-based state ownership incurs
a redistribution step that this design avoids. This comparison explains a
structural tradeoff, not an assertion that either layout is globally optimal.

Earlier producer publication, independently scheduled complete-key encoding, and
uncompressed position storage also failed to establish the required broad benefit.
The [ready-codec results](results/multicore-20261006/ready-codec/summary.json) and
[36-row position-storage ablation](results/multicore-20261006/position-storage/summary.json)
are archived. The latter's compressed T1 drift remains unexplained and cannot be
used to claim improved scaling.

The requested four-/six-worker scaling target has not been fully achieved.
Optimization exploration stops after this final experiment; the branch delivers
the retained measured candidate and the evidence for that choice.
