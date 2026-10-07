# Docker benchmarks on a Dedicated Server

The image contains the general benchmark harness, four independently compiled
Rust runners, corpus preparation and plotting dependencies. The host needs Docker;
no repository clone or host Python environment is required. Separate preparation
containers download UTF-8 corpora onto mounted host directories. Measurement is
offline: mount those corpora, a TOML config and a writable results directory.

[The example configuration](../experiments/dedicated-server.toml) uses a target
vocabulary size of 100,000. Actual vocabulary and merge counts remain in each result.

| Panel order | Corpus | Pretokenizer | Matrix input | Physical cores | Measured runs |
| --- | --- | --- | ---: | --- | ---: |
| a | Multilingual code | GPT-2 ByteLevel | 512 MiB | 1, 4, 8 | 3 |
| b | English | GPT-2 ByteLevel | 512 MiB | 1, 4, 8 | 3 |
| c | Chinese | GPT-2 ByteLevel | 512 MiB | 1, 4, 8 | 3 |
| d | Chinese | HF `Whitespace` | 512 MiB | 1, 4, 8 | 3 |

`Whitespace` follows the Unicode-aware `\w+|[^\w\s]+` rule: punctuation is
separated from text, including Chinese punctuation. Consecutive punctuation is
one group and consecutive Chinese characters remain one text span. This is not
`WhitespaceSplit`, which only splits on whitespace, or external Chinese word
segmentation. The two Chinese modes read the same file. ByteLevel uses the GPT-2
regex and byte-to-Unicode mapping, with no added prefix space.

All four corpora and all four algorithms also undergo memory growth at 8 cores.
Each size runs **once**. The raw input prefix grows exponentially until a completed
run reaches or crosses the configured soft RSS target (16 GiB in the example),
or the available corpus/configured maximum runs out. The crossing run finishes;
there is no refinement or bisection. MiB/GiB are binary units and prefixes end at
complete lines, so actual bytes can be slightly below their requested size.

## Build or obtain the image

The **Build benchmark Docker image** GitHub Action is manual-only
(`workflow_dispatch`). Once on the default branch, choose Actions → Build benchmark
Docker image → Run workflow. It builds Linux amd64, checks all four implementations
and figures, then publishes `ghcr.io/<owner>/<repository>:run-<run-id>-<attempt>`
and the requested tag (default `latest`). Use the unique tag/digest on a rented
server. Source revisions and
validation results are uploaded as workflow artifacts.

```sh
IMAGE=ghcr.io/yikai-liao/tokenizers-bpe-benchmarks:latest
# Prefer run-<run-id>-<attempt> or a digest from the completed workflow.
docker pull "$IMAGE"
```

A private GHCR package requires `docker login ghcr.io` with a token permitted to
read packages before pulling. The local build below is for harness developers;
benchmark servers can use the published image directly.

[The source manifest](../docker/sources.toml) selects:

| Build | Repository | Ref | Adapter |
| --- | --- | --- | --- |
| `hf-main` (baseline) | huggingface/tokenizers | `refs/heads/main` | `tk_train_v1` |
| `hf-pr2348` | huggingface/tokenizers | `refs/pull/2348/head` | `tk_train_pr2348` |
| `fork-main` | Yikai-Liao/tokenizers | `refs/heads/main` | `tk_train_v1` |
| `fork-yttm` | Yikai-Liao/tokenizers | `refs/heads/bpe/yttm-rust-reference` | `tk_train_v1` |

Every manual build resolves refs before compilation and retains exact source SHAs,
source snapshots, generated runner locks, compiler/flags, dependency metadata,
logs and binary hashes in `/opt/builds`. A source failure fails the build. Moving
refs cannot change an existing image. The historical PR adapter only adapts its
ByteLevel normalizer call; training remains each checkout's original implementation.

The harness accepts other source manifests and compatible builds. Copy/edit a
TOML under `docker/`, choose `baseline` and `[[sources]]`, and set its path in the
action. Unsupported source APIs fail compilation. Docker and GitHub Action builds
use ordinary `cargo --release`, without `target-cpu=native`. The Docker build
rejects custom Rust flags in source manifests, including encoded flags.

```sh
docker build -f docker/Dockerfile -t bpe-bench:local .
docker run --rm --entrypoint cat bpe-bench:local /opt/builds/bundle.json
```

For direct host execution, clone the repository and use uv instead of manually
creating a venv. Git, a suitable Rust compiler and Linux CPU/NUMA tools are also
required:

```sh
git clone https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks.git
cd tokenizers-bpe-benchmarks
uv sync --all-extras
mkdir -p data cache config results
cp experiments/dedicated-server.toml config/suite.toml
uv run python -m bench bundle --portable-release --config docker/sources.toml \
  --out .bench/bundle --cache .bench/builds
uv run --extra corpus python -m bench corpus --dataset datasets/wikipedia-en.json \
  --size-mib 513 --out data/en --cache cache
uv run --extra corpus python -m bench corpus --dataset datasets/wikipedia-zh.json \
  --size-mib 513 --out data/zh --cache cache
uv run --extra corpus python -m bench corpus --dataset datasets/github-code-clean.json \
  --size-mib 513 --out data/code --cache cache
ln -s en/text.txt data/en.txt
ln -s zh/text.txt data/zh.txt
ln -s code/text.txt data/code.txt
# Native paths are relative to config/suite.toml rather than container mounts.
sed -i 's|path = "/data/|path = "../data/|g' config/suite.toml
# Edit core counts, RSS guards and NUMA placement for the host before running.
uv run --all-extras python -m bench suite --config config/suite.toml \
  --bundle .bench/bundle/bundle.json --out results
```

For this host command, change each case path from `/data/...` to the real host
path, or to a path relative to the config, such as `../data/en/text.txt` when the
config is `config/suite.toml`. The same trainer, growth and NUMA settings apply.

## Download and prepare corpora on the host

Use the downloaded image on a machine with network access. Preparation is an
explicit Docker command with writable corpus/cache mounts. Downloads verify
pinned shard sizes and SHA-256; dataset loading scripts are never executed.
No corpus is committed or baked into the image.

```sh
mkdir -p data cache config results
docker run --rm --entrypoint cat "$IMAGE" \
  /opt/benchmark/experiments/dedicated-server.toml > config/suite.toml
docker run --rm \
  --mount type=bind,src="$PWD/data",dst=/data \
  --mount type=bind,src="$PWD/cache",dst=/cache \
  "$IMAGE" corpus --dataset /opt/benchmark/datasets/wikipedia-en.json \
  --size-mib 513 --out /data/en --cache /cache
docker run --rm \
  --mount type=bind,src="$PWD/data",dst=/data \
  --mount type=bind,src="$PWD/cache",dst=/cache \
  "$IMAGE" corpus --dataset /opt/benchmark/datasets/wikipedia-zh.json \
  --size-mib 513 --out /data/zh --cache /cache
docker run --rm \
  --mount type=bind,src="$PWD/data",dst=/data \
  --mount type=bind,src="$PWD/cache",dst=/cache \
  "$IMAGE" corpus --dataset /opt/benchmark/datasets/github-code-clean.json \
  --size-mib 513 --out /data/code --cache /cache
ln -s en/text.txt data/en.txt
ln -s zh/text.txt data/zh.txt
ln -s code/text.txt data/code.txt
```

513 MiB supplies a complete-line prefix for the 512 MiB matrix. For longer growth
curves, prepare a larger **distinct** corpus into another output directory and
update the mount/symlink. The recipe fails if the pinned shard set cannot supply
the requested amount; extend its pinned manifest or provide your own larger text
file. Do not duplicate the same text to inflate input size: that mainly increases
frequencies and barely increases the distinct strings responsible for memory.
You can prepare on another machine and transfer `data/` and `config/` with
`rsync -a`, preserving the relative symlinks. Edit `config/suite.toml` before
measurement. The measurement container preserves the partial curve when its mounted file runs
out, without downloading or repeating text.

English and Chinese use pinned Wikipedia. Code uses the ungated
[codeparrot/github-code-clean](https://huggingface.co/datasets/codeparrot/github-code-clean)
at revision `c48d40f9e70f0196f8236901ee35807f7d6c44c0`. Its first eight shards are
pinned; only needed shards download. The recipe selects Python, JavaScript,
TypeScript, Rust, Go, C/C++, Java, Shell and SQL, preserves indentation/blank lines,
and records per-language and license counts. It follows source shard order and
does not claim equal language proportions. See [dataset manifests](../datasets/README.md).

For your own inputs, mount UTF-8 text files. Prose uses one document/paragraph per
line; Chinese stays unsegmented. The runner removes LF and optional CR before
pretokenization. Code retains indentation, punctuation and blank lines. Matrix
and growth copy/hash nested prefixes before timing; public Feed reads them lazily.

Keep results on local SSD with sufficient scratch space: cached exponential
prefixes total roughly twice the largest requested size. The two Chinese modes
share prefix files by source identity. Identical inputs, binaries and config are
required for resume.

## Run, CPU affinity and NUMA

```sh
docker run --rm --entrypoint lscpu "$IMAGE" -e=CPU,CORE,SOCKET,NODE,ONLINE
docker run --rm --entrypoint numactl "$IMAGE" --hardware
docker run --rm --network none \
  --mount type=bind,src="$PWD/data",dst=/data,readonly \
  --mount type=bind,src="$PWD/config",dst=/config,readonly \
  --mount type=bind,src="$PWD/results",dst=/results \
  "$IMAGE"
```

Automatic allocation uses one logical CPU per physical core, preferring one NUMA
node. A W-worker runner uses the first W CPUs in the selected ordered list;
`RAYON_NUM_THREADS=W` and `TOKENIZERS_PARALLELISM=true` are explicit. Override
`execution.cpu_set` for quiet cores; suite allocation rejects SMT siblings.
The lower-level harness still permits deliberately labelled SMT experiments.

For a single-node comparison, set `cpu_node = 0` in `[execution]`, and
`policy = "bind"`, `nodes = [0]` in `[execution.numa]`. For a separate cross-socket
experiment, select physical cores on both nodes and `policy = "interleave"`,
`nodes = [0, 1]`. The default policy leaves OS memory placement intact. Requested
NUMA policies are probed before measurement; denied syscalls fail rather than
silently falling back. If Docker's seccomp denies these syscalls, a controlled
benchmark can use `--security-opt seccomp=unconfined` or a tailored profile.
Use separate result directories for different memory policies.

Optional Docker `--cpuset-cpus`/`--cpuset-mems` further restrict the container.
Avoid CPU quota throttling and concurrent compilation/downloads for performance
measurements. There are no exposed ports.

There is **no Docker memory hard limit**. `growth.rss_target_gib` is an observation
target, not a process kill threshold. `execution.max_process_rss_gib` is a separate
safety guard (48 GiB in the example), required to exceed the soft target when
growth is enabled. Choose it to allow an exponential step to finish. RSS/HWM and
swap are sampled every 20 ms; kernel HWM also catches short peaks. Insufficient
host/cgroup available memory, swap, timeout, crash or safety-guard termination
stops that curve as inconclusive. Failed peaks are retained as diagnostic lower
bounds and never drawn as completed RSS observations.

## Configuration and measurement definitions

The TOML names paths, input sizes, pretokenizers, trainer options and execution
settings directly. Cases may override trainer options; unknown options fail.
Existing JSON experiments and `bench run` remain supported. Add/remove cases
without specializing the harness.

`execution.warmups = 1` runs one representative workload before the entire suite:
HF main, the first corpus, at the largest matrix core count. It is excluded from
measurements; small-corpus and growth phases do not repeat it in an `all` run.
Set it to 0 to skip warmup. These native runners have no JIT compilation.

`execution.repetitions = 3` gives three measured blocks, using fresh processes
and rotating algorithm order. Absolute Feed + Train time
and process peak RSS use medians. **Throughput uses actual raw input MiB divided
by median Feed + Train seconds**. Every algorithm at a matrix cell uses the same
raw input. Relative time/RSS and speedup use medians of paired ratios against HF
main at the same core count. Exact model IDs and ordered merges are checked;
any mismatch invalidates performance comparisons and remains in the audit trail.

`growth.repetitions = 1` is required. Input grows from `start_mib` by `factor`
(default 2), bounded by `max_mib` and the mounted corpus. Each algorithm has its
own stopping point. The RSS target can be any positive value; its emphasized
left-axis tick and horizontal line are computed from the config, even when it
falls between normal ticks. A crossing observation is not an exact capacity.

The memory figure's preferred x-axis is **the sum of UTF-8 bytes of distinct
strings in the public Feed word map**, excluding their frequencies and map/object
storage. It is measured after the timed interval through streaming serialization,
without allocating another word map. ByteLevel uses the UTF-8 size of its encoded
strings, not original raw bytes. Growth controls raw prefix size and observes
this Feed size afterward. Both byte counts remain in the CSV. If a runner lacks
this metric, the entire growth figure consistently uses raw input MiB instead;
it never mixes the two definitions across curves.

For separate phases append `suite --config /config/suite.toml --out /results
--phase matrix` or `--phase growth` to the Docker command, using distinct output
directories. Repeat the exact command to resume. `--retry-failed` retries failed
slots while retaining all prior attempts; changed source/config/corpus/host/harness
requires a new results directory.

Each completed attempt prints one plain log line with Feed/Train/total time,
peak RSS, completed/remaining count, elapsed time and approximate ETA. ETA learns
wall time (including validation) from observed corpus, algorithm, size and core
combinations, uses nearby observations until a cell is measured, and removes
unneeded larger growth steps after a target crossing. It covers benchmark runs;
final figure export is additional. Early estimates may change substantially.
No timeout is imposed when `execution.timeout_seconds = 0`.

## Reports and three figures

| Artifact | Contents |
| --- | --- |
| `report/REPORT.md` | Source revisions, absolute/relative tables and stopping reasons |
| `report/summary.json`, `matrix.csv` | Medians, raw samples, throughput and paired ratios |
| `report/growth-curves.csv` | Per-curve completion/stopping summaries |
| `report/memory-growth.csv` | Every growth point, raw/Feed bytes and diagnostics |
| `report/core-scaling.png`, `.svg`, `.pdf` | Linear throughput vs cores; end labels show paired speedup |
| `report/small-core-scaling.png`, `.svg`, `.pdf` | Independent 1 MiB throughput comparison with the same trainer |
| `report/memory-growth.png`, `.svg`, `.pdf` | Linear peak RSS vs Feed size, with the configured soft target |
| `report/fonts.json`, `*.alignment.json`, `*.text-audit.json`, `*.collision-audit.json` | Actual font hashes and rendered figure checks |
| `matrix/attempts/`, `small-matrix/attempts/`, `growth/<case>/<arm>/attempts/` | Jobs, metrics, models, logs and sampled `memory.jsonl` |

Each figure contains four aligned panels in the order shown above, using consistent
method colors and symbols. Throughput and memory axes start at zero. Curves use
observed points without extrapolation. The image bundles exact Liberation Sans
regular/bold files (an Arial-compatible family) and their license; PNG renders
with them and PDF embeds them. PNG is exported at 600 dpi (4320 × 3600 for the four-panel layout). SVG keeps editable text and needs those fonts on
the viewing machine. Multi-panel alignment, PDF text sizes and collisions are
checked automatically at export. The [Nature Figure skill](../.agents/skills/nature-figure/SKILL.md)
is installed in this repository as a drawing reference.

Partial results are reported after failures. Corpus exhaustion completes the
observed experiment but marks that curve partial; failed/inconclusive runs or an
invalid matrix yield nonzero exit status. Regenerate reports without training:

```sh
docker run --rm --network none \
  --mount type=bind,src="$PWD/results",dst=/results \
  "$IMAGE" suite-report --out /results
```

Preview the figure style with clearly labelled synthetic values:

```sh
uv run --extra plots python scripts/preview_figures.py --out .bench/figure-preview
```

## Small VPS verification

`scripts/docker_smoke.py` creates deterministic fixtures and a three-round matrix
with single-run growth. It checks orchestration/models/figures, not performance.
The action uses at most two cores; local validation may use four:

```sh
python3 scripts/docker_smoke.py --out .bench/docker-smoke --workers 1 4
docker run --rm --network none --cpuset-cpus 0,1,2,3 \
  --mount type=bind,src="$PWD/.bench/docker-smoke/data",dst=/data,readonly \
  --mount type=bind,src="$PWD/.bench/docker-smoke/config",dst=/config,readonly \
  --mount type=bind,src="$PWD/.bench/docker-smoke/results",dst=/results \
  bpe-bench:local
```

For real-corpus verification on a six-core VPS, use 1, 2, 4 and 6 cores, a 32 MiB
main matrix and 1 MiB small matrix, with three repetitions and a 100,000 target
vocabulary. Growth can start at 8 MiB and double to 128 MiB using six cores, a
2 GiB soft target and a host-appropriate safety RSS guard. Run the 512 MiB/8-core
experiment with a 16 GiB soft target on the larger Dedicated Server.
