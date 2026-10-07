"""Single-writer process supervision and append-only attempt history."""

import fcntl
import math
import os
import platform
import signal
import subprocess
import time
import uuid
from pathlib import Path

from .builds import files, read_cpu
from .builds import validate as validate_build
from .config import PROTOCOL, ROOT, environment, identity, load, read, write
from .inputs import validate as validate_input
from .topology import cgroup_memory, numa_prefix

TERMINAL = {
    "ok",
    "model_mismatch",
    "resource_guard",
    "timeout",
    "process_error",
    "invalid_output",
    "interrupted",
}


def event(out, kind, **fields):
    import json

    with (out / "events.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                dict(event=kind, time_unix=time.time(), **fields), allow_nan=False
            )
            + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())


def host():
    return dict(
        platform=platform.platform(),
        hostname=platform.node(),
        cpu=read_cpu(subprocess.check_output(["lscpu", "-J"], text=True)),
        topology=subprocess.check_output(
            ["lscpu", "-p=CPU,CORE,SOCKET,NODE"], text=True
        ),
        supervisor_affinity=sorted(os.sched_getaffinity(0)),
        cgroup_memory=[{k: v for k, v in row.items() if k != "current"} for row in cgroup_memory()],
    )


def plan(config):
    cfg = load(config)
    arms = {name: validate_build(arm["build"]) for name, arm in cfg["arms"].items()}
    inputs = {
        case["name"]: validate_input(
            case["input_manifest"], cfg["mode"], case["pretokenizer"]
        )
        for case in cfg["cases"]
    }
    semantic = __import__("copy").deepcopy(cfg)
    for name, arm in semantic["arms"].items():
        arm["build"] = arms[name]["build_id"]
    for case in semantic["cases"]:
        case["input_manifest"] = inputs[case["name"]]["input_id"]
    static = host()
    provenance = dict(
        config=semantic,
        builds={
            name: dict(
                build_id=arm["build_id"],
                binary_sha256=arm["binary_sha256"],
                runner_sha256=arm["runner_sha256"],
            )
            for name, arm in arms.items()
        },
        inputs={
            name: dict(input_id=value["input_id"], sha256=value["sha256"])
            for name, value in inputs.items()
        },
        host=static,
        protocol_version=PROTOCOL,
        comparator_version=1,
        supervisor_sha256=identity(files(ROOT / "bench")),
        child_environments={
            name: environment(cfg["arms"][name]["environment"]) for name in arms
        },
    )
    return cfg, arms, inputs, provenance


def available_memory():
    available = next(
        int(line.split()[1]) * 1024
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith("MemAvailable:")
    )
    return min([available] + [max(0, r["limit"] - r["current"])
                              for r in cgroup_memory() if r["limit"] is not None])


def stop(proc):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def canonical_model(path):
    model = read(path)
    if (
        not isinstance(model, list)
        or len(model) != 2
        or any(not isinstance(v, list) for v in model)
    ):
        raise ValueError("model must contain vocabulary pairs and ordered merges")
    vocab, merges = model
    if any(
        not isinstance(e, list)
        or len(e) != 2
        or not isinstance(e[0], str)
        or type(e[1]) is not int
        or e[1] < 0
        for e in vocab
    ):
        raise ValueError("invalid vocabulary")
    if len({e[0] for e in vocab}) != len(vocab) or len({e[1] for e in vocab}) != len(
        vocab
    ):
        raise ValueError("duplicate word or token ID")
    if any(
        not isinstance(e, list) or len(e) != 2 or any(not isinstance(s, str) for s in e)
        for e in merges
    ):
        raise ValueError("invalid ordered merges")
    return [sorted(vocab, key=lambda e: e[0]), merges]


def validate_result(value, job, cpus, model):
    if not isinstance(value, dict):
        raise ValueError("runner result must be an object")
    if not isinstance(value.get("metrics"), dict) or not isinstance(
        value.get("output"), dict
    ):
        raise ValueError("metrics and output must be objects")
    for field in ("protocol_version", "attempt_id", "build_id", "input_id", "mode"):
        if value.get(field) != job[field]:
            raise ValueError(f"wrong {field}")
    if value.get("workers_requested") != job["workers"] or value.get(
        "effective_affinity"
    ) != sorted(cpus):
        raise ValueError("effective workers/affinity mismatch")
    boundary = {
        "core": "public-do-train-before-serialization",
        "pipeline": "public-feed-and-train-before-serialization",
    }[job["mode"]]
    if value.get("timing_boundary") != boundary:
        raise ValueError("wrong timing boundary")
    metrics = value["metrics"]
    required = [
        "train_seconds",
        "train_cpu_seconds",
        "process_hwm_kib_before_validation",
    ]
    required += (
        ["feed_seconds", "pipeline_seconds", "pipeline_cpu_seconds"]
        if job["mode"] == "pipeline"
        else ["load_seconds"]
    )
    if not set(required).issubset(metrics):
        raise ValueError("missing required metrics")
    for field, number in metrics.items():
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
            or number < 0
        ):
            raise ValueError(f"invalid {field}")
    for field, actual in [
        ("actual_vocab", len(model[0])),
        ("actual_merges", len(model[1])),
    ]:
        if (
            type(value["output"].get(field)) is not int
            or value["output"][field] != actual
        ):
            raise ValueError(f"wrong {field}")
    if value["output"].get("model_path") != job["output"]:
        raise ValueError("wrong model path")
    return metrics


def execute(out, cfg, case, workers, arm, build, inp, slot, compare_model=True):
    attempt_id = uuid.uuid4().hex
    folder = out / "attempts" / attempt_id
    folder.mkdir(parents=True)
    cpus = cfg["execution"]["cpu_set"][:workers]
    job = dict(
        protocol_version=PROTOCOL,
        attempt_id=attempt_id,
        build_id=build["build_id"],
        input_id=inp["input_id"],
        mode=cfg["mode"],
        input=inp["data_path"],
        output=str(folder / "model.json"),
        workers=workers,
        pretokenizer=case["pretokenizer"],
        trainer=case["trainer"],
    )
    write(folder / "job.json", job)
    row = dict(
        attempt_id=attempt_id,
        slot=slot,
        case=case["name"],
        workers=workers,
        arm=arm,
        status="running",
        job=job,
        started_unix=time.time(),
        loadavg=os.getloadavg(),
        affinity=cpus,
    )
    write(folder / "result.json", row)
    event(out, "running", attempt_id=attempt_id, slot=slot)
    proc = None
    try:
        if available_memory() < cfg["execution"]["min_available_gib"] * 2**30:
            row.update(status="resource_guard", guard_reason="available_memory", reason="available memory before launch")
        else:
            cmd = numa_prefix(cfg["execution"].get("numa", {})) + [
                "taskset",
                "--cpu-list",
                ",".join(map(str, cpus)),
                build["binary_path"],
                str(folder / "job.json"),
            ]
            env = environment(cfg["arms"][arm]["environment"], workers)
            row["environment"] = env
            row["command"] = cmd
            start = time.monotonic()
            peak = swap = peak_hwm = 0
            minimum = available_memory()
            with (
                (folder / "stdout.log").open("w") as stdout,
                (folder / "stderr.log").open("w") as stderr,
                (folder / "memory.jsonl").open("w") as trace,
            ):
                proc = subprocess.Popen(
                    cmd, env=env, stdout=stdout, stderr=stderr, start_new_session=True
                )
                row["pid"] = proc.pid
                try:
                    row["process_start_ticks"] = (
                        Path(f"/proc/{proc.pid}/stat")
                        .read_text()
                        .split(") ", 1)[1]
                        .split()[19]
                    )
                except FileNotFoundError:
                    pass
                write(folder / "result.json", row)
                reason = None
                while proc.poll() is None:
                    memory = available_memory()
                    minimum = min(minimum, memory)
                    try:
                        values = {
                            line.split(":", 1)[0]: int(line.split()[1]) * 1024
                            for line in Path(f"/proc/{proc.pid}/status")
                            .read_text()
                            .splitlines()
                            if line.startswith(("VmRSS:", "VmSwap:", "VmHWM:"))
                        }
                        peak = max(peak, values.get("VmRSS", 0))
                        swap = max(swap, values.get("VmSwap", 0))
                        peak_hwm = max(peak_hwm, values.get("VmHWM", 0))
                        trace.write(__import__("json").dumps(dict(
                            elapsed_seconds=time.monotonic() - start, **values)) + "\n")
                    except FileNotFoundError:
                        pass
                    if memory < cfg["execution"]["min_available_gib"] * 2**30:
                        reason = "resource_guard"
                        row["guard_reason"] = "available_memory"
                    elif max(peak, peak_hwm) > cfg["execution"]["max_process_rss_gib"] * 2**30:
                        reason = "resource_guard"
                        row["guard_reason"] = "rss_limit"
                    elif swap > 0:
                        reason = "resource_guard"
                        row["guard_reason"] = "swap_detected"
                    elif cfg["execution"]["timeout_seconds"] > 0 and time.monotonic() - start > cfg["execution"]["timeout_seconds"]:
                        reason = "timeout"
                    if reason:
                        stop(proc)
                        break
                    time.sleep(0.02)
                row.update(
                    returncode=proc.wait(),
                    status=reason
                    or ("ok" if proc.returncode == 0 else "process_error"),
                    supervisor_wall_seconds=time.monotonic() - start,
                    sampled_peak_rss_bytes=peak,
                    process_peak_rss_bytes=max(peak, peak_hwm),
                    sampled_peak_swap_bytes=swap,
                    minimum_host_available_bytes=minimum,
                )
            if row["status"] == "ok":
                try:
                    model = canonical_model(folder / "model.json")
                    value = read(folder / "stdout.log")
                    row["metrics"] = validate_result(value, job, cpus, model)
                    row["runner_result"] = value
                    row["model_sha256"] = identity(model)
                    row["process_peak_rss_bytes"] = max(row["process_peak_rss_bytes"],
                        row["metrics"]["process_hwm_kib_before_validation"] * 1024)
                    # A short peak can occur between supervisor samples.
                    if row["process_peak_rss_bytes"] > cfg["execution"]["max_process_rss_gib"] * 2**30:
                        row.update(status="resource_guard", guard_reason="rss_limit")
                    if compare_model:
                        refs = out / "models"
                        refs.mkdir(exist_ok=True)
                        ref = refs / (case["name"] + ".json")
                        if not ref.exists():
                            if arm != "baseline":
                                raise ValueError("baseline reference must be established first")
                            write(ref, model)
                        reference = read(ref)
                        if reference != model:
                            row.update(status="model_mismatch", difference=first_difference(reference, model))
                except (ValueError, KeyError, TypeError, OSError) as error:
                    row.update(status="invalid_output", error=str(error))
    except BaseException as error:
        if proc:
            stop(proc)
        row.update(
            status="interrupted"
            if isinstance(error, (KeyboardInterrupt, SystemExit))
            else "process_error",
            error=str(error),
        )
        finish(out, folder, row)
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        return row
    finish(out, folder, row)
    return row


def first_difference(a, b):
    for name, x, y in zip(("vocabulary", "ordered_merges"), a, b):
        for index, (left, right) in enumerate(zip(x, y)):
            if left != right:
                return dict(component=name, index=index, baseline=left, candidate=right)
        if len(x) != len(y):
            return dict(component=name, baseline_length=len(x), candidate_length=len(y))
    return {}


def finish(out, folder, row):
    row["finished_unix"] = time.time()
    write(folder / "result.json", row)
    event(
        out,
        "finished",
        attempt_id=row["attempt_id"],
        status=row["status"],
        slot=row["slot"],
    )


def recover(out):
    for p in sorted((out / "attempts").glob("*/result.json")):
        row = read(p)
        if row["status"] != "running":
            continue
        pid = row.get("pid")
        if pid:
            try:
                ticks = (
                    Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()[19]
                )
                if ticks == row.get("process_start_ticks"):
                    os.killpg(pid, signal.SIGTERM)
                    # Refuse resume while orphan still consumes measurement resources.
                    time.sleep(0.1)
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            except FileNotFoundError:
                pass
        row.update(
            status="interrupted", reason="supervisor lost before terminal record"
        )
        finish(out, p.parent, row)


def schedule(cfg):
    arms = ["baseline"] + [name for name in cfg["arms"] if name != "baseline"]
    cells = [(case, w) for case in cfg["cases"] for w in cfg["execution"]["workers"]]
    for warmup in range(cfg["execution"]["warmups_per_cell"]):
        warmup_cells = cells if cfg["execution"].get("warmup_scope", "cell") == "cell" else [(cfg["cases"][0], max(cfg["execution"]["workers"]))]
        warmup_arms = arms if cfg["execution"].get("warmup_scope", "cell") == "cell" else ["baseline"]
        for case, w in warmup_cells:
            for arm in warmup_arms:
                yield case, w, arm, f"warmup:{warmup}:{case['name']}:{w}:{arm}"
    for block in range(cfg["execution"]["paired_blocks"]):
        rotated = cells[block % len(cells) :] + cells[: block % len(cells)]
        if block % 2:
            rotated = list(reversed(rotated))
        order = arms if block % 2 == 0 else list(reversed(arms))
        if len(arms) > 2:
            order = arms[block % len(arms) :] + arms[: block % len(arms)]
        for case, w in rotated:
            for arm in order:
                yield case, w, arm, f"block:{block}:{case['name']}:{w}:{arm}"


def run(config, out, retry_failed=False, continue_on_failure=False, observer=None):
    from .reports import report

    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with (out / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cfg, arms, inputs, spec = plan(config)
        path = out / "spec.json"
        if path.exists():
            if read(path) != spec:
                raise ValueError(
                    "experiment identity changed; use a new output directory"
                )
        else:
            write(path, spec)
            write(out / "environment.json", host())
            for name, build in arms.items():
                write(out / "builds" / f"{name}.json", build)
            for name, inp in inputs.items():
                write(out / "inputs" / f"{name}.json", inp)
            event(out, "experiment", experiment_id=identity(spec))
        recover(out)
        records = [read(p) for p in sorted((out / "attempts").glob("*/result.json"))]
        for case, w, arm, slot in schedule(cfg):
            previous = [r for r in records if r["slot"] == slot]
            if any(r["status"] == "ok" for r in previous):
                continue
            if previous and not retry_failed:
                if continue_on_failure:
                    continue
                report(out)
                raise ValueError(
                    "failed/interrupted attempt exists; use --retry-failed for an explicit diagnostic retry"
                )
            row = execute(out, cfg, case, w, arm, arms[arm], inputs[case["name"]], slot)
            records.append(row)
            if observer:
                observer(row)
            else:
                print(f"{slot}: {row['status']}", flush=True)
            if row["status"] != "ok":
                report(out)
                if continue_on_failure:
                    continue
                raise RuntimeError(f"attempt {row['attempt_id']}: {row['status']}")
        return report(out)
