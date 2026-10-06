# BPE training

`BpeTrainer` builds a vocabulary and an ordered merge list from weighted words.
The builder, `Trainer::feed`, `Trainer::train`, and `train_vocab` are its public
entry points. WordPiece training consumes the vocabulary through `train_vocab`.
Thread selection uses `tk_encode::parallelism`.

The design keeps the optimized corpus, grouping, compression, and merge
algorithms behind readable ownership contracts. Storage mechanisms belong in
`tk-collections` so other tokenizer algorithms can reuse them. BPE identities,
weighted counts, cohort ownership, and phase ordering belong in the trainer.
Changing a collection layout must not require its callers to reproduce that
layout or its allocation rules.

## Ownership and phases

```mermaid
flowchart LR
    Words[Weighted words] --> Vocabulary
    Vocabulary --> Plan[Prepared corpus]
    Plan --> Initialization[Initial pairs]
    Initialization --> Corpus[Materialized corpus]
    Corpus --> PairIndex
    PairIndex --> Selection
    Vocabulary --> Selection
    Selection --> Preparation
    Corpus --> Preparation
    Preparation --> Writes[Corpus writes]
    Writes --> Commit[Pair commit]
    Commit --> PairIndex
    Vocabulary --> Model[Vocabulary and ordered merges]
```

The coordinator in `engine/mod.rs` owns phase order. Each iteration selects rules,
resolves output IDs, prepares changes from an immutable corpus view, applies
joined writes, and commits pair changes. No preparation read overlaps corpus
writes. No next selection starts before commit completes.

When the initial vocabulary already meets the target, the coordinator returns
before allocating mutable slots or a pair index. Initial weighted edge mass
fitting `u64` proves that every nonnegative per-key count fits as well. If that
proof is inconclusive, checked initial counting still runs before the return;
independent keys may each fit even when their total exceeds `u64`. Affix and
identity-reuse signed bounds are checked while preparing the corpus in either
case.

| Module | Responsibility |
|---|---|
| `vocabulary` | Alphabet selection, decorated initial IDs, token strings, reserved IDs, and identity reuse |
| `corpus` | Borrowed initial word plan, consuming corpus materialization, token endpoints, boundaries, spans, and word weights |
| `initial_pairs` | Bounded record construction, stable grouping, initial counts, and position encoding |
| `pair_index` | Frequency interpretation, candidate priority, and birth position cohorts |
| `merge` | Disjoint merge plans and ordered neighbor changes |
| `aa_parity` | Leftmost nonoverlapping matches across position chunks |
| `execution` | One pool, worker scratch, and explicit scratch reuse |

`PreparedMerges` owns both the selected rules and their write positions. Its
consuming `apply` method returns `MergeEvents` after writes complete. Commit
borrows event chains until all count owners finish, then releases the complete
event buffers. Each producer owns one chain allocation. The batch routes actual
changes into one row per count owner; it allocates no producer/owner/bucket
directory matrix. Count actions keep producer order, and stable grouping by
birth bucket preserves source order, including zero-weight births with positions.
Owners count their actual birth buckets and distribute references into an exact
output vector in parallel. The old references remain alive until distribution
finishes; count actions are not reordered.
Values, fragments, and event nodes are task-local. Each executing
worker lends two reusable ID directories to preparation and commit; its encoding
scratch also lives with the pool. A directory lease covers sequential work only,
so no nested pool task can re-enter the same worker's lock.

Fresh batch preparation also reuses the selected-rule head and tail directories.
Between batches it resets the previously selected endpoints and initializes only
new vocabulary slots. Shared endpoints retain the complete pair-key lookup.
Cohort preparation uses the same worker directories for neighbor changes,
but does not use this fresh batch lookup. Rule and candidate vectors also retain
their bounded capacity across rounds. Conflict sets are populated only when
another rule can enter the batch, so single-rule rounds leave them unallocated.

After the last merge phase joins, the coordinator releases selected position
lists and the pair index, then the corpus and arena, and clears reusable scratch
before building public model strings. Model construction reads only the
vocabulary and ordered merge IDs.

Vocabulary stores canonical token strings in an append-only `IndexSet` with the
same AHash hasher. Insertion indices are token IDs, so one string serves text
lookup and direct lookup by ID. No deletion or reordering can change those IDs.
Active flags occupy a separate vector. New merge text moves into the set after
the coordinator has checked that it is absent. Limited-alphabet selection keeps
its existing frequency map, tie handling, and final codepoint order; decorated
initial IDs still follow the original word-map traversal.

## Coordinates and storage

A position is a physical start slot, represented by `u64` throughout scheduling,
position storage, and event preparation. A resident allocation uses `usize`
indices. Full coordinate representation does not imply that a process can
allocate every possible coordinate.

Initialization starts with `PreparedCorpus`, which borrows weighted words and
retains their measured global starts, initial ID lookup, and weight intervals.
Word sorting and alphabet filtering establish the same coordinates used by the
mutable corpus. Initial pair routing reads this plan directly. `InitialPairSource`
visits complete pair keys in ascending coordinate order; each range owns left
endpoints and reads one token beyond its end when an edge needs lookahead.
Affix flags use original byte positions, including when characters are filtered.
Empty words retain their separator positions.

Long words have sparse checkpoints at UTF-8 character boundaries about every
4096 bytes. A checkpoint records the next retained symbol's coordinate and a
byte offset. Filtered stretches may repeat that coordinate; seeking uses the last
checkpoint before the requested token. This bounds repeated decoding when task
or wave boundaries split a long or heavily filtered word.

Independent byte chunks measure retained symbols in parallel. Their counts serve
both word lengths and a small ordered prefix that builds checkpoints, avoiding
another character scan. Materialization balances jobs by physical slots and
splits large words with these anchors. Affix lookup still uses each character's
original byte position rather than its position within a chunk.

After every raw wave is released, consuming `PreparedCorpus::materialize` fills
the existing mutable slot representation once in parallel. Borrowed word plans,
checkpoints, and initial ID lookup then leave scope. They never coexist with
merge writes. The plan uses one word reference and one U64 start per word, in
exchange for repeating UTF-8 decoding and ID lookup during initial routing.
Full training memory and CPU determine whether that lifetime trade is useful.

The coordinator chooses one fixed slot layout from the larger of the target
vocabulary size and the resolved initial vocabulary size. Counts through 65,535
use `AtomicU16`; counts through 16,777,215 use three contiguous atomic bytes;
larger counts retain `AtomicU32`. The all-ones code in each layout represents the
separator, and logical reads return complete `u32` IDs. Static dispatch chooses
the layout once for the complete training attempt, outside token loops.

The three-byte plane has one initialized guard slot. A scalar unaligned
four-byte read masks off the adjacent byte; even its final read remains inside
initialized storage. Stores require a joined phase without token readers.
Shared write entry points make that requirement explicit through an unsafe
contract; whole-word writers hold the mutable corpus borrow until they drop.
Rust permits synchronized atomic writes followed by non-atomic reads, as
specified in its [atomic memory model](https://doc.rust-lang.org/std/sync/atomic/index.html).

Live token IDs occupy both endpoints of their physical span. Merges update
endpoints without shifting word suffixes. Immutable separators prevent matches
across words.

A per-ID span table is sufficient while active IDs have one span. Before an ID
is reused for a different span, the corpus materializes per-occurrence spans.
Preparation then reads those spans; apply updates them after endpoint writes.

Initialization records cache a complete 64-bit pair key and a 32-bit wave-local
coordinate in twelve bytes. The key uses two `u32` fields to avoid alignment
padding. Adding the wave base restores the full-width global coordinate without
rereading the corpus. Stable grouping preserves position order within equal
keys. A wave contains at most `2^28` physical slots. All count owners sort
before installation starts. At most two owners install positions at once, and
each releases its raw record buffer before later owners allocate output.
Complete single-wave counts are filtered before one exact encoding per retained
key. Larger inputs build exact lists within each wave, then append those owned
lists into the accumulated table. They apply the global frequency floor after
accumulation.

Initial producers scan fixed tiles of `2^18` slots, independent of worker count.
Each tile retains counts and buffer references only for nonempty owner routes.
One wave therefore has at most 1,024 producer tiles. Increasing worker count
does not also multiply the producer count. Installation groups retain the record
range and frequency; their complete key remains in the first cached record.

Small position allocations use the same fixed size threshold throughout training;
larger buffers use the system allocator. Append reuses available capacity or
doubles its stream and restart capacities as needed. Replaced heap buffers free
immediately. Retired arena buffers leave with the complete training scope. No
separate construction arena or publication copy changes that lifetime.

`tk-collections` owns reusable storage mechanisms. It has no BPE identities,
word weights, candidate policies, or training pool.

| Collection | Contract |
|---|---|
| `SortedPositions` | Nondecreasing full-width coordinates, duplicates, range cursors, and append |
| `AllocationArena` | Small allocations live until the complete algorithm scope ends |
| `PositionBuffer` | Full-width coordinates with a shared high half until promotion |
| `PositionChains` | Bounded local links and full-width coordinates |
| `IdAccumulator` | Values allocated only for touched IDs; drain resets touched entries |
| `IdDirectory` | Transferable ID lookup storage without accumulated values or their allocations |
| `IntervalIndex` | Values compressed over equal adjacent intervals; cursors support sequential queries |
| `radix` | Stable key grouping with bounded scratch |

`SortedPositions` writes an absolute seed for each group of at most 128 values
and varint gaps for the rest. A range cursor skips at most 127 gaps before its
first requested value. Independent cursors share immutable bytes. Small inline
lists need no allocation. Larger lists borrow an arena or own a heap allocation;
this choice remains internal. Builders consume one sorted run or reverse chain.
Construction uses reusable encoding scratch. Append measures a replayable run,
then writes directly beyond the published prefix without a suffix buffer. It
publishes the new length only after successful replay, so a producer error or
panic preserves the old list.

`IdAccumulator::into_directory` releases every value allocation and returns a
clean directory that can serve another value type. Dense directory capacity is
bounded to 65,536 U32 entries (256 KiB); larger domains use sparse storage and
release that directory. Changing the domain or value type preserves full U32
IDs. Normal transfer resets touched entries; a forgotten drain requires a full
directory reset before ownership transfer. Preparation and commit retain only
the dense indices, never sparse maps, value vectors, or event buffers.

Position buffers and chain nodes share a private coordinate storage type. A
chain's low coordinate and local link occupy one item. A separate high plane
appears only when positions cross the shared high half.

Words are arranged by weight. The trainer retains the complete contiguous range
whose weight is one and checks that range before general interval queries.
Uniform initial weights multiply the occurrence count directly, and merge
preparation returns that constant weight without a lookup. Other initial groups
count equal-weight runs, and merge preparation uses a cached interval cursor
outside the unit-weight range.

## Identity activation and cohort ownership

Each call starts with a Fresh attempt, including nonempty affixes. Before
accepting a merge, the coordinator checks whether its canonical replacement ID
is already active. An existing but inactive reserved ID can activate once, in
its own batch. Only an active ID collision requires Reusable execution.

On that collision, the coordinator stops before consuming the candidate or
writing its batch. It releases the attempt's position lists, corpus, arena, and
scratch, then runs the same coordinator once with Reusable ownership from the
unchanged weighted words. Reconstructing the input restores cohorts and
intermediate births that Fresh pruning and fused batches omitted. An in-place
policy switch cannot recover them. Errors propagate directly; the Reusable
attempt never restarts.
Limited-alphabet selection runs once per call; reconstruction reuses its
retained characters, including the original frequency-tie choice. Both attempts
preserve complete IDs and choose the same slot layout bound. Affix inputs
keep their checked signed weight and edge-mass bounds before either attempt.

Fresh identities cannot reuse active output IDs. Such rules can share a batch
when no selected output affects another selected input. The engine filters stale
positions and combines final neighbor changes. Counts below the frequency floor
can retire permanently. Sharded queues expose their leaders to a global selector;
only the observed winner is repaired against its current count.

For reusable IDs, this engine keeps a signed count ledger and a separate position
cohort for each published birth event. The ledger stores only count bits; position
ownership stays in the candidate cohorts. Its zero and negative keys remain
available for later updates.
It selects one rule at a time. A stale position can still identify a word whose
current tokens now match after identity reuse. Words are deduplicated within a
cohort; distinct cohorts are never combined solely because their pair keys match.

Cohort selection uses one global heap. Repairing shard heads eagerly would
change mainline ordering when a signed negative count converts to an unsigned
candidate priority. Preparation also preserves intermediate births followed by
removals within one word, including `AA -> A`. The strict maximum-length gate
applies to each birth; initial pairs retain the mainline initialization behavior.

Both identity policies share corpus navigation, weight lookup, event storage,
count routing, position encoding, and phase joins. The policy difference stays
in preparation and candidate ownership. Fresh frequencies use checked `u64`
arithmetic. Training with reusable IDs requires word weights and total initial
edge mass to fit `i64`; each ledger subtraction and addition also checks its
signed bound in event order.

Commit receives the complete vocabulary ID domain from the coordinator.
Only owners with routed changes enter commit work; idle owners retain their
state and lazy priority repair. Producers route nonzero removals and nonempty
birth chains. A zero-weight birth
can still carry birth positions. Fresh job order and bucket ownership give
one sorted run with an already accumulated length, so encoding validates it in
one traversal. Cohort sources retain the general chain-order check and
merge when left and right births interleave.

## Costs and validation

Let `N` be the physical corpus slots, including separators; `W` the words; and
`E` the initial pair occurrences. Let `C` count decoded candidate positions,
`S` count tokens visited by whole-word scans, and `A` count corpus writes.
Let `H` count hash-table operations, `Q` count queue operations, and `K` be the
maximum queue size. Finally, let `M` be encoded position bytes and `G` be copied
bytes, including token strings and position-buffer growth.

Let `B` count input bytes and `L` count comparisons in interval and word-boundary
lookups. Corpus construction costs `O(B + W log W)`, including input scans and
word sorting. Stable radix grouping itself costs `O(E)` for fixed-width keys,
summed across waves. Weight accumulation also pays its lookup work. The remaining
work is `O(C + S + A + H + Q log K + M + G + L)`, with expected constant-time hash
lookups. An uncached interval query costs `O(log I)` for `I` intervals, and an
uncached word query costs `O(log W)`; cached sequential queries can avoid them.
These terms describe actual work; they do not assert linear training time.
Stale cohorts can increase `C`, identity reuse can increase `S`, and
lazy queue repair can increase `Q`.

For one merge batch, let `P` be workers, `D` producer chunks, `T` routed count
actions, `F` birth references, and `R` birth buckets, with `R <= 512` independent
of worker count. Routing and stable birth grouping take `O(P + D + T + F + PR)`
work and storage. Owners with at least two births use `R` resident counters and
temporarily hold both the input and exact output birth-reference vectors. Empty
producer/owner/bucket combinations allocate no directory entries and require no
cross-product scan. Each count-action reference uses two resident indices, and
each birth reference uses one. These actual-event costs replace the previous
producer/owner/bucket directory matrix and comparison sorting of birth buckets.

The original Word-based trainer removes tokens from vectors and moves the
remaining suffix after each removal. A word of initial length `n` can therefore
require `O(n^2)` token moves across its merges. Endpoint updates cost constant
work per accepted match. Cohort preparation can still scan affected words;
the endpoint layout removes suffix movement, not that semantic work.

On the supported 64-bit target, the main storage terms are:

| Component | Storage rule |
|---|---|
| Corpus IDs | `2N`, `3N`, or `4N` bytes by layout, plus one slot of capacity; the three-byte layout initializes that guard |
| Retained word boundaries | `8W` bytes; fresh training releases them after construction |
| Occurrence spans | `8N` bytes only when unequal-span identity reuse requires them |
| Initial records | `12E_wave` bytes, with `E_wave <= 2^28` |
| Installation groups | 16 bytes per vector capacity item, for at most two owners at once |
| Pair table | 32 bytes per raw bucket for the key, count, and position handle, plus hash-table controls |
| Reusable-ID ledger | 16 bytes per raw bucket for key and count bits; replaces the initial pair table while cohorts own positions |
| Fresh priorities | 16 bytes per queue capacity item |
| Cohort candidates | 32 bytes per queue capacity item, including the position handle |
| Position chains | 8 bytes per node with a shared high half; promotion adds a 4-byte high plane |

Building the reusable-ID ledger temporarily overlaps its new buckets with the
initial table being consumed. The smaller steady-state bucket size therefore
does not alone establish a lower initialization peak.

Weight intervals, vocabulary strings, worker scratch, and allocator metadata
add separate terms. A G128 position stream uses eight bytes per absolute seed
and one to ten bytes per remaining gap. Each multi-group allocation adds an
eight-byte restart offset per group and its header. Inline lists need no stream
allocation. Append capacities can exceed used stream and directory lengths.

Peak RSS is the maximum simultaneous resident state. Raw owner records retire
as installation advances, so their complete total need not coexist with the
complete position output. Heap buffers free individually; the scope arena keeps
small retired buffers until training ends. Arena backing already includes its
position allocations and must not be added to their payload totals again.
Reserved scratch capacity, resident pages, and allocator retention are different
quantities. Compare snapshots from the same phase and report the unaccounted
residual instead of adding independent component maxima.

Tests retain the original Word-based algorithm as a test-only oracle. They
compare rule-by-rule choices and final vocabularies and merges. An independently
recomputing greedy oracle checks fresh training. Public feed, model training,
full JSON reload, affix behavior, and isolated public thread controls cover the
entry points. Collection tests cover full coordinates, duplicate positions,
restart ranges, chain ordering, allocation lifetime, and failed publication.

## Coarse ablation experiments

Future ablations substitute a leaf implementation through its existing contract
in an external benchmark source snapshot. Production keeps one implementation.
Each variant must preserve vocabulary IDs, ordered merges, affix settings, and
occurrence ownership.

| Group | Substitution and interpretation |
|---|---|
| Indexed corpus | Compare the complete engine with the untouched Word-based trainer; this is a whole-algorithm comparison |
| Initial grouping | Use reference grouping with the same full keys, coordinates, weights, and global frequency floor |
| Batch preparation | Select one certified rule per round and preserve ordered neighbor events |
| Weight locality | Keep the corpus arrangement and replace interval queries with scalar queries; assess arrangement and query locality together |
| Position compression | Use flat positions with the same occurrence and birth cohort semantics |
| Allocation and scratch reuse | Use ordinary owned allocations and job-local encoding scratch; include allocation and retirement costs |

Start with the full implementation, one group removed at a time, and the
mainline reference. This requires `O(k)` variants for `k` groups. Add an
interaction experiment only when evidence identifies coupling. Record complete
time, stage time, peak RSS, and exact model output from immutable binaries under
matched inputs. Instrumented diagnostic runs provide attribution separately from
formal timing runs.

## Thread scaling and progress

Thread scaling uses the existing public controls:

```rust
tk_encode::parallelism::set_num_threads(worker_count);
tk_encode::parallelism::set_parallelism(true);
```

Training reads the controls once on entry and creates one private pool.
Disabling parallelism selects one worker. Initialization and merging use this
same pool, including the one-worker case.

Run each scaling sample in a fresh process with `1, 2, 4, ...` workers up to the
CPU quota. Keep input, trainer settings, and output identical. Report
`speedup(n) = T(1) / T(n)`, `efficiency(n) = speedup(n) / n`, throughput, and peak
RSS. Measure feed and training separately, and use diagnostic runs for finer
phase costs. Record affinity and quota because pool width does not describe
physical CPU availability. A four-worker comparison alone is not a scaling
curve.

Progress uses the existing `Indicatif`, `JsonLines`, and `Silent` formats.
Enabled renderers read coarse completion counters every 250 milliseconds and
show stage elapsed time during long jobs. Heartbeats do not advance completed
work. Known stages use actual slots, records, or published keys and may show a
smoothed stage ETA after a complete sampling interval.

Merge progress reports learned rules and the current and target vocabulary
sizes. Frequency limits can stop early, and reused identities need not increase
vocabulary size. Remaining merge work therefore has no fixed total or ETA.
`Silent` and `show_progress(false)` create no renderer or stage counters. Token
loops perform no progress clocks or locks. Enabled progress overhead belongs in
its own representative benchmark comparison.

The radix translation preserves its BSD notice and attribution to
[Radsort](https://github.com/clausecker/radsort), revision
`f69e816c3cd79d312cd67aea5b9cf1c338c1b371`, and the
[original paper](https://arxiv.org/abs/2607.05302).
