"""Check failure accounting and exact model comparison, independent of BPE."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import suite


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name)
        (self.out / "binaries").mkdir()
        self.config = dict(workers=1, min_available_gib=0, max_process_rss_gib=1, timeout_seconds=5)
        self.case = dict(name="case", input="unused", split="whitespace", vocab_size=100, min_frequency=2)

    def binary(self, model, delay=0):
        script = self.out / "binaries/fake"
        script.write_text("#!/usr/bin/env python3\nimport json,sys,time\n"
                          f"time.sleep({delay})\n"
                          "job=json.load(open(sys.argv[1]))\n"
                          f"open(job['output'],'w').write({json.dumps(model)!r})\n"
                          "print(json.dumps(dict(train_seconds=1.0,elapsed_seconds=2.0,"
                          "train_cpu_seconds=1.0,maxrss_kib=100,actual_vocab=2,actual_merges=1)))\n")
        script.chmod(0o755)

    def test_changed_token_ids_stop_comparison(self):
        self.binary([[['a', 0], ['b', 1]], [['a', 'b']]])
        first = suite.execute(self.out, self.config, self.case, "fake", self.out / "first")
        self.assertEqual(first["status"], "ok")
        self.assertFalse((self.out / "first/model.json").exists())
        self.binary([[['b', 0], ['a', 1]], [['a', 'b']]])
        with self.assertRaisesRegex(ValueError, "ordered merges differ"):
            suite.execute(self.out, self.config, self.case, "fake", self.out / "second")
        self.assertEqual(suite.read(self.out / "second/result.json")["status"], "model_mismatch")
        self.assertTrue((self.out / "second/model.json").exists())

    def test_changed_merge_order_stops_comparison(self):
        self.binary([[['a', 0], ['b', 1]], [['a', 'b'], ['b', 'a']]])
        suite.execute(self.out, self.config, self.case, "fake", self.out / "first")
        self.binary([[['a', 0], ['b', 1]], [['b', 'a'], ['a', 'b']]])
        with self.assertRaises(ValueError):
            suite.execute(self.out, self.config, self.case, "fake", self.out / "second")

    def test_wrong_measured_phase_cannot_establish_reference(self):
        self.binary([[['a', 0], ['b', 1]], []])
        self.config['expected_phase'] = 'public Trainer::feed'
        row = suite.execute(self.out, self.config, self.case, "fake", self.out / "wrong-phase")
        self.assertEqual(row["status"], "invalid_output")
        self.assertIn("different phase", row["error"])
        self.assertFalse((self.out / "models/case.json").exists())

    def test_memory_gate_does_not_launch_process(self):
        self.config["min_available_gib"] = 1
        with patch.object(suite, "available_memory", return_value=0), patch.object(suite.subprocess, "Popen") as launch:
            row = suite.execute(self.out, self.config, self.case, "fake", self.out / "guard")
        self.assertEqual(row["status"], "resource_gate_before_run")
        launch.assert_not_called()

    def test_timeout_is_retained_as_failure(self):
        self.binary([], delay=10)
        self.config["timeout_seconds"] = 0.02
        row = suite.execute(self.out, self.config, self.case, "fake", self.out / "timeout")
        self.assertEqual(row["status"], "timeout")
        self.assertNotIn("metrics", row)

    def test_failed_pair_and_interrupted_block_do_not_enter_statistics(self):
        metrics = dict(train_seconds=1, elapsed_seconds=2, train_cpu_seconds=1, maxrss_kib=100)
        good = dict(arm="full", status="ok", metrics=metrics)
        fail = dict(arm="hf", status="memory_guard")
        suite.write(self.out / "runs/primary/case/block-01/block.json",
                    dict(comparison_valid=False, results=[good, fail]))
        suite.write(self.out / "runs/primary/case/block-02.interrupted-1/block.json",
                    dict(comparison_valid=True, results=[good]))
        suite.report(self.out)
        summary = suite.read(self.out / "summary.json")
        self.assertEqual(summary["valid_paired_samples"], 0)
        self.assertEqual(len(summary["failed_runs"]), 1)
        self.assertEqual(summary["summary"], [])

    def test_report_uses_within_block_ratios_and_retains_warmup_failure(self):
        for block, full_time, hf_time in ((1, 2, 8), (2, 1, 2)):
            rows = [dict(arm=arm, status="ok", metrics=dict(train_seconds=seconds,
                         elapsed_seconds=seconds + 1, train_cpu_seconds=seconds, maxrss_kib=100))
                    for arm, seconds in (("full", full_time), ("hf", hf_time))]
            suite.write(self.out / f"runs/primary/case/block-{block:02d}/block.json",
                        dict(order=["hf", "full"], comparison_valid=True, results=rows))
        suite.write(self.out / "warmup/case/hf/result.json", dict(arm="hf", status="memory_guard"))
        suite.report(self.out)
        summary = suite.read(self.out / "summary.json")
        self.assertEqual(summary["valid_paired_blocks"], 2)
        self.assertEqual(summary["paired_comparisons"][0]["train_seconds_ratio_median"], 3)
        self.assertEqual(summary["paired_comparisons"][0]["baseline"], "full")
        self.assertEqual(len(summary["warmup_failures"]), 1)

    def test_two_arm_schedule_balances_first_position(self):
        orders = [suite.arm_order(["peer", "full"], block) for block in range(4)]
        self.assertEqual(sum(order[0] == "peer" for order in orders), 2)
        self.assertEqual(sum(order[0] == "full" for order in orders), 2)
        for order in orders: self.assertCountEqual(order, ["peer", "full"])

    def test_failed_warmup_stops_before_timed_blocks(self):
        self.config.update(cases=[self.case], groups=[dict(name="primary", cases=["case"],
                                arms=["fake"], repetitions=5)])
        suite.write(self.out / "prepared.json", dict(protocol=suite.PROTOCOL, config=self.config))
        suite.write(self.out / "smoke.json", dict(passed=True))
        with patch.object(suite, "execute", return_value=dict(status="memory_guard")) as execute:
            with self.assertRaisesRegex(RuntimeError, "adjust the profile"):
                suite.run(self.config, self.out)
        self.assertEqual(execute.call_count, 1)
        self.assertFalse((self.out / "runs").exists())

    def test_cpu_limit_and_rayon_worker_count_reach_child(self):
        cpus = sorted(os.sched_getaffinity(0))[:2]
        self.config.update(workers=len(cpus), cpu_affinity=cpus)
        script = self.out / "binaries/fake"
        script.write_text("#!/usr/bin/env python3\nimport json,os,sys\n"
            "job=json.load(open(sys.argv[1]))\nopen(job['output'],'w').write('[]')\n"
            "print(json.dumps(dict(train_seconds=1,elapsed_seconds=2,train_cpu_seconds=1,"
            "maxrss_kib=100,actual_vocab=0,actual_merges=0,cpus=sorted(os.sched_getaffinity(0)),"
            "rayon=os.environ['RAYON_NUM_THREADS'],workers=job['workers'])))\n")
        script.chmod(0o755)
        row = suite.execute(self.out, self.config, self.case, "fake", self.out / "limited")
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["metrics"]["cpus"], cpus)
        self.assertEqual(row["metrics"]["rayon"], str(len(cpus)))
        self.assertEqual(row["metrics"]["workers"], len(cpus))


if __name__ == "__main__": unittest.main()
