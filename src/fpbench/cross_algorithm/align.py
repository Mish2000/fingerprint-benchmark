"""Proving two finished chains were measuring the same thing, before comparing.

Everything in stage 7D's last gate rests on one claim: that the difference
between the two sets of decisions is attributable to the two algorithms and
their documented operating points, rather than to the pairs, the images, the
denominators, the formulas or the code. That claim is not self-evident and it is
not asserted here — it is *checked*, item by item, and the check produces an
artefact with a fingerprint (spec section 56).

Three things live in this module.

:func:`load_comparison_policy`
    Reads ``configs/comparisons/policies/<name>.yaml`` strictly. Every key in
    that file is a refusal, an unknown key is an error rather than a no-op, and
    the resulting fingerprint reaches the protocol, the definition, the receipt
    and the marker.

:func:`build_fair_comparability_audit`
    Turns six equalities and five negatives into one immutable record. A clean
    audit is the precondition for building a single paired row.

:func:`build_comparison_records`
    Walks the two decision sets in plan order and pairs them by pair id. It
    never reads a score, and there is no parameter through which one could reach
    it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.core.cross_algorithm_models import (
    FairComparabilityAudit,
    FairMeasurementProtocol,
    OPERATING_POINT_RELATION,
    CrossAlgorithmComparisonRecord,
    comparison_record_hash,
    fair_comparability_audit_fingerprint,
)
from fpbench.core.enums import (
    DecisionApplicationStatus,
    DecisionOutcome,
    IntegrityIssueCode,
    IntegritySeverity,
)
from fpbench.core.errors import ConfigurationError, FpbenchError
from fpbench.core.run_state_models import IntegrityIssue
from fpbench.core.serialization import stable_hash

__all__ = [
    "ComparisonPolicy",
    "ComparisonSide",
    "CrossAlgorithmError",
    "load_comparison_policy",
    "load_fair_measurement_protocol",
    "build_fair_measurement_protocol",
    "build_fair_comparability_audit",
    "build_comparison_records",
    "outcome_of",
    "require_clean_audit",
]


class CrossAlgorithmError(FpbenchError):
    """A cross-algorithm comparison cannot be built or cannot be believed."""


# ------------------------------------------------------------------ policy


#: Every key the policy file may contain, at every level. Written out rather
#: than inferred so that a typo is a refusal instead of a silently disabled
#: refusal (spec section 66).
_POLICY_SHAPE: Mapping[str, tuple[str, ...]] = {
    "policy": ("policy_id", "policy_version"),
    "operating_points": ("relation", "calibration_allowed", "test_cohort_allowed"),
    "populations": (
        "primary",
        "retain_side_specific_conditional",
        "retain_common_eligible",
    ),
    "scores": ("compare_raw", "normalise", "subtract", "correlate"),
    "statistics": ("confidence_intervals", "significance_tests"),
    "negative_sanity": ("label_as_fmr",),
    "claims": ("superiority", "causality", "equal_fmr"),
}

#: Flags that must be false. Each names something this project has not done and
#: has no machinery to do; a policy that switched one on would be asking for a
#: claim nothing could back.
_MUST_BE_FALSE: tuple[tuple[str, str], ...] = (
    ("operating_points", "calibration_allowed"),
    ("operating_points", "test_cohort_allowed"),
    ("scores", "compare_raw"),
    ("scores", "normalise"),
    ("scores", "subtract"),
    ("scores", "correlate"),
    ("statistics", "confidence_intervals"),
    ("statistics", "significance_tests"),
    ("negative_sanity", "label_as_fmr"),
    ("claims", "superiority"),
    ("claims", "causality"),
    ("claims", "equal_fmr"),
)

#: The only primary population this project reports. The full mated attempt set
#: is the one population that is identical for both algorithms by construction
#: (docs/adr/0059).
_PRIMARY_POPULATION = "mated_unconditional_all_attempts"


@dataclass(frozen=True, slots=True)
class ComparisonPolicy:
    """What a comparison may do, as a checked document with an identity."""

    policy_id: str
    policy_version: str
    primary_population: str
    retain_side_specific_conditional: bool
    retain_common_eligible: bool
    policy_fingerprint: str


def load_comparison_policy(path: Path) -> ComparisonPolicy:
    """Read a comparison policy, refusing anything it does not recognise.

    Raises:
        ConfigurationError: the file is missing, malformed, carries an unknown
            key, or switches on a refusal.
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"comparison policy not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    unknown_sections = sorted(set(map(str, document)) - set(_POLICY_SHAPE))
    if unknown_sections:
        raise ConfigurationError(
            f"{path}: unknown section(s) {unknown_sections}; a comparison policy "
            "has a fixed shape, and a section nothing reads is a refusal that "
            "does not happen"
        )
    for section, keys in _POLICY_SHAPE.items():
        block = document.get(section)
        if not isinstance(block, Mapping):
            raise ConfigurationError(f"{path}: missing or malformed {section!r}")
        unknown = sorted(set(map(str, block)) - set(keys))
        if unknown:
            raise ConfigurationError(f"{path}: unknown {section} key(s) {unknown}")
        missing = sorted(set(keys) - set(map(str, block)))
        if missing:
            raise ConfigurationError(f"{path}: {section} is missing {missing}")

    for section, key in _MUST_BE_FALSE:
        value = document[section][key]
        if type(value) is not bool:
            raise ConfigurationError(
                f"{path}: {section}.{key} must be a YAML boolean, got "
                f"{type(value).__name__}"
            )
        if value:
            raise ConfigurationError(
                f"{path}: {section}.{key} may not be true. It names something this "
                "project has not done, and a policy file is not where it could be "
                "done"
            )

    relation = str(document["operating_points"]["relation"]).strip()
    if relation != OPERATING_POINT_RELATION:
        raise ConfigurationError(
            f"{path}: operating_points.relation must be {OPERATING_POINT_RELATION!r}, "
            f"got {relation!r}. The two thresholds are both written '40' and are "
            "not the same operating point (docs/adr/0058)"
        )
    primary = str(document["populations"]["primary"]).strip()
    if primary != _PRIMARY_POPULATION:
        raise ConfigurationError(
            f"{path}: populations.primary must be {_PRIMARY_POPULATION!r}, got "
            f"{primary!r}. Every other population either filters rows or uses a "
            "denominator that differs between the two sides (docs/adr/0059)"
        )
    for key in ("retain_side_specific_conditional", "retain_common_eligible"):
        value = document["populations"][key]
        if type(value) is not bool:
            raise ConfigurationError(
                f"{path}: populations.{key} must be a YAML boolean"
            )
        if not value:
            raise ConfigurationError(
                f"{path}: populations.{key} may not be false. Dropping a population "
                "from the report would leave the reader with the primary number and "
                "no way to see what it excludes (docs/adr/0029)"
            )

    fingerprint = stable_hash(
        {
            "schema": "comparison_policy_v1",
            "document": {
                section: {key: document[section][key] for key in sorted(keys)}
                for section, keys in sorted(_POLICY_SHAPE.items())
            },
            # Inside the fingerprint on purpose: a policy that governs a
            # comparison also governs what the comparison is allowed to say, and
            # the sentence is part of the policy rather than of the renderer
            # (spec section 63).
            "statement": _statement(),
        },
        length=64,
    )
    return ComparisonPolicy(
        policy_id=str(document["policy"]["policy_id"]),
        policy_version=str(document["policy"]["policy_version"]),
        primary_population=primary,
        retain_side_specific_conditional=True,
        retain_common_eligible=True,
        policy_fingerprint=fingerprint,
    )


def _statement() -> str:
    from fpbench.core.cross_algorithm_models import NO_SUPERIORITY_STATEMENT

    return NO_SUPERIORITY_STATEMENT


# ---------------------------------------------------------------- protocol


def build_fair_measurement_protocol(**claims: Any) -> FairMeasurementProtocol:
    """Compute a protocol's fingerprint and construct it.

    Separate from the loader so that the fingerprint is derived in exactly one
    place, and so that the committed JSON can be produced by the same code that
    later reads it back and re-checks it.
    """
    from fpbench.core.cross_algorithm_models import (
        fair_measurement_protocol_fingerprint,
    )

    claims = dict(claims)
    claims.pop("protocol_fingerprint", None)
    return FairMeasurementProtocol(
        **claims,
        protocol_fingerprint=fair_measurement_protocol_fingerprint(claims),
    )


def load_fair_measurement_protocol(path: Path) -> FairMeasurementProtocol:
    """Read the committed methodology, and refuse it if it has been edited.

    The model recomputes its own fingerprint in ``__post_init__``, so a protocol
    whose threshold, comparator, policy or operating-point relation changed after
    it was committed fails to construct rather than loading with a new meaning
    (spec sections 12 and 13).

    Raises:
        ConfigurationError: the file is missing or malformed.
    """
    import json

    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"measurement protocol not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{path}: unreadable JSON ({exc})") from exc
    if not isinstance(payload, Mapping):
        raise ConfigurationError(f"{path}: expected an object at the top level")
    try:
        return FairMeasurementProtocol(**payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigurationError(f"{path}: invalid measurement protocol ({exc})") from exc


# -------------------------------------------------------------------- sides


@dataclass(frozen=True, slots=True)
class ComparisonSide:
    """One algorithm's finished chain, already verified by its own engine.

    Everything here was read back from an immutable store and re-verified before
    it arrived; this module compares, it does not validate. What it does check is
    that the two sides *line up* — which is a property of the pair, not of either
    side (spec section 56).
    """

    label: str

    run: Any
    result_set: Any
    decision_profile: Any
    decision_manifest: Any
    decisions: tuple
    eligibility_manifest: Any
    eligibility_records: tuple
    metric_manifest: Any

    #: Which stage marker made this side's raw scores authoritative, if any.
    stage_finalization_fingerprint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "decisions", tuple(self.decisions))
        object.__setattr__(
            self, "eligibility_records", tuple(self.eligibility_records)
        )


# --------------------------------------------------------------------- audit


def build_fair_comparability_audit(
    *,
    protocol: FairMeasurementProtocol,
    left: ComparisonSide,
    right: ComparisonSide,
    alignment_fingerprint: str,
    alignment_is_clean: bool,
    alignment_equal_pair_ids: int,
    alignment_equal_pair_semantics: int,
    alignment_equal_prepared_entries: int,
    expected_pairs: int,
    expected_prepared_entries: int,
) -> FairComparabilityAudit:
    """Check the six equalities and the five negatives, and record the outcome.

    The alignment numbers come from Stage 7C's own report, re-derived by the
    caller rather than rebuilt here. Building a second alignment in parallel
    would create a second answer to "were these the same inputs?", and the
    interesting failure is precisely the one where the two answers differ
    (docs/adr/0054, spec section 57).
    """
    issues: list[IntegrityIssue] = []

    def _fail(message: str) -> None:
        issues.append(
            IntegrityIssue(
                code=IntegrityIssueCode.PLAN_CONFLICT,
                severity=IntegritySeverity.ERROR,
                message=message,
            )
        )

    left_pairs = [record.pair_id for record in left.decisions]
    right_pairs = [record.pair_id for record in right.decisions]
    pair_ids_equal = left_pairs == right_pairs
    if not pair_ids_equal:
        _fail(
            f"the two decision sets do not cover the same {expected_pairs} pairs in "
            f"the same order ({len(left_pairs)} vs {len(right_pairs)} rows)"
        )
    if len(left_pairs) != expected_pairs:
        pair_ids_equal = False
        _fail(
            f"the {left.label} decision set holds {len(left_pairs)} decisions, "
            f"expected {expected_pairs}"
        )

    pair_semantics_equal = (
        alignment_is_clean
        and alignment_equal_pair_ids == expected_pairs
        and alignment_equal_pair_semantics == expected_pairs
    )
    if not pair_semantics_equal:
        _fail(
            "the stage 7C alignment does not show "
            f"{expected_pairs} pairs equal in id and in meaning "
            f"({alignment_equal_pair_ids}/{alignment_equal_pair_semantics})"
        )
    prepared_entries_equal = (
        alignment_is_clean
        and alignment_equal_prepared_entries == expected_prepared_entries
    )
    if not prepared_entries_equal:
        _fail(
            f"the stage 7C alignment does not show {expected_prepared_entries} "
            f"prepared images equal ({alignment_equal_prepared_entries})"
        )
    if alignment_fingerprint != protocol.alignment_fingerprint:
        _fail(
            "the alignment this workspace derives is not the one the frozen "
            "protocol names"
        )

    eligibility_policy_equal = (
        left.eligibility_manifest.policy_id == right.eligibility_manifest.policy_id
        and left.eligibility_manifest.policy_version
        == right.eligibility_manifest.policy_version
        and left.eligibility_manifest.policy_id == protocol.eligibility_policy_id
        and left.eligibility_manifest.policy_version
        == protocol.eligibility_policy_version
    )
    if not eligibility_policy_equal:
        _fail(
            "the two eligibility sets were derived under different policies, or "
            "under a policy the protocol does not name"
        )

    metric_policy_equal = (
        left.metric_manifest.metric_policy_fingerprint
        == right.metric_manifest.metric_policy_fingerprint
        == protocol.metric_policy_fingerprint
    )
    if not metric_policy_equal:
        _fail(
            "the two metric sets were counted under different policies, or under a "
            "policy the protocol does not name"
        )

    execution_profile_equal = (
        left.run.execution_profile_hash == right.run.execution_profile_hash
    )
    if not execution_profile_equal:
        _fail(
            "the two runs were executed under different execution profiles; the "
            "images, the timeout or the preparation differ"
        )

    left_calibrated = bool(left.decision_profile.calibration_performed)
    right_calibrated = bool(right.decision_profile.calibration_performed)
    test_cohort_used = _claims_test_cohort(left) or _claims_test_cohort(right)
    for label, calibrated in ((left.label, left_calibrated), (right.label, right_calibrated)):
        if calibrated:
            _fail(f"the {label} decision profile claims a calibrated threshold")
    if test_cohort_used:
        _fail("a decision profile claims the test cohort was used to choose it")

    equated = _claims_equivalence(left) or _claims_equivalence(right)
    if equated:
        _fail(
            "a decision profile claims its operating point is equivalent to the "
            "other algorithm's; the two thresholds are documented independently "
            "(docs/adr/0058)"
        )

    claims = {
        "protocol_fingerprint": protocol.protocol_fingerprint,
        "pair_alignment_fingerprint": alignment_fingerprint,
        "pair_ids_equal": pair_ids_equal,
        "pair_semantics_equal": pair_semantics_equal,
        "prepared_entries_equal": prepared_entries_equal,
        "eligibility_policy_equal": eligibility_policy_equal,
        "metric_policy_equal": metric_policy_equal,
        "execution_profile_equal": execution_profile_equal,
        "left_profile_origin": left.decision_profile.origin.value,
        "right_profile_origin": right.decision_profile.origin.value,
        "left_calibrated": left_calibrated,
        "right_calibrated": right_calibrated,
        "test_cohort_used": test_cohort_used,
        "operating_points_equated": equated,
        # There is no code path in this package that could set this true. It is
        # recorded because a reader of the audit needs to see the question asked
        # and answered, not because the answer could vary (spec section 52).
        "raw_scores_compared": False,
        "issues": tuple(issues),
    }
    return FairComparabilityAudit(
        **claims,
        audit_fingerprint=fair_comparability_audit_fingerprint(claims),
    )


def _claims_test_cohort(side: ComparisonSide) -> bool:
    metadata = dict(side.decision_profile.metadata)
    return metadata.get("calibration_test_cohort_used", "false") == "true"


def _claims_equivalence(side: ComparisonSide) -> bool:
    metadata = dict(side.decision_profile.metadata)
    return (
        metadata.get("claims.equivalent_to_sourceafis_operating_point", "false")
        == "true"
    )


def require_clean_audit(audit: FairComparabilityAudit) -> None:
    """Refuse to compare two chains that are not comparable.

    Raises:
        CrossAlgorithmError: any required condition is unmet.
    """
    if audit.is_clean:
        return
    raise CrossAlgorithmError(
        "the fair-comparability audit is not clean: "
        f"{list(audit.failures)} "
        f"{[issue.message for issue in audit.issues][:3]}"
    )


# ------------------------------------------------------------------ records


def outcome_of(record: Any) -> DecisionOutcome:
    """Flatten one decision into the three-valued outcome a matrix has a row for.

    ``UNDECIDABLE`` is kept as its own outcome and is never folded into
    ``NON_MATCH``: a comparison that produced no score did not fail to match, it
    failed to happen (docs/adr/0006).
    """
    if record.application_status is DecisionApplicationStatus.UNDECIDABLE:
        return DecisionOutcome.UNDECIDABLE
    return DecisionOutcome(record.decision.value)


def build_comparison_records(
    *,
    left: ComparisonSide,
    right: ComparisonSide,
    pairs: Mapping[Any, Any],
) -> tuple[CrossAlgorithmComparisonRecord, ...]:
    """One row per pair, carrying both outcomes and the artefacts behind them.

    Paired positionally *and* checked by pair id. Positional pairing alone would
    silently compare row 4,001 of one run with row 4,001 of another after a
    reordering; checking the id alone would lose the guarantee that the two runs
    executed the same plan in the same order (spec section 51).

    Raises:
        CrossAlgorithmError: the two sides are not row-for-row the same pairs.
    """
    if len(left.decisions) != len(right.decisions):
        raise CrossAlgorithmError(
            f"the {left.label} chain holds {len(left.decisions)} decisions and the "
            f"{right.label} chain holds {len(right.decisions)}; a paired comparison "
            "needs one row each"
        )

    # The manifest is keyed by ``PairId``; the decisions carry plain strings.
    # Indexed once rather than searched per row: a linear scan here would be
    # thirty-six million comparisons for six thousand pairs.
    pairs_by_id = {str(key): pair for key, pair in pairs.items()}

    records: list[CrossAlgorithmComparisonRecord] = []
    for ordinal, (left_record, right_record) in enumerate(
        zip(left.decisions, right.decisions, strict=True)
    ):
        if left_record.pair_id != right_record.pair_id:
            raise CrossAlgorithmError(
                f"at ordinal {ordinal} the {left.label} chain covers pair "
                f"{left_record.pair_id} and the {right.label} chain covers "
                f"{right_record.pair_id}"
            )
        pair = _pair_for(pairs_by_id, left_record.pair_id)
        fields = {
            "ordinal": ordinal,
            "pair_id": left_record.pair_id,
            "release": pair.release,
            "protocol_stage": pair.protocol_stage.value,
            "left_decision_hash": left_record.decision_record_hash,
            "right_decision_hash": right_record.decision_record_hash,
            "left_raw_result_hash": left_record.source_result_hash,
            "right_raw_result_hash": right_record.source_result_hash,
            "left_outcome": outcome_of(left_record),
            "right_outcome": outcome_of(right_record),
        }
        probe = _RecordProbe(**fields)
        records.append(
            CrossAlgorithmComparisonRecord(
                record_hash=comparison_record_hash(probe),  # type: ignore[arg-type]
                **fields,
            )
        )
    return tuple(records)


def _pair_for(pairs_by_id: Mapping[str, Any], pair_id: str) -> Any:
    pair = pairs_by_id.get(pair_id)
    if pair is None:
        raise CrossAlgorithmError(
            f"pair {pair_id} is decided by both chains but is not in the pair "
            "manifest"
        )
    return pair


class _RecordProbe:
    """The attributes ``comparison_record_hash`` reads, and nothing else."""

    __slots__ = (
        "ordinal",
        "pair_id",
        "release",
        "protocol_stage",
        "left_decision_hash",
        "right_decision_hash",
        "left_raw_result_hash",
        "right_raw_result_hash",
        "left_outcome",
        "right_outcome",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))


def _unused(_: Sequence[Any]) -> None:  # pragma: no cover - documentation only
    """There is deliberately no function here that reads a raw score.

    Kept as a marker for readers: the module imports no result store, no score
    parser and no threshold, and the structural suite asserts as much by walking
    this file's syntax tree (spec section 76).
    """
