"""Build and verify the pinned flx CPU runtime bundle.

Two phases with a hard line between them.

*Acquisition* (`lock`, `fetch`, `stage-checkpoint`) may use the network and the
outside world.  It runs once, deliberately, by a person.

*Everything else* is offline.  `build` installs from wheels already on disk,
with hashes required, from no index at all.  `verify` opens nothing it has not
rehashed first.  Qualification and inference never call this script.

The bundle deliberately lives outside the repository.  The checkpoint is 835
MiB and is not ours to redistribute (docs/adr/0068); the wheels are large and
reproducible from the lock; the extracted source is reproducible from an
archive whose digest is pinned.

Usage:

    python integrations/flx/runtime/build_runtime.py inspect
    python integrations/flx/runtime/build_runtime.py lock              # network
    python integrations/flx/runtime/build_runtime.py fetch             # network
    python integrations/flx/runtime/build_runtime.py stage-checkpoint --from PATH
    python integrations/flx/runtime/build_runtime.py build             # offline
    python integrations/flx/runtime/build_runtime.py verify            # offline
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fpbench.core.flx_errors import FlxArtifactError, FlxRuntimeLockError  # noqa: E402
from fpbench.flx import identity  # noqa: E402
from fpbench.flx.artifacts import (  # noqa: E402
    IMPORTED_SOURCE_FILES,
    FlxRuntimeBundle,
    verify_bundle_artifacts,
)
from fpbench.flx.lock import (  # noqa: E402
    file_sha256,
    load_runtime_lock,
    unexpected_wheels,
    verify_wheel_directory,
)

LOCK_PATH = REPOSITORY_ROOT / "configs" / "flx" / "flx_runtime_lock_v1.txt"
SOURCE_ARCHIVE_URL = (
    "https://codeload.github.com/tim-rohwedder/fixed-length-fingerprint-extractors/"
    f"tar.gz/{identity.SOURCE_COMMIT}"
)
SOURCE_ARCHIVE_NAME = "fixed-length-fingerprint-extractors-7accfca.tar.gz"
SOURCE_ARCHIVE_SIZE = 7149830
WHEEL_INDEX = "https://download.pytorch.org/whl/cpu"
EXTRA_INDEX = "https://pypi.org/simple"
PINNED = ("torch==2.13.0+cpu", "torchvision==0.28.0+cpu")


def _bundle() -> FlxRuntimeBundle:
    return FlxRuntimeBundle.from_environment()


def _run(command: Sequence[str], *, what: str) -> None:
    completed = subprocess.run(tuple(command), check=False)
    if completed.returncode != 0:
        raise SystemExit(f"{what} failed with exit status {completed.returncode}")


# ------------------------------------------------------------- acquisition


def command_lock(_: argparse.Namespace) -> int:
    """Resolve the CPU wheels and rewrite the lock. Network. Run rarely."""
    bundle = _bundle()
    bundle.wheels.mkdir(parents=True, exist_ok=True)
    _run(
        (
            sys.executable,
            "-m",
            "pip",
            "download",
            "--dest",
            str(bundle.wheels),
            "--only-binary=:all:",
            "--index-url",
            WHEEL_INDEX,
            "--extra-index-url",
            EXTRA_INDEX,
            *PINNED,
        ),
        what="wheel download",
    )
    rows: list[str] = []
    for wheel in sorted(bundle.wheels.glob("*.whl")):
        name, version = wheel.name.split("-")[:2]
        index = WHEEL_INDEX if name in {"torch", "torchvision"} else EXTRA_INDEX
        rows.extend(
            [
                f"# {wheel.name}",
                f"#   size: {wheel.stat().st_size}",
                f"#   index: {index}",
                f"{name}=={version} \\",
                f"    --hash=sha256:{file_sha256(wheel)}",
                "",
            ]
        )
    header = LOCK_PATH.read_text(encoding="utf-8").split("--only-binary")[0]
    LOCK_PATH.write_text(
        header
        + "--only-binary=:all:\n"
        + f"--index-url {WHEEL_INDEX}\n"
        + f"--extra-index-url {EXTRA_INDEX}\n\n"
        + "\n".join(rows).rstrip("\n")
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {LOCK_PATH.relative_to(REPOSITORY_ROOT)}")
    print("review the diff before committing: the lock is part of every representation's identity")
    return 0


def command_fetch(_: argparse.Namespace) -> int:
    """Download the pinned source archive and refuse anything else. Network."""
    import urllib.request

    bundle = _bundle()
    bundle.source_archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=bundle.source_archive.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        print(f"fetching {SOURCE_ARCHIVE_URL}")
        with urllib.request.urlopen(SOURCE_ARCHIVE_URL, timeout=300) as response:
            shutil.copyfileobj(response, temporary.open("wb"))
        size = temporary.stat().st_size
        digest = file_sha256(temporary)
        if size != SOURCE_ARCHIVE_SIZE or digest != identity.SOURCE_ARCHIVE_SHA256:
            raise FlxArtifactError(
                "the fetched source archive is not the pinned one; "
                f"expected {SOURCE_ARCHIVE_SIZE} bytes / {identity.SOURCE_ARCHIVE_SHA256}, "
                f"got {size} bytes / {digest}"
            )
        temporary.replace(bundle.source_archive)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"verified {bundle.source_archive.name}: {identity.SOURCE_ARCHIVE_SHA256}")
    return 0


def command_stage_checkpoint(arguments: argparse.Namespace) -> int:
    """Copy the checkpoint into the bundle, verifying before and after."""
    bundle = _bundle()
    origin = Path(arguments.source)
    if not origin.is_file():
        raise SystemExit(f"checkpoint not found: {origin}")
    size = origin.stat().st_size
    if size != identity.CHECKPOINT_SIZE_BYTES:
        raise SystemExit(
            f"{origin.name}: byte size is {size}, expected {identity.CHECKPOINT_SIZE_BYTES}"
        )
    print(f"hashing {origin} ({size} bytes)")
    digest = file_sha256(origin)
    if digest != identity.CHECKPOINT_SHA256:
        raise SystemExit(f"{origin.name}: SHA-256 is {digest}, expected {identity.CHECKPOINT_SHA256}")
    bundle.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origin, bundle.checkpoint)
    if file_sha256(bundle.checkpoint) != identity.CHECKPOINT_SHA256:
        bundle.checkpoint.unlink(missing_ok=True)
        raise SystemExit("the copy does not match the source; the bundle was left without a checkpoint")
    print(f"staged {bundle.checkpoint}")
    print("this file is not committed and is not redistributable (docs/adr/0068)")
    return 0


# ------------------------------------------------------------------ build


def command_build(_: argparse.Namespace) -> int:
    """Create the runtime from bytes already on disk. No index, no network."""
    bundle = _bundle()
    lock = load_runtime_lock(LOCK_PATH)
    verify_wheel_directory(lock, bundle.wheels)
    stray = unexpected_wheels(lock, bundle.wheels)
    if stray:
        raise SystemExit(
            f"the wheel directory holds distributions the lock does not name: {stray}"
        )
    print(f"verified {len(lock.distributions)} locked wheels")

    if bundle.venv.exists():
        shutil.rmtree(bundle.venv)
    # --without-pip, then install from outside. A venv that bootstraps its own
    # pip and setuptools ends up holding distributions the lock never named,
    # and "the installed runtime is exactly the lock" stops being checkable.
    _run(
        (sys.executable, "-m", "venv", "--without-pip", str(bundle.venv)),
        what="venv creation",
    )
    _run(
        (
            sys.executable,
            "-m",
            "pip",
            "--python",
            str(bundle.venv_python),
            "install",
            "--quiet",
            "--no-index",
            "--no-deps",
            "--require-hashes",
            "--find-links",
            str(bundle.wheels),
            "-r",
            str(LOCK_PATH),
        ),
        what="hash-checked install",
    )
    print(f"installed the locked runtime into {bundle.venv}")

    _extract_source(bundle)
    _write_bundle_manifest(bundle, lock)
    verify_bundle_artifacts(bundle)
    print("bundle verified")
    return 0


def _extract_source(bundle: FlxRuntimeBundle) -> None:
    """Extract only what the worker imports, from the archive we just rehashed."""
    if not bundle.source_archive.is_file():
        raise SystemExit(f"source archive missing; run fetch first: {bundle.source_archive}")
    digest = file_sha256(bundle.source_archive)
    if digest != identity.SOURCE_ARCHIVE_SHA256:
        raise SystemExit(f"{bundle.source_archive.name}: SHA-256 changed")
    if bundle.source_tree.exists():
        shutil.rmtree(bundle.source_tree)
    bundle.source_tree.mkdir(parents=True)
    with tarfile.open(bundle.source_archive, "r:gz") as archive:
        root = archive.getnames()[0].split("/")[0]
        for relative in IMPORTED_SOURCE_FILES:
            member = archive.getmember(f"{root}/{relative}")
            if not member.isfile():
                raise SystemExit(f"{relative} is not a regular file in the pinned archive")
            payload = archive.extractfile(member).read()
            destination = bundle.source_tree / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
    print(f"extracted {len(IMPORTED_SOURCE_FILES)} pinned source files")


def _write_bundle_manifest(bundle: FlxRuntimeBundle, lock) -> None:
    payload = {
        "runtime_profile_id": identity.RUNTIME_PROFILE_ID,
        "source_commit": identity.SOURCE_COMMIT,
        "source_archive_sha256": identity.SOURCE_ARCHIVE_SHA256,
        "dependency_lock_sha256": lock.sha256,
        "distributions": {item.name: item.version for item in lock.distributions},
    }
    bundle.manifest.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


# ----------------------------------------------------------------- verify


def command_verify(_: argparse.Namespace) -> int:
    bundle = _bundle()
    lock = load_runtime_lock(LOCK_PATH)
    verify_wheel_directory(lock, bundle.wheels)
    report = verify_bundle_artifacts(bundle)
    print(f"lock                 {lock.sha256}")
    print(f"source archive       {report['source_archive_sha256']}")
    print(f"source files         {report['source_files_verified']} verified")
    print(f"checkpoint           {report['checkpoint_sha256']}")
    print(f"checkpoint bytes     {report['checkpoint_size_bytes']}")
    print(f"bundle disk bytes    {report['bundle_disk_bytes']}")
    return 0


def command_inspect(_: argparse.Namespace) -> int:
    bundle = _bundle()
    print(f"bundle root      {bundle.root}")
    for label, path in (
        ("wheels", bundle.wheels),
        ("venv", bundle.venv),
        ("source archive", bundle.source_archive),
        ("source tree", bundle.source_tree),
        ("checkpoint", bundle.checkpoint),
        ("manifest", bundle.manifest),
    ):
        state = "present" if path.exists() else "MISSING"
        print(f"  {label:<16} {state:<8} {path}")
    try:
        lock = load_runtime_lock(LOCK_PATH)
    except FlxRuntimeLockError as exc:
        print(f"  lock             UNREADABLE {exc}")
        return 1
    print(f"  lock             {len(lock.distributions)} pins, sha256 {lock.sha256}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, handler in (
        ("inspect", command_inspect),
        ("lock", command_lock),
        ("fetch", command_fetch),
        ("build", command_build),
        ("verify", command_verify),
    ):
        subparsers.add_parser(name).set_defaults(handler=handler)
    staged = subparsers.add_parser("stage-checkpoint")
    staged.add_argument("--from", dest="source", required=True)
    staged.set_defaults(handler=command_stage_checkpoint)

    arguments = parser.parse_args(argv)
    try:
        return arguments.handler(arguments)
    except (FlxArtifactError, FlxRuntimeLockError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
