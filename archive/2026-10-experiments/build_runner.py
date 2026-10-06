#!/usr/bin/env python3
"""Build the common runner against a chosen tokenizers source snapshot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--target-dir', type=Path, required=True)
    parser.add_argument('--vendored-rayon', action='store_true')
    parser.add_argument('--runner-source', type=Path, default=HERE / 'bpe-suite/multicore-runner/src/main.rs')
    parser.add_argument('--lockfile', type=Path)
    parser.add_argument('--update-lock', action='store_true')
    parser.add_argument('--rustflags', default='-C target-cpu=native')
    args = parser.parse_args()
    source = args.source.resolve()
    if not (source / 'tokenizers/tk-train/Cargo.toml').is_file():
        raise ValueError('--source must contain tokenizers/tk-train')
    out = args.out.resolve()
    (out / 'src').mkdir(parents=True, exist_ok=True)
    # Do not preserve an old mtime: all runners share the Cargo cache, and
    # Cargo must rebuild after switching source even if dependency identities match.
    (out / 'src/main.rs').write_bytes(args.runner_source.read_bytes())
    manifest = (HERE / 'bpe-suite/multicore-runner/Cargo.toml').read_text()
    for crate in ['tk-train', 'tk-encode']:
        manifest = manifest.replace(f'../../../tokenizers/tokenizers/{crate}', str(source / 'tokenizers' / crate))
    if args.vendored_rayon:
        if not (source / 'vendor/rayon-core/Cargo.toml').is_file():
            raise ValueError('source has no retained Rayon snapshot')
        manifest += '\n[patch.crates-io]\nrayon-core = { path = ' + json.dumps(str(source / 'vendor/rayon-core')) + ' }\n'
    (out / 'Cargo.toml').write_text(manifest)
    lock = args.lockfile or HERE / ('history/multicore-runner.Cargo.lock' if args.vendored_rayon else 'bpe-suite/multicore-runner/Cargo.lock')
    shutil.copy2(lock, out / 'Cargo.lock')
    env = os.environ.copy()
    env.update(RUSTFLAGS=args.rustflags, CARGO_TARGET_DIR=str(args.target_dir.resolve()))
    command = ['cargo', 'build', '--release', '--manifest-path', str(out / 'Cargo.toml')]
    if not args.update_lock: command.append('--locked')
    subprocess.run(command, env=env, check=True)
    binary = out / 'bpe-suite-runner'
    shutil.copy2(args.target_dir / 'release/bpe-suite-runner', binary)
    files = {}
    for directory in [source / 'tokenizers/tk-train', source / 'tokenizers/tk-encode']:
        for path in sorted(directory.rglob('*.rs')):
            if 'target' not in path.parts:
                files[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / 'build-provenance.json').write_text(json.dumps(dict(
        source=str(source), rustflags=args.rustflags, vendored_rayon=args.vendored_rayon,
        lock_sha256=hashlib.sha256((out / 'Cargo.lock').read_bytes()).hexdigest(),
        runner_sha256=hashlib.sha256((out / 'src/main.rs').read_bytes()).hexdigest(),
        rustc=subprocess.check_output(['rustc', '-Vv'], text=True),
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), files=files), indent=2)+'\n')
    print(binary)

if __name__ == '__main__': main()
