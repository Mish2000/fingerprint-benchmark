#!/usr/bin/env python3
"""Re-check a built NBIS directory against everything it claims.

``build.py test`` writes the manifest once, after checking it. This script asks
the same questions again, later, against whatever is on disk now — which is the
only interesting time to ask them:

* after a CI cache restore, where the files came back from somewhere else;
* before pinning a build into a runtime bundle;
* after anything at all has been rebuilt.

Four checks, in the order they can fail:

1. the manifest is well formed and signs its own content;
2. ``bin/mindtct`` and ``bin/bozorth3`` are exactly the bytes it names;
3. those bytes came from the archives ``nbis-5.0.0.lock.json`` locks;
4. the build used this repository's patch series and this build script.

Exit code 0 when all four hold, 2 when any of them does not. Nothing is written
and nothing is repaired: a build directory that no longer verifies is rebuilt,
never patched up.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fpbench.adapters.nbis.build_manifest import (  # noqa: E402
    BUILD_MANIFEST_FILENAME,
    NbisBuildManifestError,
    read_build_manifest,
    verify_against_repository,
    verify_build_manifest,
)


def verify(build_directory: Path, *, check_repository: bool = True) -> None:
    """Raise :class:`NbisBuildManifestError` unless every check holds."""
    directory = Path(build_directory)
    manifest_path = directory / BUILD_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise NbisBuildManifestError(
            f"{directory.name} holds no {BUILD_MANIFEST_FILENAME}; it was compiled "
            "but never certified by 'build.py test'"
        )
    manifest = read_build_manifest(manifest_path)
    verify_build_manifest(
        manifest,
        mindtct=directory / "bin" / "mindtct",
        bozorth3=directory / "bin" / "bozorth3",
    )
    if check_repository:
        verify_against_repository(manifest, integration_directory=HERE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "build_directory",
        type=Path,
        help="a build/nbis-5.0.0/<build-id> directory",
    )
    parser.add_argument(
        "--skip-repository-checks",
        action="store_true",
        help="check only the manifest and the binaries, not the lock and patches",
    )
    arguments = parser.parse_args(argv)
    try:
        verify(
            arguments.build_directory,
            check_repository=not arguments.skip_repository_checks,
        )
    except NbisBuildManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{Path(arguments.build_directory).name}: verified")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
