"""Re-deriving a stored operating point, rather than believing it.

An operating point is not evidence of itself. Verification takes the protocol,
the source binding and the labelled development results it cites, runs the whole
selection again, and compares — the threshold, the comparator, every count, and
the fingerprint over all of them.

Two kinds of disagreement, and they are deliberately not the same kind of event.

**These documents do not belong together.** An operating point that cites a
different protocol, or a different source binding, is not a failed verification;
it is a verification that cannot be attempted. That raises.

**These documents disagree.** The artifacts refer to each other correctly and
re-derivation produces something else — a different boundary, a different count,
a different identity. That is a finding and is returned. A changed score body,
pair-id list, or ground-truth list is not such a finding: those are source
identity, so verification refuses them before re-derivation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fpbench.calibration.models import (
    CalibrationOperatingPoint,
    CalibrationProtocol,
    CalibrationSourceBinding,
    LabeledResults,
)
from fpbench.calibration.selection import select_operating_point
from fpbench.core.calibration_errors import CalibrationVerificationError
from fpbench.core.calibration_models import ProtectedEvaluationRegistry

__all__ = ["VerificationReport", "verify_operating_point"]

#: The counts a re-derivation must reproduce exactly. Named rather than compared
#: field-by-field inline, so that a count added to the model is compared here or
#: is visibly absent from this list.
_COMPARED_COUNTS = (
    "observed_impostor_matches",
    "observed_impostor_scored",
    "observed_impostor_attempts",
    "impostor_failures",
    "observed_mated_matches",
    "observed_mated_non_matches",
    "observed_mated_scored",
    "observed_mated_attempts",
    "mated_failures",
    "target_rate_numerator",
    "target_rate_denominator",
)


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """What a re-derivation found, in a form a report can publish.

    ``verified`` is the only summary, and it is the conjunction of the three
    flags below it — there is no partial credit and no warn-and-continue: an
    operating point whose counts re-derive but whose threshold does not is not
    "mostly right", it is a different operating point.
    """

    operating_point_id: str
    stored_fingerprint: str
    recomputed_fingerprint: str

    labeled_results_hash: str
    candidate_count: int

    boundary_reproduced: bool
    counts_reproduced: bool
    fingerprint_reproduced: bool

    findings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def verified(self) -> bool:
        return (
            self.boundary_reproduced
            and self.counts_reproduced
            and self.fingerprint_reproduced
            and not self.findings
        )


def verify_operating_point(
    operating_point: CalibrationOperatingPoint,
    protocol: CalibrationProtocol,
    source_binding: CalibrationSourceBinding,
    labeled_results: LabeledResults,
    *,
    protected_registry: ProtectedEvaluationRegistry,
) -> VerificationReport:
    """Re-run the selection and compare it with what was stored.

    Raises:
        CalibrationVerificationError: the operating point does not cite this
            protocol or this source binding, so there is nothing to verify it
            against. Continuing would produce a report about two unrelated
            documents.
    """
    if not isinstance(operating_point, CalibrationOperatingPoint):
        raise CalibrationVerificationError(
            "verification needs a stored operating point to compare against"
        )
    if operating_point.calibration_protocol_fingerprint != (
        protocol.protocol_fingerprint
    ):
        raise CalibrationVerificationError(
            f"operating point {operating_point.operating_point_id} was selected "
            f"under protocol {operating_point.calibration_protocol_fingerprint[:12]}"
            f"... and is being verified against "
            f"{protocol.protocol_fingerprint[:12]}..."
        )
    if operating_point.source_binding_fingerprint != (
        source_binding.source_binding_fingerprint
    ):
        raise CalibrationVerificationError(
            f"operating point {operating_point.operating_point_id} was selected "
            f"from source {operating_point.source_binding_fingerprint[:12]}... and "
            f"is being verified against "
            f"{source_binding.source_binding_fingerprint[:12]}..."
        )
    actual_results_hash = labeled_results.content_hash()
    if source_binding.labeled_results_hash != actual_results_hash:
        raise CalibrationVerificationError(
            f"source binding {source_binding.binding_id!r} binds labelled results "
            f"{source_binding.labeled_results_hash[:12]}... but verification was "
            f"given {actual_results_hash[:12]}..."
        )
    if operating_point.labeled_results_hash != actual_results_hash:
        raise CalibrationVerificationError(
            f"operating point {operating_point.operating_point_id} binds labelled "
            f"results {operating_point.labeled_results_hash[:12]}... but "
            f"verification was given {actual_results_hash[:12]}..."
        )
    if (
        source_binding.pair_ids != labeled_results.pair_ids
        or operating_point.pair_ids != labeled_results.pair_ids
    ):
        raise CalibrationVerificationError(
            "the source binding, operating point and labelled results do not bind "
            "one pair_id list"
        )
    if (
        source_binding.ground_truth != labeled_results.ground_truth
        or operating_point.ground_truth != labeled_results.ground_truth
    ):
        raise CalibrationVerificationError(
            "the source binding, operating point and labelled results do not bind "
            "one ground-truth list"
        )

    # The whole selection, again, from the labelled scores. The wall clock and
    # the commit are carried across rather than re-read: neither is inside the
    # fingerprint, and re-deriving them would compare the machine rather than the
    # calibration (spec section 20).
    rederived = select_operating_point(
        protocol,
        source_binding,
        labeled_results,
        protected_registry=protected_registry,
        created_source_commit=operating_point.created_source_commit,
        created_source_tree_clean=operating_point.created_source_tree_clean,
        created_utc=operating_point.created_utc,
    )

    findings: list[str] = []
    boundary_reproduced = (
        rederived.threshold == operating_point.threshold
        and rederived.comparator is operating_point.comparator
        and rederived.score_direction is operating_point.score_direction
    )
    if not boundary_reproduced:
        findings.append(
            f"boundary re-derived as {rederived.threshold} "
            f"{rederived.comparator.value}, stored as {operating_point.threshold} "
            f"{operating_point.comparator.value}"
        )

    counts_reproduced = True
    for name in _COMPARED_COUNTS:
        stored = getattr(operating_point, name)
        recomputed = getattr(rederived, name)
        if stored != recomputed:
            counts_reproduced = False
            findings.append(f"{name} re-derived as {recomputed}, stored as {stored}")

    fingerprint_reproduced = (
        rederived.operating_point_fingerprint
        == operating_point.operating_point_fingerprint
    )
    if not fingerprint_reproduced:
        findings.append(
            "the re-derived operating point has a different identity from the "
            "stored one"
        )

    from fpbench.calibration.selection import candidate_boundaries

    return VerificationReport(
        operating_point_id=operating_point.operating_point_id,
        stored_fingerprint=operating_point.operating_point_fingerprint,
        recomputed_fingerprint=rederived.operating_point_fingerprint,
        labeled_results_hash=labeled_results.content_hash(),
        candidate_count=len(candidate_boundaries(labeled_results)),
        boundary_reproduced=boundary_reproduced,
        counts_reproduced=counts_reproduced,
        fingerprint_reproduced=fingerprint_reproduced,
        findings=tuple(findings),
    )
