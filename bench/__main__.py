"""The supported entry point: python -m bench."""

import argparse
from pathlib import Path

from .config import ROOT


def main():
    parser = argparse.ArgumentParser(
        description="Pinned BPE core and public pipeline benchmarks (Linux)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("lock", "build"):
        p = commands.add_parser(name)
        p.add_argument("--source", type=Path, required=True)
        p.add_argument("--revision")
        p.add_argument("--vendored-rayon", action="store_true")
        p.add_argument("--lockfile", type=Path, required=True)
        if name == "build":
            p.add_argument("--cache", type=Path, default=ROOT / ".bench/builds")
            p.add_argument("--rustflags", default="")
            p.add_argument(
                "--build-env",
                type=Path,
                help="JSON map of explicit toolchain/link environment",
            )
    p = commands.add_parser("text")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p = commands.add_parser("prepare-input")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--pretokenizer", required=True)
    p.add_argument("--build", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = commands.add_parser("corpus")
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--size-mib", type=int, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--cache", type=Path, default=ROOT / ".bench/shards")
    p = commands.add_parser("run")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--retry-failed", action="store_true")
    p = commands.add_parser("report")
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "lock":
        from .builds import create_lock

        print(
            create_lock(args.source, args.revision, args.lockfile, args.vendored_rayon)
        )
    elif args.command == "build":
        from .builds import build
        from .config import read

        print(
            build(
                args.source,
                args.revision,
                args.lockfile,
                args.cache,
                args.rustflags,
                args.vendored_rayon,
                read(args.build_env) if args.build_env else None,
            )["record_path"]
        )
    elif args.command == "text":
        from .inputs import text_manifest

        print(text_manifest(args.input, args.manifest)["input_id"])
    elif args.command == "prepare-input":
        from .inputs import prepared

        print(prepared(args.input, args.pretokenizer, args.build, args.out)["input_id"])
    elif args.command == "corpus":
        from .inputs import corpus

        print(corpus(args.dataset, args.size_mib, args.out, args.cache)["input_id"])
    elif args.command == "run":
        from .runs import run

        summary = run(args.config, args.out, args.retry_failed)
        if not summary["performance_conclusion_valid"]:
            raise SystemExit(1)
    else:
        from .reports import report

        print(report(args.out)["experiment_id"])


if __name__ == "__main__":
    main()
