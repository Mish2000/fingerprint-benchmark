"""Every way two runs can fail to have been given the same inputs.

The positive case is one line and proves almost nothing: two identical sides
compare equal. What this file is for is the other seventeen, because the whole
claim of stage 7C — *the same 6,000 comparisons over the same 3,000 images* —
is only worth as much as the smallest difference the check can still see.

So each test below introduces exactly one difference and requires the report to
stop being clean. A missing pair, an extra pair, a renamed pair, two images the
other way round, a changed release, a changed stage, a changed ground truth, a
different image, a different order, an absent artefact, a different encoded
digest, different pixels, different geometry, a different resolution, a
different input set, a reference run that was never finalised, and a reference
result set that is not the one this experiment names (spec section 11).

An alignment of all but one is a failure and not a near miss: the one row that
differs is the row whose two results could not be attributed to one comparison.
"""

from __future__ import annotations

import dataclasses

import pytest

from fpbench.core.enums import GroundTruth, IntegrityIssueCode, ProtocolStage
from fpbench.core.errors import ResearchPreflightError
from fpbench.core.identifiers import ImageId, PairId
from fpbench.experiments.canonical_run_alignment import (
    SD300_CANONICAL_EXPECTATIONS,
    CanonicalRunAlignmentReport,
    build_canonical_run_alignment_report,
    canonical_run_alignment_fingerprint,
    pair_semantics_row,
    prepared_entry_row,
    require_clean_alignment,
)
from alignmentworld import REFERENCE, build_alignment_world, digest, make_entry

pytestmark = pytest.mark.nbis_contract


@pytest.fixture
def world():
    return build_alignment_world()


def align(world, *, reference=None, candidate=None, expected=REFERENCE):
    return build_canonical_run_alignment_report(
        reference=reference if reference is not None else world.side("reference"),
        candidate=candidate if candidate is not None else world.side("candidate"),
        expected_reference=expected,
        expectations=world.expectations,
    )


def codes(report) -> set[str]:
    return {issue.code.value for issue in report.issues}


# --------------------------------------------------------------- the positive


def test_two_identical_sides_align(world):
    report = align(world)
    assert report.is_clean
    assert report.equal_pair_ids == world.expectations.pair_count
    assert report.equal_pair_semantics == world.expectations.pair_count
    assert report.equal_prepared_entries == world.expectations.prepared_entry_count
    assert report.issues == ()
    require_clean_alignment(report)


def test_a_clean_report_names_the_reference_chain(world):
    report = align(world)
    assert report.reference_run_id == REFERENCE.run_id
    assert report.reference_plan_id == REFERENCE.plan_id
    assert report.reference_result_set_id == REFERENCE.result_set_id
    assert report.preparation_set_id == REFERENCE.preparation_set_id
    assert report.candidate_run_id == "run_111111111111"


def test_the_candidate_may_have_no_run_yet(world):
    """Preparation compares *before* the run exists (spec section 24)."""
    report = align(
        world,
        candidate=world.side("candidate", run_id=None, plan_id=None),
    )
    assert report.is_clean
    assert report.candidate_run_id is None
    assert report.candidate_plan_id is None


# ------------------------------------------------------------------- the pairs


def test_one_missing_pair_is_a_failure(world):
    pairs = dict(world.pairs)
    dropped = world.pair_sequence[7]
    pairs.pop(dropped)
    report = align(
        world,
        candidate=world.side(
            "candidate",
            pairs=pairs,
            pair_sequence=tuple(p for p in world.pair_sequence if p != dropped),
        ),
    )
    assert not report.is_clean
    assert report.equal_pair_ids < world.expectations.pair_count
    assert IntegrityIssueCode.PAIR_ID_MISMATCH.value in codes(report)


def test_one_extra_pair_is_a_failure(world):
    extra = "sd300a_plain_self_p999"
    pairs = dict(world.pairs)
    pairs[extra] = dataclasses.replace(
        world.pairs[world.pair_sequence[0]], pair_id=PairId(extra)
    )
    report = align(
        world,
        candidate=world.side(
            "candidate", pairs=pairs, pair_sequence=world.pair_sequence + (extra,)
        ),
    )
    assert not report.is_clean
    assert report.candidate_pair_count == world.expectations.pair_count + 1
    assert IntegrityIssueCode.PAIR_ID_MISMATCH.value in codes(report)


def test_one_renamed_pair_id_is_a_failure(world):
    original = world.pair_sequence[3]
    renamed = "sd300a_plain_self_p777"
    pairs = {
        (renamed if key == original else key): (
            dataclasses.replace(value, pair_id=PairId(renamed))
            if key == original
            else value
        )
        for key, value in world.pairs.items()
    }
    sequence = tuple(renamed if p == original else p for p in world.pair_sequence)
    report = align(
        world, candidate=world.side("candidate", pairs=pairs, pair_sequence=sequence)
    )
    assert not report.is_clean
    assert report.equal_pair_ids < world.expectations.pair_count


def test_swapping_left_and_right_is_a_failure(world):
    """Left is the probe and right is the gallery (spec section 16)."""
    target = next(
        pair_id
        for pair_id, pair in world.pairs.items()
        if pair.left_image_id != pair.right_image_id
    )
    pair = world.pairs[target]
    pairs = dict(world.pairs)
    pairs[target] = dataclasses.replace(
        pair, left_image_id=pair.right_image_id, right_image_id=pair.left_image_id
    )
    report = align(world, candidate=world.side("candidate", pairs=pairs))
    assert not report.is_clean
    assert report.equal_pair_ids == world.expectations.pair_count
    assert report.equal_pair_semantics == world.expectations.pair_count - 1
    assert IntegrityIssueCode.IMAGE_IDS_MISMATCH.value in codes(report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("release", "SD300C"),
        ("protocol_stage", ProtocolStage.PLAIN_ROLL_NON_MATED),
        ("ground_truth", GroundTruth.NON_MATED),
        ("left_image_id", ImageId("sd300a_s0002_plain_f01")),
        ("right_image_id", ImageId("sd300a_s0002_roll_f01")),
    ],
)
def test_one_changed_field_is_a_failure(world, field, value):
    target = world.pair_sequence[0]
    pairs = dict(world.pairs)
    pairs[target] = dataclasses.replace(world.pairs[target], **{field: value})
    report = align(world, candidate=world.side("candidate", pairs=pairs))
    assert not report.is_clean
    assert report.equal_pair_semantics == world.expectations.pair_count - 1


def test_a_reordered_sequence_is_a_failure(world):
    """The order a run walks its plan in is part of the plan (docs/adr/0011)."""
    sequence = list(world.pair_sequence)
    sequence[0], sequence[1] = sequence[1], sequence[0]
    report = align(
        world, candidate=world.side("candidate", pair_sequence=tuple(sequence))
    )
    assert not report.is_clean
    assert report.equal_pair_ids == world.expectations.pair_count - 2
    assert report.equal_pair_semantics == world.expectations.pair_count
    assert IntegrityIssueCode.PLAN_CONFLICT.value in codes(report)


def test_a_duplicated_pair_id_is_a_failure(world):
    sequence = world.pair_sequence + (world.pair_sequence[0],)
    report = align(
        world, candidate=world.side("candidate", pair_sequence=sequence)
    )
    assert not report.is_clean
    assert IntegrityIssueCode.DUPLICATE_PAIR_ID.value in codes(report)


def test_a_missing_release_cell_is_a_failure(world):
    """Every release-and-stage cell holds the same number of pairs."""
    dropped = {
        pair_id
        for pair_id, pair in world.pairs.items()
        if pair.release == "SD300B" and pair.protocol_stage is ProtocolStage.ROLL_SELF
    }
    pairs = {k: v for k, v in world.pairs.items() if k not in dropped}
    report = align(
        world,
        reference=world.side(
            "reference",
            pairs=pairs,
            pair_sequence=tuple(p for p in world.pair_sequence if p not in dropped),
        ),
        candidate=world.side(
            "candidate",
            pairs=pairs,
            pair_sequence=tuple(p for p in world.pair_sequence if p not in dropped),
        ),
    )
    assert not report.is_clean
    assert IntegrityIssueCode.PLAN_CONFLICT.value in codes(report)


# -------------------------------------------------------- the prepared images


def test_a_missing_prepared_image_is_a_failure(world):
    entries = dict(world.entries)
    entries.pop(sorted(entries)[0])
    report = align(world, candidate=world.side("candidate", prepared_entries=entries))
    assert not report.is_clean
    assert report.candidate_prepared_entries == (
        world.expectations.prepared_entry_count - 1
    )
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH.value in codes(report)


@pytest.mark.parametrize("changed", ["file", "pixels", "source"])
def test_a_changed_digest_is_a_failure(world, changed):
    """Same image, different bytes: a different artefact under the same name."""
    image_id = sorted(world.entries)[0]
    entries = dict(world.entries)
    entries[image_id] = make_entry(
        image_id=image_id,
        ordinal=world.entries[image_id].ordinal,
        source_ppi=world.entries[image_id].source_effective_ppi,
        seed=changed,
    )
    report = align(world, candidate=world.side("candidate", prepared_entries=entries))
    assert not report.is_clean
    assert report.equal_prepared_entries == (
        world.expectations.prepared_entry_count - 1
    )


def test_different_output_geometry_is_a_failure(world):
    """A 250 ppi artefact is not the 500 ppi one the reference run opened."""
    image_id = next(
        key
        for key, entry in sorted(world.entries.items())
        if entry.source_effective_ppi > 500
    )
    entries = dict(world.entries)
    entries[image_id] = make_entry(
        image_id=image_id,
        ordinal=world.entries[image_id].ordinal,
        source_ppi=world.entries[image_id].source_effective_ppi,
        output_ppi=250,
    )
    report = align(world, candidate=world.side("candidate", prepared_entries=entries))
    assert not report.is_clean
    row = prepared_entry_row(entries[image_id], "SD300B")
    assert row["output_ppi"] == "250"


def test_a_changed_release_attribution_is_a_failure(world):
    """The same artefact filed under a different delivery is not the same row."""
    image_id = sorted(world.entries)[0]
    releases = dict(world.image_releases)
    releases[image_id] = "SD300C"
    report = align(world, candidate=world.side("candidate", image_releases=releases))
    assert not report.is_clean
    assert report.equal_prepared_entries == (
        world.expectations.prepared_entry_count - 1
    )


def test_an_uneven_release_split_is_a_failure(world):
    entries = {
        key: value
        for key, value in world.entries.items()
        if world.image_releases[key] != "SD300C" or not key.endswith("roll_f01")
    }
    report = align(
        world,
        reference=world.side("reference", prepared_entries=entries),
        candidate=world.side("candidate", prepared_entries=entries),
    )
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH.value in codes(report)


# --------------------------------------------------------- the shared identity


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("protocol_id", "sd300_other", IntegrityIssueCode.PLAN_CONFLICT),
        ("cohort_id", "sd300_other_test_000000000000", IntegrityIssueCode.PLAN_CONFLICT),
        (
            "pair_manifest_hash",
            digest("a different manifest"),
            IntegrityIssueCode.PAIR_MANIFEST_HASH_MISMATCH,
        ),
        (
            "preparation_set_fingerprint",
            digest("a different set"),
            IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
        ),
    ],
)
def test_the_two_sides_must_share_their_provenance(world, field, value, code):
    report = align(world, candidate=world.side("candidate", **{field: value}))
    assert not report.is_clean
    assert code.value in codes(report)


def test_a_new_preparation_set_is_refused(world):
    """Stage 7C may not materialise a set of its own (spec section 3)."""
    report = align(
        world,
        candidate=world.side("candidate", preparation_set_id="prepset_eeeeeeeeeeee"),
    )
    assert not report.is_clean
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH.value in codes(report)


# ------------------------------------------------------------ the reference


def test_a_reference_run_that_is_not_research_ready_is_refused(world):
    report = align(
        world,
        reference=world.side(
            "reference", research_ready=False, research_status="partial"
        ),
    )
    assert not report.is_clean
    assert any("partial" in issue.message for issue in report.issues)


def test_the_wrong_reference_result_set_is_refused(world):
    report = align(
        world,
        reference=world.side("reference", result_set_id="resultset_ffffffffffff"),
    )
    assert not report.is_clean
    assert any("result_set_id" in issue.message for issue in report.issues)


def test_the_wrong_reference_run_is_refused(world):
    report = align(
        world, reference=world.side("reference", run_id="run_999999999999")
    )
    assert not report.is_clean
    assert any("run_id" in issue.message for issue in report.issues)


# ------------------------------------------------------------- the fingerprint


def test_the_report_is_deterministic_apart_from_the_timestamp(world):
    first = align(world)
    second = align(world)
    assert first.alignment_fingerprint == second.alignment_fingerprint
    assert dataclasses.replace(first, inspected_utc="") == dataclasses.replace(
        second, inspected_utc=""
    )


def test_the_timestamp_is_outside_the_fingerprint(world):
    report = align(world)
    moved = dataclasses.replace(report, inspected_utc="2099-01-01T00:00:00+00:00")
    assert moved.alignment_fingerprint == report.alignment_fingerprint


def test_an_edited_count_no_longer_fingerprints(world):
    report = align(world)
    with pytest.raises(ValueError, match="alignment_fingerprint"):
        dataclasses.replace(report, equal_pair_ids=report.equal_pair_ids - 1)


def test_an_edited_digest_no_longer_fingerprints(world):
    report = align(world)
    with pytest.raises(ValueError, match="alignment_fingerprint"):
        dataclasses.replace(report, pair_semantics_sha256=digest("something else"))


def test_dropping_an_issue_no_longer_fingerprints(world):
    report = align(
        world, reference=world.side("reference", run_id="run_999999999999")
    )
    assert report.issues
    with pytest.raises(ValueError, match="alignment_fingerprint"):
        dataclasses.replace(report, issues=())


def test_a_different_experiment_fingerprints_differently(world):
    first = align(world)
    other = build_alignment_world(per_cell=3)
    second = align(other)
    assert first.alignment_fingerprint != second.alignment_fingerprint


def test_the_fingerprint_helper_is_the_one_the_report_uses(world):
    report = align(world)
    assert report.alignment_fingerprint == canonical_run_alignment_fingerprint(
        reference_run_id=report.reference_run_id,
        reference_plan_id=report.reference_plan_id,
        reference_result_set_id=report.reference_result_set_id,
        candidate_run_id=report.candidate_run_id,
        candidate_plan_id=report.candidate_plan_id,
        pair_manifest_hash=report.pair_manifest_hash,
        preparation_set_id=report.preparation_set_id,
        preparation_set_fingerprint=report.preparation_set_fingerprint,
        reference_pair_count=report.reference_pair_count,
        candidate_pair_count=report.candidate_pair_count,
        equal_pair_ids=report.equal_pair_ids,
        equal_pair_semantics=report.equal_pair_semantics,
        reference_prepared_entries=report.reference_prepared_entries,
        candidate_prepared_entries=report.candidate_prepared_entries,
        equal_prepared_entries=report.equal_prepared_entries,
        pair_id_sequence_sha256=report.pair_id_sequence_sha256,
        pair_semantics_sha256=report.pair_semantics_sha256,
        prepared_entries_sha256=report.prepared_entries_sha256,
        issues=report.issues,
    )


# ------------------------------------------------------------------ the rules


def test_all_but_one_is_still_a_failure(world):
    """Spec section 10: 5,999 of 6,000 is a total failure."""
    target = world.pair_sequence[0]
    pairs = dict(world.pairs)
    pairs[target] = dataclasses.replace(
        world.pairs[target], ground_truth=GroundTruth.NON_MATED
    )
    report = align(world, candidate=world.side("candidate", pairs=pairs))
    assert report.equal_pair_semantics == world.expectations.pair_count - 1
    assert not report.is_clean
    with pytest.raises(ResearchPreflightError, match="not aligned"):
        require_clean_alignment(report)


def test_the_default_expectations_are_the_sd300_shape():
    """The numbers ``is_clean`` compares against when nobody says otherwise."""
    assert SD300_CANONICAL_EXPECTATIONS.pair_count == 6000
    assert SD300_CANONICAL_EXPECTATIONS.prepared_entry_count == 3000
    assert SD300_CANONICAL_EXPECTATIONS.pairs_per_release_stage == 500
    assert SD300_CANONICAL_EXPECTATIONS.prepared_entries_per_release == 1000
    assert SD300_CANONICAL_EXPECTATIONS.releases == ("SD300A", "SD300B", "SD300C")
    assert (
        CanonicalRunAlignmentReport.__dataclass_fields__["expectations"].default
        is SD300_CANONICAL_EXPECTATIONS
    )


def test_the_expectations_must_be_arithmetically_consistent():
    from fpbench.experiments.canonical_run_alignment import AlignmentExpectations

    with pytest.raises(ValueError, match="not 6000"):
        AlignmentExpectations(
            pair_count=6000,
            prepared_entry_count=3000,
            pairs_per_release_stage=499,
            prepared_entries_per_release=1000,
            releases=("SD300A", "SD300B", "SD300C"),
        )


def test_the_semantics_row_is_written_out_rather_than_reflected(world):
    """Adding a field silently would weaken every stored digest."""
    row = pair_semantics_row(world.pairs[world.pair_sequence[0]])
    assert sorted(row) == [
        "ground_truth",
        "left_image_id",
        "pair_id",
        "protocol_stage",
        "release",
        "right_image_id",
    ]


def test_the_prepared_row_covers_the_nine_required_fields(world):
    image_id = sorted(world.entries)[0]
    row = prepared_entry_row(world.entries[image_id], "SD300A")
    assert sorted(row) == [
        "entry_hash",
        "image_id",
        "output_height",
        "output_ppi",
        "output_width",
        "pixel_sha256",
        "prepared_sha256",
        "release",
        "source_sha256",
        "transform_action",
    ]
