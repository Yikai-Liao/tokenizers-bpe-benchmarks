#!/usr/bin/env python3
"""Paired regression with exact vocabulary/merge comparison and resource guards."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).parent / 'bpe-suite'))
import suite

RETAINED_ENV = {
    'TK_SINGLE_PRODUCER_FAST': '1', 'TK_SINGLE_DIRECT': '1', 'TK_PAIR_LAYOUT': 'whole',
    'TK_COMMIT_GROUP_FUSION': '1', 'TK_FAST_SHARD_ROUTER': '1', 'TK_LOGICAL_OWNERS': '0',
    'TK_COMMIT_DIRECT_COLD': '0', 'TK_COMMIT_SCATTER': '0', 'TK_REMOVAL_ENTRY': '0',
    'TK_REMOVAL_REDUCE': '0', 'TK_REMOVAL_SELECTIVE': '0', 'TK_REMOVAL_STATS': '0',
    'TK_BATCH_LIMIT': '256', 'TK_RAYON_IDLE_SPIN': '4096', 'TK_RAYON_IDLE_PAUSE': '1',
    'TK_SINGLE_DIAG': '0', 'TK_SINGLE_DIAG_TIMELINE': '0',
}

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''): h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    cfg = suite.read(args.config)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'binaries').mkdir(exist_ok=True)
    cpus = cfg['cpu_set']
    if len(set(cpus)) != len(cpus) or not set(cpus).issubset(os.sched_getaffinity(0)):
        raise ValueError('invalid CPU affinity')
    provenance = dict(config=cfg, platform=platform.platform(),
                      rustc=subprocess.check_output(['rustc', '-Vv'], text=True),
                      lscpu=subprocess.check_output(['lscpu'], text=True),
                      started_unix=time.time(), binaries={}, inputs={})
    for arm, binary in cfg['binaries'].items():
        dest = out / 'binaries' / arm
        if dest.exists() and digest(dest) != digest(binary):
            raise ValueError('use a fresh output directory after changing binaries')
        shutil.copy2(binary, dest)
        provenance['binaries'][arm] = dict(path=str(Path(binary).resolve()), sha256=digest(binary))
    for case in cfg['cases']:
        provenance['inputs'][case['name']] = dict(bytes=Path(case['input']).stat().st_size,
                                                 sha256=digest(case['input']))
    suite.write(out / 'protocol.json', provenance)
    rows = []
    settings = dict(min_available_gib=3, max_process_rss_gib=12, timeout_seconds=600)
    settings.update(cfg.get('guards', {}))
    def run(case, workers, arm, directory):
        job_cfg = dict(settings, workers=workers, cpu_affinity=cpus[:workers])
        # Baseline used the retained wrapper; candidate is the normal library.
        original = {key: os.environ.get(key) for key in RETAINED_ENV}
        try:
            for key in RETAINED_ENV: os.environ.pop(key, None)
            if arm == 'baseline': os.environ.update(RETAINED_ENV)
            row = suite.execute(out, job_cfg, case, arm, directory)
        finally:
            for key, value in original.items():
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
        if row['status'] != 'ok': raise RuntimeError(f"failed run: {directory} {row['status']}")
        print(json.dumps(dict(case=case['name'], arm=arm, workers=workers,
                              train_seconds=row['metrics']['train_seconds'],
                              hwm_kib=row['metrics']['maxrss_kib'])), flush=True)
        return row
    for case in cfg['cases']:
        for workers in cfg['workers']:
            for arm in ['baseline', 'candidate']:
                run(case, workers, arm, out / 'warmup' / case['name'] / f'w{workers}' / arm)
    for block in range(cfg['repetitions']):
        cells = [(case, workers) for case in cfg['cases'] for workers in cfg['workers']]
        cells = cells[block % len(cells):] + cells[:block % len(cells)]
        if block % 2: cells.reverse()
        for case, workers in cells:
            order = ['baseline', 'candidate'] if block % 2 == 0 else ['candidate', 'baseline']
            for arm in order:
                row = run(case, workers, arm, out / 'runs' / f'block-{block:02d}' / case['name'] / f'w{workers}' / arm)
                row['block'] = block
                row['workers'] = workers
                rows.append(row)
                suite.write(out / 'samples.json', rows)
    summary = []
    for case in cfg['cases']:
        for workers in cfg['workers']:
            cell = [r for r in rows if r['case'] == case['name'] and r['workers'] == workers]
            metrics = {}
            for field in ['train_seconds', 'elapsed_seconds', 'train_cpu_seconds', 'maxrss_kib']:
                by_arm = {arm: [r['metrics'][field] for r in cell if r['arm'] == arm]
                          for arm in ['baseline', 'candidate']}
                ratios = []
                for block in range(cfg['repetitions']):
                    pair = {r['arm']: r['metrics'][field] for r in cell if r['block'] == block}
                    ratios.append(pair['candidate'] / pair['baseline'])
                metrics[field] = dict(baseline_median=statistics.median(by_arm['baseline']),
                                      candidate_median=statistics.median(by_arm['candidate']),
                                      paired_ratio_median=statistics.median(ratios),
                                      paired_ratio_range=[min(ratios), max(ratios)], ratios=ratios)
            summary.append(dict(case=case['name'], workers=workers, metrics=metrics,
                                model_sha256=digest(out / 'models' / f"{case['name']}.json")))
    suite.write(out / 'summary.json', dict(cells=summary, timed_runs=len(rows),
        exact_models_match=True, failures=0,
        maximum_sampled_swap_bytes=max(r['sampled_peak_swap_bytes'] for r in rows)))

if __name__ == '__main__': main()
