"""The Stage 21A cross-subject impostor extension to the SD300 protocol.

The legacy 6,000-pair protocol remains untouched.  This module creates a new,
separately identified manifest containing only directed PLAIN(A) -> ROLL(B)
comparisons for different subjects at the same anatomical finger position.
It reads image metadata and cohort identities; it never reads an algorithm
result or a score.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from fpbench.core.config_values import (
    reject_unknown_keys,
    require_yaml_bool,
    require_yaml_exact_int,
    require_yaml_non_empty_str,
)
from fpbench.core.enums import (
    BaselineProtocolStage,
    CohortRole,
    FingerprintPosition,
    GroundTruth,
    Impression,
)
from fpbench.core.errors import ConfigurationError, ProtocolError
from fpbench.core.identifiers import ImageId, PairId, SubjectId, compose_id
from fpbench.core.models import Cohort, ComparisonPair, ImageRecord, SubjectRecord
from fpbench.protocols.base import Protocol
from fpbench.protocols.cohorts import select_cohort
from fpbench.protocols.pair_generation import build_image_index
from fpbench.protocols.sd300_protocol import (
    SD300ProtocolConfig,
    load_protocol_config,
)

__all__ = [
    "CROSS_SUBJECT_POPULATION",
    "CrossSubjectPairAudit",
    "CrossSubjectProtocolConfig",
    "SD300CrossSubjectProtocol",
    "audit_cross_subject_pairs",
    "generate_cross_subject_pairs",
    "load_cross_subject_protocol_config",
]


CROSS_SUBJECT_POPULATION = "plain_roll_cross_subject_non_mated"
_ORDERING = ("release", "left_subject", "right_subject", "finger_position")

_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "protocol", "dataset", "cohort", "population", "expected"}
)
_PROTOCOL_KEYS = frozenset({"id", "extends_config", "extends_protocol_id"})
_DATASET_KEYS = frozenset({"id"})
_COHORT_KEYS = frozenset(
    {
        "source_cohort_id",
        "role",
        "subjects",
        "releases",
        "legacy_pair_manifest_hash",
    }
)
_POPULATION_KEYS = frozenset(
    {
        "id",
        "left_impression",
        "right_impression",
        "subject_relation",
        "finger_relation",
        "release_relation",
        "ground_truth",
        "directed",
        "exhaustive",
        "sampling",
        "ordering",
    }
)
_EXPECTED_KEYS = frozenset(
    {
        "total_pairs",
        "pairs_per_release",
        "pairs_per_finger_per_release",
        "appearances_per_side_per_subject_per_release",
    }
)


@dataclass(frozen=True, slots=True)
class CrossSubjectProtocolConfig:
    """All identities and arithmetic frozen before the expansion run."""

    protocol_id: str
    dataset_id: str
    legacy_protocol_config_path: Path
    legacy_protocol: SD300ProtocolConfig
    legacy_protocol_id: str
    source_cohort_id: str
    legacy_pair_manifest_hash: str
    population_id: str
    ordering: tuple[str, ...]
    expected_total_pairs: int
    expected_pairs_per_release: int
    expected_pairs_per_finger_per_release: int
    expected_appearances_per_side_per_subject_per_release: int


def _mapping(document: Mapping[str, Any], key: str, where: str) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{where}: missing or malformed '{key}' section")
    return value


def _string_list(
    document: Mapping[str, Any], key: str, *, where: str
) -> tuple[str, ...]:
    value = document.get(key)
    if not isinstance(value, (list, tuple)) or isinstance(value, str):
        raise ConfigurationError(f"{where}: '{key}' must be a YAML list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ConfigurationError(
                f"{where}: {key}[{index}] must be a non-empty YAML string"
            )
        result.append(item.strip())
    if len(result) != len(set(result)):
        raise ConfigurationError(f"{where}: '{key}' contains duplicates")
    return tuple(result)


def _require_literal(
    document: Mapping[str, Any], key: str, expected: str, *, where: str
) -> str:
    value = require_yaml_non_empty_str(document, key, where=where)
    if value != expected:
        raise ConfigurationError(
            f"{where}: '{key}' must be {expected!r}, got {value!r}"
        )
    return value


def _require_sha256(value: str, *, where: str) -> str:
    digest = value.lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ConfigurationError(f"{where}: expected a lowercase SHA-256 digest")
    return digest


def load_cross_subject_protocol_config(path: Path) -> CrossSubjectProtocolConfig:
    """Load the strict, separately identified cross-subject extension config."""
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"cross-subject protocol config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")
    where = str(path)
    reject_unknown_keys(document, _TOP_LEVEL_KEYS, where=where)
    schema_version = require_yaml_exact_int(
        document, "schema_version", where=where, minimum=1
    )
    if schema_version != 1:
        raise ConfigurationError(f"{where}: schema_version must be 1")

    protocol = _mapping(document, "protocol", where)
    dataset = _mapping(document, "dataset", where)
    cohort = _mapping(document, "cohort", where)
    population = _mapping(document, "population", where)
    expected = _mapping(document, "expected", where)
    reject_unknown_keys(protocol, _PROTOCOL_KEYS, where=f"{where}: protocol")
    reject_unknown_keys(dataset, _DATASET_KEYS, where=f"{where}: dataset")
    reject_unknown_keys(cohort, _COHORT_KEYS, where=f"{where}: cohort")
    reject_unknown_keys(population, _POPULATION_KEYS, where=f"{where}: population")
    reject_unknown_keys(expected, _EXPECTED_KEYS, where=f"{where}: expected")

    protocol_id = require_yaml_non_empty_str(
        protocol, "id", where=f"{where}: protocol"
    )
    legacy_protocol_id = require_yaml_non_empty_str(
        protocol, "extends_protocol_id", where=f"{where}: protocol"
    )
    legacy_ref = require_yaml_non_empty_str(
        protocol, "extends_config", where=f"{where}: protocol"
    )
    repo_root = path.resolve().parent.parent.parent
    legacy_path = (repo_root / legacy_ref).resolve()
    legacy = load_protocol_config(legacy_path)
    if legacy.protocol_id != legacy_protocol_id:
        raise ConfigurationError(
            f"{where}: extends_protocol_id names {legacy_protocol_id!r}, but "
            f"{legacy_path} defines {legacy.protocol_id!r}"
        )

    dataset_id = require_yaml_non_empty_str(
        dataset, "id", where=f"{where}: dataset"
    )
    if dataset_id != legacy.dataset_id:
        raise ConfigurationError(
            f"{where}: dataset {dataset_id!r} differs from the legacy protocol's "
            f"{legacy.dataset_id!r}"
        )

    cohort_where = f"{where}: cohort"
    source_cohort_id = require_yaml_non_empty_str(
        cohort, "source_cohort_id", where=cohort_where
    )
    _require_literal(cohort, "role", CohortRole.TEST.value, where=cohort_where)
    subjects = require_yaml_exact_int(
        cohort, "subjects", where=cohort_where, minimum=1
    )
    releases = _string_list(cohort, "releases", where=cohort_where)
    if subjects != legacy.criteria.size or releases != legacy.criteria.releases:
        raise ConfigurationError(
            f"{where}: the extension must reuse the legacy cohort shape exactly"
        )
    legacy_hash = _require_sha256(
        require_yaml_non_empty_str(
            cohort, "legacy_pair_manifest_hash", where=cohort_where
        ),
        where=f"{cohort_where}.legacy_pair_manifest_hash",
    )

    population_where = f"{where}: population"
    population_id = _require_literal(
        population, "id", CROSS_SUBJECT_POPULATION, where=population_where
    )
    for key, literal in (
        ("left_impression", "plain"),
        ("right_impression", "roll"),
        ("subject_relation", "different"),
        ("finger_relation", "same_anatomical_position"),
        ("release_relation", "same_release"),
        ("ground_truth", "non_mated"),
        ("sampling", "forbidden"),
    ):
        _require_literal(population, key, literal, where=population_where)
    if not require_yaml_bool(population, "directed", where=population_where):
        raise ConfigurationError(f"{population_where}: directed must be true")
    if not require_yaml_bool(population, "exhaustive", where=population_where):
        raise ConfigurationError(f"{population_where}: exhaustive must be true")
    ordering = _string_list(population, "ordering", where=population_where)
    if ordering != _ORDERING:
        raise ConfigurationError(
            f"{population_where}: ordering must be {list(_ORDERING)!r}"
        )

    expected_where = f"{where}: expected"
    expected_total = require_yaml_exact_int(
        expected, "total_pairs", where=expected_where, minimum=1
    )
    expected_release = require_yaml_exact_int(
        expected, "pairs_per_release", where=expected_where, minimum=1
    )
    expected_finger = require_yaml_exact_int(
        expected, "pairs_per_finger_per_release", where=expected_where, minimum=1
    )
    expected_appearances = require_yaml_exact_int(
        expected,
        "appearances_per_side_per_subject_per_release",
        where=expected_where,
        minimum=1,
    )
    calculated_release = subjects * (subjects - 1) * len(FingerprintPosition)
    calculated_finger = subjects * (subjects - 1)
    calculated_appearances = (subjects - 1) * len(FingerprintPosition)
    calculated_total = calculated_release * len(releases)
    if (
        expected_total,
        expected_release,
        expected_finger,
        expected_appearances,
    ) != (
        calculated_total,
        calculated_release,
        calculated_finger,
        calculated_appearances,
    ):
        raise ConfigurationError(
            f"{expected_where}: frozen counts do not equal exhaustive directed "
            f"cross-subject arithmetic"
        )

    return CrossSubjectProtocolConfig(
        protocol_id=protocol_id,
        dataset_id=dataset_id,
        legacy_protocol_config_path=legacy_path,
        legacy_protocol=legacy,
        legacy_protocol_id=legacy_protocol_id,
        source_cohort_id=source_cohort_id,
        legacy_pair_manifest_hash=legacy_hash,
        population_id=population_id,
        ordering=ordering,
        expected_total_pairs=expected_total,
        expected_pairs_per_release=expected_release,
        expected_pairs_per_finger_per_release=expected_finger,
        expected_appearances_per_side_per_subject_per_release=expected_appearances,
    )


class SD300CrossSubjectProtocol(Protocol):
    """A manifest-only extension over exactly the frozen SD300 cohort."""

    def __init__(self, config: CrossSubjectProtocolConfig) -> None:
        self.config = config
        self.protocol_id = config.protocol_id
        self.dataset_id = config.dataset_id

    @classmethod
    def from_config_file(cls, path: Path) -> "SD300CrossSubjectProtocol":
        return cls(load_cross_subject_protocol_config(path))

    @property
    def releases(self) -> tuple[str, ...]:
        return self.config.legacy_protocol.criteria.releases

    def build_cohort(
        self,
        subjects: Iterable[SubjectRecord],
        image_manifest_hashes: Mapping[str, str],
    ) -> Cohort:
        return select_cohort(
            protocol_id=self.protocol_id,
            dataset_id=self.dataset_id,
            subjects=subjects,
            criteria=self.config.legacy_protocol.criteria,
            image_manifest_hashes=image_manifest_hashes,
        )

    def build_pairs(
        self, cohort: Cohort, images: Sequence[ImageRecord]
    ) -> tuple[ComparisonPair, ...]:
        if cohort.protocol_id != self.protocol_id:
            raise ProtocolError(
                f"cohort {cohort.cohort_id} belongs to {cohort.protocol_id}, not "
                f"extension {self.protocol_id}"
            )
        pairs = generate_cross_subject_pairs(cohort, images)
        if len(pairs) != self.config.expected_total_pairs:
            raise ProtocolError(
                f"extension generated {len(pairs)} pairs; frozen config requires "
                f"{self.config.expected_total_pairs}"
            )
        return pairs


def _require_image(
    index: Mapping[
        tuple[str, SubjectId, Impression, FingerprintPosition], ImageRecord
    ],
    release: str,
    subject_id: SubjectId,
    impression: Impression,
    position: FingerprintPosition,
) -> ImageRecord:
    try:
        return index[(release, subject_id, impression, position)]
    except KeyError:
        raise ProtocolError(
            f"frozen cohort subject {subject_id} has no usable {impression.value} "
            f"{position.label} image in {release}"
        ) from None


def generate_cross_subject_pairs(
    cohort: Cohort, images: Sequence[ImageRecord]
) -> tuple[ComparisonPair, ...]:
    """Enumerate every directed A-plain to B-roll pair in frozen order."""
    index = build_image_index(images)
    pairs: list[ComparisonPair] = []
    for release in sorted(cohort.releases):
        for left_subject in sorted(cohort.subject_ids):
            for right_subject in sorted(cohort.subject_ids):
                if left_subject == right_subject:
                    continue
                for position in FingerprintPosition:
                    left = _require_image(
                        index, release, left_subject, Impression.PLAIN, position
                    )
                    right = _require_image(
                        index, release, right_subject, Impression.ROLL, position
                    )
                    pairs.append(
                        ComparisonPair(
                            pair_id=PairId(
                                compose_id(
                                    release,
                                    left_subject,
                                    "plain",
                                    right_subject,
                                    "roll",
                                    position.label,
                                    "cross_subject_nonmated",
                                )
                            ),
                            dataset_id=cohort.dataset_id,
                            release=release,
                            left_image_id=left.image_id,
                            right_image_id=right.image_id,
                            ground_truth=GroundTruth.NON_MATED,
                            protocol_stage=(
                                BaselineProtocolStage.PLAIN_ROLL_CROSS_SUBJECT_NON_MATED
                            ),
                        )
                    )
    return tuple(pairs)


@dataclass(frozen=True, slots=True)
class CrossSubjectPairAudit:
    total_pairs: int
    expected_total_pairs: int
    release_counts: Mapping[str, int]
    expected_pairs_per_release: int
    pairs_per_finger_per_release: Mapping[str, Mapping[str, int]]
    expected_pairs_per_finger_per_release: int
    duplicate_pair_ids: int
    legacy_pair_id_collisions: int
    unknown_images: int
    unknown_subjects: int
    images_outside_cohort: int
    pairs_with_same_subject: int
    pairs_with_different_finger_position: int
    cross_release_pairs: int
    pair_release_mismatches: int
    left_not_plain: int
    right_not_roll: int
    wrong_ground_truth: int
    wrong_protocol_stage: int
    left_appearance_violations: int
    right_appearance_violations: int
    expected_appearances_per_side_per_subject_per_release: int

    @property
    def clean(self) -> bool:
        counts_ok = self.total_pairs == self.expected_total_pairs and all(
            count == self.expected_pairs_per_release
            for count in self.release_counts.values()
        )
        fingers_ok = all(
            count == self.expected_pairs_per_finger_per_release
            for per_release in self.pairs_per_finger_per_release.values()
            for count in per_release.values()
        )
        violations = (
            self.duplicate_pair_ids,
            self.legacy_pair_id_collisions,
            self.unknown_images,
            self.unknown_subjects,
            self.images_outside_cohort,
            self.pairs_with_same_subject,
            self.pairs_with_different_finger_position,
            self.cross_release_pairs,
            self.pair_release_mismatches,
            self.left_not_plain,
            self.right_not_roll,
            self.wrong_ground_truth,
            self.wrong_protocol_stage,
            self.left_appearance_violations,
            self.right_appearance_violations,
        )
        return counts_ok and fingers_ok and not any(violations)

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "stage_21a_cross_subject_pair_audit",
            "population": CROSS_SUBJECT_POPULATION,
            "total_pairs": self.total_pairs,
            "expected_total_pairs": self.expected_total_pairs,
            "release_counts": dict(self.release_counts),
            "expected_pairs_per_release": self.expected_pairs_per_release,
            "pairs_per_finger_per_release": {
                release: dict(counts)
                for release, counts in self.pairs_per_finger_per_release.items()
            },
            "expected_pairs_per_finger_per_release": (
                self.expected_pairs_per_finger_per_release
            ),
            "duplicate_pair_ids": self.duplicate_pair_ids,
            "legacy_pair_id_collisions": self.legacy_pair_id_collisions,
            "unknown_images": self.unknown_images,
            "unknown_subjects": self.unknown_subjects,
            "images_outside_cohort": self.images_outside_cohort,
            "pairs_with_same_subject": self.pairs_with_same_subject,
            "pairs_with_different_finger_position": (
                self.pairs_with_different_finger_position
            ),
            "cross_release_pairs": self.cross_release_pairs,
            "pair_release_mismatches": self.pair_release_mismatches,
            "left_not_plain": self.left_not_plain,
            "right_not_roll": self.right_not_roll,
            "wrong_ground_truth": self.wrong_ground_truth,
            "wrong_protocol_stage": self.wrong_protocol_stage,
            "left_appearance_violations": self.left_appearance_violations,
            "right_appearance_violations": self.right_appearance_violations,
            "expected_appearances_per_side_per_subject_per_release": (
                self.expected_appearances_per_side_per_subject_per_release
            ),
            "clean": self.clean,
        }


def audit_cross_subject_pairs(
    pairs: Sequence[ComparisonPair],
    *,
    cohort: Cohort,
    images: Sequence[ImageRecord],
    legacy_pair_ids: Iterable[str | PairId] = (),
) -> CrossSubjectPairAudit:
    """Re-derive every structural invariant from image metadata."""
    by_id: dict[ImageId, ImageRecord] = {image.image_id: image for image in images}
    legacy_ids = {str(pair_id) for pair_id in legacy_pair_ids}
    pair_ids = [str(pair.pair_id) for pair in pairs]
    release_counts: Counter[str] = Counter()
    finger_counts: dict[str, Counter[str]] = {
        release: Counter() for release in sorted(cohort.releases)
    }
    left_appearances: Counter[tuple[str, SubjectId]] = Counter()
    right_appearances: Counter[tuple[str, SubjectId]] = Counter()
    violations: Counter[str] = Counter()
    cohort_subjects = set(cohort.subject_ids)

    for pair in pairs:
        release_counts[pair.release] += 1
        left = by_id.get(pair.left_image_id)
        right = by_id.get(pair.right_image_id)
        if left is None:
            violations["unknown_images"] += 1
        if right is None:
            violations["unknown_images"] += 1
        if left is None or right is None:
            continue
        if left.position is not None:
            finger_counts.setdefault(pair.release, Counter())[left.position.label] += 1
        left_appearances[(pair.release, left.subject_id)] += 1
        right_appearances[(pair.release, right.subject_id)] += 1
        if left.subject_id == right.subject_id:
            violations["pairs_with_same_subject"] += 1
        if left.position is None or right.position is None or left.position != right.position:
            violations["pairs_with_different_finger_position"] += 1
        if left.release != right.release:
            violations["cross_release_pairs"] += 1
        if pair.release != left.release or pair.release != right.release:
            violations["pair_release_mismatches"] += 1
        if left.impression is not Impression.PLAIN:
            violations["left_not_plain"] += 1
        if right.impression is not Impression.ROLL:
            violations["right_not_roll"] += 1
        for image in (left, right):
            if image.subject_id not in cohort_subjects:
                violations["unknown_subjects"] += 1
            if image.release not in cohort.releases:
                violations["images_outside_cohort"] += 1
        if pair.ground_truth is not GroundTruth.NON_MATED:
            violations["wrong_ground_truth"] += 1
        if pair.protocol_stage is not (
            BaselineProtocolStage.PLAIN_ROLL_CROSS_SUBJECT_NON_MATED
        ):
            violations["wrong_protocol_stage"] += 1

    subject_count = len(cohort.subject_ids)
    expected_release = subject_count * (subject_count - 1) * len(FingerprintPosition)
    expected_finger = subject_count * (subject_count - 1)
    expected_appearances = (subject_count - 1) * len(FingerprintPosition)
    for release in cohort.releases:
        for subject in cohort.subject_ids:
            if left_appearances[(release, subject)] != expected_appearances:
                violations["left_appearance_violations"] += 1
            if right_appearances[(release, subject)] != expected_appearances:
                violations["right_appearance_violations"] += 1

    return CrossSubjectPairAudit(
        total_pairs=len(pairs),
        expected_total_pairs=expected_release * len(cohort.releases),
        release_counts={release: release_counts[release] for release in sorted(cohort.releases)},
        expected_pairs_per_release=expected_release,
        pairs_per_finger_per_release={
            release: {
                position.label: finger_counts[release][position.label]
                for position in FingerprintPosition
            }
            for release in sorted(cohort.releases)
        },
        expected_pairs_per_finger_per_release=expected_finger,
        duplicate_pair_ids=len(pair_ids) - len(set(pair_ids)),
        legacy_pair_id_collisions=len(set(pair_ids) & legacy_ids),
        unknown_images=violations["unknown_images"],
        unknown_subjects=violations["unknown_subjects"],
        images_outside_cohort=violations["images_outside_cohort"],
        pairs_with_same_subject=violations["pairs_with_same_subject"],
        pairs_with_different_finger_position=violations[
            "pairs_with_different_finger_position"
        ],
        cross_release_pairs=violations["cross_release_pairs"],
        pair_release_mismatches=violations["pair_release_mismatches"],
        left_not_plain=violations["left_not_plain"],
        right_not_roll=violations["right_not_roll"],
        wrong_ground_truth=violations["wrong_ground_truth"],
        wrong_protocol_stage=violations["wrong_protocol_stage"],
        left_appearance_violations=violations["left_appearance_violations"],
        right_appearance_violations=violations["right_appearance_violations"],
        expected_appearances_per_side_per_subject_per_release=expected_appearances,
    )
