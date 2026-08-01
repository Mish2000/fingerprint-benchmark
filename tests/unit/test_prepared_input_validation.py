"""The input-set checks belong to every algorithm, not to SourceAFIS.

"This result names an artefact that exists in this exact set, with this width,
this height, this file digest and this raster digest" is the same question for a
Java matcher, for a two-executable pipeline, and for whatever comes next. It is
tested here against the shared helper directly, so that a second algorithm's
validator inherits tested behaviour rather than a second copy of it
(spec section 26).

The whole-run behaviour, over a real canonical set, is covered in
``tests/integration/test_canonical_structural.py``. What this file adds is the
per-check detail and the structural guarantee that there is only one copy.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from fpbench.core.enums import (
    ChecksumStatus,
    ExecutionStatus,
    GroundTruth,
    IntegrityIssueCode,
    ProtocolStage,
    ScoreDirection,
)
from fpbench.core.execution_models import TimingBreakdown
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.imaging_models import (
    PreparedImageEntry,
    prepared_image_entry_hash,
)
from fpbench.core.result_models import RawResultRecord
from fpbench.experiments.prepared_input_validation import (
    CanonicalPreparationExpectations,
    PreparedInputExpectations,
    check_prepared_inputs,
    check_release_source_resolutions,
)
from fakes import comparison_pair

pytestmark = pytest.mark.adapter_contract

LEFT = ImageId("sd300a_00001000_plain_f01")
RIGHT = ImageId("sd300a_00001000_roll_f01")


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def entry(image_id: ImageId, *, source_ppi: int = 1000, output_ppi: int = 500):
    """One entry, with its hash derived the way the real pipeline derives it.

    The entry hash covers the whole entry, so it cannot be invented: the fields
    are assembled first and hashed second, exactly as
    :mod:`fpbench.imaging.canonical` does.
    """
    fields = _entry_fields(image_id, source_ppi=source_ppi, output_ppi=output_ppi)
    return PreparedImageEntry(
        **fields, entry_hash=prepared_image_entry_hash(_EntryDraft(**fields))
    )


class _EntryDraft:
    """An entry before it has a hash, which is what the hash is computed over."""

    def __init__(self, **fields: object) -> None:
        for name, value in fields.items():
            setattr(self, name, value)


def _entry_fields(
    image_id: ImageId, *, source_ppi: int, output_ppi: int
) -> dict[str, object]:
    return dict(
        ordinal=0,
        image_id=image_id,
        source_record_fingerprint=digest(f"{image_id}-source-record"),
        source_expected_sha256=digest(f"{image_id}-source"),
        source_size_bytes=1024,
        source_effective_ppi=source_ppi,
        source_declared_ppi=str(source_ppi),
        source_width=800,
        source_height=800,
        source_pixel_sha256=digest(f"{image_id}-source-pixels"),
        transform_profile_id="canonical_gray8_500ppi_lanczos3_v1",
        transform_profile_fingerprint=digest("profile"),
        transform_runtime_fingerprint=digest("runtime"),
        transform_action="downsample_lanczos3",
        scale_numerator=output_ppi,
        scale_denominator=source_ppi,
        output_width=400,
        output_height=400,
        output_effective_ppi=output_ppi,
        output_pixel_sha256=digest(f"{image_id}-out-pixels"),
        output_encoded_sha256=digest(f"{image_id}-out-encoded"),
        output_size_bytes=512,
        output_media_type="image/png",
        relative_path=f"prepared-images/set/{image_id}.png",
    )


def expectations(**overrides) -> PreparedInputExpectations:
    entries = {LEFT: entry(LEFT), RIGHT: entry(RIGHT)}
    settings: dict[str, object] = {
        "execution_profile_id": "canonical_500_lanczos3_60s_v1",
        "preparer_id": "canonical_500",
        "preparer_version": "1",
        "runner_metadata_schema": "canonical_prepared_v1",
        "preparation_set_id": "prepset_0123456789ab",
        "preparation_set_fingerprint": digest("set"),
        "transform_profile_id": "canonical_gray8_500ppi_lanczos3_v1",
        "transform_profile_fingerprint": digest("profile"),
        "transform_runtime_fingerprint": digest("runtime"),
        "target_ppi": 500,
        "entries": entries,
    }
    settings.update(overrides)
    return PreparedInputExpectations(**settings)  # type: ignore[arg-type]


def runner_metadata(preparation: PreparedInputExpectations) -> dict[str, str]:
    """Exactly what a well-behaved runner would have recorded."""
    metadata = dict(preparation.run_level_metadata())
    for side, image_id in (("left", LEFT), ("right", RIGHT)):
        item = preparation.entries[image_id]
        metadata.update(
            {
                f"{side}_preparation_entry_hash": item.entry_hash,
                f"{side}_prepared_sha256": item.output_encoded_sha256,
                f"{side}_pixel_sha256": item.output_pixel_sha256,
                f"{side}_source_ppi": str(item.source_effective_ppi),
                f"{side}_output_ppi": str(item.output_effective_ppi),
                f"{side}_output_width": str(item.output_width),
                f"{side}_output_height": str(item.output_height),
            }
        )
    return metadata


def record(metadata: dict[str, str]) -> RawResultRecord:
    return RawResultRecord(
        result_id="job_0123456789abcdef",
        run_id="run_0123456789ab",
        job_id="job_0123456789abcdef",
        job_fingerprint=digest("job"),
        protocol_id="sd300_50_subjects",
        cohort_id="synthetic_cohort",
        pair_manifest_hash=digest("pairs"),
        pair_id=PairId("00001000_f01_mated"),
        left_image_id=LEFT,
        right_image_id=RIGHT,
        algorithm_id="sourceafis_java",
        algorithm_fingerprint=digest("algorithm"),
        execution_profile_id="canonical_500_lanczos3_60s_v1",
        execution_profile_hash=digest("profile-hash"),
        attempt=1,
        started_utc="2026-07-30T00:00:00+00:00",
        finished_utc="2026-07-30T00:00:01+00:00",
        status=ExecutionStatus.SUCCESS,
        raw_score=42.0,
        score_direction=ScoreDirection.HIGHER_IS_BETTER,
        failure=None,
        timings=TimingBreakdown(preparation_ms=1.0, adapter_ms=2.0, total_ms=5.0),
        artifacts=(),
        adapter_metadata={},
        runner_metadata=metadata,
    )


def codes(issues) -> list[IntegrityIssueCode]:
    return [issue.code for issue in issues]


# ------------------------------------------------------------------ the model


def test_the_old_name_is_the_same_class():
    assert CanonicalPreparationExpectations is PreparedInputExpectations


def test_run_level_metadata_names_the_set_and_the_transform():
    keys = set(expectations().run_level_metadata())
    assert keys == {
        "preparer_id",
        "preparer_version",
        "runner_metadata_schema",
        "preparation_set_id",
        "preparation_set_fingerprint",
        "transform_profile_id",
        "transform_profile_fingerprint",
        "transform_runtime_fingerprint",
    }


# ------------------------------------------------------------- the per-result


def test_a_result_that_agrees_with_the_set_produces_nothing():
    preparation = expectations()
    issues = list(check_prepared_inputs(record(runner_metadata(preparation)), preparation))
    assert issues == []


def test_a_missing_run_level_key_is_reported_as_missing_metadata():
    preparation = expectations()
    metadata = runner_metadata(preparation)
    del metadata["preparation_set_fingerprint"]
    issues = list(check_prepared_inputs(record(metadata), preparation))
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(issues)


def test_a_run_level_key_that_disagrees_is_a_pipeline_mismatch():
    preparation = expectations()
    metadata = runner_metadata(preparation)
    metadata["preparation_set_id"] = "prepset_ffffffffffff"
    issues = list(check_prepared_inputs(record(metadata), preparation))
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in codes(issues)


@pytest.mark.parametrize(
    "key",
    [
        "left_preparation_entry_hash",
        "left_prepared_sha256",
        "left_pixel_sha256",
        "right_output_width",
        "right_output_height",
        "right_source_ppi",
        "right_output_ppi",
    ],
)
def test_every_per_side_claim_is_checked_against_the_entry(key):
    """Not against another copy of the same claim (spec section 75)."""
    preparation = expectations()
    metadata = runner_metadata(preparation)
    metadata[key] = "0" * 64 if key.endswith(("sha256", "hash")) else "9999"
    issues = list(check_prepared_inputs(record(metadata), preparation))
    assert IntegrityIssueCode.RESULT_PIPELINE_MISMATCH in codes(issues)


def test_a_missing_per_side_key_is_reported():
    preparation = expectations()
    metadata = runner_metadata(preparation)
    del metadata["left_pixel_sha256"]
    issues = list(check_prepared_inputs(record(metadata), preparation))
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(issues)


def test_an_image_with_no_entry_in_the_set_is_caught():
    preparation = expectations(entries={LEFT: entry(LEFT)})
    metadata = runner_metadata(expectations())
    issues = list(check_prepared_inputs(record(metadata), preparation))
    assert any("has no entry in prepared-image set" in i.message for i in issues)


def test_an_artefact_at_the_wrong_resolution_is_caught():
    preparation = expectations(target_ppi=1000)
    metadata = runner_metadata(expectations())
    issues = list(check_prepared_inputs(record(metadata), preparation))
    assert IntegrityIssueCode.RESULT_RESOLUTION_MISMATCH in codes(issues)


# ------------------------------------------------------- release resolutions


def test_a_release_scaled_from_the_wrong_source_resolution_is_caught():
    preparation = expectations()
    pairs = {
        PairId("00001000_f01_mated"): comparison_pair(
            pair_id="00001000_f01_mated",
            left_image_id=str(LEFT),
            right_image_id=str(RIGHT),
            stage=ProtocolStage.PLAIN_ROLL_MATED,
            ground_truth=GroundTruth.MATED,
            release="SD300B",
        )
    }
    issues = list(
        check_release_source_resolutions(
            pairs=pairs,
            preparation=preparation,
            expected_source_ppi={"SD300B": 2000},
        )
    )
    assert IntegrityIssueCode.RESULT_RESOLUTION_MISMATCH in codes(issues)
    assert all("scaled from" in issue.message for issue in issues)


def test_a_release_nobody_declared_is_not_checked():
    preparation = expectations()
    pairs = {
        PairId("00001000_f01_mated"): comparison_pair(
            pair_id="00001000_f01_mated",
            left_image_id=str(LEFT),
            right_image_id=str(RIGHT),
            release="SYNTHETIC",
        )
    }
    issues = list(
        check_release_source_resolutions(
            pairs=pairs, preparation=preparation, expected_source_ppi={"SD300A": 500}
        )
    )
    assert issues == []


# ------------------------------------------------------------- one copy only


def test_the_sourceafis_validator_calls_the_shared_helper():
    from fpbench.experiments import sourceafis_validation

    source = Path(sourceafis_validation.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert "_check_preparation" not in defined, (
        "the prepared-input checks were copied back into the SourceAFIS validator"
    )
    assert "_check_release_source_resolutions" not in defined

    called = {
        ast.unparse(node.func).rsplit(".", 1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "check_prepared_inputs" in called
    assert "check_release_source_resolutions" in called


def test_the_shared_helper_imports_no_adapter():
    """Prose may recall where the checks came from; code may not depend on it."""
    from fpbench.experiments import prepared_input_validation

    tree = ast.parse(
        Path(prepared_input_validation.__file__).read_text(encoding="utf-8")
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    offenders = sorted(
        module
        for module in imported
        if module.startswith("fpbench.adapters")
        or module.endswith("sourceafis_validation")
    )
    assert offenders == [], f"the shared input checks depend on an algorithm: {offenders}"
