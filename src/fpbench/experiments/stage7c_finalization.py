"""The Stage 7C marker that makes input alignment load-bearing.

The general research finalization marker proves that a run, its result set and
its algorithm-specific validation form one verified chain.  Stage 7C makes one
additional claim that the general engine cannot know about: the NBIS run used
the reference run's exact pairs and prepared pixels.  This marker binds that
alignment report, its reference identities and the general research chain into
one last-written document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import stable_hash, to_plain

__all__ = [
    "STAGE_7C_FINALIZATION_SCHEMA_VERSION",
    "STAGE_7C_FINALIZATION_KIND",
    "Stage7CFinalization",
    "alignment_report_content_hash",
    "stage_7c_finalization_fingerprint",
]

STAGE_7C_FINALIZATION_SCHEMA_VERSION = "1"
STAGE_7C_FINALIZATION_KIND = "stage_7c_finalization"
_HEX = frozenset("0123456789abcdef")


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


@dataclass(frozen=True, slots=True)
class Stage7CFinalization:
    """Immutable authority for Stage 7C's alignment claim."""

    schema_version: str
    kind: str

    run_id: str
    run_fingerprint: str
    result_set_id: str
    result_set_fingerprint: str

    research_receipt_fingerprint: str
    research_receipt_content_hash: str
    research_finalization_fingerprint: str

    reference_run_id: str
    reference_plan_id: str
    reference_result_set_id: str

    alignment_fingerprint: str
    alignment_report_content_hash: str

    verifier_source_commit: str
    verifier_source_tree_clean: bool

    stage_7c_finalization_fingerprint: str
    created_utc: str

    def __post_init__(self) -> None:
        version = str(self.schema_version).strip()
        if version != STAGE_7C_FINALIZATION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Stage 7C finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        if self.kind != STAGE_7C_FINALIZATION_KIND:
            raise ValueError(f"kind must be {STAGE_7C_FINALIZATION_KIND!r}")
        for name in (
            "run_id",
            "result_set_id",
            "reference_run_id",
            "reference_plan_id",
            "reference_result_set_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in (
            "run_fingerprint",
            "result_set_fingerprint",
            "research_receipt_fingerprint",
            "research_receipt_content_hash",
            "research_finalization_fingerprint",
            "alignment_fingerprint",
            "alignment_report_content_hash",
            "stage_7c_finalization_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        commit = str(self.verifier_source_commit).strip().lower()
        if len(commit) != 40 or not set(commit) <= _HEX:
            raise ValueError(
                "verifier_source_commit must be a full 40-character commit SHA"
            )
        object.__setattr__(self, "verifier_source_commit", commit)
        if self.verifier_source_tree_clean is not True:
            raise ValueError("Stage 7C finalization requires a clean verifier tree")
        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        expected = stage_7c_finalization_fingerprint(self)
        if self.stage_7c_finalization_fingerprint != expected:
            raise ValueError(
                "stage_7c_finalization_fingerprint does not cover the marker's claims"
            )


def alignment_report_content_hash(report: Mapping[str, Any] | Any) -> str:
    """Digest the complete stored report, including its inspection timestamp."""
    return stable_hash(
        {
            "schema": "stage_7c_alignment_report_content_v1",
            "alignment_report": to_plain(report),
        },
        length=64,
    )


def stage_7c_finalization_fingerprint(
    marker: Stage7CFinalization | Mapping[str, Any],
) -> str:
    """Derive the marker identity without its own identity or wall clock."""
    plain = dict(to_plain(marker))
    plain.pop("stage_7c_finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "stage_7c_finalization_v1", "marker": plain}, length=64
    )
