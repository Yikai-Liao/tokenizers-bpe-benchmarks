#!/usr/bin/env python3
"""Run extended BPE differential checks in an isolated, disposable source copy."""
import argparse
import io
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True, help='clean committed tokenizers checkout')
    p.add_argument('--out', type=Path, required=True, help='new disposable source directory')
    p.add_argument('--target-dir', type=Path, required=True)
    p.add_argument('--extended', action='store_true', help='also run archived oracle and wave checks')
    args = p.parse_args()
    if args.out.exists(): raise ValueError('--out must not exist')
    args.out.mkdir(parents=True)
    archive = subprocess.check_output(['git', '-C', str(args.source), 'archive', 'HEAD', 'tokenizers', 'LICENSE'])
    with tarfile.open(fileobj=io.BytesIO(archive)) as snapshot:
        snapshot.extractall(args.out, filter='data')
    tests = args.out / 'tokenizers/tk-train/src/trainers/bpe/engine/tests.rs'
    assets = ['stress-test.rs'] + (['extended-tests.rs'] if args.extended else [])
    tests.write_text(tests.read_text()+'\n'+'\n'.join((HERE / name).read_text() for name in assets))
    shutil.copy2(HERE / 'history/simplified-tk-train.Cargo.lock', args.out / 'tokenizers/tk-train/Cargo.lock')
    command = ['cargo', 'test', '--locked', '--manifest-path', str(args.out / 'tokenizers/tk-train/Cargo.toml'),
        '--target-dir', str(args.target_dir), '--lib']
    checks = [['randomized_round_by_round_hf_stress', '--', '--ignored']]
    if args.extended:
        checks += [['recomputing_greedy_oracle_without_affixes_or_length_filter'],
                   ['planned_wave_tables_preserve_coordinates_weights_and_filtering']]
    (args.out / 'validation-provenance.json').write_text(json.dumps(dict(
        source_commit=subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip(),
        injected_files={name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in assets},
        commands=[command+check for check in checks]), indent=2)+'\n')
    for check in checks:
        subprocess.run(command+check, check=True)

if __name__ == '__main__': main()
