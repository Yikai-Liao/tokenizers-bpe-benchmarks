"""Real subprocess tests for identity, failures, resume and paired reports."""

import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.builds import files, setup, source_snapshot
from bench.config import cpu_config, digest, environment, identity, read, write
from bench.inputs import prepared, shard_cache, text_manifest
from bench.reports import report
from bench.runs import canonical_model, execute, plan, recover, run


class BenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / "input.txt"
        self.input.write_text("alpha beta\n")
        self.manifest = self.root / "input.json"
        text_manifest(self.input, self.manifest)
        self.cpu = min(os.sched_getaffinity(0))
        self.cfg = dict(
            schema_version=1,
            name="tiny",
            mode="pipeline",
            comparison="exact-model",
            arms={},
            cases=[
                dict(
                    name="tiny",
                    input_manifest=str(self.manifest),
                    pretokenizer="whitespace",
                    trainer={},
                )
            ],
            execution=dict(
                workers=[1],
                cpu_set=[self.cpu],
                warmups_per_cell=0,
                paired_blocks=2,
                min_available_gib=0,
                max_process_rss_gib=1,
                timeout_seconds=3,
            ),
        )
        self.out = self.root / "run"
        self.config = self.root / "config.json"
        for arm in ("baseline", "candidate"):
            self.add_binary(arm)
        write(self.config, self.cfg)

    def add_binary(self, arm, behavior="ok"):
        folder = self.root / arm
        folder.mkdir(exist_ok=True)
        source = """#!/usr/bin/env python3
import json,os,sys,time
j=json.load(open(sys.argv[1]))
behavior=BEHAVIOR
if behavior=='crash': sys.exit(137)
if behavior=='signal': os.kill(os.getpid(),9)
if behavior=='timeout': time.sleep(10)
if behavior=='empty': sys.exit(0)
if behavior=='invalid': print('{}');sys.exit(0)
if behavior=='malformed': print('not-json');sys.exit(0)
if j['mode']=='prepare':
 json.dump({'schema_version':1,'ordered_words':[['a',1]],'hash_seeds':[11,13,17,19],
            'pretokenizer':j['pretokenizer']},open(j['output'],'w'))
 print(json.dumps({k:j[k] for k in ('protocol_version','attempt_id','build_id','input_id','mode')}))
 sys.exit(0)
wrong=behavior=='mismatch' and j['attempt_id']!=''
if behavior=='late-mismatch':
 marker=os.path.join(os.path.dirname(sys.argv[0]),'calls')
 calls=int(open(marker).read()) if os.path.exists(marker) else 0
 open(marker,'w').write(str(calls+1))
 wrong=calls==1
if behavior=='retry':
 marker=os.path.join(os.path.dirname(sys.argv[0]),'first-failure')
 wrong=not os.path.exists(marker)
 open(marker,'w').write('done')
model=[[['a',1 if wrong else 0]],[]]
json.dump(model,open(j['output'],'w'))
v={k:j[k] for k in ('protocol_version','attempt_id','build_id','input_id','mode')}
v.update(workers_requested=j['workers'],effective_affinity=sorted(os.sched_getaffinity(0)),
 timing_boundary='public-feed-and-train-before-serialization',
 metrics=dict(train_seconds=1,feed_seconds=1,pipeline_seconds=2,pipeline_cpu_seconds=1,
 train_cpu_seconds=1,process_hwm_kib_before_validation=100),
 output=dict(model_path=j['output'],actual_vocab=1,actual_merges=0))
if behavior=='nan': v['metrics']['train_seconds']=float('nan')
if behavior=='mode': v['mode']='core'
if behavior=='identity': v['build_id']='wrong'
if behavior=='shape': v['output']=[]
print(json.dumps(v))
""".replace("BEHAVIOR", repr(behavior))
        binary = folder / "fake"
        binary.write_text(source)
        binary.chmod(0o755)
        request = {"files": {}, "revision": arm, "behavior": behavior}
        record = dict(
            build_id=identity(request),
            request=request,
            binary="fake",
            binary_sha256=digest(binary),
            runner_sha256="fake-protocol-v1",
        )
        write(folder / "build.json", record)
        self.cfg["arms"][arm] = {"build": str(folder / "build.json"), "environment": {}}

    def test_same_path_same_size_input_changes_reject_resume(self):
        run(self.config, self.out)
        self.input.write_text("gamma beta\n")
        self.assertEqual(len("alpha beta\n"), len("gamma beta\n"))
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            run(self.config, self.out)
        text_manifest(self.input, self.manifest)
        with self.assertRaisesRegex(ValueError, "identity changed"):
            run(self.config, self.out)

    def test_prepared_cache_checks_raw_recipe_and_cached_content(self):
        target = self.root / "prepared"
        build = self.cfg["arms"]["baseline"]["build"]
        prepared(self.input, "whitespace", build, target)
        prepared(self.input, "whitespace", build, target)
        self.input.write_text("gamma beta\n")
        with self.assertRaisesRegex(ValueError, "prepared identity changed"):
            prepared(self.input, "whitespace", build, target)
        self.input.write_text("alpha beta\n")
        cache = target / "words.json"
        cache.write_text(cache.read_text().replace('"a"', '"b"'))
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            prepared(self.input, "whitespace", build, target)

    def test_config_and_binary_changes_reject_resume(self):
        run(self.config, self.out)
        self.cfg["cases"][0]["trainer"] = {"vocab_size": 9}
        write(self.config, self.cfg)
        with self.assertRaisesRegex(ValueError, "identity changed"):
            run(self.config, self.out)
        self.cfg["cases"][0]["trainer"] = {}
        write(self.config, self.cfg)
        (self.root / "candidate/fake").write_text("changed")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            run(self.config, self.out)

    def test_successful_resume_reuses_immutable_attempts(self):
        run(self.config, self.out)
        before = list((self.out / "attempts").iterdir())
        run(self.config, self.out)
        self.assertEqual(before, list((self.out / "attempts").iterdir()))
        s = report(self.out)
        self.assertEqual(s["complete_blocks"], 2)
        self.assertTrue(s["performance_conclusion_valid"])

    def test_mismatch_survives_successful_retry_without_block_file(self):
        self.add_binary("candidate", "retry")
        write(self.config, self.cfg)
        with self.assertRaisesRegex(RuntimeError, "model_mismatch"):
            run(self.config, self.out)
        s = report(self.out)
        self.assertTrue(s["correctness_failed"])
        self.assertEqual(len(s["failures"]), 1)
        run(self.config, self.out, retry_failed=True)
        s = report(self.out)
        self.assertTrue(s["correctness_failed"])
        self.assertFalse(s["performance_conclusion_valid"])
        self.assertEqual(s["complete_blocks"], 2)
        self.assertEqual(len(s["failures"]), 1)

    def test_late_mismatch_is_reported_after_a_complete_block(self):
        self.add_binary("candidate", "late-mismatch")
        write(self.config, self.cfg)
        with self.assertRaisesRegex(RuntimeError, "model_mismatch"):
            run(self.config, self.out)
        summary = report(self.out)
        self.assertEqual(summary["complete_blocks"], 1)
        self.assertEqual(summary["attempted_blocks"], 2)
        self.assertEqual(summary["excluded_blocks"], 1)
        self.assertTrue(summary["correctness_failed"])
        self.assertFalse(summary["performance_conclusion_valid"])
        run(self.config, self.out, retry_failed=True)
        self.assertTrue(report(self.out)["correctness_failed"])

    def test_revision_and_cpu_changes_reject_resume(self):
        run(self.config, self.out)
        path = self.root / "candidate/build.json"
        record = read(path)
        record["request"]["revision"] = "new-commit"
        record["build_id"] = identity(record["request"])
        write(path, record)
        with self.assertRaisesRegex(ValueError, "identity changed"):
            run(self.config, self.out)
        cpus = sorted(os.sched_getaffinity(0))
        if len(cpus) > 1:
            self.add_binary("candidate")
            self.cfg["execution"]["cpu_set"] = [cpus[1]]
            write(self.config, self.cfg)
            with self.assertRaisesRegex(ValueError, "identity changed"):
                run(self.config, self.out)

    def test_invalid_outputs_and_process_failures_are_terminal(self):
        for behavior, status in [
            ("empty", "invalid_output"),
            ("invalid", "invalid_output"),
            ("malformed", "invalid_output"),
            ("nan", "invalid_output"),
            ("mode", "invalid_output"),
            ("identity", "invalid_output"),
            ("shape", "invalid_output"),
            ("crash", "process_error"),
            ("signal", "process_error"),
            ("timeout", "timeout"),
        ]:
            with self.subTest(behavior=behavior):
                self.add_binary("baseline", behavior)
                self.cfg["execution"]["timeout_seconds"] = (
                    0.05 if behavior == "timeout" else 3
                )
                # load() allows positive fractional timeout.
                write(self.config, self.cfg)
                cfg, arms, inputs, spec = plan(self.config)
                out = self.root / behavior
                out.mkdir()
                write(out / "spec.json", spec)
                r = execute(
                    out,
                    cfg,
                    cfg["cases"][0],
                    1,
                    "baseline",
                    arms["baseline"],
                    inputs["tiny"],
                    "block:0:tiny:1:baseline",
                )
                self.assertEqual(r["status"], status)
                self.assertEqual(
                    read(out / "attempts" / r["attempt_id"] / "result.json")["status"],
                    status,
                )

    def test_memory_guard_and_orphan_recovery(self):
        cfg, arms, inputs, spec = plan(self.config)
        self.out.mkdir()
        write(self.out / "spec.json", spec)
        cfg["execution"]["min_available_gib"] = 1
        with (
            patch("bench.runs.available_memory", return_value=0),
            patch("bench.runs.subprocess.Popen") as launch,
        ):
            row = execute(
                self.out,
                cfg,
                cfg["cases"][0],
                1,
                "baseline",
                arms["baseline"],
                inputs["tiny"],
                "block:0:tiny:1:baseline",
            )
        self.assertEqual(row["status"], "resource_guard")
        launch.assert_not_called()
        row.update(status="running")
        write(self.out / "attempts" / row["attempt_id"] / "result.json", row)
        recover(self.out)
        self.assertEqual(report(self.out)["failures"][0]["status"], "interrupted")

    def test_cpu_invalid_cases(self):
        for cpus, workers in [
            ([], [1]),
            ([self.cpu, self.cpu], [1]),
            ([999999], [1]),
            ([self.cpu], [2]),
            ([self.cpu], [0]),
        ]:
            with self.assertRaises(ValueError):
                cpu_config({"cpu_set": cpus, "workers": workers})

    def test_cache_environment_is_removed_or_rejected(self):
        with patch.dict(
            os.environ,
            {
                "TK_WORD_COUNTS_CACHE": "bad",
                "LD_PRELOAD": "bad",
                "RAYON_NUM_THREADS": "99",
            },
        ):
            child = environment(workers=1)
            self.assertNotIn("TK_WORD_COUNTS_CACHE", child)
            self.assertNotIn("LD_PRELOAD", child)
            self.assertEqual(child["RAYON_NUM_THREADS"], "1")
        with self.assertRaises(ValueError):
            environment({"TK_WORD_COUNTS_CACHE": "bad"})

    def test_raw_cached_shard_is_verified(self):
        cache = self.root / "shards"
        cache.mkdir()
        (cache / "expected").write_text("wrong")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            shard_cache({"sha256": "expected", "url": "unused"}, cache)

    def test_full_model_ids_and_merge_order_preserved(self):
        a = self.root / "a.json"
        b = self.root / "b.json"
        write(a, [[["a", 0], ["b", 1]], [["a", "b"], ["b", "a"]]])
        write(b, [[["b", 1], ["a", 0]], [["a", "b"], ["b", "a"]]])
        self.assertEqual(canonical_model(a), canonical_model(b))
        write(b, [[["a", 1], ["b", 0]], [["b", "a"], ["a", "b"]]])
        self.assertNotEqual(canonical_model(a), canonical_model(b))

    def test_build_identity_includes_manifests_runner_and_vendor(self):
        source = self.root / "source"
        source.mkdir()
        for name in (
            "Cargo.toml",
            "Cargo.lock",
            "build.rs",
            "vendor/dep/src/lib.rs",
            "runner/src/main.rs",
        ):
            p = source / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(name)
        before = identity(files(source))
        (source / "vendor/dep/src/lib.rs").write_text("different")
        self.assertNotEqual(before, identity(files(source)))

    def test_paired_ratios_and_schedule(self):
        run(self.config, self.out)
        paths = list((self.out / "attempts").glob("*/result.json"))
        for p in paths:
            row = read(p)
            block = int(row["slot"].split(":")[1])
            row["metrics"]["train_seconds"] = {
                (0, "baseline"): 2,
                (0, "candidate"): 8,
                (1, "baseline"): 1,
                (1, "candidate"): 2,
            }[(block, row["arm"])]
            write(p, row)
        s = report(self.out)
        self.assertEqual(
            s["cells"][0]["metrics"]["train_seconds"]["paired_ratios"]["candidate"][
                "median"
            ],
            3,
        )
        starts = [
            json.loads(line)
            for line in (self.out / "events.jsonl").read_text().splitlines()
            if json.loads(line)["event"] == "running"
        ]
        self.assertEqual(
            [r["slot"].split(":")[-1] for r in starts],
            ["baseline", "candidate", "candidate", "baseline"],
        )




class SnapshotExclusionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "source.rs").write_text("preserved source\n")
        (self.repo / "LICENSE").symlink_to("source.rs")
        (self.repo / "historical-output").symlink_to("/unavailable/old-machine-output")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
        self.sha = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()

    def test_explicit_exclusion_records_original_revision_and_link(self):
        work = self.root / "work"
        _, provenance = setup(self.repo, self.sha, work, False, ["historical-output"])
        self.assertEqual(provenance["commit"], self.sha)
        self.assertFalse(provenance["dirty"])
        self.assertEqual(provenance["exclude_source_paths"], ["historical-output"])
        self.assertEqual(provenance["excluded_entries"], [{"path": "historical-output", "type": "2", "link_target": "/unavailable/old-machine-output"}])
        self.assertEqual((work / "source/source.rs").read_bytes(), (self.repo / "source.rs").read_bytes())
        self.assertFalse((work / "source/LICENSE").is_symlink())
        self.assertEqual((work / "source/LICENSE").read_bytes(), (self.repo / "source.rs").read_bytes())
        self.assertFalse((work / "source/historical-output").exists())

    def test_external_links_remain_rejected_by_default(self):
        with self.assertRaises(tarfile.FilterError):
            source_snapshot(self.repo, self.sha, self.root / "default")
        with self.assertRaises(tarfile.FilterError):
            source_snapshot(self.repo, self.sha, self.root / "unrelated", ["source.rs"])

    def test_exclusions_reject_typos_traversal_and_mutable_sources(self):
        for name in ["", ".", "../outside", "/absolute", "a/../b", "./source.rs", "missing"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                source_snapshot(self.repo, self.sha, self.root / "invalid", [name])
        with self.assertRaisesRegex(ValueError, "immutable Git revision"):
            source_snapshot(self.repo, None, self.root / "mutable", ["historical-output"])


if __name__ == "__main__":
    unittest.main()
