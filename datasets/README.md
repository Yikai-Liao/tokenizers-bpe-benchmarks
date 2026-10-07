# Pinned Wikipedia inputs

The manifests record immutable Hub revision `b04c8d1ceb2f5cd4588862100d08de323dccfbaa`,
configuration, shard URLs, expected LFS SHA-256 and sizes. Chinese metadata covers
all six shards; English covers the first ten shards, sufficient for current
prefix experiments. Requesting more eligible text than these shards provide
fails; extend the manifest with pinned metadata before running a larger recipe.

Source metadata: [Chinese shards](https://huggingface.co/api/datasets/wikimedia/wikipedia/tree/b04c8d1ceb2f5cd4588862100d08de323dccfbaa/20231101.zh),
[English shards](https://huggingface.co/api/datasets/wikimedia/wikipedia/tree/b04c8d1ceb2f5cd4588862100d08de323dccfbaa/20231101.en).
See the [dataset card](https://huggingface.co/datasets/wikimedia/wikipedia) for
licensing and attribution. No corpus text is committed.

## Multilingual code

[github-code-clean.json](github-code-clean.json) pins the first eight shards of
[codeparrot/github-code-clean](https://huggingface.co/datasets/codeparrot/github-code-clean)
at revision `c48d40f9e70f0196f8236901ee35807f7d6c44c0`. Preparation preserves code
whitespace, selects the configured language extensions, and records actual language
and license counts. The source mixture follows shard order, without asserting
equal language quotas. For direct host preparation, run `uv run --extra corpus python -m bench corpus --dataset
datasets/github-code-clean.json --size-mib 513 --out .bench/code` to provide a
512 MiB complete-line benchmark prefix. The recipe reads pinned Parquet directly.
