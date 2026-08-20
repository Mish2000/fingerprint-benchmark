"""What must be true before a single development score is read.

Order matters here more than anywhere else in the package. The role check runs
*first* — before the labelled rows are touched, not after they are counted —
because "we read the evaluation scores and then refused them" is not a refusal
(docs/adr/0079).

Everything below is a precondition of a selection rather than a property of one.
None of it looks at a score's value; the checks are about whether these scores
may be used at all, whether the binding describes the body of results it was
handed, and whether the protocol's requirements are satisfiable by what is
present.
"""

from __future__ import annotations

from typing import Any

from fpbench.core.calibration_errors import (
    CalibrationInputError,
    CalibrationLeakageError,
    CalibrationSourceError,
)
from fpbench.core.calibration_models import (
    CalibrationProtocol,
    CalibrationSourceBinding,
    ProtectedEvaluationRegistry,
)
from fpbench.core.enums import CalibrationPairTruth, CohortRole

__all__ = [
    "require_development_role",
    "require_unprotected_source",
    "require_binding_describes_results",
    "require_populations_for",
    "validate_calibration_inputs",
]

MATED = CalibrationPairTruth.MATED
IMPOSTOR = CalibrationPairTruth.CROSS_SUBJECT_IMPOSTOR


def require_development_role(binding: CalibrationSourceBinding) -> None:
    """Refuse an evaluation cohort on the strength of the binding alone.

    Takes the binding and nothing else, deliberately. A check that needed the
    scores in order to decide whether it may read the scores would have already
    read them.
    """
    if not isinstance(binding, CalibrationSourceBinding):
        raise CalibrationSourceError(
            "a calibration needs a source binding; scores handed over without one "
            "are scores nobody can say the provenance of"
        )
    if not binding.cohort_role.permits_threshold_selection:
        raise CalibrationLeakageError(
            f"cohort {binding.cohort_id!r} is declared "
            f"{binding.cohort_role.value!r}, and a threshold may only be chosen on "
            f"a {CohortRole.DEVELOPMENT.value!r} cohort. Choosing it on the cohort "
            "it is later reported on is the one form of leakage that invalidates "
            "the whole study (docs/adr/0021, docs/adr/0079)"
        )


def require_unprotected_source(
    binding: CalibrationSourceBinding,
    registry: ProtectedEvaluationRegistry | None,
) -> None:
    """Refuse a binding that resolves to registered evaluation material.

    The second half of the role check, and the half that catches an honest
    mistake. A binding can claim ``development`` and still point at the protected
    run — through a copied identity, a re-declared result set, or a fixture built
    from the real numbers because they were to hand. The declared role cannot
    detect that; the identities can (docs/adr/0079).

    A ``None`` registry is not "no protection". It is refused, because a
    calibration that ran without the registry loaded would look exactly like one
    that ran with it and found nothing.
    """
    if registry is None:
        raise CalibrationLeakageError(
            "a calibration needs the protected-evaluation registry to run against; "
            "without it, a selection that read the evaluation scores would be "
            "indistinguishable from one that did not"
        )
    if not isinstance(registry, ProtectedEvaluationRegistry):
        raise CalibrationLeakageError(
            "the protected-evaluation registry must be a verified registry artifact"
        )
    matched = registry.matches(
        fingerprints=binding.identity_fingerprints,
        identities=binding.identity_ids,
    )
    if matched:
        detail = ", ".join(
            f"{entry.kind.value} {entry.identity} ({entry.label})" for entry in matched
        )
        raise CalibrationLeakageError(
            f"source binding {binding.binding_id!r} resolves to protected "
            f"evaluation material: {detail}. It claims cohort role "
            f"{binding.cohort_role.value!r}, and the identities say otherwise "
            "(docs/adr/0079)"
        )


def require_binding_describes_results(
    binding: CalibrationSourceBinding, results: Any
) -> None:
    """The binding must describe this exact labelled view of its result set.

    A binding that declared one direction over results carrying the other would
    invert every decision made under the resulting threshold, and the operating
    point would look entirely ordinary.
    """
    if binding.score_direction is not results.score_direction:
        raise CalibrationSourceError(
            f"source binding {binding.binding_id!r} declares score direction "
            f"{binding.score_direction.value!r} but the labelled results run "
            f"{results.score_direction.value!r}; the two disagree about which side "
            "of a boundary is a match"
        )
    actual_hash = results.content_hash()
    if binding.labeled_results_hash != actual_hash:
        raise CalibrationSourceError(
            f"source binding {binding.binding_id!r} binds labelled results "
            f"{binding.labeled_results_hash[:12]}... but received "
            f"{actual_hash[:12]}...; scores from another result set cannot be "
            "calibrated under this binding"
        )
    if binding.pair_ids != results.pair_ids:
        raise CalibrationSourceError(
            f"source binding {binding.binding_id!r} does not bind this pair_id list"
        )
    if binding.ground_truth != results.ground_truth:
        raise CalibrationSourceError(
            f"source binding {binding.binding_id!r} does not bind these ground-truth labels"
        )


def require_populations_for(protocol: CalibrationProtocol, results: Any) -> None:
    """Both populations must be present, and the impostors must be scored.

    The mated population is required even though the selection rule does not
    constrain it. Genuine performance at the chosen boundary is what the rule
    produces as a *consequence*, and a development set that cannot report it has
    not calibrated anything anybody can read (spec section 16).
    """
    if protocol.requires_cross_subject_impostors and not results.of(IMPOSTOR):
        raise CalibrationInputError(
            "this protocol is defined over cross-subject impostor comparisons and "
            "the labelled results contain none. The same-subject sanity "
            "comparisons are not a substitute (docs/adr/0079)"
        )
    if not results.of(MATED):
        raise CalibrationInputError(
            "the labelled results contain no mated comparisons, so the genuine "
            "performance at the selected boundary could not be reported. A "
            "boundary chosen without it is a number with nothing beside it"
        )


def validate_calibration_inputs(
    *,
    protocol: CalibrationProtocol,
    source_binding: CalibrationSourceBinding,
    labeled_results: Any,
    protected_registry: ProtectedEvaluationRegistry | None,
) -> None:
    """Every precondition, in the order the refusals have to happen in.

    The first two take only the binding and the registry. Nothing here reaches
    into ``labeled_results`` until both have passed, which is what makes "refused
    before a single score was read" a fact about the code rather than a claim
    about it.
    """
    require_development_role(source_binding)
    require_unprotected_source(source_binding, protected_registry)

    if not isinstance(protocol, CalibrationProtocol):
        raise CalibrationInputError("a calibration needs a frozen protocol")
    require_binding_describes_results(source_binding, labeled_results)
    require_populations_for(protocol, labeled_results)
