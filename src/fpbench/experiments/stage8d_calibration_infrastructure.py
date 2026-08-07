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
    "RegistryCoverage",
    "SyntheticCaseResult",
    "SyntheticQualification",
    "SYNTHETIC_COMMIT",
    "SYNTHETIC_UTC",
    "run_synthetic_qualification",
    "synthetic_qualification_fingerprint",
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


# ----------------------------------------------------- the synthetic fixtures
#
# Every claim Stage 8D makes about the calibration engine, exercised on data this
# module invents. There is no dataset here, no runtime, no checkpoint, no prior
# result set and no workspace: the whole qualification is pure Python over
# numbers that were never measured (docs/adr/0078, spec section 31).
#
# Each fixture is small enough that its expected answer is worked out in the
# case's own claim, which is what makes the catalogue evidence rather than a
# record of whatever the code happened to do.

#: A stand-in commit and clock for artifacts that are never published. Fixed
#: rather than read from Git, so the qualification reproduces from source alone
#: and its fingerprint does not move every time the repository does.
SYNTHETIC_COMMIT = "0" * 40
SYNTHETIC_UTC = "1970-01-01T00:00:00Z"

_SYNTHETIC_ALGORITHM = "synthetic_matcher"


@dataclass(frozen=True, slots=True)
class SyntheticCaseResult:
    """What one fixture proved, in a form the evidence can publish.

    Deliberately carries no threshold and no score. The operating-point
    fingerprint covers both, so a verifier that re-runs the fixture compares
    identities exactly, and the published evidence never holds a number a reader
    could mistake for a measurement (spec section 36).
    """

    case_id: str
    claim: str
    kind: str
    outcome: str
    counts: Mapping[str, int]

    def __post_init__(self) -> None:
        if self.kind not in ("selection", "refusal", "identity"):
            raise Stage8DFinalizationError(
                f"{self.case_id}: a synthetic case selects, refuses, or establishes "
                f"an identity, not {self.kind!r}"
            )
        object.__setattr__(
            self,
            "counts",
            {str(key): int(value) for key, value in sorted(dict(self.counts).items())},
        )


@dataclass(frozen=True, slots=True)
class SyntheticQualification:
    """The whole catalogue, and one identity over it."""

    cases: tuple[SyntheticCaseResult, ...]
    selection_cases: int
    refusal_cases: int
    identity_cases: int
    qualification_fingerprint: str

    def case(self, case_id: str) -> SyntheticCaseResult:
        for result in self.cases:
            if result.case_id == case_id:
                return result
        raise KeyError(case_id)


def synthetic_qualification_fingerprint(
    cases: tuple[SyntheticCaseResult, ...],
) -> str:
    from fpbench.core.serialization import stable_hash, to_plain

    return stable_hash(
        {
            "schema": "stage_8d_synthetic_qualification_v1",
            "cases": [to_plain(case) for case in cases],
        },
        length=64,
    )


def _binding(registry: ProtectedEvaluationRegistry, **overrides):
    """A development binding that resolves to nothing the registry protects."""
    from fpbench.calibration.protocol import build_calibration_source_binding
    from fpbench.core.enums import CohortRole, ScoreDirection

    fields: dict[str, Any] = dict(
        binding_id="synthetic_development_v1",
        algorithm_id=_SYNTHETIC_ALGORITHM,
        algorithm_fingerprint="a" * 64,
        integration_id="synthetic_integration",
        integration_fingerprint="b" * 64,
        run_id="run_synthetic0001",
        run_fingerprint="c" * 64,
        result_set_id="resultset_synthetic0001",
        result_set_fingerprint="d" * 64,
        dataset_id="synthetic_development_dataset",
        dataset_fingerprint="e" * 64,
        cohort_id="synthetic_development_cohort",
        cohort_fingerprint="f" * 64,
        cohort_role=CohortRole.DEVELOPMENT,
        pair_manifest_id="synthetic_pair_manifest",
        pair_manifest_fingerprint="1" * 64,
        score_direction=ScoreDirection.HIGHER_IS_BETTER,
    )
    #: Set by the fixtures that deliberately point at protected material, so the
    #: collision check below does not refuse the very cases that exist to be
    #: refused further down.
    deliberately_protected = bool(overrides.pop("deliberately_protected", False))
    fields.update(overrides)
    binding = build_calibration_source_binding(**fields)
    # A fixture that collided with protected material by accident would make the
    # whole qualification meaningless, so the fixtures are checked rather than
    # assumed to be clean.
    if not deliberately_protected and registry.matches(
        fingerprints=binding.identity_fingerprints, identities=binding.identity_ids
    ):
        raise Stage8DFinalizationError(
            "a synthetic fixture collides with protected evaluation material"
        )
    return binding


def _results(direction, *, mated, impostor, mated_failures=0, impostor_failures=0):
    from decimal import Decimal

    from fpbench.calibration.models import LabeledResults, LabeledScore
    from fpbench.core.enums import CalibrationPairTruth, ExecutionStatus

    rows = []
    for index, score in enumerate(mated):
        rows.append(
            LabeledScore(
                pair_id=f"m{index:04d}",
                truth=CalibrationPairTruth.MATED,
                execution_status=ExecutionStatus.SUCCESS,
                score=Decimal(score),
            )
        )
    for index, score in enumerate(impostor):
        rows.append(
            LabeledScore(
                pair_id=f"i{index:04d}",
                truth=CalibrationPairTruth.CROSS_SUBJECT_IMPOSTOR,
                execution_status=ExecutionStatus.SUCCESS,
                score=Decimal(score),
            )
        )
    for index in range(mated_failures):
        rows.append(
            LabeledScore(
                pair_id=f"mf{index:04d}",
                truth=CalibrationPairTruth.MATED,
                execution_status=ExecutionStatus.FAILURE,
                failure_code="template_extraction_failed",
            )
        )
    for index in range(impostor_failures):
        rows.append(
            LabeledScore(
                pair_id=f"if{index:04d}",
                truth=CalibrationPairTruth.CROSS_SUBJECT_IMPOSTOR,
                execution_status=ExecutionStatus.FAILURE,
                failure_code="template_extraction_failed",
            )
        )
    return LabeledResults(score_direction=direction, rows=tuple(rows))


def _protocol(numerator: int, denominator: int):
    from fpbench.calibration.protocol import impostor_ceiling_protocol

    return impostor_ceiling_protocol(
        protocol_id=f"synthetic_ceiling_{numerator}_in_{denominator}_v1",
        numerator=numerator,
        denominator=denominator,
    )


def _select(protocol, binding, results, registry):
    from fpbench.calibration.selection import select_operating_point

    return select_operating_point(
        protocol,
        binding,
        results,
        protected_registry=registry,
        created_source_commit=SYNTHETIC_COMMIT,
        created_source_tree_clean=True,
        created_utc=SYNTHETIC_UTC,
    )


def _selection_case(case_id, claim, protocol, binding, results, registry):
    point = _select(protocol, binding, results, registry)
    return point, SyntheticCaseResult(
        case_id=case_id,
        claim=claim,
        kind="selection",
        outcome=point.operating_point_fingerprint,
        counts={
            "impostor_matches": point.observed_impostor_matches,
            "impostor_scored": point.observed_impostor_scored,
            "impostor_attempts": point.observed_impostor_attempts,
            "impostor_failures": point.impostor_failures,
            "mated_matches": point.observed_mated_matches,
            "mated_non_matches": point.observed_mated_non_matches,
            "mated_scored": point.observed_mated_scored,
            "mated_attempts": point.observed_mated_attempts,
            "mated_failures": point.mated_failures,
            "comparator_is_strict": int(point.comparator.is_strict),
        },
    )


def _refusal_case(case_id, claim, expected, call):
    """Run something that must fail, and record *which* refusal it produced.

    The expected class is checked rather than "some exception". A leakage refusal
    that happened to arrive as a parse error would be a refusal nobody could rely
    on, and a catalogue that recorded it as a pass would be worse than no
    catalogue (docs/adr/0079).
    """
    try:
        call()
    except expected as exc:
        return SyntheticCaseResult(
            case_id=case_id,
            claim=claim,
            kind="refusal",
            outcome=type(exc).__name__,
            counts={},
        )
    except Exception as exc:  # noqa: BLE001 - naming the wrong refusal is the point
        raise Stage8DFinalizationError(
            f"{case_id}: expected {expected.__name__}, got "
            f"{type(exc).__name__}: {exc}"
        ) from None
    raise Stage8DFinalizationError(
        f"{case_id}: expected {expected.__name__} and nothing was raised"
    )


def run_synthetic_qualification(
    registry: ProtectedEvaluationRegistry | None = None,
) -> SyntheticQualification:
    """Run every fixture, in a fixed order, and return one identity over them.

    Nothing here touches the filesystem, the network, a dataset, a runtime or a
    stored result. The only inputs are the numbers written into this function and
    the protected registry, and the only outputs are fingerprints and counts.

    Raises:
        Stage8DFinalizationError: a fixture produced the wrong answer, raised the
            wrong refusal, or did not raise at all. The qualification does not
            report a failure — it fails, because a Stage 8D that published a
            partially-passing catalogue would be publishing an engine nobody had
            qualified.
    """
    from decimal import Decimal

    from fpbench.calibration.models import (
        LabeledResults,
        LabeledScore,
        read_calibration_operating_point,
        strict_json_document,
    )
    from fpbench.calibration.profiles import derive_calibrated_decision_profile
    from fpbench.calibration.selection import select_operating_point
    from fpbench.calibration.validation import validate_calibration_inputs
    from fpbench.calibration.verify import verify_operating_point
    from fpbench.core.calibration_errors import (
        CalibrationInputError,
        CalibrationLeakageError,
        CalibrationSelectionError,
        CalibrationSourceError,
        CalibrationVerificationError,
    )
    from fpbench.core.enums import (
        CalibrationPairTruth,
        CohortRole,
        ExecutionStatus,
        ScoreDirection,
        ThresholdComparator,
        ThresholdOrigin,
    )
    from fpbench.core.serialization import to_plain

    registry = registry if registry is not None else build_registry()
    higher = ScoreDirection.HIGHER_IS_BETTER
    lower = ScoreDirection.LOWER_IS_BETTER
    cases: list[SyntheticCaseResult] = []

    def expect(condition: bool, case_id: str, detail: str) -> None:
        if not condition:
            raise Stage8DFinalizationError(f"{case_id}: {detail}")

    # ---------------------------------------------------------- selection

    # Impostors 1..4, mated 5..8, ceiling 1/4. ">= 4" admits exactly the one
    # impostor at 4 and 1/4 does not exceed 1/4; ">= 3" would admit two. So the
    # target is met exactly rather than undershot.
    point, case = _selection_case(
        "higher_is_better_exact_target",
        "a higher-is-better matcher reaches a 1/4 ceiling exactly, at >= 4",
        _protocol(1, 4),
        _binding(registry),
        _results(higher, mated=["5", "6", "7", "8"], impostor=["1", "2", "3", "4"]),
        registry,
    )
    expect(point.threshold == "4", case.case_id, "expected a boundary at 4")
    expect(
        point.comparator is ThresholdComparator.GREATER_THAN_OR_EQUAL,
        case.case_id,
        "expected an inclusive comparator",
    )
    expect(point.observed_impostor_matches == 1, case.case_id, "expected one impostor")
    cases.append(case)

    # Distances: mated 1..4 are close, impostors 5..8 far, ceiling 1/4. "<= 5"
    # admits one impostor, "<= 6" admits two. The answer runs the other way and
    # is spelled with <=, because a smaller distance is a better match.
    point, case = _selection_case(
        "lower_is_better_runs_the_other_way",
        "a lower-is-better matcher selects <= 5 under the same 1/4 ceiling",
        _protocol(1, 4),
        _binding(registry, score_direction=lower),
        _results(lower, mated=["1", "2", "3", "4"], impostor=["5", "6", "7", "8"]),
        registry,
    )
    expect(point.threshold == "5", case.case_id, "expected a boundary at 5")
    expect(
        point.comparator is ThresholdComparator.LESS_THAN_OR_EQUAL,
        case.case_id,
        "expected an inclusive lower-is-better comparator",
    )
    cases.append(case)

    # Impostors 0.4, 0.4, 0.4, 0.7, 0.7; mated 0.9, 0.9; ceiling 1/5. One
    # impostor match in five would satisfy it and no boundary produces one:
    # ">= 0.7" admits both 0.7s. Accepting one of them is not something a
    # threshold can express, so the selection undershoots to zero.
    #
    # The answer is "> 0.7", the strictest boundary the impostor scores express.
    # Not ">= 0.9": 0.9 is a mated-only value, and a threshold standing there
    # would have been placed by the genuine population (docs/adr/0080).
    point, case = _selection_case(
        "target_undershot_because_ties_are_atomic",
        "a 1/5 ceiling is undershot to zero rather than splitting two equal 0.7s",
        _protocol(1, 5),
        _binding(registry),
        _results(
            higher, mated=["0.9", "0.9"], impostor=["0.4", "0.4", "0.4", "0.7", "0.7"]
        ),
        registry,
    )
    expect(point.threshold == "0.7", case.case_id, "expected a boundary at 0.7")
    expect(
        point.comparator is ThresholdComparator.GREATER_THAN,
        case.case_id,
        "expected a strict comparator",
    )
    expect(
        point.observed_impostor_matches == 0,
        case.case_id,
        "expected no impostor to be admitted",
    )
    expect(
        point.observed_impostor_scored == 5,
        case.case_id,
        "expected all five impostors to be counted",
    )
    expect(
        point.observed_mated_matches == 2,
        case.case_id,
        "expected both mated comparisons to clear the boundary",
    )
    cases.append(case)

    # The same fixture, recorded separately: admitting no impostor at all is an
    # ordinary answer rather than a failure to find one.
    cases.append(
        SyntheticCaseResult(
            case_id="zero_impostor_match_operating_point",
            claim="an operating point that admits no impostor is a normal outcome",
            kind="selection",
            outcome=point.operating_point_fingerprint,
            counts={"impostor_matches": 0, "impostor_scored": 5},
        )
    )

    # Four impostors and four mated, all scoring 1, ceiling 1/4. ">= 1" admits
    # all four impostors; "> 1" admits none; there is nothing in between because
    # there is one distinct score. "Accept nothing" is spelled as a strict
    # boundary at the only score that exists, not as an invented number above it.
    point, case = _selection_case(
        "all_scores_equal_selects_a_strict_boundary",
        "with one distinct score the answer is > 1, without inventing a number",
        _protocol(1, 4),
        _binding(registry),
        _results(higher, mated=["1", "1", "1", "1"], impostor=["1", "1", "1", "1"]),
        registry,
    )
    expect(point.threshold == "1", case.case_id, "expected a boundary at 1")
    expect(
        point.comparator is ThresholdComparator.GREATER_THAN,
        case.case_id,
        "expected a strict comparator",
    )
    expect(
        point.observed_mated_non_matches == 4,
        case.case_id,
        "expected every mated comparison to be a non-match",
    )
    cases.append(case)

    # Three impostors at 0.4 count as three and share one decision. ">= 0.9"
    # admits the single impostor at 0.9, which is 1/4 and inside a 1/2 ceiling.
    point, case = _selection_case(
        "duplicate_scores_are_counted_and_never_separated",
        "three impostors at 0.4 count three times and receive one decision",
        _protocol(1, 2),
        _binding(registry),
        _results(higher, mated=["0.9"], impostor=["0.4", "0.4", "0.4", "0.9"]),
        registry,
    )
    expect(
        point.observed_impostor_scored == 4,
        case.case_id,
        "expected four impostor comparisons",
    )
    cases.append(case)

    # The regression case. Both sides share impostors 1, 2, 3, 4 under a ceiling
    # of one in four; the mated populations are wildly different, and the second
    # one sits *between* impostor values on purpose. When candidates were drawn
    # from every observed score, ">= 3.5" was a legal boundary — it admitted the
    # same single impostor as ">= 4" while accepting one more mated comparison,
    # so it looked more permissive and won. 3.5 is a number no impostor
    # comparison ever produced (docs/adr/0080).
    above, above_case = _selection_case(
        "mated_scores_above_every_impostor",
        "with mated 5, 6, 7 the 1/4 ceiling selects >= 4",
        _protocol(1, 4),
        _binding(registry),
        _results(higher, mated=["5", "6", "7"], impostor=["1", "2", "3", "4"]),
        registry,
    )
    interleaved, interleaved_case = _selection_case(
        "mated_scores_interleaved_with_impostors",
        "with mated 2.5, 3.5, 100 the same ceiling still selects >= 4",
        _protocol(1, 4),
        _binding(registry),
        _results(higher, mated=["2.5", "3.5", "100"], impostor=["1", "2", "3", "4"]),
        registry,
    )
    for candidate_case, point_under_test in (
        (above_case, above),
        (interleaved_case, interleaved),
    ):
        expect(
            point_under_test.threshold == "4",
            candidate_case.case_id,
            f"expected a boundary at 4, got {point_under_test.threshold}",
        )
        expect(
            point_under_test.comparator is ThresholdComparator.GREATER_THAN_OR_EQUAL,
            candidate_case.case_id,
            "expected an inclusive comparator",
        )
    expect(
        above.threshold == interleaved.threshold
        and above.comparator is interleaved.comparator
        and above.observed_impostor_matches == interleaved.observed_impostor_matches
        and above.observed_impostor_scored == interleaved.observed_impostor_scored,
        "mated_scores_interleaved_with_impostors",
        "the genuine population moved the boundary or the impostor counts",
    )
    expect(
        above.observed_mated_matches == 3 and interleaved.observed_mated_matches == 1,
        "mated_scores_interleaved_with_impostors",
        "the genuine performance was not measured at the chosen boundary",
    )
    cases.append(above_case)
    cases.append(interleaved_case)

    # Four impostor attempts, one of which failed; three mated, one failed. The
    # ceiling applies to what produced a score, and the failures stay visible
    # rather than becoming non-matches (docs/adr/0006).
    point, case = _selection_case(
        "failures_are_excluded_from_the_rate_and_reported_beside_it",
        "a comparison with no score is in no numerator, no denominator, and is counted",
        _protocol(1, 3),
        _binding(registry),
        _results(
            higher,
            mated=["8", "9"],
            impostor=["1", "2", "3"],
            mated_failures=1,
            impostor_failures=1,
        ),
        registry,
    )
    expect(
        point.observed_impostor_scored == 3
        and point.observed_impostor_attempts == 4
        and point.impostor_failures == 1,
        case.case_id,
        "expected three scored impostors out of four attempts",
    )
    expect(
        point.observed_mated_matches + point.observed_mated_non_matches == 2,
        case.case_id,
        "expected the mated failure to be outside the decided population",
    )
    cases.append(case)

    # ------------------------------------------------------------ identity

    # The reference selection for the determinism cases below.
    reference_protocol = _protocol(1, 4)
    reference_binding = _binding(registry)
    reference_results = _results(
        higher,
        mated=["5", "6", "7", "8"],
        impostor=["1", "2", "3", "4"],
        mated_failures=1,
        impostor_failures=2,
    )
    reference = _select(
        reference_protocol, reference_binding, reference_results, registry
    )

    # Twenty-five deterministic permutations. Not random: a shuffled fixture that
    # only sometimes reordered anything would be a test that only sometimes ran.
    ordered = list(reference_results.rows)
    for rotation in range(1, 26):
        rotated = ordered[rotation % len(ordered) :] + ordered[: rotation % len(ordered)]
        shuffled = LabeledResults(
            score_direction=reference_results.score_direction, rows=tuple(rotated)
        )
        again = _select(reference_protocol, reference_binding, shuffled, registry)
        expect(
            again.operating_point_fingerprint == reference.operating_point_fingerprint,
            "row_order_does_not_change_the_identity",
            f"rotation {rotation} produced a different operating point",
        )
    cases.append(
        SyntheticCaseResult(
            case_id="row_order_does_not_change_the_identity",
            claim="25 rotations of the same rows produce one identical operating point",
            kind="identity",
            outcome=reference.operating_point_fingerprint,
            counts={"permutations": 25},
        )
    )

    restored = read_calibration_operating_point(
        strict_json_document(json.dumps(to_plain(reference)))
    )
    expect(
        restored == reference,
        "json_round_trip_preserves_the_identity",
        "a JSON round trip changed the operating point",
    )
    cases.append(
        SyntheticCaseResult(
            case_id="json_round_trip_preserves_the_identity",
            claim="serialising and strictly re-reading an operating point changes nothing",
            kind="identity",
            outcome=restored.operating_point_fingerprint,
            counts={},
        )
    )

    report = verify_operating_point(
        reference,
        reference_protocol,
        reference_binding,
        reference_results,
        protected_registry=registry,
    )
    expect(
        report.verified,
        "verification_re_derives_the_stored_answer",
        f"re-derivation disagreed: {report.findings}",
    )
    cases.append(
        SyntheticCaseResult(
            case_id="verification_re_derives_the_stored_answer",
            claim="verification recomputes the selection rather than reading it back",
            kind="identity",
            outcome=report.recomputed_fingerprint,
            counts={"candidates": report.candidate_count},
        )
    )

    profile = derive_calibrated_decision_profile(
        reference,
        implementation_version="synthetic-1.0",
        allowed_execution_profiles=("synthetic_execution_profile",),
    )
    expect(
        profile.origin is ThresholdOrigin.CALIBRATED_DEVELOPMENT
        and profile.schema_version == "3"
        and profile.calibration_operating_point_fingerprint
        == reference.operating_point_fingerprint
        and profile.calibration_protocol_fingerprint
        == reference_protocol.protocol_fingerprint
        and profile.calibration_source_binding_fingerprint
        == reference_binding.source_binding_fingerprint,
        "operating_point_becomes_a_calibrated_decision_profile",
        "the bridge did not carry all three links",
    )
    cases.append(
        SyntheticCaseResult(
            case_id="operating_point_becomes_a_calibrated_decision_profile",
            claim="an operating point becomes a schema-3 CALIBRATED_DEVELOPMENT profile",
            kind="identity",
            outcome=profile.profile_fingerprint,
            counts={"links": 3},
        )
    )

    # ------------------------------------------------------------ refusals

    cases.append(
        _refusal_case(
            "evaluation_role_is_refused",
            "a binding declared on the evaluation cohort is refused",
            CalibrationLeakageError,
            lambda: select_operating_point(
                _protocol(1, 4),
                _binding(registry, cohort_role=CohortRole.EVALUATION),
                reference_results,
                protected_registry=registry,
                created_source_commit=SYNTHETIC_COMMIT,
                created_source_tree_clean=True,
                created_utc=SYNTHETIC_UTC,
            ),
        )
    )

    protected_result_set = next(
        fingerprint
        for kind, _identity, fingerprint, _label in frozen.PROTECTED_IDENTITIES
        if kind is ProtectedIdentityKind.RESULT_SET
    )
    cases.append(
        _refusal_case(
            "protected_result_set_is_refused",
            "a binding resolving to a registered evaluation result set is refused",
            CalibrationLeakageError,
            lambda: select_operating_point(
                _protocol(1, 4),
                _binding(
                    registry,
                    deliberately_protected=True,
                    result_set_fingerprint=protected_result_set,
                ),
                reference_results,
                protected_registry=registry,
                created_source_commit=SYNTHETIC_COMMIT,
                created_source_tree_clean=True,
                created_utc=SYNTHETIC_UTC,
            ),
        )
    )

    protected_cohort = next(
        fingerprint
        for kind, _identity, fingerprint, _label in frozen.PROTECTED_IDENTITIES
        if kind is ProtectedIdentityKind.COHORT
    )
    cases.append(
        _refusal_case(
            "development_claim_over_protected_cohort_is_refused",
            "claiming development over a registered evaluation cohort is refused",
            CalibrationLeakageError,
            lambda: select_operating_point(
                _protocol(1, 4),
                _binding(
                    registry,
                    deliberately_protected=True,
                    cohort_role=CohortRole.DEVELOPMENT,
                    cohort_fingerprint=protected_cohort,
                ),
                reference_results,
                protected_registry=registry,
                created_source_commit=SYNTHETIC_COMMIT,
                created_source_tree_clean=True,
                created_utc=SYNTHETIC_UTC,
            ),
        )
    )

    cases.append(
        _refusal_case(
            "running_without_the_registry_is_refused",
            "a selection with no protected registry loaded is refused",
            CalibrationLeakageError,
            lambda: validate_calibration_inputs(
                protocol=_protocol(1, 4),
                source_binding=_binding(registry),
                labeled_results=reference_results,
                protected_registry=None,
            ),
        )
    )

    cases.append(
        _refusal_case(
            "mixed_score_directions_are_refused",
            "a binding and its results must agree about which way the scale runs",
            CalibrationSourceError,
            lambda: select_operating_point(
                _protocol(1, 4),
                _binding(registry, score_direction=lower),
                reference_results,
                protected_registry=registry,
                created_source_commit=SYNTHETIC_COMMIT,
                created_source_tree_clean=True,
                created_utc=SYNTHETIC_UTC,
            ),
        )
    )

    cases.append(
        _refusal_case(
            "missing_impostor_population_is_refused",
            "a protocol over cross-subject impostors refuses a set without any",
            CalibrationInputError,
            lambda: _select(
                _protocol(1, 4),
                _binding(registry),
                _results(higher, mated=["1", "2"], impostor=[]),
                registry,
            ),
        )
    )

    cases.append(
        _refusal_case(
            "missing_genuine_population_is_refused",
            "a set with no mated comparisons cannot report genuine performance",
            CalibrationInputError,
            lambda: _select(
                _protocol(1, 4),
                _binding(registry),
                _results(higher, mated=[], impostor=["1", "2"]),
                registry,
            ),
        )
    )

    cases.append(
        _refusal_case(
            "wholly_failed_impostor_population_has_no_rate",
            "an impostor population that produced no score is not a low rate",
            CalibrationSelectionError,
            lambda: _select(
                _protocol(1, 4),
                _binding(registry),
                _results(higher, mated=["8"], impostor=[], impostor_failures=3),
                registry,
            ),
        )
    )

    cases.append(
        _refusal_case(
            "duplicate_pair_ids_are_refused",
            "one comparison appearing twice would be counted twice",
            CalibrationInputError,
            lambda: LabeledResults(
                score_direction=higher,
                rows=(
                    LabeledScore(
                        pair_id="p1",
                        truth=CalibrationPairTruth.MATED,
                        execution_status=ExecutionStatus.SUCCESS,
                        score=Decimal("1"),
                    ),
                    LabeledScore(
                        pair_id="p1",
                        truth=CalibrationPairTruth.CROSS_SUBJECT_IMPOSTOR,
                        execution_status=ExecutionStatus.SUCCESS,
                        score=Decimal("2"),
                    ),
                ),
            ),
        )
    )

    cases.append(
        _refusal_case(
            "non_finite_score_is_refused",
            "NaN and the infinities divide nothing into matches and non-matches",
            CalibrationInputError,
            lambda: LabeledScore(
                pair_id="p1",
                truth=CalibrationPairTruth.MATED,
                execution_status=ExecutionStatus.SUCCESS,
                score=Decimal("NaN"),
            ),
        )
    )

    cases.append(
        _refusal_case(
            "malformed_decimal_is_refused",
            "a score that is not a decimal number is refused rather than coerced",
            CalibrationInputError,
            lambda: LabeledScore(
                pair_id="p1",
                truth=CalibrationPairTruth.MATED,
                execution_status=ExecutionStatus.SUCCESS,
                score="0.4.4",
            ),
        )
    )

    cases.append(
        _refusal_case(
            "binary_float_score_is_refused",
            "a score that arrived as a double has already lost what was measured",
            CalibrationInputError,
            lambda: LabeledScore(
                pair_id="p1",
                truth=CalibrationPairTruth.MATED,
                execution_status=ExecutionStatus.SUCCESS,
                score=0.1,
            ),
        )
    )

    cases.append(
        _refusal_case(
            "wrong_result_set_binding_is_refused",
            "verifying against a binding that names another result set is refused",
            CalibrationVerificationError,
            lambda: verify_operating_point(
                reference,
                reference_protocol,
                _binding(registry, result_set_fingerprint="7" * 64),
                reference_results,
                protected_registry=registry,
            ),
        )
    )

    cases.append(
        _refusal_case(
            "wrong_pair_manifest_binding_is_refused",
            "verifying against a binding that names another pair manifest is refused",
            CalibrationVerificationError,
            lambda: verify_operating_point(
                reference,
                reference_protocol,
                _binding(registry, pair_manifest_fingerprint="8" * 64),
                reference_results,
                protected_registry=registry,
            ),
        )
    )

    cases.append(
        _refusal_case(
            "wrong_protocol_is_refused",
            "verifying against a protocol the point was not selected under is refused",
            CalibrationVerificationError,
            lambda: verify_operating_point(
                reference,
                _protocol(1, 10),
                reference_binding,
                reference_results,
                protected_registry=registry,
            ),
        )
    )

    results = tuple(cases)
    identifiers = [case.case_id for case in results]
    if len(set(identifiers)) != len(identifiers):
        raise Stage8DFinalizationError(
            "two synthetic cases share an id, so one of them is not being reported"
        )
    return SyntheticQualification(
        cases=results,
        selection_cases=sum(1 for case in results if case.kind == "selection"),
        refusal_cases=sum(1 for case in results if case.kind == "refusal"),
        identity_cases=sum(1 for case in results if case.kind == "identity"),
        qualification_fingerprint=synthetic_qualification_fingerprint(results),
    )
