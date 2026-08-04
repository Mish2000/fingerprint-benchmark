"""Strict loading of the three commit-3 acquisition manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fpbench.core.errors import CandidateArtifactError
from fpbench.core.modern_matcher_models import (
    CandidateArtifactManifest,
    ModernMatcherCandidateRegistry,
)
from fpbench.modern_matchers.loading import artifact_manifest_from_plain

__all__ = ["load_acquisition_manifests"]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is forbidden")


def load_acquisition_manifests(
    directory: Path,
    *,
    registry: ModernMatcherCandidateRegistry,
) -> tuple[CandidateArtifactManifest, ...]:
    """Load exactly one strict manifest per frozen candidate, in registry order."""
    directory = Path(directory)
    expected = {
        f"{candidate.candidate_id}.json": candidate
        for candidate in registry.candidates
    }
    if not directory.is_dir():
        raise CandidateArtifactError(f"acquisition manifest directory not found: {directory}")
    actual = {path.name for path in directory.glob("*.json")}
    if actual != set(expected):
        raise CandidateArtifactError(
            "acquisition manifest set must match the frozen registry exactly; "
            f"missing={sorted(set(expected) - actual)}, "
            f"extra={sorted(actual - set(expected))}"
        )
    manifests: list[CandidateArtifactManifest] = []
    for filename, candidate in expected.items():
        path = directory / filename
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_nonfinite_json,
            )
            manifest = artifact_manifest_from_plain(payload)
        except (OSError, TypeError, ValueError) as exc:
            raise CandidateArtifactError(
                f"{path}: invalid acquisition manifest ({exc})"
            ) from exc
        if manifest.candidate_id != candidate.candidate_id:
            raise CandidateArtifactError(
                f"{path}: filename and candidate id disagree"
            )
        if manifest.registry_fingerprint != registry.fingerprint:
            raise CandidateArtifactError(
                f"{candidate.candidate_id}: acquisition manifest names another registry"
            )
        if manifest.candidate_fingerprint != candidate.fingerprint:
            raise CandidateArtifactError(
                f"{candidate.candidate_id}: acquisition manifest names another candidate identity"
            )
        manifests.append(manifest)
    return tuple(manifests)
