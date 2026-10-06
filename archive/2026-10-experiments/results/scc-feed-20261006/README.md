# SCC feed experiment

These results compare bounded local preaggregation into SCC against the optimized
thread-local, partitioned feed implementation. They measure public `Trainer::feed`
with repository pretokenizers, not total BPE training time or the original Best
Multicore implementation. Both arms use identical fixed AHash seeds for this
algorithm comparison. Production code must use the default random state.

The SCC candidate retains at most 2,048 unique keys per local table, flushes
weighted counts into a shared table, and consumes the final table directly into
owned, globally unique, unordered entries. It does not export a new ordinary
dictionary. Training remains responsible for sorting. Counts are plain `u64`
protected by SCC entry guards; an extra atomic counter is unnecessary here.

## Completed three-pair experiment: local-cache-hybrid

Each cell has one warmup per arm and three measured pairs, with rotated cell order
and reversed arm order. Workers are pinned to distinct physical cores. Every
complete word-count output matched exactly. All 72 measured runs completed without
swap. Times and peak RSS below are arm medians; percentage changes use paired
median ratios, so they may differ slightly from ratios of arm medians.

| Input / pretokenizer | Workers | TLS feed, s | SCC feed, s | Paired time change | TLS peak RSS, MiB | SCC peak RSS, MiB |
|---|---:|---:|---:|---:|---:|---:|
| Chinese 256 MiB / Whitespace | 8 | 1.1640 | 0.9059 | -22.2% | 1039.0 | 697.7 |
| Chinese 512 MiB / WhitespaceSplit | 8 | 1.7618 | 1.6082 | -9.2% | 1059.2 | 906.8 |
| English 256 MiB / WhitespaceSplit | 8 | 0.7234 | 0.6627 | -8.4% | 292.3 | 216.6 |
| English 256 MiB / Whitespace | 8 | 0.6467 | 0.6294 | -4.4% | 207.3 | 66.1 |
| English 256 MiB / ByteLevel | 8 | 0.7280 | 0.6691 | -8.1% | 223.2 | 70.2 |
| Synthetic 64 MiB / 11 repeated keys | 8 | 0.0797 | 0.0851 | +8.1% | 3.6 | 3.7 |

ByteLevel uses the repository GPT-2 regex splitter followed by byte mapping.
The synthetic case is an extreme contention probe, not representative English.
Its small regression is an accepted tradeoff given real-corpus speed and memory
benefits. Single-worker cells in this version regressed by approximately 2.6–5.6%,
motivating a minimal sequential specialization.

The measurements are process high-water RSS captured immediately after feed,
before allocating canonical validation output. They are not dictionary capacity
estimates. Peak memory for feed plus train must still be measured separately.

`local-cache-hybrid/` contains protocol, all measured samples, summaries, per-run
jobs/results/logs, and both build provenances. Binary and raw corpus data are
excluded. The common runner versions differ only by a post-timer retained-RSS
measurement; final verification rebuilds both arms from the same runner source.

## Minimal sequential specialization

The revised candidate uses one ordinary map and standard-library `Iterator::fold`
when parallelism is disabled or the calling Rayon pool has one worker. There is
no Rayon bridge, parallel fold, collect, local-map vector, or final reduction on
that path. Callback handling, error handling, word traversal and key conversion
are shared by both paths in `accumulate`; statically dispatched small closures
provide their different counting operations. Callbacks continue after the first
normal error, the first error is retained, and failed feed does not replace the
old trainer state. Parallel feed retains the SCC implementation.

The revised candidate passed 68 existing unit tests and the external feed-contract
test. The production worktree with default random seeds also passed 68 unit tests.
The external test covers caller pools, callback/input feedback, error state,
serialization, equality, empty and non-fused input, WordPiece, and direct-training
equivalence.

Independent review accepted the preceding minimal sequential loop, including
callback/error and caller-pool semantics. A follow-up review of the final shared
`accumulate` implementation was attempted but did not run because the reviewer
agent reached its usage limit. That final refactoring has local test coverage and
primary-agent inspection; it does not have a completed independent review.

The common-source-runner experiment completed 48 measured runs with three pairs
per cell, exact word-count equality, and zero sampled swap. `shared-fold/` contains
the complete evidence. Relative to optimized TLS, paired median changes were:

| Input / pretokenizer | 1-worker feed time | 8-worker feed time | 8-worker peak RSS |
|---|---:|---:|---:|
| English 256 MiB / WhitespaceSplit | -2.1% | -14.1% | -21.5% |
| English 256 MiB / Whitespace | +4.0% | -14.4% | -66.9% |
| English 256 MiB / ByteLevel | -1.4% | -19.8% | -69.5% |
| Synthetic 64 MiB / 11 repeated keys | -1.0% | -3.7% | +1.8% |

Single-worker Whitespace paired ratios ranged from 0.9909 to 1.0565; ByteLevel
ranged from 0.9665 to 1.0774. The small sequential deltas need to be considered
alongside that variation. The synthetic 8-worker ratios ranged from 0.8725 to
1.0166, so this experiment does not establish a reliable hotspot speedup.
Chinese feed-only results above remain specific to the earlier hybrid version.

## Production feed plus train

Two matrices completed 60 measured runs using default random seeds. Each cell has
three measured pairs after warmups. These compare the published core-only tree
(`d857cfee`, identical to `3e79a09f`) with its original feed against the current
SCC implementation and shared sequential fold. The training engine is otherwise
the same. Every complete ID-ordered vocabulary and ordered merge output matched;
no sampled swap was used. Both arms were built from the same joint runner source.
Common dependency versions match; the candidate additionally uses SCC and its
two transitive dependencies.

Percentages below use paired median ratios. Time includes both public `feed` and
`train_vocab`; memory is process high-water RSS before model serialization.

| Input / pretokenizer | Vocabulary limit | 1-worker total time | 8-worker total time | 8-worker total peak RSS |
|---|---:|---:|---:|---:|
| Chinese 512 MiB / WhitespaceSplit | 100,000 | +0.3% | -14.5% | -4.0% |
| English 256 MiB / WhitespaceSplit | 100,000 | -11.4% | -22.2% | -0.1% |
| English 256 MiB / Whitespace | 100,000 | -24.0% | -20.6% | -4.2% |
| English 256 MiB / ByteLevel | 100,000 | -18.7% | -20.2% | -3.8% |
| English 64 MiB / ByteLevel | 50,000 | -17.5% | -16.5% | +12.2% |

Feed-only and joint comparisons have different baselines: optimized TLS for the
former, original feed for the latter. Their percentage improvements must not be
added or compared as if they shared a baseline. Likewise, feed's large memory
reduction does not imply the same reduction in overall training peak memory.
Training dominates the larger Chinese peak. The 64 MiB English ByteLevel joint
case increased peak RSS by about 10 MiB while reducing total time.

Chinese sequential total-time paired ratios ranged from 0.9767 to 1.0632, with a
median of 1.0025. This experiment supports roughly unchanged sequential total
time on that workload. Joint evidence is in `production-joint-large/` and
`production-joint-english/`, including actual runner source and build provenance.

Chinese and English Wikipedia inputs are derived from `wikimedia/wikipedia` at
revision `b04c8d1ceb2f5cd4588862100d08de323dccfbaa`, configurations `20231101.zh`
and `20231101.en`. Input sizes and SHA-256 hashes are recorded in the protocol.
