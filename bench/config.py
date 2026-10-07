"""Validated plans, content identities and atomic JSON records."""

import hashlib
import json
import math
import os
import tomllib
from pathlib import Path

PROTOCOL = 1
ROOT = Path(__file__).resolve().parent.parent


def read(path):
    if Path(path).suffix == ".toml":
        return tomllib.loads(Path(path).read_text())
    return json.loads(
        Path(path).read_text(),
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)),
    )


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        stream.write(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def identity(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path, expected):
    if digest(path) != expected:
        raise ValueError(f"content hash mismatch: {path}")


def resolve(base, value):
    return (Path(base) / value).resolve()


def positive(value, name, zero=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (value < 0 if zero else value <= 0)
    ):
        raise ValueError(f"invalid {name}")
    return value


def cpu_config(execution):
    cpus = execution["cpu_set"]
    workers = execution["workers"]
    if (
        not cpus
        or any(type(cpu) is not int for cpu in cpus)
        or len(set(cpus)) != len(cpus)
    ):
        raise ValueError("CPU set must be nonempty and unique")
    if not set(cpus).issubset(os.sched_getaffinity(0)):
        raise ValueError("CPU set outside available affinity")
    if (
        not workers
        or len(set(workers)) != len(workers)
        or any(type(w) is not int or not 1 <= w <= len(cpus) for w in workers)
    ):
        raise ValueError("workers must fit the CPU set")


def environment(extra=None, workers=None):
    # Experimental cache/allocator/thread settings cannot leak in from the shell.
    keep = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    for key, value in (extra or {}).items():
        if key.startswith(("TK_WORD_COUNTS_CACHE", "TK_WRITE_WORD_COUNTS_CACHE")):
            raise ValueError("word-count cache environment is prohibited")
        if not isinstance(value, str):
            raise ValueError("environment values must be strings")
        env[key] = value
    if workers is not None:
        env.update(RAYON_NUM_THREADS=str(workers), TOKENIZERS_PARALLELISM="true")
    return env


def load(path):
    cfg = read(path)
    if cfg.get("schema_version") != 1 or cfg.get("mode") not in ("core", "pipeline"):
        raise ValueError("unsupported schema or mode")
    if cfg.get("comparison", "exact-model") != "exact-model":
        raise ValueError("only exact-model comparison is supported")
    cfg["comparison"] = "exact-model"
    execution = dict(
        warmups_per_cell=1,
        warmup_scope="cell",
        paired_blocks=5,
        timeout_seconds=600,
        min_available_gib=3,
        max_process_rss_gib=12,
        order="balanced-alternating",
    )
    execution.update(cfg["execution"])
    if execution["warmup_scope"] not in ("cell", "representative"):
        raise ValueError("unsupported warmup_scope")
    cpu_config(execution)
    for field in ("warmups_per_cell", "paired_blocks"):
        if type(execution[field]) is not int:
            raise ValueError(f"invalid {field}")
        positive(execution[field], field, field == "warmups_per_cell")
    for field in ("timeout_seconds", "min_available_gib", "max_process_rss_gib"):
        positive(execution[field], field, field in ("min_available_gib", "timeout_seconds"))
    if execution["order"] != "balanced-alternating":
        raise ValueError("unsupported schedule")
    cfg["execution"] = execution
    from .topology import validate_numa

    execution["numa"] = validate_numa(execution.get("numa", {}), execution["cpu_set"])
    if len(cfg["arms"]) < 2 or "baseline" not in cfg["arms"]:
        raise ValueError("at least baseline and one comparison arm required")
    base = Path(path).resolve().parent
    for name, arm in cfg["arms"].items():
        if not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("unsafe arm name")
        arm["build"] = str(resolve(base, arm["build"]))
        arm.setdefault("environment", {})
        environment(arm["environment"])
    names = set()
    for case in cfg["cases"]:
        if (
            case["name"] in names
            or not case["name"].replace("-", "").replace("_", "").isalnum()
        ):
            raise ValueError("case names must be unique and safe")
        names.add(case["name"])
        case["input_manifest"] = str(resolve(base, case["input_manifest"]))
        case.setdefault("pretokenizer", "whitespace")
        if case["pretokenizer"] not in (
            "none",
            "whitespace",
            "whitespace_split",
            "bytelevel_regex",
        ):
            raise ValueError("unknown pretokenizer")
        trainer = dict(
            vocab_size=100000,
            min_frequency=2,
            prefix=None,
            suffix=None,
            max_token_length=None,
        )
        trainer.update(case.get("trainer", {}))
        if set(trainer) != {
            "vocab_size",
            "min_frequency",
            "prefix",
            "suffix",
            "max_token_length",
        }:
            raise ValueError("unsupported trainer option")
        for field in ("vocab_size", "min_frequency"):
            if type(trainer[field]) is not int:
                raise ValueError(f"invalid {field}")
            positive(trainer[field], field, True)
        if trainer["max_token_length"] is not None:
            if type(trainer["max_token_length"]) is not int:
                raise ValueError("max_token_length must be an integer")
            positive(trainer["max_token_length"], "max_token_length")
        for field in ("prefix", "suffix"):
            if trainer[field] is not None and not isinstance(trainer[field], str):
                raise ValueError(f"invalid {field}")
        case["trainer"] = trainer
    if not names:
        raise ValueError("no cases")
    return cfg
