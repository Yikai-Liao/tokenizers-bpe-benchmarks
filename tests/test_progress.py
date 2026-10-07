import tempfile
import unittest
from pathlib import Path

from bench.bundle import build_bundle
from bench.config import write
from bench.progress import SuiteProgress
from bench.runs import schedule


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(execution=dict(workers=[1, 2, 4, 6], warmups=1, repetitions=3),
                        small=dict(enabled=True, size_mib=1),
                        growth=dict(enabled=True, workers=6, start_mib=8, max_mib=128, factor=2, rss_target_gib=2),
                        cases=[dict(name="text", size_mib=32, growth=True)])
        self.logs = []
        self.progress = SuiteProgress(self.cfg, ["baseline", "candidate"], {"text": {"bytes": 129 << 20}},
                                      emit=lambda message, **_: self.logs.append(message))

    def row(self, slot, *, seconds=10, peak=1, status="ok", attempt="a"):
        return dict(slot=slot, status=status, attempt_id=attempt, started_unix=100,
                    finished_unix=100 + seconds, process_peak_rss_bytes=peak * 2**30,
                    metrics=dict(feed_seconds=2, train_seconds=3, pipeline_seconds=5))

    def test_representative_warmup_does_not_traverse_matrix(self):
        cfg = dict(arms={"baseline": {}, "candidate": {}}, cases=[{"name": "a"}, {"name": "b"}],
                   execution=dict(workers=[1, 2, 4, 6], warmups_per_cell=1, paired_blocks=3, warmup_scope="representative"))
        slots = list(schedule(cfg))
        warmups = [s for s in slots if s[3].startswith("warmup:")]
        self.assertEqual([(s[0]["name"], s[1], s[2]) for s in warmups], [("a", 6, "baseline")])
        self.assertEqual(len(slots), 1 + 2 * 4 * 2 * 3)
        self.assertEqual(sum(k[1].startswith("warmup:") for k in self.progress.pending), 1)

    def test_eta_uses_measured_wall_time_and_observed_size_scaling(self):
        p = self.progress
        self.assertIsNone(p.remaining())
        p.completed_run("matrix", self.row("block:0:text:6:baseline", seconds=32))
        self.assertEqual(p.estimate(("text", "baseline", 6, 32)), 32)
        p.completed_run("growth/text/baseline", self.row("growth:8:0:baseline", seconds=16, attempt="b"))
        self.assertAlmostEqual(p.estimate(("text", "baseline", 6, 128)), 64)
        self.assertIn("feed=2.000s train=3.000s total=5.000s peakRSS=1.000GiB", self.logs[0])
        self.assertIn("ETA~", self.logs[0])

    def test_completed_crossing_prunes_only_that_curve_and_retry_is_logged(self):
        p = self.progress
        p.completed_run("growth/text/baseline", self.row("growth:8:0:baseline", peak=2))
        self.assertFalse(any(k[0] == "growth/text/baseline" for k in p.pending))
        self.assertTrue(any(k[0] == "growth/text/candidate" for k in p.pending))
        row = self.row("block:0:text:1:candidate", status="process_error", attempt="failed")
        p.completed_run("matrix", row)
        p.completed_run("matrix", row)
        p.completed_run("matrix", self.row(row["slot"], attempt="retry"))
        self.assertEqual(len(self.logs), 3)
        self.assertEqual(len(p.completed), 2)

    def test_portable_release_rejects_native_flags_before_fetching(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sources.json"
            for fields in ({"rustflags": "-C target-cpu=native"},
                           {"build_environment": {"CARGO_ENCODED_RUSTFLAGS": "-C\x1ftarget-cpu=native"}}):
                write(path, dict(schema_version=1, sources=[{"name": "hf-main"}], baseline="hf-main", **fields))
                with self.assertRaisesRegex(ValueError, "portable release"):
                    build_bundle(path, Path(folder) / "out", Path(folder) / "cache", portable_release=True)


if __name__ == "__main__":
    unittest.main()
