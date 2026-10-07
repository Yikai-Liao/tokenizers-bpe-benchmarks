"""Standalone absolute/relative tables and exportable benchmark figures."""

import csv
import statistics
from pathlib import Path

from .config import read, write


def median(values):
    return statistics.median(values) if values else None


def matrix_rows(out, spec, name="matrix"):
    path = out / name / "spec.json"
    if not path.exists():
        return [], None
    from .reports import report

    paired = report(out / name)
    cfg = read(path)["config"]
    records = [read(p) for p in (out / name / "attempts").glob("*/result.json")]
    results = []
    inputs = read(path)["inputs"]
    for case in cfg["cases"]:
        inp = read(out / name / "inputs" / f"{case['name']}.json")
        for workers in cfg["execution"]["workers"]:
            cell = [r for r in records if r["case"] == case["name"] and r["workers"] == workers
                    and r["slot"].startswith("block:")]
            latest = {}
            for record in sorted(cell, key=lambda r: r["started_unix"]):
                if record["status"] == "ok":
                    latest.setdefault(record["slot"], record)
            baseline = {r["slot"].split(":")[1]: r for r in latest.values() if r["arm"] == "baseline"}
            mismatch = any(r["status"] == "model_mismatch" for r in cell)
            for arm in cfg["arms"]:
                successful = [r for r in latest.values() if r["arm"] == arm]
                times = [r["metrics"]["pipeline_seconds"] for r in successful]
                peaks = [r["process_peak_rss_bytes"] for r in successful]
                matches = [(r, baseline[r["slot"].split(":")[1]]) for r in successful
                           if r["slot"].split(":")[1] in baseline]
                wall = median(times)
                rss = median(peaks)
                time_ratios = [r["metrics"]["pipeline_seconds"] / b["metrics"]["pipeline_seconds"]
                               for r, b in matches if b["metrics"]["pipeline_seconds"] > 0]
                speedups = [b["metrics"]["pipeline_seconds"] / r["metrics"]["pipeline_seconds"]
                            for r, b in matches if r["metrics"]["pipeline_seconds"] > 0]
                memory_ratios = [r["process_peak_rss_bytes"] / b["process_peak_rss_bytes"]
                                 for r, b in matches if b["process_peak_rss_bytes"] > 0]
                results.append(dict(case=case["name"], workers=workers, arm=arm,
                    input_bytes=inp["bytes"], input_id=inputs[case["name"]]["input_id"],
                    completed_repetitions=len(successful), expected_repetitions=cfg["execution"]["paired_blocks"],
                    median_pipeline_seconds=wall,
                    median_train_seconds=median([r["metrics"]["train_seconds"] for r in successful]),
                    median_feed_seconds=median([r["metrics"]["feed_seconds"] for r in successful]),
                    median_peak_rss_bytes=rss,
                    throughput_mib_per_second=inp["bytes"] / 2**20 / wall if wall else None,
                    paired_time_over_baseline=median(time_ratios) if not mismatch else None,
                    paired_speedup_over_baseline=median(speedups) if not mismatch else None,
                    paired_rss_over_baseline=median(memory_ratios) if not mismatch else None,
                    paired_repetitions=len(matches), correctness_failed=mismatch,
                    pipeline_samples_seconds=times, peak_rss_samples_bytes=peaks))
    return results, paired


def write_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for row in rows for k, value in row.items()
                             if not isinstance(value, (list, dict))))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def label(arm, spec):
    return spec["bundle"]["baseline"] if arm == "baseline" else arm


def figures(folder, rows, curves, spec, small_rows):
    from .plots import CASES, METHODS, render

    cfg = spec["config"]
    aliases = {"en-bytelevel": "english-bytelevel", "zh-bytelevel": "chinese-bytelevel",
               "zh-whitespace": "chinese-whitespace"}
    cases = {c["name"]: CASES.get(aliases.get(c["name"], c["name"]), c["name"])
             for c in cfg["cases"]}
    methods = {}
    names = list(spec["bundle"]["sources"])
    names.remove(spec["bundle"]["baseline"])
    names = [spec["bundle"]["baseline"]] + sorted(names, key=lambda name: (
        list(METHODS).index(name) if name in METHODS else len(METHODS), name))
    for index, name in enumerate(names):
        arm = "baseline" if name == spec["bundle"]["baseline"] else name
        default = list(METHODS.values())[index % len(METHODS)]
        methods[arm] = METHODS.get(arm, (name, default[1], default[2]))
    if spec["bundle"]["baseline"] != "hf-main":
        methods["baseline"] = (spec["bundle"]["baseline"], *methods["baseline"][1:])
    points = [dict(case=c["case"], arm=c["arm"], **p) for c in curves for p in c["points"]
              if p["classification"] != "inconclusive"]
    feed_axis = bool(points) and all(p.get("feed_unique_utf8_bytes", 0) for p in points)
    render(folder, rows, points, cases=cases, methods=methods,
           input_mib=cfg["cases"][0]["size_mib"],
           vocabulary=cfg.get("trainer", {}).get("vocab_size", 32000),
           repetitions=cfg["execution"]["repetitions"], cores=cfg["growth"]["workers"],
           soft_target_gib=cfg["growth"]["rss_target_gib"], feed_axis=feed_axis,
           baseline_label=methods["baseline"][0])
    if small_rows:
        render(folder, small_rows, [], cases=cases, methods=methods,
               input_mib=cfg["small"]["size_mib"],
               vocabulary=cfg.get("trainer", {}).get("vocab_size", 32000),
               repetitions=cfg["execution"]["repetitions"], filename_prefix="small-",
               baseline_label=methods["baseline"][0])


def fmt(value):
    return "—" if value is None else f"{value:.4g}"


def suite_report(out):
    out = Path(out)
    spec = read(out / "suite-spec.json")
    folder = out / "report"
    folder.mkdir(parents=True, exist_ok=True)
    rows, matrix = matrix_rows(out, spec)
    small_rows, small_matrix = matrix_rows(out, spec, "small-matrix")
    curves = []
    for cell in sorted((out / "growth").glob("*/*")):
        curve = cell / "curve.json"
        if curve.exists():
            curves.append(read(curve))
        elif cell.is_dir():
            points = [read(p) for p in sorted(cell.glob("point-*.json"))]
            completed = sorted([p for p in points if p["classification"] != "inconclusive"],
                               key=lambda p: p["input_bytes"])
            curves.append(dict(case=cell.parent.name, arm=cell.name, status="inconclusive",
                points=points, last_completed_input_bytes=completed[-1]["input_bytes"] if completed else None,
                rss_target_bytes=spec["config"]["growth"]["rss_target_gib"] * 2**30))
    want_matrix = spec["phase"] in ("all", "matrix")
    want_small = spec["config"]["small"]["enabled"] and spec["phase"] in ("all", "small")
    wanted_growth = [c for c in spec["config"]["cases"] if c["growth"]] if spec["config"]["growth"]["enabled"] and spec["phase"] in ("all", "growth") else []
    complete = (not want_matrix or bool(matrix and matrix["performance_conclusion_valid"])) and (
        not want_small or bool(small_matrix and small_matrix["performance_conclusion_valid"])) and (
        len(curves) == len(wanted_growth) * len(spec["bundle"]["sources"])
        and all(c["status"] != "inconclusive" for c in curves))
    summary = dict(complete=complete, baseline=spec["bundle"]["baseline"],
                   matrix=rows, small_matrix=small_rows, growth_curves=curves,
                   all_growth_targets_crossed=bool(curves) and all(c["status"] == "target_crossed" for c in curves),
                   matrix_performance_conclusion_valid=matrix["performance_conclusion_valid"] if matrix else None,
                   small_performance_conclusion_valid=small_matrix["performance_conclusion_valid"] if small_matrix else None)
    write(folder / "summary.json", summary)
    write_csv(folder / "matrix.csv", rows)
    write_csv(folder / "small-matrix.csv", small_rows)
    write_csv(folder / "growth-curves.csv", curves)
    growth_rows = [dict(case=c["case"], arm=c["arm"], **p) for c in curves for p in c["points"]]
    write_csv(folder / "memory-growth.csv", growth_rows)
    lines = ["# BPE corpus suite", "", f"Baseline: {summary['baseline']}. Complete: {complete}.", "",
             "Matrix time and RSS use medians of measured repetitions; growth uses one run per size.",
             "Throughput = actual raw input MiB / median public Feed + Train time, excluding serialization.",
             "Growth x-axis: sum of UTF-8 bytes of distinct Feed strings, excluding frequencies; raw input fallback if unavailable.",
             "Process peak RSS includes startup/input and sampled serialization. MiB/GiB are binary units.", "",
             "## Source revisions", "", "| Build | Requested ref | Commit |", "| --- | --- | --- |"]
    lines += [f"| {name} | {s['requested_ref']} | `{s['commit']}` |" for name, s in spec["bundle"]["sources"].items()]
    lines += ["", "## Speed and memory", "",
              "Paired speedup = baseline time / candidate time; RSS ratio = candidate RSS / baseline RSS.",
              "Ratios are medians of within-block ratios at equal input and core count.", "",
              "| Case | Cores | Arm | Runs | Time (s) | MiB/s | RSS (GiB) | Speedup | RSS ratio |",
              "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        lines.append(f"| {row['case']} | {row['workers']} | {label(row['arm'], spec)} | {row['completed_repetitions']}/{row['expected_repetitions']} | "
                     f"{fmt(row['median_pipeline_seconds'])} | {fmt(row['throughput_mib_per_second'])} | "
                     f"{fmt(row['median_peak_rss_bytes']/2**30 if row['median_peak_rss_bytes'] is not None else None)} | "
                     f"{fmt(row['paired_speedup_over_baseline'])} | {fmt(row['paired_rss_over_baseline'])} |")
    if rows:
        lines += ["", "![Core scaling](core-scaling.png)"]
    if small_rows:
        lines += ["", "## Small corpus scale-up", "",
                  f"{spec['config']['small']['size_mib']} MiB nested prefixes; same trainer, workers and repetitions as the main matrix.",
                  "Ratios use this small corpus's baseline at the same core count. See `small-matrix.csv` for complete absolute/relative rows.",
                  f"Performance comparison valid: {summary['small_performance_conclusion_valid']}.", "",
                  "![Small corpus core scaling](small-core-scaling.png)"]
    lines += ["", "## Memory growth", "",
              "Each point is one fresh process. Input grows exponentially until a completed run reaches the soft RSS target.",
              "The crossing run finishes; there is no bisection or precise capacity search.",
              "Corpus exhaustion preserves the observed partial curve. Safety-guarded or failed runs are excluded from completed RSS curves and retained in the raw CSV.",
              "Feed size is observed, not targeted. ByteLevel strings use their encoded UTF-8 representation.",
              "Growth models are structurally validated; no cross-version parity claim at each independently chosen size.", "",
              "| Case | Arm | Last completed input MiB | Last Feed MiB | Last peak RSS GiB | Status |",
              "| --- | --- | ---: | ---: | ---: | --- |"]
    for curve in curves:
        points = [p for p in curve["points"] if p["classification"] != "inconclusive"]
        last = points[-1] if points else {}
        status = curve["status"]
        if status == "corpus_or_size_cap":
            status += f" ({curve['bound_reason']}; partial curve)"
        lines.append(f"| {curve['case']} | {label(curve['arm'], spec)} | "
                     f"{fmt(last.get('input_bytes', 0)/2**20)} | "
                     f"{fmt(last['feed_unique_utf8_bytes']/2**20 if last.get('feed_unique_utf8_bytes') is not None else None)} | "
                     f"{fmt(last['peak_rss_bytes']/2**30 if last.get('peak_rss_bytes') is not None else None)} | {status} |")
    if curves:
        lines += ["", "![Memory growth](memory-growth.png)"]
    if matrix:
        lines += ["", f"Matrix correctness failure: {matrix['correctness_failed']}. Failed attempts: {len(matrix['failures'])}.",
                  "See `../matrix/report/REPORT.md` and per-attempt logs for failures."]
    (folder / "REPORT.md").write_text("\n".join(lines) + "\n")
    if spec["config"]["execution"]["plots"]:
        figures(folder, rows, curves, spec, small_rows)
    return summary
