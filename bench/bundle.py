"""Build a portable collection of runners from configurable Git repositories."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .builds import build, create_lock, validate
from .config import digest, read, write


def safe_name(name):
    if not isinstance(name, str) or not name or not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"unsafe name: {name!r}")
    return name


def build_bundle(config, out, cache, portable_release=False):
    cfg = read(config)
    if cfg.get("schema_version") != 1 or not cfg.get("sources"):
        raise ValueError("bundle requires schema_version=1 and sources")
    if portable_release and (cfg.get("rustflags") or any(
        cfg.get("build_environment", {}).get(key) for key in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS")
    )):
        raise ValueError("portable release builds require empty Rust optimization flags")
    names = [safe_name(s["name"]) for s in cfg["sources"]]
    if len(set(names)) != len(names) or cfg.get("baseline") not in names:
        raise ValueError("bundle source names must be unique and include baseline")
    out, cache = Path(out).resolve(), Path(cache).resolve()
    if out.exists():
        raise ValueError("bundle destination exists; use a new directory")
    out.mkdir(parents=True)
    refs = []
    # Resolve every moving ref before compiling. A failed source fails the image.
    with tempfile.TemporaryDirectory(prefix="bpe-sources-") as temporary:
        for source in cfg["sources"]:
            checkout = Path(temporary) / source["name"]
            subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
            subprocess.run(["git", "-C", str(checkout), "fetch", "--depth=1", "--no-tags",
                            source["repository"], source["ref"]], check=True)
            sha = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "FETCH_HEAD"], text=True).strip()
            refs.append((source, checkout, sha))
        records = {}
        for source, checkout, sha in refs:
            name = source["name"]
            folder = out / name
            lock = out / "locks" / name / "Cargo.lock"
            options = dict(vendored_rayon=source.get("vendored_rayon", False),
                           exclude_source_paths=source.get("exclude_source_paths", []),
                           adapter=source.get("adapter", "tk_train_v1"))
            create_lock(checkout, sha, lock, **options)
            env = {key: os.environ[key] for key in ("CARGO_HOME", "RUSTUP_HOME", "CARGO_BUILD_JOBS") if key in os.environ}
            env.update(cfg.get("build_environment", {}))
            result = build(checkout, sha, lock, cache,
                           rustflags=cfg.get("rustflags", ""), build_env=env, **options)
            shutil.copytree(Path(result["record_path"]).parent, folder)
            validate(folder / "build.json")
            records[name] = dict(build=f"{name}/build.json", repository=source["repository"],
                                 requested_ref=source["ref"], commit=sha,
                                 build_id=result["build_id"], binary_sha256=result["binary_sha256"],
                                 lock_sha256=digest(lock), environment=source.get("environment", {}))
            records[name]["adapter"] = options["adapter"]
            print(f"built {name}: {sha}", flush=True)
    record = dict(schema_version=1, baseline=cfg["baseline"], sources=records)
    write(out / "bundle.json", record)
    return record


def load_bundle(path):
    path = Path(path).resolve()
    record = read(path)
    if record.get("schema_version") != 1 or record.get("baseline") not in record.get("sources", {}):
        raise ValueError("invalid bundle manifest")
    arms = {}
    for name, source in record["sources"].items():
        safe_name(name)
        build_path = (path.parent / source["build"]).resolve()
        result = validate(build_path)
        if (result["build_id"] != source["build_id"]
                or result["binary_sha256"] != source["binary_sha256"]
                or result["request"]["source"]["commit"] != source["commit"]):
            raise ValueError("bundle build identity mismatch")
        arm = "baseline" if name == record["baseline"] else name
        if arm in arms:
            raise ValueError("bundle name conflicts with baseline alias")
        arms[arm] = dict(build=str(build_path), environment=source.get("environment", {}))
    if len(arms) < 2:
        raise ValueError("suite requires at least two builds")
    return record, arms
