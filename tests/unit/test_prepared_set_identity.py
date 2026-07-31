"""What a prepared-image set's identity covers, and how it is derived.

Two questions, kept apart because they fail differently.

*Which images?* — the set covers exactly the distinct images the pair manifest
names, derived from the pairs and never from a directory listing. A file that
arrived after the manifest was frozen must not be able to join the experiment,
and the order must not depend on how a filesystem enumerated a directory.

*Which artefacts?* — the fingerprint folds in every entry hash in order, plus
the profile, the runtime, the pair manifest and the cohort. Change any of them
and the set is a different set. Change the wall clock and it is not.
"""

from __future__ import annotations

import dataclasses

import pytest

from fpbench.core.enums import GroundTruth, ProtocolStage
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.imaging_models import (
    PreparationDefinition,
    PreparedImageSetManifest,
    ordered_image_ids_hash,
    ordered_prepared_entries_hash,
    preparation_definition_fingerprint,
    preparation_set_fingerprint,
    preparation_set_id,
)
from fpbench.core.models import ComparisonPair
from fpbench.experiments.sd300_inputs import participating_image_ids
from fpbench.imaging.verify import preparation_source_binding_issues
from canonicalworld import build_canonical_world, make_runtime

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_canonical_world(tmp_path_factory.mktemp("set-identity"))


def _pair(pair_id: str, left: str, right: str, release: str = "SD300A"):
    return ComparisonPair(
        pair_id=PairId(pair_id),
        dataset_id="sd300",
        release=release,
        left_image_id=ImageId(left),
        right_image_id=ImageId(right),
        ground_truth=GroundTruth.MATED,
        protocol_stage=ProtocolStage.PLAIN_ROLL_MATED,
    )


# -------------------------------------------------------- deriving the images


def test_the_image_set_is_exactly_the_distinct_images_the_pairs_name():
    pairs = {
        PairId("p1"): _pair("p1", "sd300a_s1_plain_f01", "sd300a_s1_roll_f01"),
        PairId("p2"): _pair("p2", "sd300a_s1_plain_f01", "sd300a_s1_plain_f01"),
        PairId("p3"): _pair("p3", "sd300a_s1_plain_f02", "sd300a_s1_roll_f02"),
    }
    assert participating_image_ids(pairs) == (
        "sd300a_s1_plain_f01",
        "sd300a_s1_plain_f02",
        "sd300a_s1_roll_f01",
        "sd300a_s1_roll_f02",
    )


def test_an_image_named_twice_appears_once():
    """A SELF pair names the same image on both sides, and it is one image."""
    pairs = {PairId("p"): _pair("p", "sd300a_s1_plain_f01", "sd300a_s1_plain_f01")}
    assert participating_image_ids(pairs) == ("sd300a_s1_plain_f01",)


def test_the_order_is_ascending_and_not_filesystem_order():
    pairs = {
        PairId("p1"): _pair("p1", "sd300c_z", "sd300a_a"),
        PairId("p2"): _pair("p2", "sd300b_m", "sd300a_b"),
    }
    assert participating_image_ids(pairs) == (
        "sd300a_a",
        "sd300a_b",
        "sd300b_m",
        "sd300c_z",
    )


# ------------------------------------------------------------- the definition


def test_a_definition_rejects_a_duplicate_image(world):
    ordered = list(world.definition.ordered_image_ids)
    duplicated = tuple([ordered[0]] + ordered)
    with pytest.raises(ValueError, match="lists an image twice"):
        _redefine(
            world.definition,
            ordered_image_ids=duplicated,
            expected_total_images=len(duplicated),
        )


def test_a_definition_rejects_an_unsorted_image_list(world):
    ordered = list(world.definition.ordered_image_ids)
    shuffled = tuple([ordered[1], ordered[0], *ordered[2:]])
    with pytest.raises(ValueError, match="ascending order"):
        _redefine(world.definition, ordered_image_ids=shuffled)


def test_a_definition_rejects_a_count_that_disagrees_with_its_list(world):
    with pytest.raises(ValueError, match="expects"):
        _redefine(
            world.definition,
            expected_total_images=world.definition.expected_total_images + 1,
        )


def test_a_definition_must_fingerprint_to_its_own_id(world):
    with pytest.raises(ValueError, match="definition_fingerprint does not cover"):
        dataclasses.replace(world.definition, pair_manifest_hash="a" * 64)


def test_the_definition_timestamp_is_outside_its_fingerprint(world):
    later = dataclasses.replace(
        world.definition, created_utc="2099-01-01T00:00:00+00:00"
    )
    assert later.definition_fingerprint == world.definition.definition_fingerprint


# -------------------------------------------------------------- the set itself


def test_the_set_fingerprint_covers_every_entry(world):
    baseline = _set_fingerprint(world, world.entries)
    assert baseline == world.manifest.preparation_set_fingerprint

    changed_entries = (
        *world.entries[:-1],
        _entry_with_different_hash(world.entries[-1]),
    )
    assert _set_fingerprint(world, changed_entries) != baseline


def test_the_set_fingerprint_changes_with_the_pair_manifest(world):
    baseline = world.manifest.preparation_set_fingerprint
    assert (
        preparation_set_fingerprint(
            dataset_id=world.manifest.dataset_id,
            image_manifest_hash=world.manifest.image_manifest_hash,
            protocol_id=world.manifest.protocol_id,
            cohort_id=world.manifest.cohort_id,
            cohort_fingerprint=world.manifest.cohort_fingerprint,
            pair_manifest_hash="b" * 64,
            transform_profile_fingerprint=world.manifest.transform_profile_fingerprint,
            transform_runtime_fingerprint=world.manifest.transform_runtime_fingerprint,
            entries=world.entries,
        )
        != baseline
    )


def test_the_set_fingerprint_changes_with_the_transform_profile(world):
    assert (
        preparation_set_fingerprint(
            dataset_id=world.manifest.dataset_id,
            image_manifest_hash=world.manifest.image_manifest_hash,
            protocol_id=world.manifest.protocol_id,
            cohort_id=world.manifest.cohort_id,
            cohort_fingerprint=world.manifest.cohort_fingerprint,
            pair_manifest_hash=world.manifest.pair_manifest_hash,
            transform_profile_fingerprint="c" * 64,
            transform_runtime_fingerprint=world.manifest.transform_runtime_fingerprint,
            entries=world.entries,
        )
        != world.manifest.preparation_set_fingerprint
    )


def test_the_set_fingerprint_changes_with_the_runtime(world):
    other = make_runtime(pillow_version="12.4.0")
    assert (
        preparation_set_fingerprint(
            dataset_id=world.manifest.dataset_id,
            image_manifest_hash=world.manifest.image_manifest_hash,
            protocol_id=world.manifest.protocol_id,
            cohort_id=world.manifest.cohort_id,
            cohort_fingerprint=world.manifest.cohort_fingerprint,
            pair_manifest_hash=world.manifest.pair_manifest_hash,
            transform_profile_fingerprint=world.manifest.transform_profile_fingerprint,
            transform_runtime_fingerprint=other.runtime_fingerprint,
            entries=world.entries,
        )
        != world.manifest.preparation_set_fingerprint
    )


def test_the_timestamp_does_not_affect_the_set_fingerprint(world):
    """The same 3,000 images materialised again tomorrow are the same set.

    That is what makes a prepared-image set reusable evidence rather than a
    build artefact (docs/adr/0033).
    """
    later = dataclasses.replace(world.manifest, created_utc="2099-01-01T00:00:00+00:00")
    assert later.preparation_set_fingerprint == world.manifest.preparation_set_fingerprint
    assert later.preparation_set_id == world.manifest.preparation_set_id


def test_reordering_the_entries_changes_the_ordered_hash(world):
    shuffled = (world.entries[1], world.entries[0], *world.entries[2:])
    assert ordered_prepared_entries_hash(shuffled) != ordered_prepared_entries_hash(
        world.entries
    )


def test_the_set_id_is_derived_from_the_fingerprint(world):
    assert world.manifest.preparation_set_id == preparation_set_id(
        world.manifest.preparation_set_fingerprint
    )
    with pytest.raises(ValueError, match="must be derived"):
        dataclasses.replace(world.manifest, preparation_set_id="prepset_000000000000")


def test_a_set_holding_no_images_is_not_a_set(world):
    with pytest.raises(ValueError, match="total_images"):
        dataclasses.replace(world.manifest, total_images=0)


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    (
        ("dataset_id", "other_dataset"),
        ("image_manifest_hash", "a" * 64),
        ("protocol_id", "other_protocol"),
        ("cohort_id", "other_cohort"),
        ("cohort_fingerprint", "b" * 64),
        ("pair_manifest_hash", "c" * 64),
    ),
)
def test_rehashed_source_identity_tampering_is_rejected(
    world, field_name, forged_value
):
    """Recomputing every prepared-set id cannot forge external authority."""
    definition = _redefine(world.definition, **{field_name: forged_value})
    manifest = _remanifest(world, definition)
    issues = preparation_source_binding_issues(
        manifest=manifest,
        definition=definition,
        source_bundle=world.source_bundle,
    )
    assert any(field_name in issue for issue in issues)


def test_rehashed_participating_image_identity_tampering_is_rejected(world):
    forged_ids = world.definition.ordered_image_ids[:-1]
    definition = _redefine(
        world.definition,
        ordered_image_ids=forged_ids,
        expected_total_images=len(forged_ids),
    )
    issues = preparation_source_binding_issues(
        manifest=world.manifest,
        definition=definition,
        source_bundle=world.source_bundle,
    )
    assert any("ordered participating image ids" in issue for issue in issues)


# ----------------------------------------------------------------- internals


def _set_fingerprint(world, entries):
    return preparation_set_fingerprint(
        dataset_id=world.manifest.dataset_id,
        image_manifest_hash=world.manifest.image_manifest_hash,
        protocol_id=world.manifest.protocol_id,
        cohort_id=world.manifest.cohort_id,
        cohort_fingerprint=world.manifest.cohort_fingerprint,
        pair_manifest_hash=world.manifest.pair_manifest_hash,
        transform_profile_fingerprint=world.manifest.transform_profile_fingerprint,
        transform_runtime_fingerprint=world.manifest.transform_runtime_fingerprint,
        entries=entries,
    )


def _entry_with_different_hash(entry):
    """A stand-in whose ``entry_hash`` differs, without rebuilding the entry."""
    from types import SimpleNamespace

    return SimpleNamespace(
        ordinal=entry.ordinal, image_id=entry.image_id, entry_hash="f" * 64
    )


def _remanifest(world, definition: PreparationDefinition) -> PreparedImageSetManifest:
    fingerprint = preparation_set_fingerprint(
        dataset_id=definition.dataset_id,
        image_manifest_hash=definition.image_manifest_hash,
        protocol_id=definition.protocol_id,
        cohort_id=definition.cohort_id,
        cohort_fingerprint=definition.cohort_fingerprint,
        pair_manifest_hash=definition.pair_manifest_hash,
        transform_profile_fingerprint=definition.transform_profile_fingerprint,
        transform_runtime_fingerprint=definition.transform_runtime_fingerprint,
        entries=world.entries,
    )
    return PreparedImageSetManifest(
        preparation_set_id=preparation_set_id(fingerprint),
        preparation_set_fingerprint=fingerprint,
        dataset_id=definition.dataset_id,
        image_manifest_hash=definition.image_manifest_hash,
        protocol_id=definition.protocol_id,
        cohort_id=definition.cohort_id,
        cohort_fingerprint=definition.cohort_fingerprint,
        pair_manifest_hash=definition.pair_manifest_hash,
        transform_profile_id=definition.transform_profile_id,
        transform_profile_fingerprint=definition.transform_profile_fingerprint,
        transform_runtime_id=definition.transform_runtime_id,
        transform_runtime_fingerprint=definition.transform_runtime_fingerprint,
        total_images=len(world.entries),
        ordered_entries_hash=ordered_prepared_entries_hash(world.entries),
        created_utc=world.manifest.created_utc,
    )


def _redefine(definition: PreparationDefinition, **changes) -> PreparationDefinition:
    fields = {
        field.name: getattr(definition, field.name)
        for field in dataclasses.fields(definition)
        if field.name not in {"definition_id", "definition_fingerprint", "created_utc"}
    }
    fields.update(changes)
    if "ordered_image_ids" in changes:
        fields["ordered_image_ids_hash"] = ordered_image_ids_hash(
            changes["ordered_image_ids"]
        )
    fingerprint = preparation_definition_fingerprint(_Draft(**fields))
    from fpbench.core.imaging_models import preparation_definition_id

    return PreparationDefinition(
        definition_id=preparation_definition_id(fingerprint),
        definition_fingerprint=fingerprint,
        created_utc=definition.created_utc,
        **fields,
    )


class _Draft:
    __slots__ = (
        "dataset_id",
        "image_manifest_hash",
        "protocol_id",
        "cohort_id",
        "cohort_fingerprint",
        "pair_manifest_hash",
        "transform_profile_id",
        "transform_profile_fingerprint",
        "transform_runtime_id",
        "transform_runtime_fingerprint",
        "expected_total_images",
        "ordered_image_ids",
        "ordered_image_ids_hash",
        "source_commit",
        "source_tree_clean",
    )

    def __init__(self, **fields):
        for name in self.__slots__:
            setattr(self, name, fields[name])
