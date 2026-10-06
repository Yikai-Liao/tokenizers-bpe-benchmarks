#!/usr/bin/env python3
"""Stream independent paragraphs from pinned Wikipedia shards."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import pyarrow.parquet as pq

REVISION = "b04c8d1ceb2f5cd4588862100d08de323dccfbaa"
SPACE = re.compile(r"\s+")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cached-shard2", type=Path)
    parser.add_argument("--target-mib", type=int, default=1024)
    parser.add_argument("--language", choices=["zh", "en"], default="zh")
    args = parser.parse_args()
    root = args.output_dir
    (root / "raw").mkdir(parents=True, exist_ok=True)
    if args.target_mib < 1: raise ValueError("target must be positive")
    output = root / f"{args.language}-{args.target_mib}m.txt"
    shards = {"zh": 6, "en": 41}[args.language]
    configuration = f"20231101.{args.language}"
    if args.cached_shard2 and args.language != "zh":
        raise ValueError("cached shard 2 is a Chinese-only input")
    target = args.target_mib << 20
    total = lines = articles = 0
    sources = []
    with output.open("wb") as stream:
        for number in range(shards):
            name = f"train-{number:05d}-of-{shards:05d}.parquet"
            url = f"https://huggingface.co/datasets/wikimedia/wikipedia/resolve/{REVISION}/{configuration}/{name}"
            source = args.cached_shard2 if number == 2 and args.cached_shard2 else root / "raw" / name
            if not source.exists():
                partial = source.with_suffix(".part")
                subprocess.run(["curl", "-L", "--fail", "--retry", "3", "--continue-at", "-", url, "-o", str(partial)], check=True)
                partial.rename(source)
            sha = digest(source)
            if number == 2 and args.cached_shard2 and sha != "ec8f6c0dd1418b8fcd454278fb4f2bc7cd0ce8312f29c80b672533942601338f":
                raise ValueError("cached shard checksum mismatch")
            sources.append(dict(shard=name, url=url, bytes=source.stat().st_size, sha256=sha))
            reached = False
            for batch in pq.ParquetFile(source).iter_batches(batch_size=256, columns=["text"]):
                for text in batch.column(0).to_pylist():
                    articles += 1
                    for paragraph in (text or "").split("\n\n"):
                        line = (SPACE.sub(" ", paragraph).strip() + "\n").encode("utf-8")
                        if not 32 <= len(line) <= 8192:
                            continue
                        if total + len(line) > target:
                            reached = True
                            break
                        stream.write(line)
                        total += len(line)
                        lines += 1
                    if reached:
                        break
                if reached:
                    break
            print(json.dumps(dict(shard=name, output_bytes=total, lines=lines)), flush=True)
            if reached:
                break
    manifest = dict(dataset="wikimedia/wikipedia", revision=REVISION, configuration=configuration,
                    selection="shard order, article order, normalized paragraphs; no replication or synthetic additions",
                    line_byte_range=[32, 8192], sources=sources, articles_visited=articles,
                    output=dict(path=output.name, bytes=total, lines=lines, sha256=digest(output)))
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    if total < target - 8192:
        raise ValueError(f"eligible corpus only {total} bytes")
    print(json.dumps(manifest["output"]), flush=True)


if __name__ == "__main__":
    main()
