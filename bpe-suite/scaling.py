#!/usr/bin/env python3
"""Compare worker scaling and memory for the three frozen BPE trainers."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time

import suite

PROTOCOL = 1
FIELDS = ("train_seconds", "elapsed_seconds", "train_cpu_seconds", "maxrss_kib")


def prepare(args, config, out):
    source = Path(args.prepared_suite).resolve()
    if source == out.resolve():
        raise ValueError("scaling needs a separate output directory")
    previous = suite.read(source / "prepared.json")
    if config["revisions"] != previous["config"]["revisions"]:
        raise ValueError("scaling revisions differ from the prepared source suite")
    if config["rustflags"] != previous["config"]["rustflags"]:
        raise ValueError("scaling compiler flags differ from the prepared suite")
    if config["arms"] != ["full", "hf", "peer"]:
        raise ValueError("compare Full, original HF, and the peer together")
    cpus = config["cpu_set"]
    if len(set(cpus)) != len(cpus) or not set(cpus).issubset(os.sched_getaffinity(0)):
        raise ValueError("invalid CPU set")
    if 1 not in config["workers"] or any(p < 1 or p > len(cpus) for p in config["workers"]):
        raise ValueError("worker counts require a single-core control and available CPUs")
    out.mkdir(parents=True, exist_ok=True)
    (out / "sources").mkdir(exist_ok=True)
    for arm in config["arms"]:
        link = out / "sources" / arm
        if not link.exists():
            link.symlink_to(source / "sources" / arm, target_is_directory=True)
        runner = out / "runners" / arm
        if not runner.exists():
            shutil.copytree(source / "runners" / arm, runner)
        shutil.copy2(source / "common.Cargo.lock", runner / "Cargo.lock")
    shutil.copy2(source / "common.Cargo.lock", out / "common.Cargo.lock")
    (out / "models").mkdir(exist_ok=True)
    for case in config["cases"]:
        if not Path(case["input"]).is_file():
            raise FileNotFoundError(case["input"])
        shutil.copy2(source / "models" / f"{case['name']}.json", out / "models" / f"{case['name']}.json")
    (out / "smoke").mkdir(exist_ok=True)
    shutil.copy2(source / "smoke/input.txt", out / "smoke/input.txt")
    for name in ("smoke_whitespace", "smoke_bytelevel", "smoke_affixes"):
        shutil.copy2(source / "models" / f"{name}.json", out / "models" / f"{name}.json")
    suite.write(out / "prepared.json", dict(protocol=PROTOCOL, stage="preliminary",
        config=config, source_suite=str(source), source_revisions=previous["revisions"],
        common_skeleton=previous["common_skeleton"], source_correctness=suite.read(source / "smoke.json"),
        rustc=subprocess.check_output([suite.RUSTC, "-Vv"], text=True),
        cpu=subprocess.check_output(["lscpu", "-J"], text=True), affinity=cpus,
        cgroup_cpu_controls={str(p): p.read_text().strip() if p.exists() else None for p in
            (Path("/sys/fs/cgroup/cpu.max"), Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"),
             Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us"), Path("/sys/fs/cgroup/cpuset.cpus.effective"))},
        datasets={c["name"]: dict(bytes=Path(c["input"]).stat().st_size) for c in config["cases"]},
        created_unix=time.time()))


def check(config, out):
    prepared = suite.read(out / "prepared.json")
    if prepared["protocol"] != PROTOCOL or prepared["config"] != config:
        raise ValueError("scaling parameters changed; use a new output directory")


def build(args, config, out):
    check(config, out)
    target = Path(args.release_cache or out / "cache/build").resolve()
    target.mkdir(parents=True, exist_ok=True)
    (out / "binaries").mkdir(exist_ok=True)
    (out / "build-logs").mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(RUSTFLAGS=config["rustflags"], CARGO_BUILD_JOBS="2", RUSTC=suite.RUSTC)
    for arm in config["arms"]:
        print(f"building scaling arm {arm}", flush=True)
        command = [suite.CARGO, "build", "--release", "--offline", "--locked", "--manifest-path",
                   str(out / "runners" / arm / "Cargo.toml"), "--target-dir", str(target)]
        with (out / "build-logs" / f"{arm}.log").open("w") as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"scaling build failed: {arm}")
        shutil.copy2(target / "release/bpe-suite-runner", out / "binaries" / arm)
    suite.write(out / "build.json", dict(arms=config["arms"], completed_unix=time.time()))


def execute(config, out, case, arm, workers, directory):
    run_config = {**config, "workers": workers, "cpu_affinity": config["cpu_set"][:workers]}
    row = suite.execute(out, run_config, case, arm, directory)
    row["workers"] = workers
    suite.write(directory / "result.json", row)
    return row


def smoke(config, out):
    check(config, out)
    cases = [dict(name="smoke_whitespace", split="whitespace", vocab_size=750, min_frequency=2),
             dict(name="smoke_bytelevel", split="bytelevel_regex", vocab_size=750, min_frequency=2),
             dict(name="smoke_affixes", split="whitespace", vocab_size=750, min_frequency=0,
                  prefix="##", suffix="</w>", max_token_length=18)]
    count = 0
    for case in cases:
        case["input"] = str(out / "smoke/input.txt")
        for workers in config["workers"]:
            for arm in config["arms"]:
                row = execute(config, out, case, arm, workers,
                              out / "smoke" / case["name"] / f"w{workers}" / arm)
                if row["status"] != "ok":
                    raise RuntimeError(f"scaling smoke failed: {case['name']} w{workers} {arm}")
                count += 1
    suite.write(out / "smoke.json", dict(passed=True, runs=count))
    print(f"scaling model differential passed in {count} smoke runs", flush=True)


def cell_order(config, block):
    cells = [(p, arm) for p in config["workers"] for arm in config["arms"]]
    shift = block * 4 % len(cells)
    cells = cells[shift:] + cells[:shift]
    return list(reversed(cells)) if block % 2 else cells


def run(config, out):
    check(config, out)
    if not suite.read(out / "smoke.json")["passed"]:
        raise ValueError("scaling smoke failed")
    workers = config["warmup_workers"]
    for case in config["cases"]:
        for arm in config["arms"]:
            directory = out / "warmup" / case["name"] / f"w{workers}" / arm
            if (directory / "result.json").exists():
                row = suite.read(directory / "result.json")
            else:
                print(f"scaling warmup {case['name']} w{workers} {arm}", flush=True)
                row = execute(config, out, case, arm, workers, directory)
            if row["status"] != "ok":
                report(out)
                raise RuntimeError(f"scaling warmup failed: {case['name']} {arm} ({row['status']})")
    for case in config["cases"]:
        for block in range(config["repetitions"]):
            directory = out / "runs" / case["name"] / f"block-{block + 1:02d}"
            if (directory / "block.json").exists():
                continue
            if directory.exists():
                directory.rename(directory.with_name(directory.name + f".interrupted-{time.time_ns()}"))
            rows = []
            order = cell_order(config, block)
            for workers, arm in order:
                print(f"scaling {case['name']} block {block + 1}/{config['repetitions']} w{workers} {arm}", flush=True)
                row = execute(config, out, case, arm, workers, directory / f"w{workers}" / arm)
                rows.append(row)
                if row["status"] != "ok":
                    suite.write(directory / "block.json", dict(order=order, comparison_valid=False, results=rows))
                    report(out)
                    raise RuntimeError(f"scaling timing failed: {case['name']} w{workers} {arm}")
            suite.write(directory / "block.json", dict(order=order, comparison_valid=True, results=rows))
            report(out)


def summarized(samples, fields):
    return {field + "_" + label: operation(r[field] for r in samples)
            for field in fields for label, operation in
            (("median", statistics.median), ("min", min), ("max", max))}


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def report(out):
    samples, failures, orders, raw_scaling, raw_comparisons = [], [], [], [], []
    for path in sorted((out / "runs").glob("*/block-*/block.json")):
        if ".interrupted-" in str(path):
            continue
        block = suite.read(path)
        case, block_name = path.parts[-3:-1]
        failures.extend(dict(block=block_name, **r)
                        for r in block["results"] if r["status"] != "ok")
        if not block["comparison_valid"]:
            continue
        orders.append(dict(case=case, block=block_name, order=block["order"]))
        cells = {(r["arm"], r["workers"]): r["metrics"] for r in block["results"]}
        for row in block["results"]:
            arm, workers, metrics = row["arm"], row["workers"], row["metrics"]
            samples.append(dict(block=block_name, **row))
            single = cells[(arm, 1)]
            speed = single["train_seconds"] / metrics["train_seconds"]
            raw_scaling.append(dict(case=case, block=block_name, arm=arm, workers=workers,
                train_speedup=speed, elapsed_speedup=single["elapsed_seconds"] / metrics["elapsed_seconds"],
                parallel_efficiency=speed / workers,
                train_cpu_ratio=metrics["train_cpu_seconds"] / single["train_cpu_seconds"],
                hwm_ratio=metrics["maxrss_kib"] / single["maxrss_kib"]))
            if arm != "full":
                full = cells[("full", workers)]
                raw_comparisons.append(dict(case=case, block=block_name, arm=arm, baseline="full",
                    workers=workers, train_ratio=metrics["train_seconds"] / full["train_seconds"],
                    elapsed_ratio=metrics["elapsed_seconds"] / full["elapsed_seconds"],
                    train_cpu_ratio=metrics["train_cpu_seconds"] / full["train_cpu_seconds"],
                    hwm_ratio=metrics["maxrss_kib"] / full["maxrss_kib"]))
    summary = []
    for case, arm, workers in sorted({(r["case"], r["arm"], r["workers"]) for r in samples}):
        rows = [r for r in samples if (r["case"], r["arm"], r["workers"]) == (case, arm, workers)]
        metrics = [r["metrics"] for r in rows]
        entry = dict(case=case, arm=arm, workers=workers, n=len(rows), **summarized(metrics, FIELDS))
        for field in ("sampled_peak_rss_bytes", "sampled_peak_swap_bytes"):
            entry.update(summarized(rows, (field,)))
        summary.append(entry)
    scaling, comparisons = [], []
    for raw, destination, fields in (
        (raw_scaling, scaling, ("train_speedup", "elapsed_speedup", "parallel_efficiency", "train_cpu_ratio", "hwm_ratio")),
        (raw_comparisons, comparisons, ("train_ratio", "elapsed_ratio", "train_cpu_ratio", "hwm_ratio"))):
        for case, arm, workers in sorted({(r["case"], r["arm"], r["workers"]) for r in raw}):
            rows = [r for r in raw if (r["case"], r["arm"], r["workers"]) == (case, arm, workers)]
            entry = dict(case=case, arm=arm, workers=workers, n=len(rows), **summarized(rows, fields))
            if destination is comparisons:
                entry["baseline"] = "full"
            destination.append(entry)
    warmups = [dict(path=str(p), **suite.read(p)) for p in sorted((out / "warmup").glob("*/w*/*/result.json"))]
    suite.write(out / "summary.json", dict(stage="preliminary", protocol=PROTOCOL,
        valid_samples=len(samples), valid_blocks=len(orders), summary=summary, scaling_speedups=scaling,
        algorithm_comparisons=comparisons, raw_samples=samples, raw_scaling=raw_scaling,
        raw_algorithm_comparisons=raw_comparisons, block_orders=orders, failed_runs=failures,
        warmups=warmups, warmup_failures=[r for r in warmups if r["status"] != "ok"]))
    for name, rows in (("summary.csv", summary), ("scaling-speedups.csv", scaling),
                       ("algorithm-comparisons.csv", comparisons)):
        write_csv(out / name, rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "build", "smoke", "run", "report", "all"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prepared-suite", type=Path)
    parser.add_argument("--release-cache", type=Path)
    args = parser.parse_args()
    config, out = suite.read(args.config), args.out.resolve()
    commands = ("prepare", "build", "smoke", "run", "report") if args.command == "all" else (args.command,)
    for command in commands:
        if command == "prepare":
            if args.prepared_suite is None:
                parser.error("prepare requires --prepared-suite")
            prepare(args, config, out)
        elif command == "build": build(args, config, out)
        elif command == "smoke": smoke(config, out)
        elif command == "run": run(config, out)
        else: report(out)


if __name__ == "__main__":
    main()
