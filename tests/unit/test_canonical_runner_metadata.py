"""What a canonical result records about the inputs it was produced from.

The runner is algorithm-agnostic and stays that way: it asks the *preparer* what
to record and stores what it is told, prefixing the per-side keys. There is no
``if resolution_mode == "canonical_500"`` in the runner, in the executor or in
the planner, and these tests are what makes that checkable — the same runner
produces bare metadata for the identity preparer and full preparation provenance
for the canonical one, with no branch in between (docs/adr/0007).
"""

from __future__ import annotations

import pytest

from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.result_models import raw_result_hash
from fpbench.imaging.canonical500 import (
    PREPARER_ID,
    RESOLUTION_MODE,
    RUNNER_METADATA_SCHEMA,
    Canonical500ImagePreparer,
)
from fpbench.imaging.identity import IdentityImagePreparer
from canonicalworld import build_canonical_world, publish_receipt_and_marker
from runworld import build_world

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


def _canonical_profile(world) -> ExecutionProfile:
    return ExecutionProfile(
        profile_id="canonical_500_lanczos3_60s_v1",
        preparer_id=PREPARER_ID,
        timeout_seconds=60,
        deterministic_seed=0,
        parameters={
            "resolution_mode": RESOLUTION_MODE,
            "target_ppi": "500",
            "transform_profile_id": world.profile.profile_id,
            "transform_profile_fingerprint": world.profile.profile_fingerprint,
            "preparation_set_id": world.preparation_set_id,
            "preparation_set_fingerprint": world.preparation_set_fingerprint,
            "output_media_type": "image/png",
            "output_pixel_format": "gray8",
            "output_ppi_metadata_policy": "fixed_500",
        },
    )


@pytest.fixture()
def canonical_run(tmp_path):
    """A dummy-matcher run whose inputs come from a real prepared-image set."""
    canonical = build_canonical_world(tmp_path)
    publish_receipt_and_marker(canonical)

    preparer = Canonical500ImagePreparer(
        store=canonical.store,
        preparation_set_id=canonical.preparation_set_id,
        preparation_set_fingerprint=canonical.preparation_set_fingerprint,
    )
    pairs = _pairs_over(canonical)
    world = build_world(
        tmp_path / "run",
        preparer=preparer,
        execution_profile=_canonical_profile(canonical),
        image_index=canonical.images,
        pairs=pairs,
    )
    # The runner's dataset root points at the delivery; the canonical preparer
    # deliberately never reads from it.
    return canonical, world


def _pairs_over(canonical):
    """A tiny protocol over the canonical world: two SELF pairs and one mated."""
    from fpbench.core.enums import GroundTruth, ProtocolStage
    from fpbench.core.identifiers import PairId
    from fpbench.core.models import ComparisonPair

    by_release: dict[str, list] = {}
    for image_id, record in sorted(canonical.images.items()):
        by_release.setdefault(record.release, []).append((image_id, record))

    pairs = []
    for release, entries in sorted(by_release.items()):
        plain = [item for item in entries if item[1].impression.value == "plain"]
        roll = [item for item in entries if item[1].impression.value == "roll"]
        left = plain[0][0]
        right = roll[0][0]
        pairs.append(
            ComparisonPair(
                pair_id=PairId(f"{release.lower()}_selfplain_0"),
                dataset_id="sd300",
                release=release,
                left_image_id=left,
                right_image_id=left,
                ground_truth=GroundTruth.MATED,
                protocol_stage=ProtocolStage.PLAIN_SELF,
            )
        )
        pairs.append(
            ComparisonPair(
                pair_id=PairId(f"{release.lower()}_mated_0"),
                dataset_id="sd300",
                release=release,
                left_image_id=left,
                right_image_id=right,
                ground_truth=GroundTruth.MATED,
                protocol_stage=ProtocolStage.PLAIN_ROLL_MATED,
            )
        )
    return pairs


def test_a_canonical_result_names_the_set_and_both_entries(canonical_run):
    canonical, world = canonical_run
    runner = world.job_runner()
    planned = world.plan.jobs[0]
    pair = world.pair_index[planned.job.pair_id]

    outcome = runner.execute(planned.job, pair)
    metadata = outcome.result.runner_metadata

    assert metadata["preparer_id"] == PREPARER_ID
    assert metadata["preparer_version"] == "1"
    assert metadata["runner_metadata_schema"] == RUNNER_METADATA_SCHEMA
    assert metadata["preparation_set_id"] == canonical.preparation_set_id
    assert (
        metadata["preparation_set_fingerprint"]
        == canonical.preparation_set_fingerprint
    )
    assert metadata["transform_profile_id"] == canonical.profile.profile_id
    assert (
        metadata["transform_profile_fingerprint"]
        == canonical.profile.profile_fingerprint
    )
    assert (
        metadata["transform_runtime_fingerprint"]
        == canonical.runtime.runtime_fingerprint
    )

    left = canonical.entry_for(pair.left_image_id)
    right = canonical.entry_for(pair.right_image_id)
    assert metadata["left_preparation_entry_hash"] == left.entry_hash
    assert metadata["right_preparation_entry_hash"] == right.entry_hash
    assert metadata["left_prepared_sha256"] == left.output_encoded_sha256
    assert metadata["right_prepared_sha256"] == right.output_encoded_sha256
    assert metadata["left_pixel_sha256"] == left.output_pixel_sha256
    assert metadata["right_pixel_sha256"] == right.output_pixel_sha256
    assert metadata["left_source_ppi"] == str(left.source_effective_ppi)
    assert metadata["right_source_ppi"] == str(right.source_effective_ppi)
    assert metadata["left_output_ppi"] == "500"
    assert metadata["right_output_ppi"] == "500"
    assert metadata["left_output_width"] == str(left.output_width)
    assert metadata["left_output_height"] == str(left.output_height)
    assert metadata["right_output_width"] == str(right.output_width)
    assert metadata["right_output_height"] == str(right.output_height)


def test_no_path_appears_anywhere_in_the_metadata(canonical_run):
    canonical, world = canonical_run
    runner = world.job_runner()
    for planned in world.plan.jobs:
        pair = world.pair_index[planned.job.pair_id]
        outcome = runner.execute(planned.job, pair)
        rendered = " ".join(
            f"{key}={value}" for key, value in outcome.result.runner_metadata.items()
        )
        assert str(canonical.workspace) not in rendered
        assert str(canonical.dataset_root) not in rendered
        assert ".png" not in rendered
        assert "/" not in rendered.replace("image/png", "")


def test_the_raw_result_hash_covers_the_preparation_metadata(canonical_run):
    """Change one preparation claim and the stored row is a different row.

    ``raw_result_hash`` folds in ``runner_metadata`` already; this asserts it
    rather than assuming it, because the result-set fingerprint — and therefore
    everything stage 6B will cite — is built from these hashes (spec section 63).
    """
    import dataclasses

    canonical, world = canonical_run
    runner = world.job_runner()
    planned = world.plan.jobs[0]
    pair = world.pair_index[planned.job.pair_id]
    record = runner.execute(planned.job, pair).result

    altered = dataclasses.replace(
        record,
        runner_metadata={
            **dict(record.runner_metadata),
            "left_pixel_sha256": "0" * 64,
        },
    )
    assert raw_result_hash(altered) != raw_result_hash(record)


def test_a_self_comparison_records_the_same_artefact_on_both_sides(canonical_run):
    canonical, world = canonical_run
    runner = world.job_runner()
    self_job = next(
        planned
        for planned in world.plan.jobs
        if world.pair_index[planned.job.pair_id].protocol_stage.value == "plain_self"
    )
    pair = world.pair_index[self_job.job.pair_id]
    metadata = runner.execute(self_job.job, pair).result.runner_metadata

    assert metadata["left_preparation_entry_hash"] == metadata[
        "right_preparation_entry_hash"
    ]
    assert metadata["left_prepared_sha256"] == metadata["right_prepared_sha256"]


def test_an_identity_run_stays_readable_and_records_no_preparation_set(tmp_path):
    """The native experiment is unchanged by any of this.

    Its results gain ``preparer_version`` and ``runner_metadata_schema`` — new
    runs only; nothing already stored is rewritten — and gain nothing else. No
    preparation set, no entry hash, no pixel digest, because there is no set
    (spec section 61).
    """
    world = build_world(tmp_path, preparer=IdentityImagePreparer())
    runner = world.job_runner()
    planned = world.plan.jobs[0]
    metadata = runner.execute(
        planned.job, world.pair_index[planned.job.pair_id]
    ).result.runner_metadata

    assert metadata["preparer_id"] == "identity"
    assert metadata["preparer_version"] == "1"
    assert metadata["runner_metadata_schema"] == "identity_preparation_v1"
    assert not any(key.startswith("preparation_set") for key in metadata)
    assert not any(key.endswith("pixel_sha256") for key in metadata)


def test_the_runner_holds_no_knowledge_of_canonical_preparation():
    """Grep-level, and deliberately so.

    The one thing docs/adr/0007 forbids is the runner knowing which algorithm —
    or which resolution mode — it is serving. A branch on either would make the
    fairness argument depend on reading the code rather than on the design.
    """
    import ast
    from pathlib import Path

    import fpbench.execution.batch_runner as batch_module
    import fpbench.execution.planner as planner_module
    import fpbench.execution.runner as runner_module

    def executable_source(module) -> str:
        """The module's code with every docstring removed.

        Prose is allowed to discuss canonicalisation — the runner's docstring
        explains why it does not branch. Code is not.
        """
        tree = ast.parse(Path(module.__file__).read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                body = getattr(node, "body", [])
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    body.pop(0)
        return ast.unparse(tree)

    for module in (runner_module, batch_module, planner_module):
        code = executable_source(module)
        # ``canonical_pair_order`` in the planner is about pair ordering and is
        # fine; ``canonical_500`` would be the resolution mode leaking in.
        assert "canonical_500" not in code
        assert "resolution_mode" not in code
        assert "resize" not in code.lower()
        assert "lanczos" not in code.lower()
        assert "effective_ppi" not in code
        assert "from PIL" not in code
        assert "fpbench.imaging.canonical" not in code
