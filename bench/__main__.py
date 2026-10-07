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
        p.add_argument(
            "--exclude-source-path",
            action="append",
            default=[],
            help="explicit tracked path/subtree omitted from a Git revision snapshot; recorded in build identity",
        )
        p.add_argument("--vendored-rayon", action="store_true")
        p.add_argument("--adapter", choices=("tk_train_v1", "tk_train_pr2348"), default="tk_train_v1")
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
    p = commands.add_parser("corpora", help="prepare all configured corpora in one command; retain shorter sources")
    p.add_argument("--config", type=Path, default=ROOT / "datasets/corpora.toml")
    p.add_argument("--size-mib", type=int, help="override the raw-text target for every corpus")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--cache", type=Path, default=ROOT / ".bench/shards")
    p = commands.add_parser("run")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--retry-failed", action="store_true")
    p = commands.add_parser("report")
    p.add_argument("--out", type=Path, required=True)
    p = commands.add_parser("bundle", help="build portable runners from Git source TOML")
    p.add_argument("--portable-release", action="store_true", help="require ordinary release builds without custom Rust flags")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--cache", type=Path, default=ROOT / ".bench/builds")
    p = commands.add_parser("suite", help="run corpus matrix and soft-target RSS growth from TOML")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--bundle", type=Path, default=Path("/opt/builds/bundle.json"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--phase", choices=("all", "matrix", "small", "growth"), default="all")
    p.add_argument("--retry-failed", action="store_true")
    p = commands.add_parser("suite-report", help="regenerate suite tables and plots")
    p.add_argument("--out", type=Path, required=True)
    p = commands.add_parser("suite-follow", help="log completed attempts from a running suite")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--started-file", type=Path)
    p.add_argument("--finished-file", type=Path)
    args = parser.parse_args()
    if args.command == "lock":
        from .builds import create_lock

        print(
            create_lock(
                args.source, args.revision, args.lockfile,
                args.vendored_rayon, args.exclude_source_path, args.adapter,
            )
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
                args.exclude_source_path,
                args.adapter,
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
    elif args.command == "corpora":
        from .corpora import prepare

        prepare(args.config, args.out, args.cache, args.size_mib)
    elif args.command == "bundle":
        from .bundle import build_bundle

        build_bundle(args.config, args.out, args.cache, args.portable_release)
    elif args.command == "suite":
        from .suite import suite

        if not suite(args.config, args.bundle, args.out, args.phase, args.retry_failed)["complete"]:
            raise SystemExit(1)
    elif args.command == "suite-report":
        from .suite_report import suite_report

        suite_report(args.out)
    elif args.command == "suite-follow":
        from .progress import follow

        follow(args.out, args.started_file, args.finished_file)
    else:
        from .reports import report

        print(report(args.out)["experiment_id"])


if __name__ == "__main__":
    main()
