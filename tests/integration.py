"""Deterministic two-revision smoke; performance conclusions are deliberately omitted."""

import argparse
import os
from pathlib import Path

from bench.builds import validate
from bench.config import read, write
from bench.inputs import prepared, text_manifest
from bench.runs import run


def smoke(baseline, candidate, out):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    text = out / "text.txt"
    text.write_text(("aaaa aaab abab roses reddish café 中文 字符 12345 🙂\n") * 13)
    text_manifest(text, out / "text.json")
    cpus = sorted(os.sched_getaffinity(0))[:2]
    workers = [1, len(cpus)] if len(cpus) > 1 else [1]
    arms = {
        name: dict(build=str(Path(build).resolve()), environment={})
        for name, build in [("baseline", baseline), ("candidate", candidate)]
    }
    models = {}
    for pretokenizer in ("whitespace", "whitespace_split", "bytelevel_regex", "none"):
        core = out / f"words-{pretokenizer}"
        prepared(text, pretokenizer, baseline, core)
        for mode in ("core", "pipeline"):
            cfg = dict(
                schema_version=1,
                name="integration",
                mode=mode,
                arms=arms,
                cases=[
                    dict(
                        name="fixture",
                        input_manifest=str(
                            core / "manifest.json"
                            if mode == "core"
                            else out / "text.json"
                        ),
                        pretokenizer=pretokenizer,
                        trainer=dict(
                            vocab_size=300, min_frequency=2, max_token_length=12
                        ),
                    )
                ],
                execution=dict(
                    workers=workers,
                    cpu_set=cpus,
                    warmups_per_cell=1,
                    paired_blocks=2,
                    timeout_seconds=60,
                    min_available_gib=0,
                    max_process_rss_gib=2,
                ),
                comparison="exact-model",
            )
            config = out / f"{mode}-{pretokenizer}.json"
            write(config, cfg)
            experiment = out / f"{mode}-{pretokenizer}"
            summary = run(config, experiment)
            assert summary["performance_conclusion_valid"]
            models[mode, pretokenizer] = read(experiment / "models/fixture.json")
            # Resume verifies identities without creating any new attempt.
            attempts = summary["attempts"]
            assert run(config, experiment)["attempts"] == attempts
        assert models["core", pretokenizer] == models["pipeline", pretokenizer]
    # Affix is measured separately because its initial-ID semantics need their
    # own stable fixture instead of weakening the main exact comparator.
    affix_text = out / "affix.txt"
    affix_text.write_text("aaaaaaaa\n" * 17)
    text_manifest(affix_text, out / "affix-text.json")
    prepared(affix_text, "whitespace", baseline, out / "affix-words")
    for mode in ("core", "pipeline"):
        cfg = read(out / f"{mode}-whitespace.json")
        cfg["cases"][0]["input_manifest"] = str(
            out / "affix-words/manifest.json"
            if mode == "core"
            else out / "affix-text.json"
        )
        cfg["cases"][0]["trainer"].update(prefix="##", suffix="</w>")
        cfg["execution"].update(workers=[1], paired_blocks=1)
        config = out / f"affix-{mode}.json"
        write(config, cfg)
        assert run(config, out / f"affix-{mode}")["performance_conclusion_valid"]
    assert read(out / "affix-core/models/fixture.json") == read(
        out / "affix-pipeline/models/fixture.json"
    )
    # Empty text and a zero target must remain a valid zero-merge request.
    empty_text = out / "empty.txt"
    empty_text.write_text("")
    text_manifest(empty_text, out / "empty-text.json")
    prepared(empty_text, "whitespace", baseline, out / "empty-words")
    for mode in ("core", "pipeline"):
        cfg = read(out / f"{mode}-whitespace.json")
        cfg["cases"][0]["input_manifest"] = str(
            out / "empty-words/manifest.json"
            if mode == "core"
            else out / "empty-text.json"
        )
        cfg["cases"][0]["trainer"]["vocab_size"] = 0
        cfg["execution"].update(warmups_per_cell=0, paired_blocks=1)
        config = out / f"empty-{mode}.json"
        write(config, cfg)
        assert run(config, out / f"empty-{mode}")["performance_conclusion_valid"]
        assert read(out / f"empty-{mode}/models/fixture.json") == [[], []]
    write(
        out / "INTEGRATION.json",
        dict(
            status="passed",
            baseline=validate(baseline)["build_id"],
            candidate=validate(candidate)["build_id"],
            performance_evidence=False,
        ),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    smoke(args.baseline, args.candidate, args.out)
