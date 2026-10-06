# Simplification and compatibility review

The performance control is Best Multicore at
`57c04ca9ed1e843f6e36fe68ed3ae5adf499936c`. The public interface control is official
Hugging Face main at `bbccb0513ff9afda385ca5c85c66eddb1318cfc7`. These controls serve
different purposes: existing performance experiments do not define public APIs.
The final source revision is `6cda2e07000c63f66ee47cc7aac8a9628985de3a`, also recorded in the source snapshot
manifest and build provenance. It is one implementation commit on the official main baseline.

An independent agent reviewed architecture, tests and function ownership against
these controls using the software-design-philosophy skill. The retained design
separates token identity, corpus state, priorities, write preparation and resource
lifetimes. The additional engine surface is private to BPE training. The review
found no remaining credible large production deletion that preserves the measured
algorithms; the final performance report is needed to assess their costs.

## Production source size

`count_core.py` masks Rust comments and literals to find complete `cfg(test)`
items, statements and arguments, then counts the retained source with `tokei`.
Dedicated engine test files are omitted. Code lines omit blanks and comment-only
lines; trailing comments do not erase a code line. The core includes the original
`tk-collections` storage crate in Best Multicore and the private `engine/storage`
module in the candidate. Moving files therefore earns no size reduction.

| Scope | Best Multicore | Final candidate | Difference |
| --- | ---: | ---: | ---: |
| Engine and storage, production SLOC | 6,713 | 5,173 | -1,540 (-22.9%) |
| Trainer, Word, private feed/count view, excluding tests | 388 | 513 | +125 |
| Progress renderer | 219 | 135 | -84 |
| Combined scopes | 7,320 | 5,821 | -1,499 (-20.5%) |

These are source counts, not generated code, instruction counts or a claim that
all retained lines execute on every feature path. File-level scopes and counts
are preserved in `baseline-sloc.json` and `candidate-sloc.json`.

## Changes that reduce review cost

- Move the necessary collections into private engine storage; remove the extra
  workspace member and forwarding wrappers. Delete unused storage operations,
  iterator directions, scratch statistics and the unused direct smallvec dependency.
- Keep stable full-key radix grouping, G128 positions, compact slot planes,
  allocation leases, whole-pair scheduling and direct complete-producer births.
  Remove diagnostics, unused scheduling strategies and experimental switches.
- Separate corpus preparation, slot storage and live-corpus access; separate
  compact merge events from the actual read/prepare/write workflow.
- Put the complete `RulePreparation` constructor beside its methods and make
  initial-table construction `InitialPairTable::build` / `build_in_waves`.
  Do not add thin accessors or move cross-object scheduling into resource owners.
- Keep `PreparedMerges::apply` as a consuming operation. Keep `Execution` concerned
  with pools, leases, scratch resources and recovery, rather than BPE policy.
- Restore the upstream JSON progress fields and show-progress behavior while
  retaining coarse atomic accounting and a separate periodic renderer.

The main performance tradeoff is retaining several specialized merge paths.
Complete producer, split producer, AA overlap and active-ID reuse have distinct
eligibility and count semantics; collapsing them would move complexity into
conditional hot loops and would need new performance evidence.

The second focused pass removed 64 production SLOC: test-only arena optionality
and forwarding, duplicate encoded-size/write logic, repeated affix-state inference,
and the obsolete owner-count forwarding method. The private `RuleBatch` makes the
main select/prepare/apply/commit loop explicit and owns its reusable selection
containers. Its declaration, outcomes and phase calls cost a net 43 source lines,
so that pass reduced the core by 21 lines, to 5,121. This is an explicit readability
tradeoff, rather than claiming file movement or every new abstraction saves lines.

A final hierarchy pass separates read-only preparation from consuming application.
The merge root holds contracts and `apply`; preparation dispatches to complete
ordinary/AA/cohort algorithms, with shared private neighbor rules in its parent.
Pair-index commit is a directly moved inherent implementation in a child module,
not a forwarding method. Module imports and explicit leaf signatures add 49 SLOC,
bringing that revision to 5,170; the private word-count view adds three engine
source lines, bringing the current engine to 5,173. Independent normalized-body comparisons found
no changes to ordinary preparation or commit algorithms, allocations or joins.
Sorted positions and radix stay together to keep their representation and unsafe
proofs local. This is a navigation benefit, not a claimed algorithm size reduction.

## Test audit

The independent final review confirmed the shared encoding writer, affix-state
reuse, batch outcomes and lifetime order without finding a semantic change.

The PR retains 68 library tests in both default and no-default configurations;
67 apply on i686 because one resident-size assertion is 64-bit specific.
These tests protect public feed/train/reload and thread/progress behavior, weighted
and tie ordering, AA overlap, affixes, strict length limits, active-ID restart,
reserved IDs, wide and signed counts, zero-merge validation, routing and storage
lifetime/unsafe boundaries. The reference preserves upstream queue/cohort semantics
independently of optimized storage; the retained differential test uses 64 cases.

Three tests were removed from the implementation PR:

- A duplicate active-ID reuse/restart test whose exact fixtures and trace/model
  assertions already appeared in a stronger test that observes the restart.
- A 250-case experiment and second fresh-only greedy recomputation oracle.
  Keep this extra cross-check in `extended-tests.rs`, rather than requiring a
  reviewer to assess two independent reference implementations in one PR.
- A 27-cell plan/materialization/wave snapshot comparison using the same initial
  counting implementation on both sides. Coordinate-by-coordinate source checks
  and independent literal wave/weight/filter expectations retain its substantive
  boundaries. The larger comparison is preserved in `extended-tests.rs`.

The 1,500-case stress check is also external, in `stress-test.rs` with a disposable
checkout runner. Shared worker matrices keep serial and multiple-worker branches;
redundant interior compact-slot domains and proportional AA coordinate scales
were removed. Wide positions, radix dispatch thresholds, iterator replay changes,
append errors, forgotten-drain recovery and arena lifetime tests remain.

The partial-producer eligibility fixture now enables the fast path in both worker
configurations. Its four-worker partition really splits five-occurrence candidates
into partial tasks; an empty direct-birth output therefore checks eligibility,
rather than merely checking an explicitly disabled fast path.

## Public interfaces and parity

`BpeTrainer` public methods and builder signatures match the official baseline;
`public-api-audit.json` records no additions or removals. The inference model name
`PipelineBPE` already exists in that baseline; this PR does not rename a public
BPE type. Serialization and bindings are unchanged.

The official baseline's optional parity trainer does not compile: it imports
`super::BPE`, which was already removed upstream. The final parity trainer file is
byte-identical to official main and has the same compile failure. Consequently
there is no valid upstream parity runtime/performance comparison. No temporary
compatibility repair or replacement parity algorithm is part of this PR.
`upstream-parity-check.log` and `final-parity-check.log` preserve the evidence.

The candidate uses released Rayon, as official upstream does. The historical
vendored idle-policy dependency is confined to the performance control snapshot.
The existing radix implementation and its BSD notice remain; no third-party
RadSort is introduced. Experiments and Chinese historical notes reside here,
not in the implementation branch.

## Feed review and portability

A separate independent review found that `BpeTrainer::feed` was identical to Best
Multicore and official main. It creates one word-count map per input sequence,
then merges that map into an accumulator. The isolated `feed-fold` experiment
keeps `maybe_par_bridge`, uses its existing partition fold, and retains the same
reducer. It calls `process` before propagating an earlier accumulator error, so
all callbacks still execute. Empty input clears the word table; failed feed
retains the previous table; successful repeated feed replaces it. Parallel first
error ordering was never an upstream guarantee. The public feed runner compares
canonical full word counts, separately from the core runner's manual input count.

The independent review approved dynamic position flags based on `usize::BITS`,
high-u64 seed fallback with actual singleton/pair lengths, `AtomicUsize` work
counters with u64 rendering, and the 64-bit-only resident-offset fixture. Existing
storage oracles already exercise high-u64 singleton/pair values. Actual i686
no-default-feature library tests passed (65 tests; the resident-base fixture is
excluded). No ARM hardware performance or cross-compilation result is claimed.

## Public feed redesign

The original public iterator/callback adapter is retained. Each fold aggregates
owned strings locally, then routes unique entries by a common AHash into disjoint
partitions. Each partition is finalized independently. Train consumes a private
flat borrowed view of those tables; no second ordinary global dictionary is
exported. Public `do_train(&AHashMap<CompactString, u64>)` borrows the caller's
existing table through the same view, with no clone or rehash.

Successful feed replaces prior state only after all callbacks finish and results
are checked. Failure preserves prior state; upstream callback and local Rayon-pool
behavior remain intact. Flat-map serialization, content equality, empty state,
zero counts and full-u64 deserialization remain covered. These two focused tests
run in the existing thread-policy matrix, rather than a new protocol test framework.

Capacity begins at the largest incoming local chunk, a guaranteed lower bound
on a partition's distinct keys. Reserving the sum counts repeated keys multiple
times; the simpler bound halves retained slots in the regex Chinese diagnostic.
Peak RSS includes earlier local tables/routed entries and is not claimed to halve.

An independent final review found no architectural blocker. Owned-row SCC variants
remain external experiments: removing export rehash fixes a real cost, but
global atomic updates regress severely on hot keys. A bounded local-cache
variant checks that contention separately. New dependencies and cache thresholds
require a representative single/multiple-worker win before production adoption.
