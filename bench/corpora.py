"""Prepare a configurable set of pinned corpora with one command."""

from pathlib import Path

from .bundle import safe_name
from .config import ROOT, read, write
from .inputs import corpus


def prepare(config, out, cache, size_mib=None):
    config = Path(config).resolve()
    plan = read(config)
    if plan.get("schema_version") != 1 or set(plan) - {"schema_version", "size_mib", "corpora"}:
        raise ValueError("unsupported corpora plan")
    entries = plan.get("corpora", [])
    if not entries:
        raise ValueError("corpora plan requires entries")
    names = set()
    validated = []
    for entry in entries:
        if set(entry) - {"name", "dataset", "size_mib"}:
            raise ValueError("unknown corpus entry option")
        name = safe_name(entry["name"])
        if name in names:
            raise ValueError("duplicate corpus name")
        names.add(name)
        target = size_mib if size_mib is not None else entry.get("size_mib", plan.get("size_mib", 4096))
        if type(target) is not int or target < 1:
            raise ValueError("size_mib must be a positive integer")
        dataset = (config.parent / entry["dataset"]).resolve()
        # An exported plan can refer to the image's bundled manifests by name.
        if not dataset.exists() and Path(entry["dataset"]).name == entry["dataset"]:
            dataset = ROOT / "datasets" / entry["dataset"]
        read(dataset)
        validated.append((name, dataset, target))
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    summary = dict(schema_version=1, corpora=[], complete=False)
    for name, dataset, target in validated:
        destination = out / name
        link = out / f"{name}.txt"
        expected = Path(name) / "text.txt"
        if link.is_symlink():
            if link.readlink() != expected:
                raise ValueError(f"existing corpus link points elsewhere: {link}")
        elif link.exists():
            raise ValueError(f"refusing to replace existing corpus file: {link}")
        print(f"Preparing {name}: target={target} MiB, dataset={dataset.name}", flush=True)
        record = corpus(dataset, target, destination, cache, allow_short=True)
        if not link.is_symlink():
            link.symlink_to(expected)
        availability = record["availability"]
        summary["corpora"].append(dict(name=name, path=f"{name}.txt", input_id=record["input_id"],
            sha256=record["sha256"], **availability))
        write(out / "corpora.json", summary)
        print(f"{name}: actual={record['bytes'] / 2**20:.2f} MiB "
              f"status={availability['status']} saved={link}", flush=True)
    summary["complete"] = True
    write(out / "corpora.json", summary)
    return summary
