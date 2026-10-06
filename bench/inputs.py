"""Verified text, pinned shards and explicit prepared word-count inputs."""

import json
import subprocess
import urllib.request
from pathlib import Path

from .builds import validate as validate_build
from .config import digest, environment, identity, read, verify, write


def text_manifest(text, out):
    text = Path(text).resolve()
    data = dict(
        schema_version=1,
        kind="text",
        path=str(text),
        sha256=digest(text),
        bytes=text.stat().st_size,
        line_protocol="UTF-8 lines; remove LF and optional CR; preserve other whitespace",
    )
    data["input_id"] = identity({k: v for k, v in data.items() if k != "path"})
    write(out, data)
    return data


def validate(path, mode, pretokenizer):
    path = Path(path).resolve()
    manifest = read(path)
    kind = "prepared_words" if mode == "core" else "text"
    if manifest.get("schema_version") != 1 or manifest.get("kind") != kind:
        raise ValueError(f"{mode} requires {kind} input")
    data = (path.parent / manifest["path"]).resolve()
    verify(data, manifest["sha256"])
    if manifest.get("bytes") != data.stat().st_size:
        raise ValueError("input byte count mismatch")
    claimed = manifest["input_id"]
    if (
        identity({k: v for k, v in manifest.items() if k not in ("path", "input_id")})
        != claimed
    ):
        raise ValueError("input manifest identity mismatch")
    if kind == "prepared_words":
        if manifest["pretokenizer"] != pretokenizer:
            raise ValueError("prepared input preprocessing differs")
    return {**manifest, "data_path": str(data)}


def prepared(text, pretokenizer, build_record, out):
    out = Path(out).resolve()
    build = validate_build(build_record)
    raw = dict(path=str(Path(text).resolve()), sha256=digest(text))
    recipe = dict(
        raw_sha256=raw["sha256"],
        pretokenizer=pretokenizer,
        preparer_build_id=build["build_id"],
        tool_sha256=digest(Path(__file__)),
        format_version=1,
    )
    if out.exists():
        old = read(out / "manifest.json")
        if old["recipe"] != recipe:
            raise ValueError("prepared identity changed; use a new directory")
        return validate(out / "manifest.json", "core", pretokenizer)
    out.mkdir(parents=True)
    job = dict(
        protocol_version=1,
        attempt_id="prepare",
        build_id=build["build_id"],
        input_id=identity(recipe),
        mode="prepare",
        input=raw["path"],
        output=str(out / "words.json"),
        workers=1,
        pretokenizer=pretokenizer,
        trainer=dict(
            vocab_size=0,
            min_frequency=0,
            prefix=None,
            suffix=None,
            max_token_length=None,
        ),
    )
    write(out / "job.json", job)
    result = subprocess.run(
        [build["binary_path"], str(out / "job.json")],
        env=environment(workers=1),
        capture_output=True,
        text=True,
    )
    (out / "stdout.log").write_text(result.stdout)
    (out / "stderr.log").write_text(result.stderr)
    result.check_returncode()
    value = json.loads(result.stdout)
    for field in ("protocol_version", "attempt_id", "build_id", "input_id", "mode"):
        if value.get(field) != job[field]:
            raise ValueError(f"preparation returned wrong {field}")
    write(out / "preparation-result.json", value)
    verify(text, raw["sha256"])
    data = dict(
        schema_version=1,
        kind="prepared_words",
        path="words.json",
        sha256=digest(out / "words.json"),
        bytes=(out / "words.json").stat().st_size,
        pretokenizer=pretokenizer,
        raw=raw,
        recipe=recipe,
    )
    # Locating the raw file is not part of semantic identity.
    data["raw"] = {"sha256": raw["sha256"]}
    data["input_id"] = identity({k: v for k, v in data.items() if k != "path"})
    write(out / "manifest.json", data)
    return data


def shard_cache(shard, cache):
    dest = Path(cache) / shard["sha256"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        verify(dest, shard["sha256"])
        if "bytes" in shard and dest.stat().st_size != shard["bytes"]:
            raise ValueError("shard byte count mismatch")
        return dest
    temporary = dest.with_suffix(".part")
    with urllib.request.urlopen(shard["url"]) as source, temporary.open("wb") as target:
        import shutil

        shutil.copyfileobj(source, target)
    verify(temporary, shard["sha256"])
    if "bytes" in shard and temporary.stat().st_size != shard["bytes"]:
        raise ValueError("shard byte count mismatch")
    temporary.replace(dest)
    return dest


def corpus(dataset_manifest, size_mib, out, cache):
    import re

    import pyarrow.parquet as pq

    dataset = read(dataset_manifest)
    out = Path(out).resolve()
    if size_mib < 1:
        raise ValueError("positive size required")
    recipe = dict(
        dataset=dataset,
        size_mib=size_mib,
        tool_sha256=digest(Path(__file__)),
        normalization="Unicode whitespace collapse; strip; LF",
        paragraph_bytes=[32, 8192],
        selection="ordered nested prefix",
    )
    if out.exists():
        record = read(out / "manifest.json")
        if record["recipe"] != recipe:
            raise ValueError("corpus recipe changed; use a new directory")
        return validate(out / "manifest.json", "pipeline", "none")
    out.mkdir(parents=True)
    total = lines = 0
    used = []
    limit = size_mib << 20
    reached = False
    with (out / "text.txt").open("wb") as stream:
        for shard in dataset["shards"]:
            path = shard_cache(shard, cache)
            used.append(shard)
            for batch in pq.ParquetFile(path).iter_batches(
                batch_size=256, columns=["text"]
            ):
                for article in batch.column(0).to_pylist():
                    for paragraph in (article or "").split("\n\n"):
                        line = (re.sub(r"\s+", " ", paragraph).strip() + "\n").encode()
                        if not 32 <= len(line) <= 8192:
                            continue
                        if total + len(line) > limit:
                            reached = True
                            break
                        stream.write(line)
                        total += len(line)
                        lines += 1
                    if reached:
                        break
                if reached:
                    break
            if reached:
                break
    if total < limit - 8192:
        raise ValueError("manifest shards cannot supply requested corpus")
    record = text_manifest(out / "text.txt", out / "manifest.json")
    record.update(path="text.txt", recipe=recipe, used_shards=used, lines=lines)
    record["input_id"] = identity(
        {k: v for k, v in record.items() if k not in ("path", "input_id")}
    )
    write(out / "manifest.json", record)
    return record
