#!/usr/bin/env python3
"""Run a preliminary BPE comparison from recorded Git revisions."""
import argparse
import csv
import filecmp
import io
import json
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import tarfile
import time

from variants import FULL_ARMS, substitute

HERE = Path(__file__).resolve().parent
CARGO = shutil.which("cargo") or str(Path.home() / ".cargo/bin/cargo")
RUSTC = shutil.which("rustc") or str(Path.home() / ".cargo/bin/rustc")
ARMS = (*FULL_ARMS, "hf", "peer", "peer_no_word_arena", "hf_native", "peer_native")
PROTOCOL = 2


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def archive(repo, revision, destination, paths):
    destination.mkdir(parents=True, exist_ok=True)
    data = subprocess.check_output(["git", "-C", str(repo), "archive", revision, *paths])
    with tarfile.open(fileobj=io.BytesIO(data)) as bundle:
        bundle.extractall(destination, filter="data")


def available_memory():
    return next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemAvailable:")) * 1024


def prepare(args, config, out):
    repo = Path(args.repo).resolve()
    revisions = {key: subprocess.check_output(["git", "-C", str(repo), "rev-parse", ref + "^{commit}"],
                                              text=True).strip()
                 for key, ref in config["revisions"].items()}
    original = out / "originals"
    for arm in ("full", "hf", "peer"):
        if not (original / arm).exists():
            archive(repo, revisions[arm], original / arm, ["tokenizers", "LICENSE"])
    if not (original / "peer_before_arena").exists():
        archive(repo, revisions["peer_before_arena"], original / "peer_before_arena",
                ["tokenizers/tk-train/src/trainers/bpe"])
    descriptions = {}
    for arm in ARMS:
        source = out / "sources" / arm
        native = arm.endswith("_native")
        if not source.exists():
            base = arm.removesuffix("_native") if native else "full"
            shutil.copytree(original / base, source)
            if arm in ("hf", "peer", "peer_no_word_arena"):
                origin = "peer_before_arena" if arm == "peer_no_word_arena" else arm
                target = source / "tokenizers/tk-train/src/trainers/bpe"
                shutil.rmtree(target)
                shutil.copytree(original / origin / "tokenizers/tk-train/src/trainers/bpe", target)
            elif not native:
                substitute(source / "tokenizers", arm, HERE / "templates")
        descriptions[arm] = {"source": str(source), "native_correctness_only": native}
        runner = out / "runners" / arm
        (runner / "src").mkdir(parents=True, exist_ok=True)
        runner_text = (HERE / "runner.rs").read_text()
        if arm == "peer_native":
            # The older frontend lacks the offset argument; ByteLevel text is identical.
            anchor = ".normalize(piece, 0)?"
            if runner_text.count(anchor) != 1: raise ValueError("normalizer adapter anchor changed")
            runner_text = runner_text.replace(anchor, ".normalize(piece)?")
            descriptions[arm]["runner_adapter"] = "older ByteLevel normalizer arity"
        (runner / "src/main.rs").write_text(runner_text)
        relative = os.path.relpath(source / "tokenizers", runner)
        (runner / "Cargo.toml").write_text(f'''[package]
name = "bpe-suite-runner"
version = "0.1.0"
edition = "2024"
[dependencies]
tk-train = {{ path = "{relative}/tk-train", default-features = false }}
tk-encode = {{ path = "{relative}/tk-encode", default-features = false }}
ahash = "0.8.12"
compact_str = "0.9"
serde = {{ version = "1", features = ["derive"] }}
serde_json = "1"
libc = "0.2"
[profile.release]
opt-level = 3
lto = "fat"
codegen-units = 1
debug = false
strip = false
''')
    for case in config["cases"]:
        if not Path(case["input"]).is_file(): raise FileNotFoundError(case["input"])
    write(out / "prepared.json", {"protocol": PROTOCOL, "stage": config["stage"], "config": config,
          "revisions": revisions, "common_skeleton": revisions["full"], "arms": descriptions,
          "datasets": {c["name"]: {"path": c["input"], "bytes": Path(c["input"]).stat().st_size}
                       for c in config["cases"]},
          "rustc": subprocess.check_output([RUSTC, "-Vv"], text=True),
          "cpu": subprocess.check_output(["lscpu", "-J"], text=True),
          "affinity": sorted(os.sched_getaffinity(0)), "created_unix": time.time()})
    print(f"prepared {len(ARMS)} source arms", flush=True)


def check_config(out, config):
    recorded = read(out / "prepared.json")
    if recorded["protocol"] != PROTOCOL or recorded["config"] != config:
        raise ValueError("protocol or parameters changed; use a new output directory")


def build(args, config, out):
    check_config(out, config)
    target = Path(args.release_cache or out / "cache/release").resolve()
    target.mkdir(parents=True, exist_ok=True)
    (out / "binaries").mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update({"RUSTFLAGS": config["rustflags"], "CARGO_BUILD_JOBS": "2", "RUSTC": RUSTC,
                "PATH": str(Path(CARGO).parent) + os.pathsep + env.get("PATH", "")})
    lock = out / "common.Cargo.lock"
    # Resolve once, then use this exact lock for all measured arms.
    first = out / "runners/full/Cargo.toml"
    subprocess.run([CARGO, "generate-lockfile", "--offline", "--manifest-path", str(first)], env=env, check=True)
    shutil.copy2(first.with_name("Cargo.lock"), lock)
    for arm in ARMS:
        if shutil.disk_usage(target).free < 4 * 2**30: raise RuntimeError("less than 4 GiB free before build")
        runner = out / "runners" / arm
        cmd = [CARGO, "build", "--release", "--offline", "--manifest-path", str(runner / "Cargo.toml"),
               "--target-dir", str(target)]
        if not arm.endswith("_native"):
            shutil.copy2(lock, runner / "Cargo.lock")
            cmd.append("--locked")
        log = out / "build-logs" / f"{arm}.log"
        log.parent.mkdir(exist_ok=True)
        print(f"building {arm}", flush=True)
        with log.open("w") as stream:
            result = subprocess.run(cmd, env=env, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode: raise RuntimeError(f"build failed for {arm}; see {log}")
        shutil.copy2(target / "release/bpe-suite-runner", out / "binaries" / arm)
    write(out / "build.json", {"protocol": PROTOCOL, "arms": list(ARMS), "completed_unix": time.time()})


def execute(out, config, case, arm, directory):
    directory.mkdir(parents=True, exist_ok=True)
    model = directory / "model.json"
    job = {key: case.get(key) for key in ("input", "split", "vocab_size", "min_frequency",
                                        "prefix", "suffix", "max_token_length")}
    job.update(workers=config["workers"], output=str(model))
    write(directory / "job.json", job)
    row = {"arm": arm, "case": case["name"], "started_unix": time.time(),
           "protocol": PROTOCOL, "status": "running", "loadavg": os.getloadavg()}
    if available_memory() < config["min_available_gib"] * 2**30:
        row["status"] = "resource_gate_before_run"
        write(directory / "result.json", row)
        return row
    cmd = [str(out / "binaries" / arm), str(directory / "job.json")]
    if config.get("cpu_affinity"):
        taskset = shutil.which("taskset")
        if taskset is None:
            raise RuntimeError("taskset is required for CPU-limited measurements")
        affinity = sorted(config["cpu_affinity"])
        if not set(affinity).issubset(os.sched_getaffinity(0)):
            raise ValueError("requested CPUs are outside the supervisor affinity")
        cmd = [taskset, "--cpu-list", ",".join(map(str, affinity)), *cmd]
        row["cpu_affinity"] = affinity
    row["command"] = cmd
    env = os.environ.copy()
    env.update({"RAYON_NUM_THREADS": str(config["workers"]), "TOKENIZERS_PARALLELISM": "true"})
    start = time.monotonic()
    peak_rss = peak_swap = 0
    minimum_available = available_memory()
    reason = None
    with (directory / "stdout.log").open("w") as stdout, (directory / "stderr.log").open("w") as stderr:
        proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr, env=env, start_new_session=True)
        while proc.poll() is None:
            available = available_memory()
            minimum_available = min(minimum_available, available)
            try:
                status = Path(f"/proc/{proc.pid}/status").read_text()
                values = {line.split(":", 1)[0]: int(line.split()[1]) * 1024
                          for line in status.splitlines() if line.startswith(("VmRSS:", "VmSwap:"))}
                peak_rss = max(peak_rss, values.get("VmRSS", 0))
                peak_swap = max(peak_swap, values.get("VmSwap", 0))
            except FileNotFoundError: pass
            if available < config["min_available_gib"] * 2**30: reason = "memory_guard"
            elif peak_rss > config["max_process_rss_gib"] * 2**30: reason = "rss_guard"
            elif time.monotonic() - start > config["timeout_seconds"]: reason = "timeout"
            if reason:
                try: os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                break
            time.sleep(0.1)
        row.update(returncode=proc.wait(), supervisor_wall_seconds=time.monotonic() - start,
                   sampled_peak_rss_bytes=peak_rss, sampled_peak_swap_bytes=peak_swap,
                   minimum_host_available_bytes=minimum_available)
    row["status"] = reason or ("ok" if row["returncode"] == 0 else "process_error")
    if row["status"] == "ok":
        try:
            row["metrics"] = json.loads((directory / "stdout.log").read_text())
            for field in ("train_seconds", "elapsed_seconds", "maxrss_kib", "actual_vocab", "actual_merges"):
                if field not in row["metrics"]: raise ValueError(f"missing {field}")
            if config.get("expected_phase") and row["metrics"].get("phase") != config["expected_phase"]:
                raise ValueError("runner measured a different phase")
            if not model.is_file(): raise ValueError("missing model output")
            reference = out / "models" / f"{case['name']}.json"
            reference.parent.mkdir(exist_ok=True)
            if reference.exists() and not filecmp.cmp(model, reference, shallow=False):
                row["status"] = "model_mismatch"
            elif not reference.exists(): shutil.copy2(model, reference)
            if row["status"] == "ok": model.unlink()
        except (ValueError, KeyError) as error:
            row.update(status="invalid_output", error=str(error))
    write(directory / "result.json", row)
    if row["status"] == "model_mismatch":
        raise ValueError(f"exact vocabulary IDs or ordered merges differ: {case['name']} {arm}")
    return row


def smoke(config, out):
    check_config(out, config)
    fixture = out / "smoke/input.txt"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(("aaaa aaab abab baba bbbb roses red reddish are blue bluer big bigger "
                        "中文字符 中文词语 韩国 日本語 café café naïve GPT-2 12345 🙂\n") * 37
                       + " ".join(f"sharedprefix{i:05d}sharedsuffix" for i in range(2100)) + "\n")
    cases = [dict(name="smoke_whitespace", split="whitespace", vocab_size=750, min_frequency=2),
             dict(name="smoke_bytelevel", split="bytelevel_regex", vocab_size=750, min_frequency=2),
             dict(name="smoke_affixes", split="whitespace", vocab_size=750, min_frequency=0,
                  prefix="##", suffix="</w>", max_token_length=18)]
    count = 0
    for case in cases:
        case["input"] = str(fixture)
        for arm in ARMS:
            row = execute(out, config, case, arm, out / "smoke" / case["name"] / arm)
            if row["status"] != "ok": raise RuntimeError(f"smoke failed: {case['name']} {arm}")
            count += 1
    write(out / "smoke.json", {"protocol": PROTOCOL, "passed": True, "runs": count})
    print(f"exact vocabulary/merge differential passed in {count} smoke runs", flush=True)


def run(config, out):
    check_config(out, config)
    if not read(out / "smoke.json")["passed"]: raise ValueError("smoke validation failed")
    cases = {case["name"]: case for case in config["cases"]}
    warmed = set()
    for group in config["groups"]:
        for name in group["cases"]:
            for arm in group["arms"]:
                key = (name, arm)
                if key in warmed: continue
                warmed.add(key)
                folder = out / "warmup" / name / arm
                if (folder / "result.json").exists():
                    row = read(folder / "result.json")
                else:
                    print(f"warmup {name} {arm}", flush=True)
                    row = execute(out, config, cases[name], arm, folder)
                if row["status"] != "ok":
                    raise RuntimeError(f"warmup failed: {name} {arm} ({row['status']}); adjust the profile before timing")
    for group in config["groups"]:
        for name in group["cases"]:
            for block in range(group["repetitions"]):
                folder = out / "runs" / group["name"] / name / f"block-{block + 1:02d}"
                done = folder / "block.json"
                if done.exists(): continue
                if folder.exists(): folder.rename(folder.with_name(folder.name + f".interrupted-{time.time_ns()}"))
                arms = group["arms"]
                order = arm_order(arms, block)
                rows = []
                for arm in order:
                    print(f"{group['name']} {name} block {block + 1}/{group['repetitions']} {arm}", flush=True)
                    rows.append(execute(out, config, cases[name], arm, folder / arm))
                write(done, {"order": order, "comparison_valid": all(r["status"] == "ok" for r in rows),
                             "results": rows})
                report(out)


def arm_order(arms, block):
    shift = block % len(arms)
    order = arms[shift:] + arms[:shift]
    # With two arms, reversing odd rotations would cancel the alternation.
    if len(arms) > 2 and block % 2: order = list(reversed(order))
    return order


def report(out):
    rows, failed, pairs = [], [], []
    fields = ("train_seconds", "elapsed_seconds", "train_cpu_seconds", "maxrss_kib")
    valid_blocks = 0
    for path in sorted((out / "runs").glob("*/*/block-*/block.json")):
        if ".interrupted-" in str(path): continue
        block = read(path)
        group, case = path.parts[-4:-2]
        if block["comparison_valid"]:
            valid_blocks += 1
            by_arm = {r["arm"]: r["metrics"] for r in block["results"]}
            baseline = "full" if "full" in by_arm else block["order"][0]
            # The supplementary peer arena group uses the unchanged peer as control.
            if "peer" in by_arm and "full" not in by_arm: baseline = "peer"
            for arm, metrics in by_arm.items():
                if arm == baseline: continue
                pairs.append({"group": group, "case": case, "block": path.parent.name,
                              "arm": arm, "baseline": baseline,
                              **{field + "_ratio": metrics[field] / by_arm[baseline][field]
                                 for field in fields if by_arm[baseline][field] > 0}})
        for row in block["results"]:
            if row["status"] != "ok": failed.append({"group": group, "case": case, **row})
            if block["comparison_valid"]:
                rows.append({"group": group, "case": case, "block": path.parent.name,
                             "arm": row["arm"], **row["metrics"]})
    summary = []
    for key in sorted({(r["group"], r["case"], r["arm"]) for r in rows}):
        samples = [r for r in rows if (r["group"], r["case"], r["arm"]) == key]
        summary.append({"group": key[0], "case": key[1], "arm": key[2], "n": len(samples),
            **{f"{field}_median": statistics.median(r[field] for r in samples)
               for field in fields},
            "train_seconds_min": min(r["train_seconds"] for r in samples),
            "train_seconds_max": max(r["train_seconds"] for r in samples)})
    comparisons = []
    for key in sorted({(r["group"], r["case"], r["arm"], r["baseline"]) for r in pairs}):
        samples = [r for r in pairs if (r["group"], r["case"], r["arm"], r["baseline"]) == key]
        entry = dict(group=key[0], case=key[1], arm=key[2], baseline=key[3], n=len(samples))
        for field in fields:
            values = [r[field + "_ratio"] for r in samples if field + "_ratio" in r]
            if values:
                entry.update({field + "_ratio_median": statistics.median(values),
                              field + "_ratio_min": min(values), field + "_ratio_max": max(values)})
        comparisons.append(entry)
    warmup_failures = []
    for path in sorted((out / "warmup").glob("*/*/result.json")):
        row = read(path)
        if row["status"] != "ok": warmup_failures.append({"path": str(path), **row})
    write(out / "summary.json", {"stage": "preliminary", "summary": summary,
          "valid_paired_samples": len(rows), "valid_paired_blocks": valid_blocks,
          "failed_runs": failed, "warmup_failures": warmup_failures, "raw_samples": rows,
          "paired_comparisons": comparisons, "raw_paired_ratios": pairs})
    if summary:
        with (out / "summary.csv").open("w") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
            writer.writeheader(); writer.writerows(summary)
    if comparisons:
        with (out / "comparisons.csv").open("w") as stream:
            columns = list(dict.fromkeys(column for row in comparisons for column in row))
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader(); writer.writerows(comparisons)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "build", "smoke", "run", "report", "all"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo", required=True, help="tokenizers Git repository containing the recorded revisions")
    parser.add_argument("--release-cache")
    args = parser.parse_args()
    config = read(args.config)
    if config["stage"] != "preliminary": raise ValueError("formal review/freeze is a later phase")
    out = Path(args.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    operations = {"prepare": lambda: prepare(args, config, out), "build": lambda: build(args, config, out),
                  "smoke": lambda: smoke(config, out), "run": lambda: run(config, out), "report": lambda: report(out)}
    for name in operations if args.command == "all" else [args.command]: operations[name]()


if __name__ == "__main__": main()
