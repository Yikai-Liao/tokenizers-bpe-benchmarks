"""Check scaling ratios separately from equal-core algorithm comparisons."""
from pathlib import Path
import tempfile
import unittest

import scaling
import suite


class ScalingReportTests(unittest.TestCase):
    def test_single_core_speedup_and_equal_core_comparison_are_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            for block, times in ((1, (10, 5, 30, 12)), (2, (20, 20, 80, 40))):
                rows = []
                for (arm, workers), seconds in zip((('full', 1), ('full', 2), ('hf', 1), ('hf', 2)), times):
                    rows.append(dict(case="case", arm=arm, workers=workers, status="ok",
                        sampled_peak_rss_bytes=100, sampled_peak_swap_bytes=0,
                        metrics=dict(train_seconds=seconds, elapsed_seconds=seconds + 1,
                                     train_cpu_seconds=seconds, maxrss_kib=100 * workers)))
                suite.write(out / f"runs/case/block-{block:02d}/block.json",
                            dict(order=[], comparison_valid=True, results=rows))
            scaling.report(out)
            report = suite.read(out / "summary.json")
            full = next(r for r in report["scaling_speedups"] if r["arm"] == "full" and r["workers"] == 2)
            hf = next(r for r in report["algorithm_comparisons"] if r["arm"] == "hf" and r["workers"] == 2)
            self.assertEqual(report["valid_samples"], 8)
            self.assertEqual(full["train_speedup_median"], 1.5)
            self.assertEqual(full["parallel_efficiency_median"], 0.75)
            self.assertEqual(full["hwm_ratio_median"], 2)
            self.assertEqual(hf["train_ratio_median"], 2.2)
            self.assertEqual(hf["hwm_ratio_median"], 1)


if __name__ == "__main__":
    unittest.main()
