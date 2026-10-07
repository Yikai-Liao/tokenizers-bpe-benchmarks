"""Corpus matrix and single-run growth curves with a soft RSS target."""

import codecs
import copy
import fcntl
from pathlib import Path

from . import runs
from .builds import files, validate as validate_build
from .bundle import load_bundle, safe_name
from .config import ROOT, digest, identity, load, positive, read, write
from .inputs import text_manifest
from .topology import select_cpus, validate_numa


def options(value, defaults, context):
    if set(value) - set(defaults):
        raise ValueError(f"unknown {context} option: {sorted(set(value) - set(defaults))}")
    return {**defaults, **value}


def integer(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def load_suite(path):
    cfg = read(path)
    if cfg.get("schema_version") != 1 or set(cfg) - {"schema_version", "name", "execution", "trainer", "growth", "small", "cases"}:
        raise ValueError("unsupported suite schema/options")
    safe_name(cfg.get("name", "suite"))
    execution = options(cfg.get("execution", {}), dict(
        workers=[1, 4, 8], repetitions=3, warmups=1, timeout_seconds=7200,
        min_available_gib=2, max_process_rss_gib=48, cpu_set=None, cpu_node=None,
        numa={}, plots=True), "execution")
    integer(execution["repetitions"], "repetitions")
    if type(execution["warmups"]) is not int or execution["warmups"] < 0:
        raise ValueError("warmups must be a nonnegative integer")
    workers = execution["workers"]
    if not workers or len(set(workers)) != len(workers):
        raise ValueError("workers must be nonempty and unique")
    for worker in workers:
        integer(worker, "worker count")
    for name in ("timeout_seconds", "min_available_gib", "max_process_rss_gib"):
        positive(execution[name], name, name in ("min_available_gib", "timeout_seconds"))
    if type(execution["plots"]) is not bool:
        raise ValueError("plots must be a boolean")
    if execution["cpu_node"] is not None and (type(execution["cpu_node"]) is not int or execution["cpu_node"] < 0):
        raise ValueError("cpu_node must be a nonnegative integer")
    growth = options(cfg.get("growth", {}), dict(
        enabled=True, workers=8, repetitions=1, start_mib=512, max_mib=32768,
        factor=2, rss_target_gib=16), "growth")
    if type(growth["enabled"]) is not bool:
        raise ValueError("growth.enabled must be a boolean")
    for name in ("workers", "repetitions", "start_mib", "max_mib"):
        integer(growth[name], name)
    if growth["repetitions"] != 1:
        raise ValueError("growth uses exactly one measured run per size")
    positive(growth["rss_target_gib"], "rss_target_gib")
    if growth["enabled"] and execution["max_process_rss_gib"] <= growth["rss_target_gib"]:
        raise ValueError("safety RSS guard must exceed the growth soft target")
    if type(growth["factor"]) is not int or growth["factor"] < 2 or growth["start_mib"] > growth["max_mib"]:
        raise ValueError("growth factor must be an integer >=2; start_mib must fit max_mib")
    small = options(cfg.get("small", {}), dict(enabled=False, size_mib=1), "small")
    if type(small["enabled"]) is not bool:
        raise ValueError("small.enabled must be a boolean")
    integer(small["size_mib"], "small.size_mib")
    names = set()
    cases = cfg.get("cases", [])
    if not cases:
        raise ValueError("suite requires cases")
    for case in cases:
        if set(case) - {"name", "path", "size_mib", "pretokenizer", "growth", "trainer"}:
            raise ValueError("unknown case option")
        name = safe_name(case["name"])
        if name in names:
            raise ValueError("duplicate case name")
        names.add(name)
        case["path"] = str((Path(path).resolve().parent / case["path"]).resolve())
        integer(case.setdefault("size_mib", 512), "size_mib")
        case.setdefault("pretokenizer", "whitespace")
        case.setdefault("growth", True)
        if type(case["growth"]) is not bool:
            raise ValueError("case.growth must be a boolean")
    cfg.update(execution=execution, growth=growth, small=small)
    return cfg


def prefix(source, target_bytes, out, source_identity):
    """Copy a nested prefix at a full-line boundary with bounded working memory."""
    out = Path(out)
    recipe = dict(source=source_identity, requested_bytes=target_bytes,
                  selection="ordered prefix ending at complete LF line, or complete EOF")
    manifest = out / "manifest.json"
    if manifest.exists():
        from .inputs import validate

        record = read(manifest)
        if record.get("recipe") != recipe:
            raise ValueError("prefix identity changed")
        return validate(manifest, "pipeline", "none")
    out.mkdir(parents=True, exist_ok=True)
    source = Path(source)
    size = source.stat().st_size
    end = min(target_bytes, size)
    with source.open("rb") as stream:
        if end < size:
            # Walk backwards in chunks to find the last full LF line. No line
            # buffer or whole-corpus copy is held in supervisor memory.
            cursor = end
            while cursor > 0:
                begin = max(0, cursor - (1 << 20))
                stream.seek(begin)
                chunk = stream.read(cursor - begin)
                index = chunk.rfind(b"\n")
                if index >= 0:
                    end = begin + index + 1
                    break
                cursor = begin
            else:
                raise ValueError("requested prefix contains no complete line")
        stream.seek(0)
        remaining = end
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        temporary = out / "text.part"
        with temporary.open("wb") as target:
            while remaining:
                chunk = stream.read(min(1 << 20, remaining))
                if not chunk:
                    raise ValueError("corpus changed while copying")
                decoder.decode(chunk)
                target.write(chunk)
                remaining -= len(chunk)
            decoder.decode(b"", final=True)
    temporary.replace(out / "text.txt")
    record = text_manifest(out / "text.txt", manifest)
    record.update(path="text.txt", recipe=recipe)
    record["input_id"] = identity({k: v for k, v in record.items() if k not in ("path", "input_id")})
    write(manifest, record)
    return {**record, "data_path": str((out / "text.txt").resolve())}


def experiment(cfg, arms, cpus, cases, *, workers=None):
    execution = cfg["execution"]
    return dict(schema_version=1, name=cfg.get("name", "suite"), mode="pipeline",
                comparison="exact-model", arms=arms, cases=cases,
                execution=dict(workers=workers or execution["workers"], cpu_set=cpus,
                               warmups_per_cell=execution["warmups"],
                               warmup_scope="representative",
                               paired_blocks=execution["repetitions"],
                               timeout_seconds=execution["timeout_seconds"],
                               min_available_gib=execution["min_available_gib"],
                               max_process_rss_gib=execution["max_process_rss_gib"],
                               numa=execution["numa"]))


def validated_config(value, path):
    # Keep all trainer and protocol validation in the existing schema.
    write(path, value)
    return load(path)


def probe_summary(row, target):
    """Only completed runs provide uncensored points and prove a target crossing."""
    result = dict(attempt_id=row["attempt_id"], run_status=row["status"],
                  observed_peak_rss_bytes=row.get("process_peak_rss_bytes"),
                  guard_reason=row.get("guard_reason"))
    if row["status"] != "ok":
        return {**result, "classification": "inconclusive"}
    metrics = row["metrics"]
    peak = row["process_peak_rss_bytes"]
    return {**result, "classification": "target_crossed" if peak >= target else "below_target",
            "peak_rss_bytes": peak, "pipeline_seconds": metrics["pipeline_seconds"],
            "feed_unique_words": metrics.get("feed_unique_words"),
            "feed_unique_utf8_bytes": metrics.get("feed_unique_utf8_bytes")}


def growth_curve(probe, start, maximum, factor):
    """Increase prefixes exponentially; retain the first completed crossing."""
    points = []
    size = min(start, maximum)
    while True:
        point = probe(size)
        point = {**point, "requested_mib": size}
        points.append(point)
        kind = point["classification"]
        if kind in ("inconclusive", "target_crossed"):
            return dict(status=kind, points=points)
        if size == maximum:
            return dict(status="corpus_or_size_cap", points=points)
        size = min(maximum, size * factor)


def growth_case(out, cfg, arms, builds, cpus, case, source, retry_failed=False, progress=None):
    growth = cfg["growth"]
    maximum = min(growth["max_mib"], source["bytes"] >> 20)
    if maximum < 1:
        raise ValueError("growth requires at least 1 MiB of source text")
    summaries = {}
    for arm, build in builds.items():
        folder = out / "growth" / case["name"] / arm
        folder.mkdir(parents=True, exist_ok=True)
        runs.recover(folder)

        def probe(size):
            inp = prefix(case["path"], size << 20, out / "inputs" / source["sha256"] / str(size), source)
            cell = dict(name=f"{case['name']}-mib-{size}",
                        input_manifest=str(Path(inp["data_path"]).parent / "manifest.json"),
                        pretokenizer=case["pretokenizer"], trainer={**cfg.get("trainer", {}), **case.get("trainer", {})})
            plan = experiment(cfg, arms, cpus, [cell], workers=[growth["workers"]])
            plan = validated_config(plan, folder / f"probe-{size}.json")
            cell = plan["cases"][0]
            previous = [read(p) for p in (folder / "attempts").glob("*/result.json")]
            slot = f"growth:{size}:0:{arm}"
            existing = sorted([r for r in previous if r["slot"] == slot], key=lambda r: r["started_unix"])
            retained = next((r for r in existing if r["status"] == "ok"), existing[-1] if existing else None)
            retry = retry_failed and retained is not None and retained["status"] != "ok"
            if retained is not None and not retry:
                row = retained
            else:
                row = runs.execute(folder, plan, cell, growth["workers"], arm, build, inp, slot,
                                   compare_model=False)
                if progress:
                    progress.completed_run(f"growth/{case['name']}/{arm}", row)
            if not progress:
                print(f"{case['name']} {arm} {size} MiB: {row['status']}", flush=True)
            point = probe_summary(row, growth["rss_target_gib"] * 2**30)
            point.update(requested_mib=size, input_bytes=inp["bytes"], input_id=inp["input_id"],
                         model_comparison="structurally validated; no cross-version parity claim")
            write(folder / f"point-{size}.json", point)
            return point

        value = growth_curve(probe, growth["start_mib"], maximum, growth["factor"])
        completed = [p for p in value["points"] if p["classification"] != "inconclusive"]
        value.update(case=case["name"], arm=arm, rss_target_bytes=growth["rss_target_gib"] * 2**30,
                     last_completed_input_bytes=completed[-1]["input_bytes"] if completed else None,
                     available_source_bytes=source["bytes"], maximum_requested_mib=maximum,
                     bound_reason="source_exhausted" if maximum < growth["max_mib"] else "configured_max_mib")
        write(folder / "curve.json", value)
        summaries[arm] = value
    return summaries


def suite(config, bundle, out, phase="all", retry_failed=False):
    from .suite_report import suite_report

    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with (out / ".suite.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cfg = load_suite(config)
        bundle_record, arms = load_bundle(bundle)
        growth_enabled = cfg["growth"]["enabled"] and phase in ("all", "growth")
        small_enabled = cfg["small"]["enabled"] and phase in ("all", "small")
        if phase == "small" and not small_enabled:
            raise ValueError("small phase requires small.enabled = true")
        selected = cfg["cases"] if phase != "growth" else [c for c in cfg["cases"] if c["growth"]]
        if phase == "growth" and (not growth_enabled or not selected):
            raise ValueError("growth phase requires enabled growth cases")
        count = max(cfg["execution"]["workers"] + ([cfg["growth"]["workers"]] if growth_enabled else []))
        cpus = select_cpus(count, cfg["execution"]["cpu_set"], cfg["execution"]["cpu_node"])
        cfg["execution"]["cpu_set"] = cpus
        cfg["execution"]["numa"] = validate_numa(cfg["execution"]["numa"], cpus)
        sources = {c["name"]: dict(bytes=Path(c["path"]).stat().st_size, sha256=digest(c["path"])) for c in selected}
        if phase in ("all", "matrix"):
            for case in selected:
                if sources[case["name"]]["bytes"] < case["size_mib"] << 20:
                    raise ValueError(f"{case['name']}: source cannot supply {case['size_mib']} MiB")
        if small_enabled:
            for case in selected:
                if sources[case["name"]]["bytes"] < cfg["small"]["size_mib"] << 20:
                    raise ValueError(f"{case['name']}: source cannot supply small.size_mib")
        semantic = copy.deepcopy(cfg)
        for case in semantic["cases"]:
            case.pop("path")
        spec = dict(config=semantic, bundle=bundle_record, sources=sources,
                    host=runs.host(), supervisor_sha256=identity(files(ROOT / "bench")), phase=phase)
        spec_path = out / "suite-spec.json"
        if spec_path.exists() and read(spec_path) != spec:
            raise ValueError("suite identity changed; use a new output directory")
        write(spec_path, spec)
        # Validate all canonical case/trainer options before long measurements.
        validation = [dict(name=c["name"], input_manifest="unused.json", pretokenizer=c["pretokenizer"],
                           trainer={**cfg.get("trainer", {}), **c.get("trainer", {})}) for c in selected]
        validated_config(experiment(cfg, arms, cpus, validation), out / "validation.json")
        builds = {name: validate_build(arm["build"]) for name, arm in arms.items()}
        from .progress import SuiteProgress

        progress = SuiteProgress(cfg, arms, sources, phase)
        progress.ingest(out, quiet=True)
        def matrix(folder, small=False):
            cases = []
            for case in selected:
                size = cfg["small"]["size_mib"] if small else case["size_mib"]
                inp = prefix(case["path"], size << 20,
                             out / "inputs" / sources[case["name"]]["sha256"] / str(size), sources[case["name"]])
                cases.append(dict(name=case["name"], input_manifest=str(Path(inp["data_path"]).parent / "manifest.json"),
                                  pretokenizer=case["pretokenizer"], trainer={**cfg.get("trainer", {}), **case.get("trainer", {})}))
            plan_path = out / f"{folder}.json"
            plan = experiment(cfg, arms, cpus, cases)
            if small and phase == "all":
                plan["execution"]["warmups_per_cell"] = 0
            validated_config(plan, plan_path)
            runs.run(plan_path, out / folder, retry_failed=retry_failed, continue_on_failure=True,
                     observer=lambda row: progress.completed_run(folder, row))
        try:
            if phase in ("all", "matrix"):
                matrix("matrix")
            if small_enabled:
                matrix("small-matrix", small=True)
            if growth_enabled:
                for case in selected:
                    if case["growth"]:
                        growth_case(out, cfg, arms, builds, cpus, case, sources[case["name"]], retry_failed, progress)
        finally:
            summary = suite_report(out)
        return summary
