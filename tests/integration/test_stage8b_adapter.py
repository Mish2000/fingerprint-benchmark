"""The whole route, end to end, on the pinned runtime.

SELF independence is the reason several of these look repetitive.  A SELF
comparison whose two sides came from one extraction measures nothing, so the
call counts and the object identities are what is asserted — not the equality
of the representations, which is expected and is allowed.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from fpbench.core.flx_errors import FlxArtifactError, FlxError, FlxScoreError
from fpbench.flx import fixtures, identity
from fpbench.flx.artifacts import FlxRuntimeBundle, verify_bundle_artifacts
from fpbench.flx.integration import FlxLearnedFingerprintIntegration
from fpbench.flx.score import canonical_decimal_text

pytestmark = pytest.mark.flx_runtime

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def adapter():
    bundle = FlxRuntimeBundle.from_environment()
    try:
        verify_bundle_artifacts(bundle)
    except FlxArtifactError as exc:
        pytest.skip(f"no verified flx runtime bundle: {exc}")
    integration = FlxLearnedFingerprintIntegration(bundle)
    integration.load_runtime()
    try:
        yield integration
    finally:
        integration.close()


def _represent(adapter, name: str):
    return adapter.extract(adapter.preprocess(fixtures.build_fixture(name)))


# ------------------------------------------------------------------- score


def test_a_comparison_returns_a_decimal_inside_the_nominal_range(adapter) -> None:
    left = _represent(adapter, "fixture_synthetic_ridges")
    right = _represent(adapter, "fixture_gradient")

    score = adapter.compare(left, right)

    assert isinstance(score, Decimal)
    assert not isinstance(score, float)
    assert Decimal("-2") <= score <= Decimal("2")


def test_a_self_comparison_of_an_identical_image_is_two_within_float32(adapter) -> None:
    # Two unit vectors dotted with themselves give 1 + 1. This is an arithmetic
    # property of the comparator, not a biometric claim about the fixture, and
    # it lands within a couple of float32 ulps rather than exactly on 2.
    representation = _represent(adapter, "fixture_synthetic_ridges")

    score = adapter.compare(representation, representation)

    assert abs(score - Decimal("2")) <= Decimal(
        identity.SCORE_RANGE_VALIDATION_TOLERANCE
    )


def test_the_comparison_is_symmetric(adapter) -> None:
    left = _represent(adapter, "fixture_seeded_noise")
    right = _represent(adapter, "fixture_synthetic_ridges")

    forward = adapter.compare(left, right)
    backward = adapter.compare(right, left)

    # The tolerance was fixed at zero before the probe ran (spec section 18).
    assert forward == backward


def test_the_score_is_the_sum_of_the_two_branch_scores(adapter) -> None:
    left = _represent(adapter, "fixture_gradient")
    right = _represent(adapter, "fixture_seeded_noise")

    payload = adapter._require_session().request(
        "compare",
        deadline_seconds=float(adapter.policy.compare_deadline_seconds),
        left=left.as_request(),
        right=right.as_request(),
    )["result"]
    total = float(payload["texture_score"]) + float(payload["minutia_score"])

    assert canonical_decimal_text(total) == payload["raw_score"]


def test_no_threshold_or_decision_ever_reaches_the_caller(adapter) -> None:
    described = adapter.describe_operation()
    validated = adapter.validate_runtime()

    for key in ("threshold", "decision", "match", "non_match", "eligible"):
        assert key not in described
        assert key not in validated


# ------------------------------------------------------- SELF independence


def test_self_uses_two_preprocess_calls_and_two_extract_calls(adapter) -> None:
    payload = fixtures.build_fixture("fixture_synthetic_ridges")
    before_preprocess = adapter.preprocess_calls
    before_extract = adapter.extract_calls

    left_input = adapter.preprocess(payload)
    left = adapter.extract(left_input)
    right_input = adapter.preprocess(payload)
    right = adapter.extract(right_input)
    score = adapter.compare(left, right)

    assert adapter.preprocess_calls - before_preprocess == 2
    assert adapter.extract_calls - before_extract == 2
    # Two independent operations, not one reused.
    assert left_input is not right_input
    assert left is not right
    assert left.texture_bytes is not right.texture_bytes
    # Equality between them is expected and allowed.
    assert left.content_hash == right.content_hash
    assert abs(score - Decimal("2")) <= Decimal(
        identity.SCORE_RANGE_VALIDATION_TOLERANCE
    )


def test_a_second_extraction_is_not_served_from_an_image_cache(adapter) -> None:
    payload = fixtures.build_fixture("fixture_white")
    first_input = adapter.preprocess(payload)
    second_input = adapter.preprocess(payload)

    # Equal content, distinct objects: nothing was looked up by image digest.
    assert first_input.content_hash == second_input.content_hash
    assert first_input is not second_input
    assert first_input.values is not second_input.values


def test_the_adapter_holds_nothing_between_operations(adapter) -> None:
    import gc

    from fpbench.flx.representation import FlxRepresentation, ModelInput

    before = len([obj for obj in gc.get_objects() if isinstance(obj, FlxRepresentation)])
    for name in ("fixture_white", "fixture_gradient"):
        adapter.extract(adapter.preprocess(fixtures.build_fixture(name)))
    gc.collect()
    after = len([obj for obj in gc.get_objects() if isinstance(obj, FlxRepresentation)])

    # Whatever the caller keeps is the caller's; the adapter itself keeps none.
    assert after <= before + 1
    assert not any(
        isinstance(value, (FlxRepresentation, ModelInput))
        for value in vars(adapter).values()
    )


# ---------------------------------------------------------------- metadata


def test_validate_runtime_reports_only_what_is_running(adapter) -> None:
    report = adapter.validate_runtime()

    assert report["runtime_profile_id"] == identity.RUNTIME_PROFILE_ID
    assert report["device"] == "cpu"
    assert report["cuda_available"] is False
    assert report["torch_num_threads"] == 1
    assert report["checkpoint_loaded"] is True
    assert report["model_in_eval_mode"] is True
    assert report["gradients_disabled"] is True
    assert report["missing_state_dict_keys"] == ()
    assert report["unexpected_state_dict_keys"] == ()
    assert report["network_attempts"] == 0


def test_describe_operation_is_constant_across_calls(adapter) -> None:
    assert adapter.describe_operation() == adapter.describe_operation()


def test_loading_the_runtime_twice_is_refused(adapter) -> None:
    with pytest.raises(FlxError, match="already loaded its runtime"):
        adapter.load_runtime()


# ------------------------------------------------------ negative comparisons


def test_a_representation_of_the_wrong_width_is_refused(adapter) -> None:
    with pytest.raises(FlxError, match="COMPARE_WRONG_VECTOR_LENGTH|takes representations"):
        adapter._require_session().request(
            "compare",
            deadline_seconds=float(adapter.policy.compare_deadline_seconds),
            left={"texture": "", "minutia": ""},
            right={"texture": "", "minutia": ""},
        )


def test_a_score_the_worker_reports_outside_the_range_is_refused() -> None:
    from fpbench.flx.score import score_from_worker

    with pytest.raises(FlxScoreError, match="outside the nominal range"):
        score_from_worker(
            {"texture_score": "1.5", "minutia_score": "1.5", "raw_score": "3"}
        )
