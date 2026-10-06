# Preliminary BPE comparison and ablations

The retained multicore candidate, its selected runtime configuration, and the
final structural experiment are documented in
[MULTICORE_CANDIDATE.md](MULTICORE_CANDIDATE.md).

This suite runs the current trainer and eight variants derived from the same
source. It writes to a separate experiment directory and labels its results
`preliminary`. Review and the later formal experiment remain separate steps.

Copy `preliminary.example.json`, replace the three corpus paths, and run:

```sh
python3 bpe-suite/suite.py all \
  --repo /absolute/path/tokenizers \
  --config /absolute/path/preliminary.local.json \
  --out /absolute/path/preliminary-results \
  --release-cache /absolute/path/shared-release-cache
```

To rerun the recorded matrix, use
[`results/preliminary-20261005/config.json`](results/preliminary-20261005/config.json)
and replace its five input paths. The example above is the initial profile.

The repository must contain the recorded Git revisions. The entry also supports
`prepare`, `build`, `smoke`, `run`, and `report` separately. Builds use one shared
Cargo cache. Measurement starts after builds and correctness checks finish.
`run` resumes completed paired blocks and reruns an interrupted block in full.
Use a new output directory after changing source revisions or parameters.

The primary comparison uses original HF BPE at `bbccb051`, PR #2348 BPE at
`6ac0de53`, and Full at `f9ff8b97`. The measured trainers share the Full frontend,
dependency skeleton, dependency lock, release profile, streaming feed, and word
map insertion order. The word map uses fixed seeds `[11, 13, 17, 19]`; internal
trainer maps keep their native random seeds. Separate native HF and peer binaries
check that the ported trainers preserve exact outputs on smoke inputs. Native
control timings are excluded.

Training time measures the public `do_train(&word_counts)` call, including the
returned vocabulary and ordered merge strings. End-to-end time includes common
file reading, pretokenization, word aggregation, and training. It ends before
validation and does not build an inference model. Whitespace is `WhitespaceSplit`.
ByteLevel applies the GPT-2 regex and byte-to-character encoding, without adding
a prefix space, and supplies all 256 alphabet symbols. Lines retain newlines.

| Variant | Change from Full |
| --- | --- |
| `no_radix` | Stable comparison sorting, retaining the cached keys and grouping |
| `one_rule` | At most one certified rule per round |
| `flat64` | Full U64 position values instead of G128, with the same inline cases and allocator |
| `u32_corpus` | U32 corpus slots, retaining deferred construction |
| `eager_corpus` | Materialize the corpus before initial grouping |
| `no_position_arena` | Zero pooling cutoff, retaining leases, locks, inline lists and G128 scratch reuse |
| `scalar_weights` | Scalar weight accumulation and interval searches |
| `dual_strings` | Independently owned vocabulary text in the lookup map and ID vector |

The flat-position variant necessarily changes the encoding workspace. All deltas
are conditional on Full and must not be added together. The supplementary peer
control restores its pre-WordArena BPE source. That arena stores corpus symbols;
Full's arena pools position buffers, so the two controls measure different objects.

Correctness directly compares vocabulary entries in token-ID order and merges in
rank order. Each run writes its canonical output after timing. One reference model
per case is retained; matching temporary copies are removed. A mismatch stops the
experiment and retains the differing model for inspection.

Each run records wall time, CPU time, training HWM, sampled RSS and swap, word and
symbol counts, initial edges, host load, parameters, and raw stdout/stderr. HWM is
read before model output; sampled RSS covers the whole child process, including
canonical model output. The parent compares files after the child exits.
Allocation counters are disabled. Memory, RSS, and timeout guards retain failures.
Only complete paired blocks enter statistics. Warm-ups are recorded separately.
The initial profile uses five repetitions with rotated and reversed arm order.
Two-arm groups alternate directly. A failed warm-up stops before timed blocks so
the input size or resource conditions can be adjusted first.

`prepared.json` records revisions, settings, dataset sizes, and machine information.
`summary.json` retains valid raw samples, per-block ratios, and failures (including
warm-ups); `summary.csv` reports medians and ranges. `comparisons.csv` reports the
median and range of ratios computed within each paired block, with Full as the
control and unchanged peer as the control for the peer arena group. A ratio above
one means the other arm costs more time or memory. Old experiments and binary
archives are unnecessary for this suite.
Docker packaging, dataset publication, reviewed formal runs, and capacity sweeps
belong to later phases.

## Multicore comparison

The scaling follow-up compares Full, original HF, and PR #2348 on the same
English 512 MiB, Chinese 256 MiB, and mixed 256 MiB inputs. It measures 1, 2, 4,
and 6 workers with three repetitions per cell. CPU affinity limits each child
to the first corresponding CPUs in the recorded CPU set, and the Rayon worker
count matches that limit. The current host exposes six KVM vCPUs; this does not
establish six dedicated physical cores.

Use the source snapshots, runner, dependency lock, and canonical model references
from the prepared preliminary suite:

```sh
python3 bpe-suite/scaling.py all \
  --prepared-suite /absolute/path/preliminary-results \
  --config /absolute/path/scaling.local.json \
  --out /absolute/path/scaling-results \
  --release-cache /absolute/path/shared-release-cache
```

The scaling configuration provides `arms: ["full", "hf", "peer"]`,
`workers: [1, 2, 4, 6]`, `repetitions: 3`, `warmup_workers: 6`, and the host's
available `cpu_set`, together with the same source revisions, compiler flags,
three case descriptions, and resource guards as the preliminary suite. Builds
reuse its exact dependency lock. A 36-run smoke gate checks all three trainers
at every worker count before real-input warm-ups and timing.

Each paired block contains all twelve trainer/worker configurations. The order
rotates between blocks and reverses on alternating blocks. All four-worker
measurements are new observations within those blocks. `scaling-speedups.csv`
reports each trainer's T1/Tp training and end-to-end speedups, parallel efficiency,
CPU-time ratio, and HWM relative to its own one-worker control.
`algorithm-comparisons.csv` reports HF/Full and peer/Full ratios at equal CPU
counts. Each ratio is computed inside the same block before its median and
observed range are summarized.

`summary.csv` records absolute time, HWM, sampled RSS, and swap with medians and
ranges for every trainer/worker cell. HWM is read before canonical model output;
sampled RSS covers the whole child. `summary.json` retains every raw observation,
ratio, arm order, and failure. Exact token IDs and ordered merges are compared
with the preliminary suite's canonical case models after each run.

Run supervisor checks with `python3 -m unittest discover -s benchmarks/bpe-suite`.

## Preliminary results, 2026-10-05

The complete matrix contains 35 paired blocks, 120 timed runs, and 24 cells
with five observations each. Every timed run matched the same case's vocabulary
IDs and ordered merges. There were no timed-run failures and the supervisor
observed zero swap for every timed subprocess. These results use unchanged
Full source at `f9ff8b97`; code review and the formal experiment remain pending.

The correctness gate also passed 42 smoke runs across all 14 arms, including
the native HF and peer controls. Eight supervisor checks and five flat-position
collection tests also passed. Native control timings
are excluded from these tables.

All inputs are ordered, normalized Wikipedia paragraphs from the pinned
`wikimedia/wikipedia` revision `b04c8d1ceb2f5cd4588862100d08de323dccfbaa`
and the 20231101 snapshots. Mixed 512 MiB interleaves whole lines from English,
Chinese, Japanese, and German, approximately 128 MiB per language. The 256 MiB
cases are whole-line prefixes of their 512 MiB counterparts. Text is not
replicated to reach the requested size. English uses a 50,000-token target;
Chinese and mixed inputs use 100,000. Other parameters appear in the protocol.

Runs were serial on a KVM host exposing six Xeon Gold 6140 vCPUs and 15.59 GiB
of physical memory, using four training workers, native CPU compilation,
fat LTO, and disabled allocation counters. Background Codex sessions and
tmpfs research caches were released before the matrix. Exact input bytes
and word, symbol, and initial-edge counts are recorded in
[protocol.json](results/preliminary-20261005/protocol.json).

### Primary comparisons

The table reports medians of absolute measurements. End-to-end time includes
the common feed and BPE training; process HWM is read before model output.

| Case | Trainer | BPE training (s) | End-to-end (s) | Process HWM (GiB) |
| --- | --- | ---: | ---: | ---: |
| English 512 MiB | Full | 2.705 | 17.937 | 0.478 |
| English 512 MiB | Original HF | 44.670 | 60.028 | 2.477 |
| English 512 MiB | PR #2348 | 9.981 | 25.236 | 0.708 |
| Chinese 256 MiB | Full | 12.191 | 16.099 | 1.647 |
| Chinese 256 MiB | Original HF | 312.567 | 316.037 | 11.666 |
| Chinese 256 MiB | PR #2348 | 135.283 | 138.944 | 3.928 |
| Mixed 256 MiB | Full | 12.302 | 22.908 | 1.838 |
| Mixed 256 MiB | Original HF | 213.772 | 224.763 | 10.817 |
| Mixed 256 MiB | PR #2348 | 48.017 | 58.656 | 3.358 |
| Chinese 512 MiB | Full | 20.716 | 28.619 | 3.155 |
| Chinese 512 MiB | PR #2348 | 266.786 | 274.654 | 7.022 |
| Mixed 512 MiB | Full | 21.815 | 41.911 | 3.100 |
| Mixed 512 MiB | PR #2348 | 83.096 | 103.094 | 5.730 |

The following ratios are computed inside each paired block, then summarized
by their median. They are not divisions of the preceding table's medians.
A ratio above one means that the named trainer costs more than Full.

| Case | Trainer / Full | Training ratio | End-to-end ratio | HWM ratio |
| --- | --- | ---: | ---: | ---: |
| English 512 MiB | Original HF | 16.808× | 3.356× | 5.180× |
| English 512 MiB | PR #2348 | 3.755× | 1.411× | 1.482× |
| Chinese 256 MiB | Original HF | 25.249× | 19.626× | 7.049× |
| Chinese 256 MiB | PR #2348 | 11.187× | 8.753× | 2.385× |
| Mixed 256 MiB | Original HF | 17.458× | 9.945× | 5.886× |
| Mixed 256 MiB | PR #2348 | 3.903× | 2.570× | 1.828× |
| Chinese 512 MiB | PR #2348 | 12.901× | 9.767× | 2.225× |
| Mixed 512 MiB | PR #2348 | 3.811× | 2.459× | 1.848× |

Original HF did not complete either 512 MiB Chinese or mixed input under the
host reserve guard. After resource cleanup, the last attempts stopped at
approximately 12.43 GiB sampled RSS with zero process swap. This is an observed
lower bound before stopping, not a completed-run HWM or an OOM result. Those
two cases therefore compare Full and PR #2348; their three-way comparisons
use 256 MiB. Ratios never cross input sizes.

Six HF 512 MiB memory-guard attempts, one cancelled Peer warm-up, and one
partial Chinese 512 MiB timed block interrupted for the arm-order correction
are retained separately and excluded from statistics. That timed block was
then rerun in full. Two-arm groups alternate directly; the retained first
Chinese 512 MiB block has the same valid order as the corrected schedule.

### Core ablations

The Chinese 512 MiB whitespace case contains five paired blocks (45 timed runs).
Full's median BPE training time is 20.76 s and its process
HWM is 3.15 GiB. Each row disables one feature.
The percentages are medians of within-block ratios relative to Full; the
range covers the five observed training ratios. Effects are conditional on
Full and cannot be added together.

| Change from Full | Training time change | Observed range | Process HWM change |
| --- | ---: | ---: | ---: |
| Stable comparison sorting | +9.34% | +8.14% to +11.18% | +22.36% |
| One rule per round | +45.16% | +43.20% to +47.55% | +0.08% |
| Full U64 positions | +7.56% | +4.74% to +13.99% | +35.01% |
| U32 corpus slots | +2.16% | -3.97% to +7.45% | +4.22% |
| Eager corpus construction | -4.55% | -7.78% to -1.52% | +14.62% |
| Position pool disabled | +18.93% | +12.53% to +25.85% | +0.29% |
| Scalar weights | +10.98% | +8.28% to +16.77% | -0.07% |
| Independently owned vocabulary strings | +0.87% | -4.29% to +1.75% | +0.03% |

Eager construction trades lower latency for a higher peak. U32 slots and dual
strings show no consistent timing direction across these five samples. U32
slots increase measured HWM by 4.22%, while dual strings barely change it.
HWM includes the common word map and transient buffers; it does not measure
the payload size of a single structure. Full U64 positions also change the
encoding workspace, as described in the variant table above.

### Supplementary Peer WordArena control

This comparison uses its own five paired blocks and the unchanged peer as
baseline. The other arm restores the pre-WordArena BPE source at `2e22a686`.
Peer's arena stores corpus symbols; Full's arena pools position buffers.

| Peer variant | BPE training (s) | End-to-end (s) | Process HWM (GiB) |
| --- | ---: | ---: | ---: |
| With WordArena | 304.352 | 313.112 | 7.022 |
| Before WordArena | 332.364 | 340.712 | 7.128 |

Relative to the peer with WordArena, the pre-WordArena arm changes training
time by +12.42% (observed range
+2.77% to +18.02%), end-to-end time by
+11.95%, and process HWM by +1.51%.
This control does not isolate the other algorithm changes in PR #2348.

### Data and interpretation

[Absolute summaries](results/preliminary-20261005/summary.csv),
[paired comparisons and observed ranges](results/preliminary-20261005/comparisons.csv),
[raw samples and ratios](results/preliminary-20261005/summary.json),
[per-run resources, jobs, and arm orders](results/preliminary-20261005/samples.json),
[portable configuration](results/preliminary-20261005/config.json), and
[protocol](results/preliminary-20261005/protocol.json) contain the complete
matrix. The earlier core-only CSV files remain an identical subset.

The five observations describe this host, input selection, frontend, and
worker count. Small effects with ranges spanning zero do not establish a
consistent timing direction. The report makes no significance claim or
multi-gigabyte capacity extrapolation. Local raw stdout/stderr and canonical
case models are retained; standalone executables and Cargo build caches are
removed after measurement.
