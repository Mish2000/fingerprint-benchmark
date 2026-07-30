"""Grouping comparisons into fingers, and refusing every way of getting it wrong.

The mapping is the join everything conditional depends on. If it silently
mis-grouped — a unit taking its ROLL SELF from a different release, say — the
conditional view would exclude the wrong pairs and no fingerprint anywhere
would notice, because every individual artefact would still be internally
consistent.

So the mapping refuses rather than skips. A missing SELF comparison is not "this
finger is out"; it is "the pair manifest and the protocol disagree", and every
answer derived from it would be meaningless (docs/adr/0023).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from fpbench.core.eligibility_models import eligibility_unit_id
from fpbench.core.enums import (
    ExecutionStatus,
    FingerprintPosition,
    GroundTruth,
    Impression,
    ProtocolStage,
)
from fpbench.core.errors import SelfMappingError
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.models import ComparisonPair
from fpbench.eligibility import (
    build_self_eligibility_units,
    require_self_independence_evidence,
)
from decisionworld import SELF_INDEPENDENCE_METADATA
from runworld import build_world

pytestmark = pytest.mark.decisions


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path, subjects=2, fingers=2, releases=("SD300A", "SD300B"))


def _units(world, *, pairs=None, images=None):
    jobs_by_pair = {
        str(planned.job.pair_id): planned.job.job_id for planned in world.plan.jobs
    }
    return build_self_eligibility_units(
        pairs=pairs if pairs is not None else world.pairs,
        images=images if images is not None else world.images,
        jobs_by_pair=jobs_by_pair,
        protocol_id=world.run.protocol_id,
        cohort_id=str(world.run.cohort_id),
    )


# ------------------------------------------------------------------- shape


def test_one_unit_per_release_subject_and_finger(world):
    units = _units(world)
    assert len(units) == 2 * 2 * 2  # releases x subjects x fingers
    keys = {(unit.release, unit.subject_id, unit.canonical_finger) for unit in units}
    assert len(keys) == len(units)


def test_the_same_finger_in_two_releases_is_two_units(world):
    """500 ppi and 1000 ppi are separate measurements of the same finger."""
    units = _units(world)
    by_finger: dict[tuple[str, int], set[str]] = {}
    for unit in units:
        by_finger.setdefault(
            (unit.subject_id, unit.canonical_finger), set()
        ).add(unit.release)
    for releases in by_finger.values():
        assert releases == {"SD300A", "SD300B"}
    assert len({unit.eligibility_unit_id for unit in units}) == len(units)


def test_each_unit_holds_its_own_three_comparisons(world):
    units = _units(world)
    for unit in units:
        assert unit.plain_self_pair_id != unit.roll_self_pair_id
        assert unit.mated_pair_id not in (
            unit.plain_self_pair_id,
            unit.roll_self_pair_id,
        )
        assert unit.plain_self_job_id and unit.roll_self_job_id and unit.mated_job_id


def test_the_unit_id_does_not_reveal_the_subject(world):
    units = _units(world)
    for unit in units:
        assert unit.subject_id not in unit.eligibility_unit_id
        assert unit.eligibility_unit_id.startswith("selfunit_")


def test_the_unit_id_is_derived_and_stable(world):
    units = _units(world)
    unit = units[0]
    assert unit.eligibility_unit_id == eligibility_unit_id(
        protocol_id=world.run.protocol_id,
        cohort_id=str(world.run.cohort_id),
        release=unit.release,
        subject_id=unit.subject_id,
        canonical_finger=unit.canonical_finger,
    )


def test_impostor_pairs_govern_no_unit(world):
    """A non-mated pair spans two fingers and belongs to neither."""
    units = _units(world)
    impostors = {
        str(pair.pair_id)
        for pair in world.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_NON_MATED
    }
    cited = {unit.plain_self_pair_id for unit in units}
    cited |= {unit.roll_self_pair_id for unit in units}
    cited |= {unit.mated_pair_id for unit in units}
    assert impostors.isdisjoint(cited)


# ----------------------------------------------------------- what is refused


def test_a_missing_plain_self_is_refused(world):
    pairs = [
        pair
        for pair in world.pairs
        if pair.protocol_stage is not ProtocolStage.PLAIN_SELF
        or str(pair.pair_id) != str(world.pairs[0].pair_id)
    ]
    with pytest.raises(SelfMappingError, match="no PLAIN SELF"):
        _units(world, pairs=pairs)


def test_a_missing_roll_self_is_refused(world):
    dropped = next(
        pair
        for pair in world.pairs
        if pair.protocol_stage is ProtocolStage.ROLL_SELF
    )
    pairs = [pair for pair in world.pairs if pair is not dropped]
    with pytest.raises(SelfMappingError, match="no ROLL SELF"):
        _units(world, pairs=pairs)


def test_a_missing_mated_pair_is_refused(world):
    dropped = next(
        pair
        for pair in world.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED
    )
    pairs = [pair for pair in world.pairs if pair is not dropped]
    with pytest.raises(SelfMappingError, match="no mated"):
        _units(world, pairs=pairs)


def test_a_duplicate_plain_self_is_refused(world):
    original = next(
        pair for pair in world.pairs if pair.protocol_stage is ProtocolStage.PLAIN_SELF
    )
    duplicate = replace(original, pair_id=PairId(f"{original.pair_id}_again"))
    with pytest.raises(SelfMappingError, match="two PLAIN SELF"):
        _units(world, pairs=[*world.pairs, duplicate])


def test_a_duplicate_roll_self_is_refused(world):
    original = next(
        pair for pair in world.pairs if pair.protocol_stage is ProtocolStage.ROLL_SELF
    )
    duplicate = replace(original, pair_id=PairId(f"{original.pair_id}_again"))
    with pytest.raises(SelfMappingError, match="two ROLL SELF"):
        _units(world, pairs=[*world.pairs, duplicate])


def test_a_self_pair_comparing_two_images_is_refused(world):
    original = next(
        pair for pair in world.pairs if pair.protocol_stage is ProtocolStage.PLAIN_SELF
    )
    other = next(
        pair
        for pair in world.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_SELF
        and pair.left_image_id != original.left_image_id
    )
    broken = replace(original, right_image_id=other.left_image_id)
    pairs = [broken if pair is original else pair for pair in world.pairs]
    with pytest.raises(SelfMappingError, match="image against itself"):
        _units(world, pairs=pairs)


def test_a_plain_self_built_from_a_rolled_image_is_refused(world):
    plain = next(
        pair for pair in world.pairs if pair.protocol_stage is ProtocolStage.PLAIN_SELF
    )
    roll = next(
        pair for pair in world.pairs if pair.protocol_stage is ProtocolStage.ROLL_SELF
    )
    swapped = replace(
        plain, left_image_id=roll.left_image_id, right_image_id=roll.right_image_id
    )
    pairs = [swapped if pair is plain else pair for pair in world.pairs]
    with pytest.raises(SelfMappingError, match="requires plain"):
        _units(world, pairs=pairs)


def test_a_mated_pair_spanning_two_releases_is_refused(world):
    mated = next(
        pair
        for pair in world.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED
        and pair.release == "SD300A"
    )
    other_release = next(
        pair
        for pair in world.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED
        and pair.release == "SD300B"
    )
    broken = replace(mated, right_image_id=other_release.right_image_id)
    pairs = [broken if pair is mated else pair for pair in world.pairs]
    with pytest.raises(SelfMappingError, match="spans releases"):
        _units(world, pairs=pairs)


def test_a_mated_pair_spanning_two_fingers_is_refused(world):
    mated = next(
        pair
        for pair in world.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED
    )
    other_finger = next(
        pair
        for pair in world.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED
        and pair.release == mated.release
        and pair.right_image_id != mated.right_image_id
        and world.images[pair.left_image_id].subject_id
        == world.images[mated.left_image_id].subject_id
    )
    broken = replace(mated, right_image_id=other_finger.right_image_id)
    pairs = [broken if pair is mated else pair for pair in world.pairs]
    with pytest.raises(SelfMappingError, match="one finger"):
        _units(world, pairs=pairs)


def test_a_mated_pair_with_a_rolled_left_side_is_refused(world):
    mated = next(
        pair
        for pair in world.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED
    )
    broken = replace(mated, left_image_id=mated.right_image_id)
    pairs = [broken if pair is mated else pair for pair in world.pairs]
    with pytest.raises(SelfMappingError, match="plain left side"):
        _units(world, pairs=pairs)


def test_an_image_without_an_anatomical_finger_is_refused(world):
    images = dict(world.images)
    first = next(iter(images))
    images[first] = replace(images[first], position=None)
    with pytest.raises(SelfMappingError, match="no single"):
        _units(world, images=images)


def test_a_pair_with_no_planned_job_is_refused(world):
    jobs_by_pair = {
        str(planned.job.pair_id): planned.job.job_id
        for planned in world.plan.jobs[1:]
    }
    with pytest.raises(SelfMappingError, match="no planned job"):
        build_self_eligibility_units(
            pairs=world.pairs,
            images=world.images,
            jobs_by_pair=jobs_by_pair,
            protocol_id=world.run.protocol_id,
            cohort_id=str(world.run.cohort_id),
        )


# -------------------------------------------------- independence evidence


class _Result:
    """The two fields the independence check reads."""

    def __init__(self, *, metadata, status=ExecutionStatus.SUCCESS, artifacts=()):
        self.job_id = "job_0123456789abcdef"
        self.status = status
        self.adapter_metadata = metadata
        self.artifacts = artifacts


def test_a_self_result_proving_two_extractions_is_accepted():
    require_self_independence_evidence(
        results=[_Result(metadata=dict(SELF_INDEPENDENCE_METADATA))]
    )


@pytest.mark.parametrize(
    "key", ["extraction_policy", "extraction_count", "template_cache"]
)
def test_a_self_result_missing_its_evidence_is_refused(key):
    metadata = dict(SELF_INDEPENDENCE_METADATA)
    metadata.pop(key)
    with pytest.raises(SelfMappingError, match="does not record"):
        require_self_independence_evidence(results=[_Result(metadata=metadata)])


def test_a_self_result_that_reused_one_template_is_refused():
    metadata = dict(SELF_INDEPENDENCE_METADATA) | {"extraction_count": "1"}
    with pytest.raises(SelfMappingError, match="extraction_count"):
        require_self_independence_evidence(results=[_Result(metadata=metadata)])


def test_a_self_result_with_a_cached_template_is_refused():
    metadata = dict(SELF_INDEPENDENCE_METADATA) | {"template_cache": "enabled"}
    with pytest.raises(SelfMappingError, match="template_cache"):
        require_self_independence_evidence(results=[_Result(metadata=metadata)])


def test_a_failed_self_result_needs_no_evidence():
    """It made no claim about how it was performed, because it did not perform."""
    require_self_independence_evidence(
        results=[_Result(metadata={}, status=ExecutionStatus.FAILURE)]
    )
