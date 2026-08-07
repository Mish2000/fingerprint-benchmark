"""Stage 8D's experiment layer: the protected registry, and the qualification.

Two jobs, and the first one is the reason the second is trustworthy.

**Building the protected-evaluation registry.** The identities of the material a
calibration may never draw a threshold from are frozen in
:mod:`fpbench.experiments.stage8d_identity`, and this module re-reads the
published documents they were copied from and refuses on any disagreement. That
makes the frozen list a *reviewable copy of an authority* rather than a second
authority — the same relationship Stage 8C's frozen constants have with Stage
8B's evidence.

What is read is exactly the identity keys, named one document at a time: run
ids, run fingerprints, result-set fingerprints, a cohort fingerprint, a
pair-manifest hash. No results file is opened, no parquet is touched, no
workspace is consulted, and no score is read (spec section 24).

**Running the synthetic qualification.** Every claim Stage 8D makes about the
calibration engine, exercised on fixtures this module builds from nothing. There
is no dataset, no runtime, no checkpoint and no prior result set anywhere in it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from fpbench.calibration.protocol import build_protected_evaluation_registry
from fpbench.core.calibration_errors import Stage8DFinalizationError
from fpbench.core.calibration_models import (
    ProtectedEvaluationIdentity,
    ProtectedEvaluationRegistry,
)
from fpbench.core.enums import ProtectedIdentityKind
from fpbench.experiments import stage8d_identity as frozen

__all__ = [
    "build_registry",
    "read_published_identity_values",
    "require_frozen_identities_match_published_evidence",
    "require_stage8c_is_the_stage_this_follows",
]


def _read_document(repository_root: Path, relative: str) -> Mapping[str, Any]:
    path = Path(repository_root) / PurePosixPath(relative)
    if not path.is_file():
        raise Stage8DFinalizationError(
            f"Stage 8D cannot build the protected registry: {relative} is not "
            "published"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage8DFinalizationError(
            f"published evidence {relative} is not readable JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise Stage8DFinalizationError(
            f"published evidence {relative} is not a JSON object"
        )
    return document


def read_published_identity_values(repository_root: Path) -> dict[str, str]:
    """Every identity value Stage 8D is entitled to read, and only those.

    Keyed by ``<document>:<key>`` so that two documents carrying the same key
    name — and they do, ``run_id`` appears in three — stay distinguishable.
    """
    values: dict[str, str] = {}
    for relative, keys in frozen.PROTECTED_SOURCE_DOCUMENTS:
        document = _read_document(repository_root, relative)
        for key in keys:
            if key not in document:
                raise Stage8DFinalizationError(
                    f"{relative} does not carry {key!r}, which Stage 8D's "
                    "protected registry is built from"
                )
            value = document[key]
            if not isinstance(value, str) or not value.strip():
                raise Stage8DFinalizationError(
                    f"{relative}: {key!r} is not a non-empty string"
                )
            values[f"{relative}:{key}"] = value.strip()
    return values


def require_frozen_identities_match_published_evidence(
    repository_root: Path,
) -> dict[str, str]:
    """Every frozen identity and fingerprint must appear in a published document.

    Checked by *value* rather than by position. A frozen digest that no published
    document carries would mean the registry is protecting something this
    repository does not have, which is at best a typo and at worst a registry
    that protects nothing real.
    """
    published = read_published_identity_values(repository_root)
    known = set(published.values())
    missing = [
        f"{kind.value} {identity} ({fingerprint[:12]}...)"
        for kind, identity, fingerprint, _label in frozen.PROTECTED_IDENTITIES
        if identity not in known or fingerprint not in known
    ]
    if missing:
        raise Stage8DFinalizationError(
            "the frozen protected identities are not all present in the published "
            f"evidence they were copied from: {missing}"
        )
    return published


def require_stage8c_is_the_stage_this_follows(repository_root: Path) -> None:
    """Confirm the closed stage is the one Stage 8D thinks it follows.

    Read-only, and it is the only thing Stage 8D does with Stage 8C's evidence.
    Nothing under that directory is edited and nothing is re-derived: the change
    of plan is recorded in an ADR, not by amending a closed stage's published
    record (docs/adr/0078).
    """
    document = _read_document(
        repository_root, "evidence/flx-canonical500-raw/stage-8c-finalization.json"
    )
    fingerprint = str(document.get("stage_8c_finalization_fingerprint", "")).strip()
    outcome = str(document.get("outcome", "")).strip()
    if fingerprint != frozen.STAGE8C_FINALIZATION_FINGERPRINT:
        raise Stage8DFinalizationError(
            "the published Stage 8C marker is not the one Stage 8D was frozen "
            f"against: {fingerprint[:12]}... vs "
            f"{frozen.STAGE8C_FINALIZATION_FINGERPRINT[:12]}..."
        )
    if outcome != frozen.STAGE8C_OUTCOME:
        raise Stage8DFinalizationError(
            f"the published Stage 8C outcome is {outcome!r}, not "
            f"{frozen.STAGE8C_OUTCOME!r}"
        )
    if document.get("opens_stage_8d") is not True:
        raise Stage8DFinalizationError(
            "the published Stage 8C marker does not open Stage 8D"
        )


def build_registry(
    repository_root: Path | None = None,
) -> ProtectedEvaluationRegistry:
    """The registry, optionally checked against the evidence it was copied from.

    ``repository_root`` is optional so that a contract test can build the
    registry without a checkout of the published evidence. Every path that
    *publishes* anything passes it, so the check is skipped only where there is
    nothing to check against.
    """
    if repository_root is not None:
        require_frozen_identities_match_published_evidence(repository_root)
    return build_protected_evaluation_registry(
        registry_id=frozen.REGISTRY_ID,
        registry_version=frozen.REGISTRY_VERSION,
        entries=[
            ProtectedEvaluationIdentity(
                kind=kind, identity=identity, fingerprint=fingerprint, label=label
            )
            for kind, identity, fingerprint, label in frozen.PROTECTED_IDENTITIES
        ],
    )


@dataclass(frozen=True, slots=True)
class RegistryCoverage:
    """What the registry protects, counted by kind.

    Published in the evidence so a reader can see at a glance that every executed
    algorithm's canonical result set is registered, without the evidence having
    to name a score.
    """

    total: int
    by_kind: Mapping[str, int]

    @classmethod
    def of(cls, registry: ProtectedEvaluationRegistry) -> "RegistryCoverage":
        counts: dict[str, int] = {}
        for entry in registry.entries:
            counts[entry.kind.value] = counts.get(entry.kind.value, 0) + 1
        return cls(
            total=len(registry.entries),
            by_kind={kind: counts[kind] for kind in sorted(counts)},
        )

    def require_every_executed_algorithm_is_registered(self, expected: int) -> None:
        """One canonical result set per algorithm that has run the 6,000.

        A result set that was published and never registered is a result set the
        engine would happily calibrate on, and nothing would announce it
        (docs/adr/0079).
        """
        registered = self.by_kind.get(ProtectedIdentityKind.RESULT_SET.value, 0)
        if registered != expected:
            raise Stage8DFinalizationError(
                f"{registered} canonical result sets are registered as protected "
                f"evaluation material, and {expected} have been published"
            )
