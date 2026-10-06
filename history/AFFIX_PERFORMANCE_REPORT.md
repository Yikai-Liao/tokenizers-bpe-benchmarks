# BPE affix performance on the current HF cohort path

## Scope and method

This measures the public `BpeTrainer.feed(...).train_vocab()` route in the clean `c9af0cf2e5d81b89147f555d6d9693f504aab1dc` source. Only copied source under `benchmarks/hf-bpe/.build/native-affix-analysis*/` was instrumented; the source worktree stayed clean. The build inserts one branch that calls the original `do_train_observed` greedy trainer when `HF_BPE_ORACLE=1`, captures `IndexedTrainingStats`, and counts cohort-scanning work. The native runner uses a serial feed with fixed AHash seeds `(11, 13, 17, 19)`, vocabulary 30,000 for 1/16 MiB and 50,000 for 512 MiB, minimum frequency 2, and `split=none`.

Each native run has `.environment.json`, `.stdout`, `.stderr`, and `.jsonl` artifacts under `results/affix-analysis/`. Records preserve input and binary SHA256, command and overrides, memory checks, and host/resource diagnostics; the newer isolated builds also link an immutable build manifest. Input-manifest data is present only for runs whose input directory supplies it. All completed calls had sampled process VmSwap=0 and stayed above the 1 GiB available-memory stop threshold. Results are single runs, so treat small timing differences as descriptive.

## Results

`train_ms` is the runner's train interval after feed. The one-thread no-affix rows are the fair fallback comparison for affixes. The corrected four-thread no-affix rows show the ordinary parallel path. The 512 MiB no-affix run is four-thread; the affix fallback is serial and did not finish before its 180-second wall cap.

| Input | Configuration | Train time | Initialization | Merge | Layout / workers | Peak RSS |
|---|---|---:|---:|---:|---|---:|
| EN 1 MiB | none | 0.474 s | 0.048 s | 0.399 s | `parallel_u32_flat32`, 1 | 0.02 GiB |
| EN 1 MiB | `##` | 0.773 s | 0.177 s | 0.504 s | `hf_cohorts`, serial | 0.04 GiB |
| EN 1 MiB | `</w>` | 0.697 s | 0.109 s | 0.520 s | `hf_cohorts`, serial | 0.04 GiB |
| EN 1 MiB | both | 0.767 s | 0.173 s | 0.518 s | `hf_cohorts`, serial | 0.04 GiB |
| EN 16 MiB | none, 1 thread | 4.435 s | 0.729 s | 3.671 s | `parallel_u32_flat32`, 1 | 0.25 GiB |
| EN 16 MiB | `##`, 1 thread | 8.672 s | 2.509 s | 5.851 s | `hf_cohorts`, serial | 0.39 GiB |
| EN 16 MiB | `</w>`, 1 thread | 7.660 s | 1.533 s | 5.809 s | `hf_cohorts`, serial | 0.40 GiB |
| EN 16 MiB | both, 1 thread | 8.462 s | 2.513 s | 5.611 s | `hf_cohorts`, serial | 0.39 GiB |
| EN 16 MiB | U+E000 prefix, absent from input | 8.794 s | 2.513 s | 5.944 s | `hf_cohorts`, serial | 0.40 GiB |
| EN 16 MiB | U+E000 prefix + U+E001 suffix, both absent | 8.891 s | 2.580 s | 6.024 s | `hf_cohorts`, serial | 0.39 GiB |
| EN 16 MiB | none, 4 threads | 2.008 s | 0.294 s | 1.678 s | `parallel_u32_flat32`, 4 | 0.27 GiB |
| ZH 16 MiB | none, 1 thread | 1.594 s | 0.414 s | 1.153 s | `parallel_u32_flat32`, 1 | 0.14 GiB |
| ZH 16 MiB | `##`, 1 thread | 4.614 s | 2.354 s | 1.776 s | `hf_cohorts`, serial | 0.31 GiB |
| ZH 16 MiB | `</w>`, 1 thread | 4.536 s | 1.676 s | 2.268 s | `hf_cohorts`, serial | 0.33 GiB |
| ZH 16 MiB | both, 1 thread | 4.639 s | 2.289 s | 1.856 s | `hf_cohorts`, serial | 0.29 GiB |
| ZH 16 MiB | none, 4 threads | 0.890 s | 0.172 s | 0.689 s | `parallel_u32_flat32`, 4 | 0.14 GiB |
| ZH 512 MiB | none, 4 threads, vocab 50k | 24.375 s | 5.985 s | 17.831 s | `parallel_u32_flat32`, 4 | 3.27 GiB |
| ZH 512 MiB | `</w>`, 1 thread, vocab 50k | did not finish by 180 s wall cap | — | — | `hf_cohorts`, serial | 3.36 GiB sampled |

The one-thread EN16 affix cases took 1.73–1.95× the one-thread no-affix time. The one-thread ZH16 affix cases took 2.85–2.91×. At 512 MiB the no-affix four-thread run finished; the suffix run was stopped by the cap. The suffix record is an incomplete 180.38-second wall timeout that includes feed and process overhead; it has no exact training duration or completed model SHA. The timeout record contains 174.35 child user seconds and 4.97 child system seconds, with process VmSwap=0 and minimum available memory 3.80 GiB.

## General-path candidate v1 comparison

The candidate at `d7d67475bd858f6eeddffc528a792acd9ee51349` retained exact model SHA256 parity with the baseline for all six 16 MiB affix cases. Its affix dispatch used one worker in each case. The comparison below puts the candidate affix run next to the baseline's one-thread and four-thread no-affix runs on the same input; the four-thread column makes the remaining serial-dispatch gap visible.

| Input | Affix | Candidate affix train (workers) | Baseline none, 1 thread | Affix / none-1 | Baseline none, 4 threads | Affix / none-4 | Model SHA matches |
|---|---|---:|---:|---:|---:|---:|:---:|
| EN 16 MiB | `##` | 6.285 s (1) | 4.435 s | 1.42× | 2.008 s | 3.13× | yes |
| EN 16 MiB | `</w>` | 6.500 s (1) | 4.435 s | 1.47× | 2.008 s | 3.24× | yes |
| EN 16 MiB | both | 6.219 s (1) | 4.435 s | 1.40× | 2.008 s | 3.10× | yes |
| ZH 16 MiB | `##` | 2.524 s (1) | 1.594 s | 1.58× | 0.890 s | 2.84× | yes |
| ZH 16 MiB | `</w>` | 2.850 s (1) | 1.594 s | 1.79× | 0.890 s | 3.20× | yes |
| ZH 16 MiB | both | 2.647 s (1) | 1.594 s | 1.66× | 0.890 s | 2.97× | yes |

The no-affix controls use the verified four-thread row names `en16m-none-workers4` and `zh16m-none-workers4`. An earlier artifact named `en16m-none-t4` actually ran one worker and is excluded. A candidate no-affix four-thread rerun against a clean `48223a5898a144874f6b48e3b437fd3ce75adb08` baseline produced the same model SHA and worker/layout stats on both sides; train intervals were 2.299 s baseline and 2.176 s candidate, while harness wall times were both 2.511 s. This single pair does not establish a reliable no-affix speed change.

The 512 MiB candidate suffix run also stopped at the 180 second cap: wall time 180.56 s, sampled peak RSS 4.91 GiB, minimum available memory 2.55 GiB, one process thread, and process VmSwap 0. The earlier frozen baseline suffix run also timed out and peaked at 3.36 GiB RSS, so v1's higher sampled memory makes its large-input arena allocation policy unsuitable. The host-wide page-out counter changed during the v1 run, so the process-level VmSwap reading is the relevant per-run measure; no claim is made that the host performed no paging.

An alias/reuse correctness fixture with input bytes `baaba` (no trailing newline), suffix `a`, vocabulary 10, and minimum frequency 1 produced identical model SHA256 values on the candidate, frozen baseline, and original greedy HF oracle. Candidate counters recorded `reused_ids=2`, `cohort_scan_activations=4`, `cohort_words_scanned=4`, and `word_scan_steps=9`. A newline changes this fixture's token and does not activate the same condition; that exploratory run is retained separately and is not part of the correctness check.

The next general-path candidate parallelized word-local cohort rewriting, retained the non-monotone ledger semantics, and used stable radix initialization with System posting allocation. Its six-case EN16/ZH16 affix matrix, active-alias parallel correctness case, and 512 MiB comparison are recorded in [the v2 summary](AFFIX_PARALLEL_V2_SUMMARY.md). All six short affix cases retained exact baseline and v1 model hashes. Affix4 was 2.01–2.34× slower than same-source none4. The 512 MiB suffix case completed in 91.4 seconds but used 5.10 GiB peak RSS, above both the v1 4.91 GiB record and the old 3.36 GiB suffix timeout record; the requested thread counts differ, so these RSS values are not direct thread-matched comparisons. The old affix timeout has no model SHA for a full-size parity check.

## What the counters show

The no-affix path selected `parallel_u32_flat32`; affixes selected `hf_cohorts`. `monotone_pairs=true` on the no-affix cases and `false` in the affix fallback, so the affix run retains HF's general count and cohort semantics rather than using the no-affix retirement rule. The `workers=0` and `initialization_workers=0` values printed in affix `IndexedTrainingStats` are default, unfilled fields. Source dispatch calls `do_train_indexed()` directly on this route, whose training loop is serial. The run environment also caps Rayon at one thread. Do not read those stats zeros as zero active work.

The EN16 MiB affix runs each visited roughly 24.4 million postings; about 11.0 million were stale. The ZH16 MiB prefix run visited 3.13 million postings (0.70 million stale); suffix visited 3.66 million (0.92 million stale). No span-reuse scan was observed in these EN/ZH16 runs (`reused_ids=0`, `word_scan_steps=0`, and the added cohort-scan counters are zero). This corpus result does not imply that a maximum token length is required for scanning: an active reused ID can also make the cohort scan necessary. `initial_edges` counts adjacent pair-position edges processed by initial pair counting; it is not a count of character probes. These measurements point first to affix-path initialization and general ledger/posting work, with stale occurrence handling as a large merge-stage cost.

## Exactness check

On the same 63,767-byte English fixture, the instrumented public fast route and the original HF greedy `do_train_observed` route produced identical vocabulary-and-ordered-merges hashes for no affix, prefix `##`, suffix `</w>`, and both affixes (4/4 exact SHA256 matches). The checks establish parity for these tested settings and fixture; they do not replace the existing broader test suite.

## Input and build identity

The English inputs are the existing benchmark inputs with hashes recorded next to each copy. The ZH16 input is the whole-line prefix below 16 MiB from the exact 536,870,289-byte ZH512 input, SHA256 `ebd64699a917bb0982e9b64d302d94cc08057f43d16bcb5efc041594684c12a6`. ZH512 is the original `wikimedia/wikipedia` snapshot described by `.build/gb-corpus/manifest.json`, SHA256 `a0d40d4102cba1e933f25e5ccd17552d2eaebaec4ef770bc39d8e46e740b4d4f`.

The first frozen runner binary had SHA256 `7824be6f26f5eeef143cdb21d9c90a260aa37c92c379a05ba26580ccfd223038`; later I mistakenly rebuilt over its path while correcting the worker setup. Per-run metadata retains the exact binary hash observed for each invocation, and the later worker-four build has its own label and hash. The original `7824…3038` executable is no longer present, so those early records retain source/command/hash provenance but cannot be rerun from the current build directory. Do not combine those records with the later build's results as if they shared a binary. The true four-thread EN/ZH16 controls and the 512 MiB no-affix measurement use the separate `affix-analysis-workers4` build.

## Implemented optimization stages and next measurement

The first candidate tested several general mechanisms while preserving HF affix semantics:

1. During initial pair counting, combine each pair's frequency and posting owner in one hash-map entry. The baseline visits each adjacent pair-position edge; combining the two per-edge map lookups can remove a repeated lookup without skipping edges.
2. Store short postings inline and spill larger ones into a reusable arena, reducing per-cohort vector allocation overhead.
3. Cache decorated-character IDs. Passing an already-known cohort weight can remove a weight lookup, but it does not remove the posting-position-to-word conversion or word-ID sort/dedup. A separate word-range cursor could reduce that conversion/sort work if cohort ordering proves sufficient.
4. Keep span metadata lazy; allocate it only after observing a replacement ID whose physical occurrences have genuinely different payload spans. Continue using the general ledger and cohort semantics for affixes.

The v1 report above records a serial intermediate candidate. The v2 report shows that parallel word-local rewrites and parallel initialization preserved alias behavior and improved the short affix cases, while small-posting and queue costs remain material, especially for ZH. A subsequent candidate collects the remaining portable initialization, weight-layout, small-posting, scratch, scheduling, and queue changes behind private benchmark-only switches for one unified ablation. Its public-entry narrow-corpus setting was corrected before any measurement; the superseded build is marked `cancelled_no_native` and has no benchmark cases.
