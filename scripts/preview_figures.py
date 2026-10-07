"""Generate three synthetic layout previews with the production renderer."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench.plots import CASES, METHODS, render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(".bench/figure-preview"))
    args = parser.parse_args()
    times, growth = [], []
    # These deliberately varied curves test visual separation and axis choices.
    # They are constructed illustrations, never evidence for algorithm rankings.
    levels = [420, 580, 860, 490]
    # Assumed 8-core gaps requested by the user: ~10x PR, ~30x optimized,
    # and ~10x RSS at equal distinct Feed size. None are measured results.
    speedups = [(1, 10, 27, 30), (1, 9, 25, 29),
                (1, 10.5, 29, 32), (1, 9.5, 26, 30)]
    memory_factors = (1, 0.32, 0.12, 0.10)
    for corpus_index, case in enumerate(CASES):
        for method_index, arm in enumerate(METHODS):
            for workers in (1, 4, 8):
                parallel = 0.81
                baseline = levels[corpus_index] * (1 - parallel + parallel / workers)
                ratio = speedups[corpus_index][method_index] * (0.86 + 0.14 * workers / 8)
                if arm == "baseline":
                    ratio = 1
                value = baseline / ratio
                times.append(dict(case=case, arm=arm, workers=workers,
                                  paired_speedup_over_baseline=ratio,
                                  paired_train_speedup_over_baseline=ratio * 0.85 / (0.85 - method_index * 0.1),
                                  train_samples_seconds=[value * factor * (0.85 - method_index * 0.1)
                                                         for factor in (0.93, 1, 1.065)],
                                  pipeline_samples_seconds=[value * 0.93, value, value * 1.065]))
            for point, input_mib in enumerate((512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)):
                distinct_mib = (8 + corpus_index * 3) * 1.84**point
                rss_gib = 0.15 + memory_factors[method_index] * distinct_mib * (0.39 + corpus_index * 0.02)
                growth.append(dict(case=case, arm=arm, input_bytes=input_mib * 2**20,
                                   feed_unique_utf8_bytes=int(distinct_mib * 2**20),
                                   peak_rss_bytes=int(rss_gib * 2**30)))
                if rss_gib >= 16:
                    break
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "source-data.json").write_text(json.dumps(
        dict(synthetic=True, purpose="Style preview only; no benchmark conclusions",
             time_rows=times, growth_rows=growth), indent=2) + "\n")
    render(args.out, times, growth, mock=True)
    render(args.out, times, [], mock=True, timing="train", filename_prefix="train-")
    print(args.out.resolve())


if __name__ == "__main__":
    main()
