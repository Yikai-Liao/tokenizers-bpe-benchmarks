# Tokenizers BPE benchmarks

This repository contains BPE training comparisons, multicore experiments and
simplification regression evidence for
[Yikai-Liao/tokenizers](https://github.com/Yikai-Liao/tokenizers). Production
implementation, correctness tests and the engine design belong to tokenizers.
Research runners, historical plans and measurements belong here.

## Source and evidence boundaries

The unchanged Best Multicore control is
`57c04ca9ed1e843f6e36fe68ed3ae5adf499936c` on `bpe/multicore-best`.
`source-snapshots/57c04ca9.tar.gz` preserves its implementation, dependency lock,
vendored experimental Rayon and licenses. Its measured configuration requires
`bpe-suite/with_multicore_candidate.sh`; ordinary library defaults differ.

The simplification candidate at `8176f5e12127f46f682e8e9c9836fc18af158775` uses released Rayon and the selected whole-pair,
complete-producer and owner-local grouping paths directly. Its source snapshot
and regression report are recorded under `results/simplification-20261006`.
No third-party radix replacement is used.

`bpe-suite/results/` and `bpe-suite/MULTICORE_CANDIDATE.md` are historical evidence.
Their absolute paths describe the original host. Phase-instrumented core times,
public `do_train` times, and feed-plus-training times have different boundaries;
do not combine them. Archived unapplied patches are against their recorded source
snapshot and are not production changes. `history/` contains superseded plans,
review material and the original custom idle-policy dependency.

## Pinned Chinese Wikipedia input

The dataset is `wikimedia/wikipedia`, revision
`b04c8d1ceb2f5cd4588862100d08de323dccfbaa`, configuration `20231101.zh`.
`prepare_gb_corpus.py` streams shards and articles in order, normalizes paragraph
whitespace, accepts lines of 32–8192 UTF-8 bytes and stops at the requested size.
It never replicates text. This is the original preparation algorithm with an
optional cached shard and configurable target size; the default remains 1 GiB.

```sh
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python prepare_gb_corpus.py --output-dir /absolute/path/corpus --target-mib 1024
```

Whole-line prefixes provide smaller inputs. The 512 MiB preparation produced
536,870,289 bytes, 1,445,902 lines and SHA-256
`a0d40d4102cba1e933f25e5ccd17552d2eaebaec4ef770bc39d8e46e740b4d4f`.
The data manifest records source URLs, downloaded shard hashes and output hashes.
Raw Parquet and text files stay outside Git. The earlier provenance appears in
`history/AFFIX_PERFORMANCE_REPORT.md`.

## Build against a selected source snapshot

Extract the preserved source or use a tokenizers checkout at the desired revision.
The common runner and release profile remain identical between arms. Each build
uses the appropriate committed dependency lock and records source and binary
hashes. Native CPU compilation makes its binary machine-specific.

```sh
mkdir -p /absolute/path/baseline
tar -xzf source-snapshots/57c04ca9.tar.gz -C /absolute/path/baseline
python3 build_runner.py --source /absolute/path/baseline \
  --out /absolute/path/build-baseline --target-dir /absolute/path/cargo-cache \
  --vendored-rayon
python3 build_runner.py --source /absolute/path/tokenizers \
  --out /absolute/path/build-candidate --target-dir /absolute/path/cargo-cache
```

The baseline's retained idle policy is selected only for baseline measurements.
The production candidate has no vendored Rayon or experimental environment inputs.

## Paired local regression

`regression.py` uses the suite's existing process supervisor. Configure absolute
binary and corpus paths, available CPU IDs, worker counts and repetitions:

```json
{
  "binaries": {
    "baseline": "/absolute/path/build-baseline/bpe-suite-runner",
    "candidate": "/absolute/path/build-candidate/bpe-suite-runner"
  },
  "cpu_set": [0, 2, 4, 6, 8, 10, 12, 14, 1, 3, 5, 7, 9, 11, 13, 15],
  "workers": [1, 4, 8, 16],
  "repetitions": 5,
  "cases": [{
    "name": "zh1024", "input": "/absolute/path/corpus/zh-1024m.txt",
    "split": "whitespace", "vocab_size": 100000, "min_frequency": 2
  }]
}
```

```sh
python3 regression.py --config /absolute/path/config.json --out /absolute/path/results
python3 -m unittest discover -s bpe-suite
```

The first eight CPU IDs in the example select one logical CPU on each physical
core of the recorded Ryzen host. Choose IDs for your own topology. Each worker
cell uses its corresponding prefix. Runs are serial; paired arm order alternates,
and cell order rotates and reverses. Each arm/cell has a warm-up. A mismatch,
failed run, memory guard or timeout stops the experiment. Use a fresh output
directory after changing binaries, inputs or parameters.

Training wall and CPU time cover public `do_train` after word counting, including
returned vocabulary and ordered merges. Process HWM ends before serialization.
The supervisor separately samples whole-process RSS and process swap, including
validation. Every run compares canonical vocabulary ID order and complete merge
rank order. Warm-ups stay outside paired statistics. Ratios are computed within
each block before taking medians; ranges describe observed variability.

The legacy full comparison and scaling protocols remain in
[bpe-suite/README.md](bpe-suite/README.md). Pass `--repo` to the legacy suite so its
revision exporter can access the recorded tokenizers commits.

License: Apache-2.0 for the suite, except preserved source files with their own
license notices (including the BSD radix implementation and experimental Rayon).
