"""Generate canonical Byte-level BPE plans without starting measurements."""

import argparse
import os
import tempfile
from pathlib import Path

from bench import inputs
from bench.config import identity, load, read, write

PRETOKENIZER = "bytelevel_regex"
VOCAB_SIZES = (32_000, 50_000, 65_536)
WORKERS = (1, 4, 8)
AFFIXES = {
    "prefix": ("##", None),
    "suffix": (None, "</w>"),
    "both": ("##", "</w>"),
}


def build_reference(path):
    path = Path(path).resolve()
    if path.is_dir():
        path /= "build.json"
    record = read(path)
    if identity(record["request"]) != record["build_id"]:
        raise ValueError(f"build provenance identity mismatch: {path}")
    return str(path)


def text_reference(path):
    path = Path(path).resolve()
    record = read(path)
    if record.get("schema_version") != 1 or record.get("kind") != "text":
        raise ValueError(f"text manifest required: {path}")
    expected = identity(
        {key: value for key, value in record.items() if key not in ("path", "input_id")}
    )
    if record.get("input_id") != expected:
        raise ValueError(f"input manifest identity mismatch: {path}")
    return str(path)


def prepare_core_input(manifest, baseline, out):
    # Full content verification and preprocessing are explicitly opt-in. Use
    # the shared runner, rather than duplicating byte mapping or regex logic.
    source = inputs.validate(manifest, "pipeline", PRETOKENIZER)
    inputs.prepared(source["data_path"], PRETOKENIZER, baseline, out)


def generate(
    baseline,
    candidates,
    zh_manifest,
    en_manifest,
    out,
    *,
    workers=WORKERS,
    vocab_sizes=VOCAB_SIZES,
    affixes=("both",),
    cpu_set=None,
    prepare_core=False,
    timeout_seconds=600,
    min_available_gib=3,
    max_process_rss_gib=12,
):
    if "baseline" in candidates:
        raise ValueError("baseline is reserved for the shared reference arm")
    if not workers:
        raise ValueError("at least one worker count is required")
    if not vocab_sizes:
        raise ValueError("at least one vocabulary target is required")
    if any(name not in AFFIXES for name in affixes):
        raise ValueError("affix profiles must be prefix, suffix or both")
    out = Path(out).resolve()
    baseline = build_reference(baseline)
    arms = {"baseline": dict(build=baseline, environment={})}
    arms.update(
        (name, dict(build=build_reference(path), environment={}))
        for name, path in candidates.items()
    )
    sources = {
        "zh": text_reference(zh_manifest),
        "en": text_reference(en_manifest),
    }
    prepared = {
        language: out / "inputs" / f"{language}-bytelevel"
        for language in sources
    }
    execution = dict(
        workers=list(workers),
        cpu_set=(
            list(cpu_set)
            if cpu_set is not None
            else sorted(os.sched_getaffinity(0))[: max(workers)]
        ),
        warmups_per_cell=1,
        paired_blocks=3,
        order="balanced-alternating",
        timeout_seconds=timeout_seconds,
        min_available_gib=min_available_gib,
        max_process_rss_gib=max_process_rss_gib,
    )
    profiles = [
        (f"vocab-{size}", size, None, None) for size in vocab_sizes
    ] + [
        (f"affix-{name}-vocab-{vocab_sizes[0]}", vocab_sizes[0], *AFFIXES[name])
        for name in affixes
    ]
    configs = {}
    for mode in ("pipeline", "core"):
        cfg = dict(
            schema_version=1,
            name=f"bytelevel-{mode}",
            mode=mode,
            comparison="exact-model",
            arms=arms,
            execution=execution,
            cases=[
                dict(
                    name=f"{language}-{label}",
                    input_manifest=(
                        source
                        if mode == "pipeline"
                        else str(prepared[language] / "manifest.json")
                    ),
                    pretokenizer=PRETOKENIZER,
                    trainer=dict(
                        vocab_size=vocab_size,
                        min_frequency=2,
                        prefix=prefix,
                        suffix=suffix,
                        max_token_length=None,
                    ),
                )
                for language, source in sources.items()
                for label, vocab_size, prefix, suffix in profiles
            ],
        )
        # Validate with the canonical schema before touching output or preparing
        # input. Only tiny JSON files are read here, never corpus/build binaries.
        with tempfile.TemporaryDirectory(prefix="bytelevel-plan-") as temporary:
            check = Path(temporary) / "config.json"
            write(check, cfg)
            configs[mode] = load(check)

    paths = {mode: out / f"{mode}.json" for mode in configs}
    for mode, path in paths.items():
        if path.exists() and read(path) != configs[mode]:
            raise ValueError(f"configuration changed; use a new output directory: {path}")
    if prepare_core:
        for language, source in sources.items():
            prepare_core_input(source, baseline, prepared[language])
    for mode, path in paths.items():
        if not path.exists():
            write(path, configs[mode])
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline", type=Path, required=True, help="build.json or build directory"
    )
    parser.add_argument(
        "--candidate", type=Path, help="optional build for the arm named candidate"
    )
    parser.add_argument(
        "--arm",
        action="append",
        default=[],
        metavar="NAME=BUILD",
        help="additional comparison arm; repeat to share one baseline",
    )
    parser.add_argument("--zh-manifest", type=Path, required=True)
    parser.add_argument("--en-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", nargs="+", type=int, default=list(WORKERS))
    parser.add_argument("--vocab-sizes", nargs="+", type=int, default=list(VOCAB_SIZES))
    parser.add_argument(
        "--affixes",
        choices=("none", "both", "all"),
        default="both",
        help="affix cases at the first vocabulary target (default: combined prefix/suffix)",
    )
    parser.add_argument("--cpu-set", nargs="+", type=int)
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--min-available-gib", type=float, default=3)
    parser.add_argument("--max-process-rss-gib", type=float, default=12)
    parser.add_argument(
        "--prepare-core",
        action="store_true",
        help="explicitly verify text and prepare shared core inputs with the baseline runner",
    )
    args = parser.parse_args(argv)
    candidates = {"candidate": args.candidate} if args.candidate is not None else {}
    for arm in args.arm:
        name, separator, build = arm.partition("=")
        if not separator or not name or not build:
            parser.error("--arm requires NAME=BUILD")
        if name in candidates or name == "baseline":
            parser.error(f"duplicate or reserved arm name: {name}")
        candidates[name] = Path(build)
    if not candidates:
        parser.error("provide --candidate or at least one --arm NAME=BUILD")
    try:
        paths = generate(
            args.baseline,
            candidates,
            args.zh_manifest,
            args.en_manifest,
            args.out,
            workers=args.workers,
            vocab_sizes=args.vocab_sizes,
            affixes=(
                () if args.affixes == "none"
                else tuple(AFFIXES) if args.affixes == "all"
                else ("both",)
            ),
            cpu_set=args.cpu_set,
            prepare_core=args.prepare_core,
            timeout_seconds=args.timeout_seconds,
            min_available_gib=args.min_available_gib,
            max_process_rss_gib=args.max_process_rss_gib,
        )
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    for mode, path in paths.items():
        print(f"{mode}: {path}")


if __name__ == "__main__":
    main()
