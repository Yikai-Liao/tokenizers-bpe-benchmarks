#!/usr/bin/env python3
"""Build pinned independent candidates and run one exact-model comparison."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from bench.builds import validate as validate_build
from bench.config import digest, identity, write
from bench.inputs import prepared, text_manifest
from bench.reports import report
from bench.runs import run


def prefix(source, folder, limit):
    folder.mkdir(parents=True)
    text = folder / 'text.txt'
    size = lines = 0
    with source.open('rb') as src, text.open('wb') as dst:
        for line in src:
            if size + len(line) > limit:
                break
            dst.write(line)
            size += len(line)
            lines += 1
    if not size:
        raise ValueError(f'no complete line fits the requested prefix: {source}')
    record = text_manifest(text, folder / 'manifest.json')
    record['recipe'] = dict(selection='whole-line prefix', source_sha256=digest(source),
                            requested_bytes=limit, retained_lines=lines)
    record['input_id'] = identity({k: v for k, v in record.items() if k not in ('path', 'input_id')})
    write(folder / 'manifest.json', record)
    print(f'{source.name}: {size} raw bytes, {lines} lines', flush=True)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='local tokenizers Git clone with candidate commits')
    parser.add_argument('--en-text', type=Path, required=True)
    parser.add_argument('--zh-text', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='new output directory')
    parser.add_argument('--arms', help='comma-separated candidate IDs; baseline is always included')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--cpus', help='comma-separated allowed CPU IDs; defaults to first N available CPUs')
    parser.add_argument('--size-mib', type=int, default=256)
    parser.add_argument('--blocks', type=int, default=2)
    parser.add_argument('--self-check', action='store_true', help='compare two names for the exact same baseline build')
    parser.add_argument('--build-index', type=Path, help='reuse a JSON map of candidate ID to local build.json')
    parser.add_argument('--plan-only', action='store_true', help='build/prepare/write config without measured runs')
    args = parser.parse_args()
    if min(args.workers, args.size_mib, args.blocks) < 1:
        parser.error('workers, size-mib, and blocks must be positive')
    if args.self_check and args.arms:
        parser.error('--self-check and --arms are alternatives')
    source, out = args.source.resolve(), args.out.resolve()
    if out.exists():
        parser.error('--out must be a new directory')
    available = sorted(os.sched_getaffinity(0))
    cpus = [int(value) for value in args.cpus.split(',')] if args.cpus else available[:args.workers]
    if len(set(cpus)) != len(cpus) or len(cpus) < args.workers or not set(cpus).issubset(available):
        parser.error('CPU IDs must be unique, available, and enough for the workers')
    manifest = json.loads((HERE / 'candidates.json').read_text())
    candidates = manifest['sources']
    requested = args.arms.split(',') if args.arms else [k for k, v in candidates.items() if v['kind'] == 'candidate']
    names = ['baseline'] if args.self_check else list(dict.fromkeys(['baseline', *requested]))
    if any(name not in candidates for name in names):
        parser.error('unknown arm ID; see candidates.json')
    if not args.self_check and len(names) < 2:
        parser.error('select at least one candidate or use --self-check')
    for name in names:
        subprocess.run(['git', '-C', str(source), 'cat-file', '-e', candidates[name]['commit'] + '^{commit}'], check=True)
    out.mkdir(parents=True)
    reused = json.loads(args.build_index.read_text()) if args.build_index else {}
    builds = {}
    for name in names:
        if name in reused:
            path = Path(reused[name]).resolve()
        else:
            command = [sys.executable, '-m', 'bench', 'build', '--source', str(source),
                       '--revision', candidates[name]['commit'], '--lockfile', str(HERE / 'Cargo.lock')]
            result = subprocess.check_output(command, cwd=ROOT, text=True)
            path = Path(result.strip().splitlines()[-1]).resolve()
        build = validate_build(path)
        if build['request']['source']['commit'] != candidates[name]['commit'] or build['request']['source'].get('dirty'):
            raise ValueError(f'{name}: build does not match the clean pinned commit')
        if build['request']['rustflags'] or build['request']['files']['runner/Cargo.lock'] != digest(HERE / 'Cargo.lock'):
            raise ValueError(f'{name}: expected common lock and ordinary portable release flags')
        builds[name] = str(path)
        print(f'{name}: {candidates[name]["commit"]} {build["build_id"]}', flush=True)
    write(out / 'build-index.json', builds)
    cases = []
    for language, raw, pretokenizer in [('en', args.en_text, 'whitespace_split'), ('zh', args.zh_text, 'whitespace')]:
        text = prefix(raw.resolve(), out / 'inputs' / language, args.size_mib * 2**20)
        words = out / 'inputs' / (language + '-words')
        prepared(text, pretokenizer, builds['baseline'], words)
        cases.append(dict(name=f'{language}{args.size_mib}-{pretokenizer}', input_manifest=str(words / 'manifest.json'),
                          pretokenizer=pretokenizer, trainer=dict(vocab_size=100000, min_frequency=2,
                          max_token_length=None, prefix=None, suffix=None)))
    arms = {name: dict(build=path, environment={}) for name, path in builds.items()}
    if args.self_check:
        arms['baseline_repeat'] = dict(build=builds['baseline'], environment={})
    config = dict(schema_version=1, name='baseline-self-check' if args.self_check else 'main-bpe-independent-candidates',
                  mode='core', arms=arms, cases=cases, comparison='exact-model', execution=dict(workers=[args.workers],
                  cpu_set=cpus, warmups_per_cell=0, warmup_scope='cell', paired_blocks=args.blocks,
                  order='balanced-alternating', timeout_seconds=0, min_available_gib=1.5, max_process_rss_gib=8,
                  numa=dict(policy='default', nodes=[])))
    config_path = out / 'comparison.json'
    write(config_path, config)
    if args.plan_only:
        print(config_path)
        return
    result = run(config_path, out / 'runs')
    report(out / 'runs')
    if not result['performance_conclusion_valid']:
        raise SystemExit('one or more runs failed model/resource/protocol checks; inspect retained attempts')
    print(out / 'runs' / 'report' / 'summary.json')


if __name__ == '__main__':
    main()
