"""Frozen identities Stage 21B must consume without mutating."""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.stage21b.bindings import load_frozen_pairs, load_stage21a_binding
from fpbench.stage21b.constants import (
    LEGACY_PAIR_MANIFEST_HASH,
    PREPARATION_PROFILE_ID,
    PREPARATION_SET_ID,
)
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "workspace"
LEGACY_PROTOCOL = "sd300_50_subjects"
LEGACY_COHORT = "sd300_50_subjects_test_22f8d52a7478"
pytestmark = pytest.mark.stage21b_contract


def test_legacy_6000_and_cross_subject_73500_identities_remain_frozen() -> None:
    legacy_path = (
        WORKSPACE
        / "manifests/protocols"
        / LEGACY_PROTOCOL
        / "cohorts"
        / LEGACY_COHORT
        / "pairs.parquet"
    )
    if not legacy_path.is_file():
        pytest.skip("local frozen manifests are absent")
    store = ManifestStore(WORKSPACE)
    legacy = store.read_pairs(LEGACY_PROTOCOL, LEGACY_COHORT)
    assert len(legacy) == 6_000
    assert store.pair_manifest_metadata(LEGACY_PROTOCOL, LEGACY_COHORT)[
        "pair_manifest_hash"
    ] == LEGACY_PAIR_MANIFEST_HASH

    binding = load_stage21a_binding(ROOT)
    cross_subject = load_frozen_pairs(workspace=WORKSPACE, binding=binding)
    assert len(cross_subject.pairs) == 73_500
    assert cross_subject.pair_manifest_hash == binding.pair_manifest_hash


def test_canonical500_identity_used_by_stage21b_has_not_changed() -> None:
    store = PreparedImageSetStore(WORKSPACE)
    path = store.manifest_path(PREPARATION_SET_ID)
    if not path.is_file():
        pytest.skip("local canonical500 prepared-set metadata is absent")
    manifest = store.read_manifest(PREPARATION_SET_ID)
    assert manifest.preparation_set_id == PREPARATION_SET_ID
    assert manifest.transform_profile_id == PREPARATION_PROFILE_ID
    assert manifest.pair_manifest_hash == LEGACY_PAIR_MANIFEST_HASH
