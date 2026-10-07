"""Behavioral checks for soft RSS targets, corpus prefixes and suite resume."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.config import digest, read, write
from bench.suite import load_suite, prefix, probe_summary, growth_curve, suite
from bench.topology import select_cpus, validate_numa
import test_bench


class CapacityTests(unittest.TestCase):
    def row(self, peak, status="ok", **extra):
        return dict(attempt_id=str(peak), status=status, process_peak_rss_bytes=peak,
                    metrics=dict(pipeline_seconds=peak/10), **extra)

    def test_completed_run_preserves_full_peak_and_feed_size(self):
        row = self.row(170)
        row["metrics"].update(feed_unique_utf8_bytes=123, feed_unique_words=7)
        value = probe_summary(row, 160)
        self.assertEqual(value["peak_rss_bytes"], 170)
        self.assertEqual(value["pipeline_seconds"], 17)
        self.assertEqual(value["feed_unique_utf8_bytes"], 123)
        self.assertEqual(value["classification"], "target_crossed")

    def test_guard_kills_never_prove_a_completed_target_crossing(self):
        for status, extra in [("timeout", {}), ("process_error", {}),
                              ("resource_guard", {"guard_reason": "rss_limit"}),
                              ("resource_guard", {"guard_reason": "available_memory"}),
                              ("resource_guard", {"guard_reason": "swap_detected"})]:
            with self.subTest(status=status, extra=extra):
                value = probe_summary(self.row(170, status, **extra), 160)
                self.assertEqual(value["classification"], "inconclusive")
                self.assertNotIn("peak_rss_bytes", value)
                self.assertEqual(value["observed_peak_rss_bytes"], 170)

    def test_growth_stops_at_first_completed_crossing_without_refinement(self):
        calls = []
        def probe(size):
            calls.append(size)
            return {"classification": "below_target" if size <= 77 else "target_crossed"}
        value = growth_curve(probe, 16, 512, 2)
        self.assertEqual(calls, [16, 32, 64, 128])
        self.assertEqual(value["status"], "target_crossed")
        self.assertEqual(value["points"][-1]["requested_mib"], 128)

    def test_first_run_already_over_target_is_retained_without_searching_downward(self):
        result = growth_curve(lambda _: dict(classification="target_crossed"), 32, 64, 2)
        self.assertEqual(result["status"], "target_crossed")
        self.assertEqual(len(result["points"]), 1)
        self.assertEqual(result["points"][0]["requested_mib"], 32)

    def test_corpus_exhaustion_preserves_partial_curve(self):
        value = growth_curve(lambda _: {"classification": "below_target"}, 16, 55, 2)
        self.assertEqual([p["requested_mib"] for p in value["points"]], [16, 32, 55])
        self.assertEqual(value["status"], "corpus_or_size_cap")

    def test_fractional_factor_matches_progress_and_advances_small_sizes(self):
        from bench.progress import sizes

        value = growth_curve(lambda _: {"classification": "below_target"}, 1, 12, 1.5)
        expected = [1, 2, 3, 5, 8, 12]
        self.assertEqual([p["requested_mib"] for p in value["points"]], expected)
        self.assertEqual(list(sizes(1, 12, 1.5)), expected)

    def test_failure_preserves_completed_points(self):
        value = growth_curve(lambda n: {"classification": "below_target" if n == 16 else "inconclusive"}, 16, 64, 2)
        self.assertEqual(value["status"], "inconclusive")
        self.assertEqual(value["points"][0]["classification"], "below_target")


class PrefixTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.text = self.root / "source.txt"
        self.text.write_bytes("中文\n下一行\n最后一行".encode())
        self.source = dict(bytes=self.text.stat().st_size, sha256=digest(self.text))

    def test_chinese_prefixes_preserve_full_lines_and_exact_bytes(self):
        small = prefix(self.text, 9, self.root / "small", self.source)
        large = prefix(self.text, 19, self.root / "large", self.source)
        a, b = Path(small["data_path"]).read_bytes(), Path(large["data_path"]).read_bytes()
        self.assertEqual(a.decode(), "中文\n")
        self.assertTrue(b.startswith(a))
        self.assertEqual(small["bytes"], 7)
        self.assertEqual(large["bytes"], len(b))

    def test_complete_eof_without_newline_is_preserved(self):
        record = prefix(self.text, 100, self.root / "all", self.source)
        self.assertEqual(Path(record["data_path"]).read_bytes(), self.text.read_bytes())

    def test_cache_is_reverified_and_changed_request_rejected(self):
        out = self.root / "cached"
        prefix(self.text, 9, out, self.source)
        with self.assertRaisesRegex(ValueError, "prefix identity changed"):
            prefix(self.text, 19, out, self.source)
        (out / "text.txt").write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            prefix(self.text, 9, out, self.source)

    def test_invalid_utf8_rejected(self):
        self.text.write_bytes(b"bad\xff\n")
        with self.assertRaises(UnicodeDecodeError):
            prefix(self.text, 100, self.root / "bad", self.source)


class TopologyTests(unittest.TestCase):
    @patch("bench.topology.topology", return_value=[(0, 0, 0, 0), (1, 0, 0, 0), (2, 1, 0, 0), (3, 0, 1, 1)])
    @patch("bench.topology.os.sched_getaffinity", return_value={0, 1, 2, 3})
    def test_automatic_allocation_prefers_one_node_and_distinct_cores(self, *_):
        self.assertEqual(select_cpus(2), [0, 2])
        self.assertEqual(select_cpus(3), [0, 2, 3])
        with self.assertRaisesRegex(ValueError, "NUMA node"):
            select_cpus(3, node=0)
        with self.assertRaisesRegex(ValueError, "distinct physical"):
            select_cpus(2, [0, 1])

    @patch("bench.topology.topology", return_value=[(0, 0, 0, 0), (1, 1, 1, 1)])
    def test_bind_rejects_cross_node_cpu_set(self, *_):
        with self.assertRaisesRegex(ValueError, "bind CPU set"):
            validate_numa(dict(policy="bind", nodes=[0]), [0, 1])

    @patch("bench.topology.topology", return_value=[(0, 0, 0, 0)])
    @patch("bench.topology.subprocess.run", side_effect=__import__("subprocess").CalledProcessError(1, ["numactl"]))
    def test_denied_numa_syscall_fails_preflight(self, *_):
        with self.assertRaises(__import__("subprocess").CalledProcessError):
            validate_numa(dict(policy="bind", nodes=[0]), [0])


class SuiteTests(unittest.TestCase):
    def setUp(self):
        fixture = test_bench.BenchTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.root = fixture.root
        fixture.input.write_bytes(b"alpha beta\n" * ((2 << 20) // 11 + 1))
        self.config = self.root / "suite.toml"
        self.out = self.root / "suite"
        self.config.write_text(f'''schema_version = 1
name = "test"
[execution]
workers = [1]
cpu_set = [{fixture.cpu}]
repetitions = 3
warmups = 0
min_available_gib = 0
max_process_rss_gib = 1
timeout_seconds = 3
plots = false
[growth]
workers = 1
repetitions = 1
start_mib = 1
max_mib = 2
rss_target_gib = 0.5
[[cases]]
name = "text"
path = "input.txt"
size_mib = 1
growth = true
''')
        self.bundle = dict(baseline="hf-main", sources={n: dict(commit=n, requested_ref="main") for n in fixture.cfg["arms"]})

    def run_suite(self):
        with patch("bench.suite.load_bundle", return_value=(self.bundle, self.fixture.cfg["arms"])):
            return suite(self.config, self.root / "unused-bundle.json", self.out)

    def test_three_round_matrix_single_run_growth_and_resume(self):
        value = self.run_suite()
        self.assertTrue(value["complete"])
        for row in value["matrix"]:
            self.assertEqual(row["completed_repetitions"], 3)
            self.assertEqual(row["median_pipeline_seconds"], 2)
            self.assertEqual(row["paired_speedup_over_baseline"], 1)
            if row["arm"] == "baseline":
                self.assertEqual(row["paired_rss_over_baseline"], 1)
        self.assertEqual(len(value["growth_curves"]), 2)
        self.assertFalse(value["all_growth_targets_crossed"])
        attempts = list(self.out.rglob("attempts/*/result.json"))
        self.assertEqual(len(attempts), 8)
        for curve in value["growth_curves"]:
            first = curve["points"][0]
            self.assertEqual(first["source"], "matrix_median")
            self.assertEqual(len(first["reused_attempt_ids"]), 3)
        self.assertTrue(self.run_suite()["complete"])
        self.assertEqual(len(list(self.out.rglob("attempts/*/result.json"))), 8)
        self.assertTrue((self.out / "report" / "matrix.csv").exists())
        self.assertTrue((self.out / "report" / "memory-growth.csv").exists())

    def test_changed_corpus_is_not_silently_reused(self):
        self.run_suite()
        self.fixture.input.write_bytes(self.fixture.input.read_bytes().replace(b"alpha", b"gamma"))
        with self.assertRaisesRegex(ValueError, "suite identity changed"):
            self.run_suite()

    def test_matrix_reuse_rejects_incomplete_or_changed_job(self):
        from bench.memory import matrix_reference

        self.run_suite()
        path = next(p for p in (self.out / "matrix/attempts").glob("*/result.json")
                    if read(p)["arm"] == "baseline")
        row = read(path)
        row["job"]["pretokenizer"] = "none"
        write(path, row)
        self.assertIsNone(matrix_reference(self.out, "text", 1, "baseline"))
        self.assertIsNotNone(matrix_reference(self.out, "text", 1, "candidate"))

    def test_reused_crossing_uses_any_completed_peak_and_keeps_median(self):
        from bench.memory import classify_reference

        value = classify_reference(dict(peak_rss_bytes=100, peak_rss_samples_bytes=[90, 100, 170]), 160)
        self.assertEqual(value["classification"], "target_crossed")
        self.assertEqual(value["peak_rss_bytes"], 100)

    def test_train_only_report_uses_paired_train_times_from_same_attempts(self):
        from bench.suite_report import matrix_rows

        self.run_suite()
        for path in (self.out / "matrix/attempts").glob("*/result.json"):
            row = read(path)
            block = int(row["slot"].split(":")[1])
            values = [1, 4, 9] if row["arm"] == "baseline" else [0.2, 4, 3]
            row["metrics"].update(train_seconds=values[block],
                                  feed_seconds=100 - values[block], pipeline_seconds=100)
            write(path, row)
        rows, _ = matrix_rows(self.out, read(self.out / "suite-spec.json"))
        candidate = next(row for row in rows if row["arm"] != "baseline")
        self.assertEqual(candidate["paired_speedup_over_baseline"], 1)
        self.assertEqual(candidate["paired_train_speedup_over_baseline"], 3)
        self.assertEqual(candidate["median_train_seconds"], 3)
        self.assertCountEqual(candidate["train_samples_seconds"], [0.2, 4, 3])
        self.assertAlmostEqual(candidate["train_throughput_mib_per_second"], candidate["input_bytes"] / 2**20 / 3)

    def test_small_phase_uses_small_prefixes_and_reports_independent_baselines(self):
        self.config.write_text(self.config.read_text().replace("[growth]", "[small]\nenabled = true\nsize_mib = 1\n[growth]"))
        with patch("bench.suite.load_bundle", return_value=(self.bundle, self.fixture.cfg["arms"])):
            value = suite(self.config, self.root / "unused-bundle.json", self.out, phase="small")
        self.assertTrue(value["complete"])
        self.assertEqual(value["matrix"], [])
        self.assertEqual(value["growth_curves"], [])
        self.assertEqual(len(value["small_matrix"]), 2)
        self.assertTrue(value["small_performance_conclusion_valid"])
        for row in value["small_matrix"]:
            self.assertLessEqual(row["input_bytes"], 1 << 20)
            self.assertEqual(row["completed_repetitions"], 3)
            self.assertEqual(row["paired_speedup_over_baseline"], 1)

    def test_unknown_options_and_multiple_growth_repetitions_are_rejected(self):
        original = self.config.read_text()
        for text in (original.replace("plots = false", "plot = false"),
                     original.replace("[growth]\nworkers = 1\nrepetitions = 1", "[growth]\nworkers = 1\nrepetitions = 3")):
            self.config.write_text(text)
            with self.assertRaises(ValueError):
                load_suite(self.config)


if __name__ == "__main__":
    unittest.main()
