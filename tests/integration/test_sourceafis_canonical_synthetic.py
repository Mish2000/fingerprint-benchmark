"""A canonical artefact, through the real Java bridge, into a real result.

Real SourceAFIS, real JVM, no SD300. The point is the *seam*: a
``Canonical500ImagePreparer`` hands the adapter a file it produced hours earlier,
the adapter is told 500 ppi for both sides, and the runner writes a result
carrying the whole preparation provenance. Every one of those steps exists in the
6,000-comparison run and none of them needs a restricted dataset to exercise.

The images are synthetic ridge patterns. SourceAFIS may well decline to extract a
template from them, and that is fine and is asserted as such: the test is about
the pipeline, and a template-extraction failure is a recorded scientific outcome
rather than a broken run (docs/adr/0006, docs/adr/0013).
"""

from __future__ import annotations

import pytest

from fpbench.core.enums import ExecutionStatus, FailureCode
from fpbench.core.execution_models import ExecutionProfile
from fpbench.imaging.canonical500 import (
    PREPARER_ID,
    RESOLUTION_MODE,
    RUNNER_METADATA_SCHEMA,
    Canonical500ImagePreparer,
)
from canonicalworld import build_canonical_world, publish_receipt_and_marker
from sourceafis_support import comparison_context, require_bridge

pytestmark = [
    pytest.mark.sourceafis,
    pytest.mark.imaging,
    pytest.mark.canonical500,
]

#: Only extraction and matching may fail here. Anything else means the bridge
#: never got a usable file, which is exactly what this test exists to rule out.
ALLOWED_FAILURES = {
    FailureCode.TEMPLATE_EXTRACTION_FAILED,
    FailureCode.MATCHING_FAILED,
}


def _profile(canonical) -> ExecutionProfile:
    return ExecutionProfile(
        profile_id="canonical_500_lanczos3_60s_v1",
        preparer_id=PREPARER_ID,
        timeout_seconds=60,
        deterministic_seed=0,
        parameters={
            "resolution_mode": RESOLUTION_MODE,
            "target_ppi": "500",
            "transform_profile_id": canonical.profile.profile_id,
            "transform_profile_fingerprint": canonical.profile.profile_fingerprint,
            "preparation_set_id": canonical.preparation_set_id,
            "preparation_set_fingerprint": canonical.preparation_set_fingerprint,
            "output_media_type": "image/png",
            "output_pixel_format": "gray8",
            "output_ppi_metadata_policy": "fixed_500",
        },
    )


def _ridge_raster(width: int, height: int, seed: int) -> bytes:
    """Curved, warped ridges at the requested size.

    Reuses the whorl generator the stage 4A tests already rely on, decoded and
    cropped to whatever the canonical world asked for. A plain gradient would
    contain no minutiae at all and SourceAFIS would decline every one of them,
    which would make this test unable to fail for the right reason.
    """
    import io

    from PIL import Image

    from synthetic_ridges import whorl_png

    # The generator is square and sized by dpi; ask for one at least as large as
    # the target and take the top-left corner.
    dpi = 500
    while True:
        with Image.open(io.BytesIO(whorl_png(dpi, seed % 5))) as image:
            image.load()
            if image.width >= width and image.height >= height:
                return image.crop((0, 0, width, height)).tobytes()
        dpi *= 2


@pytest.fixture(scope="module")
def canonical(tmp_path_factory):
    """A prepared set built from ridge-like synthetic prints, big enough to matter."""
    world = build_canonical_world(
        tmp_path_factory.mktemp("canonical-java"),
        subjects=1,
        fingers=(1, 2),
        base_size=(250, 250),
        raster_builder=_ridge_raster,
    )
    publish_receipt_and_marker(world)
    return world


def test_the_bridge_accepts_a_canonical_artefact_at_500_dpi(canonical, tmp_path):
    adapter, _ = require_bridge()

    preparer = Canonical500ImagePreparer(
        store=canonical.store,
        preparation_set_id=canonical.preparation_set_id,
        preparation_set_fingerprint=canonical.preparation_set_fingerprint,
    )
    preparer.preflight()
    profile = _profile(canonical)

    entry = next(e for e in canonical.entries if e.source_effective_ppi == 2000)
    record = canonical.images[entry.image_id]
    left = preparer.prepare(record, canonical.dataset_root, profile)
    right = preparer.prepare(record, canonical.dataset_root, profile)

    assert left.effective_ppi == 500
    assert right.effective_ppi == 500
    assert left.local_path.suffix == ".png"

    result = adapter.compare(left, right, comparison_context(tmp_path))

    assert result.metadata["left_dpi"] == "500"
    assert result.metadata["right_dpi"] == "500"
    assert result.metadata["sourceafis_version"] == "3.18.1"
    assert result.metadata["template_cache"] == "disabled"

    if result.status is ExecutionStatus.SUCCESS:
        import math

        assert math.isfinite(float(result.raw_score))
        # Two independent extractions, even though both sides are one file
        # (docs/adr/0035).
        assert result.metadata["extraction_count"] == "2"
        assert result.metadata["extraction_policy"] == "independent_both_sides"
    else:
        assert result.failure.code in ALLOWED_FAILURES, (
            f"the bridge failed with {result.failure.code.value}, which means it "
            "never got a usable canonical file"
        )

    # No threshold, no decision, no artefact, in either case.
    assert result.artifacts == ()
    assert "threshold" not in result.metadata
    assert "decision" not in result.metadata


def test_a_full_job_through_the_runner_records_canonical_provenance(
    canonical, tmp_path
):
    """The whole seam, ending in a stored ``RawResultRecord``."""
    from fpbench.core.enums import GroundTruth, ProtocolStage
    from fpbench.core.identifiers import PairId
    from fpbench.core.models import ComparisonPair
    from runworld import build_world

    require_bridge()
    adapter, _ = require_bridge()

    preparer = Canonical500ImagePreparer(
        store=canonical.store,
        preparation_set_id=canonical.preparation_set_id,
        preparation_set_fingerprint=canonical.preparation_set_fingerprint,
    )
    entry = next(e for e in canonical.entries if e.source_effective_ppi == 1000)
    other = next(
        e
        for e in canonical.entries
        if e.image_id != entry.image_id
        and canonical.images[e.image_id].release
        == canonical.images[entry.image_id].release
    )
    pairs = [
        ComparisonPair(
            pair_id=PairId("canonical_mated_0"),
            dataset_id="sd300",
            release=canonical.images[entry.image_id].release,
            left_image_id=entry.image_id,
            right_image_id=other.image_id,
            ground_truth=GroundTruth.MATED,
            protocol_stage=ProtocolStage.PLAIN_ROLL_MATED,
        )
    ]
    world = build_world(
        tmp_path / "run",
        adapter=adapter,
        preparer=preparer,
        execution_profile=_profile(canonical),
        image_index=canonical.images,
        pairs=pairs,
    )
    planned = world.plan.jobs[0]
    stored = world.job_runner().execute(
        planned.job, world.pair_index[planned.job.pair_id]
    ).result

    metadata = stored.runner_metadata
    assert metadata["runner_metadata_schema"] == RUNNER_METADATA_SCHEMA
    assert metadata["preparation_set_id"] == canonical.preparation_set_id
    assert metadata["left_preparation_entry_hash"] == entry.entry_hash
    assert metadata["right_preparation_entry_hash"] == other.entry_hash
    assert metadata["left_output_ppi"] == metadata["right_output_ppi"] == "500"
    assert stored.adapter_metadata["left_dpi"] == "500"
    assert stored.adapter_metadata["right_dpi"] == "500"

    if stored.status is not ExecutionStatus.SUCCESS:
        assert stored.failure.code in ALLOWED_FAILURES

    # Preparation is a lookup, not a resampling: it costs microseconds, and the
    # real work happened before the run (spec section 74).
    assert stored.timings.preparation_ms < stored.timings.adapter_ms
