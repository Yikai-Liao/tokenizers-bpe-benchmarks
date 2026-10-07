# Pinned Wikipedia inputs

The manifests record immutable Hub revision `b04c8d1ceb2f5cd4588862100d08de323dccfbaa`,
configuration, shard URLs, expected LFS SHA-256 and sizes. Chinese metadata covers
all six shards; English covers all 41 shards. A single `corpus` request beyond
available eligible text fails; batch `corpora` preparation retains a shorter
source and records its actual size. Extend pinned metadata or choose a larger
source before running a larger recipe.

Source metadata: [Chinese shards](https://huggingface.co/api/datasets/wikimedia/wikipedia/tree/b04c8d1ceb2f5cd4588862100d08de323dccfbaa/20231101.zh),
[English shards](https://huggingface.co/api/datasets/wikimedia/wikipedia/tree/b04c8d1ceb2f5cd4588862100d08de323dccfbaa/20231101.en).
See the [dataset card](https://huggingface.co/datasets/wikimedia/wikipedia) for
licensing and attribution. No corpus text is committed.

## Multilingual code

[github-code-clean.json](github-code-clean.json) pins the first 128 shards of
[codeparrot/github-code-clean](https://huggingface.co/datasets/codeparrot/github-code-clean)
at revision `c48d40f9e70f0196f8236901ee35807f7d6c44c0`. Preparation preserves code
whitespace, selects the configured language extensions, and records actual language
and license counts. The source mixture follows shard order, without asserting
equal language quotas. For direct host preparation, run `uv run --extra corpus python -m bench corpus --dataset
datasets/github-code-clean.json --size-mib 513 --out .bench/code` to provide a
512 MiB complete-line benchmark prefix. The recipe reads pinned Parquet directly.

## Prepare all inputs at once

The [batch plan](corpora.toml) prepares English, Chinese and Code with one command:

```sh
uv run --extra corpus python -m bench corpora --out data --cache cache --size-mib 32769
```

This targets up to 32 GiB plus 1 MiB of extracted UTF-8 text per source. Only
required pinned shards download. Short sources are retained and their requested
and actual sizes appear in `data/corpora.json`. The plan supports other datasets
and per-source targets. See [Docker preparation](../docs/docker.md#download-and-prepare-corpora-on-the-host)
for the equivalent single-container command.
