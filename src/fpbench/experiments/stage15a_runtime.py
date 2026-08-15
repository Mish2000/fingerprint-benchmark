"""G1 — the artifact and the runtime it will actually execute on.

Two questions, and the second one is the one that has teeth.

The first is easy: are the bytes on this machine the bytes PyPI published for
``fingerprints-matching==0.1.0``? Both digests were written into
:mod:`fpbench.experiments.stage15a_identity` before anything was fetched, so the
download is checked against the record rather than the record written from the
download.

The second is that this candidate has no vendored runtime at all. It is 4,492
bytes of pure Python that calls OpenCV for every pixel operation it performs, and
it declares ``opencv-python`` with no version bound whatsoever. Whatever
``pip install fingerprints-matching`` resolves to on the day it is run *is* the
feature extractor, because the contours ``cv2.findContours`` returns are the
direct and only input to feature construction. A benchmark that let that float
would not be able to reproduce its own results (docs/adr/0125).

So the runtime is frozen the way a vendor SDK would be: an exact interpreter, an
exact platform, an exact wheel for every installed distribution, each with a
SHA-256, in a wheelhouse this project holds, installed with ``--no-index`` into
an environment that never reaches the network again.

Nothing in this module downloads anything. Acquisition is a deliberate act with
its own command; this is the part that says whether what arrived is what was
expected.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.serialization import stable_hash
from fpbench.core.stage15a_errors import Stage15ARuntimeIdentityError
from fpbench.experiments import stage15a_identity as frozen
from fpbench.third_party.artifacts import (
    file_sha256,
    resolve_third_party_root,
)

__all__ = [
    "RUNTIME_SCHEMA",
    "STORE_RELATIVE",
    "ComponentCheck",
    "RuntimeClosure",
    "store_root",
    "artifacts_directory",
    "wheelhouse_directory",
    "runtime_directory",
    "runtime_python",
    "check_artifacts",
    "check_wheelhouse",
    "inspect_installed_runtime",
    "build_runtime_closure",
    "runtime_manifest_fingerprint",
    "require_ready",
]

RUNTIME_SCHEMA = "stage_15a_artifact_runtime_identity_v1"

#: Where this candidate lives under the third-party store root. One directory,
#: three roles: the two published distributions as delivered, the wheelhouse the
#: environment is built from, and the environment itself.
STORE_RELATIVE = "fingerprints-matching"


def store_root(*, repository_root: Path | None = None) -> Path:
    root = resolve_third_party_root(repository_root=repository_root)
    return Path(root) / STORE_RELATIVE


def artifacts_directory(*, repository_root: Path | None = None) -> Path:
    return store_root(repository_root=repository_root) / "artifacts"


def wheelhouse_directory(*, repository_root: Path | None = None) -> Path:
    return store_root(repository_root=repository_root) / "wheelhouse"


def runtime_directory(*, repository_root: Path | None = None) -> Path:
    return store_root(repository_root=repository_root) / "runtime"


def runtime_python(*, repository_root: Path | None = None) -> Path:
    """The interpreter of the frozen environment, on this platform."""
    base = runtime_directory(repository_root=repository_root)
    windows = base / "Scripts" / "python.exe"
    return windows if windows.exists() else base / "bin" / "python"


# --------------------------------------------------------------------- checking


@dataclass(frozen=True, slots=True)
class ComponentCheck:
    """What was found where the closure said to look.

    Absence is returned rather than raised: no CI runner has these bytes, by
    design. Different bytes under the expected name is not absence, and that one
    does raise.
    """

    name: str
    role: str
    expected_sha256: str
    expected_size_bytes: int
    present: bool
    observed_sha256: str | None = None
    observed_size_bytes: int | None = None

    @property
    def matches(self) -> bool:
        return (
            self.present
            and self.observed_sha256 == self.expected_sha256
            and self.observed_size_bytes == self.expected_size_bytes
        )

    def as_document(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "expected_sha256": self.expected_sha256,
            "expected_size_bytes": self.expected_size_bytes,
            "present": self.present,
            "matches": self.matches,
        }


def _check_one(
    path: Path, *, name: str, role: str, expected_sha256: str, expected_size: int
) -> ComponentCheck:
    if not path.exists():
        return ComponentCheck(
            name=name,
            role=role,
            expected_sha256=expected_sha256,
            expected_size_bytes=expected_size,
            present=False,
        )
    size = path.stat().st_size
    digest = file_sha256(path)
    return ComponentCheck(
        name=name,
        role=role,
        expected_sha256=expected_sha256,
        expected_size_bytes=expected_size,
        present=True,
        observed_sha256=digest,
        observed_size_bytes=size,
    )


def check_artifacts(*, repository_root: Path | None = None) -> tuple[ComponentCheck, ...]:
    """The two published distributions, as delivered.

    Both are checked, not just the wheel that gets installed. The sdist is what
    makes the route auditable — it is the only copy of the source that is signed
    for by a digest PyPI published rather than by whatever a wheel happened to
    unpack to.
    """
    directory = artifacts_directory(repository_root=repository_root)
    return (
        _check_one(
            directory / frozen.RUNTIME_ARTIFACT_NAME,
            name=frozen.RUNTIME_ARTIFACT_NAME,
            role="published_wheel",
            expected_sha256=frozen.RUNTIME_ARTIFACT_SHA256,
            expected_size=frozen.RUNTIME_ARTIFACT_SIZE_BYTES,
        ),
        _check_one(
            directory / frozen.SOURCE_ARTIFACT_NAME,
            name=frozen.SOURCE_ARTIFACT_NAME,
            role="published_sdist",
            expected_sha256=frozen.SOURCE_ARTIFACT_SHA256,
            expected_size=frozen.SOURCE_ARTIFACT_SIZE_BYTES,
        ),
    )


def check_wheelhouse(*, repository_root: Path | None = None) -> tuple[ComponentCheck, ...]:
    """Every wheel the frozen environment is built from, by digest."""
    directory = wheelhouse_directory(repository_root=repository_root)
    checks = []
    for distribution, pin in sorted(frozen.RUNTIME_WHEELS.items()):
        filename = str(pin["filename"])
        checks.append(
            _check_one(
                directory / filename,
                name=filename,
                role=f"runtime_wheel:{distribution}",
                expected_sha256=str(pin["sha256"]),
                expected_size=int(pin["size_bytes"]),  # type: ignore[arg-type]
            )
        )
    return tuple(checks)


# ------------------------------------------------------------ the live environment

#: Asked of the frozen interpreter, never of the one running fpbench. The whole
#: point of a separate environment is that fpbench's own numpy — if it ever has
#: one — is not the algorithm's numpy.
_INTROSPECT = r"""
import json, platform, sys
out = {
    "python_version": platform.python_version(),
    "platform": platform.platform(),
    "machine": platform.machine(),
    "executable": sys.executable,
}
try:
    import numpy
    out["numpy"] = numpy.__version__
except Exception as exc:
    out["numpy_error"] = type(exc).__name__
try:
    import cv2
    out["cv2_library"] = cv2.__version__
except Exception as exc:
    out["cv2_library_error"] = type(exc).__name__
try:
    from importlib.metadata import version
    out["opencv"] = version("opencv-python")
except Exception as exc:
    out["opencv_error"] = type(exc).__name__
try:
    import fingerprints_matching.minutiae_matching as mm
    import fingerprints_matching.fingerprints_matching as fm
    out["module_paths"] = {
        "fingerprints_matching/minutiae_matching.py": mm.__file__,
        "fingerprints_matching/fingerprints_matching.py": fm.__file__,
    }
except Exception as exc:
    out["package_error"] = type(exc).__name__
print(json.dumps(out))
"""


def inspect_installed_runtime(
    *, repository_root: Path | None = None, timeout_seconds: float = 120.0
) -> dict[str, Any]:
    """Ask the frozen interpreter what it is, and refuse to guess when it is absent."""
    interpreter = runtime_python(repository_root=repository_root)
    if not interpreter.exists():
        return {"present": False, "reason": "RUNTIME_ENVIRONMENT_NOT_BUILT"}
    try:
        completed = subprocess.run(  # noqa: S603
            [str(interpreter), "-I", "-c", _INTROSPECT],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stage15ARuntimeIdentityError(
            f"the frozen interpreter at {interpreter} could not be run: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise Stage15ARuntimeIdentityError(
            "the frozen interpreter refused to describe itself "
            f"(exit {completed.returncode}): {completed.stderr.strip()[:400]}"
        )
    try:
        observed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise Stage15ARuntimeIdentityError(
            f"the frozen interpreter did not answer with JSON: {exc}"
        ) from exc
    observed["present"] = True
    return observed


def _installed_module_digests(
    observed: Mapping[str, Any],
) -> dict[str, str | None]:
    """Hash the modules the frozen environment will actually import.

    Not the wheel — the files on disk. A wheel that verifies and an installed
    tree that was edited afterwards are the same digest at the front door and
    different code at the back.
    """
    paths = observed.get("module_paths")
    digests: dict[str, str | None] = {
        name: None for name in frozen.UPSTREAM_MODULE_DIGESTS
    }
    if not isinstance(paths, Mapping):
        return digests
    for name in digests:
        raw = paths.get(name)
        if not raw:
            continue
        candidate = Path(str(raw))
        if candidate.exists():
            digests[name] = file_sha256(candidate)
    # ``__init__.py`` is empty and carries no ``__file__`` of its own in the
    # introspection above; derive it from the package directory instead.
    init_name = "fingerprints_matching/__init__.py"
    if digests.get(init_name) is None:
        anchor = paths.get("fingerprints_matching/minutiae_matching.py")
        if anchor:
            init_path = Path(str(anchor)).parent / "__init__.py"
            if init_path.exists():
                digests[init_name] = file_sha256(init_path)
    return digests


# ------------------------------------------------------------------- the closure


@dataclass(frozen=True, slots=True)
class RuntimeClosure:
    """Everything that could change a score, and whether it is what it should be."""

    artifacts: tuple[ComponentCheck, ...]
    wheels: tuple[ComponentCheck, ...]
    observed: Mapping[str, Any]
    module_digests: Mapping[str, str | None]

    @property
    def artifacts_present(self) -> bool:
        return all(check.present for check in self.artifacts)

    @property
    def artifacts_verify(self) -> bool:
        return all(check.matches for check in self.artifacts)

    @property
    def wheels_verify(self) -> bool:
        return all(check.matches for check in self.wheels)

    @property
    def environment_present(self) -> bool:
        return bool(self.observed.get("present"))

    @property
    def version_mismatches(self) -> tuple[str, ...]:
        if not self.environment_present:
            return ()
        expected = {
            "python_version": frozen.PINNED_PYTHON_VERSION,
            "machine": frozen.PINNED_MACHINE,
            "numpy": frozen.PINNED_NUMPY,
            "opencv": frozen.PINNED_OPENCV,
            "cv2_library": frozen.PINNED_CV2_LIBRARY,
        }
        return tuple(
            sorted(
                f"{key}: pinned {value!r}, found {self.observed.get(key)!r}"
                for key, value in expected.items()
                if self.observed.get(key) != value
            )
        )

    @property
    def module_mismatches(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                f"{name}: pinned {expected[:12]}…, found "
                f"{(self.module_digests.get(name) or 'absent')[:12]}…"
                for name, expected in frozen.UPSTREAM_MODULE_DIGESTS.items()
                if self.module_digests.get(name) != expected
            )
        )

    @property
    def gate_state(self) -> str:
        if not (self.artifacts_present and self.wheels_verify and self.environment_present):
            return "ACTION_REQUIRED"
        if not self.artifacts_verify:
            return "FAIL"
        if self.version_mismatches or self.module_mismatches:
            return "FAIL"
        return "PASS"

    def as_document(self) -> dict[str, Any]:
        return {
            "schema": RUNTIME_SCHEMA,
            "gate": frozen.GATES["G1"],
            "gate_state": self.gate_state,
            "candidate_id": frozen.CANDIDATE_ID,
            "package": frozen.PACKAGE_REQUIREMENT,
            "license": frozen.LICENSE,
            "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
            "upstream_index": frozen.UPSTREAM_INDEX,
            "published_artifacts": [check.as_document() for check in self.artifacts],
            "runtime_wheels": [check.as_document() for check in self.wheels],
            "pinned_environment": {
                "python_version": frozen.PINNED_PYTHON_VERSION,
                "platform": frozen.PINNED_PLATFORM,
                "machine": frozen.PINNED_MACHINE,
                "numpy": frozen.PINNED_NUMPY,
                "opencv_python": frozen.PINNED_OPENCV,
                "cv2_library": frozen.PINNED_CV2_LIBRARY,
            },
            "observed_environment": {
                key: self.observed.get(key)
                for key in (
                    "present",
                    "python_version",
                    "platform",
                    "machine",
                    "numpy",
                    "opencv",
                    "cv2_library",
                )
            },
            "installed_module_digests": dict(self.module_digests),
            "opencv_is_part_of_algorithm_identity": True,
            "opencv_generation_rule": frozen.OPENCV_GENERATION_RULE,
            "why_opencv_is_pinned": (
                "the contours cv2.findContours returns are the direct input to "
                "feature extraction, so a different OpenCV is a different feature "
                "extractor. The package declares opencv-python with no bound"
            ),
            "network_after_environment_creation": "NONE",
            "install_index": "NONE (--no-index against the local wheelhouse)",
            "version_mismatches": list(self.version_mismatches),
            "module_mismatches": list(self.module_mismatches),
            "store_is_outside_repository": True,
        }


def build_runtime_closure(*, repository_root: Path | None = None) -> RuntimeClosure:
    observed = inspect_installed_runtime(repository_root=repository_root)
    return RuntimeClosure(
        artifacts=check_artifacts(repository_root=repository_root),
        wheels=check_wheelhouse(repository_root=repository_root),
        observed=observed,
        module_digests=_installed_module_digests(observed),
    )


def runtime_manifest_fingerprint(closure: RuntimeClosure) -> str:
    """A digest of everything a stored result depends on for its number.

    Carried on every one of the 6,000 results, so a run whose environment moved
    halfway through is visible rather than merely plausible.
    """
    return stable_hash(
        {
            "schema": RUNTIME_SCHEMA,
            "package": frozen.PACKAGE_REQUIREMENT,
            "wheel_sha256": frozen.RUNTIME_ARTIFACT_SHA256,
            "python_version": frozen.PINNED_PYTHON_VERSION,
            "machine": frozen.PINNED_MACHINE,
            "numpy": frozen.PINNED_NUMPY,
            "opencv_python": frozen.PINNED_OPENCV,
            "cv2_library": frozen.PINNED_CV2_LIBRARY,
            "modules": dict(sorted(frozen.UPSTREAM_MODULE_DIGESTS.items())),
        }
    )


def require_ready(closure: RuntimeClosure) -> None:
    """Refuse to go further than G1 on a runtime that is not the frozen one."""
    if closure.gate_state == "PASS":
        return
    if not closure.artifacts_present:
        raise Stage15ARuntimeIdentityError(
            "the published artifacts are not in the local store. Fetch them with "
            "`make stage15a-acquire` before anything else runs"
        )
    if not closure.artifacts_verify:
        raise Stage15ARuntimeIdentityError(
            "the artifacts in the local store are not the bytes PyPI published "
            "for 0.1.0. This is a hard fail condition, not a re-download"
        )
    if not closure.wheels_verify:
        raise Stage15ARuntimeIdentityError(
            "the wheelhouse does not match the pinned runtime closure"
        )
    if not closure.environment_present:
        raise Stage15ARuntimeIdentityError(
            "the frozen runtime environment has not been built. Build it with "
            "`make stage15a-runtime`"
        )
    details = list(closure.version_mismatches) + list(closure.module_mismatches)
    raise Stage15ARuntimeIdentityError(
        "the frozen runtime is not the pinned one: " + "; ".join(details)
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "verify"
    closure = build_runtime_closure(repository_root=Path("."))
    if command == "verify":
        print(json.dumps(closure.as_document(), indent=2, sort_keys=True))
        return 0 if closure.gate_state == "PASS" else 1
    if command == "fingerprint":
        print(runtime_manifest_fingerprint(closure))
        return 0
    print(f"unknown command {command!r}; expected verify or fingerprint", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
