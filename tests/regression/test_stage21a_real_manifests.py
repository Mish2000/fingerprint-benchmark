"""Real-manifest Stage 21A regression; metadata only, never score results."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.experiments.stage21a_finalization import LEGACY_PAIR_MANIFEST_HASH
from fpbench.core.serialization import stable_hash
from fpbench.protocols.cross_subject import audit_cross_subject_pairs
from fpbench.protocols.sd300_protocol import SD300Protocol
from fpbench.storage.manifest_store import ManifestStore

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "workspace"
LEGACY_PROTOCOL = "sd300_50_subjects"
LEGACY_COHORT = "sd300_50_subjects_test_22f8d52a7478"
pytestmark = pytest.mark.stage21a_workspace


def _pair_rows(pairs):
    return [
        {
            "pair_id": str(pair.pair_id),
            "dataset_id": pair.dataset_id,
            "release": pair.release,
            "left_image_id": str(pair.left_image_id),
            "right_image_id": str(pair.right_image_id),
            "ground_truth": pair.ground_truth.value,
            "protocol_stage": pair.protocol_stage.value,
        }
        for pair in pairs
    ]


def _store_or_skip() -> ManifestStore:
    path = (
        WORKSPACE
        / "manifests/protocols/sd300_50_subjects/cohorts"
        / LEGACY_COHORT
        / "pairs.parquet"
    )
    if not path.is_file():
        pytest.skip("local SD300 manifests are not present")
    return ManifestStore(WORKSPACE)


def test_the_real_legacy_generator_still_reproduces_all_6000_rows() -> None:
    store = _store_or_skip()
    protocol = SD300Protocol.from_config_file(
        ROOT / "configs/protocols/sd300_50_subjects.yaml"
    )
    cohort = store.read_cohort(LEGACY_PROTOCOL, LEGACY_COHORT)
    images = [
        image
        for release in protocol.releases
        for image in store.read_images("sd300", release)
    ]
    stored = store.read_pairs(LEGACY_PROTOCOL, LEGACY_COHORT)
    assert protocol.build_pairs(cohort, images) == tuple(stored)
    assert len(stored) == 6_000
    assert store.pair_manifest_metadata(LEGACY_PROTOCOL, LEGACY_COHORT)[
        "pair_manifest_hash"
    ] == LEGACY_PAIR_MANIFEST_HASH


def test_the_real_cross_subject_manifest_matches_its_published_audit() -> None:
    store = _store_or_skip()
    binding = json.loads(
        (
            ROOT
            / "evidence/stage21a-final-baseline-evaluation-protocol/"
            "cross-subject-pair-binding.json"
        ).read_text(encoding="utf-8")
    )
    protocol_id = binding["protocol_id"]
    cohort_id = binding["cohort_id"]
    pairs = store.read_pairs(protocol_id, cohort_id)
    cohort = store.read_cohort(protocol_id, cohort_id)
    images = [
        image
        for release in cohort.releases
        for image in store.read_images("sd300", release)
    ]
    legacy = store.read_pairs(LEGACY_PROTOCOL, LEGACY_COHORT)
    audit = audit_cross_subject_pairs(
        pairs,
        cohort=cohort,
        images=images,
        legacy_pair_ids=(pair.pair_id for pair in legacy),
    )
    assert audit.clean
    assert len(pairs) == 73_500
    assert store.pair_manifest_metadata(protocol_id, cohort_id)[
        "pair_manifest_hash"
    ] == binding["pair_manifest_hash"]


def test_future_challenger_pair_sets_derive_from_the_two_frozen_manifests() -> None:
    store = _store_or_skip()
    evidence = ROOT / "evidence/stage21a-final-baseline-evaluation-protocol"
    reservation = json.loads(
        (evidence / "high-resolution-test-reservation.json").read_text(
            encoding="utf-8"
        )
    )["reservation"]["future_test_population"]
    cross = json.loads(
        (evidence / "cross-subject-pair-binding.json").read_text(encoding="utf-8")
    )
    genuine = [
        pair
        for pair in store.read_pairs(LEGACY_PROTOCOL, LEGACY_COHORT)
        if pair.release == "SD300B"
        and pair.protocol_stage.value == "plain_roll_mated"
    ]
    impostor = [
        pair
        for pair in store.read_pairs(cross["protocol_id"], cross["cohort_id"])
        if pair.release == "SD300B"
    ]
    for pairs, frozen in (
        (genuine, reservation["genuine"]),
        (impostor, reservation["impostor"]),
    ):
        assert len(pairs) == frozen["pair_count"]
        assert stable_hash(
            [str(pair.pair_id) for pair in pairs], length=64
        ) == frozen["pair_ids_sha256"]
        assert stable_hash(_pair_rows(pairs), length=64) == frozen[
            "pair_set_fingerprint"
        ]
