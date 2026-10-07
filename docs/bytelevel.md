# Regular Byte-level BPE comparisons

The matrix generator creates standard pipeline and core configurations for Chinese
and English text manifests, plain vocabulary targets 32,000 / 50,000 / 65,536, and
workers 1 / 4 / 8. Each language also has one representative combined-affix case
at 32,000, with prefix `##` and suffix `</w>`. Each cell uses one warmup and three
balanced alternating measurement
blocks, with exact vocabulary-ID and ordered-merge comparison. Multiple comparison
arms share one baseline attempt in each block.

The 32k and 50k targets exercise the trainer's narrow mutable slot domain. The
65,536 target exercises the wider slot selection boundary, even when a small input
cannot reach the requested vocabulary size. Always check the reported actual
vocabulary and merge count when interpreting a target-size result.

## Generate plans

Run from the repository root, supplying existing canonical text manifests and
build records. A build argument may name `build.json` or its containing directory.

```sh
python -m scripts.prepare_bytelevel_matrix \
  --baseline .bench/builds/BASELINE/build.json \
  --candidate .bench/builds/CANDIDATE/build.json \
  --zh-manifest .bench/corpora/zh/manifest.json \
  --en-manifest .bench/corpora/en/manifest.json \
  --out .bench/bytelevel-comparison
```

This writes `pipeline.json` and `core.json`. Default generation reads small
manifest/build JSON records, checks their metadata identities, and validates the
plans with the existing benchmark schema. It does not read corpus contents,
validate build binaries, preprocess input, compile, or run measurements. The
canonical run validates full input/build content before executing any attempt.

The default CPU set is the first eight CPUs in the process's allowed affinity.
Use `--cpu-set` to select a consistent explicit set. On a smaller machine, specify
the available worker counts, for example `--workers 1 4`. Worker counts must fit
the CPU set. Resource limits can be set with `--timeout-seconds`,
`--min-available-gib`, and `--max-process-rss-gib`.

`--affixes both` is the default. `--affixes all` adds prefix-only and suffix-only
cases alongside the combined case; `--affixes none` emits only the plain matrix.
Affix cases use the first value of `--vocab-sizes`, so `--vocab-sizes 50000` puts
the representative affix comparison at 50k without multiplying every target by
every affix profile. All profiles share the same prepared input per language;
the affixes are applied by the actual trainer in each attempt.

For additional candidates, repeat `--arm NAME=BUILD`:

```sh
python -m scripts.prepare_bytelevel_matrix \
  --baseline .bench/builds/BASELINE \
  --arm consume-cache=.bench/builds/CONSUME_CACHE \
  --arm feed-startup=.bench/builds/FEED_STARTUP \
  --zh-manifest .bench/corpora/zh/manifest.json \
  --en-manifest .bench/corpora/en/manifest.json \
  --out .bench/bytelevel-multiarm
```

Repeating an identical generation preserves the files. A changed configuration
requires a new output directory, keeping existing run plans intact. Original
text manifests and build records are referenced by absolute path and remain
unchanged; no revision or input identity is substituted.

## Prepare core inputs explicitly

`core.json` refers to one shared prepared word-count manifest per language under
`inputs/zh-bytelevel/` and `inputs/en-bytelevel/`. To create those inputs, repeat
the same generation command with `--prepare-core`. This explicitly verifies the
raw text and calls the canonical preparation workflow with the baseline runner.
Preparation can read the entire corpus and consume substantial memory; schedule
it separately from active performance measurements.

Prepared inputs retain the raw content hash, baseline preparer build ID,
pretokenizer recipe, and prepared-word content identity. All vocabulary targets
and all comparison arms use that same language-specific input. Core preparation
does not train a model, and the generator never starts a timed run.

## Preprocessing and timing boundaries

The generator sets `pretokenizer: bytelevel_regex` and delegates processing to the
existing runner adapter. For each input line, the runner removes LF and optional
CR while preserving other whitespace. It then applies the repository's GPT-2
regex with isolated delimiters and maps each resulting piece through the
repository ByteLevel normalizer. It adds no prefix space. The trainer starts with
the complete 256-character ByteLevel alphabet. No regex or byte mapping is copied
into the generator.

Pipeline uses the actual public feed callback for that processing, followed by
training. It never loads prepared word counts. Core loads the shared verified
prepared counts before training timing, then calls the public training API.
Both modes serialize and compare models after the measurement boundary. The
matrix uses minimum frequency 2 and leaves maximum token length unset; the plain
cases leave affixes unset. The existing integration smoke exercises length gates,
empty input, mixed Unicode, and ByteLevel core/pipeline model parity separately.

The forced alphabet contains 256 base ByteLevel characters. Nonempty affixes can
create additional initial token identities: a character can appear with or
without a continuation prefix and with or without the final suffix. With distinct
`##` / `</w>` strings, prefix-only or suffix-only configurations can produce up
to 512 identities; the combined configuration can produce up to 1,024. Actual
counts depend on observed token positions, filtering, and identity aliases.
Check both the number of emitted initial identities and their numeric ID range
when evaluating a narrow symbol representation. A 256-character base alphabet
does not prove that all emitted IDs fit in eight bits. These affix cases exercise
the trainer with the existing initial-alphabet configuration; the generator does
not change the canonical runner's alphabet or preprocessing.

## Run and inspect results

After input preparation and when the performance machine is available, use the
existing entry point:

```sh
python -m bench run --config .bench/bytelevel-comparison/pipeline.json \
  --out .bench/bytelevel-comparison/pipeline-run
python -m bench run --config .bench/bytelevel-comparison/core.json \
  --out .bench/bytelevel-comparison/core-run
```

Reports are under each run's `report/` directory. `REPORT.md` gives the primary
paired wall-time ratios, while `summary.json` and `comparisons.csv` expose
`feed_seconds`, `train_seconds`, `pipeline_seconds`, and memory metrics per
case/worker/arm. Ratios are candidate divided by baseline within each complete
paired block; a smaller wall-time ratio means a faster candidate. Inspect the
separate Feed and Train metrics when attributing a pipeline change.

`process_hwm_kib_before_validation` includes process startup and input loading
through the boundary before serialization/model validation; it is not a
training-only allocation peak. `sampled_peak_rss_bytes` covers the entire child
process and can include validation. Use the same metric and mode for all arms.
The overall high-water mark may be set by an earlier stage even when an
optimization reduces memory in a later stage.

Treat the default three paired blocks as a screening matrix. Require passed
exact-model comparisons, complete same-session blocks, and
`performance_conclusion_valid` before drawing a performance conclusion. Use the
standard run/report workflow for additional measurement blocks when the observed
differences need more evidence.
