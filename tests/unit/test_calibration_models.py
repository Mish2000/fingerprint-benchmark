"""The calibration containers, their arithmetic, and their strict reader.

Three groups. The rates, which are integers and must stay integers under inputs
that would defeat a float. The artifacts, whose fingerprints have to cover
everything that could change a decision and nothing that could not. And the
reader, which has no lenient path — every test in the last group is a document
that *nearly* parses.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from fpbench.calibration.models import (
    CandidateBoundary,
    LabeledResults,
    LabeledScore,
    read_calibration_operating_point,
    read_calibration_protocol,
    read_calibration_source_binding,
    read_protected_evaluation_registry,
    require_finite_decimal,
    strict_json_document,
)
from fpbench.calibration.protocol import (
    build_calibration_operating_point,
    build_calibration_source_binding,
    build_protected_evaluation_registry,
    impostor_ceiling_protocol,
)
from fpbench.core.calibration_errors import (
    CalibrationInputError,
    CalibrationProtocolError,
    CalibrationSourceError,
)
from fpbench.core.calibration_models import (
    ExactRate,
    ProtectedEvaluationIdentity,
    calibration_operating_point_fingerprint,
    operating_point_id,
    rate_at_most,
)
from fpbench.core.enums import (
    CalibrationPairTruth,
    CohortRole,
    ExecutionStatus,
    ProtectedIdentityKind,
    ScoreDirection,
    ScoreNormalizationPolicy,
    ThresholdComparator,
)
from fpbench.core.serialization import to_plain

pytestmark = pytest.mark.stage8d_contract

MATED = CalibrationPairTruth.MATED
IMPOSTOR = CalibrationPairTruth.CROSS_SUBJECT_IMPOSTOR
HIGHER = ScoreDirection.HIGHER_IS_BETTER
LOWER = ScoreDirection.LOWER_IS_BETTER
GE = ThresholdComparator.GREATER_THAN_OR_EQUAL
GT = ThresholdComparator.GREATER_THAN
LE = ThresholdComparator.LESS_THAN_OR_EQUAL
LT = ThresholdComparator.LESS_THAN


def scored(pair_id: str, truth: CalibrationPairTruth, score: str) -> LabeledScore:
    return LabeledScore(
        pair_id=pair_id,
        truth=truth,
        execution_status=ExecutionStatus.SUCCESS,
        score=Decimal(score),
    )


def failed(pair_id: str, truth: CalibrationPairTruth) -> LabeledScore:
    return LabeledScore(
        pair_id=pair_id,
        truth=truth,
        execution_status=ExecutionStatus.FAILURE,
        failure_code="template_extraction_failed",
    )


def a_protocol(numerator: int = 1, denominator: int = 1000):
    return impostor_ceiling_protocol(
        protocol_id="synthetic_ceiling_v1",
        numerator=numerator,
        denominator=denominator,
    )


def a_binding(role: CohortRole = CohortRole.DEVELOPMENT, direction=HIGHER):
    return build_calibration_source_binding(
        binding_id="synthetic_binding_v1",
        algorithm_id="synthetic_matcher",
        algorithm_fingerprint="a" * 64,
        integration_id="synthetic_integration",
        integration_fingerprint="b" * 64,
        run_id="run_synthetic01",
        run_fingerprint="c" * 64,
        result_set_id="resultset_syn01",
        result_set_fingerprint="d" * 64,
        dataset_id="synthetic_dataset",
        dataset_fingerprint="e" * 64,
        cohort_id="synthetic_dev_cohort",
        cohort_fingerprint="f" * 64,
        cohort_role=role,
        pair_manifest_id="synthetic_pairs",
        pair_manifest_fingerprint="1" * 64,
        score_direction=direction,
    )


def an_operating_point(**overrides):
    fields = dict(
        calibration_protocol_fingerprint_value=a_protocol().protocol_fingerprint,
        source_binding_fingerprint=a_binding().source_binding_fingerprint,
        algorithm_id="synthetic_matcher",
        algorithm_fingerprint="a" * 64,
        threshold=Decimal("0.5"),
        comparator=GE,
        score_direction=HIGHER,
        target_rate_numerator=1,
        target_rate_denominator=1000,
        observed_impostor_matches=0,
        observed_impostor_scored=1000,
        observed_impostor_attempts=1000,
        impostor_failures=0,
        observed_mated_matches=900,
        observed_mated_non_matches=100,
        observed_mated_scored=1000,
        observed_mated_attempts=1000,
        mated_failures=0,
        selection_rule=a_protocol().threshold_selection_rule,
        tie_policy=a_protocol().tie_policy,
        created_source_commit="0" * 40,
        created_source_tree_clean=True,
        created_utc="2026-08-07T12:00:00Z",
    )
    fields.update(overrides)
    return build_calibration_operating_point(**fields)


# ------------------------------------------------------------- exact rates


def test_a_rate_is_reduced_so_one_rate_has_one_identity() -> None:
    assert ExactRate(numerator=2, denominator=2000) == ExactRate(
        numerator=1, denominator=1000
    )
    assert str(ExactRate(numerator=250, denominator=1000)) == "1/4"


def test_a_rate_refuses_a_float_and_a_bool() -> None:
    for bad in (0.001, True, "1"):
        with pytest.raises(ValueError):
            ExactRate(numerator=bad, denominator=1000)


def test_a_rate_needs_a_positive_denominator() -> None:
    with pytest.raises(ValueError):
        ExactRate(numerator=1, denominator=0)
    with pytest.raises(ValueError):
        ExactRate(numerator=-1, denominator=1000)


@pytest.mark.parametrize(
    "numerator, denominator", [(0, 1), (0, 1000), (1, 1000), (1, 4), (1, 1)]
)
def test_a_rate_inside_zero_and_one_is_accepted(numerator, denominator) -> None:
    """Both ends are meaningful: admit no impostor, admit every impostor."""
    rate = ExactRate(numerator=numerator, denominator=denominator)
    assert rate.numerator <= rate.denominator


@pytest.mark.parametrize(
    "numerator, denominator", [(2, 1), (1001, 1000), (5, 4), (3, 2)]
)
def test_a_rate_above_one_is_refused(numerator, denominator) -> None:
    """It is not a lax target; it is a target that constrains nothing."""
    with pytest.raises(ValueError, match="must not exceed 1"):
        ExactRate(numerator=numerator, denominator=denominator)


def test_a_protocol_cannot_be_built_with_a_target_above_one() -> None:
    """Refused through the public builder, not only by direct construction."""
    from fpbench.calibration.protocol import impostor_ceiling_protocol

    with pytest.raises(ValueError, match="must not exceed 1"):
        impostor_ceiling_protocol(
            protocol_id="impossible_v1", numerator=2, denominator=1
        )
    with pytest.raises(ValueError, match="must not exceed 1"):
        impostor_ceiling_protocol(
            protocol_id="impossible_v1", numerator=1001, denominator=1000
        )


def test_a_protocol_may_target_zero_or_one() -> None:
    from fpbench.calibration.protocol import impostor_ceiling_protocol

    strictest = impostor_ceiling_protocol(
        protocol_id="admit_nothing_v1", numerator=0, denominator=1
    )
    laxest = impostor_ceiling_protocol(
        protocol_id="admit_everything_v1", numerator=1, denominator=1
    )
    assert strictest.permits(0, 100) is True
    assert strictest.permits(1, 100) is False
    assert laxest.permits(100, 100) is True


def test_an_operating_point_cannot_carry_a_target_above_one() -> None:
    with pytest.raises(ValueError, match="must not exceed 1"):
        an_operating_point(target_rate_numerator=2, target_rate_denominator=1)


def test_rate_comparison_is_exact_where_a_float_would_not_be() -> None:
    """The case the whole rational representation exists for.

    ``1/3`` of ten thousand impostor comparisons is 3,333.33...; a boundary that
    admits 3,334 exceeds the target and one that admits 3,333 does not. In binary
    floating point the two comparisons can come out the same.
    """
    assert rate_at_most(3333, 10_000, 1, 3) is True
    assert rate_at_most(3334, 10_000, 1, 3) is False


def test_rate_comparison_holds_at_enormous_denominators() -> None:
    """Python integers are unbounded, so exactness does not run out."""
    huge = 10**30
    assert rate_at_most(1, huge, 1, huge) is True
    assert rate_at_most(2, huge, 1, huge) is False


def test_a_rate_over_nothing_is_refused_rather_than_called_zero() -> None:
    with pytest.raises(ValueError):
        rate_at_most(0, 0, 1, 1000)


def test_the_ceiling_is_inclusive() -> None:
    """Spec section 10: the observed rate may *reach* the target, not pass it."""
    assert a_protocol(1, 1000).permits(1, 1000) is True
    assert a_protocol(1, 1000).permits(2, 1000) is False


# ---------------------------------------------------------------- protocol


def test_a_protocol_fingerprints_to_what_it_carries() -> None:
    protocol = a_protocol()
    assert len(protocol.protocol_fingerprint) == 64
    assert a_protocol().protocol_fingerprint == protocol.protocol_fingerprint
    assert a_protocol(1, 2000).protocol_fingerprint != protocol.protocol_fingerprint


def test_a_protocol_that_permits_the_evaluation_cohort_is_refused() -> None:
    with pytest.raises(CalibrationProtocolError, match="development"):
        impostor_ceiling_protocol(
            protocol_id="leaky_v1", numerator=1, denominator=1000
        ).__class__(
            **{
                **{
                    field: getattr(a_protocol(), field)
                    for field in a_protocol().__slots__
                },
                "requires_development_role": False,
            }
        )


def test_a_protocol_that_would_use_the_sanity_population_is_refused() -> None:
    with pytest.raises(CalibrationProtocolError, match="cross-subject"):
        from fpbench.calibration.protocol import build_calibration_protocol

        build_calibration_protocol(
            protocol_id="sanity_v1",
            protocol_version="1",
            target_rate_numerator=1,
            target_rate_denominator=1000,
            requires_cross_subject_impostors=False,
        )


def test_a_protocol_that_filters_by_quality_is_refused() -> None:
    from fpbench.calibration.protocol import build_calibration_protocol

    with pytest.raises(CalibrationProtocolError, match="quality"):
        build_calibration_protocol(
            protocol_id="filtered_v1",
            protocol_version="1",
            target_rate_numerator=1,
            target_rate_denominator=1000,
            quality_filtering=True,
        )


def test_a_protocol_has_no_knob_the_selector_does_not_implement() -> None:
    from fpbench.calibration.protocol import build_calibration_protocol

    with pytest.raises(CalibrationProtocolError, match="new protocol version"):
        build_calibration_protocol(
            protocol_id="invented_v1",
            protocol_version="1",
            target_rate_numerator=1,
            target_rate_denominator=1000,
            smoothing="loess",
        )


def test_the_only_normalization_a_protocol_can_declare_is_none() -> None:
    assert a_protocol().normalization is ScoreNormalizationPolicy.NONE


# ----------------------------------------------------------- source binding


def test_a_binding_pins_content_addressed_identities_and_no_path() -> None:
    binding = a_binding()
    fields = set(to_plain(binding))
    assert not any(
        token in name
        for name in fields
        for token in ("path", "directory", "filename", "location")
    )
    assert len(binding.identity_fingerprints) == 5


def test_a_binding_refuses_metadata_that_smuggles_a_path_back_in() -> None:
    with pytest.raises(CalibrationSourceError, match="not by where"):
        build_calibration_source_binding(
            binding_id="located_v1",
            algorithm_id="synthetic_matcher",
            algorithm_fingerprint="a" * 64,
            integration_id="synthetic_integration",
            integration_fingerprint="b" * 64,
            run_id="run_synthetic01",
            run_fingerprint="c" * 64,
            result_set_id="resultset_syn01",
            result_set_fingerprint="d" * 64,
            dataset_id="synthetic_dataset",
            dataset_fingerprint="e" * 64,
            cohort_id="synthetic_dev_cohort",
            cohort_fingerprint="f" * 64,
            cohort_role=CohortRole.DEVELOPMENT,
            pair_manifest_id="synthetic_pairs",
            pair_manifest_fingerprint="1" * 64,
            score_direction=HIGHER,
            metadata={"workspace_path": "/data/dev"},
        )


def test_relabelling_a_binding_from_evaluation_to_development_changes_it() -> None:
    """docs/adr/0079: the role is inside the fingerprint."""
    assert (
        a_binding(CohortRole.DEVELOPMENT).source_binding_fingerprint
        != a_binding(CohortRole.EVALUATION).source_binding_fingerprint
    )


# ------------------------------------------------------- protected registry


def test_the_registry_holds_identities_and_has_nowhere_to_put_a_score() -> None:
    registry = build_protected_evaluation_registry(
        registry_id="reg_v1",
        registry_version="1",
        entries=[
            ProtectedEvaluationIdentity(
                kind=ProtectedIdentityKind.RESULT_SET,
                identity="resultset_protected",
                fingerprint="2" * 64,
                label="a protected result set",
            )
        ],
    )
    plain = json.dumps(to_plain(registry))
    for token in ("score", "threshold", "histogram", "count"):
        assert token not in plain


def test_an_empty_registry_is_refused_because_it_looks_like_a_check() -> None:
    with pytest.raises(ValueError, match="protects nothing"):
        build_protected_evaluation_registry(
            registry_id="reg_v1", registry_version="1", entries=[]
        )


def test_registry_order_does_not_change_registry_identity() -> None:
    entries = [
        ProtectedEvaluationIdentity(
            kind=ProtectedIdentityKind.RUN,
            identity="run_aaa",
            fingerprint="3" * 64,
            label="one",
        ),
        ProtectedEvaluationIdentity(
            kind=ProtectedIdentityKind.COHORT,
            identity="cohort_bbb",
            fingerprint="4" * 64,
            label="two",
        ),
    ]
    first = build_protected_evaluation_registry(
        registry_id="reg_v1", registry_version="1", entries=entries
    )
    second = build_protected_evaluation_registry(
        registry_id="reg_v1", registry_version="1", entries=list(reversed(entries))
    )
    assert first.registry_fingerprint == second.registry_fingerprint


# ------------------------------------------------------------ labelled input


def test_a_failure_carries_no_score_and_a_success_carries_no_failure_code() -> None:
    with pytest.raises(CalibrationInputError, match="no score to threshold"):
        LabeledScore(
            pair_id="p1",
            truth=MATED,
            execution_status=ExecutionStatus.FAILURE,
            score=Decimal("1"),
            failure_code="matching_failed",
        )
    with pytest.raises(CalibrationInputError, match="records why"):
        LabeledScore(
            pair_id="p1", truth=MATED, execution_status=ExecutionStatus.FAILURE
        )


def test_a_score_may_not_arrive_as_a_binary_float() -> None:
    with pytest.raises(CalibrationInputError, match="never a float"):
        LabeledScore(
            pair_id="p1",
            truth=MATED,
            execution_status=ExecutionStatus.SUCCESS,
            score=0.1,
        )


def test_a_non_finite_score_is_refused() -> None:
    for bad in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(CalibrationInputError, match="finite"):
            scored("p1", MATED, bad)


def test_a_malformed_decimal_is_refused() -> None:
    """Passed as text, because ``Decimal("0.4.4")`` never gets far enough to try."""
    with pytest.raises(CalibrationInputError, match="not a decimal"):
        LabeledScore(
            pair_id="p1",
            truth=MATED,
            execution_status=ExecutionStatus.SUCCESS,
            score="0.4.4",
        )


def test_a_duplicated_comparison_is_refused() -> None:
    with pytest.raises(CalibrationInputError, match="more than once"):
        LabeledResults(
            score_direction=HIGHER,
            rows=(scored("p1", MATED, "1"), scored("p1", IMPOSTOR, "2")),
        )


def test_two_spellings_of_one_score_are_one_distinct_score() -> None:
    """What makes ties atomic: grouping is by value, not by text."""
    results = LabeledResults(
        score_direction=HIGHER,
        rows=(scored("p1", MATED, "0.40"), scored("p2", MATED, "0.4")),
    )
    assert results.distinct_scores == (Decimal("0.4"),)


def test_row_order_does_not_change_the_content_hash() -> None:
    rows = [
        scored("p1", MATED, "3"),
        scored("p2", IMPOSTOR, "1"),
        failed("p3", MATED),
    ]
    first = LabeledResults(score_direction=HIGHER, rows=tuple(rows))
    second = LabeledResults(score_direction=HIGHER, rows=tuple(reversed(rows)))
    assert first.content_hash() == second.content_hash()


def test_the_score_direction_is_inside_the_content_hash() -> None:
    rows = (scored("p1", MATED, "3"), scored("p2", IMPOSTOR, "1"))
    assert (
        LabeledResults(score_direction=HIGHER, rows=rows).content_hash()
        != LabeledResults(score_direction=LOWER, rows=rows).content_hash()
    )


# --------------------------------------------------------------- boundaries


@pytest.mark.parametrize(
    "comparator, score, expected",
    [
        (GE, "40", True),
        (GT, "40", False),
        (GE, "41", True),
        (GT, "41", True),
        (LE, "40", True),
        (LT, "40", False),
        (LE, "39", True),
        (LT, "39", True),
    ],
)
def test_a_boundary_is_a_threshold_and_a_comparator(comparator, score, expected):
    """docs/adr/0080: ``>= 40`` and ``> 40`` disagree about exactly 40."""
    boundary = CandidateBoundary(threshold=Decimal("40"), comparator=comparator)
    assert boundary.decides(Decimal(score)) is expected


def test_a_boundary_decides_equal_scores_identically() -> None:
    boundary = CandidateBoundary(threshold=Decimal("0.4"), comparator=GT)
    equal = [Decimal("0.4"), Decimal("0.40"), Decimal("0.400")]
    assert len({boundary.decides(score) for score in equal}) == 1


# ---------------------------------------------------------- operating point


def test_an_operating_point_derives_its_id_from_its_fingerprint() -> None:
    point = an_operating_point()
    assert point.operating_point_id == operating_point_id(
        point.operating_point_fingerprint
    )
    assert point.operating_point_id.startswith("oppoint_")


def test_the_wall_clock_is_outside_the_operating_point_identity() -> None:
    first = an_operating_point(created_utc="2026-08-07T12:00:00Z")
    second = an_operating_point(created_utc="2030-01-01T00:00:00Z")
    assert first.operating_point_fingerprint == second.operating_point_fingerprint


def test_the_comparator_is_inside_the_operating_point_identity() -> None:
    assert (
        an_operating_point(comparator=GE).operating_point_fingerprint
        != an_operating_point(comparator=GT).operating_point_fingerprint
    )


def test_an_operating_point_refuses_a_comparator_that_inverts_it() -> None:
    with pytest.raises(ValueError, match="inverts every decision"):
        an_operating_point(score_direction=HIGHER, comparator=LE)


def test_failures_are_kept_apart_from_non_matches() -> None:
    """docs/adr/0006: attempts = scored + failures, and scored = match + non-match."""
    point = an_operating_point(
        observed_mated_attempts=1000,
        observed_mated_scored=990,
        mated_failures=10,
        observed_mated_matches=900,
        observed_mated_non_matches=90,
    )
    assert point.observed_mated_scored + point.mated_failures == (
        point.observed_mated_attempts
    )
    with pytest.raises(ValueError, match="a failure is neither"):
        an_operating_point(
            observed_mated_attempts=1000,
            observed_mated_scored=990,
            mated_failures=10,
            observed_mated_matches=900,
            observed_mated_non_matches=100,
        )


def test_an_operating_point_over_an_empty_impostor_population_is_refused() -> None:
    with pytest.raises(ValueError, match="not a rate"):
        an_operating_point(
            observed_impostor_matches=0,
            observed_impostor_scored=0,
            observed_impostor_attempts=0,
            impostor_failures=0,
        )


def test_an_operating_point_that_breaks_its_own_ceiling_is_refused() -> None:
    with pytest.raises(ValueError, match="exceeds the target ceiling"):
        an_operating_point(
            observed_impostor_matches=5,
            observed_impostor_scored=1000,
            observed_impostor_attempts=1000,
            impostor_failures=0,
        )


def test_the_fingerprint_carries_no_timestamp_no_path_and_no_hostname() -> None:
    point = an_operating_point()
    covered = json.dumps(to_plain(point))
    assert calibration_operating_point_fingerprint(point) == (
        point.operating_point_fingerprint
    )
    for token in ("hostname", "/home/", "C:\\\\", "created_utc\": \"2026"):
        assert token not in covered.replace(point.created_utc, "")


# ------------------------------------------------------------ strict reading


def a_document(model) -> str:
    return json.dumps(to_plain(model))


def test_a_document_round_trips_to_the_same_identity() -> None:
    for model, reader in (
        (a_protocol(), read_calibration_protocol),
        (a_binding(), read_calibration_source_binding),
        (an_operating_point(), read_calibration_operating_point),
    ):
        restored = reader(strict_json_document(a_document(model)))
        assert restored == model


def test_the_registry_round_trips_to_the_same_identity() -> None:
    registry = build_protected_evaluation_registry(
        registry_id="reg_v1",
        registry_version="1",
        entries=[
            ProtectedEvaluationIdentity(
                kind=ProtectedIdentityKind.RUN,
                identity="run_protected",
                fingerprint="5" * 64,
                label="protected",
            )
        ],
    )
    restored = read_protected_evaluation_registry(
        strict_json_document(a_document(registry))
    )
    assert restored == registry


def test_a_duplicate_json_key_is_refused() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        strict_json_document('{"protocol_id": "a", "protocol_id": "b"}')


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_nan_and_infinity_are_refused(literal) -> None:
    with pytest.raises(ValueError):
        strict_json_document('{"target_rate_numerator": %s}' % literal)


def test_a_fractional_json_number_is_refused_outright() -> None:
    """A score and a threshold are written as strings, so nothing is a double."""
    with pytest.raises(ValueError, match="fractional part"):
        strict_json_document('{"threshold": 0.4}')


def test_an_unknown_key_is_refused_rather_than_ignored() -> None:
    document = json.loads(a_document(a_protocol()))
    document["clever_extra"] = "yes"
    with pytest.raises(CalibrationProtocolError, match="nothing reads"):
        read_calibration_protocol(document)


def test_a_missing_key_is_refused_rather_than_defaulted() -> None:
    document = json.loads(a_document(a_protocol()))
    del document["tie_policy"]
    with pytest.raises(CalibrationProtocolError, match="missing"):
        read_calibration_protocol(document)


def test_a_boolean_is_not_an_integer_and_an_integer_is_not_a_string() -> None:
    document = json.loads(a_document(a_protocol()))
    document["target_rate_numerator"] = True
    with pytest.raises(CalibrationProtocolError, match="exact integer"):
        read_calibration_protocol(document)

    document = json.loads(a_document(a_protocol()))
    document["target_rate_denominator"] = "1000"
    with pytest.raises(CalibrationProtocolError, match="exact integer"):
        read_calibration_protocol(document)


def test_a_threshold_written_as_a_number_never_reaches_a_decimal() -> None:
    document = json.loads(a_document(an_operating_point()))
    document["threshold"] = 40
    with pytest.raises(CalibrationInputError, match="written as a string"):
        read_calibration_operating_point(document)


def test_an_unknown_enum_spelling_is_refused_with_the_ones_it_knows() -> None:
    document = json.loads(a_document(a_binding()))
    document["cohort_role"] = "evaluation"
    with pytest.raises(CalibrationSourceError, match="not one of"):
        read_calibration_source_binding(document)


def test_a_fingerprint_must_be_a_full_digest() -> None:
    document = json.loads(a_document(a_binding()))
    document["run_fingerprint"] = "abc123"
    with pytest.raises(CalibrationSourceError, match="64-character"):
        read_calibration_source_binding(document)


def test_a_tampered_fingerprint_does_not_survive_reading() -> None:
    document = json.loads(a_document(a_protocol()))
    document["target_rate_numerator"] = 5
    with pytest.raises(CalibrationProtocolError, match="does not cover"):
        read_calibration_protocol(document)


def test_require_finite_decimal_refuses_a_float_even_though_it_would_convert():
    assert require_finite_decimal("0.1", "x") == Decimal("0.1")
    assert require_finite_decimal(Decimal("0.1"), "x") == Decimal("0.1")
    with pytest.raises(ValueError, match="never a float"):
        require_finite_decimal(0.1, "x")
