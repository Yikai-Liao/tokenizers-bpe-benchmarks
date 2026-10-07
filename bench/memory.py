"""Reuse completed matrix measurements with their original attempt provenance."""

import statistics
from pathlib import Path

from .config import read


def matrix_reference(out, case, workers, arm):
    folder = Path(out) / "matrix"
    if not (folder / "spec.json").exists():
        return None
    spec = read(folder / "spec.json")
    cfg = spec["config"]
    cell = next((c for c in cfg["cases"] if c["name"] == case), None)
    if cell is None or workers not in cfg["execution"]["workers"] or arm not in cfg["arms"]:
        return None
    records = [read(p) for p in (folder / "attempts").glob("*/result.json")]
    records = [r for r in records if r["case"] == case and r["workers"] == workers
               and r["slot"].startswith("block:")]
    if any(r["status"] == "model_mismatch" for r in records):
        return None
    successful = {}
    for row in sorted(records, key=lambda r: r["started_unix"]):
        if row["arm"] == arm and row["status"] == "ok":
            successful.setdefault(row["slot"], row)
    expected = {f"block:{n}:{case}:{workers}:{arm}" for n in range(cfg["execution"]["paired_blocks"])}
    if set(successful) != expected:
        return None
    samples = [successful[slot] for slot in sorted(expected)]
    inp = read(folder / "inputs" / f"{case}.json")
    cpus = cfg["execution"]["cpu_set"][:workers]
    build_id = cfg["arms"][arm]["build"]
    for row in samples:
        job = row["job"]
        if (job["input_id"] != inp["input_id"] or job["build_id"] != build_id
            or job["pretokenizer"] != cell["pretokenizer"] or job["trainer"] != cell["trainer"]
            or row["affinity"] != cpus or job["workers"] != workers):
            return None
    peaks = [r["process_peak_rss_bytes"] for r in samples]
    point = dict(case=case, arm=arm, workers=workers, input_id=inp["input_id"],
                 input_bytes=inp["bytes"], peak_rss_bytes=statistics.median(peaks),
                 peak_rss_samples_bytes=peaks, pipeline_seconds=statistics.median(
                     [r["metrics"]["pipeline_seconds"] for r in samples]),
                 source="matrix_median", reused_attempt_ids=[r["attempt_id"] for r in samples],
                 repetitions=len(samples), build_id=build_id, trainer=cell["trainer"],
                 pretokenizer=cell["pretokenizer"], affinity=cpus, numa=cfg["execution"]["numa"])
    for field in ("feed_unique_words", "feed_unique_utf8_bytes"):
        values = [r["metrics"].get(field) for r in samples]
        point[field] = values[0] if values[0] is not None and len(set(values)) == 1 else None
    return point


def compatible(point, cfg, cell, workers, build, inp):
    return point is not None and (
        point["input_id"] == inp["input_id"] and point["input_bytes"] == inp["bytes"]
        and point["build_id"] == build["build_id"] and point["trainer"] == cell["trainer"]
        and point["pretokenizer"] == cell["pretokenizer"] and point["workers"] == workers
        and point["affinity"] == cfg["execution"]["cpu_set"][:workers]
        and point["numa"] == cfg["execution"]["numa"])


def classify_reference(point, target):
    # Any completed replicate proves a crossing. The plotted center remains
    # the median, and all three observed peaks stay available in the report.
    return {**point, "classification": "target_crossed" if max(point["peak_rss_samples_bytes"]) >= target
            else "below_target", "run_status": "ok", "model_comparison": "reused exact-model matrix"}
