"""Plain per-attempt logs and an empirical estimate of remaining suite time."""

import math
import statistics
import time
from pathlib import Path

from .config import read


def duration(seconds):
    if seconds is None:
        return "learning"
    seconds = max(0, round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:d}h{minutes:02d}m{seconds:02d}s" if hours else f"{minutes:d}m{seconds:02d}s"


def sizes(start, maximum, factor):
    size = min(start, maximum)
    while True:
        yield size
        if size == maximum:
            return
        size = min(maximum, math.ceil(size * factor))


class SuiteProgress:
    def __init__(self, cfg, arms, sources, phase="all", started=None, emit=print):
        self.cfg = cfg
        self.started = time.time() if started is None else started
        self.emit = emit
        self.pending = {}
        self.completed = set()
        self.seen = set()
        self.samples = []
        execution = cfg["execution"]
        for folder, enabled, small in (
            ("matrix", phase in ("all", "matrix"), False),
            ("small-matrix", cfg["small"]["enabled"] and phase in ("all", "small"), True),
        ):
            if not enabled:
                continue
            for case in cfg["cases"]:
                size = cfg["small"]["size_mib"] if small else case["size_mib"]
                for worker in execution["workers"]:
                    for arm in arms:
                        warmups = execution["warmups"] if case == cfg["cases"][0] and worker == max(execution["workers"]) and arm == "baseline" and (folder == "matrix" or phase == "small") else 0
                        for kind, count in (("warmup", warmups), ("block", execution["repetitions"])):
                            for index in range(count):
                                slot = f"{kind}:{index}:{case['name']}:{worker}:{arm}"
                                self.pending[folder, slot] = (case["name"], arm, worker, size)
        growth = cfg["growth"]
        if growth["enabled"] and phase in ("all", "growth"):
            for case in cfg["cases"]:
                if not case["growth"]:
                    continue
                maximum = min(growth["max_mib"], sources[case["name"]]["bytes"] >> 20)
                for arm in arms:
                    folder = f"growth/{case['name']}/{arm}"
                    for size in sizes(growth["start_mib"], maximum, growth["factor"]):
                        self.pending[folder, f"growth:{size}:0:{arm}"] = (case["name"], arm, growth["workers"], size)
        self.targets = self.pending.copy()

    def estimate(self, target):
        if not self.samples:
            return None
        case, arm, worker, size = target
        # Prefer the same corpus and algorithm; use broader observations only
        # while their own first measurements have not completed.
        candidates = [s for s in self.samples if s[0][:2] == (case, arm)]
        if not candidates:
            candidates = [s for s in self.samples if s[0][1] == arm] or self.samples
        nearest_worker = min((s[0][2] for s in candidates), key=lambda w: abs(math.log(w / worker)))
        candidates = [s for s in candidates if s[0][2] == nearest_worker]
        by_size = {}
        for key, seconds in candidates:
            by_size.setdefault(key[3], []).append(seconds)
        medians = {n: statistics.median(values) for n, values in by_size.items()}
        nearest = min(medians, key=lambda n: abs(math.log(n / size)))
        exponent = 1.0
        if len(medians) > 1:
            low, high = min(medians), max(medians)
            exponent = max(0.0, min(2.0, math.log(medians[high] / medians[low]) / math.log(high / low)))
        # Scaling by cores before observing them can imply an unrealistic
        # speedup; retain the nearest observed worker's wall time instead.
        return medians[nearest] * (size / nearest) ** exponent

    def remaining(self, active=None):
        estimates = [self.estimate(value) for value in self.pending.values()]
        if any(value is None for value in estimates):
            return None
        seconds = sum(estimates)
        if active:
            for folder, row in active:
                key = folder, row["slot"]
                if key in self.pending:
                    estimate = self.estimate(self.pending[key])
                    seconds -= min(estimate, max(0, time.time() - row["started_unix"]))
        return seconds

    def completed_run(self, folder, row, *, quiet=False):
        if row["status"] == "running" or row["attempt_id"] in self.seen:
            return
        self.seen.add(row["attempt_id"])
        slot_key = folder, row["slot"]
        target = self.pending.pop(slot_key, self.targets.get(slot_key))
        if target is None:
            return
        self.completed.add(slot_key)
        metrics = row.get("metrics", {})
        wall = row.get("finished_unix", time.time()) - row["started_unix"]
        if row["status"] == "ok" and wall > 0:
            self.samples.append((target, wall))
        if folder.startswith("growth/") and (
            row["status"] != "ok" or row.get("process_peak_rss_bytes", 0) >= self.cfg["growth"]["rss_target_gib"] * 2**30
        ):
            self.pending = {key: value for key, value in self.pending.items() if key[0] != folder}
        if quiet:
            return
        case, arm, worker, size = target
        number = lambda value, unit: "n/a" if value is None else f"{value:.3f}{unit}"
        rss = row.get("process_peak_rss_bytes")
        done = len(self.completed)
        label = "warmup" if row["slot"].startswith("warmup:") else "measured"
        self.emit(
            f"[{done}/{done + len(self.pending)}] {folder} {label} {case} {arm} "
            f"cores={worker} input={size}MiB status={row['status']} "
            f"feed={number(metrics.get('feed_seconds'), 's')} "
            f"train={number(metrics.get('train_seconds'), 's')} "
            f"total={number(metrics.get('pipeline_seconds'), 's')} "
            f"peakRSS={number(None if rss is None else rss / 2**30, 'GiB')} "
            f"elapsed={duration(time.time() - self.started)} ETA~{duration(self.remaining())}",
            flush=True,
        )

    def reused_point(self, folder, point, *, quiet=False):
        key = folder, f"growth:{point['requested_mib']}:0:{point['arm']}"
        if key in self.completed:
            return
        self.pending.pop(key, None)
        self.completed.add(key)
        if point["classification"] == "target_crossed":
            self.pending = {k: v for k, v in self.pending.items() if k[0] != folder}
        if not quiet:
            done = len(self.completed)
            self.emit(f"[{done}/{done + len(self.pending)}] {folder} reused {point['repetitions']} matrix runs "
                      f"input={point['requested_mib']}MiB medianPeakRSS={point['peak_rss_bytes']/2**30:.3f}GiB "
                      f"elapsed={duration(time.time() - self.started)} ETA~{duration(self.remaining())}", flush=True)

    def ingest(self, out, *, quiet=False):
        active = []
        records = []
        for path in Path(out).glob("**/attempts/*/result.json"):
            row = read(path)
            folder = str(path.parents[2].relative_to(out))
            if row["status"] == "running":
                active.append((folder, row))
            elif row["attempt_id"] not in self.seen:
                records.append((folder, row))
        for folder, row in sorted(records, key=lambda item: item[1].get("finished_unix", item[1]["started_unix"])):
            self.completed_run(folder, row, quiet=quiet)
        for path in Path(out).glob("growth/*/*/point-*.json"):
            point = read(path)
            if point.get("source") == "matrix_median":
                self.reused_point(str(path.parent.relative_to(out)), point, quiet=quiet)
        return active


def follow(out, started_file=None, finished_file=None):
    """Monitor an already-running container without changing its supervisor."""
    out = Path(out).resolve()
    spec = read(out / "suite-spec.json")
    started = read(started_file)["started_unix"] if started_file else None
    bundle = spec["bundle"]
    arms = ["baseline" if name == bundle["baseline"] else name for name in bundle["sources"]]
    progress = SuiteProgress(spec["config"], arms, spec["sources"], spec["phase"], started)
    while True:
        progress.ingest(out)
        if finished_file and Path(finished_file).exists():
            progress.ingest(out)
            return
        time.sleep(1)
