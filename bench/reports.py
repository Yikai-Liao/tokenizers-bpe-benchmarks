"""Rebuild statistics from every terminal attempt, independently of block completeness."""

import csv
import statistics
from pathlib import Path

from .config import identity, read, write

FIELDS = (
    "load_seconds",
    "train_seconds",
    "feed_seconds",
    "pipeline_seconds",
    "train_cpu_seconds",
    "pipeline_cpu_seconds",
    "process_hwm_kib_before_validation",
    "sampled_peak_rss_bytes",
)


def report(out):
    out = Path(out)
    spec = read(out / "spec.json")
    cfg = spec["config"]
    rows = [read(p) for p in sorted((out / "attempts").glob("*/result.json"))]
    failures = [r for r in rows if r["status"] != "ok"]
    mismatch = any(r["status"] == "model_mismatch" for r in rows)
    latest = {}
    # Retrying creates a new attempt; earliest successful attempt fills the slot.
    for row in sorted(rows, key=lambda r: r["started_unix"]):
        if row["status"] == "ok":
            latest.setdefault(row["slot"], row)
    cells = []
    attempted = complete = 0
    arms = list(cfg["arms"])
    for case in cfg["cases"]:
        for workers in cfg["execution"]["workers"]:
            blocks = []
            for block in range(cfg["execution"]["paired_blocks"]):
                slots = [
                    f"block:{block}:{case['name']}:{workers}:{arm}" for arm in arms
                ]
                if any(r["slot"] in slots for r in rows):
                    attempted += 1
                if all(slot in latest for slot in slots):
                    complete += 1
                    blocks.append({arm: latest[slot] for arm, slot in zip(arms, slots)})
            metrics = {}
            for field in FIELDS:
                values = {
                    arm: [
                        (
                            b[arm].get(field)
                            if field.startswith("sampled_")
                            else b[arm]["metrics"].get(field)
                        )
                        for b in blocks
                    ]
                    for arm in arms
                }
                if not blocks or any(
                    any(v is None for v in vs) for vs in values.values()
                ):
                    continue
                ratios = {
                    arm: [
                        b / a for a, b in zip(values["baseline"], values[arm]) if a > 0
                    ]
                    for arm in arms
                    if arm != "baseline"
                }
                metrics[field] = dict(
                    by_arm={
                        arm: dict(
                            median=statistics.median(v),
                            minimum=min(v),
                            maximum=max(v),
                            samples=v,
                        )
                        for arm, v in values.items()
                    },
                    paired_ratios={
                        arm: dict(
                            median=statistics.median(v) if v else None,
                            range=[min(v), max(v)] if v else None,
                            samples=v,
                        )
                        for arm, v in ratios.items()
                    },
                )
            cells.append(
                dict(
                    case=case["name"],
                    workers=workers,
                    complete_blocks=len(blocks),
                    metrics=metrics,
                )
            )
    scaling = []
    field = "pipeline_seconds" if cfg["mode"] == "pipeline" else "train_seconds"
    for case in cfg["cases"]:
        for arm in arms:
            serial = next(
                (
                    c
                    for c in cells
                    if c["case"] == case["name"]
                    and c["workers"] == 1
                    and field in c["metrics"]
                ),
                None,
            )
            if serial:
                t1 = serial["metrics"][field]["by_arm"][arm]["median"]
                for c in cells:
                    if c["case"] == case["name"] and field in c["metrics"]:
                        tp = c["metrics"][field]["by_arm"][arm]["median"]
                        scaling.append(
                            dict(
                                case=case["name"],
                                arm=arm,
                                workers=c["workers"],
                                speedup=t1 / tp if tp else None,
                                efficiency=t1 / tp / c["workers"] if tp else None,
                                method="ratio of arm wall-time medians",
                            )
                        )
    expected = (
        len(cfg["cases"])
        * len(cfg["execution"]["workers"])
        * cfg["execution"]["paired_blocks"]
    )
    summary = dict(
        experiment_id=identity(spec),
        mode=cfg["mode"],
        correctness_failed=mismatch,
        performance_conclusion_valid=not mismatch and complete == expected,
        attempted_blocks=attempted,
        complete_blocks=complete,
        expected_blocks=expected,
        excluded_blocks=attempted - complete,
        failures=failures,
        cells=cells,
        scaling=scaling,
        attempts=len(rows),
        maximum_sampled_swap_bytes=max(
            (r.get("sampled_peak_swap_bytes", 0) for r in rows), default=0
        ),
    )
    folder = out / "report"
    write(folder / "summary.json", summary)
    with (folder / "comparisons.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "case",
                "workers",
                "metric",
                "arm",
                "paired_candidate_over_baseline_median",
                "observed_min",
                "observed_max",
            ]
        )
        for cell in cells:
            for metric, value in cell["metrics"].items():
                for arm, ratio in value["paired_ratios"].items():
                    writer.writerow(
                        [
                            cell["case"],
                            cell["workers"],
                            metric,
                            arm,
                            ratio["median"],
                            *(ratio["range"] or [None, None]),
                        ]
                    )
    lines = [
        f"# Experiment {summary['experiment_id']}",
        "",
        f"Mode: {cfg['mode']}. Complete paired blocks: {complete}/{expected}.",
        f"Correctness failed: {mismatch}. Retained unsuccessful attempts: {len(failures)}.",
        f"Performance conclusion valid: {summary['performance_conclusion_valid']}.",
        "",
        "Paired ratios use candidate / baseline within each complete block. Ranges are observed minimum/maximum, not confidence intervals.",
        "Process HWM includes startup and loading up to the pre-serialization boundary; sampled RSS includes the entire child process.",
        "",
        "| Case | Workers | Arm | Wall ratio |",
        "| --- | ---: | --- | ---: |",
    ]
    for c in cells:
        for arm, r in c["metrics"].get(field, {}).get("paired_ratios", {}).items():
            lines.append(f"| {c['case']} | {c['workers']} | {arm} | {r['median']} |")
    lines += ["", "## Failures", ""]
    lines += [
        f"- `{r['attempt_id']}`: {r['status']} ({r['slot']})" for r in failures
    ] or ["None."]
    (folder / "REPORT.md").write_text("\n".join(lines) + "\n")
    return summary
