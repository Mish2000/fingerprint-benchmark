"""Proving two runs were given the same inputs, row by row.

Stage 7C runs a second algorithm over the comparisons the first one already ran.
The whole value of that depends on one sentence being literally true: *the same
6,000 pairs, in the same order, over the same 3,000 prepared images*. Nothing
about a run's identity says so. Two runs can share a ``pair_manifest_hash`` and
still have been planned from different rows if somebody rebuilt a manifest in
between; two runs can quote the same ``preparation_set_id`` and still have opened
different bytes if the set was re-materialised.

So the sentence is checked rather than asserted, and it is checked by comparing
records — not by comparing counts. A reference plan of 6,000 and a candidate plan
of 6,000 tells you nothing at all; what tells you something is that position
*i* of both sequences names the same pair, and that the pair with that id has the
same release, the same stage, the same ground truth and the same two images on
both sides (spec section 6).

Three comparisons, three counts, three digests:

``pair ids``
    Positional. Position 4,217 must hold the same ``pair_id`` in both. Order is
    part of the claim, because a plan whose order changed is a different plan
    (docs/adr/0011) and because a resumed run walks the plan in order.

``pair semantics``
    Per id: ``release``, ``protocol_stage``, ``ground_truth``,
    ``left_image_id``, ``right_image_id``. Left stays probe and right stays
    gallery, so swapping them is a different experiment and is caught here.

``prepared entries``
    Per image id: the source digest, the prepared file's digest, the pixel
    digest, the output geometry, the output resolution, the transform action and
    the entry fingerprint (spec section 8).

Nothing in this module reads a score. It reads two plans, two pair manifests and
two prepared-entry indexes, and it is deliberately ignorant of which algorithms
produced them — an alignment between two SourceAFIS runs would use exactly this
code (spec section 41, docs/adr/0051).

**On the expected counts.** :attr:`CanonicalRunAlignmentReport.is_clean` is true
when every comparison came out equal, every side is the size it was expected to
be, and no issue was raised. The expected sizes arrive through
:class:`AlignmentExpectations` rather than being hard-coded into ``is_clean``,
whose default is exactly the SD300 shape — 6,000 pairs, 3,000 prepared images,
500 pairs in every release-and-stage cell. For the Stage 7C report that makes
``is_clean`` precisely the condition spec section 10 states; parameterising it is
what lets the same code be exercised by a fifty-pair synthetic world instead of
only ever by the run it was written for (spec section 43).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from fpbench.core.enums import IntegrityIssueCode, IntegritySeverity, ProtocolStage
from fpbench.core.errors import ResearchPreflightError, StorageError
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.imaging_models import PreparedImageEntry
from fpbench.core.models import ComparisonPair, ImageRecord
from fpbench.core.research_models import ResearchRunState
from fpbench.core.result_models import RunDefinition
from fpbench.core.run_state_models import IntegrityIssue
from fpbench.core.serialization import stable_hash
from fpbench.execution.planner import canonical_pair_order
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore

__all__ = [
    "AlignmentExpectations",
    "AlignmentSide",
    "CanonicalRunAlignmentReport",
    "ReferenceRunIdentity",
    "SD300_CANONICAL_EXPECTATIONS",
    "build_canonical_run_alignment_report",
    "canonical_run_alignment_fingerprint",
    "load_candidate_alignment_side",
    "load_reference_alignment_side",
    "require_canonical_input_controls_equal",
    "require_clean_alignment",
    "require_execution_controls_equal",
    "pair_semantics_row",
    "prepared_entry_row",
]


# --------------------------------------------------------------- expectations


@dataclass(frozen=True, slots=True)
class AlignmentExpectations:
    """How big each side has to be for the alignment to mean what it claims.

    Separate from the equality checks because they answer different questions.
    Equality says the two runs were handed the same thing; these say the thing
    was the whole experiment rather than a fragment of it that happens to match.
    """

    pair_count: int
    prepared_entry_count: int
    pairs_per_release_stage: int
    prepared_entries_per_release: int
    releases: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "pair_count",
            "prepared_entry_count",
            "pairs_per_release_stage",
            "prepared_entries_per_release",
        ):
            value = int(getattr(self, name))
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        releases = tuple(str(item) for item in self.releases)
        if not releases or len(set(releases)) != len(releases):
            raise ValueError("releases must be a non-empty list of distinct names")
        object.__setattr__(self, "releases", releases)

        expected_pairs = (
            self.pairs_per_release_stage * len(releases) * len(ProtocolStage)
        )
        if expected_pairs != self.pair_count:
            raise ValueError(
                f"{self.pairs_per_release_stage} pairs in each of "
                f"{len(releases)} releases x {len(ProtocolStage)} stages is "
                f"{expected_pairs}, not {self.pair_count}"
            )
        expected_entries = self.prepared_entries_per_release * len(releases)
        if expected_entries != self.prepared_entry_count:
            raise ValueError(
                f"{self.prepared_entries_per_release} images in each of "
                f"{len(releases)} releases is {expected_entries}, not "
                f"{self.prepared_entry_count}"
            )


#: The shape of the canonical SD300 experiment. 500 comparisons in every one of
#: the twelve release-and-stage cells, 1,000 prepared images per release
#: (spec sections 4 and 8).
SD300_CANONICAL_EXPECTATIONS = AlignmentExpectations(
    pair_count=6000,
    prepared_entry_count=3000,
    pairs_per_release_stage=500,
    prepared_entries_per_release=1000,
    releases=("SD300A", "SD300B", "SD300C"),
)


# ------------------------------------------------------------------- the sides


@dataclass(frozen=True, slots=True)
class ReferenceRunIdentity:
    """The exact chain the candidate is required to be aligned against.

    Written down as three identifiers rather than resolved by search. "The most
    recent finished run" would silently move the reference the day a second one
    exists, and every number in the study would then be attributed to whichever
    run happened to be newest (spec section 3).
    """

    run_id: str
    plan_id: str
    result_set_id: str

    preparation_set_id: str
    preparation_set_fingerprint: str


@dataclass(frozen=True, slots=True)
class AlignmentSide:
    """One run's inputs, read from that run's own manifests.

    ``run_id`` and ``plan_id`` are optional because the candidate side exists
    before the candidate run does: preparation checks the alignment *first* and
    only then creates a run, so that a misaligned experiment never acquires an
    identity at all (spec section 24).
    """

    label: str

    run_id: str | None
    plan_id: str | None
    result_set_id: str | None

    protocol_id: str
    cohort_id: str
    pair_manifest_hash: str

    preparation_set_id: str
    preparation_set_fingerprint: str

    #: Pair ids in execution order — the plan's order when there is a plan, and
    #: the order the planner will impose when there is not.
    pair_sequence: tuple[str, ...]
    pairs: Mapping[str, ComparisonPair]

    prepared_entries: Mapping[str, PreparedImageEntry]
    image_releases: Mapping[str, str]

    #: Only meaningful for a reference side. ``None`` means "not asked".
    research_ready: bool | None = None
    research_status: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pair_sequence", tuple(str(item) for item in self.pair_sequence)
        )
        object.__setattr__(
            self,
            "pairs",
            MappingProxyType({str(k): v for k, v in dict(self.pairs).items()}),
        )
        object.__setattr__(
            self,
            "prepared_entries",
            MappingProxyType(
                {str(k): v for k, v in dict(self.prepared_entries).items()}
            ),
        )
        object.__setattr__(
            self,
            "image_releases",
            MappingProxyType(
                {str(k): str(v) for k, v in dict(self.image_releases).items()}
            ),
        )


# -------------------------------------------------------------------- the rows


def pair_semantics_row(pair: ComparisonPair) -> dict[str, str]:
    """Everything about a pair that two runs must agree on.

    Deliberately not the whole object: ``dataset_id`` is covered by the protocol
    and cohort identity, and adding a field here would silently weaken every
    stored ``pair_semantics_sha256``, so the list is written out rather than
    derived by reflection (spec section 6).
    """
    return {
        "pair_id": str(pair.pair_id),
        "release": pair.release,
        "protocol_stage": pair.protocol_stage.value,
        "ground_truth": pair.ground_truth.value,
        "left_image_id": str(pair.left_image_id),
        "right_image_id": str(pair.right_image_id),
    }


def prepared_entry_row(entry: PreparedImageEntry, release: str) -> dict[str, str]:
    """Everything about a prepared image that two runs must agree on.

    ``release`` comes from the image manifest rather than from the entry, which
    does not carry one: an entry describes a transformation, and which delivery
    the source arrived in is a fact about the dataset (spec section 8).
    """
    return {
        "image_id": str(entry.image_id),
        "release": str(release),
        "source_sha256": entry.source_expected_sha256,
        "prepared_sha256": entry.output_encoded_sha256,
        "pixel_sha256": entry.output_pixel_sha256,
        "output_width": str(entry.output_width),
        "output_height": str(entry.output_height),
        "output_ppi": str(entry.output_effective_ppi),
        "transform_action": entry.transform_action,
        "entry_hash": entry.entry_hash,
    }


# ------------------------------------------------------------------ the report


@dataclass(frozen=True, slots=True)
class CanonicalRunAlignmentReport:
    """What a row-by-row comparison of two runs' inputs found.

    Canonical: every field reaches :attr:`alignment_fingerprint`, which is
    recomputed in ``__post_init__`` from the fields themselves. A stored report
    whose counts were edited no longer fingerprints to what it carries, and a
    stored report whose fingerprint was edited to match no longer equals the one
    re-derived from the sources — which is the pair of checks
    ``inspect_nbis_canonical500_experiment`` performs (spec sections 9 and 37).

    There is no timestamp inside the fingerprint. ``inspected_utc`` is reported
    beside it and excluded, so the same workspace compared twice produces the
    same digest (spec section 42).
    """

    reference_run_id: str
    reference_plan_id: str
    reference_result_set_id: str

    candidate_run_id: str | None
    candidate_plan_id: str | None

    pair_manifest_hash: str
    preparation_set_id: str
    preparation_set_fingerprint: str

    reference_pair_count: int
    candidate_pair_count: int
    equal_pair_ids: int
    equal_pair_semantics: int

    reference_prepared_entries: int
    candidate_prepared_entries: int
    equal_prepared_entries: int

    pair_id_sequence_sha256: str
    pair_semantics_sha256: str
    prepared_entries_sha256: str

    issues: tuple[IntegrityIssue, ...]
    alignment_fingerprint: str

    #: Excluded from the fingerprint on purpose; see the class docstring.
    inspected_utc: str = ""

    #: The complete shape the comparison was carried out against. This is a
    #: claim, not caller context: changing the expected population changes what
    #: ``is_clean`` means and therefore must change the report fingerprint.
    expectations: AlignmentExpectations = SD300_CANONICAL_EXPECTATIONS

    def __post_init__(self) -> None:
        for name in (
            "reference_pair_count",
            "candidate_pair_count",
            "equal_pair_ids",
            "equal_pair_semantics",
            "reference_prepared_entries",
            "candidate_prepared_entries",
            "equal_prepared_entries",
        ):
            value = int(getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "issues", tuple(self.issues))

        expected = canonical_run_alignment_fingerprint(
            reference_run_id=self.reference_run_id,
            reference_plan_id=self.reference_plan_id,
            reference_result_set_id=self.reference_result_set_id,
            candidate_run_id=self.candidate_run_id,
            candidate_plan_id=self.candidate_plan_id,
            pair_manifest_hash=self.pair_manifest_hash,
            preparation_set_id=self.preparation_set_id,
            preparation_set_fingerprint=self.preparation_set_fingerprint,
            reference_pair_count=self.reference_pair_count,
            candidate_pair_count=self.candidate_pair_count,
            equal_pair_ids=self.equal_pair_ids,
            equal_pair_semantics=self.equal_pair_semantics,
            reference_prepared_entries=self.reference_prepared_entries,
            candidate_prepared_entries=self.candidate_prepared_entries,
            equal_prepared_entries=self.equal_prepared_entries,
            pair_id_sequence_sha256=self.pair_id_sequence_sha256,
            pair_semantics_sha256=self.pair_semantics_sha256,
            prepared_entries_sha256=self.prepared_entries_sha256,
            issues=self.issues,
            expectations=self.expectations,
        )
        if self.alignment_fingerprint != expected:
            raise ValueError(
                "alignment_fingerprint does not cover this report: expected "
                f"{expected}, got {self.alignment_fingerprint}"
            )

    @property
    def is_clean(self) -> bool:
        """True only when every row matched and the sides were the right size.

        An alignment of 5,999 of 6,000 pairs is a failure, not a near miss: the
        one row that differs is the one whose result could not be attributed,
        and there is no honest way to publish the other 5,999 as "the same
        comparisons" (spec section 10).
        """
        pairs = self.expectations.pair_count
        entries = self.expectations.prepared_entry_count
        return (
            self.reference_pair_count == pairs
            and self.candidate_pair_count == pairs
            and self.equal_pair_ids == pairs
            and self.equal_pair_semantics == pairs
            and self.reference_prepared_entries == entries
            and self.candidate_prepared_entries == entries
            and self.equal_prepared_entries == entries
            and not self.issues
        )

    @property
    def errors(self) -> tuple[IntegrityIssue, ...]:
        return tuple(
            issue for issue in self.issues if issue.severity is IntegritySeverity.ERROR
        )

    def summary(self) -> str:
        """One line, for a CLI and for a failure message."""
        return (
            f"pairs {self.equal_pair_ids}/{self.reference_pair_count} ids, "
            f"{self.equal_pair_semantics}/{self.reference_pair_count} semantics; "
            f"prepared {self.equal_prepared_entries}/"
            f"{self.reference_prepared_entries}; issues {len(self.issues)}"
        )


def canonical_run_alignment_fingerprint(
    *,
    reference_run_id: str,
    reference_plan_id: str,
    reference_result_set_id: str,
    candidate_run_id: str | None,
    candidate_plan_id: str | None,
    pair_manifest_hash: str,
    preparation_set_id: str,
    preparation_set_fingerprint: str,
    reference_pair_count: int,
    candidate_pair_count: int,
    equal_pair_ids: int,
    equal_pair_semantics: int,
    reference_prepared_entries: int,
    candidate_prepared_entries: int,
    equal_prepared_entries: int,
    pair_id_sequence_sha256: str,
    pair_semantics_sha256: str,
    prepared_entries_sha256: str,
    issues: Sequence[IntegrityIssue],
    expectations: AlignmentExpectations,
) -> str:
    """The digest behind an alignment report, over every field that is a claim.

    Takes the values rather than the record so that the builder can compute the
    digest *before* constructing a frozen report and the report can re-derive it
    afterwards, with one definition between them. A second copy of this mapping
    is exactly how a fingerprint stops covering what it claims to.
    """
    return stable_hash(
        {
            "schema": "canonical_run_alignment_v2",
            "reference": {
                "run_id": reference_run_id,
                "plan_id": reference_plan_id,
                "result_set_id": reference_result_set_id,
            },
            "candidate": {
                "run_id": candidate_run_id,
                "plan_id": candidate_plan_id,
            },
            "inputs": {
                "pair_manifest_hash": pair_manifest_hash,
                "preparation_set_id": preparation_set_id,
                "preparation_set_fingerprint": preparation_set_fingerprint,
            },
            "counts": {
                "reference_pair_count": reference_pair_count,
                "candidate_pair_count": candidate_pair_count,
                "equal_pair_ids": equal_pair_ids,
                "equal_pair_semantics": equal_pair_semantics,
                "reference_prepared_entries": reference_prepared_entries,
                "candidate_prepared_entries": candidate_prepared_entries,
                "equal_prepared_entries": equal_prepared_entries,
            },
            "digests": {
                "pair_id_sequence_sha256": pair_id_sequence_sha256,
                "pair_semantics_sha256": pair_semantics_sha256,
                "prepared_entries_sha256": prepared_entries_sha256,
            },
            "expectations": {
                "pair_count": expectations.pair_count,
                "prepared_entry_count": expectations.prepared_entry_count,
                "pairs_per_release_stage": expectations.pairs_per_release_stage,
                "prepared_entries_per_release": (
                    expectations.prepared_entries_per_release
                ),
                "releases": list(expectations.releases),
            },
            "issues": [
                {
                    "code": issue.code.value,
                    "severity": issue.severity.value,
                    "message": issue.message,
                    "job_id": issue.job_id,
                    "details": dict(issue.details),
                }
                for issue in issues
            ],
        },
        length=64,
    )


# ------------------------------------------------------------------ the check


def build_canonical_run_alignment_report(
    *,
    reference: AlignmentSide,
    candidate: AlignmentSide,
    expected_reference: ReferenceRunIdentity,
    expectations: AlignmentExpectations = SD300_CANONICAL_EXPECTATIONS,
) -> CanonicalRunAlignmentReport:
    """Compare two sides record by record and say exactly what differs.

    Never raises for a misalignment: the report *is* the answer, and a caller
    that wants a misalignment to stop the world calls
    :func:`require_clean_alignment` on it. That split is the same one
    :class:`~fpbench.core.run_state_models.RunAuditReport` makes, and for the
    same reason — a diagnostic that raises cannot be printed.
    """
    issues: list[IntegrityIssue] = []

    issues.extend(_check_reference_identity(reference, expected_reference))
    issues.extend(_check_shared_provenance(reference, candidate, expected_reference))

    equal_pair_ids = _compare_pair_sequences(reference, candidate, issues)
    equal_pair_semantics = _compare_pair_semantics(reference, candidate, issues)
    equal_prepared = _compare_prepared_entries(reference, candidate, issues)

    issues.extend(_check_shape(reference, expectations))
    issues.extend(_check_shape(candidate, expectations))

    fields = {
        "reference_run_id": str(reference.run_id or expected_reference.run_id),
        "reference_plan_id": str(reference.plan_id or expected_reference.plan_id),
        "reference_result_set_id": str(
            reference.result_set_id or expected_reference.result_set_id
        ),
        "candidate_run_id": candidate.run_id,
        "candidate_plan_id": candidate.plan_id,
        "pair_manifest_hash": reference.pair_manifest_hash,
        "preparation_set_id": reference.preparation_set_id,
        "preparation_set_fingerprint": reference.preparation_set_fingerprint,
        "reference_pair_count": len(reference.pair_sequence),
        "candidate_pair_count": len(candidate.pair_sequence),
        "equal_pair_ids": equal_pair_ids,
        "equal_pair_semantics": equal_pair_semantics,
        "reference_prepared_entries": len(reference.prepared_entries),
        "candidate_prepared_entries": len(candidate.prepared_entries),
        "equal_prepared_entries": equal_prepared,
        "pair_id_sequence_sha256": _sequence_digest(reference.pair_sequence),
        "pair_semantics_sha256": _semantics_digest(reference),
        "prepared_entries_sha256": _entries_digest(reference),
        "issues": tuple(issues),
    }
    return CanonicalRunAlignmentReport(
        **fields,
        alignment_fingerprint=canonical_run_alignment_fingerprint(
            **fields, expectations=expectations
        ),
        inspected_utc=_utc_now(),
        expectations=expectations,
    )


def require_clean_alignment(report: CanonicalRunAlignmentReport) -> None:
    """Stop unless every row of both sides matched.

    Raises:
        ResearchPreflightError: the alignment is not clean. Preflight rather
            than a plain error because this is the same class of refusal as a
            dirty working tree or an unverified dataset: the run is not
            entitled to exist (spec section 24).
    """
    if report.is_clean:
        return
    detail = "; ".join(issue.message for issue in report.issues[:3])
    raise ResearchPreflightError(
        f"the candidate run is not aligned with {report.reference_run_id}: "
        f"{report.summary()}"
        + (f". {detail}" if detail else "")
    )


# --------------------------------------------------------------- the comparisons


def _compare_pair_sequences(
    reference: AlignmentSide,
    candidate: AlignmentSide,
    issues: list[IntegrityIssue],
) -> int:
    """Positional equality of the two ordered pair-id sequences."""
    left = reference.pair_sequence
    right = candidate.pair_sequence

    for side in (reference, candidate):
        duplicates = _duplicates(side.pair_sequence)
        if duplicates:
            issues.append(
                _issue(
                    IntegrityIssueCode.DUPLICATE_PAIR_ID,
                    f"the {side.label} side lists {len(duplicates)} pair id(s) more "
                    f"than once, starting with {sorted(duplicates)[:3]}",
                    side=side.label,
                )
            )

    if len(left) != len(right):
        issues.append(
            _issue(
                IntegrityIssueCode.PLAN_CONFLICT,
                f"the reference side holds {len(left)} pairs and the candidate "
                f"side {len(right)}; a run over a different number of comparisons "
                "is a different experiment",
                reference_pairs=str(len(left)),
                candidate_pairs=str(len(right)),
            )
        )

    missing = sorted(set(left) - set(right))
    extra = sorted(set(right) - set(left))
    if missing:
        issues.append(
            _issue(
                IntegrityIssueCode.PAIR_ID_MISMATCH,
                f"{len(missing)} pair id(s) of the reference run are absent from "
                f"the candidate, starting with {missing[:3]}",
                missing=str(len(missing)),
            )
        )
    if extra:
        issues.append(
            _issue(
                IntegrityIssueCode.PAIR_ID_MISMATCH,
                f"the candidate holds {len(extra)} pair id(s) the reference run "
                f"never compared, starting with {extra[:3]}",
                extra=str(len(extra)),
            )
        )

    equal = sum(1 for a, b in zip(left, right) if a == b)
    if equal != len(left) or len(left) != len(right):
        first = next(
            (
                index
                for index, (a, b) in enumerate(zip(left, right))
                if a != b
            ),
            min(len(left), len(right)),
        )
        issues.append(
            _issue(
                IntegrityIssueCode.PLAN_CONFLICT,
                f"the two pair-id sequences first differ at position {first}; the "
                "order a run walks its plan in is part of the plan "
                "(docs/adr/0011)",
                first_difference=str(first),
                equal_positions=str(equal),
            )
        )
    return equal


def _compare_pair_semantics(
    reference: AlignmentSide,
    candidate: AlignmentSide,
    issues: list[IntegrityIssue],
) -> int:
    """Field-by-field equality of every pair both sides name."""
    equal = 0
    differing: list[str] = []
    swapped: list[str] = []

    for pair_id in reference.pair_sequence:
        left = reference.pairs.get(pair_id)
        right = candidate.pairs.get(pair_id)
        if left is None:
            issues.append(
                _issue(
                    IntegrityIssueCode.PAIR_ID_MISMATCH,
                    f"the reference plan names pair {pair_id}, which is not in the "
                    "reference pair manifest",
                    pair_id=pair_id,
                )
            )
            continue
        if right is None:
            differing.append(pair_id)
            continue
        first = pair_semantics_row(left)
        second = pair_semantics_row(right)
        if first == second:
            equal += 1
            continue
        differing.append(pair_id)
        if (
            first["left_image_id"] == second["right_image_id"]
            and first["right_image_id"] == second["left_image_id"]
        ):
            swapped.append(pair_id)

    if swapped:
        issues.append(
            _issue(
                IntegrityIssueCode.IMAGE_IDS_MISMATCH,
                f"{len(swapped)} pair(s) have their two images the other way "
                f"round, starting with {swapped[:3]}; left is the probe and right "
                "is the gallery, and reversing them is a different comparison "
                "(spec section 16)",
                swapped=str(len(swapped)),
            )
        )
    if differing:
        issues.append(
            _issue(
                IntegrityIssueCode.PLAN_CONFLICT,
                f"{len(differing)} pair(s) differ between the two sides in release, "
                f"stage, ground truth or images, starting with {differing[:3]}",
                differing=str(len(differing)),
            )
        )
    return equal


def _compare_prepared_entries(
    reference: AlignmentSide,
    candidate: AlignmentSide,
    issues: list[IntegrityIssue],
) -> int:
    """Field-by-field equality of every prepared artefact both sides name."""
    equal = 0
    differing: list[str] = []

    missing = sorted(set(reference.prepared_entries) - set(candidate.prepared_entries))
    extra = sorted(set(candidate.prepared_entries) - set(reference.prepared_entries))
    if missing:
        issues.append(
            _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"the candidate has no prepared artefact for {len(missing)} image(s) "
                f"the reference run used, starting with {missing[:3]}",
                missing=str(len(missing)),
            )
        )
    if extra:
        issues.append(
            _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"the candidate holds {len(extra)} prepared artefact(s) the "
                f"reference run did not use, starting with {extra[:3]}",
                extra=str(len(extra)),
            )
        )

    for image_id, entry in sorted(reference.prepared_entries.items()):
        other = candidate.prepared_entries.get(image_id)
        if other is None:
            continue
        first = prepared_entry_row(entry, reference.image_releases.get(image_id, ""))
        second = prepared_entry_row(other, candidate.image_releases.get(image_id, ""))
        if first == second:
            equal += 1
            continue
        differing.append(image_id)

    if differing:
        issues.append(
            _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"{len(differing)} prepared image(s) are not the artefact the "
                f"reference run opened, starting with {differing[:3]}; a run over "
                "different pixels is not the same experiment (docs/adr/0031)",
                differing=str(len(differing)),
            )
        )
    return equal


def _check_reference_identity(
    reference: AlignmentSide, expected: ReferenceRunIdentity
) -> Iterable[IntegrityIssue]:
    """The reference really is the run this stage is defined against."""
    for label, actual, wanted in (
        ("run_id", reference.run_id, expected.run_id),
        ("plan_id", reference.plan_id, expected.plan_id),
        ("result_set_id", reference.result_set_id, expected.result_set_id),
        (
            "preparation_set_id",
            reference.preparation_set_id,
            expected.preparation_set_id,
        ),
        (
            "preparation_set_fingerprint",
            reference.preparation_set_fingerprint,
            expected.preparation_set_fingerprint,
        ),
    ):
        if actual is not None and actual != wanted:
            yield _issue(
                IntegrityIssueCode.PLAN_CONFLICT,
                f"the reference chain's {label} is {actual!r}, but this experiment "
                f"is defined against {wanted!r}",
                field=label,
            )

    if reference.research_ready is False:
        yield _issue(
            IntegrityIssueCode.PLAN_CONFLICT,
            f"the reference run {expected.run_id} is "
            f"{reference.research_status or 'not RESEARCH_READY'}; a run may not be "
            "aligned against evidence that has not itself been finalised "
            "(docs/adr/0020)",
            research_status=str(reference.research_status or ""),
        )


def _check_shared_provenance(
    reference: AlignmentSide,
    candidate: AlignmentSide,
    expected: ReferenceRunIdentity,
) -> Iterable[IntegrityIssue]:
    """Both sides came from one protocol, one cohort and one pair manifest."""
    for label, code in (
        ("protocol_id", IntegrityIssueCode.PLAN_CONFLICT),
        ("cohort_id", IntegrityIssueCode.PLAN_CONFLICT),
        ("pair_manifest_hash", IntegrityIssueCode.PAIR_MANIFEST_HASH_MISMATCH),
        ("preparation_set_id", IntegrityIssueCode.RESULT_PIPELINE_MISMATCH),
        (
            "preparation_set_fingerprint",
            IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
        ),
    ):
        first = getattr(reference, label)
        second = getattr(candidate, label)
        if first != second:
            yield _issue(
                code,
                f"the reference side names {label}={_short(first)} and the "
                f"candidate {label}={_short(second)}; the two runs did not share "
                "one set of inputs",
                field=label,
            )

    if candidate.preparation_set_id != expected.preparation_set_id:
        yield _issue(
            IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
            f"the candidate reads prepared set {candidate.preparation_set_id!r}; "
            f"this experiment is defined over {expected.preparation_set_id!r}, and "
            "no new set may be materialised for it (spec section 3)",
            field="preparation_set_id",
        )


def _check_shape(
    side: AlignmentSide, expectations: AlignmentExpectations
) -> Iterable[IntegrityIssue]:
    """Each side is the whole experiment, in every cell of it."""
    if len(side.pair_sequence) != expectations.pair_count:
        yield _issue(
            IntegrityIssueCode.PLAN_CONFLICT,
            f"the {side.label} side holds {len(side.pair_sequence)} pairs, and this "
            f"experiment is exactly {expectations.pair_count}",
            side=side.label,
        )
    if len(side.prepared_entries) != expectations.prepared_entry_count:
        yield _issue(
            IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
            f"the {side.label} side holds {len(side.prepared_entries)} prepared "
            f"images, and this experiment is exactly "
            f"{expectations.prepared_entry_count}",
            side=side.label,
        )

    cells: dict[tuple[str, str], int] = {}
    for pair in side.pairs.values():
        key = (pair.release, pair.protocol_stage.value)
        cells[key] = cells.get(key, 0) + 1
    wrong = sorted(
        f"{release}/{stage}={cells.get((release, stage), 0)}"
        for release in expectations.releases
        for stage in (item.value for item in ProtocolStage)
        if cells.get((release, stage), 0) != expectations.pairs_per_release_stage
    )
    if wrong:
        yield _issue(
            IntegrityIssueCode.PLAN_CONFLICT,
            f"the {side.label} side does not hold "
            f"{expectations.pairs_per_release_stage} pairs in every "
            f"release-and-stage cell: {wrong[:4]}",
            side=side.label,
        )

    per_release: dict[str, int] = {}
    for image_id in side.prepared_entries:
        release = side.image_releases.get(image_id)
        if release is None:
            continue
        per_release[release] = per_release.get(release, 0) + 1
    off = sorted(
        f"{release}={per_release.get(release, 0)}"
        for release in expectations.releases
        if per_release.get(release, 0) != expectations.prepared_entries_per_release
    )
    if off:
        yield _issue(
            IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
            f"the {side.label} side does not hold "
            f"{expectations.prepared_entries_per_release} prepared images in every "
            f"release: {off}",
            side=side.label,
        )


# ------------------------------------------------------- execution controls


def require_execution_controls_equal(
    reference_run: RunDefinition,
    nbis_spec: object,
    *,
    reference_materialization_policy: str | None = None,
) -> None:
    """The candidate run reproduces every execution control of the reference.

    Same timeout, same deterministic seed, same replicate index, same preparer,
    same execution-profile parameters — and therefore the same execution profile
    hash. The permitted differences are the algorithm configuration, the research
    integration, the runtime bundle and the run's identity; anything else would
    mean the second run was carried out under a budget or an input policy the
    first was not, and no amount of matching pair ids would repair that
    (spec section 19).

    ``nbis_spec`` is duck-typed on purpose. It is an
    :class:`~fpbench.experiments.algorithm_research.AlgorithmResearchExperimentSpec`
    in practice, but this function has no business importing the engine to say
    so, and a test double with the same four attributes is a legitimate caller.

    Raises:
        ResearchPreflightError: any execution control differs.
    """
    profile = getattr(nbis_spec, "execution_profile")
    reference_profile = reference_run.execution_profile

    differences: list[str] = []
    for label, first, second in (
        ("profile_id", reference_profile.profile_id, profile.profile_id),
        ("preparer_id", reference_profile.preparer_id, profile.preparer_id),
        (
            "timeout_seconds",
            f"{float(reference_profile.timeout_seconds):.6f}",
            f"{float(profile.timeout_seconds):.6f}",
        ),
        (
            "deterministic_seed",
            str(reference_profile.deterministic_seed),
            str(profile.deterministic_seed),
        ),
        (
            "replicate_index",
            str(reference_run.replicate_index),
            str(getattr(nbis_spec, "replicate_index")),
        ),
    ):
        if first != second:
            differences.append(f"{label}: reference {first!r} vs candidate {second!r}")

    reference_parameters = dict(reference_profile.parameters)
    candidate_parameters = dict(profile.parameters)
    if reference_parameters != candidate_parameters:
        keys = sorted(
            set(reference_parameters) | set(candidate_parameters)
        )
        changed = [
            key
            for key in keys
            if reference_parameters.get(key) != candidate_parameters.get(key)
        ]
        differences.append(f"execution profile parameters differ in {changed}")

    if not getattr(nbis_spec, "research_mode", False):
        differences.append(
            "research_mode: the reference run recorded research provenance and "
            "the candidate declares research_mode=false"
        )
    if not reference_run.environment.runtime.get("fpbench.source.revision"):
        differences.append(
            "the reference run records no fpbench source revision, so it is not a "
            "research run at all (docs/adr/0017)"
        )

    policy = getattr(nbis_spec, "materialization_policy", None)
    if reference_materialization_policy is not None and policy != (
        reference_materialization_policy
    ):
        differences.append(
            f"materialization_policy: reference "
            f"{reference_materialization_policy!r} vs candidate {policy!r}"
        )

    if differences:
        raise ResearchPreflightError(
            "the NBIS run does not reproduce the reference run's execution "
            f"controls: {'; '.join(differences)}"
        )


def require_canonical_input_controls_equal(
    reference_run: RunDefinition,
    candidate_spec: object,
    *,
    reference_materialization_policy: str | None = None,
) -> None:
    """The candidate run opens the reference run's pixels, under its own budget.

    The narrower sibling of :func:`require_execution_controls_equal`, for a
    candidate that cannot reproduce the reference run's *timeout* and must
    reproduce everything else.

    That case is real rather than hypothetical. The canonical execution profile
    gives an adapter 60 seconds per comparison, which was chosen for a Java
    matcher. A route that spends five separately deadlined operations inside one
    job — two preprocess calls, two extractions and one comparison — would have
    its outcome decided by whichever timeout fired first, so it declares its own
    job deadline and reproduces every input control exactly (docs/adr/0074).

    Checked here, and it is the complete list:

    * the preparer, so the same code produced the bytes;
    * every execution-profile parameter that names an input — the input set, its
      fingerprint, the transform profile and its fingerprint, the target
      resolution, the output format;
    * the deterministic seed and the replicate index;
    * research mode, and that the reference is a research run at all;
    * the runtime materialization policy.

    Deliberately *not* checked: ``profile_id`` and ``timeout_seconds``. Those are
    the two the caller is declaring different, and a function that checked them
    anyway would be the strict sibling under another name.

    ``candidate_spec`` is duck-typed on purpose, exactly as its sibling is.

    Raises:
        ResearchPreflightError: any input control differs.
    """
    profile = getattr(candidate_spec, "execution_profile")
    reference_profile = reference_run.execution_profile

    differences: list[str] = []
    if reference_profile.preparer_id != profile.preparer_id:
        differences.append(
            f"preparer_id: reference {reference_profile.preparer_id!r} vs "
            f"candidate {profile.preparer_id!r}"
        )
    for label, first, second in (
        (
            "deterministic_seed",
            str(reference_profile.deterministic_seed),
            str(profile.deterministic_seed),
        ),
        (
            "replicate_index",
            str(reference_run.replicate_index),
            str(getattr(candidate_spec, "replicate_index")),
        ),
    ):
        if first != second:
            differences.append(f"{label}: reference {first!r} vs candidate {second!r}")

    # Every parameter, not a chosen subset. The profile's parameters are exactly
    # the strings its hash is taken over, and any one of them naming a different
    # input set, transform or resolution would mean two runs over two different
    # sets of pixels (docs/adr/0031).
    reference_parameters = dict(reference_profile.parameters)
    candidate_parameters = dict(profile.parameters)
    if reference_parameters != candidate_parameters:
        keys = sorted(set(reference_parameters) | set(candidate_parameters))
        changed = [
            key
            for key in keys
            if reference_parameters.get(key) != candidate_parameters.get(key)
        ]
        differences.append(f"execution profile parameters differ in {changed}")

    if not getattr(candidate_spec, "research_mode", False):
        differences.append(
            "research_mode: the reference run recorded research provenance and "
            "the candidate declares research_mode=false"
        )
    if not reference_run.environment.runtime.get("fpbench.source.revision"):
        differences.append(
            "the reference run records no fpbench source revision, so it is not a "
            "research run at all (docs/adr/0017)"
        )

    policy = getattr(candidate_spec, "materialization_policy", None)
    if reference_materialization_policy is not None and policy != (
        reference_materialization_policy
    ):
        differences.append(
            f"materialization_policy: reference "
            f"{reference_materialization_policy!r} vs candidate {policy!r}"
        )

    if differences:
        raise ResearchPreflightError(
            "the candidate run does not open the reference run's inputs under "
            f"the reference run's input controls: {'; '.join(differences)}"
        )


# ------------------------------------------------------------------- loading


def load_reference_alignment_side(
    *,
    workspace: Path,
    expected: ReferenceRunIdentity,
    research_state: ResearchRunState | None = None,
) -> AlignmentSide:
    """Read the reference run's inputs from the reference run's own manifests.

    Only identity is read: the run definition, the plan, the result-set manifest,
    the pair manifest the run names and the prepared set it names. No stored
    score is opened, and no results table is joined — that belongs to a later
    stage and would be a different claim (spec section 41).
    """
    workspace = Path(workspace)
    result_store = ResultStore(workspace)
    run = result_store.read_run(expected.run_id)
    plan = PlanStore(workspace).read_plan(expected.run_id)

    result_set_id: str | None = None
    try:
        result_set_id = ResultSetStore(workspace).read_manifest(
            expected.run_id
        ).result_set_id
    except (StorageError, ValueError):
        result_set_id = None

    manifests = ManifestStore(workspace)
    pairs = {
        str(pair.pair_id): pair
        for pair in manifests.read_pairs(run.protocol_id, str(run.cohort_id))
    }
    metadata = manifests.pair_manifest_metadata(run.protocol_id, str(run.cohort_id))

    parameters = dict(run.execution_profile.parameters)
    set_id = str(parameters.get("preparation_set_id") or "")
    set_fingerprint = str(parameters.get("preparation_set_fingerprint") or "")

    entries, releases = _prepared_index(
        workspace=workspace,
        preparation_set_id=set_id,
        manifests=manifests,
        protocol_id=run.protocol_id,
        cohort_id=str(run.cohort_id),
    )

    return AlignmentSide(
        label="reference",
        run_id=run.run_id,
        plan_id=plan.plan_id,
        result_set_id=result_set_id,
        protocol_id=run.protocol_id,
        cohort_id=str(run.cohort_id),
        pair_manifest_hash=str(metadata["pair_manifest_hash"]),
        preparation_set_id=set_id,
        preparation_set_fingerprint=set_fingerprint,
        pair_sequence=tuple(str(pair_id) for pair_id in plan.pair_ids()),
        pairs=pairs,
        prepared_entries=entries,
        image_releases=releases,
        research_ready=(
            None if research_state is None else research_state.is_research_ready
        ),
        research_status=(
            None if research_state is None else research_state.status.value
        ),
    )


def load_candidate_alignment_side(
    *,
    pairs: Mapping[PairId, ComparisonPair],
    pair_manifest_hash: str,
    protocol_id: str,
    cohort_id: str,
    preparation_set_id: str,
    preparation_set_fingerprint: str,
    prepared_entries: Mapping[ImageId, PreparedImageEntry],
    images: Mapping[ImageId, ImageRecord],
    plan: ExecutionPlan | None = None,
    run_id: str | None = None,
    result_set_id: str | None = None,
) -> AlignmentSide:
    """Assemble the candidate side from what the engine is about to plan from.

    Before a plan exists the order is derived with the planner's own
    :func:`~fpbench.execution.planner.canonical_pair_order`, so "the order this
    run will execute in" is the planner's answer rather than a second
    implementation of it that could drift (spec section 6).
    """
    if plan is not None:
        sequence = tuple(str(pair_id) for pair_id in plan.pair_ids())
    else:
        sequence = tuple(
            str(pair.pair_id)
            for pair in sorted(pairs.values(), key=canonical_pair_order)
        )
    return AlignmentSide(
        label="candidate",
        run_id=run_id,
        plan_id=plan.plan_id if plan is not None else None,
        result_set_id=result_set_id,
        protocol_id=protocol_id,
        cohort_id=str(cohort_id),
        pair_manifest_hash=str(pair_manifest_hash),
        preparation_set_id=str(preparation_set_id),
        preparation_set_fingerprint=str(preparation_set_fingerprint),
        pair_sequence=sequence,
        pairs={str(key): value for key, value in pairs.items()},
        prepared_entries={str(key): value for key, value in prepared_entries.items()},
        image_releases={
            str(image_id): record.release for image_id, record in images.items()
        },
    )


# ----------------------------------------------------------------- internals


def _prepared_index(
    *,
    workspace: Path,
    preparation_set_id: str,
    manifests: ManifestStore,
    protocol_id: str,
    cohort_id: str,
) -> tuple[dict[str, PreparedImageEntry], dict[str, str]]:
    """The reference run's prepared entries, and which release each image is in.

    The set is named by the reference run's own execution profile, never
    searched for. A workspace that holds two prepared sets is exactly the
    situation in which "the one that is there" is the wrong answer
    (spec section 12's rule, applied to inputs rather than to builds).
    """
    store = PreparedImageSetStore(Path(workspace))
    entries = {
        str(entry.image_id): entry
        for entry in store.read_entries(preparation_set_id)
    }

    cohort = manifests.read_cohort(protocol_id, cohort_id)
    image_releases: dict[str, str] = {}
    for release in cohort.releases:
        for record in manifests.read_images(cohort.dataset_id, release):
            image_releases[str(record.image_id)] = record.release
    return entries, image_releases


def _sequence_digest(sequence: Sequence[str]) -> str:
    return stable_hash(
        {
            "schema": "canonical_pair_id_sequence_v1",
            "pair_ids": [str(item) for item in sequence],
        },
        length=64,
    )


def _semantics_digest(side: AlignmentSide) -> str:
    return stable_hash(
        {
            "schema": "canonical_pair_semantics_v1",
            "pairs": [
                pair_semantics_row(side.pairs[pair_id])
                for pair_id in side.pair_sequence
                if pair_id in side.pairs
            ],
        },
        length=64,
    )


def _entries_digest(side: AlignmentSide) -> str:
    return stable_hash(
        {
            "schema": "canonical_prepared_entries_v1",
            "entries": [
                prepared_entry_row(entry, side.image_releases.get(image_id, ""))
                for image_id, entry in sorted(side.prepared_entries.items())
            ],
        },
        length=64,
    )


def _duplicates(values: Sequence[str]) -> set[str]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for value in values:
        if value in seen:
            repeated.add(value)
        seen.add(value)
    return repeated


def _short(value: object) -> str:
    text = str(value)
    return repr(text if len(text) <= 20 else f"{text[:16]}...")


def _issue(
    code: IntegrityIssueCode,
    message: str,
    *,
    severity: IntegritySeverity = IntegritySeverity.ERROR,
    **details: str,
) -> IntegrityIssue:
    return IntegrityIssue(
        code=code, severity=severity, message=message, details=details
    )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
