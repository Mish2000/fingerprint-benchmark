"""The immutable artifacts a calibration produces, and the exact arithmetic.

Five containers, and every one of them is a statement somebody could otherwise
have made in a sentence:

**A protocol** is the policy, frozen before any score is read: which rate is
constrained, to what, by which selection rule, over which population, with which
tie policy. It carries no algorithm and no dataset. The same protocol is meant to
be run over five matchers whose numbers have nothing in common (docs/adr/0080).

**A source binding** is the one exact body of development scores a threshold was
chosen from. Every identity in it is content-addressed, and there is deliberately
no field naming a path: a threshold whose provenance is "the file that was in
that directory" is a threshold nobody can re-derive (spec section 7).

**A protected evaluation registry** is the list of identities a calibration may
never draw from. It holds identities and nothing else — no score, no count of
scores, no statistic — and it exists so that the prohibition is executable rather
than a sentence in a README (docs/adr/0079).

**An operating point** is the answer: a threshold, the comparator that says which
side of it matches, the exact target it was selected against, and the counts that
were observed. Failures are counted separately from non-matches, because a
comparison that produced no score did not fail to match (docs/adr/0006).

**An exact rate** is the reason none of this uses floating point. ``0.001`` is
not one thousandth, and a borderline candidate compared against it would be
decided by the rounding of IEEE 754. A target is a numerator and a denominator,
and every comparison of two rates is a cross-multiplication of integers:

.. math::

    \\frac{a}{b} \\le \\frac{c}{d}
    \\quad\\Longleftrightarrow\\quad
    a \\cdot d \\le c \\cdot b

The dataclasses live in ``core`` because the storage layer persists them and
``storage`` may only import ``core``. The rules for deriving them live in
:mod:`fpbench.calibration`, which re-exports the containers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from math import gcd
from typing import Any, Iterable, Mapping, Sequence

from fpbench.core.decision_models import canonical_threshold
from fpbench.core.enums import (
    CalibrationFailurePolicy,
    CalibrationPairTruth,
    CalibrationTargetMetric,
    CalibrationTargetPopulation,
    CalibrationTiePolicy,
    CandidateBoundaryPolicy,
    CohortRole,
    ProtectedIdentityKind,
    ScoreDirection,
    ScoreNormalizationPolicy,
    ScorePopulationPolicy,
    ThresholdComparator,
    ThresholdSelectionRule,
)
from fpbench.core.calibration_errors import (
    CalibrationInputError,
    CalibrationProtocolError,
    CalibrationSourceError,
)
from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import (
    freeze_str_mapping,
    require_exact_int,
    stable_hash,
    to_plain,
)

__all__ = [
    "strict_json_document",
    "require_exact_keys",
    "read_str",
    "read_int",
    "read_bool",
    "read_digest",
    "read_enum",
    "read_decimal_text",
    "require_finite_decimal",
    "read_calibration_protocol",
    "read_calibration_source_binding",
    "read_protected_evaluation_registry",
    "read_calibration_operating_point",
    "CALIBRATION_PROTOCOL_SCHEMA_VERSION",
    "CALIBRATION_SOURCE_BINDING_SCHEMA_VERSION",
    "CALIBRATION_OPERATING_POINT_SCHEMA_VERSION",
    "PROTECTED_REGISTRY_SCHEMA_VERSION",
    "OPERATING_POINT_ID_LENGTH",
    "ExactRate",
    "rate_at_most",
    "CalibrationProtocol",
    "CalibrationSourceBinding",
    "ProtectedEvaluationIdentity",
    "ProtectedEvaluationRegistry",
    "CalibrationOperatingPoint",
    "calibration_protocol_fingerprint",
    "calibration_source_binding_fingerprint",
    "protected_evaluation_registry_fingerprint",
    "calibration_operating_point_fingerprint",
    "operating_point_id",
    "require_exact_bool",
    "require_digest",
]

#: Bumped when the meaning of one of these artifacts changes. Four independent
#: versions rather than one, because a protocol and an operating point are not
#: obliged to evolve together.
CALIBRATION_PROTOCOL_SCHEMA_VERSION = "1"
CALIBRATION_SOURCE_BINDING_SCHEMA_VERSION = "2"
CALIBRATION_OPERATING_POINT_SCHEMA_VERSION = "2"
PROTECTED_REGISTRY_SCHEMA_VERSION = "1"

OPERATING_POINT_ID_LENGTH = 12

_HEX = frozenset("0123456789abcdef")


def require_digest(value: object, field_name: str) -> str:
    """A 64-character lowercase hexadecimal digest, or a refusal.

    There is no short form and no ``sha256:`` prefix. A fingerprint that could be
    written two ways is a fingerprint two documents can disagree about while
    naming the same thing.
    """
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def require_exact_bool(value: object, field_name: str) -> bool:
    """A ``bool``, without accepting ``1``, ``"true"`` or a truthy object.

    The mirror of :func:`fpbench.core.serialization.require_exact_int`. These
    flags are the ones that say a calibration was *not* performed and that
    evaluation data was *not* read, so a coercion here would let a document make
    a claim its bytes do not support.
    """
    if type(value) is not bool:
        raise ValueError(
            f"{field_name} must be a boolean, got {type(value).__name__}"
        )
    return value


# ------------------------------------------------------------------ exact rate


def rate_at_most(
    numerator: int, denominator: int, ceiling_numerator: int, ceiling_denominator: int
) -> bool:
    """Whether ``numerator/denominator <= ceiling_numerator/ceiling_denominator``.

    Evaluated as ``a*d <= c*b`` over Python integers, which are unbounded, so the
    answer is exact for every input and never depends on a rounding mode. Both
    denominators must be positive; a rate over nothing is not a small rate, it is
    not a rate, and the caller has to decide what that means rather than being
    handed ``False``.
    """
    a = require_exact_int(numerator, "numerator")
    b = require_exact_int(denominator, "denominator")
    c = require_exact_int(ceiling_numerator, "ceiling_numerator")
    d = require_exact_int(ceiling_denominator, "ceiling_denominator")
    if b <= 0 or d <= 0:
        raise ValueError("a rate needs a positive denominator on both sides")
    return a * d <= c * b


@dataclass(frozen=True, slots=True)
class ExactRate:
    """A target rate as a pair of integers, in lowest terms.

    Canonicalised on construction for the same reason a threshold is: ``1/1000``
    and ``2/2000`` are one rate, and a protocol whose fingerprint depended on
    which spelling somebody typed would be two protocols with one meaning.

    Observed rates are deliberately *not* represented with this class. ``1/1000``
    and ``2/2000`` are different observations — one impostor match in a thousand
    comparisons is not two in two thousand — so counts are carried as counts and
    reduced nowhere (spec section 9).

    This is a *rate*, not a general ratio, so it is bounded by ``[0, 1]``.
    ``0/1`` and ``1/1`` are both meaningful — admit no impostor, admit every
    impostor — and ``5/4`` is not a lax target, it is a target that says nothing:
    every boundary satisfies it, including the one that admits everything, so a
    protocol carrying it would report a selection nobody constrained.
    """

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        numerator = require_exact_int(self.numerator, "numerator")
        denominator = require_exact_int(self.denominator, "denominator")
        if denominator <= 0:
            raise ValueError("a rate needs a positive denominator")
        if numerator < 0:
            raise ValueError("a rate must not be negative")
        if numerator > denominator:
            raise ValueError(
                f"a rate must not exceed 1, and {numerator}/{denominator} does. "
                "A target above 1 constrains nothing: every boundary satisfies "
                "it, including the one that admits every impostor"
            )
        divisor = gcd(numerator, denominator) or 1
        object.__setattr__(self, "numerator", numerator // divisor)
        object.__setattr__(self, "denominator", denominator // divisor)

    def covers(self, matches: int, population: int) -> bool:
        """Whether an observed ``matches/population`` does not exceed this rate."""
        return rate_at_most(matches, population, self.numerator, self.denominator)

    def __str__(self) -> str:
        return f"{self.numerator}/{self.denominator}"


# -------------------------------------------------------------------- protocol


@dataclass(frozen=True, slots=True)
class CalibrationProtocol:
    """The policy, frozen before a score is read.

    Deliberately carries no algorithm, no dataset, no cohort and no scale. Two
    matchers calibrated under the same protocol share a *definition* of the
    operating point they are aiming at; they share no number (docs/adr/0080).
    """

    protocol_id: str
    protocol_version: str

    target_metric: CalibrationTargetMetric
    target_rate_numerator: int
    target_rate_denominator: int
    target_population: CalibrationTargetPopulation

    threshold_selection_rule: ThresholdSelectionRule
    candidate_boundary_policy: CandidateBoundaryPolicy
    tie_policy: CalibrationTiePolicy

    score_population_policy: ScorePopulationPolicy
    failure_policy: CalibrationFailurePolicy

    requires_cross_subject_impostors: bool
    requires_development_role: bool

    quality_filtering: bool
    normalization: ScoreNormalizationPolicy

    protocol_fingerprint: str

    schema_version: str = CALIBRATION_PROTOCOL_SCHEMA_VERSION
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        version = str(self.schema_version).strip()
        if version != CALIBRATION_PROTOCOL_SCHEMA_VERSION:
            raise CalibrationProtocolError(
                f"unsupported calibration-protocol schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)

        validate_id(self.protocol_id)
        protocol_version = str(self.protocol_version).strip()
        if not protocol_version:
            raise CalibrationProtocolError("protocol_version must not be empty")
        object.__setattr__(self, "protocol_version", protocol_version)

        rate = ExactRate(
            numerator=require_exact_int(
                self.target_rate_numerator, "target_rate_numerator"
            ),
            denominator=require_exact_int(
                self.target_rate_denominator, "target_rate_denominator"
            ),
        )
        object.__setattr__(self, "target_rate_numerator", rate.numerator)
        object.__setattr__(self, "target_rate_denominator", rate.denominator)

        for name in (
            "requires_cross_subject_impostors",
            "requires_development_role",
            "quality_filtering",
        ):
            object.__setattr__(
                self, name, require_exact_bool(getattr(self, name), name)
            )

        # The three refusals that make this protocol the one docs/adr/0079 and
        # docs/adr/0080 describe, rather than a shape somebody could fill in with
        # a laxer policy and the same class name.
        if not self.requires_cross_subject_impostors:
            raise CalibrationProtocolError(
                "a calibration protocol must require cross-subject impostors; the "
                "same-subject sanity comparisons do not estimate the rate at which "
                "two different people are confused (docs/adr/0079)"
            )
        if not self.requires_development_role:
            raise CalibrationProtocolError(
                "a calibration protocol must require a development cohort; "
                "choosing a threshold on the cohort it is later reported on is the "
                "one form of leakage that invalidates the study (docs/adr/0021)"
            )
        if self.quality_filtering:
            raise CalibrationProtocolError(
                "quality filtering is not available in v1: letting each algorithm "
                "discard the development prints it finds hard would give each one "
                "a different development population under one protocol name "
                "(spec section 18)"
            )
        if self.normalization is not ScoreNormalizationPolicy.NONE:
            raise CalibrationProtocolError(
                "calibration reads the raw score on the algorithm's own scale; "
                "there is no normalization (docs/adr/0080)"
            )

        # A selection rule that does not constrain the metric it claims to is a
        # protocol whose name and behaviour disagree.
        if (
            self.target_metric is CalibrationTargetMetric.IMPOSTOR_MATCH_RATE
            and self.threshold_selection_rule
            is not ThresholdSelectionRule.MOST_PERMISSIVE_WITHIN_IMPOSTOR_CEILING
        ):
            raise CalibrationProtocolError(
                f"target metric {self.target_metric.value!r} is not constrained by "
                f"selection rule {self.threshold_selection_rule.value!r}"
            )

        object.__setattr__(self, "metadata", freeze_str_mapping(self.metadata))
        object.__setattr__(
            self,
            "protocol_fingerprint",
            require_digest(self.protocol_fingerprint, "protocol_fingerprint"),
        )
        recomputed = calibration_protocol_fingerprint(self)
        if self.protocol_fingerprint != recomputed:
            raise CalibrationProtocolError(
                "protocol_fingerprint does not cover the protocol it is attached to"
            )

    @property
    def target_rate(self) -> ExactRate:
        return ExactRate(
            numerator=self.target_rate_numerator,
            denominator=self.target_rate_denominator,
        )

    def permits(self, matches: int, population: int) -> bool:
        """Whether an observed impostor rate is inside this protocol's ceiling."""
        return rate_at_most(
            matches, population, self.target_rate_numerator,
            self.target_rate_denominator,
        )


def calibration_protocol_fingerprint(
    protocol: CalibrationProtocol | Mapping[str, Any],
) -> str:
    """A digest of every field that could change which boundary is selected.

    Excludes the fingerprint itself and nothing else. There is no display name to
    leave out and no timestamp to exclude: a protocol is a policy, and two people
    who write the same policy have written the same protocol.
    """
    plain = dict(to_plain(protocol))
    plain.pop("protocol_fingerprint", None)
    return stable_hash(
        {"schema": "calibration_protocol_v1", "protocol": plain}, length=64
    )


# -------------------------------------------------------------- source binding


#: Every identity a source binding pins, and the kind of value each one is. The
#: tuple is the schema: a field added here changes the binding fingerprint, and a
#: field missing from a document is a refusal rather than a default.
_BINDING_IDS: tuple[str, ...] = (
    "algorithm_id",
    "integration_id",
    "run_id",
    "result_set_id",
    "dataset_id",
    "cohort_id",
    "pair_manifest_id",
)
_BINDING_FINGERPRINTS: tuple[str, ...] = (
    "algorithm_fingerprint",
    "integration_fingerprint",
    "run_fingerprint",
    "result_set_fingerprint",
    "dataset_fingerprint",
    "cohort_fingerprint",
    "pair_manifest_fingerprint",
)


@dataclass(frozen=True, slots=True)
class CalibrationSourceBinding:
    """The one exact body of scores a threshold may be chosen from.

    Note what is absent: any field naming a path, a directory or a filename. A
    binding that identified its scores as "whatever was in that folder" would be
    unre-derivable the moment the folder changed, and nothing would announce it
    (spec section 7).

    Note also what is present but unused by the arithmetic: ``cohort_role``. It
    is inside the fingerprint, so a binding cannot be relabelled from evaluation
    to development without becoming a different binding (docs/adr/0079).
    """

    binding_id: str

    algorithm_id: str
    algorithm_fingerprint: str

    integration_id: str
    integration_fingerprint: str

    run_id: str
    run_fingerprint: str

    result_set_id: str
    result_set_fingerprint: str

    # The exact labelled view derived from that result set.  The result-set
    # fingerprint alone identifies raw records; it does not identify which
    # pair ids and ground-truth labels were joined to those scores.
    labeled_results_hash: str
    pair_ids: tuple[str, ...]
    ground_truth: tuple[CalibrationPairTruth, ...]

    dataset_id: str
    dataset_fingerprint: str

    cohort_id: str
    cohort_fingerprint: str
    cohort_role: CohortRole

    pair_manifest_id: str
    pair_manifest_fingerprint: str

    score_direction: ScoreDirection

    source_binding_fingerprint: str

    schema_version: str = CALIBRATION_SOURCE_BINDING_SCHEMA_VERSION
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        version = str(self.schema_version).strip()
        if version != CALIBRATION_SOURCE_BINDING_SCHEMA_VERSION:
            raise CalibrationSourceError(
                f"unsupported calibration source-binding schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)

        validate_id(self.binding_id)
        for name in _BINDING_IDS:
            validate_id(str(getattr(self, name)))
        for name in _BINDING_FINGERPRINTS:
            object.__setattr__(self, name, require_digest(getattr(self, name), name))
        object.__setattr__(
            self,
            "labeled_results_hash",
            require_digest(self.labeled_results_hash, "labeled_results_hash"),
        )

        pair_ids = tuple(str(pair_id).strip() for pair_id in self.pair_ids)
        if not pair_ids or any(not pair_id for pair_id in pair_ids):
            raise CalibrationSourceError(
                "a source binding must name every non-empty pair_id in its labelled results"
            )
        if len(set(pair_ids)) != len(pair_ids):
            raise CalibrationSourceError(
                "a source binding may bind each pair_id only once"
            )
        if pair_ids != tuple(sorted(pair_ids)):
            raise CalibrationSourceError(
                "source-binding pair_ids must be in canonical lexical order"
            )
        truth = tuple(self.ground_truth)
        if len(truth) != len(pair_ids):
            raise CalibrationSourceError(
                "source-binding pair_ids and ground_truth must have the same length"
            )
        if any(not isinstance(item, CalibrationPairTruth) for item in truth):
            raise CalibrationSourceError(
                "every source-binding ground_truth value must be a CalibrationPairTruth"
            )
        object.__setattr__(self, "pair_ids", pair_ids)
        object.__setattr__(self, "ground_truth", truth)
        object.__setattr__(
            self,
            "source_binding_fingerprint",
            require_digest(
                self.source_binding_fingerprint, "source_binding_fingerprint"
            ),
        )

        metadata = freeze_str_mapping(self.metadata)
        located = sorted(
            key
            for key in metadata
            if any(
                token in str(key).lower()
                for token in ("path", "directory", "filename", "location")
            )
        )
        if located:
            raise CalibrationSourceError(
                f"a source binding identifies scores by fingerprint, not by where "
                f"they were stored: {located} (spec section 7)"
            )
        object.__setattr__(self, "metadata", metadata)

        recomputed = calibration_source_binding_fingerprint(self)
        if self.source_binding_fingerprint != recomputed:
            raise CalibrationSourceError(
                "source_binding_fingerprint does not cover the binding it is "
                "attached to"
            )

    @property
    def identity_fingerprints(self) -> tuple[str, ...]:
        """Every content-addressed identity this binding resolves to.

        What the protected-evaluation check is run against. The algorithm and
        integration fingerprints are excluded on purpose: an algorithm is not
        evaluation data, and refusing one would forbid ever calibrating the
        matcher that produced the protected run (docs/adr/0079).
        """
        return (
            self.run_fingerprint,
            self.result_set_fingerprint,
            self.dataset_fingerprint,
            self.cohort_fingerprint,
            self.pair_manifest_fingerprint,
        )

    @property
    def identity_ids(self) -> tuple[str, ...]:
        return (
            self.run_id,
            self.result_set_id,
            self.dataset_id,
            self.cohort_id,
            self.pair_manifest_id,
        )


def calibration_source_binding_fingerprint(
    binding: CalibrationSourceBinding | Mapping[str, Any],
) -> str:
    plain = dict(to_plain(binding))
    plain.pop("source_binding_fingerprint", None)
    return stable_hash(
        {"schema": "calibration_source_binding_v2", "binding": plain}, length=64
    )


# ------------------------------------------------------- protected evaluation


@dataclass(frozen=True, slots=True)
class ProtectedEvaluationIdentity:
    """One thing a calibration may never draw a threshold from.

    An identity and a digest. There is no field here that could hold a score, a
    count of scores or a summary of them, and that is the artifact's entire
    design: it makes the prohibition executable without importing the thing it
    prohibits (docs/adr/0079).
    """

    kind: ProtectedIdentityKind
    identity: str
    fingerprint: str
    label: str

    def __post_init__(self) -> None:
        validate_id(str(self.identity))
        object.__setattr__(
            self, "fingerprint", require_digest(self.fingerprint, "fingerprint")
        )
        label = str(self.label).strip()
        if not label:
            raise ValueError(
                "a protected identity needs a label; an unexplained digest in a "
                "refusal list is a digest nobody can maintain"
            )
        object.__setattr__(self, "label", label)


@dataclass(frozen=True, slots=True)
class ProtectedEvaluationRegistry:
    """The identities calibration refuses, whatever role a binding claims.

    Ordered and de-duplicated on construction, so that two registries listing the
    same identities in different orders are one registry with one fingerprint.
    """

    registry_id: str
    registry_version: str
    entries: tuple[ProtectedEvaluationIdentity, ...]
    registry_fingerprint: str

    schema_version: str = PROTECTED_REGISTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        version = str(self.schema_version).strip()
        if version != PROTECTED_REGISTRY_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported protected-registry schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        validate_id(self.registry_id)
        registry_version = str(self.registry_version).strip()
        if not registry_version:
            raise ValueError("registry_version must not be empty")
        object.__setattr__(self, "registry_version", registry_version)

        entries = tuple(self.entries)
        if not entries:
            raise ValueError(
                "an empty protected-evaluation registry protects nothing, and a "
                "registry that protects nothing is worse than none: it looks like "
                "a check (docs/adr/0079)"
            )
        seen: dict[str, ProtectedEvaluationIdentity] = {}
        for entry in entries:
            if not isinstance(entry, ProtectedEvaluationIdentity):
                raise TypeError("registry entries must be protected identities")
            previous = seen.get(entry.fingerprint)
            if previous is not None and previous != entry:
                raise ValueError(
                    f"fingerprint {entry.fingerprint[:12]}... is registered twice "
                    f"with different claims: {previous.label!r} and {entry.label!r}"
                )
            seen[entry.fingerprint] = entry
        ordered = tuple(
            sorted(seen.values(), key=lambda item: (item.kind.value, item.identity))
        )
        object.__setattr__(self, "entries", ordered)

        object.__setattr__(
            self,
            "registry_fingerprint",
            require_digest(self.registry_fingerprint, "registry_fingerprint"),
        )
        recomputed = protected_evaluation_registry_fingerprint(self)
        if self.registry_fingerprint != recomputed:
            raise ValueError(
                "registry_fingerprint does not cover the registry it is attached to"
            )

    @property
    def protected_fingerprints(self) -> frozenset[str]:
        return frozenset(entry.fingerprint for entry in self.entries)

    @property
    def protected_identities(self) -> frozenset[str]:
        return frozenset(entry.identity for entry in self.entries)

    def matches(self, *, fingerprints: Iterable[str], identities: Iterable[str]):
        """Every registered entry a candidate source resolves to.

        Both halves are checked. A fingerprint match is the real one; an identity
        match catches a binding that re-declared a protected run id under a
        freshly computed digest, which is what an honest mistake looks like.
        """
        wanted_fingerprints = {str(value).strip().lower() for value in fingerprints}
        wanted_identities = {str(value).strip() for value in identities}
        return tuple(
            entry
            for entry in self.entries
            if entry.fingerprint in wanted_fingerprints
            or entry.identity in wanted_identities
        )


def protected_evaluation_registry_fingerprint(
    registry: ProtectedEvaluationRegistry | Mapping[str, Any],
) -> str:
    plain = dict(to_plain(registry))
    plain.pop("registry_fingerprint", None)
    return stable_hash(
        {"schema": "protected_evaluation_registry_v1", "registry": plain}, length=64
    )


# ------------------------------------------------------------- operating point


#: The counts an operating point carries, and the arithmetic each one is part of.
_MATED_COUNTS = (
    "observed_mated_matches",
    "observed_mated_non_matches",
    "observed_mated_scored",
    "observed_mated_attempts",
    "mated_failures",
)
_IMPOSTOR_COUNTS = (
    "observed_impostor_matches",
    "observed_impostor_scored",
    "observed_impostor_attempts",
    "impostor_failures",
)


@dataclass(frozen=True, slots=True)
class CalibrationOperatingPoint:
    """A boundary, what it was selected against, and what was observed at it.

    The threshold and the comparator travel together and neither means anything
    alone: ``>= 40`` and ``> 40`` disagree about every comparison that scored
    exactly 40 (docs/adr/0055, docs/adr/0080).

    The counts are kept in three layers — attempts, scored, failures — rather
    than collapsed into two. A comparison that produced no score is not a
    non-match and never becomes one; it is excluded from the selection and stays
    visible here, so a reader can see how much of the development population the
    boundary was actually chosen from (docs/adr/0006, spec section 17).

    The fingerprint covers everything except itself and ``created_utc``. No
    timestamp, no absolute path and no hostname reaches it: the same selection,
    run on two machines, is one operating point (spec section 20).
    """

    operating_point_id: str
    operating_point_fingerprint: str

    calibration_protocol_fingerprint: str
    source_binding_fingerprint: str

    labeled_results_hash: str
    pair_ids: tuple[str, ...]
    ground_truth: tuple[CalibrationPairTruth, ...]

    algorithm_id: str
    algorithm_fingerprint: str

    threshold: str
    comparator: ThresholdComparator
    score_direction: ScoreDirection

    target_rate_numerator: int
    target_rate_denominator: int

    observed_impostor_matches: int
    observed_impostor_scored: int
    observed_impostor_attempts: int
    impostor_failures: int

    observed_mated_matches: int
    observed_mated_non_matches: int
    observed_mated_scored: int
    observed_mated_attempts: int
    mated_failures: int

    selection_rule: ThresholdSelectionRule
    tie_policy: CalibrationTiePolicy

    created_source_commit: str
    created_source_tree_clean: bool

    created_utc: str

    schema_version: str = CALIBRATION_OPERATING_POINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        version = str(self.schema_version).strip()
        if version != CALIBRATION_OPERATING_POINT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported operating-point schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)

        validate_id(self.algorithm_id)
        for name in (
            "operating_point_fingerprint",
            "calibration_protocol_fingerprint",
            "source_binding_fingerprint",
            "algorithm_fingerprint",
            "labeled_results_hash",
        ):
            object.__setattr__(self, name, require_digest(getattr(self, name), name))

        pair_ids = tuple(str(pair_id).strip() for pair_id in self.pair_ids)
        if not pair_ids or any(not pair_id for pair_id in pair_ids):
            raise ValueError(
                "an operating point must bind every non-empty pair_id it was selected from"
            )
        if len(set(pair_ids)) != len(pair_ids):
            raise ValueError("an operating point may bind each pair_id only once")
        if pair_ids != tuple(sorted(pair_ids)):
            raise ValueError("operating-point pair_ids must be in canonical lexical order")
        truth = tuple(self.ground_truth)
        if len(truth) != len(pair_ids):
            raise ValueError(
                "operating-point pair_ids and ground_truth must have the same length"
            )
        if any(not isinstance(item, CalibrationPairTruth) for item in truth):
            raise ValueError(
                "every operating-point ground_truth value must be a CalibrationPairTruth"
            )
        object.__setattr__(self, "pair_ids", pair_ids)
        object.__setattr__(self, "ground_truth", truth)

        object.__setattr__(self, "threshold", canonical_threshold(self.threshold))

        # The comparator has to agree with the direction, or every decision made
        # under this operating point is inverted while the document looks fine.
        # Strict comparators are first-class here from the start: unlike a legacy
        # decision profile, no calibrated operating point predates schema 2.
        inclusive = {
            ScoreDirection.HIGHER_IS_BETTER: (
                ThresholdComparator.GREATER_THAN_OR_EQUAL,
                ThresholdComparator.GREATER_THAN,
            ),
            ScoreDirection.LOWER_IS_BETTER: (
                ThresholdComparator.LESS_THAN_OR_EQUAL,
                ThresholdComparator.LESS_THAN,
            ),
        }[self.score_direction]
        if self.comparator not in inclusive:
            spellings = ", ".join(sorted(item.value for item in inclusive))
            raise ValueError(
                f"score direction {self.score_direction.value!r} admits "
                f"{spellings}, not {self.comparator.value!r}; the other pairing "
                "inverts every decision made under this operating point"
            )

        rate = ExactRate(
            numerator=require_exact_int(
                self.target_rate_numerator, "target_rate_numerator"
            ),
            denominator=require_exact_int(
                self.target_rate_denominator, "target_rate_denominator"
            ),
        )
        object.__setattr__(self, "target_rate_numerator", rate.numerator)
        object.__setattr__(self, "target_rate_denominator", rate.denominator)

        for name in (*_MATED_COUNTS, *_IMPOSTOR_COUNTS):
            value = require_exact_int(getattr(self, name), name)
            if value < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)

        # Four arithmetic facts a reader should not have to check by hand.
        if self.observed_impostor_scored + self.impostor_failures != (
            self.observed_impostor_attempts
        ):
            raise ValueError(
                "every impostor attempt either produced a score or failed: "
                f"{self.observed_impostor_scored} + {self.impostor_failures} != "
                f"{self.observed_impostor_attempts}"
            )
        if self.observed_mated_scored + self.mated_failures != (
            self.observed_mated_attempts
        ):
            raise ValueError(
                "every mated attempt either produced a score or failed: "
                f"{self.observed_mated_scored} + {self.mated_failures} != "
                f"{self.observed_mated_attempts}"
            )
        if self.observed_impostor_matches > self.observed_impostor_scored:
            raise ValueError(
                "more impostor matches than impostor comparisons that produced a "
                "score"
            )
        if self.observed_mated_matches + self.observed_mated_non_matches != (
            self.observed_mated_scored
        ):
            raise ValueError(
                "every scored mated comparison is a match or a non-match, and a "
                "failure is neither (docs/adr/0006): "
                f"{self.observed_mated_matches} + "
                f"{self.observed_mated_non_matches} != {self.observed_mated_scored}"
            )
        total_attempts = self.observed_mated_attempts + self.observed_impostor_attempts
        if total_attempts != len(self.pair_ids):
            raise ValueError(
                "the operating point's attempt counts must cover its exact pair_id list: "
                f"{total_attempts} != {len(self.pair_ids)}"
            )
        mated_labels = sum(
            1 for item in self.ground_truth if item is CalibrationPairTruth.MATED
        )
        impostor_labels = sum(
            1
            for item in self.ground_truth
            if item is CalibrationPairTruth.CROSS_SUBJECT_IMPOSTOR
        )
        if mated_labels != self.observed_mated_attempts:
            raise ValueError(
                "observed_mated_attempts does not match the bound ground_truth list"
            )
        if impostor_labels != self.observed_impostor_attempts:
            raise ValueError(
                "observed_impostor_attempts does not match the bound ground_truth list"
            )
        if self.observed_impostor_scored <= 0:
            raise ValueError(
                "an impostor match rate over an empty impostor population is not a "
                "small rate; it is not a rate (docs/adr/0027)"
            )

        # The selection is only meaningful if the boundary satisfies the ceiling
        # it claims to have been selected under.
        if not rate_at_most(
            self.observed_impostor_matches,
            self.observed_impostor_scored,
            self.target_rate_numerator,
            self.target_rate_denominator,
        ):
            raise ValueError(
                f"observed impostor match rate "
                f"{self.observed_impostor_matches}/{self.observed_impostor_scored} "
                f"exceeds the target ceiling {self.target_rate_numerator}/"
                f"{self.target_rate_denominator} this operating point claims"
            )

        commit = str(self.created_source_commit).strip().lower()
        if len(commit) != 40 or not set(commit) <= _HEX:
            raise ValueError(
                "created_source_commit must be a full 40-character commit SHA"
            )
        object.__setattr__(self, "created_source_commit", commit)
        object.__setattr__(
            self,
            "created_source_tree_clean",
            require_exact_bool(
                self.created_source_tree_clean, "created_source_tree_clean"
            ),
        )

        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        recomputed = calibration_operating_point_fingerprint(self)
        if self.operating_point_fingerprint != recomputed:
            raise ValueError(
                "operating_point_fingerprint does not cover this operating point"
            )
        expected = operating_point_id(self.operating_point_fingerprint)
        if self.operating_point_id != expected:
            raise ValueError(
                f"operating_point_id must be derived from the fingerprint: expected "
                f"{expected}, got {self.operating_point_id!r}"
            )

    @property
    def threshold_value(self) -> Decimal:
        return Decimal(self.threshold)

    @property
    def target_rate(self) -> ExactRate:
        return ExactRate(
            numerator=self.target_rate_numerator,
            denominator=self.target_rate_denominator,
        )


def calibration_operating_point_fingerprint(
    point: CalibrationOperatingPoint | Mapping[str, Any],
) -> str:
    """Derive the identity without its own identity, its id, or a wall clock."""
    plain = dict(to_plain(point))
    plain.pop("operating_point_fingerprint", None)
    plain.pop("operating_point_id", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "calibration_operating_point_v2", "operating_point": plain},
        length=64,
    )


def operating_point_id(fingerprint: str) -> str:
    """``oppoint_<12 chars of the operating-point fingerprint>``."""
    digest = require_digest(fingerprint, "operating_point_fingerprint")
    return f"oppoint_{digest[:OPERATING_POINT_ID_LENGTH]}"


#: Re-exported so a caller that only imports this module can still say what a
#: labelled comparison is, without reaching into the enums directly.
PairTruth = CalibrationPairTruth


# ------------------------------------------------------------ strict reading
#
# Turning a stored document back into one of the artifacts above, and refusing
# everything ambiguous on the way. It lives in ``core`` rather than in
# :mod:`fpbench.calibration` for the same reason the containers do: the storage
# layer has to reconstruct them, and ``storage`` may import only ``core``.
# :mod:`fpbench.calibration.models` re-exports every name below, so a caller
# working with the engine still imports model and reader from one place.
#
# There is no lenient path, no coercion and no default:
#
# * an unknown key is refused, because a key nothing reads is a claim nothing
#   checks;
# * a missing key is refused, because the default somebody would have chosen is
#   exactly the thing that should have been written down;
# * a duplicate JSON key is refused, because ``json`` silently keeps the last one
#   and the two documents would fingerprint identically;
# * ``NaN`` and ``Infinity`` are refused;
# * a JSON number with a fractional part is refused outright — a score and a
#   threshold are written as *strings* and read as ``Decimal``, so that no value
#   in this layer ever passes through binary floating point;
# * ``true`` is not ``1`` and ``1`` is not ``"1"``;
# * an enum spelling this project does not know is refused rather than guessed at.

class _DuplicateJsonKey(ValueError):
    """A JSON object carried the same key twice."""


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateJsonKey(
                f"duplicate JSON key {key!r}; the parser would keep the last one "
                "and the two documents would be indistinguishable afterwards"
            )
        seen[key] = value
    return seen


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a value a calibration document may carry")


def _reject_fractional_literal(literal: str) -> Any:
    raise ValueError(
        f"the JSON number {literal!r} has a fractional part; a score, a threshold "
        "and a rate are written as strings and integers in this package, so that "
        "nothing here is ever a binary floating-point value (docs/adr/0080)"
    )


def strict_json_document(text: str) -> Mapping[str, Any]:
    """Parse one calibration document, refusing everything ambiguous.

    Raises:
        ValueError: the text is not JSON, is not an object at the top level,
            carries a duplicate key, a fractional number, ``NaN`` or an infinity.
    """
    try:
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_fractional_literal,
            parse_constant=_reject_constant,
        )
    except _DuplicateJsonKey:
        raise
    except json.JSONDecodeError as exc:
        raise ValueError(f"not a readable JSON document: {exc}") from None
    if not isinstance(document, dict):
        raise ValueError("a calibration document is a JSON object at the top level")
    return document


def require_exact_keys(
    document: Mapping[str, Any], expected: Iterable[str], *, what: str
) -> None:
    """Exactly these keys: no more, no fewer.

    Both halves matter. A missing key would be filled in with a default nobody
    wrote down; an unknown key is a claim the reader does not check and the writer
    believes was honoured.
    """
    wanted = set(expected)
    present = set(map(str, document))
    missing = sorted(wanted - present)
    if missing:
        raise ValueError(f"{what} is missing {missing}")
    unknown = sorted(present - wanted)
    if unknown:
        raise ValueError(
            f"{what} carries keys nothing reads: {unknown}; an unrecognised key is "
            "refused rather than ignored"
        )


def read_str(document: Mapping[str, Any], key: str) -> str:
    value = document[key]
    if type(value) is not str:
        raise ValueError(f"{key} must be a string, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{key} must not be empty")
    return text


def read_int(document: Mapping[str, Any], key: str) -> int:
    """An exact integer. ``true`` is not ``1`` and ``"1"`` is not ``1``."""
    return require_exact_int(document[key], key)


def read_bool(document: Mapping[str, Any], key: str) -> bool:
    return require_exact_bool(document[key], key)


def read_digest(document: Mapping[str, Any], key: str) -> str:
    value = document[key]
    if type(value) is not str:
        raise ValueError(f"{key} must be a string, got {type(value).__name__}")
    return require_digest(value, key)


def read_enum(document: Mapping[str, Any], key: str, enum: Any) -> Any:
    """One of this project's spellings, or a refusal naming the ones it knows."""
    value = document[key]
    if type(value) is not str:
        raise ValueError(f"{key} must be a string, got {type(value).__name__}")
    try:
        return enum(value)
    except ValueError:
        known = ", ".join(sorted(member.value for member in enum))
        raise ValueError(
            f"{key} is {value!r}, which is not one of: {known}. An unknown "
            "vocabulary member is refused rather than guessed at"
        ) from None


def read_decimal_text(document: Mapping[str, Any], key: str) -> Decimal:
    """A decimal written as a string, read exactly.

    A JSON number would already have been refused by the parser. This is the
    positive half: the value is a string, and it becomes a ``Decimal`` built from
    that string's own digits rather than from a double.
    """
    value = document[key]
    if type(value) is not str:
        raise ValueError(
            f"{key} must be a decimal written as a string, got "
            f"{type(value).__name__}"
        )
    return require_finite_decimal(value, key)


def require_finite_decimal(value: object, field_name: str) -> Decimal:
    """An exact, finite ``Decimal``, refusing a ``float`` outright.

    A ``float`` is refused even though it would convert: the conversion is where
    ``0.1`` stops being one tenth, and a development score that arrived as a
    double has already lost whatever the algorithm actually produced
    (docs/adr/0073).
    """
    if isinstance(value, bool) or type(value) is float:
        raise ValueError(
            f"{field_name} must be a Decimal or a decimal string, never a "
            f"{type(value).__name__}"
        )
    if isinstance(value, Decimal):
        number = value
    else:
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, ArithmeticError):
            raise ValueError(f"{field_name} is not a decimal number: {value!r}") from None
    if not number.is_finite():
        raise ValueError(
            f"{field_name} must be finite; NaN and infinities divide nothing into "
            "matches and non-matches"
        )
    return number


# ------------------------------------------------- documents into artifacts


_PROTOCOL_KEYS = (
    "schema_version",
    "protocol_id",
    "protocol_version",
    "target_metric",
    "target_rate_numerator",
    "target_rate_denominator",
    "target_population",
    "threshold_selection_rule",
    "candidate_boundary_policy",
    "tie_policy",
    "score_population_policy",
    "failure_policy",
    "requires_cross_subject_impostors",
    "requires_development_role",
    "quality_filtering",
    "normalization",
    "metadata",
    "protocol_fingerprint",
)

_BINDING_KEYS = (
    "schema_version",
    "binding_id",
    "algorithm_id",
    "algorithm_fingerprint",
    "integration_id",
    "integration_fingerprint",
    "run_id",
    "run_fingerprint",
    "result_set_id",
    "result_set_fingerprint",
    "labeled_results_hash",
    "pair_ids",
    "ground_truth",
    "dataset_id",
    "dataset_fingerprint",
    "cohort_id",
    "cohort_fingerprint",
    "cohort_role",
    "pair_manifest_id",
    "pair_manifest_fingerprint",
    "score_direction",
    "metadata",
    "source_binding_fingerprint",
)

_REGISTRY_KEYS = (
    "schema_version",
    "registry_id",
    "registry_version",
    "entries",
    "registry_fingerprint",
)
_REGISTRY_ENTRY_KEYS = ("kind", "identity", "fingerprint", "label")

_OPERATING_POINT_KEYS = (
    "schema_version",
    "operating_point_id",
    "operating_point_fingerprint",
    "calibration_protocol_fingerprint",
    "source_binding_fingerprint",
    "labeled_results_hash",
    "pair_ids",
    "ground_truth",
    "algorithm_id",
    "algorithm_fingerprint",
    "threshold",
    "comparator",
    "score_direction",
    "target_rate_numerator",
    "target_rate_denominator",
    "observed_impostor_matches",
    "observed_impostor_scored",
    "observed_impostor_attempts",
    "impostor_failures",
    "observed_mated_matches",
    "observed_mated_non_matches",
    "observed_mated_scored",
    "observed_mated_attempts",
    "mated_failures",
    "selection_rule",
    "tie_policy",
    "created_source_commit",
    "created_source_tree_clean",
    "created_utc",
)


def _read_metadata(document: Mapping[str, Any], what: str) -> Mapping[str, str]:
    value = document["metadata"]
    if not isinstance(value, dict):
        raise ValueError(f"{what}: metadata must be a JSON object")
    for key, item in value.items():
        if type(item) is not str:
            raise ValueError(
                f"{what}: metadata[{key!r}] must be a string; a structured value "
                "there would be a claim outside the schema"
            )
    return {str(key): str(item) for key, item in value.items()}


def _read_string_array(
    document: Mapping[str, Any], field_name: str, *, what: str
) -> tuple[str, ...]:
    value = document[field_name]
    if not isinstance(value, list):
        raise ValueError(f"{what}: {field_name} must be a JSON array")
    result: list[str] = []
    for index, item in enumerate(value):
        if type(item) is not str or not item.strip():
            raise ValueError(
                f"{what}: {field_name}[{index}] must be a non-empty string"
            )
        result.append(item.strip())
    return tuple(result)


def _read_truth_array(
    document: Mapping[str, Any], field_name: str, *, what: str
) -> tuple[CalibrationPairTruth, ...]:
    values = _read_string_array(document, field_name, what=what)
    try:
        return tuple(CalibrationPairTruth(value) for value in values)
    except ValueError as exc:
        raise ValueError(f"{what}: {field_name} contains an unknown ground truth") from exc


def read_calibration_protocol(document: Mapping[str, Any]) -> CalibrationProtocol:
    """Build a protocol from a strictly parsed document, or refuse it."""
    from fpbench.core.enums import (
        CalibrationFailurePolicy,
        CalibrationTargetMetric,
        CalibrationTargetPopulation,
        CalibrationTiePolicy,
        CandidateBoundaryPolicy,
        ScoreNormalizationPolicy,
        ScorePopulationPolicy,
        ThresholdSelectionRule,
    )

    try:
        require_exact_keys(document, _PROTOCOL_KEYS, what="a calibration protocol")
        version = read_str(document, "schema_version")
        if version != CALIBRATION_PROTOCOL_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported calibration-protocol schema version {version!r}"
            )
        return CalibrationProtocol(
            schema_version=version,
            protocol_id=read_str(document, "protocol_id"),
            protocol_version=read_str(document, "protocol_version"),
            target_metric=read_enum(document, "target_metric", CalibrationTargetMetric),
            target_rate_numerator=read_int(document, "target_rate_numerator"),
            target_rate_denominator=read_int(document, "target_rate_denominator"),
            target_population=read_enum(
                document, "target_population", CalibrationTargetPopulation
            ),
            threshold_selection_rule=read_enum(
                document, "threshold_selection_rule", ThresholdSelectionRule
            ),
            candidate_boundary_policy=read_enum(
                document, "candidate_boundary_policy", CandidateBoundaryPolicy
            ),
            tie_policy=read_enum(document, "tie_policy", CalibrationTiePolicy),
            score_population_policy=read_enum(
                document, "score_population_policy", ScorePopulationPolicy
            ),
            failure_policy=read_enum(
                document, "failure_policy", CalibrationFailurePolicy
            ),
            requires_cross_subject_impostors=read_bool(
                document, "requires_cross_subject_impostors"
            ),
            requires_development_role=read_bool(document, "requires_development_role"),
            quality_filtering=read_bool(document, "quality_filtering"),
            normalization=read_enum(document, "normalization", ScoreNormalizationPolicy),
            metadata=_read_metadata(document, "a calibration protocol"),
            protocol_fingerprint=read_digest(document, "protocol_fingerprint"),
        )
    except CalibrationProtocolError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationProtocolError(f"malformed calibration protocol: {exc}") from None


def read_calibration_source_binding(
    document: Mapping[str, Any],
) -> CalibrationSourceBinding:
    """Build a source binding from a strictly parsed document, or refuse it."""
    from fpbench.core.enums import CohortRole

    try:
        require_exact_keys(document, _BINDING_KEYS, what="a calibration source binding")
        version = read_str(document, "schema_version")
        if version != CALIBRATION_SOURCE_BINDING_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported calibration source-binding schema version {version!r}"
            )
        return CalibrationSourceBinding(
            schema_version=version,
            binding_id=read_str(document, "binding_id"),
            algorithm_id=read_str(document, "algorithm_id"),
            algorithm_fingerprint=read_digest(document, "algorithm_fingerprint"),
            integration_id=read_str(document, "integration_id"),
            integration_fingerprint=read_digest(document, "integration_fingerprint"),
            run_id=read_str(document, "run_id"),
            run_fingerprint=read_digest(document, "run_fingerprint"),
            result_set_id=read_str(document, "result_set_id"),
            result_set_fingerprint=read_digest(document, "result_set_fingerprint"),
            labeled_results_hash=read_digest(document, "labeled_results_hash"),
            pair_ids=_read_string_array(
                document, "pair_ids", what="a calibration source binding"
            ),
            ground_truth=_read_truth_array(
                document, "ground_truth", what="a calibration source binding"
            ),
            dataset_id=read_str(document, "dataset_id"),
            dataset_fingerprint=read_digest(document, "dataset_fingerprint"),
            cohort_id=read_str(document, "cohort_id"),
            cohort_fingerprint=read_digest(document, "cohort_fingerprint"),
            cohort_role=read_enum(document, "cohort_role", CohortRole),
            pair_manifest_id=read_str(document, "pair_manifest_id"),
            pair_manifest_fingerprint=read_digest(document, "pair_manifest_fingerprint"),
            score_direction=read_enum(document, "score_direction", ScoreDirection),
            metadata=_read_metadata(document, "a calibration source binding"),
            source_binding_fingerprint=read_digest(
                document, "source_binding_fingerprint"
            ),
        )
    except CalibrationSourceError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationSourceError(
            f"malformed calibration source binding: {exc}"
        ) from None


def read_protected_evaluation_registry(
    document: Mapping[str, Any],
) -> ProtectedEvaluationRegistry:
    """Build the protected registry from a strictly parsed document."""
    from fpbench.core.enums import ProtectedIdentityKind

    try:
        require_exact_keys(
            document, _REGISTRY_KEYS, what="a protected evaluation registry"
        )
        version = read_str(document, "schema_version")
        if version != PROTECTED_REGISTRY_SCHEMA_VERSION:
            raise ValueError(f"unsupported protected-registry schema version {version!r}")
        raw_entries = document["entries"]
        if not isinstance(raw_entries, list):
            raise ValueError("entries must be a JSON array")
        entries = []
        for index, item in enumerate(raw_entries):
            if not isinstance(item, dict):
                raise ValueError(f"entries[{index}] must be a JSON object")
            require_exact_keys(
                item, _REGISTRY_ENTRY_KEYS, what=f"protected identity {index}"
            )
            entries.append(
                ProtectedEvaluationIdentity(
                    kind=read_enum(item, "kind", ProtectedIdentityKind),
                    identity=read_str(item, "identity"),
                    fingerprint=read_digest(item, "fingerprint"),
                    label=read_str(item, "label"),
                )
            )
        return ProtectedEvaluationRegistry(
            schema_version=version,
            registry_id=read_str(document, "registry_id"),
            registry_version=read_str(document, "registry_version"),
            entries=tuple(entries),
            registry_fingerprint=read_digest(document, "registry_fingerprint"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationSourceError(
            f"malformed protected evaluation registry: {exc}"
        ) from None


def read_calibration_operating_point(
    document: Mapping[str, Any],
) -> CalibrationOperatingPoint:
    """Build an operating point from a strictly parsed document, or refuse it."""
    from fpbench.core.enums import CalibrationTiePolicy, ThresholdSelectionRule

    try:
        require_exact_keys(
            document, _OPERATING_POINT_KEYS, what="a calibration operating point"
        )
        version = read_str(document, "schema_version")
        if version != CALIBRATION_OPERATING_POINT_SCHEMA_VERSION:
            raise ValueError(f"unsupported operating-point schema version {version!r}")
        # Read as text and hand the text on: the model canonicalises it, and a
        # Decimal built from the document's own digits is the only kind that
        # cannot have been rounded on the way in.
        threshold = read_decimal_text(document, "threshold")
        return CalibrationOperatingPoint(
            schema_version=version,
            operating_point_id=read_str(document, "operating_point_id"),
            operating_point_fingerprint=read_digest(
                document, "operating_point_fingerprint"
            ),
            calibration_protocol_fingerprint=read_digest(
                document, "calibration_protocol_fingerprint"
            ),
            source_binding_fingerprint=read_digest(
                document, "source_binding_fingerprint"
            ),
            labeled_results_hash=read_digest(document, "labeled_results_hash"),
            pair_ids=_read_string_array(
                document, "pair_ids", what="a calibration operating point"
            ),
            ground_truth=_read_truth_array(
                document, "ground_truth", what="a calibration operating point"
            ),
            algorithm_id=read_str(document, "algorithm_id"),
            algorithm_fingerprint=read_digest(document, "algorithm_fingerprint"),
            threshold=threshold,
            comparator=read_enum(document, "comparator", ThresholdComparator),
            score_direction=read_enum(document, "score_direction", ScoreDirection),
            target_rate_numerator=read_int(document, "target_rate_numerator"),
            target_rate_denominator=read_int(document, "target_rate_denominator"),
            observed_impostor_matches=read_int(document, "observed_impostor_matches"),
            observed_impostor_scored=read_int(document, "observed_impostor_scored"),
            observed_impostor_attempts=read_int(document, "observed_impostor_attempts"),
            impostor_failures=read_int(document, "impostor_failures"),
            observed_mated_matches=read_int(document, "observed_mated_matches"),
            observed_mated_non_matches=read_int(document, "observed_mated_non_matches"),
            observed_mated_scored=read_int(document, "observed_mated_scored"),
            observed_mated_attempts=read_int(document, "observed_mated_attempts"),
            mated_failures=read_int(document, "mated_failures"),
            selection_rule=read_enum(document, "selection_rule", ThresholdSelectionRule),
            tie_policy=read_enum(document, "tie_policy", CalibrationTiePolicy),
            created_source_commit=read_str(document, "created_source_commit"),
            created_source_tree_clean=read_bool(document, "created_source_tree_clean"),
            created_utc=read_str(document, "created_utc"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationInputError(
            f"malformed calibration operating point: {exc}"
        ) from None
