# Tokenizers BPE benchmarks

This repository compares BPE training implementations with exact vocabulary IDs
and ordered merges. The supported entry point is `python -m bench`. Python owns
input/build identities, process supervision and reports; one Rust runner measures
each source version through the `tk_train_v1` public API adapter.

## Measurement boundaries

| Mode | Input | Main wall-time metric | Public calls |
| --- | --- | --- | --- |
| `core` | Verified prepared weighted words | `train_seconds` | `BpeTrainer::do_train` |
| `pipeline` | Verified UTF-8 text, consumed lazily | `pipeline_seconds`, with separate Feed/Train times | `Trainer::feed`, then `train_vocab` |

Core loading and map reconstruction happen before training timing. Preparation
uses the same repository pretokenizers as pipeline, lexical insertion order and
caller-map AHash seeds `[11, 13, 17, 19]`; internal trainer maps use native seeds.
Pipeline never uses prepared word-count caches. Both modes serialize and compare
models after timing. Preprocessing names are `none`, `whitespace` (repository
regex Whitespace), `whitespace_split`, and `bytelevel_regex` (GPT-2 regex isolated
splits followed by repository byte mapping, no added prefix space). Input removes
line endings in both modes; other whitespace is preserved.

The runner supports prefix, suffix, minimum frequency, vocabulary target and
maximum token length. Unsupported adapter/API shapes fail explicitly at build
or protocol validation. Special-token configuration and preloaded-input timing
are outside version 1. Exact comparison may fail for configurations with unstable
initial ID assignment: that is a correctness finding, never a reason to renumber
IDs or sort merges.

## Build two revisions

Requirements: Linux with `/proc`, `taskset`, `lscpu`, Python 3.11.8+, Git and a Rust
compiler supporting the selected source. Python supervision uses only the standard
library. Corpus preparation additionally uses PyArrow (`uv pip install -e '.[corpus]'`).
The runner release profile uses fat LTO and one codegen unit.

```sh
# Run commands from this repository. A local checkout supplies both revisions.
python -m bench lock --source /path/to/tokenizers --revision BASELINE_SHA \
  --lockfile locks/my-baseline/Cargo.lock
python -m bench lock --source /path/to/tokenizers --revision CANDIDATE_SHA \
  --lockfile locks/my-candidate/Cargo.lock
python -m bench build --source /path/to/tokenizers --revision BASELINE_SHA \
  --lockfile locks/my-baseline/Cargo.lock
python -m bench build --source /path/to/tokenizers --revision CANDIDATE_SHA \
  --lockfile locks/my-candidate/Cargo.lock
```

Each build prints its `.bench/builds/<build-id>/build.json`. `lock` explicitly
resolves a new **runner** lock profile; `build` always uses `--locked`. The supplied
`locks/tk-train-v1/Cargo.lock` supports the upstream API baseline; source versions
with a different dependency graph need a separately named profile. Preserve each
actual runner lock when publishing. `--revision` snapshots a resolved commit;
omitting it snapshots the complete local tracked and nonignored file set,
including dirty edits, which is recorded in provenance. Internal file symlinks
are materialized; external symlinks and local Cargo path dependencies outside the snapshot are rejected. No automatic porting of
BPE code into another source tree is performed.

Build identity covers the source snapshot (including manifests, locks, build
scripts, other local crates and vendor), runner/adapter, generated manifest and
runner lock, compiler/Cargo, flags, explicit environment, user/ancestor Cargo
configuration, file permissions, CPU data, and artifact
hash. Native compilation is opt-in with `--rustflags '-C target-cpu=native'`.
Link or compiler overrides use a JSON map passed with `--build-env`; they are
recorded. The build directory retains sources, dependency metadata and verbose compilation
commands for inspection. An artifact-copy lock protects the shared Cargo target.
Partial builds have no usable `build.json` and cannot be cache hits.

These commands use each version's actual dependency graph. A controlled-common
lock experiment is a separate choice: select the identical compatible runner lock
for both arms and record that choice in the experiment name. For the historical
Best Multicore source, use `--vendored-rayon` only with its preserved source and
lock profile; record its retained algorithm/idle-policy environment in that arm's
configuration. [Historical wrapper and settings](archive/2026-10-experiments/bpe-suite/with_multicore_candidate.sh)
are preserved for this purpose.

## Identify input and run

```sh
python -m bench text --input /path/to/text.txt --manifest .bench/text.json
# Only core needs a preparation step. Select a validated build for preprocessing.
python -m bench prepare-input --input /path/to/text.txt \
  --pretokenizer whitespace --build .bench/builds/BUILD_ID/build.json \
  --out .bench/words
```

Copy [pipeline-small.json](experiments/pipeline-small.json) or
[core-small.json](experiments/core-small.json), set both `arms.*.build` paths,
input manifest and the CPU set for your host, then run:

```sh
python -m bench run --config experiments/my-experiment.json --out .bench/runs/my-experiment
python -m bench report --out .bench/runs/my-experiment
```

Paths in configurations resolve relative to the configuration file. A worker count
must fit a nonempty unique CPU set within the supervisor affinity. The first W CPUs
are assigned to a W-worker cell. `environment.json` records CPU/core/socket/NUMA
topology: choose distinct physical cores for physical-core scaling; label SMT
experiments separately. [scaling.json](experiments/scaling.json) uses the same run
and resume path.

The immutable `spec.json` binds effective defaults, source/build/input identities,
comparator/protocol/supervisor versions, machine/topology, CPU allocation and
recorded child environments. Changed content at the same path, changed binaries,
trainer settings, workers or CPU allocation require a new output directory.
Moving files alone does not alter semantic input/build identity. At every resume,
input and build contents are reverified. Child environment comes from a small
system allowlist plus each arm's explicit settings; inherited TK caches,
allocator and thread overrides are removed. Word-count cache overrides are also
rejected if explicitly requested.

Each process has a unique attempt directory, logs, job, result and full model.
An exclusive writer lock prevents simultaneous supervisors. Warmups and paired
blocks are fixed in advance; two-arm AB/BA and multi-arm rotation are recorded.
Timeout, resource guard, crash, invalid protocol, signal and model mismatch all
produce retained terminal records. A killed process is reported as a process
failure, without guessing OOM. Resume marks orphaned running attempts interrupted
and stops their still-matching process groups. Failed slots require explicit
`--retry-failed`; the retry receives a new ID. An experiment that ever recorded a
model mismatch remains `correctness_failed`, even after successful retries.

Reports scan **all attempts**, including failures without a complete block. Only
complete valid blocks enter paired statistics. Reports include attempted,
complete, expected and excluded block counts, raw metrics, candidate/baseline
within-block ratios, observed ranges, and each arm's T1/Tp and efficiency (ratio
of wall-time medians). Process HWM is measured before validation and includes
startup/loading; supervisor sampled RSS includes serialization. Neither is an
incremental training allocation metric. Sampling is every 20 ms, so short peaks
can be missed. Small smoke measurements test the workflow, not performance.

## Pinned Wikipedia and published evidence

[Dataset manifests](datasets/README.md) pin Wikipedia revision and expected shard
hashes. Existing cache hits are checked against expected content, including after
same-size replacement. Preparation keeps shard/article order, normalizes paragraph
whitespace and filters 32–8192 UTF-8 bytes. Smaller sizes are nested ordered
prefixes, not independent random samples.

```sh
python -m bench corpus --dataset datasets/wikipedia-zh.json \
  --size-mib 512 --out .bench/inputs/zh512
python -m bench corpus --dataset datasets/wikipedia-en.json \
  --size-mib 256 --out .bench/inputs/en256
```

`results/` is reserved for selected experiments produced by the new protocol;
no historical result is relabeled as a new-protocol performance measurement. Publish
`spec`, environment, build provenance with retrievable source snapshots/locks,
all attempt records/logs, canonical model references, and the generated report.
Do not publish only a summary, or claim a new source revision was measured by an
old result. Local raw text, build caches and working experiments stay in `.bench/`.

[The archived evidence index](archive/2026-10-experiments/README.md) preserves the
2026-10 experiments and conclusions under their original protocol. Their common
serial frontend is `common_serial_frontend`, not public Feed. Public Feed and
joint measurements have their recorded boundaries. These records have **not**
been retroactively certified by the new protocol. The retained performance
control is Best Multicore `57c04ca9ed1e843f6e36fe68ed3ae5adf499936c`; the non-Feed
simplification pushed during this work is `d857cfeecc659449550c6f5ff37438c6d0ebffd5`.
[Source snapshots](source-snapshots/manifest.json) preserve precise historic source
identities. A moving candidate branch is not a substitute for either SHA.

## Validation

```sh
python -m unittest discover -s tests -v
python -m bench --help
```

CI runs supervision/protocol tests and a deterministic core/pipeline integration
smoke against a pinned source revision. Large-data performance matrices run on a
specified quiet machine, outside CI. Active modules never import the archive.

Local two-revision smoke command (after building both sources):

```sh
PYTHONPATH=. python tests/integration.py --baseline /path/to/baseline/build.json \
  --candidate /path/to/candidate/build.json --out .bench/two-revision-smoke
```

The smoke compares 1/2 workers and four preprocessing definitions in both modes,
checks core/pipeline equivalence and immutable resume, and exercises affixes with
a single-character fixture. Multi-character affix initialization can assign
unstable IDs even across repeated upstream runs; exact-model experiments retain
that mismatch and reject performance conclusions instead of relaxing comparison.

[Published protocol validation](results/protocol-smoke-20261006/VALIDATION.md) records
15 passing supervision tests and 112 passing native two-revision process runs.
The preliminary affix mismatch is retained alongside it.
