"""Deriving and checking the committed VeriFinger runtime manifest.

:mod:`fpbench.adapters.verifinger_java.runtime` owns the closure, the model and
the three guards, and it imports nothing above ``fpbench.core`` — because an
adapter that could reach the artifact store could reach a great deal else
(tests/unit/test_import_boundaries.py).

Deriving the manifest is a different job. It needs the local third-party store,
the prepared installation and the pinned SDK archive, all of which are Stage 11A's
and therefore an experiment-layer concern. So the operator command lives here::

    python -m fpbench.experiments.verifinger_runtime_manifest build
    python -m fpbench.experiments.verifinger_runtime_manifest verify

``build`` writes ``configs/verifinger/verifinger_runtime_manifest_v1.json`` from
what is installed, having first proved every component against the archive.
``verify`` re-derives it and reports whether the committed file still describes
what is on this machine. Neither is ever run in CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from fpbench.adapters.verifinger_java import identity, runtime as runtime_closure

__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "default_installation",
    "derive_runtime_manifest",
    "main",
]

DEFAULT_MANIFEST_PATH = Path("configs/verifinger/verifinger_runtime_manifest_v1.json")


def default_installation(*, repository_root: Path = Path(".")) -> Path:
    """Where the prepared SDK lives, when the operator has not said.

    The one place that knows this. The adapter takes an installation path and
    never goes looking for one, which is what keeps a second installation
    appearing on a machine from silently changing which engine a run's results
    are attributed to.
    """
    from fpbench.experiments.stage11a_artifacts import artifact_store_prefix_path

    return (
        artifact_store_prefix_path(repository_root=Path(repository_root))
        / "installation"
    ).resolve()


def derive_runtime_manifest(
    *, repository_root: Path = Path("."), installation: Path | None = None
) -> runtime_closure.RuntimeManifest:
    """Hash the closure as installed, and prove it came from the pinned archive.

    Raises:
        VeriFingerRuntimeClosureError: a component is absent, or the archive
            holds different bytes under that name.
    """
    from fpbench.experiments.stage11a_artifacts import artifact_store_prefix_path
    from fpbench.experiments.stage11a_qualification import prepare_installation
    from fpbench.experiments.stage11a_verifinger_observations import SDK_ARCHIVE

    root = Path(repository_root)
    tree = (
        Path(installation).resolve()
        if installation is not None
        else prepare_installation(repository_root=root)
    )
    derived = runtime_closure.build_runtime_manifest(
        tree,
        sdk_archive_sha256=SDK_ARCHIVE.sha256,
        platform=f"{identity.PLATFORM_OPERATING_SYSTEM}/{identity.PLATFORM_ARCHITECTURE}",
    )
    runtime_closure.verify_against_archive(
        artifact_store_prefix_path(repository_root=root) / SDK_ARCHIVE.filename,
        derived,
    )
    return derived


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - operator tool
    import argparse

    parser = argparse.ArgumentParser(description="VeriFinger runtime closure")
    parser.add_argument("action", choices=("build", "verify"), nargs="?", default="verify")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--installation", default=None)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    root = Path(arguments.repository_root).resolve()
    manifest_path = root / arguments.manifest
    installation = (
        Path(arguments.installation).resolve()
        if arguments.installation
        else default_installation(repository_root=root)
    )
    derived = derive_runtime_manifest(repository_root=root, installation=installation)

    if arguments.action == "build":
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(derived.as_document(), indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {arguments.manifest}")
        print(f"fingerprint {derived.fingerprint}")
        return 0

    committed = runtime_closure.read_runtime_manifest(manifest_path)
    if committed.fingerprint != derived.fingerprint:
        print(
            f"MISMATCH committed={committed.fingerprint[:12]}... "
            f"derived={derived.fingerprint[:12]}..."
        )
        return 1
    runtime_closure.verify_installation(installation, committed)
    print(f"OK {committed.fingerprint}")
    print(f"components {len(committed.components)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
