from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

import fpbench.protocols as protocols
from fpbench.core import BaselineProtocolStage as PublicBaselineProtocolStage
from fpbench.core.enums import (
    BaselineProtocolStage,
    CohortRole,
    FingerprintPosition,
    GroundTruth,
    Impression,
)
from fpbench.core.models import Cohort, CohortSelection, ImageRecord
from fpbench.protocols.cross_subject import (
    SD300CrossSubjectProtocol,
    audit_cross_subject_pairs,
    generate_cross_subject_pairs,
    load_cross_subject_protocol_config,
)
from fpbench.storage.manifest_store import ManifestStore

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "protocols" / "sd300_cross_subject_non_mated_v1.yaml"
RELEASES = ("SD300A", "SD300B", "SD300C")
pytestmark = pytest.mark.stage21a_contract


def test_extension_preserves_the_public_legacy_protocol_exports() -> None:
    assert {
        "Protocol",
        "SD300Protocol",
        "generate_pairs",
        "select_cohort",
        "SD300CrossSubjectProtocol",
        "generate_cross_subject_pairs",
    } <= set(protocols.__all__)
    assert PublicBaselineProtocolStage is BaselineProtocolStage
    assert not BaselineProtocolStage.PLAIN_ROLL_CROSS_SUBJECT_NON_MATED.is_self


def _cohort(subject_count: int = 3, releases=RELEASES) -> Cohort:
    subjects = tuple(f"{1000 + index:08d}" for index in range(subject_count))
    return Cohort(
        cohort_id="cross_test_cohort",
        protocol_id="sd300_cross_subject_non_mated_v1",
        dataset_id="sd300",
        role=CohortRole.TEST,
        releases=tuple(releases),
        subject_ids=tuple(reversed(subjects)),
        selection=CohortSelection(
            seed=20260728,
            size=subject_count,
            candidate_ids=subjects,
            criteria={},
            image_manifest_hashes={release: "a" * 64 for release in releases},
        ),
    )


def _images(cohort: Cohort) -> list[ImageRecord]:
    rows: list[ImageRecord] = []
    ppi = {"SD300A": 500, "SD300B": 1000, "SD300C": 2000}
    for release in reversed(cohort.releases):
        for subject in reversed(cohort.subject_ids):
            for position in reversed(tuple(FingerprintPosition)):
                for impression in (Impression.ROLL, Impression.PLAIN):
                    rows.append(
                        ImageRecord(
                            image_id=(
                                f"{release.lower()}_{subject}_{impression.value}_"
                                f"{position.label}"
                            ),
                            dataset_id="sd300",
                            release=release,
                            subject_id=subject,
                            impression=impression,
                            position=position,
                            is_multi_finger=False,
                            relative_path="fixture.png",
                            effective_ppi=ppi[release],
                            expected_sha256="0" * 64,
                        )
                    )
    return rows


def test_the_frozen_config_loads_with_exact_exhaustive_arithmetic() -> None:
    config = load_cross_subject_protocol_config(CONFIG)
    assert config.expected_total_pairs == 73_500
    assert config.expected_pairs_per_release == 24_500
    assert config.expected_pairs_per_finger_per_release == 2_450
    assert config.expected_appearances_per_side_per_subject_per_release == 490
    assert config.legacy_pair_manifest_hash == (
        "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"
    )


def test_generation_is_exhaustive_directed_and_in_frozen_order() -> None:
    cohort = _cohort()
    pairs = generate_cross_subject_pairs(cohort, _images(cohort))
    assert len(pairs) == 3 * 2 * 10 * 3
    assert pairs == generate_cross_subject_pairs(cohort, list(reversed(_images(cohort))))
    keys = []
    by_id = {image.image_id: image for image in _images(cohort)}
    for pair in pairs:
        left = by_id[pair.left_image_id]
        right = by_id[pair.right_image_id]
        keys.append((pair.release, left.subject_id, right.subject_id, int(left.position)))
        assert left.impression is Impression.PLAIN
        assert right.impression is Impression.ROLL
        assert left.subject_id != right.subject_id
        assert left.position is right.position
        assert left.release == right.release == pair.release
        assert pair.ground_truth is GroundTruth.NON_MATED
        assert pair.protocol_stage is (
            BaselineProtocolStage.PLAIN_ROLL_CROSS_SUBJECT_NON_MATED
        )
    assert keys == sorted(keys)
    directed = Counter((key[1], key[2]) for key in keys)
    for left in cohort.subject_ids:
        for right in cohort.subject_ids:
            if left != right:
                assert directed[(left, right)] == 10 * len(cohort.releases)


def test_the_full_fifty_subject_shape_is_exact() -> None:
    cohort = _cohort(subject_count=50)
    pairs = generate_cross_subject_pairs(cohort, _images(cohort))
    assert len(pairs) == 73_500
    counts = Counter(pair.release for pair in pairs)
    assert counts == {release: 24_500 for release in RELEASES}


def test_audit_rederives_every_balance_invariant() -> None:
    cohort = _cohort(subject_count=4)
    images = _images(cohort)
    pairs = generate_cross_subject_pairs(cohort, images)
    audit = audit_cross_subject_pairs(
        pairs,
        cohort=cohort,
        images=images,
        legacy_pair_ids=("legacy_pair",),
    )
    assert audit.clean
    assert audit.expected_pairs_per_release == 4 * 3 * 10
    assert audit.expected_pairs_per_finger_per_release == 12
    assert audit.expected_appearances_per_side_per_subject_per_release == 30
    assert set(audit.pairs_per_finger_per_release) == set(RELEASES)
    assert all(
        set(per_release.values()) == {12}
        for per_release in audit.pairs_per_finger_per_release.values()
    )


def test_audit_detects_duplicate_and_legacy_collision() -> None:
    cohort = _cohort(subject_count=2, releases=("SD300A",))
    images = _images(cohort)
    pairs = generate_cross_subject_pairs(cohort, images)
    collided = replace(pairs[1], pair_id=pairs[0].pair_id)
    audit = audit_cross_subject_pairs(
        (pairs[0], collided, *pairs[2:]),
        cohort=cohort,
        images=images,
        legacy_pair_ids=(pairs[0].pair_id,),
    )
    assert audit.duplicate_pair_ids == 1
    assert audit.legacy_pair_id_collisions == 1
    assert not audit.clean


def test_manifest_storage_round_trips_the_extension_stage(tmp_path: Path) -> None:
    cohort = _cohort(subject_count=2, releases=("SD300A",))
    images = _images(cohort)
    pairs = generate_cross_subject_pairs(cohort, images)
    store = ManifestStore(tmp_path)
    store.write_cohort(cohort)
    store.write_pairs(pairs, cohort=cohort)
    loaded = store.read_pairs(cohort.protocol_id, str(cohort.cohort_id))
    assert loaded == list(pairs)
    assert all(
        pair.protocol_stage
        is BaselineProtocolStage.PLAIN_ROLL_CROSS_SUBJECT_NON_MATED
        for pair in loaded
    )


def test_protocol_object_refuses_a_cohort_from_the_legacy_namespace() -> None:
    protocol = SD300CrossSubjectProtocol.from_config_file(CONFIG)
    legacy = replace(_cohort(), protocol_id="sd300_50_subjects")
    try:
        protocol.build_pairs(legacy, _images(legacy))
    except Exception as exc:
        assert "not extension" in str(exc)
    else:  # pragma: no cover - the refusal is the contract
        raise AssertionError("legacy cohort namespace was accepted")
