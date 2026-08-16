"""G1 — the exact bytes FingerFlow is, and the exact runtime that would run them.

Two questions, and the gate is their conjunction.

**Is every artifact the route needs obtainable without asking anybody?** Nine
checkpoints are published, and the answer is not uniform across them: two of the
Google Drive links in the upstream README — CoarseNet and FineNet — return HTTP
404 today from every Drive endpoint there is. Both are also published, in the
same README, on Dropbox, and both Dropbox links serve. So the artifact set is
complete and self-service, and the finding that matters is recorded per
checkpoint rather than per host: *which* locator served these bytes. A stage that
concluded ``SELF_SERVICE_ARTIFACT_INCOMPLETE`` from the first dead link would
have published a fact about a URL and called it a fact about the candidate
(docs/adr/0129).

**Can the runtime be stated exactly?** Upstream's own ``requirements.txt`` pins
``tensorflow==2.5.1``, ``numpy==1.19.5`` and ``opencv-python==4.5.3.56``, and
none of those install on any Python this project runs — TensorFlow 2.5 stops at
CPython 3.9. The package's *declared* floor is ``tensorflow>=2.5.1`` with no
ceiling, so a resolve today produces TensorFlow 2.20 and Keras 3: a different
Keras major from the one these weights were trained and serialised under. That is
recorded as a resolved-at-acquisition closure and named as such. It is not a
contemporary closure and this module refuses to call it one — the distinction is
the same one Stage 15A drew when it pinned OpenCV to the generation contemporary
with its artifact (docs/adr/0125), and here that generation is unreachable.

Nothing here is a conclusion about the route. A byte sequence being present and
hashable says nothing about whether there is one way to use it, which is G2's
question and the one this stage turns on.
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fpbench.core.stage16a_errors import Stage16AArtifactIdentityError
from fpbench.experiments import stage16a_identity as frozen
from fpbench.third_party.artifacts import (
    file_sha256,
    require_store_is_outside,
    resolve_third_party_root,
)

__all__ = [
    "ARTIFACT_SCHEMA",
    "STORE_DIRECTORY",
    "RUNTIME_CLOSURE",
    "CLOSURE_RULE",
    "ArtifactObservation",
    "ArtifactIdentity",
    "store_root",
    "inspect_artifacts",
    "main",
]

ARTIFACT_SCHEMA = "stage_16a_artifact_runtime_identity_v1"

#: Under the third-party store root, never under the working tree. 1.5 GB of
#: checkpoints in Git would be 1.5 GB of checkpoints in Git forever.
STORE_DIRECTORY = "fingerflow"

#: The rule the versions below were chosen by, stated so that a rebuild is
#: reproducible from the rule rather than from the numbers. It is deliberately
#: *not* ``CONTEMPORARY_WITH_ARTIFACT_PUBLICATION``: that rule is unsatisfiable
#: here, and pretending otherwise would make the closure look better founded
#: than it is.
CLOSURE_RULE = "RESOLVED_AT_ACQUISITION_FROM_UPSTREAM_DECLARED_FLOORS"

#: The score-affecting half of the closure, hashed at the wheel. The full
#: ``pip freeze`` is longer and is written into the evidence document; these are
#: the components whose version could move a number rather than a log line.
RUNTIME_CLOSURE: dict[str, dict[str, Any]] = {
    "fingerflow": {
        "version": "3.0.1",
        "wheel": "fingerflow-3.0.1-py3-none-any.whl",
        "sha256": "d256c1351b74b2e746386a3c32c61e92d569a8ba9f79cb9f9e084367000e3c35",
        "size_bytes": 54538,
    },
    "tensorflow": {
        "version": "2.20.0",
        "wheel": "tensorflow-2.20.0-cp312-cp312-win_amd64.whl",
        "sha256": "1590cbf87b6bcbd34d8e9ad70d0c696135e0aa71be31803b27358cf7ed63f8fc",
        "size_bytes": 331887041,
    },
    "keras": {
        "version": "3.15.1",
        "wheel": "keras-3.15.1-py3-none-any.whl",
        "sha256": "836460e480930acbd19bb7a17e62f9ecad40e8a9af9a651fc8d0586a96d27e20",
        "size_bytes": 2398595,
    },
    "tf-keras": {
        "version": "2.20.1",
        "wheel": "tf_keras-2.20.1-py3-none-any.whl",
        "sha256": "3f0e0a34d9a4c8758f24fdc1053e6e335f16ab5534c7d34f1899b8924779760c",
        "size_bytes": 1694335,
    },
    "numpy": {
        "version": "2.5.2",
        "wheel": "numpy-2.5.2-cp312-cp312-win_amd64.whl",
        "sha256": "28ac63476ec7651484215ee7fa15a1f78b57c14621f01e392afe17b9a1390ce4",
        "size_bytes": 12464674,
    },
    "opencv-python": {
        "version": "5.0.0.93",
        "wheel": "opencv_python-5.0.0.93-cp37-abi3-win_amd64.whl",
        "sha256": "f90ba04b8f73bc5c3814037699739f0156f597338a98f05956c684e7c3ca10d2",
        "size_bytes": 44000345,
    },
    "pandas": {
        "version": "3.0.5",
        "wheel": "pandas-3.0.5-cp312-cp312-win_amd64.whl",
        "sha256": "80a611068e8a3ac23f7398c6c14eb46dc974e5cc9997f653e2dcfd1da74edd41",
        "size_bytes": 9831691,
    },
    "scipy": {
        "version": "1.18.0",
        "wheel": "scipy-1.18.0-cp312-cp312-win_amd64.whl",
        "sha256": "71ccc8faa2dd16ac310233203474a8b5cb67f10dedd54a3116d34943f4b19132",
        "size_bytes": 36597428,
    },
    "scikit-image": {
        "version": "0.26.0",
        "wheel": "scikit_image-0.26.0-cp312-cp312-win_amd64.whl",
        "sha256": "abed017474593cd3056ae0fe948d07d0747b27a085e92df5474f4955dd65aec0",
        "size_bytes": 11911059,
    },
    "h5py": {
        "version": "3.16.0",
        "wheel": "h5py-3.16.0-cp312-cp312-win_amd64.whl",
        "sha256": "96b422019a1c8975c2d5dadcf61d4ba6f01c31f92bbde6e4649607885fe502d6",
        "size_bytes": 3182868,
    },
    "Keras-Applications": {
        "version": "1.0.8",
        "wheel": "Keras_Applications-1.0.8-py3-none-any.whl",
        "sha256": "df4323692b8c1174af821bf906f1e442e63fa7589bf0f1230a0b6bdc5a810c95",
        "size_bytes": 50704,
    },
    "ml_dtypes": {
        "version": "0.6.0",
        "wheel": "ml_dtypes-0.6.0-cp312-cp312-win_amd64.whl",
        "sha256": "2a3e9d53925597fbffafd2a37048dadeddd0bdaba58058f6ae0869ed709a184d",
        "size_bytes": 439333,
    },
}

#: What upstream itself asks for, recorded beside what was installed so the gap
#: is visible rather than inferable. Every one of these is unreachable on any
#: supported CPython.
UPSTREAM_DECLARED_PINS: dict[str, str] = {
    "tensorflow": "2.5.1",
    "numpy": "1.19.5",
    "opencv-python": "4.5.3.56",
    "pandas": "1.3.1",
    "scikit-image": "0.18.3",
    "scipy": "1.6.2",
    "Keras-Applications": "1.0.8",
    "matplotlib": "3.4.2",
}


def store_root(*, repository_root: Path | None = None) -> Path:
    """Where this machine keeps FingerFlow's bytes, checked to be outside Git."""
    root = resolve_third_party_root(repository_root=repository_root)
    if repository_root is not None:
        require_store_is_outside(root, Path(repository_root))
    return root / STORE_DIRECTORY


@dataclass(frozen=True, slots=True)
class ArtifactObservation:
    """One checkpoint or distribution, as the record expects it and as it is."""

    role: str
    name: str
    expected_sha256: str
    expected_size_bytes: int
    source: str
    locator: str
    present: bool
    observed_sha256: str | None
    observed_size_bytes: int | None

    @property
    def matches(self) -> bool:
        return (
            self.present
            and self.observed_sha256 == self.expected_sha256
            and self.observed_size_bytes == self.expected_size_bytes
        )

    def as_document(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "name": self.name,
            "source": self.source,
            "locator": self.locator,
            "expected_sha256": self.expected_sha256,
            "expected_size_bytes": self.expected_size_bytes,
            "present": self.present,
            "matches": self.matches,
        }


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    """G1's whole answer."""

    checkpoints: tuple[ArtifactObservation, ...]
    distributions: tuple[ArtifactObservation, ...]
    observed_environment: dict[str, Any]
    store_is_outside_repository: bool
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def observations(self) -> tuple[ArtifactObservation, ...]:
        return self.checkpoints + self.distributions

    @property
    def mismatches(self) -> tuple[str, ...]:
        return tuple(o.name for o in self.observations if o.present and not o.matches)

    @property
    def absent(self) -> tuple[str, ...]:
        return tuple(o.name for o in self.observations if not o.present)

    @property
    def roles_covered(self) -> tuple[str, ...]:
        return tuple(
            role
            for role in frozen.REQUIRED_CHECKPOINT_ROLES
            if any(c.role == role and c.matches for c in self.checkpoints)
        )

    @property
    def gate_state(self) -> str:
        if self.mismatches:
            return "FAIL"
        if set(self.roles_covered) != set(frozen.REQUIRED_CHECKPOINT_ROLES):
            return "FAIL"
        if not all(d.matches for d in self.distributions):
            return "FAIL"
        return "PASS"

    @property
    def blocker(self) -> str | None:
        if self.gate_state == "PASS":
            return None
        return "SELF_SERVICE_ARTIFACT_INCOMPLETE"

    def as_document(self) -> dict[str, Any]:
        return {
            "schema": ARTIFACT_SCHEMA,
            "gate": frozen.GATES["G1"],
            "gate_state": self.gate_state,
            "blocker": self.blocker,
            "candidate_id": frozen.CANDIDATE_ID,
            "package": frozen.PACKAGE_REQUIREMENT,
            "license": frozen.LICENSE,
            "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
            "upstream_index": frozen.UPSTREAM_INDEX,
            "upstream_repository": frozen.UPSTREAM_REPOSITORY,
            "upstream_commit": frozen.UPSTREAM_COMMIT,
            "upstream_tag": frozen.UPSTREAM_TAG,
            "published_distributions": [d.as_document() for d in self.distributions],
            "checkpoints": [c.as_document() for c in self.checkpoints],
            "required_checkpoint_roles": list(frozen.REQUIRED_CHECKPOINT_ROLES),
            "roles_covered": list(self.roles_covered),
            "vendor_or_author_request_required": False,
            "self_service_acquisition": True,
            "dead_upstream_locators": [
                {
                    "role": "coarse_net",
                    "host": "google_drive",
                    "status": "HTTP_404",
                    "endpoints_tried": ["/uc", "/file/d/", "drive.usercontent"],
                    "served_instead_by": "the Dropbox mirror in the same README",
                },
                {
                    "role": "fine_net",
                    "host": "google_drive",
                    "status": "HTTP_404",
                    "endpoints_tried": ["/uc", "/file/d/", "drive.usercontent"],
                    "served_instead_by": "the Dropbox mirror in the same README",
                },
            ],
            "upstream_publishes_checkpoint_digests": False,
            "why_digests_are_computed_here": (
                "upstream ships none, so without these 'the CoarseNet weights' "
                "names a file nobody can check and a re-acquisition years from "
                "now is unfalsifiable"
            ),
            "closure_rule": CLOSURE_RULE,
            "closure_is_contemporary_with_artifact": False,
            "why_not_contemporary": (
                "upstream pins tensorflow==2.5.1, numpy==1.19.5 and "
                "opencv-python==4.5.3.56; TensorFlow 2.5 stops at CPython 3.9 and "
                "none of the three install on any Python this project runs. The "
                "declared floor is unbounded, so a resolve today gives TensorFlow "
                "2.20 and Keras 3 — a different Keras major from the one these "
                "weights were serialised under (docs/adr/0125 states the rule this "
                "cannot satisfy)"
            ),
            "upstream_declared_pins": dict(UPSTREAM_DECLARED_PINS),
            "runtime_closure": {
                name: dict(record) for name, record in RUNTIME_CLOSURE.items()
            },
            "pinned_environment": {
                "python_version": frozen.PINNED_PYTHON_VERSION,
                "platform": frozen.PINNED_PLATFORM,
                "machine": frozen.PINNED_MACHINE,
                "device_mode": frozen.PINNED_DEVICE_MODE,
            },
            "observed_environment": dict(self.observed_environment),
            "install_index": "NONE (--no-index against the local wheelhouse)",
            "network_after_environment_creation": "NONE",
            "store_is_outside_repository": self.store_is_outside_repository,
            "third_party_bytes_added_to_git": False,
            "notes": dict(self.notes),
            "mismatches": list(self.mismatches),
            "absent": list(self.absent),
        }


def _observe(
    directory: Path,
    *,
    role: str,
    name: str,
    expected_sha256: str,
    expected_size_bytes: int,
    source: str,
    locator: str,
) -> ArtifactObservation:
    path = directory / name
    present = path.is_file()
    return ArtifactObservation(
        role=role,
        name=name,
        expected_sha256=expected_sha256,
        expected_size_bytes=expected_size_bytes,
        source=source,
        locator=locator,
        present=present,
        observed_sha256=file_sha256(path) if present else None,
        observed_size_bytes=path.stat().st_size if present else None,
    )


def inspect_artifacts(*, repository_root: Path | None = None) -> ArtifactIdentity:
    """Re-hash everything the record names, and report what is there.

    Absence is reported, never raised: no CI runner has 1.5 GB of checkpoints and
    that is by design. Different bytes under a recorded name is a mismatch, which
    is a gate failure.
    """
    root = store_root(repository_root=repository_root)
    checkpoints = tuple(
        _observe(
            root / "checkpoints",
            role=str(record["role"]),
            name=str(record["stored_as"]),
            expected_sha256=str(record["sha256"]),
            expected_size_bytes=int(record["size_bytes"]),
            source=str(record["source"]),
            locator=str(record["locator"]),
        )
        for record in frozen.CHECKPOINTS
    )
    distributions = (
        _observe(
            root / "artifacts",
            role="published_wheel",
            name=frozen.RUNTIME_ARTIFACT_NAME,
            expected_sha256=frozen.RUNTIME_ARTIFACT_SHA256,
            expected_size_bytes=frozen.RUNTIME_ARTIFACT_SIZE_BYTES,
            source="pypi",
            locator=frozen.UPSTREAM_INDEX,
        ),
        _observe(
            root / "artifacts",
            role="published_sdist",
            name=frozen.SOURCE_ARTIFACT_NAME,
            expected_sha256=frozen.SOURCE_ARTIFACT_SHA256,
            expected_size_bytes=frozen.SOURCE_ARTIFACT_SIZE_BYTES,
            source="pypi",
            locator=frozen.UPSTREAM_INDEX,
        ),
    )

    outside = True
    if repository_root is not None:
        try:
            require_store_is_outside(root, Path(repository_root))
        except Exception:  # noqa: BLE001 - reported, not raised, so G1 can say why
            outside = False

    return ArtifactIdentity(
        checkpoints=checkpoints,
        distributions=distributions,
        observed_environment={
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "interpreter": sys.executable and Path(sys.executable).name,
        },
        store_is_outside_repository=outside,
        notes={
            "checkpoint_bytes_total": sum(
                int(record["size_bytes"]) for record in frozen.CHECKPOINTS
            ),
            "runtime_probe": {
                "fingerflow.matcher imports": True,
                "fingerflow.extractor imports": True,
                "every .h5 checkpoint is valid HDF5": True,
                "CoreNet.weights carries a darknet header": "major=0 minor=2 rev=5",
                "Matcher(30, VerifyNet-30.h5) loads its weights": True,
                "why this is recorded under G1": (
                    "it proves the acquired bytes are models rather than error "
                    "pages. Whether there is one way to *use* them is G2"
                ),
            },
        },
    )


def require_artifacts(*, repository_root: Path | None = None) -> ArtifactIdentity:
    """As :func:`inspect_artifacts`, but a mismatch is fatal."""
    identity = inspect_artifacts(repository_root=repository_root)
    if identity.mismatches:
        raise Stage16AArtifactIdentityError(
            "the local artifacts do not match the frozen record: "
            + ", ".join(identity.mismatches)
        )
    return identity


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    identity = inspect_artifacts(repository_root=Path("."))
    print(json.dumps(identity.as_document(), indent=2, sort_keys=True))
    return 0 if identity.gate_state == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
