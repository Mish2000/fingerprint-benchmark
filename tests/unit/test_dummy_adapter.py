"""The dummy matcher's only job is to be perfectly predictable."""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.adapters.dummy.adapter import (
    ALGORITHM_ID,
    SCORE_SCALE,
    DummyShaAdapter,
    score_for,
)
from fpbench.core.enums import ChecksumStatus, EnvironmentStatus, ScoreDirection
from fpbench.core.execution_models import (
    ComparisonContext,
    PreparedImage,
    descriptor_fingerprint,
)
from fakes import sha256_of

LEFT = sha256_of("left image bytes")
RIGHT = sha256_of("right image bytes")
ABS = Path.cwd().resolve()


def prepared(digest: str, image_id: str = "sd300a_00001000_plain_f01") -> PreparedImage:
    return PreparedImage(
        image_id=image_id,
        local_path=ABS / f"{image_id}.png",
        effective_ppi=500,
        media_type="image/png",
        expected_sha256=digest,
        checksum_status=ChecksumStatus.NOT_VERIFIED,
        preparation_profile_id="identity_png_v1",
        preparation_hash=sha256_of(image_id),
    )


def context(seed: int = 0) -> ComparisonContext:
    return ComparisonContext(
        run_id="run_abc123",
        job_id="job_def456",
        attempt=1,
        working_directory=ABS / "work",
        artifact_directory=ABS / "artifacts",
        timeout_seconds=10.0,
        deterministic_seed=seed,
    )


def compare(seed: int = 0, left: str = LEFT, right: str = RIGHT):
    return DummyShaAdapter().compare(prepared(left), prepared(right), context(seed))


# ------------------------------------------------------------------- descriptor


def test_descriptor_matches_the_specification():
    descriptor = DummyShaAdapter().descriptor
    assert descriptor.algorithm_id == ALGORITHM_ID
    assert descriptor.adapter_id == ALGORITHM_ID
    assert descriptor.adapter_contract_version == "1"
    assert descriptor.implementation_version == "dummy-sha256-v1"
    assert descriptor.score_direction is ScoreDirection.HIGHER_IS_BETTER
    assert descriptor.deterministic
    assert descriptor.capabilities == ()


def test_descriptor_fingerprint_is_stable_across_instances():
    assert descriptor_fingerprint(
        DummyShaAdapter().descriptor
    ) == descriptor_fingerprint(DummyShaAdapter().descriptor)


def test_environment_is_always_ready():
    report = DummyShaAdapter().validate_environment()
    assert report.status is EnvironmentStatus.READY
    assert report.implementation_version
    assert report.dependencies == {}
    assert "python" in report.runtime


def test_rejects_configuration_it_does_not_understand():
    with pytest.raises(ValueError, match="takes no configuration"):
        DummyShaAdapter.from_config({"threshold": 40})


# ------------------------------------------------------------------- scoring


def test_the_same_inputs_and_seed_give_the_same_score():
    assert compare().raw_score == compare().raw_score


def test_a_different_seed_gives_a_different_score():
    assert compare(seed=0).raw_score != compare(seed=1).raw_score


def test_swapping_the_sides_changes_the_score():
    """A symmetric matcher would hide ordering bugs in the runner."""
    forward = score_for(LEFT, RIGHT, 0)
    reversed_ = score_for(RIGHT, LEFT, 0)
    assert forward != reversed_


def test_the_score_is_finite_and_in_range():
    for seed in range(25):
        score = compare(seed=seed).raw_score
        assert 0.0 <= score <= SCORE_SCALE


def test_the_result_declares_the_descriptor_direction():
    result = compare()
    assert result.score_direction is DummyShaAdapter().descriptor.score_direction


def test_no_artifacts_are_produced():
    assert compare().artifacts == ()


def test_the_generator_is_named_in_metadata():
    assert compare().metadata["generator"] == "sha256_ordered_pair_v1"


def test_the_score_ignores_everything_except_digests_and_seed():
    """Image ids, paths and resolutions must not reach the score."""
    adapter = DummyShaAdapter()
    baseline = adapter.compare(prepared(LEFT), prepared(RIGHT), context()).raw_score
    renamed = adapter.compare(
        prepared(LEFT, image_id="sd300c_00009999_roll_f07"),
        prepared(RIGHT, image_id="sd300c_00009999_roll_f08"),
        context(),
    ).raw_score
    assert renamed == baseline


@pytest.mark.parametrize(
    "left,right,seed,expected",
    [
        ("0" * 64, "1" * 64, 0, 63.45074491837212),
        ("a" * 64, "b" * 64, 7, 88.53207010051759),
    ],
)
def test_known_scores_are_pinned(left, right, seed, expected):
    """A regression guard: changing the formula must break this deliberately.

    The dummy adapter's whole value is that a result computed today can be
    reproduced next year. If the payload layout, the digest slice or the
    scaling changes, these two numbers move and the change has to be
    acknowledged rather than discovered later in a diff of results.
    """
    assert score_for(left, right, seed) == pytest.approx(expected, abs=1e-12)
