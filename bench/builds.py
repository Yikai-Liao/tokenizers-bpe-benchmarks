"""Snapshot complete source inputs and build locked, immutable runner artifacts."""

import fcntl
import io
import shutil
import subprocess
import tarfile
from pathlib import Path

from .config import ROOT, digest, environment, identity, read, verify, write

EXCLUDED = {".git", "target", ".bench", "__pycache__", ".venv", "node_modules"}


def files(root):
    root = Path(root)
    try:
        top = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        top = None
    if top and Path(top).resolve() == root.resolve():
        names = (
            subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(root),
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "-z",
                ]
            )
            .decode()
            .split("\0")
        )
        paths = [root / name for name in names if name and (root / name).is_file()]
    else:
        paths = [
            p
            for p in root.rglob("*")
            if p.is_file() and not EXCLUDED.intersection(p.relative_to(root).parts)
        ]
    result = {}
    for p in sorted(set(paths)):
        if p.is_symlink():
            p.resolve().relative_to(root.resolve())
        result[str(p.relative_to(root))] = digest(p)
    return result


def source_snapshot(source, revision, destination):
    if revision:
        sha = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", revision + "^{commit}"], text=True
        ).strip()
        tree = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", sha + "^{tree}"], text=True
        ).strip()
        data = subprocess.check_output(["git", "-C", str(source), "archive", sha])
        with tarfile.open(fileobj=io.BytesIO(data)) as bundle:
            bundle.extractall(destination, filter="data")
        return {"commit": sha, "tree": tree, "dirty": False}
    manifest = files(source)
    for name in manifest:
        dest = destination / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, dest)
        shutil.copymode(source / name, dest)
    try:
        sha = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "-C", str(source), "status", "--porcelain"], text=True
            )
        )
    except subprocess.CalledProcessError:
        sha, dirty = None, True
    return {"commit": sha, "dirty": dirty, "snapshot_files": manifest}


def setup(source, revision, work, vendored_rayon):
    work.mkdir(parents=True, exist_ok=False)
    snapshot = work / "source"
    snapshot.mkdir()
    provenance = source_snapshot(Path(source).resolve(), revision, snapshot)
    # Official source includes LICENSE symlinks. Materialize internal links so
    # the frozen snapshot remains self-contained; reject external targets.
    for path in snapshot.rglob("*"):
        if path.is_symlink():
            path.resolve().relative_to(snapshot.resolve())
            content = path.read_bytes()
            mode = path.stat().st_mode
            path.unlink()
            path.write_bytes(content)
            path.chmod(mode)
    runner = work / "runner"
    shutil.copytree(ROOT / "runner/src", runner / "src")
    manifest = (ROOT / "runner/Cargo.toml").read_text().replace("@SOURCE@", "../source")
    if vendored_rayon:
        if not (snapshot / "vendor/rayon-core/Cargo.toml").is_file():
            raise ValueError("vendored profile requires recorded rayon-core source")
        manifest += '\n[patch.crates-io]\nrayon-core = { path = "../source/vendor/rayon-core" }\n'
    (runner / "Cargo.toml").write_text(manifest)
    return runner, provenance


def create_lock(source, revision, profile, vendored_rayon=False):
    import tempfile

    profile = Path(profile)
    if profile.exists():
        raise ValueError("lock profile exists; create a new named profile")
    with tempfile.TemporaryDirectory() as temp:
        runner, _ = setup(source, revision, Path(temp) / "work", vendored_rayon)
        subprocess.run(
            [
                "cargo",
                "generate-lockfile",
                "--manifest-path",
                str(runner / "Cargo.toml"),
            ],
            check=True,
        )
        profile.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(runner / "Cargo.lock", profile)
    return profile


def cargo_configs(env):
    """Record user and ancestor Cargo configuration that can affect commands."""
    cargo_home = Path(env.get("CARGO_HOME", str(Path(env["HOME"]) / ".cargo")))
    locations = [("cargo_home", cargo_home)]
    locations += [
        (f"ancestor_{level}", path / ".cargo")
        for level, path in enumerate((Path.cwd(), *Path.cwd().parents))
    ]
    return {
        f"{label}/{name}": (folder / name).read_text()
        for label, folder in locations
        for name in ("config", "config.toml")
        if (folder / name).is_file()
    }


def build(
    source,
    revision,
    lockfile,
    cache,
    rustflags="",
    vendored_rayon=False,
    build_env=None,
):
    import tempfile

    cache = Path(cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    env = environment(build_env)
    # The caller explicitly records link/toolchain settings needed for this build.
    if rustflags:
        env["RUSTFLAGS"] = rustflags
    toolchain = {
        name: subprocess.check_output(
            [
                env.get("RUSTC", name) if name == "rustc" else name,
                "-Vv" if name == "rustc" else "-V",
            ],
            env=env,
            text=True,
        )
        for name in ("rustc", "cargo")
    }
    cpu = subprocess.check_output(["lscpu", "-J"], text=True)
    with tempfile.TemporaryDirectory(dir=cache) as temp:
        work = Path(temp) / "work"
        runner, source_info = setup(source, revision, work, vendored_rayon)
        shutil.copyfile(lockfile, runner / "Cargo.lock")
        modes = {
            str(p.relative_to(work)): p.stat().st_mode & 0o777
            for p in work.rglob("*")
            if p.is_file()
        }
        request = dict(
            file_modes=modes,
            builder_sha256=digest(Path(__file__)),
            cargo_configuration=cargo_configs(env),
            protocol_version=1,
            adapter="tk_train_v1",
            source=source_info,
            files=files(work),
            toolchain=toolchain,
            environment=env,
            rustflags=rustflags,
            vendored_rayon=vendored_rayon,
            cpu=read_cpu(cpu),
        )
        build_id = identity(request)
        dest = cache / build_id
        if dest.exists():
            return validate(dest / "build.json")
        shutil.move(str(work), dest)
    runner = dest / "runner"
    try:
        metadata = read_metadata(runner, env)
        for package in metadata["packages"]:
            if package["source"] is None:
                Path(package["manifest_path"]).resolve().relative_to(dest)
        target = cache / "target"
        cmd = [
            "cargo",
            "build",
            "--verbose",
            "--locked",
            "--release",
            "--manifest-path",
            str(runner / "Cargo.toml"),
            "--target-dir",
            str(target),
        ]
        binary = dest / "bpe-bench-runner"
        # Cargo serializes builds but releases its lock before our artifact copy.
        # Hold our own lock across both operations to prevent a second version
        # replacing the shared target binary between build completion and copy.
        with (cache / ".target.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with (dest / "build.log").open("w") as stream:
                subprocess.run(
                    cmd, env=env, check=True, stdout=stream, stderr=subprocess.STDOUT
                )
            shutil.copy2(target / "release/bpe-bench-runner", binary)
        if files(dest / "source") != {
            key.removeprefix("source/"): value
            for key, value in request["files"].items()
            if key.startswith("source/")
        }:
            raise ValueError("build changed source inputs")
        verify(runner / "Cargo.lock", request["files"]["runner/Cargo.lock"])
        record = dict(
            build_id=build_id,
            request=request,
            binary="bpe-bench-runner",
            binary_sha256=digest(binary),
            dependencies=metadata,
            runner_sha256=identity(files(ROOT / "runner")),
        )
        write(dest / "build.json", record)
    except BaseException:
        # A partial build remains inspectable, but can never become a cache hit.
        write(dest / "failed.json", {"build_id": build_id})
        raise
    return validate(dest / "build.json")


def read_cpu(text):
    import json

    value = json.loads(text)
    value["lscpu"] = [
        row for row in value["lscpu"] if row["field"] != "CPU(s) scaling MHz:"
    ]
    return value


def read_metadata(runner, env):
    import json

    return json.loads(
        subprocess.check_output(
            [
                "cargo",
                "metadata",
                "--locked",
                "--format-version",
                "1",
                "--manifest-path",
                str(runner / "Cargo.toml"),
            ],
            env=env,
            text=True,
        )
    )


def validate(path):
    path = Path(path).resolve()
    record = read(path)
    if identity(record["request"]) != record["build_id"]:
        raise ValueError("build provenance identity mismatch")
    binary = path.parent / record["binary"]
    verify(binary, record["binary_sha256"])
    for name, sha in record["request"]["files"].items():
        verify(path.parent / name, sha)
        expected_mode = record["request"].get("file_modes", {}).get(name)
        if (
            expected_mode is not None
            and (path.parent / name).stat().st_mode & 0o777 != expected_mode
        ):
            raise ValueError("build input mode changed")
    return {**record, "binary_path": str(binary), "record_path": str(path)}
