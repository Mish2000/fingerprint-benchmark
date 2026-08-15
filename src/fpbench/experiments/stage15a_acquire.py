"""Fetching the two published artifacts, and building the frozen runtime.

The only module in Stage 15A that touches the network, and it touches it twice:
once to download two files whose digests were written down before anything was
fetched, and once to fill a wheelhouse. After that the runtime is created with
``--no-index`` against the local wheelhouse and never reaches the network again.

Nothing here is run in CI and nothing here can be. The artifact store lives
outside the working tree by policy (docs/adr/0083), no runner has one, and the
verification side of this stage is deliberately separate so it can run anywhere:
:mod:`fpbench.experiments.stage15a_runtime` reads and hashes, and this module is
the only thing that writes.

**A digest mismatch is a hard failure, not a retry.** If the bytes PyPI serves
today are not the bytes it published for 0.1.0, that is one of Stage 15A's stated
hard-fail conditions, and downloading again until it matches would be the exact
wrong response.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fpbench.core.stage15a_errors import Stage15ARuntimeIdentityError
from fpbench.experiments import stage15a_identity as frozen
from fpbench.experiments import stage15a_runtime as runtime
from fpbench.third_party.artifacts import file_sha256

__all__ = ["ARTIFACT_URLS", "acquire_artifacts", "build_frozen_runtime", "main"]

#: The exact files.pythonhosted.org locators for 0.1.0. Written down rather than
#: discovered, so that acquisition cannot quietly follow a redirect to a
#: different release (docs/adr/0100).
ARTIFACT_URLS: dict[str, str] = {
    frozen.RUNTIME_ARTIFACT_NAME: (
        "https://files.pythonhosted.org/packages/54/f1/"
        "ee0fa2852af5ab24c8bffa0e8b300146dc434bba4734b5fed325d7f30e5e/"
        "fingerprints_matching-0.1.0-py3-none-any.whl"
    ),
    frozen.SOURCE_ARTIFACT_NAME: (
        "https://files.pythonhosted.org/packages/ec/d0/"
        "b331141ed9c0b2464a1f7b010a13bc1f83d034fe6ffb1dda9eac7573b124/"
        "fingerprints_matching-0.1.0.tar.gz"
    ),
}

_EXPECTED: dict[str, tuple[str, int]] = {
    frozen.RUNTIME_ARTIFACT_NAME: (
        frozen.RUNTIME_ARTIFACT_SHA256,
        frozen.RUNTIME_ARTIFACT_SIZE_BYTES,
    ),
    frozen.SOURCE_ARTIFACT_NAME: (
        frozen.SOURCE_ARTIFACT_SHA256,
        frozen.SOURCE_ARTIFACT_SIZE_BYTES,
    ),
}


def acquire_artifacts(*, repository_root: Path, force: bool = False) -> dict[str, Any]:
    """Download both distributions into the local store, and verify both."""
    directory = runtime.artifacts_directory(repository_root=repository_root)
    directory.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"store": str(directory.name), "artifacts": []}

    for name, url in sorted(ARTIFACT_URLS.items()):
        expected_digest, expected_size = _EXPECTED[name]
        destination = directory / name
        if destination.exists() and not force:
            observed = file_sha256(destination)
            report["artifacts"].append(
                {
                    "name": name,
                    "action": "already present",
                    "matches": observed == expected_digest,
                }
            )
            if observed != expected_digest:
                raise Stage15ARuntimeIdentityError(
                    f"{name} is already in the store and is not the published "
                    "bytes. Remove it deliberately rather than re-downloading "
                    "over it"
                )
            continue
        try:
            with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
                payload = response.read()
        except (urllib.error.URLError, OSError) as exc:
            raise Stage15ARuntimeIdentityError(
                f"could not fetch {name}: {exc}"
            ) from exc
        destination.write_bytes(payload)

        observed = file_sha256(destination)
        size = destination.stat().st_size
        if observed != expected_digest or size != expected_size:
            destination.unlink(missing_ok=True)
            raise Stage15ARuntimeIdentityError(
                f"{name} does not match what PyPI published for 0.1.0: expected "
                f"{expected_digest[:16]}… / {expected_size} bytes, got "
                f"{observed[:16]}… / {size} bytes. This is a hard fail condition"
            )
        report["artifacts"].append(
            {"name": name, "action": "downloaded", "size_bytes": size, "matches": True}
        )
    return report


def build_frozen_runtime(
    *, repository_root: Path, interpreter: Path | None = None
) -> dict[str, Any]:
    """Fill the wheelhouse, then create the environment from it, offline.

    The wheelhouse is filled with the *pinned* versions rather than with whatever
    a resolver prefers. That is the whole point: ``fingerprints-matching``
    declares ``opencv-python`` with no bound, and an unpinned resolution installs
    a feature extractor nobody chose (docs/adr/0125).
    """
    root = Path(repository_root)
    wheelhouse = runtime.wheelhouse_directory(repository_root=root)
    environment = runtime.runtime_directory(repository_root=root)
    wheelhouse.mkdir(parents=True, exist_ok=True)
    python = Path(interpreter) if interpreter else Path(sys.executable)

    pins = [
        f"numpy=={frozen.PINNED_NUMPY}",
        f"opencv-python=={frozen.PINNED_OPENCV}",
    ]
    _run(
        [
            str(python),
            "-m",
            "pip",
            "download",
            "--only-binary=:all:",
            "--python-version",
            "312",
            "--implementation",
            "cp",
            "--platform",
            "win_amd64",
            "--dest",
            str(wheelhouse),
            *pins,
        ],
        what="filling the wheelhouse",
    )
    wheel = runtime.artifacts_directory(repository_root=root) / frozen.RUNTIME_ARTIFACT_NAME
    if not wheel.is_file():
        raise Stage15ARuntimeIdentityError(
            "the published wheel is not in the store; run acquisition first"
        )
    (wheelhouse / frozen.RUNTIME_ARTIFACT_NAME).write_bytes(wheel.read_bytes())

    if environment.exists():
        raise Stage15ARuntimeIdentityError(
            f"a frozen runtime already exists at {environment.name}. Remove it "
            "deliberately rather than installing over it: an environment built "
            "twice is not a frozen environment"
        )
    _run([str(python), "-m", "venv", str(environment)], what="creating the environment")

    venv_python = runtime.runtime_python(repository_root=root)
    _run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(wheelhouse),
            "--disable-pip-version-check",
            frozen.PACKAGE_REQUIREMENT,
            f"numpy=={frozen.PINNED_NUMPY}",
            f"opencv-python=={frozen.PINNED_OPENCV}",
        ],
        what="installing offline from the wheelhouse",
    )

    closure = runtime.build_runtime_closure(repository_root=root)
    return {
        "wheelhouse": sorted(p.name for p in wheelhouse.glob("*.whl")),
        "gate_state": closure.gate_state,
        "runtime_manifest_fingerprint": runtime.runtime_manifest_fingerprint(closure),
    }


def _run(command: list[str], *, what: str) -> None:
    completed = subprocess.run(  # noqa: S603
        command, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise Stage15ARuntimeIdentityError(
            f"{what} failed (exit {completed.returncode}): "
            f"{completed.stderr.strip()[:400]}"
        )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - operator tool
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "acquire"
    root = Path(".")
    if command == "acquire":
        print(json.dumps(acquire_artifacts(repository_root=root), indent=2, sort_keys=True))
        return 0
    if command == "runtime":
        print(
            json.dumps(build_frozen_runtime(repository_root=root), indent=2, sort_keys=True)
        )
        return 0
    print(f"unknown command {command!r}; expected acquire or runtime", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
