# Tokenizers BPE benchmarks

This repository compares BPE training implementations with exact vocabulary IDs
and ordered merges. The supported entry point is `python -m bench`. Python owns
input/build identities, process supervision and reports; one Rust runner measures
each source version through the `tk_train_v1` public API adapter.

For a portable four-build image, manual GitHub Actions, TOML corpus matrices,
three-round matrix medians, single-run RSS growth and generated figures, see
[Docker and Dedicated Server runs](docs/docker.md). The standard adapter follows
current HF main; `tk_train_pr2348` explicitly handles the historical Normalizer
signature. Sources and workloads are configurable independently.

## Run the Docker benchmark on another machine

The target machine needs Docker. Choose the unique image tag shown by the manual
[image workflow](https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks/actions/workflows/docker.yml).
The same image provides corpus preparation, the example config, all four compiled
runners and plotting dependencies. No repository clone or host Python is needed.
The GHCR package is public; pulling it requires no login.

```sh
IMAGE=ghcr.io/yikai-liao/tokenizers-bpe-benchmarks:latest
# Replace latest with run-<run-id>-<attempt> or an image digest for repeatable runs.
docker pull "$IMAGE"
mkdir -p data cache config results
docker run --rm --entrypoint cat "$IMAGE" \
  /opt/benchmark/experiments/dedicated-server.toml > config/suite.toml
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --mount type=bind,src="$PWD/data",dst=/data \
  --mount type=bind,src="$PWD/cache",dst=/cache \
  "$IMAGE" corpora --out /data --cache /cache --size-mib 4096
```

Preparation commands have network access and save corpora/cache onto the host.
The measurement command below disables networking and never downloads corpora.
This single command prepares English, Chinese and Code and creates the three
relative links used by the suite. The recommended default, `--size-mib 4096`, targets
**up to 4 GiB of UTF-8 text per corpus**, after decompression/filtering, rather than
compressed download bytes. Only required pinned shards download; source exhaustion
keeps a smaller usable corpus and records `source_exhausted` in
`data/corpora.json`. The 16 GiB RSS target is observed during training, not inferred
from text bytes. Growth stops at the available corpus and retains a partial curve
if the RSS target is not reached.

Use `--size-mib 513` for a quick 512 MiB matrix, or a smaller value for VPS checks.
For longer growth runs, increase `--size-mib`; `32769` supplies up to 32 GiB plus
a complete-line margin per corpus. Three full 4 GiB corpora can occupy about 12 GiB before download cache and nested
benchmark prefixes. Downloads verify pinned shard hashes. English uses Wikipedia; code preserves
indentation and selects the configured language extensions. Chinese uses the
same file for HF `Whitespace` (including punctuation splitting) and ByteLevel.
To prepare on a different machine from the rented server, copy `data/` and
`config/` with `rsync -a`, which preserves the relative links.

The [batch preparation plan](datasets/corpora.toml) can select other pinned dataset
manifests and per-corpus targets. Export it with `docker run --rm --entrypoint cat
"$IMAGE" /opt/benchmark/datasets/corpora.toml > config/corpora.toml`, edit it, mount
`config/` and pass `corpora --config /config/corpora.toml`. Relative manifest names
resolve beside the plan first, then from the image's bundled datasets.
The packaged English manifest covers all 41 Wikipedia shards, Chinese all six,
and Code the first 128 shards. If a source still runs out, provide a larger
distinct UTF-8 file or another pinned manifest. Do not repeat text to inflate size.
The container retains partial curves when the mounted corpus runs out.

Edit `config/suite.toml` to fit the server, then run from the directory containing
`data/`, `config/` and `results/`:

```sh
docker run --rm --network none \
  --user "$(id -u):$(id -g)" \
  --mount type=bind,src="$PWD/data",dst=/data,readonly \
  --mount type=bind,src="$PWD/config",dst=/config,readonly \
  --mount type=bind,src="$PWD/results",dst=/results \
  "$IMAGE"
```

Docker and the image workflow compile all four sources
with ordinary `cargo --release`, without `target-cpu=native`.

The [complete TOML example](experiments/dedicated-server.toml) tests code ByteLevel,
English ByteLevel, Chinese ByteLevel and Chinese Whitespace in that order:

| Setting | Example | Meaning |
| --- | --- | --- |
| `execution.workers` | `[1, 4, 8]` | Core counts for the matrix; both timing figures use these same runs |
| `execution.repetitions` | `3` | Median of three measured runs per combination |
| `execution.warmups` | `1` | One representative workload before the whole suite |
| `execution.timeout_seconds` | `0` | No timeout |
| `trainer.vocab_size` | `100000` | Target vocabulary; actual vocabulary/merges are recorded |
| `cases[].size_mib` | `512` | Main matrix input prefix per corpus |
| `growth.workers`, `growth.repetitions` | `8`, `1` | One run per input size for every algorithm/corpus |
| `growth.start_mib`, `growth.factor`, `growth.max_mib` | `512`, `1.5`, `32768` | Exponential raw-input prefix growth |
| `growth.rss_target_gib` | `16` | Soft target: keep the completed crossing point, then stop |
| `execution.max_process_rss_gib` | `48` | Separate safety guard; choose for the host and above the soft target |
| `execution.min_available_gib` | `2` | Minimum available host/cgroup memory |

`cases[].path` names the **container** path, for example `/data/code.txt`.
There is no Docker memory hard limit. Change input sizes, workers and RSS guards
to fit your host; the example assumes at least eight available physical cores
and enough memory to finish a step beyond the 16 GiB target.

Inspect the topology before choosing NUMA placement:

```sh
docker run --rm --entrypoint lscpu "$IMAGE" -e=CPU,CORE,SOCKET,NODE,ONLINE
docker run --rm --entrypoint numactl "$IMAGE" --hardware
```

The default picks one logical CPU per physical core, preferring one NUMA node.
For a node-local comparison, set `cpu_node = 0` inside the existing `[execution]`
table and replace the example's memory policy with:

```toml
[execution.numa]
policy = "bind"
nodes = [0]
```

For a separate cross-node experiment, choose an ordered `execution.cpu_set` from
the topology output, spanning both nodes without SMT siblings, and use
`policy = "interleave"`, `nodes = [0, 1]`. A run uses the first W CPUs in that
list. NUMA policies are checked before measurement; if Docker blocks the required
syscalls, use an appropriate seccomp profile or `--security-opt seccomp=unconfined`
for the controlled benchmark. Use a new results directory for each config or
NUMA policy. See [CPU affinity and NUMA details](docs/docker.md#run-cpu-affinity-and-numa).

Each completed run logs timings, peak RSS, elapsed time and approximate remaining
time. The container writes three English figures under `results/report/`:
`core-scaling`, `train-core-scaling` and `memory-growth`, each as 600 dpi PNG,
editable SVG and PDF. The first uses original input MiB per median Feed + Train
second; the second uses the same runs' Train time, excluding Feed. Each figure's
endpoint labels use paired speedups for its own timing stage. No separate 1 MiB
matrix runs. Throughput Y limits and both memory axes vary by corpus;
growth prefers distinct Feed strings' UTF-8 bytes on the x-axis. CSV tables include
absolute values and paired ratios against HF main at the same core count.
All jobs, model outputs, logs, sampled RSS, source/build identities and failed
attempts remain in `results/`; keep the whole directory. Repeat the exact command
to resume, or see [report regeneration and phase options](docs/docker.md).

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
library. For direct host runs, install uv and run `uv sync --all-extras` from this
repository. uv manages Python and project dependencies, including PyArrow and
plotting libraries; no manual venv setup is needed. The Docker flow above does
not require uv on the host.
The runner release profile uses fat LTO and one codegen unit.

```sh
# Run commands from this repository. A local checkout supplies both revisions.
uv run python -m bench lock --source /path/to/tokenizers --revision BASELINE_SHA \
  --lockfile locks/my-baseline/Cargo.lock
uv run python -m bench lock --source /path/to/tokenizers --revision CANDIDATE_SHA \
  --lockfile locks/my-candidate/Cargo.lock
uv run python -m bench build --source /path/to/tokenizers --revision BASELINE_SHA \
  --lockfile locks/my-baseline/Cargo.lock
uv run python -m bench build --source /path/to/tokenizers --revision CANDIDATE_SHA \
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

Some historical commits contain external links to experiment outputs. Revision
snapshots reject these links by default. For Best Multicore, pass
`--exclude-source-path benchmarks/bpe-suite/results` to **both** `lock` and
`build`, together with its full `--revision` and `--vendored-rayon`. This
explicitly omits the historical result subtree while preserving its training
sources and vendor. You can instead repeat `--exclude-source-path` for individual
tracked paths. Exclusions require a Git revision; the original commit/tree,
requested paths and every omitted archive entry (including link targets) are
recorded in build identity. Missing paths fail rather than silently changing the
snapshot. Retained external links remain rejected.

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
uv run python -m bench text --input /path/to/text.txt --manifest .bench/text.json
# Only core needs a preparation step. Select a validated build for preprocessing.
uv run python -m bench prepare-input --input /path/to/text.txt \
  --pretokenizer whitespace --build .bench/builds/BUILD_ID/build.json \
  --out .bench/words
```

Copy [pipeline-small.json](experiments/pipeline-small.json) or
[core-small.json](experiments/core-small.json), set both `arms.*.build` paths,
input manifest and the CPU set for your host, then run:

```sh
uv run python -m bench run --config experiments/my-experiment.json --out .bench/runs/my-experiment
uv run python -m bench report --out .bench/runs/my-experiment
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
uv run --extra corpus python -m bench corpus --dataset datasets/wikipedia-zh.json \
  --size-mib 512 --out .bench/inputs/zh512
uv run --extra corpus python -m bench corpus --dataset datasets/wikipedia-en.json \
  --size-mib 256 --out .bench/inputs/en256
uv run --extra corpus python -m bench corpus --dataset datasets/github-code-clean.json \
  --size-mib 512 --out .bench/inputs/code512
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
uv run python -m unittest discover -s tests -v
uv run python -m bench --help
```

CI runs supervision/protocol tests and a deterministic core/pipeline integration
smoke against a pinned source revision. Large-data performance matrices run on a
specified quiet machine, outside CI. Active modules never import the archive.

Local two-revision smoke command (after building both sources):

```sh
PYTHONPATH=. uv run python tests/integration.py --baseline /path/to/baseline/build.json \
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
